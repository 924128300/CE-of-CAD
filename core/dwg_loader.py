"""DWG 读取：ezdwg 高层 API + 块参照递归展开。"""
from __future__ import annotations

import math
import os
import time
from collections import defaultdict
from typing import Callable

from .geometry import Point3
from .model import DrawingModel, EntityRecord, LayerInfo

try:
    import ezdwg
    from ezdwg import raw as ezdwg_raw
    from ezdwg import _aci
except Exception:  # pragma: no cover - 依赖缺失时给出可读提示
    ezdwg = None
    ezdwg_raw = None
    _aci = None


class DwgLoadError(RuntimeError):
    pass


# 可选中的实体类型
PATH_TYPES = {"LINE", "LWPOLYLINE", "POLYLINE_2D", "POLYLINE_3D", "ARC", "CIRCLE"}
POINT_TYPES = {"POINT"}
SUPPORTED_TYPES = PATH_TYPES | POINT_TYPES
# 枚举时只解码需要的类型：文字、填充、标注等类型解码很慢，且本来就不参与绘图
ENUM_TYPES = tuple(sorted(SUPPORTED_TYPES | {"INSERT", "MINSERT"}))

MAX_BLOCK_DEPTH = 8
SYNTHETIC_BASE = 1_000_000_000


def _aci_color(index: int | None) -> tuple[int, int, int]:
    if _aci is None:
        return (220, 220, 220)
    palette = _aci.aci_palette()
    return palette.get(int(index or 7), (220, 220, 220))


def _resolve_color(dxf: dict) -> tuple[int, int, int]:
    true_color = dxf.get("resolved_true_color")
    if true_color is None:
        true_color = dxf.get("true_color")
    if true_color:
        try:
            if _aci is not None:
                return _aci.true_color_to_rgb(int(true_color))
            value = int(true_color)
            return ((value >> 16) & 0xFF, (value >> 8) & 0xFF, value & 0xFF)
        except Exception:
            pass
    return _aci_color(dxf.get("resolved_color_index") or dxf.get("color_index"))


def _as_point(value) -> Point3 | None:
    if value is None:
        return None
    try:
        x, y = float(value[0]), float(value[1])
        z = float(value[2]) if len(value) > 2 else 0.0
    except (TypeError, ValueError, IndexError):
        return None
    if not (math.isfinite(x) and math.isfinite(y) and math.isfinite(z)):
        return None
    return (x, y, z)


def _arc_to_path(center: Point3, radius: float, start_deg: float, end_deg: float):
    """把 ARC 转成两点 + bulge 的路径。角度为度，逆时针。"""
    sweep = (float(end_deg) - float(start_deg)) % 360.0
    if sweep <= 1e-12:
        sweep = 360.0
    cx, cy, cz = center
    a0 = math.radians(float(start_deg))
    a1 = math.radians(float(start_deg) + sweep)
    p0 = (cx + radius * math.cos(a0), cy + radius * math.sin(a0), cz)
    p1 = (cx + radius * math.cos(a1), cy + radius * math.sin(a1), cz)
    bulge = math.tan(math.radians(sweep) / 4.0)
    return [p0, p1], [bulge]


def _circle_to_path(center: Point3, radius: float):
    cx, cy, cz = center
    p0 = (cx + radius, cy, cz)
    p1 = (cx - radius, cy, cz)
    return [p0, p1], [1.0, 1.0]


def _entity_path(entity) -> tuple[str, list[Point3], list[float], bool] | None:
    """返回 (kind, points, bulges, closed)；不支持返回 None。"""
    dxftype = str(entity.dxftype)
    dxf = entity.dxf
    if dxftype == "LINE":
        start = _as_point(dxf.get("start"))
        end = _as_point(dxf.get("end"))
        if not start or not end:
            return None
        return "path", [start, end], [], False
    if dxftype in ("LWPOLYLINE", "POLYLINE_2D"):
        elevation = float(dxf.get("elevation") or 0.0)
        raw_points = dxf.get("points") or []
        points: list[Point3] = []
        for item in raw_points:
            p = _as_point(item)
            if p is None:
                continue
            points.append((p[0], p[1], p[2] + elevation if p[2] == 0.0 else p[2]))
        if len(points) < 2:
            return None
        bulges = [float(b or 0.0) for b in (dxf.get("bulges") or [])]
        return "path", points, bulges, bool(dxf.get("closed"))
    if dxftype == "POLYLINE_3D":
        points = [p for p in (_as_point(item) for item in (dxf.get("points") or [])) if p]
        if len(points) < 2:
            return None
        return "path", points, [], bool(dxf.get("closed"))
    if dxftype == "ARC":
        center = _as_point(dxf.get("center"))
        radius = float(dxf.get("radius") or 0.0)
        if not center or radius <= 0.0:
            return None
        points, bulges = _arc_to_path(center, radius, float(dxf.get("start_angle")),
                                      float(dxf.get("end_angle")))
        return "path", points, bulges, False
    if dxftype == "CIRCLE":
        center = _as_point(dxf.get("center"))
        radius = float(dxf.get("radius") or 0.0)
        if not center or radius <= 0.0:
            return None
        points, bulges = _circle_to_path(center, radius)
        return "path", points, bulges, True
    if dxftype == "POINT":
        location = _as_point(dxf.get("location"))
        if not location:
            return None
        return "point", [location], [], False
    return None


def _transform_point(p: Point3, insert: Point3, sx: float, sy: float, sz: float,
                     cos_r: float, sin_r: float, base: Point3) -> Point3:
    dx = (p[0] - base[0]) * sx
    dy = (p[1] - base[1]) * sy
    return (
        insert[0] + dx * cos_r - dy * sin_r,
        insert[1] + dx * sin_r + dy * cos_r,
        insert[2] + (p[2] - base[2]) * sz,
    )


class _EntityFactory:
    def __init__(self) -> None:
        self._synthetic = SYNTHETIC_BASE

    def next_handle(self) -> int:
        self._synthetic += 1
        return self._synthetic

    def build(self, entity, layer: str, color, points, bulges, closed, kind,
              source_handle: int) -> EntityRecord:
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        bbox = (min(xs), min(ys), max(xs), max(ys)) if xs else (0.0, 0.0, 0.0, 0.0)
        return EntityRecord(
            handle=self.next_handle(),
            dxftype=str(entity.dxftype),
            layer=layer,
            color=color,
            points=points,
            source_handle=source_handle or int(getattr(entity, "handle", 0) or 0),
            bulges=list(bulges),
            closed=bool(closed),
            kind=kind,
            bbox=bbox,
        )


def load_dwg(path: str,
             progress: Callable[[str, int], None] | None = None) -> DrawingModel:
    if ezdwg is None:
        raise DwgLoadError("缺少 ezdwg 依赖，请先执行 pip install ezdwg==0.19.0")
    if not os.path.isfile(path):
        raise DwgLoadError(f"文件不存在：{path}")

    def report(stage: str, percent: int) -> None:
        if progress:
            progress(stage, percent)

    report("读取文件", 5)
    t0 = time.perf_counter()
    try:
        doc = ezdwg.read(path)
    except Exception as exc:  # noqa: BLE001
        message = str(exc)
        lowered = message.lower()
        if "password" in lowered or "encrypt" in lowered:
            raise DwgLoadError("该 DWG 已加密，需要密码或人工解锁后才能读取。") from exc
        if "version" in lowered:
            raise DwgLoadError(f"不支持该 DWG 版本：{message}") from exc
        raise DwgLoadError(f"无法解析 DWG：{message or exc.__class__.__name__}") from exc

    model = DrawingModel(path=path, version=str(getattr(doc, "version", "") or ""))
    insunits = getattr(doc, "insunits", None)
    if insunits is None:
        try:
            insunits = doc.header_variables().get("$INSUNITS")
        except Exception:
            insunits = 0
    try:
        model.insunits = int(insunits or 0)
    except (TypeError, ValueError):
        model.insunits = 0

    report("读取块表", 15)
    block_meta: dict[int, dict] = {}
    name_to_handle: dict[str, int] = {}
    if ezdwg_raw is not None:
        try:
            for item in ezdwg_raw.decode_write_blocks(path):
                handle = int(item.get("handle") or 0)
                if not handle:
                    continue
                block_meta[handle] = item
                name = str(item.get("name") or "")
                if name:
                    name_to_handle[name] = handle
        except Exception as exc:  # noqa: BLE001
            model.warnings.append(f"块表读取不完整：{exc}")

    # 图层
    layer_by_handle: dict[int, LayerInfo] = {}
    try:
        for layer in doc.layers:
            info = LayerInfo(
                name=str(layer.name or "0"),
                color=(_aci_color(layer.color) if layer.true_color is None
                       else _resolve_color({"true_color": layer.true_color})),
                visible=bool(layer.on) and not bool(layer.frozen),
            )
            layer_by_handle[int(layer.handle)] = info
            model.layers[info.name] = info
    except Exception as exc:  # noqa: BLE001
        model.warnings.append(f"图层读取失败：{exc}")

    report("建立块内实体索引", 25)
    # 顶层实体直接取模型空间：entmode + owner 的组合口径由 ezdwg 判定，
    # 自己按 entity_placement 分类会把匿名块（*D 之类）里的实体误判或漏判。
    try:
        top_level = list(doc.modelspace().iter_entities(types=ENUM_TYPES))
    except Exception as exc:  # noqa: BLE001
        raise DwgLoadError(f"实体遍历失败：{exc}") from exc

    block_entities: dict[int, list] = defaultdict(list)
    if ezdwg_raw is not None and any(
            str(getattr(ent, "dxftype", "")) in ("INSERT", "MINSERT") for ent in top_level):
        # 只有图纸里真的存在块参照时才需要全量枚举块内实体；
        # 无块图纸可跳过这次遍历（大图约省掉四分之一的解析时间）。
        try:
            all_entities = list(doc.entities().iter_entities(types=ENUM_TYPES))
        except Exception as exc:  # noqa: BLE001
            all_entities = []
            model.warnings.append(f"块内实体读取不完整：{exc}")
        for ent in all_entities:
            try:
                placement = doc.entity_placement(int(getattr(ent, "handle", 0) or 0))
            except Exception:
                placement = None
            if placement and placement[0] == 0 and placement[1]:
                block_entities[int(placement[1])].append(ent)

    if not top_level:
        model.warnings.append("模型空间没有实体，已尝试使用图纸空间内容。")
        try:
            top_level = list(doc.paperspace().iter_entities(types=ENUM_TYPES))
        except Exception:
            top_level = []

    report("解析实体", 45)
    factory = _EntityFactory()
    model_space_handle = name_to_handle.get("*Model_Space")
    expanded_count = 0

    def entity_layer_color(ent) -> tuple[str, tuple[int, int, int]]:
        dxf = ent.dxf
        layer_info = layer_by_handle.get(int(dxf.get("layer_handle") or 0))
        layer_name = layer_info.name if layer_info else "0"
        if int(dxf.get("resolved_color_index") or 0) == 256 and layer_info:
            color = layer_info.color
        elif dxf.get("resolved_true_color") is None and dxf.get("resolved_color_index") in (None, 256) \
                and layer_info:
            color = layer_info.color
        else:
            color = _resolve_color(dxf)
        return layer_name, color

    def add_entity(ent, depth: int, insert: Point3 | None, scale: tuple[float, float, float],
                   rotation_deg: float, base: Point3, source_handle: int) -> None:
        nonlocal expanded_count
        dxftype = str(ent.dxftype)
        if dxftype in ("INSERT", "MINSERT"):
            if depth >= MAX_BLOCK_DEPTH:
                return
            name = str(ent.dxf.get("name") or "")
            handle = name_to_handle.get(name)
            if not handle or handle == model_space_handle:
                return
            meta = block_meta.get(handle, {})
            block_base = _as_point(meta.get("base_point")) or (0.0, 0.0, 0.0)
            ins = _as_point(ent.dxf.get("insert")) or (0.0, 0.0, 0.0)
            sx = float(ent.dxf.get("xscale") or 1.0)
            sy = float(ent.dxf.get("yscale") or 1.0)
            sz = float(ent.dxf.get("zscale") or 1.0)
            rot = float(ent.dxf.get("rotation") or 0.0) + rotation_deg
            # 组合变换：先应用父变换到插入点，再叠加子变换
            if insert is not None:
                ins = _transform_point(ins, insert, scale[0], scale[1], scale[2],
                                       math.cos(math.radians(rotation_deg)),
                                       math.sin(math.radians(rotation_deg)), base)
                sx *= scale[0]
                sy *= scale[1]
                sz *= scale[2]
            for child in block_entities.get(handle, []):
                add_entity(child, depth + 1, ins, (sx, sy, sz), rot, block_base, source_handle)
            expanded_count += 1
            return

        path = _entity_path(ent)
        if path is None:
            return
        kind, points, bulges, closed = path
        layer_name, color = entity_layer_color(ent)
        if insert is not None:
            cos_r = math.cos(math.radians(rotation_deg))
            sin_r = math.sin(math.radians(rotation_deg))
            uniform = abs(scale[0] - scale[1]) <= 1e-12
            points = [_transform_point(p, insert, scale[0], scale[1], scale[2],
                                      cos_r, sin_r, base) for p in points]
            if bulges and not (uniform and scale[0] > 0 and scale[1] > 0):
                # 非均匀缩放或镜像时圆弧不再是圆弧，退化为密折线
                from .geometry import polyline_render_points
                points = polyline_render_points(points, bulges, closed)
                bulges = []
        record = factory.build(ent, layer_name, color, points, bulges, closed, kind,
                               source_handle or int(getattr(ent, "handle", 0) or 0))
        if record.kind == "point":
            record.bbox = (points[0][0], points[0][1], points[0][0], points[0][1])
        else:
            # 预先生成渲染折线，避免首帧在绘制线程里做大量三角函数
            record.render_points
        model.entities.append(record)
        layer_info = model.layers.get(layer_name)
        if layer_info is not None:
            layer_info.entity_count += 1

    for ent in top_level:
        add_entity(ent, 0, None, (1.0, 1.0, 1.0), 0.0, (0.0, 0.0, 0.0),
                   int(getattr(ent, "handle", 0) or 0))

    report("统计范围", 90)
    model.insert_count = expanded_count
    if model.entities:
        xs0 = min(e.bbox[0] for e in model.entities)
        ys0 = min(e.bbox[1] for e in model.entities)
        xs1 = max(e.bbox[2] for e in model.entities)
        ys1 = max(e.bbox[3] for e in model.entities)
        model.bbox = (xs0, ys0, xs1, ys1)
        model.origin = ((xs0 + xs1) / 2.0, (ys0 + ys1) / 2.0, 0.0)
    else:
        model.warnings.append("没有找到可显示的实体，请确认图纸内容位于模型空间。")

    model._by_handle = {e.handle: e for e in model.entities}
    model.elapsed = time.perf_counter() - t0
    report("完成", 100)
    return model

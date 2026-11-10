"""纯几何与数值格式化工具。

所有坐标一律使用 Python float（IEEE-754 双精度），不做 float32 降级。
方位角口径：测量方位角，正北（+Y）起顺时针，范围 [0, 360)。
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP, localcontext

Point3 = tuple[float, float, float]

# Excel 数值最多保留 15 位有效数字，超过后会被静默截断或转成科学计数
EXCEL_MAX_SIG_DIGITS = 15
EXCEL_TEXT_THRESHOLD = 1e11

COORD_DECIMALS = 4
LENGTH_DECIMALS = 3
DMS_SECOND_DECIMALS = 0


# ---------------------------------------------------------------- 基础向量


def distance(a: Point3, b: Point3) -> float:
    """两点三维距离，math.hypot 内部做防溢出处理。"""
    return math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2])


def planar_distance(a: Point3, b: Point3) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def azimuth(a: Point3, b: Point3) -> float:
    """测量方位角：正北起顺时针，单位度，范围 [0, 360)。

    CAD 平面中 +X 为东、+Y 为北，因此 atan2(dx, dy)。
    """
    dx = b[0] - a[0]
    dy = b[1] - a[1]
    if dx == 0.0 and dy == 0.0:
        return 0.0
    angle = math.degrees(math.atan2(dx, dy))
    angle %= 360.0
    if angle == 360.0:
        angle = 0.0
    return angle


def normalize_angle(deg: float) -> float:
    value = deg % 360.0
    if value == 360.0:
        value = 0.0
    return value


def point_segment_distance_2d(p: Point3, a: Point3, b: Point3) -> float:
    """点到二维线段的最短距离。"""
    ax, ay = a[0], a[1]
    bx, by = b[0], b[1]
    px, py = p[0], p[1]
    vx, vy = bx - ax, by - ay
    length_sq = vx * vx + vy * vy
    if length_sq <= 0.0:
        return math.hypot(px - ax, py - ay)
    t = ((px - ax) * vx + (py - ay) * vy) / length_sq
    if t < 0.0:
        t = 0.0
    elif t > 1.0:
        t = 1.0
    return math.hypot(px - (ax + t * vx), py - (ay + t * vy))


# ---------------------------------------------------------------- 凸度圆弧

@dataclass(frozen=True, slots=True)
class ArcInfo:
    """bulge 表示的一段圆弧（仅有二维信息，Z 按端点线性插值）。"""

    center: tuple[float, float]
    radius: float
    start_angle: float
    sweep: float  # 带符号，正为逆时针
    start: Point3
    end: Point3

    @property
    def arc_length(self) -> float:
        return abs(self.sweep) * self.radius


def bulge_to_arc(p0: Point3, p1: Point3, bulge: float) -> ArcInfo | None:
    """把一段 bulge（凸度）圆弧转成圆心、半径、起始角与圆心角。

    - ``bulge``：DXF 凸度 = tan(圆心角 / 4)，正为逆时针、负为顺时针，0 或弦长为 0 时返回 ``None``
    - 半径由弦长与圆心角反算，``|bulge| > 1`` 表示优弧，圆心落在弦的另一侧
    - ``sweep`` 带符号保存方向，调用方据此决定离散点的走向
    """
    if not bulge:
        return None
    chord = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
    if chord <= 0.0:
        return None
    theta = 4.0 * math.atan(bulge)  # 圆心角，带符号
    radius = chord / (2.0 * math.sin(abs(theta) / 2.0))
    # 弦中点
    mx = (p0[0] + p1[0]) / 2.0
    my = (p0[1] + p1[1]) / 2.0
    # 弦的单位法向（左法向）
    ux = (p1[0] - p0[0]) / chord
    uy = (p1[1] - p0[1]) / chord
    nx, ny = -uy, ux
    offset = chord * (1.0 - bulge * bulge) / (4.0 * bulge) if bulge else 0.0
    cx = mx + nx * offset
    cy = my + ny * offset
    start_angle = math.atan2(p0[1] - cy, p0[0] - cx)
    return ArcInfo(
        center=(cx, cy),
        radius=radius,
        start_angle=start_angle,
        sweep=theta,
        start=p0,
        end=p1,
    )


def arc_segment_length(p0: Point3, p1: Point3, bulge: float) -> float:
    """圆弧段三维长度（弧长 + Z 差），bulge 为 0 时退化为直线距离。"""
    if not bulge:
        return distance(p0, p1)
    arc = bulge_to_arc(p0, p1, bulge)
    if arc is None:
        return distance(p0, p1)
    planar = arc.arc_length
    dz = p1[2] - p0[2]
    return math.hypot(planar, dz)


def arc_points(p0: Point3, p1: Point3, bulge: float, max_step_deg: float = 5.0,
               max_sagitta: float = 0.0) -> list[Point3]:
    """圆弧离散点（含起点与终点）。max_sagitta > 0 时按弦高进一步细分。"""
    arc = bulge_to_arc(p0, p1, bulge)
    if arc is None:
        return [p0, p1]
    sweep_abs = abs(arc.sweep)
    if max_sagitta > 0.0 and arc.radius > max_sagitta:
        step_by_sagitta = 2.0 * math.acos(max(-1.0, 1.0 - max_sagitta / arc.radius))
        step = min(math.radians(max_step_deg), max(step_by_sagitta, 1e-4))
    else:
        step = math.radians(max_step_deg)
    count = max(1, int(math.ceil(sweep_abs / step)))
    count = min(count, 720)
    sign = 1.0 if arc.sweep >= 0 else -1.0
    cx, cy = arc.center
    dz = (p1[2] - p0[2]) / count
    points: list[Point3] = [p0]
    for i in range(1, count):
        ang = arc.start_angle + sign * sweep_abs * (i / count)
        points.append((cx + arc.radius * math.cos(ang),
                       cy + arc.radius * math.sin(ang),
                       p0[2] + dz * i))
    points.append(p1)
    return points


def polyline_render_points(points: list[Point3], bulges: list[float], closed: bool,
                           max_step_deg: float = 5.0) -> list[Point3]:
    """把带 bulge 的折线展开为用于绘制的密集折线。"""
    if not points:
        return []
    if len(points) == 1:
        return list(points)
    result: list[Point3] = [points[0]]
    seg_count = len(points) - 1 + (1 if closed else 0)
    for i in range(seg_count):
        a = points[i]
        b = points[(i + 1) % len(points)]
        b_val = bulges[i] if i < len(bulges) else 0.0
        if b_val:
            pts = arc_points(a, b, b_val, max_step_deg=max_step_deg)
            result.extend(pts[1:])
        else:
            result.append(b)
    return result


# ---------------------------------------------------------------- 路径段

@dataclass(slots=True)
class PathSegment:
    """一段路径（直线或圆弧），保存精确长度与弦方位角。"""

    start: Point3
    end: Point3
    bulge: float = 0.0
    length: float = 0.0
    azimuth: float = 0.0
    is_arc: bool = False

    @classmethod
    def build(cls, start: Point3, end: Point3, bulge: float = 0.0) -> "PathSegment":
        return cls(
            start=start,
            end=end,
            bulge=bulge,
            length=arc_segment_length(start, end, bulge),
            azimuth=azimuth(start, end),
            is_arc=bool(bulge),
        )


def reverse_path(points: list[Point3], bulges: list[float],
                 closed: bool) -> tuple[list[Point3], list[float]]:
    """反转路径方向：点序倒置，圆弧 bulge 取反并重新配对。

    圆弧段的 bulge 描述的是「从段起点到终点，弧向右/向左鼓出」；反向走同一段弧，
    鼓出方向相反，因此取负号即可保持几何形状不变。闭合路径多出的一条闭合段
    也要跟着反向。
    """
    n = len(points)
    if n < 2:
        return list(points), list(bulges)
    reversed_points = list(reversed(points))
    new_bulges = [
        -bulges[n - 2 - j] if n - 2 - j < len(bulges) else 0.0
        for j in range(n - 1)
    ]
    if closed:
        new_bulges.append(-bulges[n - 1] if n - 1 < len(bulges) else 0.0)
    return reversed_points, new_bulges


def build_segments(points: list[Point3], bulges: list[float], closed: bool) -> list[PathSegment]:
    if len(points) < 2:
        return []
    count = len(points) - 1 + (1 if closed else 0)
    segments: list[PathSegment] = []
    for i in range(count):
        a = points[i]
        b = points[(i + 1) % len(points)]
        bulge = bulges[i] if i < len(bulges) else 0.0
        segments.append(PathSegment.build(a, b, bulge))
    return segments


def total_length(segments: list[PathSegment]) -> float:
    return math.fsum(s.length for s in segments)




def segment_planar_length(seg: PathSegment) -> float:
    """平面长度：圆弧取弧长，直线取弦长。"""
    if seg.bulge:
        arc = bulge_to_arc(seg.start, seg.end, seg.bulge)
        if arc is not None:
            return arc.arc_length
    return planar_distance(seg.start, seg.end)


def planar_total(segments: list[PathSegment]) -> float:
    return math.fsum(segment_planar_length(s) for s in segments)


def walk_path_points(points: list[Point3], bulges: list[float], closed: bool,
                     step: float, include_vertices: bool) -> list[tuple[Point3, int, float]]:
    """沿路径生成导出点，返回 ``(点, 所属段序号, 该点之前的累计平面长度)``。

    - 累计长度一律取**平面**长度：直线取两点水平距离，圆弧取弧长（不是弦长）
    - ``include_vertices=True``：只返回原始顶点，闭合线去掉与起点重合的末点
    - ``include_vertices=False``：每段按 ``step`` 均分插值，段内不会跨段累计步长，
      因此相邻导出点的间距可能小于 ``step``（按段取整）
    - 圆弧段沿真实弧线取点，Z 按段两端线性插值
    - ``step <= 0`` 时退化为每段只取端点
    """
    if not points:
        return []
    segments = build_segments(points, bulges, closed)
    if not segments:
        return [(points[0], 0, 0.0)]

    result: list[tuple[Point3, int, float]] = []
    cumulative = 0.0

    if include_vertices:
        for i, seg in enumerate(segments):
            result.append((seg.start, i, cumulative))
            cumulative += segment_planar_length(seg)
        result.append((segments[-1].end, len(segments) - 1, cumulative))
        if closed and len(result) > 1 and result[-1][0] == result[0][0]:
            result.pop()
        return result

    for i, seg in enumerate(segments):
        if i == 0:
            result.append((seg.start, 0, 0.0))
        planar = segment_planar_length(seg)
        count = max(1, int(math.ceil(planar / step))) if step > 0 else 1
        arc = bulge_to_arc(seg.start, seg.end, seg.bulge) if seg.bulge else None
        for k in range(1, count + 1):
            t = k / count
            if arc is not None:
                sign = 1.0 if arc.sweep >= 0 else -1.0
                ang = arc.start_angle + sign * abs(arc.sweep) * t
                point: Point3 = (
                    arc.center[0] + arc.radius * math.cos(ang),
                    arc.center[1] + arc.radius * math.sin(ang),
                    seg.start[2] + (seg.end[2] - seg.start[2]) * t,
                )
            else:
                point = (
                    seg.start[0] + (seg.end[0] - seg.start[0]) * t,
                    seg.start[1] + (seg.end[1] - seg.start[1]) * t,
                    seg.start[2] + (seg.end[2] - seg.start[2]) * t,
                )
            result.append((point, i, cumulative + planar * t))
        cumulative += planar

    if closed and len(result) > 1 and result[-1][0] == result[0][0]:
        result.pop()
    return result


# ---------------------------------------------------------------- 格式化


def _quantize(value: float, decimals: int) -> Decimal:
    quantum = Decimal(1).scaleb(-decimals)
    with localcontext() as ctx:
        ctx.prec = 40
        return Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP)


def round_decimal(value: float, decimals: int) -> float:
    """十进制四舍五入后转回 float，用于写入 Excel 的值本身。"""
    return float(_quantize(value, decimals))


def format_decimal(value: float, decimals: int) -> str:
    """固定小数位字符串，不出现科学计数法，也不输出 -0.0000。"""
    quantized = _quantize(value, decimals)
    if quantized == 0:
        quantized = quantized.copy_abs()
    return format(quantized, f".{decimals}f")


def format_coord(value: float) -> str:
    return format_decimal(value, COORD_DECIMALS)


def format_length(value: float) -> str:
    return format_decimal(value, LENGTH_DECIMALS)


def decimal_to_dms(value: float, second_decimals: int = DMS_SECOND_DECIMALS
                   ) -> tuple[int, int, Decimal]:
    """十进制度转度分秒，按十进制四舍五入到指定秒小数位。"""
    value = normalize_angle(value)
    quantum = Decimal(1).scaleb(-second_decimals)
    with localcontext() as ctx:
        ctx.prec = 40
        total_seconds = (Decimal(str(value)) * 3600).quantize(quantum, rounding=ROUND_HALF_UP)
        if total_seconds >= Decimal(360 * 3600):
            total_seconds = Decimal(0)
        degrees = int(total_seconds // 3600)
        remainder = total_seconds - Decimal(degrees * 3600)
        minutes = int(remainder // 60)
        seconds = remainder - Decimal(minutes * 60)
    return degrees, minutes, seconds


def format_dms(value: float, second_decimals: int = DMS_SECOND_DECIMALS) -> str:
    """格式化为 162°00′00″ 形式；默认秒为整数，秒位补足两位。"""
    degrees, minutes, seconds = decimal_to_dms(value, second_decimals)
    width = 2 if second_decimals == 0 else second_decimals + 3
    second_text = format(seconds, f"0{width}.{second_decimals}f")
    return f"{degrees}°{minutes:02d}′{second_text}″"


def excel_cell_value(value: float, decimals: int) -> float | str:
    """按 Excel 精度能力返回数值或文本。

    Excel 数值上限约 15 位有效数字；|值| 超过 1e11 时转文本，避免静默截断。
    """
    if abs(value) >= EXCEL_TEXT_THRESHOLD:
        return format_decimal(value, decimals)
    return round_decimal(value, decimals)


def slope_ratio(z0: float, z1: float, horizontal: float) -> float | None:
    """相邻两点坡度：高差 ÷ 水平距离，返回比值（0.01 即 1%）。

    - 高差与水平距离都取**图纸原值**（同一单位），因此与比例尺、坐标单位无关
    - 上坡为正、下坡为负，与现场计算表一致（-0.01 表示 -1%）
    - 水平距离为 0（两点重合）时返回 ``None``，由调用方留空
    """
    if horizontal <= 0:
        return None
    return (z1 - z0) / horizontal

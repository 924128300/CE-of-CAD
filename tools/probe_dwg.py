"""只读诊断脚本：探测 ezdwg 对真实 DWG 的解析能力。

用法:
    python tools/probe_dwg.py <file.dwg> [--limit N]

输出: DWG 版本、单位、图层、实体类型计数、坐标范围、块参照嵌套、解析耗时。
"""
from __future__ import annotations

import argparse
import sys
import time
import traceback
from collections import Counter


def describe_api(doc) -> None:
    print("== doc API ==")
    names = [n for n in dir(doc) if not n.startswith("_")]
    print("doc attrs:", ", ".join(names[:60]))

    msp = doc.modelspace()
    print("== modelspace API ==")
    print("msp attrs:", ", ".join([n for n in dir(msp) if not n.startswith("_")][:40]))

    ents = list(msp)
    print(f"modelspace entity count: {len(ents)}")
    if not ents:
        return

    types = Counter()
    for e in ents:
        try:
            t = e.dxftype() if callable(getattr(e, "dxftype", None)) else e.dxftype
        except Exception:
            t = "?"
        types[str(t)] += 1
    print("entity types:", dict(types.most_common(20)))

    sample = {}
    for e in ents:
        t = e.dxftype() if callable(getattr(e, "dxftype", None)) else e.dxftype
        if t not in sample:
            sample[t] = e
        if len(sample) >= 8:
            break

    for t, e in sample.items():
        print(f"\n-- sample {t} --")
        print("handle:", getattr(e, "handle", None))
        dxf = getattr(e, "dxf", None)
        if dxf is None:
            continue
        for key in ("start", "end", "location", "center", "radius", "layer",
                    "elevation", "color", "bulge", "points", "flags", "name",
                    "insert", "rotation", "xscale", "yscale", "zscale", "extrusion"):
            try:
                if key in dxf:
                    print(f"  dxf[{key}] = {dxf[key]!r}")
            except Exception as exc:  # noqa: BLE001
                print(f"  dxf[{key}] -> {exc}")
        if hasattr(e, "get_points"):
            try:
                print("  get_points('xy') =", list(e.get_points("xy"))[:6])
            except Exception as exc:  # noqa: BLE001
                print("  get_points error:", exc)
        for key in ("vertices", "points", "attribs"):
            if hasattr(e, key):
                try:
                    print(f"  {key} =", len(getattr(e, key)))
                except Exception:
                    pass


def walk_blocks(doc, limit: int = 5) -> None:
    print("\n== blocks ==")
    try:
        blocks = doc.blocks
    except Exception as exc:  # noqa: BLE001
        print("doc.blocks unavailable:", exc)
        return
    print("blocks type:", type(blocks))
    names = [n for n in dir(blocks) if not n.startswith("_")]
    print("blocks attrs:", ", ".join(names[:30]))
    try:
        block_names = [b.name for b in blocks]
    except Exception:
        try:
            block_names = list(blocks.keys())
        except Exception as exc:  # noqa: BLE001
            print("cannot list blocks:", exc)
            return
    print("block count:", len(block_names))
    for name in block_names[:limit]:
        try:
            b = blocks.get(name)
            ents = list(b)
            print(f"  block {name!r}: {len(ents)} entities, first={ents[0].dxftype() if ents else None}")
        except Exception as exc:  # noqa: BLE001
            print(f"  block {name!r} error: {exc}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--api", action="store_true", help="打印 API 结构")
    args = ap.parse_args()

    import ezdwg

    print("ezdwg version:", getattr(ezdwg, "__version__", "unknown"))
    print("file:", args.path)

    t0 = time.perf_counter()
    try:
        doc = ezdwg.read(args.path)
    except Exception:
        traceback.print_exc()
        return 2
    t1 = time.perf_counter()
    print(f"read ok in {t1 - t0:.2f}s, doc type={type(doc).__name__}")

    for attr in ("version", "dwg_version", "units", "codepage"):
        try:
            print(f"doc.{attr} = {getattr(doc, attr)!r}")
        except Exception:
            pass

    try:
        hv = doc.header_variables()
        for key in ("$INSUNITS", "$EXTMIN", "$EXTMAX", "$MEASUREMENT", "$LUNITS", "$LUPREC"):
            if key in hv:
                print(f"header {key} = {hv[key]!r}")
    except Exception as exc:  # noqa: BLE001
        print("header_variables error:", exc)

    if args.api:
        describe_api(doc)
    walk_blocks(doc, args.limit)

    t2 = time.perf_counter()
    msp = doc.modelspace()
    xs: list[float] = []
    ys: list[float] = []
    zs: list[float] = []
    types = Counter()
    n = 0
    for e in msp:
        n += 1
        t = e.dxftype() if callable(getattr(e, "dxftype", None)) else e.dxftype
        types[str(t)] += 1
        for key in ("start", "end", "location", "center"):
            try:
                p = e.dxf[key]
            except Exception:
                continue
            if p is None:
                continue
            try:
                xs.append(float(p[0])); ys.append(float(p[1]))
                if len(p) > 2:
                    zs.append(float(p[2]))
            except Exception:
                pass
        if hasattr(e, "get_points"):
            try:
                for p in e.get_points("xy"):
                    xs.append(float(p[0])); ys.append(float(p[1]))
            except Exception:
                pass
    t3 = time.perf_counter()
    print(f"\niterated {n} entities in {t3 - t2:.2f}s")
    print("top types:", dict(types.most_common(25)))
    if xs:
        print(f"X range: {min(xs):.4f} .. {max(xs):.4f}  (span {max(xs) - min(xs):.3f})")
        print(f"Y range: {min(ys):.4f} .. {max(ys):.4f}  (span {max(ys) - min(ys):.3f})")
    if zs:
        print(f"Z range: {min(zs):.4f} .. {max(zs):.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

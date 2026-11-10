"""导出分段耗时诊断：样式 / 合并 / 写值 / 保存 各占多少。

用法：python tools/bench_export_parts.py [dwg路径] [实体数...]
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from openpyxl import Workbook  # noqa: E402

from core import section_sheet  # noqa: E402
from core.dwg_loader import load_dwg  # noqa: E402
from core.excel_export import ExportOptions, export_excel  # noqa: E402

DEFAULT_FILE = "D:/6月探采对比汇报资料/剖面图/EW000线.dwg"

def part_timing(path: str) -> None:
    print(f"===== {os.path.basename(path)} =====")
    t0 = time.perf_counter()
    model = load_dwg(path)
    print(f"解析: {(time.perf_counter() - t0) * 1000:.0f} ms | 实体 {len(model.entities)}")

    acc = {"style": 0.0, "merge": 0.0}
    orig_style = section_sheet._style_range
    orig_merge = section_sheet._merge

    def style_range(ws, r1, c1, r2, c2):
        start = time.perf_counter()
        orig_style(ws, r1, c1, r2, c2)
        acc["style"] += time.perf_counter() - start

    def merge(ws, r1, c1, r2, c2):
        start = time.perf_counter()
        orig_merge(ws, r1, c1, r2, c2)
        acc["merge"] += time.perf_counter() - start

    section_sheet._style_range = style_range
    section_sheet._merge = merge
    try:
        for count in (1, 20, 100):
            acc["style"] = acc["merge"] = 0.0
            out = os.path.join("tools", "screenshots", f"_parts_{count}.xlsx")
            t0 = time.perf_counter()
            export_excel(model, model.entities[:count],
                         ExportOptions(path=out, include_info=False))
            total = (time.perf_counter() - t0) * 1000
            print(f"导出 {count:>3} 条: {total:7.0f} ms | 样式 {acc['style']:6.0f} ms | "
                  f"合并 {acc['merge']:6.0f} ms | 其它 {total - acc['style'] - acc['merge']:6.0f} ms")

        # 只保存空工作簿的落盘成本
        wb = Workbook()
        wb.active["A1"] = "x"
        t0 = time.perf_counter()
        wb.save("tools/screenshots/_parts_empty.xlsx")
        print(f"空工作簿保存: {(time.perf_counter() - t0) * 1000:.0f} ms")
    finally:
        section_sheet._style_range = orig_style
        section_sheet._merge = orig_merge

def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_FILE
    part_timing(path)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

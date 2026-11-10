"""生成《代码清单与哈希》的客观数据表。

只统计与哈希，不修改任何源文件。输出直接写入 copyright/02_存证与保护/代码清单与哈希.md
用法：python tools/make_code_manifest.py
"""
from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "copyright" / "02_存证与保护" / "代码清单与哈希.md"

TARGETS = [
    ("app.py", "程序入口：应用初始化、主题、异常钩子、命令行传参"),
    ("core/model.py", "数据模型：点、图层、实体记录、图纸模型"),
    ("core/dwg_loader.py", "DWG 解析与块参照展开，实体转为内部几何"),
    ("core/geometry.py", "几何与格式化：距离、方位角、圆弧、度分秒、小数位口径"),
    ("core/spatial_index.py", "均匀网格空间索引：视口裁剪与拾取候选"),
    ("core/undo.py", "选择模型与撤销栈（快照式命令）"),
    ("core/section_sheet.py", "阶梯形坐标计算表的单元格布局、样式与合并"),
    ("core/excel_export.py", "导出流程：选项、单位与比例尺换算、原子保存、信息表"),
    ("ui/main_window.py", "主窗口：工具栏、动作、加载线程、导出与状态同步"),
    ("ui/canvas.py", "自绘图纸画布：绘制、缩放平移、拾取、框选、高亮与顶点标记"),
    ("ui/geometry_cache.py", "加载期构建的绘制缓存：局部坐标折线、粗细两级 LOD"),
    ("ui/property_panel.py", "当前要素属性面板与待导出列表（虚拟化表格模型）"),
    ("ui/layer_panel.py", "图层树与实体类型过滤"),
    ("ui/export_dialog.py", "导出对话框：路径、取点规则、坐标单位、比例尺"),
    ("ui/theme.py", "深色主题样式表"),
]


def count_lines(path: Path) -> tuple[int, int, int, int]:
    total = code = comment = blank = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        total += 1
        stripped = line.strip()
        if not stripped:
            blank += 1
        elif stripped.startswith("#"):
            comment += 1
        else:
            code += 1
    return total, code, comment, blank


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    rows = []
    totals = [0, 0, 0, 0]
    for rel, purpose in TARGETS:
        path = ROOT / rel
        if not path.exists():
            raise SystemExit(f"缺少文件：{rel}")
        total, code, comment, blank = count_lines(path)
        totals = [a + b for a, b in zip(totals, (total, code, comment, blank))]
        rows.append((rel, purpose, total, code, comment, blank, sha256(path)))

    lines = [
        "# 代码清单与哈希",
        "",
        f"生成日期：{date.today().isoformat()}",
        "",
        "本文件是**客观数据**（文件、行数、SHA-256），不是创作说明，可直接作为存证附件使用。",
        "行数口径：总行数含注释与空行；代码行指去掉空行与整行注释后的行数。",
        "",
        "## 一、清单",
        "",
        "| 文件 | 作用 | 总行 | 代码行 | 注释行 | 空行 | SHA-256 |",
        "| --- | --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for rel, purpose, total, code, comment, blank, digest in rows:
        lines.append(f"| `{rel}` | {purpose} | {total} | {code} | {comment} | {blank} | `{digest}` |")
    lines += [
        f"| **合计** | 15 个文件 | **{totals[0]}** | **{totals[1]}** | **{totals[2]}** | **{totals[3]}** | — |",
        "",
        "## 二、汇总",
        "",
        f"- 文件数：{len(rows)}",
        f"- 总行数：{totals[0]}",
        f"- 代码行：{totals[1]}",
        f"- 注释行：{totals[2]}",
        f"- 空行：{totals[3]}",
        f"- 按每页 50 行折算：约 {totals[0] / 50:.0f} 页（登记要求前后各 30 页，需不少于 3000 行）",
        "",
        "## 三、怎么用这份清单存证",
        "",
        "1. 把整个工程目录打成 zip（排除 `.venv`、`build*`、`dist`、`__pycache__`）。",
        "2. 对 zip 计算一次 SHA-256，记在 `存证操作指引.md` 的登记表里。",
        "3. 把 zip 与清单一起提交给时间戳/公证机构，取得时间戳证书或公证书。",
        "4. 以后每次交付或重大改动，重复一次，形成时间序列证据链。",
        "",
        "> 提示：本清单只覆盖主程序 15 个文件。`tests/` 与 `tools/` 属于开发辅助，",
        "> 若一并存证，请在 zip 说明中注明用途，避免与「程序」混淆。",
    ]
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"已生成 {OUT.relative_to(ROOT)}：{len(rows)} 个文件，{totals[0]} 行")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

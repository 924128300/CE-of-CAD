"""更新 README：点选模式的功能、操作、导出说明与项目结构。"""
from __future__ import annotations

import io
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGET = os.path.join(ROOT, "README.md")

PATCHES = [
    ('在 Windows 上预览 DWG 图纸，点选线或点，实时查看并导出 XYZ 坐标、长度与测量方位角到 Excel。',
     '在 Windows 上预览 DWG 图纸，按「线选」整条取线或按「点选」逐个端点取点，'
     '实时查看并导出 XYZ 坐标、长度与测量方位角到 Excel。'),
    ('''- 工具栏「多选」（`M`）开启后连续单击即可追加多条线，一次导出多条线到同一张 sheet，块与块之间空一行''',
     '''- 工具栏「多选」（`M`）开启后连续单击即可追加多条线，一次导出多条线到同一张 sheet，块与块之间空一行
- 工具栏「模式」可在「线选 / 点选」之间切换（`L` / `P`）：点选模式显示视口内各线条的端点（小十字），鼠标变十字，靠近端点自动吸附；左键按顺序加点、右键撤销上一个点、`Space` 结束本轮并开始下一轮、`Esc` 取消本轮，每一轮各占一块导出
- 点选序列与图纸中某条多段线**整条重合**时，该线改用虚线并做「由暗到明、由明到暗」的呼吸提示，提醒你这条线已经整条点完（可直接改用线选）'''),
    ('''| 选择 | 左键单击；`Ctrl`/`Shift` 加选；拖框批量选择 |
| 多选模式 | 工具栏「多选」（`M`）开启后，连续单击即可追加/取消选中，不必按 `Ctrl` |''',
     '''| 选择模式 | 工具栏「模式」选「线选」（`L`）或「点选」（`P`），默认线选 |
| 线选 | 左键单击；`Ctrl`/`Shift` 加选；拖框批量选择 |
| 多选模式 | 工具栏「多选」（`M`）开启后，连续单击即可追加/取消选中，不必按 `Ctrl` |
| 点选加点 | 点选模式下左键单击端点（12 px 内自动吸附到精确顶点），按单击顺序编号 |
| 点选撤点 | 点选模式下右键：撤销当前轮最后一个点 |
| 点选换轮 | `Space`：结束当前轮并开始下一轮（每轮导出一块） |
| 点选取消本轮 | `Esc`：放弃当前轮已点但未结束的点，已完成轮次保留 |'''),
    ('''| 平移 | 中键拖拽、右键拖拽、空格+左键拖拽 |''',
     '''| 平移 | 中键拖拽、右键拖拽、空格+左键拖拽；点选模式下右键用于撤点，请用中键或按住左键拖动 |'''),
    ('''- 一次可以选中任意多条线：**全部写在同一张 sheet 里**，每条线一块（9 行），块与块之间空一行；块的标题依次是 `线1/线2/…`，与「待导出列表」的顺序一致。''',
     '''- 一次可以选中任意多条线：**全部写在同一张 sheet 里**，每条线一块（9 行），块与块之间空一行；块的标题依次是 `线1/线2/…`，与「待导出列表」的顺序一致。
- 点选模式同理：每一轮点选写成一块，标题为 `点选1/点选2/…`，点号按单击顺序排列；点选块只导出被点中的点，不按间距插值，坐标就是图纸顶点的原值。'''),
    ('''    excel_export.py      Excel 导出
    undo.py              选择集与撤销栈''',
     '''    excel_export.py      Excel 导出
    pick_model.py        点选轮次、撤销、合成导出实体、整条重合判定
    undo.py              选择集与撤销栈'''),
    ('''    geometry_cache.py    加载线程内的折线转多边形与索引构建''',
     '''    geometry_cache.py    加载线程内的折线转多边形与索引构建
    snap_index.py        点选模式的端点捕捉索引（视口内顶点分格）'''),
    ('''  tools/verify_sheet_style.py  新旧表形写入一致性校验''',
     '''  tools/verify_sheet_style.py  新旧表形写入一致性校验
  tools/verify_point_select.py 点选模式真实图纸验证（吸附/分轮/呼吸/导出）'''),
    ('''测试覆盖方位角四象限与 0/360 边界、凸度圆弧长度、按间距采样、大坐标四位小数、Excel 文本降级与超 15 位有效数字、重复导出无残留、真实 DWG 加载与块展开。当前 30 项。''',
     '''测试覆盖方位角四象限与 0/360 边界、凸度圆弧长度、按间距采样、大坐标四位小数、Excel 文本降级与超 15 位有效数字、重复导出无残留、真实 DWG 加载与块展开，以及点选轮次、右键撤点、空格换轮、整条重合判定与点选导出。当前 55 项。'''),
    ('''- 454 KB 剖面图：解析约 0.5 s''',
     '''- 454 KB 剖面图：解析约 0.5 s
- 点选模式：6 689 实体 / 22 872 顶点（EW023 线）全图视图下，端点索引 < 5 ms、整帧 9.5 ms；放大后端点 3 588 个、整帧 1.7 ms'''),
]


def main() -> None:
    with io.open(TARGET, encoding="utf-8", newline="") as handle:
        raw = handle.read()
    crlf = "\r\n" in raw
    text = raw.replace("\r\n", "\n") if crlf else raw
    for index, (old, new) in enumerate(PATCHES, start=1):
        if text.count(old) != 1:
            raise SystemExit(f"锚点 {index} 匹配 {text.count(old)} 次：{old[:60]!r}")
        text = text.replace(old, new)
    if crlf:
        text = text.replace("\n", "\r\n")
    with io.open(TARGET, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)
    print("README.md 已更新")


if __name__ == "__main__":
    main()

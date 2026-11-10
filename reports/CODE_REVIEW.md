# DWG 坐标导出工具 — 代码审查报告

- 审查时间：2026-11-03
- 审查范围：`dwg_coord_exporter/` 下 `core/`（6 个模块）、`ui/`（8 个模块）、`app.py`、`tools/`、`tests/`，共 21 个 Python 文件、3659 行
- 审查方式：逐文件静态通读 + 针对可疑点写复现脚本 + pytest 回归 + 真实图纸（`EW000线.dwg`，6588 实体）端到端验证
- 技能：`/code-reviewer`（自带 `code_reviewer.py` / `report_generator.py` 已跑，结果见文末“静态扫描说明”）

## 一、结论

整体结构清晰：几何 / 模型 / 索引 / 解析 / 导出 / UI 分层明确，重计算都有缓存，精度口径（float64 + 十进制四舍五入）统一在 `core/geometry.py` 一处。

第一轮修复了 **2 个会直接影响使用正确性的功能缺陷**、3 处健壮性问题、3 处可维护性问题；第二轮处理了 8 条建议项（R-02、R-03、R-05、R-06、R-07、R-09、R-10、R-11）；第三轮按现场口径补上比例尺换算（R-01 的落地方式）并把平距改为弧长（R-04）。全部 11 条已闭环。

## 二、已修复问题

| 编号 | 级别 | 位置 | 问题 | 状态 |
|------|------|------|------|------|
| F-01 | 严重 | `core/spatial_index.py` `add/query_rect` | 超长实体按抽样格写入，放大后从画面和拾取中消失 | 已修复 |
| F-02 | 中 | `core/spatial_index.py` `query_rect` | 包围盒过滤用未归一化矩形，反向框选会全部漏判 | 已修复 |
| F-03 | 低 | `ui/canvas.py` `_pen` | 画笔缓存键不含线宽，不同线宽会互相覆盖（潜伏） | 已修复 |
| F-04 | 低 | `ui/canvas.py` `handles_in_rect` | `crossing` 参数语义与实际行为相反 | 已修复 |
| F-05 | 中 | `ui/canvas.py` `pick` | 悬停拾取对每个候选遍历全部折线点，无包围盒预筛 | 已修复 |
| F-06 | 严重 | `core/dwg_loader.py` `add_entity` | 闭合多段线的圆弧在均匀缩放下被错误退化成密折线；另有一处自赋值空分支 | 已修复 |
| F-07 | 中 | `ui/main_window.py` `closeEvent` | 解析线程超时未退出即关闭窗口，QThread 运行中被析构 | 已修复 |
| F-08 | 低 | `ui/main_window.py` | 版本号硬编码 1.0.0 与导出信息 1.1.0 不一致；选中后状态栏丢失文件名 | 已修复 |
| F-09 | 低 | `core/geometry.py` | 死代码与错误命名（`total_planar_length` 名为平面长度却累加三维长度） | 已清理 |

### F-01 空间索引漏检长实体（严重）

`GridIndex.add()` 对包围盒跨格数超过 4096 的实体，用 `step_x/step_y` 抽样写格，被跳过的格子查询不到该实体。矿山图纸里横贯全图的贯通巷道、剖面线正好属于这类实体，**放大到单格窗口后线会从画面上消失，也点不中**。

复现（修复前）：

```
GridIndex((0,0,1000,1000)) + add(1, (0,0,1000,1000))
query_rect(401,401,402,402) -> []      # 应为 [1]
query_rect(403,403,404,404) -> []
```

修复后：

```
query_rect(401,401,402,402) -> [1]
query_rect(403,403,404,404) -> [1]
```

实现改为：跨格过多的实体不写网格，统一放进 `_large` 列表，查询时并入候选再做包围盒过滤。既不会索引爆炸，也不会漏画。

真实图纸验证：视口压到 1.111 × 0.778 图纸单位（深缩放），最长实体（2333.7 × 588.4，handle 1000004983）仍在候选中，可绘制、可拾取。

### F-06 闭合多段线圆弧被错误退化（严重）

原判定：

```python
if bulges and uniform and scale[0] > 0 and scale[1] > 0 and not closed:
    pass                      # 保留圆弧
elif bulges:
    points = polyline_render_points(...)   # 退化成密折线
    bulges = []
elif uniform and (scale[0] < 0 or scale[1] < 0):
    bulges = [b for b in bulges]           # 自赋值，空操作
```

块参照里的闭合圆弧多段线（弯道、井巷环）即使只是平移+等比缩放，也会落到第二个分支被降级为折线，导致属性面板的平面长度从弧长变成折线近似，导出平距也随离散点走。第三个分支是纯空操作。

修复：条件改为 `if bulges and not (uniform and scale[0] > 0 and scale[1] > 0)`，只在非均匀缩放或镜像时退化。

### F-05 拾取性能

`pick()` 对每个候选实体遍历全部 `render_points` 求点线距离。候选通常只有几条，但一条上万点的多段线在悬停时每移动一帧就是上万次 Python 调用，容易掉帧。增加「包围盒 ± 容差」廉价预筛后再计算距离。

## 三、建议项处理结果（第二轮）

按你的要求处理了 R-02、R-03、R-05、R-06、R-07、R-09、R-10、R-11，R-01 与 R-04 涉及口径未动。

| 编号 | 位置 | 原问题 | 处理方式 |
|------|------|--------|----------|
| R-02 | `ui/property_panel.py` | 每次选择变化重建整表，并对每条实体算长度 | 改为 `SelectionTableModel`（`QAbstractTableModel`）：「总长」只在视图真正取该单元格时计算并缓存。实测全选 6588 条耗时 3 ms（原为逐条建 `QTableWidgetItem` + 全量算长度） |
| R-03 | `ui/canvas.py` / `ui/main_window.py` | 主线程为全图构建 `QPolygonF`，加载完还会顿一下 | 新增 `ui/geometry_cache.py`：折线转多边形、粗/细两级、空间索引全部在 `LoadWorker` 线程里做完，画布只接管指针；构建失败自动退回主线程，不影响加载 |
| R-05 | `core/dwg_loader.py` | 先全量遍历再取一次 modelspace，双份开销 | 只枚举需要的类型（`ENUM_TYPES`），并仅在图纸里存在 INSERT 时才做全量枚举。9.9 MB 图：枚举阶段 4.14 s → 1.68 s，整图解析 3.4 s。**modelspace 口径保持不变**，见下方说明 |
| R-06 | `core/excel_export.py` | `text_cells` 恒 0；路径识别只认 C:/D: | 删除 `text_cells`；路径判断改用正则（盘符、UNC、POSIX 都覆盖） |
| R-07 | `core/geometry.py` / `core/section_sheet.py` | `sample_points` 与生产路径重复；`excel_cell_value` 无人调用 | 删除 `sample_points`（合并进 `walk_path_points`），坐标写入改用 `excel_cell_value`：超过 Excel 15 位有效数字时写成文本，避免静默丢精度 |
| R-09 | `core/excel_export.py` | 直接写目标文件，失败会留下半个 xlsx | 新增 `_save_atomic`：先写 `*.part` 再 `os.replace`；失败时尽力清理临时文件并给出“文件可能被 Excel 占用”的提示 |
| R-10 | `ui/layer_panel.py` | 可选类型全不勾选时画布空白无提示 | 取消最后一个勾选时自动恢复，并显示“至少保留一类可选类型”提示 2.5 秒 |
| R-11 | 全局 | 注释覆盖率低 | 补齐 `bulge_to_arc`、`walk_path_points`、`write_block`、`build_geometry`、`SelectionTableModel` 的参数与口径说明 |

### 关于 R-05 的一处修正

第一版按 `entity_placement` 的 entmode 自行划分顶层实体，结果 9.9 MB 样图少了 7 个可绘实体：有 150 个实体（SOLID/LINE/POINT/MTEXT）虽然 `entmode=0`，owner 却是不在块表里的匿名块记录，`modelspace()` 仍把它们算作模型空间。改成自己判断后，这些实体进了“块内容”，而匿名块无法通过 INSERT 展开，等于从画面上消失。

最终方案是保留 `modelspace()` 作为顶层口径（ezdwg 自己用 entmode + owner 判定），只把**枚举范围**收窄到需要的类型，并按需（存在 INSERT 时）再枚举块内容。这样既没有改动显示结果，也拿到了大部分时间收益。

### 口径确认与第三轮改动

| 编号 | 结论与改动 |
|------|-----------|
| R-01 | 现场口径确认：1:1000 的图上 1 个单位就是 1 m。据此新增「比例尺」选项（1:100 / 1:200 / 1:500 / 1:1000 / 1:2000 / 1:5000，默认 1:1000），`平距(m) = 图上长度 × 分母 / 1000`；坐标仍按图纸原值输出，表头继续写 `(m)` |
| R-04 | 平距改用弧长：`walk_path_points` 的累计长度由三维长度改为**平面长度**（圆弧取弧长），相邻两点平距 = 累计长度之差 × 比例尺系数 |

新增口径说明：

- 比例尺只参与平距换算，不影响坐标、方位角
- 平距与 `$INSUNITS` 解耦：即使图纸标成毫米，1:1000 下图上 1 单位仍按 1 m 计
- 巷道长、坡度依旧留空；巷道长与平距同为米

## 四、静态扫描说明

`/code-reviewer` 技能自带脚本扫描结果：21 个文件，0 严重 / 21 一般 / 11 优化，注释覆盖率 1.17%。

逐条核对后为 **正则误报**，未按这些条目改动：

- “可能存在空指针风险：true_color / progress / name / msp_entities …”：脚本把 `if x is None`、`if not x` 这类正确判空写法里的变量名匹配成了“未判空使用”。
- “Python 文件名不符合 snake_case：`__init__.py`”：包初始化文件不适用该规则。

## 五、验证记录

| 项目 | 结果 |
|------|------|
| 单元测试 | `python -m pytest tests -q` → 30 passed（新增比例尺换算、圆弧弧长、导出信息记录比例尺） |
| 语法编译 | `python -m compileall core ui app.py` → 通过 |
| 真实图纸加载 | `EW000线.dwg` AC1021，6588 实体，块展开 380 |
| 深缩放可见性 | 视口 1.111×0.778 单位下最长实体在候选中、绘制命中、拾取返回其句柄 |
| 主窗口冒烟 | 标题/状态栏/选中/撤销/重做均正常，截图 `tools/screenshots/_review_ui.png` |
| 大图解析 | 9.9 MB、22611 实体的总图：枚举阶段 4.14 s → 1.68 s，整图 3.4 s |
| 大选择集 | 全选 6588 条：3 ms（列表改为按需计算，不再逐条建控件） |
| 导出 | 3 条线 6 个点生成 `_v120.xlsx`，合并单元格与参考表一致；失败路径给出“文件可能被 Excel 占用”并清理 `.part` |
| 比例尺 | 20 单位直线：1:500 → 10.000，1:1000 → 20.000，1:2000 → 40.000；坐标不随比例变化 |
| 弧长平距 | 半径 10 的半圆弧：平距 31.416（弦长 20.000） |
| 打包 | 见下一节 |

复现与验证脚本：`tools/verify_review_fixes.py`；本次补丁脚本：`tools/apply_review_fixes.py`（一次性记录，可删）。

## 六、打包结果

| 形式 | 路径 | 体积 | 实测 |
|---|---|---|---|
| 单文件版 | `dist/DWGCoordExporter.exe` | 46 MB | 启动并打开 `EW000线.dwg` 用时约 3.4 s，标题 `DWG 坐标导出工具 - EW000线.dwg`，无 `logs/crash.log` |
| 目录版 | `dist/DWGCoordExporter/` | 111 MB | 仍为修复前构建（11:03），重建被“禁止永久删除旧文件”拦住，需要先把旧目录移入回收站再重打 |

- 构建脚本：`build.bat`（目录版）、`build_onefile.bat`（单文件版）
- 单文件版内嵌 `ezdwg` 的 `_core.pyd` 与 Qt 平台插件，已在真机启动验证；`openpyxl` 为模块级导入，能正常启动即说明已打包

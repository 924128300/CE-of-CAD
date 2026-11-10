# 性能复核与优化记录（1.3.1）

对象：`dwg_coord_exporter`（DWG 坐标导出工具）
样图：`D:/6月探采对比汇报资料/剖面图/EW000线.dwg`（454 KB，6588 实体，380 块）、
`D:/D盘迁移文件/工作 Lonshi/Lonshi mining总图/龙溪矿总图9-11(1).dwg`（9.9 MB，22611 实体，79 块）

方法：先用 `tools/bench_perf.py` 记录基线（min-of-N，不含 tracemalloc），
按 cProfile 定位热点，单点改动后同条件复测，最后跑全量测试与既有验证脚本。
所有数字均为本机单次运行的最小值，仅供横向比较。

## 1. 基线（优化前）

| 指标 | EW000线 | 龙溪总图 |
|---|---|---|
| 解析 | 370 ms | 3673 ms |
| 构建绘制缓存 | 88 ms | 211 ms |
| 全图绘制 | 5.9 ms | 4.1 ms |
| 放大 20x / 200x | 1.3 / 1.2 ms | 0.4 / 0.4 ms |
| 拾取 60 点 | 1.3 ms | 0.3 ms |
| 选中最长实体后重绘 | 8.2 ms（626 点） | 10.4 ms（1220 点） |
| 导出 1 / 20 / 100 条 | 32 / 318 / 2369 ms | 33 / 351 / 2288 ms |

合成极端场景（`tools/bench_vertices.py`，单条超长多段线）：

| 点数 | 选中 | 选中且为当前要素（画顶点方块） |
|---|---|---|
| 2 000 | 3.0 ms | 8.6 ms |
| 20 000 | 17.1 ms | 83.5 ms |
| 100 000 | 90.9 ms | 416.7 ms |

## 2. 诊断

### 2.1 导出（最痛）

`cProfile` 导出 100 条线（优化前约 1.4 s，profiler 下 4.2 s）的累计耗时：

| 函数 | 累计 | 说明 |
|---|---|---|
| `section_sheet._merge` | 3.41 s | 合并单元格 |
| `openpyxl.worksheet.merge.MergedCellRange.format` | 2.82 s | 合并后逐格 `cell.border += Border(...)` |
| `openpyxl.styles.styleable.StyleDescriptor.__set__` | 2.99 s | 每次赋样式都要在集合里去重 |
| `section_sheet._style_range` | 0.57 s | 9 行 × 全列，每格 3 次样式赋值 |

两个叠加问题：

1. `merge_cells` → `_clean_merge_range` → `format()` 会给合并区的每条边逐格执行
   `cell.border += Border(side)`。`Border` 是 `Serialisable`，加一次就要递归
   `hash`/`__eq__`（一次赋值约 1800 次 `isinstance`），2000 个合并区就是 2.8 s。
   而本表整块用的是**同一套四边细线**，这个叠加是纯空操作。
2. `cell.font = FONT` 走 `StyleDescriptor`，每次都要把样式对象丢进集合去重
   （`hash(tuple(iter(self)))` 逐层递归到 Color）。每格 3 次、每块上千格，
   真正需要的只是「同一个 `StyleArray`」。

### 2.2 画布高亮与顶点标记

- `_draw_vertices` 对当前要素的**每个**顶点算屏幕坐标并 `drawRect`，不裁剪、
  不限量；10 万点要素单独就要 300 ms 以上，缩放/平移时每帧重算。
- `_full_polygon` 只缓存 64 条，超限**整表清空**；框选上千条长线时每帧反复重建，
  且 `drawPolyline` 回放十万级顶点本身就要约 90 ms。
- 底图绘制本来就按 `DISPLAY_POINT_LIMIT=600` 抽稀显示，高亮却用全量顶点，
  两者精度口径不一致。

### 2.3 解析

9.9 MB 总图 3.59 s 的构成（冷启动，分进程测量）：

| 环节 | 耗时 | 归属 |
|---|---|---|
| `modelspace().iter_entities()` | 2282 ms | ezdwg 的 Python 包装（逐实体构造 `Entity` + 附加颜色/线型） |
| `entities()`（块内容二次枚举） | 752 ms | 同上，其中真正需要的块内实体只有 1089 条 |
| Rust 解码（polyline/insert/style 等） | 约 1.1 s | 已包含在上面两项里 |
| 本程序侧（`_entity_path` / `build` / `_as_point`） | 约 0.6 s | — |

即 3.6 s 里约 2.3 s 花在 ezdwg 的实体对象构造上，本程序能压缩的只有约 0.6 s。

## 3. 改了什么

### 3.1 `core/section_sheet.py`：批量样式 + 快速合并

- 新增 `block_style(ws)`：整块样式只算一次，得到 `StyleArray`（字体/对齐/边框的
  索引元组），缓存到工作簿上；之后每格 `cell._style = StyleArray(style)` 直接拷数组，
  完全跳过样式去重。每格必须是独立数组，因为 `number_format` 是就地改数组的。
- `_merge()` 改为快速路径：登记 `MergedCellRange` 区域后，把非锚点格换成
  `MergedCell` 并赋予同一份样式数组，不再调用 `_clean_merge_range` 的边框重算。
  本表所有格边框一致，边缘格再叠边框是空操作，显示效果不变（见 4.2 比对）。
  保留 `try/except` 回退到公开 `ws.merge_cells`，防止 openpyxl 版本变化。

### 3.2 `ui/canvas.py`：高亮 LOD、顶点裁剪限量、折线缓存 LRU

- 新增 `_highlight_polygon()`：要素渲染点数超过 `HIGHLIGHT_POINT_LIMIT=20000` 时，
  高亮沿用底图的抽稀折线（最多 600 点）；否则仍用完整折线。口径与底图一致。
- `_draw_vertices()`：先按视口世界范围裁掉屏幕外的顶点，再按
  `VERTEX_MARKER_LIMIT=2000` 均匀抽样（并保证画出最后一个点）；同时把逐点
  `to_screen()` 调用改成内联算式，省掉十万次函数调用。
- `_full_polygon()`：缓存改为 LRU（命中时挪到末尾）+ 总点数预算
  `FULL_POLYGON_BUDGET=300000`，淘汰最久未用的条目，不再整表清空。

### 3.3 未改动的地方（附理由）

- **解析**：`include_styles=False` 实测会把 `layer_handle`、`color_index` 一并清空
  （22456 条里颜色 22303 条不一致），无法使用；绕开 `Entity` 包装需要复刻 ezdwg
  的私有 `_SIMPLE_ENTITY_REGISTRY`，风险收益不划算。故保持现状，靠加载线程 +
  进度提示保证不卡界面。
- **框选上千条的高亮批处理**：把选中集合合并成一个 `QPainterPath` 能再降到 5 ms
  量级，但要在选中变化时重建（一次 10–20 ms），当前 5000 条 25 ms（约 40 fps）
  已够用，暂不引入新的缓存失效路径。

## 4. 验证

### 4.1 复测

| 指标 | EW000线 前 → 后 | 龙溪总图 前 → 后 |
|---|---|---|
| 解析 | 370 → 349 ms | 3673 → 3586 ms |
| 构建绘制缓存 | 88 → 96 ms | 211 → 221 ms |
| 全图绘制 | 5.9 → 5.9 ms | 4.1 → 4.2 ms |
| 选中最长实体后重绘 | 8.2 → 7.7 ms | 10.4 → 7.9 ms |
| 导出 1 条 | 32 → 22 ms | 33 → 19 ms |
| 导出 20 条 | 318 → 30 ms | 351 → 29 ms |
| 导出 100 条 | 2369 → 115 ms | 2288 → 112 ms |

合成极端场景：

| 点数 | 优化前（选中 / 当前） | 优化后（选中 / 当前） |
|---|---|---|
| 2 000 | 3.0 / 8.6 ms | 2.8 / 4.8 ms |
| 20 000 | 17.1 / 83.5 ms | 16.8 / 20.7 ms |
| 100 000 | 90.9 / 416.7 ms | 2.8 / 12.6 ms |

框选重绘（龙溪总图）：100 条 5.1 ms、1000 条 21.9 ms、5000 条 24.7 ms
（优化前 1000 条 23.1 ms、5000 条 30.7 ms）。

解析、构建缓存的 ±10 ms 波动在噪声范围内，未做优化，符合预期。

### 4.2 输出一致性

`tools/verify_sheet_style.py` 用同一组点分别跑新实现与旧实现（逐格赋样式 +
公开 `merge_cells`），比对：

- 合并区域：28 个，完全一致
- 每格的**值与数字格式**：完全一致
- 新版每格都是宋体 11、水平垂直居中、四边细线；旧版合并区内部格反而会丢字体
  （`_clean_merge_range` 重建 `MergedCell` 时只搬了部分边框），新版更完整

另外用 openpyxl 直接读回生成的 xlsx 检查：`<c r="B1" s="1" .../>` 等合并区内部格
都带样式索引，`<mergeCells count="2000">` 记录正常。

### 4.3 回归

- `python -m pytest tests -q` → 30 passed
- `python tools/verify_review_fixes.py` → 验证通过（深缩放下长实体仍可见、可拾取）
- 大图加载、框选、导出 100 条 xlsx 均正常

## 5. 复现方法

```bash
python tools/bench_perf.py                    # 全流程基准（两张样图）
python tools/bench_export_parts.py            # 导出分段耗时（样式/合并/其它）
python tools/bench_vertices.py 2000 20000 100000   # 超长要素高亮与顶点标记
python tools/verify_sheet_style.py            # 新旧表形写入一致性
```

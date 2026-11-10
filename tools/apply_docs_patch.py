"""一次性补丁：版本号 1.3.1 + README 性能章节更新。

用法：python tools/apply_docs_patch.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERSION_FILE = ROOT / "core" / "excel_export.py"
README = ROOT / "README.md"

PERF_SECTION = """框选 6000+ 条要素时，待导出列表只计算当前可见行的总长，列表刷新约 3 ms。

### 1.3.1 性能优化（同机实测，min-of-N）

| 指标 | 优化前 | 优化后 | 做法 |
|---|---|---|---|
| 导出 100 条线 | 2369 ms | 115 ms | 单元格样式改成样式数组批量套用；合并绕开 openpyxl 逐格重算边框 |
| 导出 20 条线 | 318 ms | 30 ms | 同上 |
| 导出 1 条线 | 32 ms | 22 ms | 余下是建工作簿与落盘本身的开销 |
| 选中 10 万点长线后重绘 | 417 ms | 13 ms | 高亮改用底图那套抽稀折线；顶点方块按视口裁剪并限量抽样 |
| 选中 2 万点长线后重绘 | 84 ms | 21 ms | 同上 |
| 框选 5000 条后重绘 | 31 ms | 25 ms | 完整折线缓存从「超限整表清空」改为 LRU + 总点数预算 |

解析时间仍由 ezdwg 的实体枚举主导（9.9 MB 总图 3.6 s 里约 2.3 s 在枚举），
本程序侧没有可再压缩的空间；加载已有独立线程 + 进度提示，不阻塞界面。
"""


def patch_text(path: Path, old: str, new: str, label: str) -> str:
    with open(path, "r", encoding="utf-8", newline="") as fh:
        text = fh.read().replace("\r\n", "\n")
    if new.split("\n")[0] and new in text:
        print(f"{label}: 已是新内容")
        return text
    if old not in text:
        raise SystemExit(f"[失败] {label} 未找到锚点")
    text = text.replace(old, new, 1)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text.replace("\n", "\r\n"))
    print(f"{label}: 已更新")
    return text


def main() -> int:
    with open(VERSION_FILE, "r", encoding="utf-8", newline="") as fh:
        text = fh.read().replace("\r\n", "\n")
    if 'APP_VERSION = "1.3.0"' in text:
        text = text.replace('APP_VERSION = "1.3.0"', 'APP_VERSION = "1.3.1"', 1)
        with open(VERSION_FILE, "w", encoding="utf-8", newline="") as fh:
            fh.write(text.replace("\n", "\r\n"))
        print("版本号: 1.3.0 -> 1.3.1")
    else:
        print("版本号: 已是 1.3.1 或其它值，跳过")

    patch_text(
        README,
        "框选 6000+ 条要素时，待导出列表只计算当前可见行的总长，列表刷新约 3 ms。\n",
        PERF_SECTION,
        "README 性能章节",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""启动打包后的 exe 并测量「窗口出现 / 图纸打开完成」耗时。

用法：python tools/launch_and_time.py <exe> <dwg> [--keep]
默认测完就退出（子进程随父进程结束），传 --keep 则测完继续等待窗口关闭。
"""
from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import time
from ctypes import wintypes

user32 = ctypes.windll.user32
WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def find(title_part: str) -> list[tuple[str, int]]:
    hits: list[tuple[str, int]] = []

    def callback(hwnd, _lparam):
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                if title_part in buf.value:
                    pid = wintypes.DWORD()
                    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                    hits.append((buf.value, pid.value))
        return True

    user32.EnumWindows(WNDENUMPROC(callback), 0)
    return hits


def main() -> int:
    exe, dwg = os.path.abspath(sys.argv[1]), sys.argv[2]
    keep = "--keep" in sys.argv
    start = time.perf_counter()
    proc = subprocess.Popen([exe, dwg])
    window_at = loaded_at = None
    while time.perf_counter() - start < 90:
        hits = find("DWG 坐标导出工具")
        if hits and window_at is None:
            window_at = time.perf_counter() - start
        if hits and os.path.basename(dwg)[:6] in hits[0][0]:
            loaded_at = time.perf_counter() - start
            break
        if proc.poll() is not None:
            print("进程已退出，退出码", proc.returncode)
            return 1
        time.sleep(0.1)
    print(f"窗口出现 {window_at * 1000:.0f} ms | 图纸打开完成 "
          f"{(loaded_at or 0) * 1000:.0f} ms | 标题 {hits[0][0] if hits else '无'}")
    logs = os.path.join(os.path.dirname(exe), "logs", "crash.log")
    print("崩溃日志存在:", os.path.exists(logs))
    if keep:
        proc.wait()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

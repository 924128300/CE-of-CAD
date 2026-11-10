"""端到端验证打包后的 exe：打开图纸 -> Ctrl+W 清空图纸 -> 标题复位。

用法：python tools/verify_exe_clear.py [exe] [dwg]
"""
from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import time
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
VK_CONTROL, VK_W = 0x11, 0x57
KEYEVENTF_KEYUP = 0x0002


def find_window(title_part: str) -> tuple[int, str] | None:
    hits: list[tuple[int, str]] = []

    def callback(hwnd, _lparam):
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                if title_part in buf.value:
                    hits.append((hwnd, buf.value))
        return True

    user32.EnumWindows(WNDENUMPROC(callback), 0)
    return hits[0] if hits else None


def wait_title(part: str, timeout: float) -> tuple[int, str] | None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        found = find_window(part)
        if found:
            return found
        time.sleep(0.2)
    return None


def send_ctrl_w(hwnd: int) -> None:
    user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.4)
    user32.keybd_event(VK_CONTROL, 0, 0, 0)
    user32.keybd_event(VK_W, 0, 0, 0)
    user32.keybd_event(VK_W, 0, KEYEVENTF_KEYUP, 0)
    user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)


def main() -> int:
    exe = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "dist/DWGCoordExporter.exe")
    dwg = sys.argv[2] if len(sys.argv) > 2 else "D:/6月探采对比汇报资料/剖面图/EW000线.dwg"
    proc = subprocess.Popen([exe, dwg])
    try:
        found = wait_title("EW000线.dwg", 30)
        if not found:
            print("未等到图纸窗口")
            return 1
        hwnd, title = found
        print(f"已打开：{title}")
        send_ctrl_w(hwnd)
        cleared = None
        deadline = time.time() + 8
        while time.time() < deadline:
            current = find_window("DWG 坐标导出工具")
            if current and current[1] == "DWG 坐标导出工具":
                cleared = current
                break
            time.sleep(0.2)
        print("清空后标题：" + (cleared[1] if cleared else "（未复位）"))
        return 0 if cleared else 1
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())

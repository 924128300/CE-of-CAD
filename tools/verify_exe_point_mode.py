"""端到端验证打包后的 exe：启动、打开图纸、切到点选模式并截图。

用法：python tools/verify_exe_point_mode.py [exe] [dwg]
"""
from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import time
from ctypes import wintypes

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.grab_window import grab  # noqa: E402

user32 = ctypes.WinDLL("user32", use_last_error=True)
WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
KEYEVENTF_KEYUP = 0x0002
VK_P = 0x50

SHOT = os.path.join("tools", "screenshots", "_v150_exe_point.png")


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


def force_foreground(hwnd: int) -> None:
    """绕过 Windows 的抢焦点限制，把目标窗口真正切到前台。"""
    user32.ShowWindow(hwnd, 9)
    foreground = user32.GetForegroundWindow()
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    self_thread = kernel32.GetCurrentThreadId()
    other_thread = user32.GetWindowThreadProcessId(foreground, None)
    attached = False
    if other_thread and other_thread != self_thread:
        attached = bool(user32.AttachThreadInput(self_thread, other_thread, True))
    user32.BringWindowToTop(hwnd)
    user32.SetForegroundWindow(hwnd)
    user32.SetFocus(hwnd)
    if attached:
        user32.AttachThreadInput(self_thread, other_thread, False)
    time.sleep(0.3)


def click_client(hwnd: int, x: int, y: int) -> None:
    point = wintypes.POINT(x, y)
    user32.ClientToScreen(hwnd, ctypes.byref(point))
    user32.SetCursorPos(point.x, point.y)
    time.sleep(0.2)
    user32.mouse_event(0x0002, 0, 0, 0, 0)  # LEFTDOWN
    user32.mouse_event(0x0004, 0, 0, 0, 0)  # LEFTUP


def press_key(vk: int) -> None:
    user32.keybd_event(vk, 0, 0, 0)
    user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)


def close_window(hwnd: int) -> None:
    WM_CLOSE = 0x0010
    user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)


def main() -> int:
    exe = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "dist/DWGCoordExporter.exe")
    dwg = sys.argv[2] if len(sys.argv) > 2 else "D:/6月探采对比汇报资料/剖面图/EW000线.dwg"
    started = time.perf_counter()
    proc = subprocess.Popen([exe, dwg])
    hwnd = None
    try:
        found = wait_title("EW000线.dwg", 40)
        if not found:
            print("未等到图纸窗口")
            return 1
        hwnd, title = found
        print(f"启动并打开图纸 {time.perf_counter() - started:.2f} s | 标题：{title}")
        time.sleep(1.2)
        force_foreground(hwnd)
        click_client(hwnd, 420, 300)   # 点一下画布，让键盘焦点落在画布上
        time.sleep(0.5)
        press_key(VK_P)                # 快捷键切到点选模式
        time.sleep(1.5)
        grab(hwnd, SHOT)
        print("截图：", SHOT)
        logs = os.path.join(os.path.dirname(exe), "logs", "crash.log")
        print("崩溃日志：", "有" if os.path.exists(logs) else "无")
        return 0
    finally:
        if hwnd:
            close_window(hwnd)
        try:
            proc.wait(timeout=8)
        except Exception:  # noqa: BLE001
            proc.terminate()


if __name__ == "__main__":
    raise SystemExit(main())

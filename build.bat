@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo 创建打包用虚拟环境...
    python -m venv --system-site-packages .venv
    ".venv\Scripts\python.exe" -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple pyinstaller
)

echo 开始打包...
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --windowed ^
    --name DWGCoordExporter ^
    --icon assets/app.ico ^
    --add-data "README.md;." ^
    --exclude-module matplotlib ^
    --exclude-module scipy ^
    --exclude-module pandas ^
    --exclude-module numpy ^
    --exclude-module PIL ^
    --exclude-module tkinter ^
    --exclude-module IPython ^
    --exclude-module pytest ^
    app.py

if errorlevel 1 (
    echo 打包失败。
    pause
    exit /b 1
)
echo 打包完成：dist\DWGCoordExporter\DWGCoordExporter.exe
pause

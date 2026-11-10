@echo off
chcp 65001 >nul
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo 未找到 Python，请先安装 Python 3.10 及以上版本。
    pause
    exit /b 1
)

python -c "import PySide6, ezdwg, openpyxl" >nul 2>nul
if errorlevel 1 (
    echo 正在安装运行依赖，首次启动需要联网...
    python -m pip install -r requirements.txt
    if errorlevel 1 (
        echo 依赖安装失败，请检查网络后重试。
        pause
        exit /b 1
    )
)

python app.py %*
if errorlevel 1 pause

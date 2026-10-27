@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\pyinstaller.exe" (
    echo 未安装 PyInstaller，正在安装...
    ".venv\Scripts\python.exe" -m pip install pyinstaller -i https://mirrors.aliyun.com/pypi/simple
    if errorlevel 1 (
        echo 安装失败，请先运行“安装依赖.bat”，再重试。
        pause
        exit /b 1
    )
)
".venv\Scripts\pyinstaller.exe" --noconfirm --clean --windowed --name AutoRename115 --hidden-import PIL._tkinter_finder --distpath dist --workpath build run.py
if errorlevel 1 (
    echo 打包失败。
    pause
    exit /b 1
)
echo.
echo 打包完成：dist\AutoRename115\AutoRename115.exe
pause

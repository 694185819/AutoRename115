@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo  115 海报墙重命名助手 - 安装依赖
echo ============================================
if not exist ".venv\Scripts\python.exe" (
    echo 正在创建 Python 虚拟环境...
    py -3 -m venv .venv
    if errorlevel 1 (
        echo 创建虚拟环境失败，请确认已安装 Python 3.10 或更高版本。
        pause
        exit /b 1
    )
)
echo 正在安装依赖（使用阿里云镜像）...
".venv\Scripts\python.exe" -m pip install --upgrade pip -i https://mirrors.aliyun.com/pypi/simple
".venv\Scripts\python.exe" -m pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple
if errorlevel 1 (
    echo.
    echo 依赖安装失败，请检查网络后重试。
    pause
    exit /b 1
)
echo.
echo 安装完成。双击“启动.bat”即可运行。
pause

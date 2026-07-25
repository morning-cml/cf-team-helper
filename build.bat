@echo off
chcp 65001 >nul
echo ============================================
echo   打包 CF 辅助工具 v2.10 为单文件 exe
echo ============================================

REM 必须用原生 CPython（py 启动器）。PATH 上的 python 可能是 msys2 版，
REM 用它打出的 exe 会依赖 mingw DLL，换台机器就跑不起来。
py -3 --version >nul 2>nul
if errorlevel 1 (
    echo [x] 未找到原生 Python，请先安装 python.org 版本的 Python。
    pause
    exit /b 1
)

py -3 -m PyInstaller --version >nul 2>nul
if errorlevel 1 (
    echo [!] 未检测到 pyinstaller，正在安装...
    py -3 -m pip install pyinstaller
)

py -3 -m PyInstaller --noconfirm --clean --onefile --noconsole --name "cf辅助工具" ^
  --add-data "cfhelper/templates;cfhelper/templates" ^
  --add-data "cfhelper/static;cfhelper/static" ^
  run.py

if errorlevel 1 (
    echo [x] 打包失败。
    pause
    exit /b 1
)

echo.
echo ============================================
echo   完成！产物：dist\cf辅助工具.exe
echo   双击即可运行，无黑窗口，会自动打开浏览器。
echo   关闭浏览器页面后进程自动退出（约 2~4 秒）。
echo.
echo   首次运行会在 exe 同级生成 data\ 存放大部队与题单。
echo   如需保留现有数据，把本目录 data\ 下的 json
echo   复制到 exe 同级的 data\ 下即可。
echo ============================================
pause

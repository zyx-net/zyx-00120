@echo off
chcp 65001 >nul
setlocal
setlocal enabledelayedexpansion

echo ============================================
echo   预约冻结与恢复中心 - Windows 一键回归测试
echo ============================================
echo.

cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] 未找到 Python，请先安装 Python 3.8+ 并加入 PATH
    exit /b 1
)

python -c "import flask" >nul 2>nul
if errorlevel 1 (
    echo [WARN] 未检测到 flask 依赖，正在安装...
    pip install flask
    if errorlevel 1 (
        echo [ERROR] 安装依赖失败，请手动执行: pip install -r requirements.txt
        exit /b 1
    )
)

echo [INFO] 启动回归测试，请等待服务器就绪...
echo.

python freeze_regression.py
set EXIT_CODE=%ERRORLEVEL%

echo.
echo ============================================
if %EXIT_CODE% EQU 0 (
    echo   回归测试 [PASSED] 全部通过 ^_^
) else (
    echo   回归测试 [FAILED] 共 %EXIT_CODE% 项用例未通过
    echo   请查看 _freeze_regression.log 了解详情
)
echo ============================================

endlocal
exit /b %EXIT_CODE%

@echo off
chcp 65001 >nul
setlocal

echo ============================================
echo   入口自检脚本 - freeze_regression 入口复核
echo ============================================
echo.

cd /d "%~dp0"

set "PASS=0"
set "FAIL=0"

echo [自检 1/8] BAT --help 退出码...
cmd /c freeze_regression.bat --help >nul 2>&1
if %errorlevel% equ 0 (
    echo   [PASS] BAT --help 退出码 0
    set /a PASS+=1
) else (
    echo   [FAIL] BAT --help 退出码 %errorlevel%，应为 0
    set /a FAIL+=1
)

echo.
echo [自检 2/8] Python --help 退出码...
python freeze_regression.py --help >nul 2>&1
if %errorlevel% equ 0 (
    echo   [PASS] Python --help 退出码 0
    set /a PASS+=1
) else (
    echo   [FAIL] Python --help 退出码 %errorlevel%，应为 0
    set /a FAIL+=1
)

echo.
echo [自检 3/8] BAT --clean-only 退出码...
cmd /c freeze_regression.bat --clean-only >nul 2>&1
if %errorlevel% equ 0 (
    echo   [PASS] BAT --clean-only 退出码 0
    set /a PASS+=1
) else (
    echo   [FAIL] BAT --clean-only 退出码 %errorlevel%，应为 0
    set /a FAIL+=1
)

echo.
echo [自检 4/8] Python --clean-only 退出码...
python freeze_regression.py --clean-only >nul 2>&1
if %errorlevel% equ 0 (
    echo   [PASS] Python --clean-only 退出码 0
    set /a PASS+=1
) else (
    echo   [FAIL] Python --clean-only 退出码 %errorlevel%，应为 0
    set /a FAIL+=1
)

echo.
echo [自检 5/8] BAT --HELP 大小写不敏感...
cmd /c freeze_regression.bat --HELP >nul 2>&1
if %errorlevel% equ 0 (
    echo   [PASS] BAT --HELP 大写有效（大小写不敏感）
    set /a PASS+=1
) else (
    echo   [FAIL] BAT --HELP 大写无效
    set /a FAIL+=1
)

echo.
echo [自检 6/8] Python --HELP 大小写敏感（应报错）...
python freeze_regression.py --HELP >nul 2>&1
if %errorlevel% equ 2 (
    echo   [PASS] Python --HELP 大写报错退出码 2（大小写敏感）
    set /a PASS+=1
) else (
    echo   [FAIL] Python --HELP 退出码 %errorlevel%，应为 2
    set /a FAIL+=1
)

echo.
echo [自检 7/8] BAT --keep 别名（包装层特有）...
cmd /c freeze_regression.bat --keep --clean-only >nul 2>&1
if %errorlevel% equ 0 (
    echo   [PASS] BAT --keep 别名有效
    set /a PASS+=1
) else (
    echo   [FAIL] BAT --keep 别名无效
    set /a FAIL+=1
)

echo.
echo [自检 8/8] Python --git-check 无别名（应报错）...
python freeze_regression.py --git-check --clean-only >nul 2>&1
if %errorlevel% equ 2 (
    echo   [PASS] Python --git-check 报错退出码 2（无别名）
    set /a PASS+=1
) else (
    echo   [FAIL] Python --git-check 退出码 %errorlevel%，应为 2
    echo   注意: --keep 因 argparse 前缀匹配碰巧生效，但不是有意设计的别名
    set /a FAIL+=1
)

echo.
echo ============================================
echo   自检完成  通过: %PASS%   失败: %FAIL%
echo ============================================
echo.

if %FAIL% gtr 0 (
    echo 建议运行完整回归测试:
    echo   python test_freeze_regression.py
    exit /b 1
) else (
    echo 所有快速自检通过 ^_^
    echo 如需完整测试请运行:
    echo   python test_freeze_regression.py
    exit /b 0
)

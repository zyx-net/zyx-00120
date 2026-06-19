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

set "EXTRA_ARGS="
set "SHOW_HELP=0"

:parse_args
if "%~1"=="" goto done_args
if /I "%~1"=="--help"       set "SHOW_HELP=1"
if /I "%~1"=="-h"           set "SHOW_HELP=1"
if /I "%~1"=="--keep"       set "EXTRA_ARGS=%EXTRA_ARGS% --keep-artifacts"
if /I "%~1"=="--keep-artifacts" set "EXTRA_ARGS=%EXTRA_ARGS% --keep-artifacts"
if /I "%~1"=="--export"     set "EXTRA_ARGS=%EXTRA_ARGS% --export-samples"
if /I "%~1"=="--export-samples" set "EXTRA_ARGS=%EXTRA_ARGS% --export-samples"
if /I "%~1"=="--clean"      set "EXTRA_ARGS=%EXTRA_ARGS% --clean-before"
if /I "%~1"=="--clean-before" set "EXTRA_ARGS=%EXTRA_ARGS% --clean-before"
if /I "%~1"=="--clean-only" set "EXTRA_ARGS=%EXTRA_ARGS% --clean-only"
if /I "%~1"=="--git-check"  set "EXTRA_ARGS=%EXTRA_ARGS% --check-git-clean"
if /I "%~1"=="--check-git-clean" set "EXTRA_ARGS=%EXTRA_ARGS% --check-git-clean"
shift
goto parse_args
:done_args

if "%SHOW_HELP%"=="1" (
    echo 用法: %~nx0 [选项]
    echo.
    echo 选项（可任意组合）:
    echo   --keep, --keep-artifacts    无论成功失败都保留工件目录
    echo   --export, --export-samples  成功后显式导出报告样例到 _regression_artifacts\exports\
    echo   --clean, --clean-before     运行前先清理所有历史工件目录
    echo   --clean-only                仅清理历史工件并退出，不执行回归
    echo   --git-check, --check-git-clean  执行前后检查 git status 干净性
    echo   -h, --help                  显示此帮助
    echo.
    echo 默认策略:
    echo   * 成功 -^> 自动清理工件，源码根保持干净
    echo   * 失败 -^> 保留工件（backup/logs/reports/diagnostics）供诊断
    echo.
    echo 工件统一入口: _regression_artifacts\  （已在 .gitignore 中排除）
    exit /b 0
)

echo [INFO] 启动回归测试，请等待服务器就绪...
echo        工件目录: _regression_artifacts\
if not "%EXTRA_ARGS%"=="" echo        附加参数:%EXTRA_ARGS%
echo.

python freeze_regression.py%EXTRA_ARGS%
set EXIT_CODE=%ERRORLEVEL%

echo.
echo ============================================
if %EXIT_CODE% EQU 0 (
    echo   回归测试 [PASSED] 全部通过 ^_^
) else (
    echo   回归测试 [FAILED] 共 %EXIT_CODE% 项用例未通过
    echo   请查看 _regression_artifacts\runs\^\<run_id\>\logs\regression.log
)
echo ============================================
echo.
echo 工件管理提示:
echo   * 清理所有历史工件: %~nx0 --clean-only
echo   * 保留诊断工件:     %~nx0 --keep
echo   * 导出报告样例:     %~nx0 --export
echo   * 验证 git 干净:    %~nx0 --git-check

endlocal
exit /b %EXIT_CODE%

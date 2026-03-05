@echo off
echo ========================================
echo   MyAPS 自动启动脚本
echo ========================================
echo.

cd /d "%~dp0"

:start
echo [%time%] 启动 MyAPS...
python app.py
echo [%time%] MyAPS 已停止，准备重启...
echo.
timeout /t 3 /nobreak >nul
goto start

@echo off
chcp 65001 >nul
title TG-FLOWMAP Launcher

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

if exist "%SCRIPT_DIR%.venv\Scripts\python.exe" (
    set "PYTHON_EXE=%SCRIPT_DIR%.venv\Scripts\python.exe"
) else (
    set "PYTHON_EXE=python"
)

"%PYTHON_EXE%" run.py %*
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] Процесс завершился с ошибкой (код %ERRORLEVEL%).
    pause
)

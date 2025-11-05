@echo off
setlocal

REM ============================================
REM Baseline Local Test - MLSP
REM ============================================

echo Starting MLSP baseline test...
for /f "delims=" %%p in ('where python 2^>nul') do set PYTHON_EXE="%%p"
if not defined PYTHON_EXE (
    echo Python not found in PATH.
    pause
    exit /b 1
)

REM Get script directory so paths stay correct
set "PROJECT_DIR=%~dp0"
cd /d "%PROJECT_DIR%"

REM Start server
start "MLSP SERVER" cmd /k %PYTHON_EXE% ..\src\server.py
timeout /t 2 >nul

REM Start four clients
for /l %%i in (1,1,2) do (
    start "CLIENT %%i" cmd /k %PYTHON_EXE% ..\src\client.py
    timeout /t 1 >nul
)

exit /b 0

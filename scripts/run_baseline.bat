@echo off
REM ============================================
REM Baseline Local Test - MLSP (Phase 1)
REM Launches one server and four clients
REM ============================================

echo Starting MLSP baseline test...
set PORT=40000

REM Start server in a new terminal
start "MLSP SERVER" cmd /k python server.py

REM Give the server time to start
timeout /t 2 >nul

REM Start four clients in new terminals
start "CLIENT 1" cmd /k python client.py
timeout /t 1 >nul
start "CLIENT 2" cmd /k python client.py
timeout /t 1 >nul
start "CLIENT 3" cmd /k python client.py
timeout /t 1 >nul
start "CLIENT 4" cmd /k python client.py

echo All clients launched.
echo When finished, close all terminals manually.
pause

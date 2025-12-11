@echo off
setlocal enabledelayedexpansion

set START_SERVER=python "..\src\server.py"
set START_CLIENT1=python "..\src\client.py" --id 1
set START_CLIENT2=python "..\src\client.py" --id 2
set START_CLIENT3=python "..\src\client.py" --id 3
set START_CLIENT4=python "..\src\client.py" --id 4

set TEST_DURATION=60

echo RUNNING TEST

:: Start server
start "" cmd /c "%START_SERVER%"
set SERVER_PID=%!

:: Start clients
start "" cmd /c "%START_CLIENT1%"
start "" cmd /c "%START_CLIENT2%"
start "" cmd /c "%START_CLIENT3%"
start "" cmd /c "%START_CLIENT4%"

echo Running for %TEST_DURATION% seconds...
timeout /T %TEST_DURATION% >nul

echo Stopping processes...

:: Kill server & clients
taskkill /IM python.exe /F >nul 2>&1

echo TEST COMPLETE
pause
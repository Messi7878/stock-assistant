@echo off
cd /d "%~dp0"
set "PY=%USERPROFILE%\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"
if not exist "%PY%" set "PY=python"
echo.
echo  A-share assistant starting: http://127.0.0.1:8756
echo  Close this window (or press Ctrl+C) to stop the server.
echo.
start /b cmd /c "timeout /t 2 >nul && start http://127.0.0.1:8756"
"%PY%" app.py
pause

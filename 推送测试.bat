@echo off
chcp 65001 >nul
echo 正在生成报告并推送,请稍候...
call "%~dp0run_push.bat"
echo.
echo 如果手机没收到,请看同目录下的 push.log 排查原因。
pause

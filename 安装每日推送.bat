@echo off
chcp 65001 >nul
echo 正在注册 Windows 计划任务:每个工作日 08:30 自动推送每日报告...
schtasks /Create /TN "AStockAssistant_DailyPush" /TR "\"%~dp0run_push.bat\"" /SC WEEKLY /D MON,TUE,WED,THU,FRI /ST 08:30 /F
echo.
if %ERRORLEVEL%==0 (
  echo 安装成功!任务名:AStockAssistant_DailyPush(工作日 08:30 自动运行)
  echo 想改时间:重新运行本文件前,先编辑里面的 08:30。
  echo 想删除:运行 schtasks /Delete /TN AStockAssistant_DailyPush /F
) else (
  echo 安装失败。可尝试右键本文件 -^> 以管理员身份运行。
)
echo.
pause

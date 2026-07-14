@echo off
chcp 936 >nul
cd /d "%~dp0"
pwsh -NoProfile -ExecutionPolicy Bypass -File "刷新线上采集.ps1"
if errorlevel 1 (
  powershell -NoProfile -ExecutionPolicy Bypass -File "刷新线上采集.ps1"
)
if errorlevel 1 (
  echo.
  echo [!] 脚本异常退出，上面红字是错误信息，截图发给助手即可。
  pause
)

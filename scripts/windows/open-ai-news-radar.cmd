@echo off
set "SCRIPT_DIR=%~dp0"
set "LAUNCHER=%SCRIPT_DIR%open-ai-news-radar.ps1"
set "LOG=%LOCALAPPDATA%\AINewsRadarLauncher\open-ai-news-radar-launch.log"
set "URL=http://127.0.0.1:8080/"
set "CHROME=C:\Program Files\Google\Chrome\Application\chrome.exe"
set "EDGE=C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"

if not exist "%LOCALAPPDATA%\AINewsRadarLauncher" mkdir "%LOCALAPPDATA%\AINewsRadarLauncher"

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%LAUNCHER%" -NoBrowser > "%LOG%" 2>&1
if errorlevel 1 (
    type "%LOG%"
    pause
    exit /b %errorlevel%
)

if exist "%CHROME%" (
    start "AI News Radar" "%CHROME%" --new-window "%URL%"
    exit /b 0
)

if exist "%EDGE%" (
    start "AI News Radar" "%EDGE%" --new-window "%URL%"
    exit /b 0
)

start "AI News Radar" "%URL%"

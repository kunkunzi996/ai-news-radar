@echo off
chcp 65001 >nul
schtasks /run /tn "DouyinCollectAndPush"
if errorlevel 1 goto failed
powershell.exe -NoProfile -Command "Write-Host ([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('5bey6Kem5Y+R77yM6L+b5bqm6K+35p+l55yL5pel5b+X44CC')))"
goto end

:failed
powershell.exe -NoProfile -Command "Write-Host ([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('6Kem5Y+R5aSx6LSl77yM6K+35qOA5p+lIERvdXlpbkNvbGxlY3RBbmRQdXNoIOiuoeWIkuS7u+WKoeOAgg==')))"

:end
pause

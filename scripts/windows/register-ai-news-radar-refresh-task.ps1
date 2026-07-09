param(
    [ValidateSet("Register", "Unregister")]
    [string]$Mode = "Register",

    [int]$IntervalMinutes = 30,

    [ValidateSet("since-last", "24h", "all")]
    [string]$CollectionScope = "since-last"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$refreshScript = Join-Path $PSScriptRoot "refresh-ai-news-radar.ps1"
$taskName = "AI News Radar Refresh"
$taskDescription = "Refresh AI News Radar data files on a schedule."

if ($Mode -eq "Unregister") {
    $existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($null -ne $existing) {
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
        Write-Host "Removed scheduled task: $taskName"
    } else {
        Write-Host "Scheduled task does not exist: $taskName"
    }
    exit 0
}

if ($IntervalMinutes -lt 5) {
    throw "IntervalMinutes must be at least 5."
}
if (-not (Test-Path -LiteralPath $refreshScript)) {
    throw "Refresh script was not found: $refreshScript"
}

$powershellExe = Join-Path $env:WINDIR "System32\WindowsPowerShell\v1.0\powershell.exe"
$taskArguments = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", "`"$refreshScript`"",
    "-CollectionScope", $CollectionScope
) -join " "

$action = New-ScheduledTaskAction `
    -Execute $powershellExe `
    -Argument $taskArguments `
    -WorkingDirectory $repoRoot

$trigger = New-ScheduledTaskTrigger `
    -Once `
    -At (Get-Date).AddMinutes(2) `
    -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes) `
    -RepetitionDuration (New-TimeSpan -Days 3650)

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 20)

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description $taskDescription `
    -Force | Out-Null

Write-Host "Registered scheduled task: $taskName"
Write-Host "Interval minutes: $IntervalMinutes"
Write-Host "Collection scope: $CollectionScope"
Write-Host "Manual run: Start-ScheduledTask -TaskName '$taskName'"
Write-Host "Logs: $env:LOCALAPPDATA\AINewsRadarAutomation"

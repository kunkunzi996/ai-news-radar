param(
    [ValidateSet("since-last", "24h", "all")]
    [string]$CollectionScope = "since-last",

    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$pythonExe = Join-Path $repoRoot ".venv\Scripts\python.exe"
$sourceConfigPath = Join-Path $repoRoot "sources.config.json"
$statusPath = Join-Path $repoRoot "data\source-status.json"
$logDir = Join-Path $env:LOCALAPPDATA "AINewsRadarAutomation"

function Get-CollectWindowHours {
    param(
        [string]$Scope,
        [string]$StatusFile
    )

    if ($Scope -eq "all") {
        return 0
    }
    if ($Scope -eq "24h") {
        return 24
    }
    if (-not (Test-Path -LiteralPath $StatusFile)) {
        return 24
    }

    try {
        $payload = Get-Content -LiteralPath $StatusFile -Raw | ConvertFrom-Json
        $rawGeneratedAt = [string]$payload.generated_at
        if ([string]::IsNullOrWhiteSpace($rawGeneratedAt)) {
            return 24
        }
        $generatedAt = [DateTimeOffset]::Parse($rawGeneratedAt.Replace("Z", "+00:00"))
        $elapsed = [DateTimeOffset]::UtcNow - $generatedAt.ToUniversalTime()
        if ($elapsed.TotalSeconds -le 0) {
            return 24
        }
        return [Math]::Max(1, [int][Math]::Ceiling($elapsed.TotalHours))
    } catch {
        return 24
    }
}

if (-not (Test-Path -LiteralPath $repoRoot)) {
    throw "Project folder was not found: $repoRoot"
}
if (-not (Test-Path -LiteralPath $pythonExe)) {
    throw "Local Python was not found: $pythonExe"
}
if (-not (Test-Path -LiteralPath $logDir)) {
    New-Item -ItemType Directory -Path $logDir | Out-Null
}

$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUNBUFFERED = "1"

$arguments = @(
    "scripts/update_news.py",
    "--output-dir", "data",
    "--window-hours", "24",
    "--archive-days", "3650",
    "--all-time"
)

if (Test-Path -LiteralPath $sourceConfigPath) {
    $arguments = @("scripts/update_news.py", "--source-config", "sources.config.json") + $arguments[1..($arguments.Count - 1)]
}

$collectWindowHours = Get-CollectWindowHours -Scope $CollectionScope -StatusFile $statusPath
if ($collectWindowHours -gt 0) {
    $arguments += @("--collect-window-hours", [string]$collectWindowHours)
}

if ($DryRun) {
    [PSCustomObject]@{
        Python = $pythonExe
        WorkingDirectory = $repoRoot
        CollectionScope = $CollectionScope
        CollectWindowHours = $collectWindowHours
        Arguments = $arguments
        SourceConfig = if (Test-Path -LiteralPath $sourceConfigPath) { $sourceConfigPath } else { "" }
        LogDirectory = $logDir
    } | ConvertTo-Json -Depth 4
    exit 0
}

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$stdoutLog = Join-Path $logDir "refresh-$timestamp.out.log"
$stderrLog = Join-Path $logDir "refresh-$timestamp.err.log"
$latestOut = Join-Path $logDir "latest.out.log"
$latestErr = Join-Path $logDir "latest.err.log"

$process = Start-Process `
    -FilePath $pythonExe `
    -ArgumentList $arguments `
    -WorkingDirectory $repoRoot `
    -RedirectStandardOutput $stdoutLog `
    -RedirectStandardError $stderrLog `
    -WindowStyle Hidden `
    -PassThru `
    -Wait

Copy-Item -LiteralPath $stdoutLog -Destination $latestOut -Force
Copy-Item -LiteralPath $stderrLog -Destination $latestErr -Force

if ($process.ExitCode -ne 0) {
    throw "AI News Radar refresh failed with exit code $($process.ExitCode). Logs: $stdoutLog / $stderrLog"
}

Write-Host "AI News Radar refresh completed. Logs: $stdoutLog / $stderrLog"

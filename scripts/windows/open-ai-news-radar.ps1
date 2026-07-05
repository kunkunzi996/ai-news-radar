param(
    [switch]$NoBrowser
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$pythonExe = Join-Path $repoRoot ".venv\Scripts\python.exe"
$dashboardUrl = "http://127.0.0.1:8080/"
$launcherDir = Join-Path $env:LOCALAPPDATA "AINewsRadarLauncher"
$stdoutLog = Join-Path $launcherDir "ai-news-radar-server.out.log"
$stderrLog = Join-Path $launcherDir "ai-news-radar-server.err.log"

function Show-LauncherError {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Message
    )

    Add-Type -AssemblyName System.Windows.Forms
    [void][System.Windows.Forms.MessageBox]::Show(
        $Message,
        "AI News Radar launcher error",
        [System.Windows.Forms.MessageBoxButtons]::OK,
        [System.Windows.Forms.MessageBoxIcon]::Error
    )
}

function Test-DashboardReady {
    try {
        $response = Invoke-WebRequest -Uri $dashboardUrl -UseBasicParsing -TimeoutSec 2
        return [int]$response.StatusCode -eq 200
    } catch {
        return $false
    }
}

function Open-Dashboard {
    $browserCandidates = @(
        "C:\Program Files\Google\Chrome\Application\chrome.exe",
        "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        "C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
    )

    foreach ($browserPath in $browserCandidates) {
        if (Test-Path -LiteralPath $browserPath) {
            Start-Process -FilePath $browserPath -ArgumentList @("--new-window", $dashboardUrl)
            return
        }
    }

    $cmdExe = Join-Path $env:WINDIR "System32\cmd.exe"
    Start-Process -FilePath $cmdExe -ArgumentList @("/c", "start", '""', $dashboardUrl)
}

if (-not (Test-Path -LiteralPath $repoRoot)) {
    Show-LauncherError "Project folder was not found:`n$repoRoot"
    exit 1
}

if (-not (Test-Path -LiteralPath $pythonExe)) {
    Show-LauncherError "Local Python was not found:`n$pythonExe"
    exit 1
}

if (-not (Test-Path -LiteralPath $launcherDir)) {
    New-Item -ItemType Directory -Path $launcherDir | Out-Null
}

if (-not (Test-DashboardReady)) {
    Start-Process `
        -FilePath $pythonExe `
        -ArgumentList @("scripts/local_server.py", "--host", "127.0.0.1", "--port", "8080") `
        -WorkingDirectory $repoRoot `
        -RedirectStandardOutput $stdoutLog `
        -RedirectStandardError $stderrLog `
        -WindowStyle Hidden

    $ready = $false
    foreach ($attempt in 1..20) {
        Start-Sleep -Milliseconds 500
        if (Test-DashboardReady) {
            $ready = $true
            break
        }
    }

    if (-not $ready) {
        Show-LauncherError "Dashboard server did not become ready.`n`nLogs:`n$stdoutLog`n$stderrLog"
        exit 1
    }
}

if (-not $NoBrowser) {
    Open-Dashboard
}

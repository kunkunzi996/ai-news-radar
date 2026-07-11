param(
    [string]$RadarRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path,
    [string]$SidecarRoot = "",
    [string]$BridgeRoot = "",
    [string]$BaseUrl = "http://127.0.0.1:8001",
    [int]$MaxItems = 20,
    [string]$LogFile = ""
)

$ErrorActionPreference = "Stop"
if ($LogFile) {
    try { Start-Transcript -Path $LogFile -Append | Out-Null } catch { Write-Warning "Log transcript start failed: $_" }
}
$env:PYTHONIOENCODING = "utf-8"

function Write-Step([string]$Message) {
    Write-Host ("[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message)
}

function Invoke-Git([string]$RepoDir, [string[]]$GitArgs) {
    $ErrorActionPreference = "Continue"
    & git -C $RepoDir @GitArgs 2>&1 | ForEach-Object { Write-Host ("  git: {0}" -f $_) }
    return $LASTEXITCODE
}

if (-not $SidecarRoot) { $SidecarRoot = Join-Path (Split-Path $RadarRoot -Parent) "we-mp-rss-sidecar" }
if (-not $BridgeRoot) { $BridgeRoot = Join-Path (Split-Path $RadarRoot -Parent) "wechat-bridge" }
$PythonExe = Join-Path $RadarRoot ".venv\Scripts\python.exe"
$Exporter = Join-Path $RadarRoot "scripts\export_we_mp_rss_jsonl.py"
$SidecarStarter = Join-Path $SidecarRoot "start-we-mp-rss.ps1"

foreach ($check in @(
        @{ Path = $Exporter; Hint = "RadarRoot is not the AI News Radar repository" },
        @{ Path = $PythonExe; Hint = "Radar venv is missing" },
        @{ Path = $SidecarStarter; Hint = "WeRSS sidecar start script is missing" },
        @{ Path = (Join-Path $BridgeRoot ".git"); Hint = "BridgeRoot is not a git repository" }
    )) {
    if (-not (Test-Path -LiteralPath $check.Path)) {
        throw ("Missing {0}: {1}" -f $check.Path, $check.Hint)
    }
}

function Test-SidecarReady {
    try {
        Invoke-WebRequest -Uri "$BaseUrl/" -UseBasicParsing -TimeoutSec 3 | Out-Null
        return $true
    } catch {
        return $false
    }
}

if (-not (Test-SidecarReady)) {
    Write-Step "WeRSS sidecar is offline; starting it now."
    Start-Process powershell.exe -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $SidecarStarter) -WindowStyle Hidden
    $ready = $false
    for ($attempt = 0; $attempt -lt 20; $attempt++) {
        Start-Sleep -Seconds 2
        if (Test-SidecarReady) { $ready = $true; break }
    }
    if (-not $ready) { throw "WeRSS sidecar did not become ready within 40 seconds." }
}

$tempJsonl = Join-Path $env:TEMP "wechat_contents_latest.jsonl"
Write-Step "Exporting public WeRSS article fields."
& $PythonExe $Exporter --base-url $BaseUrl --out $tempJsonl --max-items $MaxItems
if ($LASTEXITCODE -ne 0) { throw "WeRSS JSONL export failed (exit=$LASTEXITCODE)." }

$bridgeJsonlDir = Join-Path $BridgeRoot "output\wechat\jsonl"
New-Item -ItemType Directory -Force -Path $bridgeJsonlDir | Out-Null
$bridgeJsonl = Join-Path $bridgeJsonlDir "wechat_contents_latest.jsonl"
Copy-Item -LiteralPath $tempJsonl -Destination $bridgeJsonl -Force

$lineCount = 0
Get-Content -LiteralPath $bridgeJsonl -ReadCount 1000 | ForEach-Object { $lineCount += $_.Count }
if ($lineCount -eq 0) { Write-Warning "WeRSS export returned 0 articles; pushing the empty public snapshot is allowed." }
$manifest = [ordered]@{
    generated_at = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    source_file = "wechat_contents_latest.jsonl"
    line_count = $lineCount
    max_items = $MaxItems
}
($manifest | ConvertTo-Json) | Set-Content -LiteralPath (Join-Path $BridgeRoot "manifest.json") -Encoding UTF8

Write-Step "Pushing WeChat bridge repository."
if ((Invoke-Git $BridgeRoot @("pull", "--ff-only")) -ne 0) {
    Write-Warning "Bridge repository pull failed; attempting to commit the local snapshot."
}
Invoke-Git $BridgeRoot @("add", "output/wechat/jsonl/wechat_contents_latest.jsonl", "manifest.json") | Out-Null
& git -C $BridgeRoot diff --cached --quiet
if ($LASTEXITCODE -eq 0) {
    Write-Step "Bridge repository has no changes."
    exit 0
}
if ((Invoke-Git $BridgeRoot @("commit", "-m", "数据：更新微信公众号公开文章 JSONL")) -ne 0) {
    throw "Bridge repository commit failed."
}
if ((Invoke-Git $BridgeRoot @("push")) -ne 0) {
    throw "Bridge repository push failed."
}
Write-Step ("Done: pushed {0} public article rows." -f $lineCount)

param(
    [string]$RadarRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path,
    [string]$SidecarRoot = "",
    [string]$BridgeRoot = "",
    [string]$BaseUrl = "http://127.0.0.1:8001",
    [int]$MaxItems = 20,
    [switch]$SkipSync,
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
$SidecarPython = Join-Path $SidecarRoot ".venv\Scripts\python.exe"
$Syncer = Join-Path $RadarRoot "deploy\local\we_mp_rss_sync_once.py"

# 抓取结果收集在这两个变量里，等脚本最末尾统一红字告警（中途报会被 git 输出刷走）
$fetchFailedAccounts = @()
$fetchWarning = ""

function Show-FetchAlert {
    if ($fetchFailedAccounts.Count -eq 0 -and -not $fetchWarning) {
        return
    }
    Write-Host ""
    Write-Host "==================== 抓取告警 ====================" -ForegroundColor Red
    if ($fetchFailedAccounts.Count -gt 0) {
        Write-Host ("以下公众号本次抓取失败：{0}" -f ($fetchFailedAccounts -join "、")) -ForegroundColor Red
        Write-Host "它们的最新文章没能进库，页面上看到的是旧内容。" -ForegroundColor Red
    }
    if ($fetchWarning) {
        Write-Host $fetchWarning -ForegroundColor Red
    }
    Write-Host "排查建议：打开 http://127.0.0.1:8001 看 sidecar 是否正常；" -ForegroundColor Red
    Write-Host "          若提示登录失效，需要重新扫码登录微信。" -ForegroundColor Red
    Write-Host "=================================================" -ForegroundColor Red
}

# 脚本后半段（导出 / git commit / git push）任何一步 throw 都会跳过末尾的
# Show-FetchAlert，导致抓取告警被异常吞掉 —— 断网时就是这样：抓取失败 + push 也失败，
# 用户只看到 push 报错，完全不知道文章根本没抓到。用 trap 兜住所有终止性错误。
trap {
    Show-FetchAlert
    break
}

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

if ($SkipSync) {
    Write-Step "Skipping WeRSS fetch (-SkipSync)."
} elseif (-not (Test-Path -LiteralPath $SidecarPython)) {
    $fetchWarning = "找不到 sidecar 的 Python：$SidecarPython —— 本次没有抓取新文章，导出的是数据库里的旧数据。"
    Write-Step "Sidecar python missing; skipping fetch."
} else {
    Write-Step "Triggering WeRSS to fetch new articles from WeChat."
    # cwd 必须是 sidecar 根目录：它的 config.yaml / data/db.db 都按相对路径读取
    Push-Location $SidecarRoot
    try {
        $ErrorActionPreference = "Continue"
        # 保留完整输出：抓取脚本崩了的时候，真正的报错就在这里面，不能过滤掉
        $rawOutput = & $SidecarPython $Syncer 2>&1
        $syncExit = $LASTEXITCODE

        # sidecar 的输出里混着大量 SQL 日志，屏幕上只显示我们自己打的进度行
        $syncOutput = $rawOutput | Where-Object { $_ -match '^\[sync\]' }
        $syncOutput | ForEach-Object { Write-Host ("  {0}" -f $_) }

        # 从 "[sync] FAIL 猫笔刀 XxxError: ..." 里把失败的公众号名字捞出来
        $fetchFailedAccounts = @(
            $syncOutput |
                ForEach-Object { [regex]::Match([string]$_, '^\[sync\] FAIL (\S+)') } |
                Where-Object { $_.Success } |
                ForEach-Object { $_.Groups[1].Value }
        )

        # 抓取失败只记录、不中断：库里还有旧数据可导，比整条链路挂掉强
        if ($syncExit -ne 0 -and $fetchFailedAccounts.Count -eq 0) {
            # 兜底：退出码非 0 但没解析到 FAIL 行 —— 说明抓取脚本自己就崩了。
            # 这种情况必须把原始报错吐出来，否则排查全靠猜（2026-07-12 真踩过）。
            Write-Host "  抓取脚本崩溃，原始输出如下：" -ForegroundColor Yellow
            $rawOutput | Select-Object -Last 15 | ForEach-Object { Write-Host ("    {0}" -f $_) -ForegroundColor DarkGray }
            $fetchWarning = "抓取脚本异常退出 (exit=$syncExit)，可能是 sidecar 环境有问题。本次导出的是数据库里的旧数据。"
        }
    } catch {
        $fetchWarning = "抓取步骤本身崩了：$_ —— 本次导出的是数据库里的旧数据。"
    } finally {
        $ErrorActionPreference = "Stop"
        Pop-Location
    }
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
    Show-FetchAlert
    exit 0
}
if ((Invoke-Git $BridgeRoot @("commit", "-m", "数据：更新微信公众号公开文章 JSONL")) -ne 0) {
    throw "Bridge repository commit failed."
}
if ((Invoke-Git $BridgeRoot @("push")) -ne 0) {
    throw "Bridge repository push failed."
}
Write-Step ("Done: pushed {0} public article rows." -f $lineCount)
Show-FetchAlert

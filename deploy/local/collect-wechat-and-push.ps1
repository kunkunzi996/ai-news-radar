param(
    [string]$RadarRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path,
    [string]$SidecarRoot = "",
    [string]$BridgeRoot = "",
    [string]$BaseUrl = "http://127.0.0.1:8001",
    [int]$MaxItems = 20,
    [switch]$SkipSync,
    [string]$LogFile = "",
    [string]$StatusFile = ""
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

function Invoke-GitText([string]$RepoDir, [string[]]$GitArgs) {
    $oldPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $output = @(& git -C $RepoDir @GitArgs 2>&1 | ForEach-Object { [string]$_ })
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $oldPreference
    }
    if ($code -ne 0) { throw "git $($GitArgs -join ' ') failed (exit=$code): $($output -join ' | ')" }
    return $output
}

function Assert-RemoteHead([string]$RepoDir) {
    $branch = ([string](Invoke-GitText $RepoDir @("branch", "--show-current") | Select-Object -First 1)).Trim()
    if (-not $branch) { throw "Cannot determine bridge branch: $RepoDir" }
    $localHead = ([string](Invoke-GitText $RepoDir @("rev-parse", "HEAD") | Select-Object -First 1)).Trim()
    $remoteLine = ([string](Invoke-GitText $RepoDir @("ls-remote", "--exit-code", "origin", "refs/heads/$branch") | Select-Object -First 1)).Trim()
    $remoteHead = ($remoteLine -split "\s+")[0]
    if ($localHead -ne $remoteHead) { throw "Bridge local/remote HEAD mismatch: $RepoDir" }
    return $localHead
}

$script:RunId = [guid]::NewGuid().ToString("N")
$script:StartedAt = (Get-Date).ToUniversalTime().ToString("o")
$script:PipelineMutex = $null
$script:MutexAcquired = $false
$script:MayWriteStatus = $false
$script:FailureStage = "unhandled_error"
$script:TempJsonl = ""
$script:Status = [ordered]@{
    schema_version = 1
    channel = "wechat"
    run_id = $script:RunId
    state = "running"
    stage = "starting"
    started_at = $script:StartedAt
    finished_at = $null
    exit_code = $null
    message = "Starting WeChat collection."
    login_state = "not_applicable"
    source_file = ""
    source_last_write_time = $null
    source_sha256 = ""
    output_rows = 0
    crawl_output_rows = 0
    new_unique_items = 0
    requested_creator_count = 0
    completed_creator_count = 0
    failed_creator_count = 0
    creator_results = @()
    content_changed = $false
    bridge_changed = $false
    bridge_head_before = ""
    bridge_head_after = ""
    warnings = @()
}

function Write-AtomicJson([string]$Path, [object]$Value, [string]$RunId) {
    if (-not $Path) { return }
    $directory = Split-Path -Parent $Path
    if ($directory -and -not (Test-Path -LiteralPath $directory)) { [IO.Directory]::CreateDirectory($directory) | Out-Null }
    $temp = "$Path.$RunId.tmp"
    $json = $Value | ConvertTo-Json -Depth 12
    $encoding = New-Object Text.UTF8Encoding($false)
    $stream = New-Object IO.FileStream($temp, [IO.FileMode]::Create, [IO.FileAccess]::Write, [IO.FileShare]::None)
    try {
        $writer = New-Object IO.StreamWriter($stream, $encoding)
        try { $writer.Write($json); $writer.Write("`n"); $writer.Flush(); $stream.Flush($true) } finally { $writer.Dispose() }
    } finally {
        if ($stream) { $stream.Dispose() }
    }
    if (Test-Path -LiteralPath $Path) {
        $replaceBackup = "$Path.$RunId.replace-backup"
        if (Test-Path -LiteralPath $replaceBackup) { [IO.File]::Delete($replaceBackup) }
        [IO.File]::Replace($temp, $Path, $replaceBackup)
        if (Test-Path -LiteralPath $replaceBackup) { [IO.File]::Delete($replaceBackup) }
    } else {
        [IO.File]::Move($temp, $Path)
    }
}

function Write-RunStatus {
    if ($StatusFile) { Write-AtomicJson $StatusFile $script:Status $script:RunId }
}

function Complete-RunStatus([string]$State, [string]$Stage, [string]$Message, [int]$ExitCode) {
    $script:Status.state = $State
    $script:Status.stage = $Stage
    $script:Status.message = $Message
    $script:Status.exit_code = $ExitCode
    $script:Status.finished_at = (Get-Date).ToUniversalTime().ToString("o")
    Write-RunStatus
}

function Release-PipelineMutex {
    if ($script:PipelineMutex) {
        if ($script:MutexAcquired) { try { $script:PipelineMutex.ReleaseMutex() } catch {} }
        $script:PipelineMutex.Dispose()
        $script:PipelineMutex = $null
        $script:MutexAcquired = $false
    }
}

function Exit-Run([string]$State, [string]$Stage, [string]$Message, [int]$ExitCode) {
    Complete-RunStatus $State $Stage $Message $ExitCode
    if ($State -eq "succeeded" -and $script:TempJsonl -and (Test-Path -LiteralPath $script:TempJsonl)) {
        Remove-Item -LiteralPath $script:TempJsonl -Force
    }
    Release-PipelineMutex
    if ($LogFile) { try { Stop-Transcript | Out-Null } catch {} }
    exit $ExitCode
}

$script:PipelineMutex = New-Object Threading.Mutex($false, "Local\AI-News-Radar-WeChat-CollectAndPush")
try {
    $script:MutexAcquired = $script:PipelineMutex.WaitOne(0)
} catch [Threading.AbandonedMutexException] {
    $script:MutexAcquired = $true
}
if (-not $script:MutexAcquired) {
    [Console]::Error.WriteLine("busy: WeChat collection pipeline is already running")
    $script:PipelineMutex.Dispose()
    exit 2
}
$script:MayWriteStatus = $true
Write-RunStatus

trap {
    $message = [string]$_
    if ($script:MayWriteStatus) {
        try { Complete-RunStatus "failed" $script:FailureStage $message 1 } catch { [Console]::Error.WriteLine("status write failed: $_") }
    }
    Release-PipelineMutex
    if ($LogFile) { try { Stop-Transcript | Out-Null } catch {} }
    [Console]::Error.WriteLine($message)
    exit 1
}

$script:FailureStage = "preflight"
$script:Status.stage = "preflight"
Write-RunStatus
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

$script:FailureStage = "bridge_preflight"
$bridgeDirty = @((Invoke-GitText $BridgeRoot @("status", "--porcelain")) | Where-Object { $_ })
if ($bridgeDirty.Count -gt 0) { throw "WeChat bridge has existing changes; refusing to continue." }
Invoke-GitText $BridgeRoot @("pull", "--ff-only") | Out-Null
$bridgeHeadBefore = ([string](Invoke-GitText $BridgeRoot @("rev-parse", "HEAD") | Select-Object -First 1)).Trim()
$script:Status.bridge_head_before = $bridgeHeadBefore
$script:Status.bridge_head_after = $bridgeHeadBefore

function Test-SidecarReady {
    try {
        Invoke-WebRequest -Uri "$BaseUrl/" -UseBasicParsing -TimeoutSec 3 | Out-Null
        return $true
    } catch {
        return $false
    }
}

if (-not (Test-SidecarReady)) {
    $script:FailureStage = "sidecar_start"
    $script:Status.stage = "starting_sidecar"
    Write-RunStatus
    Write-Step "WeRSS sidecar is offline; starting it now."
    $sidecarArgs = '--headless powershell.exe -NoProfile -ExecutionPolicy Bypass -File "{0}"' -f $SidecarStarter
    Start-Process -FilePath "$env:SystemRoot\System32\conhost.exe" -ArgumentList $sidecarArgs
    $ready = $false
    for ($attempt = 0; $attempt -lt 20; $attempt++) {
        Start-Sleep -Seconds 2
        if (Test-SidecarReady) { $ready = $true; break }
    }
    if (-not $ready) { throw "WeRSS sidecar did not become ready within 40 seconds." }
}

if ($SkipSync) {
    $fetchWarning = "WeRSS fetch was skipped by -SkipSync; bridge was not changed."
    Write-Step "Skipping WeRSS fetch (-SkipSync)."
} elseif (-not (Test-Path -LiteralPath $SidecarPython)) {
    $fetchWarning = "找不到 sidecar 的 Python：$SidecarPython —— 本次没有抓取新文章，导出的是数据库里的旧数据。"
    Write-Step "Sidecar python missing; skipping fetch."
} else {
    $script:FailureStage = "wechat_fetch"
    $script:Status.stage = "fetching"
    Write-RunStatus
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

$script:Status.warnings = @(
    @($fetchFailedAccounts | ForEach-Object { "WeChat fetch failed: $_" })
    if ($fetchWarning) { $fetchWarning }
)

$script:FailureStage = "export"
$script:Status.stage = "exporting"
Write-RunStatus
$script:TempJsonl = Join-Path $env:TEMP ("wechat-contents-{0}.jsonl" -f $script:RunId)
Write-Step "Exporting public WeRSS article fields."
& $PythonExe $Exporter --base-url $BaseUrl --out $script:TempJsonl --max-items $MaxItems
if ($LASTEXITCODE -ne 0) { throw "WeRSS JSONL export failed (exit=$LASTEXITCODE)." }
$lineCount = 0
Get-Content -LiteralPath $script:TempJsonl -ReadCount 1000 | ForEach-Object { $lineCount += $_.Count }
$sourceHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $script:TempJsonl).Hash
$sourceItem = Get-Item -LiteralPath $script:TempJsonl
$script:Status.source_file = $script:TempJsonl
$script:Status.source_last_write_time = $sourceItem.LastWriteTimeUtc.ToString("o")
$script:Status.source_sha256 = $sourceHash
$script:Status.output_rows = $lineCount
if ($lineCount -eq 0) { $script:Status.warnings += "WeRSS export returned 0 articles." }

# 抓取失败时可以留下导出产物排错，但绝不能覆盖 bridge 或伪装成功。
if ($fetchFailedAccounts.Count -gt 0 -or $fetchWarning) {
    Show-FetchAlert
    Exit-Run "warning" "fetch_warning" "WeChat fetch was incomplete; diagnostic export was retained and bridge was not changed." 1
}

$bridgeJsonlDir = Join-Path $BridgeRoot "output\wechat\jsonl"
$bridgeJsonl = Join-Path $bridgeJsonlDir "wechat_contents_latest.jsonl"
$manifestPath = Join-Path $BridgeRoot "manifest.json"
$targetHashBefore = if (Test-Path -LiteralPath $bridgeJsonl) { (Get-FileHash -Algorithm SHA256 -LiteralPath $bridgeJsonl).Hash } else { "" }
$contentChanged = (-not $targetHashBefore) -or $targetHashBefore.ToLowerInvariant() -ne $sourceHash.ToLowerInvariant()
$script:Status.content_changed = $contentChanged
$manifestNeedsMigration = $true
if (Test-Path -LiteralPath $manifestPath) {
    try {
        $existingManifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
        $manifestNeedsMigration = [int]$existingManifest.schema_version -ne 1
    } catch { $script:Status.warnings += "Existing manifest is invalid and will be replaced after a successful fetch." }
}
if ($contentChanged) {
    [IO.Directory]::CreateDirectory($bridgeJsonlDir) | Out-Null
    Copy-Item -LiteralPath $script:TempJsonl -Destination $bridgeJsonl -Force
    if ((Get-FileHash -Algorithm SHA256 -LiteralPath $bridgeJsonl).Hash.ToLowerInvariant() -ne $sourceHash.ToLowerInvariant()) {
        throw "Bridge JSONL SHA256 does not match the export after copy."
    }
}
if ($contentChanged -or $manifestNeedsMigration) {
    $manifest = [ordered]@{
        schema_version = 1
        generated_at = (Get-Date).ToUniversalTime().ToString("o")
        source_file = "wechat_contents_latest.jsonl"
        source_sha256 = $sourceHash
        output_rows = $lineCount
        max_items = $MaxItems
    }
    Write-AtomicJson $manifestPath $manifest "$($script:RunId)-manifest"
}

$script:FailureStage = "bridge_update"
if ((Invoke-Git $BridgeRoot @("add", "--", "output/wechat/jsonl/wechat_contents_latest.jsonl", "manifest.json")) -ne 0) {
    throw "Precise bridge staging failed."
}
& git -C $BridgeRoot diff --cached --quiet
$script:Status.bridge_changed = $LASTEXITCODE -ne 0
if (-not $script:Status.bridge_changed) {
    $script:Status.bridge_head_after = Assert-RemoteHead $BridgeRoot
    Exit-Run "succeeded" "completed_no_change" ("WeChat fetch completed with {0} exported rows; bridge bytes are unchanged." -f $lineCount) 0
}
$stage = if ($contentChanged) { "completed_pushed" } else { "completed_pushed_metadata_only" }
$commitMessage = if ($contentChanged) { "数据：更新微信公众号公开文章 JSONL" } else { "数据：迁移微信公众号桥接清单格式" }
if ((Invoke-Git $BridgeRoot @("commit", "-m", $commitMessage)) -ne 0) { throw "Bridge repository commit failed." }
if ((Invoke-Git $BridgeRoot @("push")) -ne 0) { throw "Bridge repository push failed." }
$script:Status.bridge_head_after = Assert-RemoteHead $BridgeRoot
Exit-Run "succeeded" $stage ("WeChat fetch completed and pushed {0} exported rows." -f $lineCount) 0

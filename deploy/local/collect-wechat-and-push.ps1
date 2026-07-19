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
$script:TempAuthority = ""
$script:TempSnapshot = ""
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
    login_state = "not_checked"
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
    if ($State -eq "succeeded") {
        foreach ($tempPath in @($script:TempJsonl, $script:TempAuthority, $script:TempSnapshot)) {
            if ($tempPath -and (Test-Path -LiteralPath $tempPath)) { Remove-Item -LiteralPath $tempPath -Force }
        }
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
$syncAttempted = $false
$syncExit = 0
$syncOutput = @()
$hasParseableSyncOutput = $false

function Update-CollectionHealthMetadata(
    [bool]$SyncAttempted,
    [object[]]$SyncOutput,
    [bool]$HasParseableSyncOutput,
    [int]$SyncExit,
    [int]$FailedCreatorCount,
    [bool]$SyncSkipped
) {
    $script:Status.failed_creator_count = [Math]::Max(0, $FailedCreatorCount)
    $syncText = (@($SyncOutput) | ForEach-Object { [string]$_ }) -join "`n"

    if ($syncText -match 'Invalid\s+Session|session\s+(?:invalid|expired)|登录\s*(?:失效|过期)|凭证\s*(?:失效|过期)') {
        $script:Status.login_state = "expired"
    } elseif (
        $SyncAttempted -and
        $HasParseableSyncOutput -and
        -not $SyncSkipped -and
        $SyncExit -eq 0 -and
        $FailedCreatorCount -eq 0
    ) {
        $script:Status.login_state = "valid"
    } else {
        $script:Status.login_state = "unknown"
    }

    Write-RunStatus
}

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
if (-not $SkipSync) { Invoke-GitText $BridgeRoot @("pull", "--ff-only") | Out-Null }
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

if (-not (Test-Path -LiteralPath $SidecarPython)) {
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
        $script:TempAuthority = Join-Path $env:TEMP ("wechat-authority-{0}.json" -f $script:RunId)
        # 保留完整输出：抓取脚本崩了的时候，真正的报错就在这里面，不能过滤掉
        $syncArgs = @($Syncer, "--subscriptions-out", $script:TempAuthority)
        if ($SkipSync) { $syncArgs += "--snapshot-only" }
        $oldConsoleOutputEncoding = [Console]::OutputEncoding
        $oldOutputEncoding = $OutputEncoding
        try {
            # 计划任务没有控制台时，Windows PowerShell 5.1 会错误解码 UTF-8 的 Python 输出。
            # 同步脚本的中文登录失效提示必须按 UTF-8 读入，才能写出正确的安全状态码。
            [Console]::OutputEncoding = [Text.Encoding]::UTF8
            $OutputEncoding = [Text.Encoding]::UTF8
            $rawOutput = & $SidecarPython @syncArgs 2>&1
            $syncExit = $LASTEXITCODE
            $syncAttempted = $true
        } finally {
            [Console]::OutputEncoding = $oldConsoleOutputEncoding
            $OutputEncoding = $oldOutputEncoding
        }

        # sidecar 的输出里混着大量 SQL 日志，屏幕上只显示我们自己打的进度行
        $syncOutput = @($rawOutput | Where-Object { $_ -match '^\[sync\]' })
        $hasParseableSyncOutput = $syncOutput.Count -gt 0
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
        } elseif ($SkipSync) {
            $fetchWarning = "WeRSS fetch was skipped by -SkipSync; diagnostic files were generated in TEMP and bridge was not changed."
        }
    } catch {
        $fetchWarning = "抓取步骤本身崩了：$_ —— 本次导出的是数据库里的旧数据。"
    } finally {
        $ErrorActionPreference = "Stop"
        Pop-Location
    }
}

Update-CollectionHealthMetadata `
    -SyncAttempted $syncAttempted `
    -SyncOutput $syncOutput `
    -HasParseableSyncOutput $hasParseableSyncOutput `
    -SyncExit $syncExit `
    -FailedCreatorCount $fetchFailedAccounts.Count `
    -SyncSkipped ([bool]$SkipSync)

$script:Status.warnings = @(
    @($fetchFailedAccounts | ForEach-Object { "WeChat fetch failed: $_" })
    if ($fetchWarning) { $fetchWarning }
)

$script:FailureStage = "export"
$script:Status.stage = "exporting"
Write-RunStatus
$script:TempJsonl = Join-Path $env:TEMP ("wechat-contents-{0}.jsonl" -f $script:RunId)
$script:TempSnapshot = Join-Path $env:TEMP ("wechat-subscriptions-{0}.json" -f $script:RunId)
if (-not $script:TempAuthority -or -not (Test-Path -LiteralPath $script:TempAuthority)) {
    Show-FetchAlert
    Exit-Run "warning" "authority_unavailable" "Authoritative subscription input was not produced; bridge was not changed." 1
}

function Get-Sha256([string]$Path) {
    $stream = [IO.File]::OpenRead($Path)
    try {
        $sha = [Security.Cryptography.SHA256]::Create()
        try { return ([BitConverter]::ToString($sha.ComputeHash($stream))).Replace("-", "").ToLowerInvariant() }
        finally { $sha.Dispose() }
    } finally {
        $stream.Dispose()
    }
}

function Test-BridgeFailureInjection([string]$Stage, [int]$ReplaceIndex = 0) {
    # 双重 test-only 门：生产默认不读取故障点，任意普通参数也无法触发。
    if ($env:WE_MP_RSS_ENABLE_TEST_FAILURES -ne "1") { return $false }
    if ($Stage -eq "replace") {
        return [int]($env:WE_MP_RSS_TEST_FAIL_AFTER_REPLACE -as [int]) -eq $ReplaceIndex
    }
    if ($Stage -eq "git_add") { return $env:WE_MP_RSS_TEST_FAIL_GIT_ADD -eq "1" }
    return $false
}
Write-Step "Exporting public WeRSS article fields."
$previousSnapshot = Join-Path $BridgeRoot "output\wechat\jsonl\wechat_subscriptions_latest.json"
$exportArgs = @(
    $Exporter,
    "--base-url", $BaseUrl,
    "--subscriptions-in", $script:TempAuthority,
    "--out", $script:TempJsonl,
    "--snapshot-out", $script:TempSnapshot,
    "--max-items", $MaxItems
)
if (Test-Path -LiteralPath $previousSnapshot) { $exportArgs += @("--previous-snapshot", $previousSnapshot) }
& $PythonExe @exportArgs
if ($LASTEXITCODE -ne 0) { throw "WeRSS JSONL export failed (exit=$LASTEXITCODE)." }
$lineCount = 0
Get-Content -LiteralPath $script:TempJsonl -ReadCount 1000 | ForEach-Object { $lineCount += $_.Count }
$sourceHash = Get-Sha256 $script:TempJsonl
$sourceItem = Get-Item -LiteralPath $script:TempJsonl
$script:Status.source_file = $script:TempJsonl
$script:Status.source_last_write_time = $sourceItem.LastWriteTimeUtc.ToString("o")
$script:Status.source_sha256 = $sourceHash
$script:Status.output_rows = $lineCount
if ($lineCount -eq 0) { $script:Status.warnings += "WeRSS export returned 0 articles." }

# -SkipSync 只允许产出 TEMP 诊断文件；不 pull、不替换、不暂存、不 commit。
if ($SkipSync) {
    $headAfterDiagnostic = ([string](Invoke-GitText $BridgeRoot @("rev-parse", "HEAD") | Select-Object -First 1)).Trim()
    if ($headAfterDiagnostic -ne $bridgeHeadBefore) { throw "-SkipSync changed bridge HEAD unexpectedly." }
    Show-FetchAlert
    Exit-Run "warning" "skip_sync_diagnostic_only" "Diagnostic export completed; bridge HEAD and formal files were not changed." 1
}

# 抓取失败时可以留下导出产物排错，但绝不能覆盖 bridge 或伪装成功。
if ($fetchFailedAccounts.Count -gt 0 -or $fetchWarning) {
    Show-FetchAlert
    Exit-Run "warning" "fetch_warning" "WeChat fetch was incomplete; diagnostic export was retained and bridge was not changed." 1
}

$bridgeJsonlDir = Join-Path $BridgeRoot "output\wechat\jsonl"
$bridgeJsonl = Join-Path $bridgeJsonlDir "wechat_contents_latest.jsonl"
$bridgeSnapshot = Join-Path $bridgeJsonlDir "wechat_subscriptions_latest.json"
$manifestPath = Join-Path $BridgeRoot "manifest.json"
$targetHashBefore = if (Test-Path -LiteralPath $bridgeJsonl) { Get-Sha256 $bridgeJsonl } else { "" }
$contentChanged = (-not $targetHashBefore) -or $targetHashBefore.ToLowerInvariant() -ne $sourceHash.ToLowerInvariant()
$script:Status.content_changed = $contentChanged

function ConvertTo-SemanticJson([string]$Path, [string]$Kind) {
    if (-not (Test-Path -LiteralPath $Path)) { return "" }
    $value = Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($Kind -eq "snapshot") {
        $feeds = @($value.feeds | Sort-Object { [string]$_.feed_id } | ForEach-Object {
            [ordered]@{ feed_id = [string]$_.feed_id; account = [string]$_.account; status = [int]$_.status; active = [bool]$_.active }
        })
        $semantic = [ordered]@{
            schema_version = [int]$value.schema_version; complete = [bool]$value.complete; reason = $value.reason
            authority_source = [string]$value.authority_source; retention_policy = [string]$value.retention_policy
            active_policy = [string]$value.active_policy; source_jsonl_sha256 = ([string]$value.source_jsonl_sha256).ToLowerInvariant()
            known_count = [int]$value.known_count; active_count = [int]$value.active_count
            empty_confirmations = [int]$value.empty_confirmations; feeds = $feeds
        }
    } else {
        $semantic = [ordered]@{
            schema_version = [int]$value.schema_version; article_file = [string]$value.article_file
            article_sha256 = ([string]$value.article_sha256).ToLowerInvariant(); subscription_file = [string]$value.subscription_file
            subscription_sha256 = ([string]$value.subscription_sha256).ToLowerInvariant(); output_rows = [int]$value.output_rows
            known_feed_count = [int]$value.known_feed_count; active_feed_count = [int]$value.active_feed_count
            max_items = [int]$value.max_items
        }
    }
    return ($semantic | ConvertTo-Json -Depth 12 -Compress)
}

$snapshotValue = Get-Content -LiteralPath $script:TempSnapshot -Raw -Encoding UTF8 | ConvertFrom-Json
if (-not [bool]$snapshotValue.complete) { throw "Subscription snapshot is not complete; refusing bridge publication." }
if (([string]$snapshotValue.source_jsonl_sha256).ToLowerInvariant() -ne $sourceHash.ToLowerInvariant()) {
    throw "Subscription snapshot JSONL SHA256 mismatch."
}
if ([int]$snapshotValue.active_count -ne @($snapshotValue.feeds | Where-Object { [bool]$_.active }).Count) {
    throw "Subscription snapshot active count mismatch."
}
if ([int]$snapshotValue.known_count -ne @($snapshotValue.feeds).Count) {
    throw "Subscription snapshot known count mismatch."
}
$snapshotChanged = (ConvertTo-SemanticJson $script:TempSnapshot "snapshot") -ne (ConvertTo-SemanticJson $bridgeSnapshot "snapshot")
# 语义没变时沿用已发布快照的真实字节哈希；否则 generated_at/数组顺序会间接让 manifest 误判变化。
$snapshotHash = if (-not $snapshotChanged -and (Test-Path -LiteralPath $bridgeSnapshot)) {
    Get-Sha256 $bridgeSnapshot
} else {
    Get-Sha256 $script:TempSnapshot
}
$tempManifest = Join-Path $env:TEMP ("wechat-manifest-{0}.json" -f $script:RunId)
$manifest = [ordered]@{
    schema_version = 2
    generated_at = (Get-Date).ToUniversalTime().ToString("o")
    article_file = "output/wechat/jsonl/wechat_contents_latest.jsonl"
    article_sha256 = $sourceHash.ToLowerInvariant()
    subscription_file = "output/wechat/jsonl/wechat_subscriptions_latest.json"
    subscription_sha256 = $snapshotHash
    output_rows = $lineCount
    known_feed_count = [int]$snapshotValue.known_count
    active_feed_count = [int]$snapshotValue.active_count
    max_items = $MaxItems
}
Write-AtomicJson $tempManifest $manifest "$($script:RunId)-candidate"
$manifestChanged = (ConvertTo-SemanticJson $tempManifest "manifest") -ne (ConvertTo-SemanticJson $manifestPath "manifest")

if ($contentChanged -or $snapshotChanged -or $manifestChanged) {
    [IO.Directory]::CreateDirectory($bridgeJsonlDir) | Out-Null
    $targets = @($bridgeJsonl, $bridgeSnapshot, $manifestPath)
    # snapshot 语义没变时必须复用旧文件真实字节，否则 manifest-only 变化会绑定旧 hash、却发布新 generated_at 字节。
    $publishedSnapshotCandidate = if ($snapshotChanged) { $script:TempSnapshot } else { $bridgeSnapshot }
    $candidates = @($script:TempJsonl, $publishedSnapshotCandidate, $tempManifest)
    $backups = @()
    try {
        for ($i = 0; $i -lt $targets.Count; $i++) {
            $backup = Join-Path $env:TEMP ("wechat-bridge-backup-{0}-{1}" -f $script:RunId, $i)
            if (Test-Path -LiteralPath $targets[$i]) { Copy-Item -LiteralPath $targets[$i] -Destination $backup -Force; $backups += $backup } else { $backups += "" }
        }
        for ($i = 0; $i -lt $targets.Count; $i++) {
            $replaceTemp = "$($targets[$i]).$($script:RunId).tmp"
            Copy-Item -LiteralPath $candidates[$i] -Destination $replaceTemp -Force
            if (Test-Path -LiteralPath $targets[$i]) {
                $atomicBackup = "$($targets[$i]).$($script:RunId).replace-backup"
                [IO.File]::Replace($replaceTemp, $targets[$i], $atomicBackup)
                if (Test-Path -LiteralPath $atomicBackup) { Remove-Item -LiteralPath $atomicBackup -Force }
            } else {
                [IO.File]::Move($replaceTemp, $targets[$i])
            }
            if (Test-BridgeFailureInjection "replace" ($i + 1)) {
                throw "Injected bridge transaction failure after replacement $($i + 1)."
            }
        }
        if ((Get-Sha256 $bridgeJsonl) -ne $sourceHash.ToLowerInvariant()) { throw "Published article hash mismatch." }
        if ((Get-Sha256 $bridgeSnapshot) -ne $snapshotHash) { throw "Published snapshot hash mismatch." }
        if ((Invoke-Git $BridgeRoot @("add", "--", "output/wechat/jsonl/wechat_contents_latest.jsonl", "output/wechat/jsonl/wechat_subscriptions_latest.json", "manifest.json")) -ne 0) {
            throw "Precise bridge staging failed."
        }
        if (Test-BridgeFailureInjection "git_add") { throw "Injected precise bridge staging failure." }
    } catch {
        $transactionError = $_
        for ($i = 0; $i -lt $targets.Count; $i++) {
            if ($backups[$i]) {
                Copy-Item -LiteralPath $backups[$i] -Destination $targets[$i] -Force
            } elseif (Test-Path -LiteralPath $targets[$i]) {
                Remove-Item -LiteralPath $targets[$i] -Force
            }
        }
        # preflight 保证 bridge 初始干净，因此只撤销本轮三个明确路径的 index 变化，不碰其它路径。
        & git -C $BridgeRoot diff --cached --quiet -- "output/wechat/jsonl/wechat_contents_latest.jsonl" "output/wechat/jsonl/wechat_subscriptions_latest.json" "manifest.json"
        if ($LASTEXITCODE -ne 0) {
            if ((Invoke-Git $BridgeRoot @("restore", "--staged", "--", "output/wechat/jsonl/wechat_contents_latest.jsonl", "output/wechat/jsonl/wechat_subscriptions_latest.json", "manifest.json")) -ne 0) {
                throw "Bridge rollback restored files but failed to clear precise staging: $transactionError"
            }
        }
        # 精确刷新三路径；若内容并未恢复到前态，cached diff 闸必须拦住并再次撤销 staging。
        $refreshIndexCode = Invoke-Git $BridgeRoot @("add", "-A", "--", "output/wechat/jsonl/wechat_contents_latest.jsonl", "output/wechat/jsonl/wechat_subscriptions_latest.json", "manifest.json")
        if ($refreshIndexCode -ne 0) {
            Invoke-Git $BridgeRoot @("restore", "--staged", "--", "output/wechat/jsonl/wechat_contents_latest.jsonl", "output/wechat/jsonl/wechat_subscriptions_latest.json", "manifest.json") | Out-Null
            throw "Bridge rollback restored bytes but failed to refresh precise index paths: $transactionError"
        }
        & git -C $BridgeRoot diff --cached --quiet -- "output/wechat/jsonl/wechat_contents_latest.jsonl" "output/wechat/jsonl/wechat_subscriptions_latest.json" "manifest.json"
        if ($LASTEXITCODE -ne 0) {
            Invoke-Git $BridgeRoot @("restore", "--staged", "--", "output/wechat/jsonl/wechat_contents_latest.jsonl", "output/wechat/jsonl/wechat_subscriptions_latest.json", "manifest.json") | Out-Null
            throw "Bridge rollback left staged content changes on precise paths: $transactionError"
        }
        throw $transactionError
    }
}

$script:FailureStage = "bridge_update"
& git -C $BridgeRoot diff --cached --quiet
$script:Status.bridge_changed = $LASTEXITCODE -ne 0
if (-not $script:Status.bridge_changed) {
    $script:Status.bridge_head_after = Assert-RemoteHead $BridgeRoot
    Exit-Run "succeeded" "completed_no_change" ("WeChat fetch completed with {0} exported rows; bridge bytes are unchanged." -f $lineCount) 0
}
$stage = if ($contentChanged) { "completed_pushed" } else { "completed_pushed_subscription_only" }
$commitMessage = if ($contentChanged) { "数据：更新微信公众号公开文章与订阅快照" } else { "数据：更新微信公众号订阅快照" }
if ((Invoke-Git $BridgeRoot @("commit", "-m", $commitMessage)) -ne 0) { throw "Bridge repository commit failed." }
if ((Invoke-Git $BridgeRoot @("push")) -ne 0) { throw "Bridge repository push failed." }
$script:Status.bridge_head_after = Assert-RemoteHead $BridgeRoot
Exit-Run "succeeded" $stage ("WeChat fetch completed and pushed {0} exported rows." -f $lineCount) 0

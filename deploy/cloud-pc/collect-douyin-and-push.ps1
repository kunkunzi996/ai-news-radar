# 云电脑抖音采集 + 桥接仓库推送脚本
#
# 用途：在 24 小时在线的云 Windows 上定时运行——
#   1. 拉取主仓库最新代码（获取最新的抖音博主配置）。
#   2. 从 config/online-sources.json 读取启用的抖音博主。
#   3. 调用 MediaCrawler（经 scripts/run_mediacrawler_douyin.py）抓取博主最新作品。
#   4. 把最新 creator JSONL 复制进私有桥接仓库并 git push。
#      GitHub Actions 刷新时会克隆桥接仓库读取该 JSONL。
#
# 依赖：git、MediaCrawler 及其 venv、已扫码登录的 Chrome profile（首次手动运行完成扫码）。
# 兼容 Windows PowerShell 5.1；计划任务需以"仅当用户登录时运行"方式执行（Chrome 非 headless）。
#
# 示例（手动首跑，完成抖音扫码登录）：
#   powershell -ExecutionPolicy Bypass -File deploy\cloud-pc\collect-douyin-and-push.ps1 `
#     -CrawlerRoot D:\ai-news\MediaCrawler -BridgeRoot D:\ai-news\douyin-bridge

param(
    # AI News Radar 主仓库根目录（默认取本脚本所在仓库）
    [string]$RadarRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path,
    # MediaCrawler 仓库根目录
    [string]$CrawlerRoot = "",
    # 私有桥接仓库本地克隆目录
    [string]$BridgeRoot = "",
    # MediaCrawler venv 的 python（默认 <CrawlerRoot>\.venv\Scripts\python.exe）
    [string]$PythonExe = "",
    # 每个博主最多抓最近几条作品
    [int]$MaxNotes = 10,
    # 覆盖博主列表（逗号分隔 sec_uid），默认从线上配置读取
    [string]$CreatorIds = "",
    # 跳过主仓库 git pull（调试用）
    [switch]$SkipGitPull,
    # 把采集专用浏览器移到虚拟桌面外（计划任务专用）
    [switch]$BrowserOffscreen,
    # 日志文件路径（留空不记录；计划任务传入以便无人值守排查）
    [string]$LogFile = "",
    # 本轮机器可判定状态；conhost 不透传子进程退出码，因此计划任务必须传入
    [string]$StatusFile = ""
)

$ErrorActionPreference = "Stop"
if ($LogFile) {
    try { Start-Transcript -Path $LogFile -Append | Out-Null } catch { Write-Warning "日志启动失败：$_" }
}
$env:PYTHONIOENCODING = "utf-8"

function Write-Step([string]$Message) {
    Write-Host ("[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message)
}

function Invoke-Git([string]$RepoDir, [string[]]$GitArgs) {
    # git 会把正常进度信息写到 stderr（如 push 的 "To https://..."）。
    # Windows PowerShell 5.1 下 2>&1 + ErrorActionPreference=Stop 会把这些行误判为异常，
    # 所以本函数内降级为 Continue，成败只看 $LASTEXITCODE。
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
$script:PipelineLock = $null
$script:OwnerFile = Join-Path $env:TEMP "ai-news-radar-mediacrawler.pipeline.owner.json"
$script:LockToken = ""
$script:CrawlResultFile = ""
$script:MayWriteStatus = $false
$script:FailureStage = "unhandled_error"
$script:Status = [ordered]@{
    schema_version = 1
    channel = "douyin"
    run_id = $script:RunId
    state = "running"
    stage = "starting"
    started_at = $script:StartedAt
    finished_at = $null
    exit_code = $null
    message = "Starting Douyin collection."
    login_state = "unknown"
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
    if ($directory -and -not (Test-Path -LiteralPath $directory)) {
        [IO.Directory]::CreateDirectory($directory) | Out-Null
    }
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

function Release-PipelineLock {
    if ($script:OwnerFile -and (Test-Path -LiteralPath $script:OwnerFile)) {
        try {
            $owner = Get-Content -LiteralPath $script:OwnerFile -Raw -Encoding UTF8 | ConvertFrom-Json
            if ([string]$owner.run_id -eq $script:RunId) {
                Remove-Item -LiteralPath $script:OwnerFile -Force
            }
        } catch { Write-Warning "Could not inspect/remove this run's lock owner file: $_" }
    }
    if ($script:PipelineLock) { $script:PipelineLock.Dispose(); $script:PipelineLock = $null }
    Remove-Item Env:AI_NEWS_RADAR_COLLECTION_LOCK_TOKEN -ErrorAction SilentlyContinue
}

function Remove-RunResult {
    if ($script:CrawlResultFile -and (Test-Path -LiteralPath $script:CrawlResultFile)) {
        Remove-Item -LiteralPath $script:CrawlResultFile -Force
    }
}

function Exit-Run([string]$State, [string]$Stage, [string]$Message, [int]$ExitCode) {
    Complete-RunStatus $State $Stage $Message $ExitCode
    Remove-RunResult
    Release-PipelineLock
    if ($LogFile) { try { Stop-Transcript | Out-Null } catch {} }
    exit $ExitCode
}

# 独占锁必须覆盖采集、复制、commit 和 push；抢不到时不能覆盖另一个实例的 canonical status。
$lockPath = Join-Path $env:TEMP "ai-news-radar-mediacrawler.pipeline.lock"
try {
    $script:PipelineLock = New-Object IO.FileStream(
        $lockPath,
        [IO.FileMode]::OpenOrCreate,
        [IO.FileAccess]::ReadWrite,
        [IO.FileShare]::None
    )
} catch {
    [Console]::Error.WriteLine("busy: Douyin collection pipeline is already running")
    exit 2
}

$tokenBytes = New-Object byte[] 32
$rng = [Security.Cryptography.RandomNumberGenerator]::Create()
try { $rng.GetBytes($tokenBytes) } finally { $rng.Dispose() }
$script:LockToken = [Convert]::ToBase64String($tokenBytes)
$sha = [Security.Cryptography.SHA256]::Create()
try { $tokenHash = ([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($script:LockToken)))).Replace("-", "").ToLowerInvariant() } finally { $sha.Dispose() }
$owner = [ordered]@{ owner_pid = $PID; run_id = $script:RunId; token_sha256 = $tokenHash }
Write-AtomicJson $script:OwnerFile $owner $script:RunId
$env:AI_NEWS_RADAR_COLLECTION_LOCK_TOKEN = $script:LockToken
$script:MayWriteStatus = $true
Write-RunStatus

trap {
    $message = [string]$_
    $statusWritten = $false
    if ($script:MayWriteStatus) {
        try { Complete-RunStatus "failed" $script:FailureStage $message 1; $statusWritten = $true } catch { [Console]::Error.WriteLine("status write failed: $_") }
    }
    if ($statusWritten) { Remove-RunResult }
    Release-PipelineLock
    if ($LogFile) { try { Stop-Transcript | Out-Null } catch {} }
    [Console]::Error.WriteLine($message)
    exit 1
}

# ---------- 参数解析与前置检查 ----------
$script:FailureStage = "preflight"
$script:Status.stage = "preflight"
Write-RunStatus
if (-not $CrawlerRoot) { $CrawlerRoot = Join-Path (Split-Path $RadarRoot -Parent) "MediaCrawler" }
if (-not $BridgeRoot) { $BridgeRoot = Join-Path (Split-Path $RadarRoot -Parent) "douyin-bridge" }
if (-not $PythonExe) {
    foreach ($candidate in @("venv\Scripts\python.exe", ".venv\Scripts\python.exe")) {
        $probe = Join-Path $CrawlerRoot $candidate
        if (Test-Path -LiteralPath $probe) { $PythonExe = $probe; break }
    }
    if (-not $PythonExe) { $PythonExe = Join-Path $CrawlerRoot ".venv\Scripts\python.exe" }
}
$runner = Join-Path $RadarRoot "scripts\run_mediacrawler_douyin.py"
foreach ($check in @(
        @{ Path = $runner; Hint = "RadarRoot is not the main repository" },
        @{ Path = (Join-Path $CrawlerRoot "main.py"); Hint = "CrawlerRoot is not a MediaCrawler repository" },
        @{ Path = (Join-Path $BridgeRoot ".git"); Hint = "BridgeRoot is not a git repository" },
        @{ Path = $PythonExe; Hint = "MediaCrawler venv is missing" }
    )) {
    if (-not (Test-Path -LiteralPath $check.Path)) { throw "Missing $($check.Path): $($check.Hint)" }
}

if (-not $SkipGitPull) {
    $script:FailureStage = "radar_pull"
    Write-Step "更新主仓库 $RadarRoot"
    Invoke-GitText $RadarRoot @("pull", "--ff-only") | Out-Null
}

# ---------- 读取并验证本轮博主 ----------
$script:FailureStage = "creator_config"
if ($CreatorIds) {
    $secUids = @($CreatorIds.Split(",") | ForEach-Object { $_.Trim() } | Where-Object { $_ } | Select-Object -Unique)
    $creatorNames = @("(manual)")
} else {
    $configPath = Join-Path $RadarRoot "config\online-sources.json"
    $config = Get-Content -LiteralPath $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $douyinSources = @($config.sources | Where-Object {
            $_.type -eq "mediacrawler_jsonl" -and $_.enabled -ne $false -and $_.locator -match "douyin\.com/user/"
        })
    $secUids = @($douyinSources | ForEach-Object { ($_.locator -split "/user/")[1].Split("?")[0].Trim("/") } | Where-Object { $_ } | Select-Object -Unique)
    $creatorNames = @($douyinSources | ForEach-Object { $_.name })
}
if (-not $secUids -or $secUids.Count -eq 0) {
    Exit-Run "succeeded" "completed_no_sources" "No enabled Douyin creators; nothing was collected or pushed." 0
}
foreach ($secUid in $secUids) {
    if ([string]$secUid -notmatch '^[A-Za-z0-9_.-]+$') { throw "Invalid Douyin creator id." }
}
$script:Status.requested_creator_count = $secUids.Count
Write-Step ("本次采集 {0} 个博主：{1}" -f $secUids.Count, ($creatorNames -join "、"))

# ---------- Bridge 开跑前必须完全干净并成功快进 ----------
$script:FailureStage = "bridge_preflight"
$bridgeDirty = @((Invoke-GitText $BridgeRoot @("status", "--porcelain")) | Where-Object { $_ })
if ($bridgeDirty.Count -gt 0) { throw "Douyin bridge has existing changes; refusing to continue." }
Invoke-GitText $BridgeRoot @("pull", "--ff-only") | Out-Null
$bridgeHeadBefore = ([string](Invoke-GitText $BridgeRoot @("rev-parse", "HEAD") | Select-Object -First 1)).Trim()
$script:Status.bridge_head_before = $bridgeHeadBefore
$script:Status.bridge_head_after = $bridgeHeadBefore

# ---------- 运行带本轮回执的 MediaCrawler ----------
$script:FailureStage = "runner"
$script:Status.stage = "collecting"
Write-RunStatus
$creatorArg = $secUids -join ","
$script:CrawlResultFile = Join-Path $env:TEMP ("douyin-crawl-result-{0}.json" -f $script:RunId)
$runnerArgs = @(
    "--crawler-root", $CrawlerRoot,
    "--platform", "douyin",
    "--creator-id", $creatorArg,
    "--max-notes", $MaxNotes,
    "--run-id", $script:RunId,
    "--result-file", $script:CrawlResultFile,
    "--parent-holds-collection-lock"
)
if ($BrowserOffscreen) { $runnerArgs += "--offscreen" }
Write-Step "启动 MediaCrawler（max-notes=$MaxNotes）"
& $PythonExe $runner @runnerArgs
$runnerExit = $LASTEXITCODE
$runnerResult = $null
if (Test-Path -LiteralPath $script:CrawlResultFile) {
    try { $runnerResult = Get-Content -LiteralPath $script:CrawlResultFile -Raw -Encoding UTF8 | ConvertFrom-Json } catch { throw "Runner result JSON is invalid." }
}
if ($runnerResult) {
    foreach ($field in @("login_state", "source_file", "source_last_write_time", "source_sha256", "output_rows", "crawl_output_rows", "new_unique_items", "requested_creator_count", "completed_creator_count", "failed_creator_count", "creator_results")) {
        if ($runnerResult.PSObject.Properties.Name -contains $field) { $script:Status[$field] = $runnerResult.$field }
    }
    $script:Status.warnings = @($runnerResult.warnings)
}
if ($runnerExit -ne 0) {
    if ($runnerResult -and $runnerResult.login_state -eq "login_required") { $script:FailureStage = "login_required" }
    throw "MediaCrawler failed (exit=$runnerExit); bridge was not changed."
}
if (-not $runnerResult -or [string]$runnerResult.run_id -ne $script:RunId) {
    Exit-Run "warning" "output_delta_ambiguous" "Runner result is missing or belongs to another run; bridge was not changed." 1
}
if ($runnerResult.ambiguous -eq $true) {
    Exit-Run "warning" "output_delta_ambiguous" "Crawler output delta is ambiguous; bridge was not changed." 1
}
$creatorReceipts = @($runnerResult.creator_results)
$receiptsValid = (
    [int]$runnerResult.requested_creator_count -eq $secUids.Count -and
    [int]$runnerResult.completed_creator_count -eq $secUids.Count -and
    [int]$runnerResult.failed_creator_count -eq 0 -and
    $creatorReceipts.Count -eq $secUids.Count -and
    @($creatorReceipts | Where-Object {
            $_.state -ne "completed" -or $_.profile_valid -ne $true -or $_.api_pages_valid -ne $true -or
            [int]$_.written_rows -ne [int]$_.listed_count
        }).Count -eq 0
)
if (-not $receiptsValid) {
    Exit-Run "warning" "partial_creator_failure" "One or more creator receipts are incomplete; bridge was not changed." 1
}

$manifestPath = Join-Path $BridgeRoot "manifest.json"
$bridgeJsonlDir = Join-Path $BridgeRoot "output\douyin\jsonl"
$bridgeJsonl = Join-Path $bridgeJsonlDir "creator_contents_latest.jsonl"
$legacyFiles = @()
if (Test-Path -LiteralPath $bridgeJsonlDir) {
    $legacyFiles = @(Get-ChildItem -LiteralPath $bridgeJsonlDir -Filter "creator_contents_*.jsonl" -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -ne "creator_contents_latest.jsonl" } | ForEach-Object { $_.FullName })
}
if ($legacyFiles.Count -gt 0) { $script:Status.warnings += @($legacyFiles | ForEach-Object { "Legacy JSONL retained for manual review: $_" }) }

# 0 行只能在所有账号明确返回合法空列表时成功，不能退回旧 JSONL。
if ([int]$runnerResult.crawl_output_rows -eq 0) {
    $allExplicitlyEmpty = @($creatorReceipts | Where-Object {
            $_.profile_valid -ne $true -or $_.api_pages_valid -ne $true -or [int]$_.listed_count -ne 0
        }).Count -eq 0
    if (-not $allExplicitlyEmpty) {
        Exit-Run "warning" "no_crawl_output" "No rows were appended without complete empty-account receipts; bridge was not changed." 1
    }
    try {
        if (-not (Test-Path -LiteralPath $manifestPath)) { throw "Bridge manifest is missing." }
        $existingManifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
        if (-not $existingManifest) { throw "Bridge manifest is invalid." }
    } catch {
        $script:Status.warnings += [string]$_
        Exit-Run "warning" "no_crawl_output" "No rows were appended and the existing manifest is unavailable; bridge was not changed." 1
    }
    $script:Status.content_changed = $false
    $script:Status.bridge_changed = $false
    $script:Status.bridge_head_after = Assert-RemoteHead $BridgeRoot
    Exit-Run "succeeded" "completed_no_change" "All creators completed with no returned works; bridge remains unchanged." 0
}

# ---------- 复制 candidate，按字节判断内容变化，并精确暂存 ----------
$script:FailureStage = "bridge_update"
$sourceFile = [string]$runnerResult.source_file
if (-not $sourceFile -or -not (Test-Path -LiteralPath $sourceFile)) {
    Exit-Run "warning" "output_delta_ambiguous" "Runner candidate file is missing; bridge was not changed." 1
}
if ((Get-FileHash -Algorithm SHA256 -LiteralPath $sourceFile).Hash.ToLowerInvariant() -ne ([string]$runnerResult.source_sha256).ToLowerInvariant()) {
    Exit-Run "warning" "output_delta_ambiguous" "Runner candidate SHA256 changed before copy; bridge was not changed." 1
}
$targetHashBefore = if (Test-Path -LiteralPath $bridgeJsonl) { (Get-FileHash -Algorithm SHA256 -LiteralPath $bridgeJsonl).Hash } else { "" }
$contentChanged = (-not $targetHashBefore) -or $targetHashBefore.ToLowerInvariant() -ne ([string]$runnerResult.source_sha256).ToLowerInvariant()
$script:Status.content_changed = $contentChanged
$manifestNeedsMigration = $true
if (Test-Path -LiteralPath $manifestPath) {
    try {
        $existingManifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
        $manifestNeedsMigration = [int]$existingManifest.schema_version -ne 1
    } catch { $script:Status.warnings += "Existing manifest is invalid and will be replaced after valid crawler output." }
}
if ($contentChanged) {
    [IO.Directory]::CreateDirectory($bridgeJsonlDir) | Out-Null
    Copy-Item -LiteralPath $sourceFile -Destination $bridgeJsonl -Force
    if ((Get-FileHash -Algorithm SHA256 -LiteralPath $bridgeJsonl).Hash.ToLowerInvariant() -ne ([string]$runnerResult.source_sha256).ToLowerInvariant()) {
        throw "Bridge JSONL SHA256 does not match the runner candidate after copy."
    }
}
if ($contentChanged -or $manifestNeedsMigration) {
    $manifest = [ordered]@{
        schema_version = 1
        generated_at = (Get-Date).ToUniversalTime().ToString("o")
        source_file = [IO.Path]::GetFileName($sourceFile)
        source_sha256 = [string]$runnerResult.source_sha256
        output_rows = $runnerResult.output_rows
        crawl_output_rows = $runnerResult.crawl_output_rows
        new_unique_items = $runnerResult.new_unique_items
        creator_count = $secUids.Count
        max_notes = $MaxNotes
    }
    Write-AtomicJson $manifestPath $manifest "$($script:RunId)-manifest"
}

if ((Invoke-Git $BridgeRoot @("add", "--", "output/douyin/jsonl/creator_contents_latest.jsonl", "manifest.json")) -ne 0) {
    throw "Precise bridge staging failed."
}
& git -C $BridgeRoot diff --cached --quiet
$script:Status.bridge_changed = $LASTEXITCODE -ne 0
if (-not $script:Status.bridge_changed) {
    $script:Status.bridge_head_after = Assert-RemoteHead $BridgeRoot
    Exit-Run "succeeded" "completed_no_change" ("Collection completed: {0} appended rows, {1} new unique works; bridge bytes unchanged." -f $runnerResult.crawl_output_rows, $runnerResult.new_unique_items) 0
}

$stage = if ($contentChanged) { "completed_pushed" } else { "completed_pushed_metadata_only" }
$commitMessage = if ($contentChanged) { "数据：更新抖音采集 JSONL" } else { "数据：迁移抖音桥接清单格式" }
if ((Invoke-Git $BridgeRoot @("commit", "-m", $commitMessage)) -ne 0) { throw "Bridge commit failed." }
if ((Invoke-Git $BridgeRoot @("push")) -ne 0) { throw "Bridge push failed." }
$script:Status.bridge_head_after = Assert-RemoteHead $BridgeRoot
Exit-Run "succeeded" $stage ("Collection completed: {0} appended rows, {1} new unique works; bridge pushed." -f $runnerResult.crawl_output_rows, $runnerResult.new_unique_items) 0

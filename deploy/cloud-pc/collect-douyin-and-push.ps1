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
    # 日志文件路径（留空不记录；计划任务传入以便无人值守排查）
    [string]$LogFile = ""
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

# ---------- 参数解析与前置检查 ----------
if (-not $CrawlerRoot) { $CrawlerRoot = Join-Path (Split-Path $RadarRoot -Parent) "MediaCrawler" }
if (-not $BridgeRoot) { $BridgeRoot = Join-Path (Split-Path $RadarRoot -Parent) "douyin-bridge" }
if (-not $PythonExe) {
    foreach ($candidate in @("venv\Scripts\python.exe", ".venv\Scripts\python.exe")) {
        $probe = Join-Path $CrawlerRoot $candidate
        if (Test-Path $probe) { $PythonExe = $probe; break }
    }
    if (-not $PythonExe) { $PythonExe = Join-Path $CrawlerRoot ".venv\Scripts\python.exe" }
}

foreach ($check in @(
        @{ Path = (Join-Path $RadarRoot "scripts\run_mediacrawler_douyin.py"); Hint = "RadarRoot 不是主仓库" },
        @{ Path = (Join-Path $CrawlerRoot "main.py"); Hint = "CrawlerRoot 不是 MediaCrawler 仓库" },
        @{ Path = (Join-Path $BridgeRoot ".git"); Hint = "BridgeRoot 不是 git 仓库（先 git clone 私有桥接仓库）" },
        @{ Path = $PythonExe; Hint = "MediaCrawler venv 缺失（先在 CrawlerRoot 建 .venv 并装依赖）" }
    )) {
    if (-not (Test-Path $check.Path)) {
        throw ("缺少 {0}：{1}" -f $check.Path, $check.Hint)
    }
}

# ---------- 1. 更新主仓库，拿最新博主配置 ----------
if (-not $SkipGitPull) {
    Write-Step "更新主仓库 $RadarRoot"
    if ((Invoke-Git $RadarRoot @("pull", "--ff-only")) -ne 0) {
        Write-Warning "主仓库 git pull 失败，继续用本地已有配置"
    }
}

# ---------- 2. 读取启用的抖音博主 ----------
if ($CreatorIds) {
    $secUids = $CreatorIds.Split(",") | ForEach-Object { $_.Trim() } | Where-Object { $_ }
    $creatorNames = @("(手动指定)")
} else {
    $configPath = Join-Path $RadarRoot "config\online-sources.json"
    $config = Get-Content -LiteralPath $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $douyinSources = @($config.sources | Where-Object {
            $_.type -eq "mediacrawler_jsonl" -and $_.enabled -ne $false -and $_.locator -match "douyin\.com/user/"
        })
    $secUids = @($douyinSources | ForEach-Object { ($_.locator -split "/user/")[1].Split("?")[0].Trim("/") } | Where-Object { $_ })
    $creatorNames = @($douyinSources | ForEach-Object { $_.name })
}
if (-not $secUids -or $secUids.Count -eq 0) {
    Write-Step "线上配置中没有启用的抖音博主，本次不采集。"
    exit 0
}
Write-Step ("本次采集 {0} 个博主：{1}" -f $secUids.Count, ($creatorNames -join "、"))

# ---------- 3. 运行 MediaCrawler 采集 ----------
$runner = Join-Path $RadarRoot "scripts\run_mediacrawler_douyin.py"
$creatorArg = $secUids -join ","
Write-Step "启动 MediaCrawler（max-notes=$MaxNotes）"
& $PythonExe $runner --crawler-root $CrawlerRoot --platform douyin --creator-id $creatorArg --max-notes $MaxNotes
if ($LASTEXITCODE -ne 0) {
    throw "MediaCrawler 采集失败（exit=$LASTEXITCODE），本次不推送。"
}

# ---------- 4. 取最新 JSONL，复制进桥接仓库 ----------
$jsonlDir = Join-Path $CrawlerRoot "output\douyin\jsonl"
$newest = Get-ChildItem -LiteralPath $jsonlDir -Filter "creator_contents_*.jsonl" -ErrorAction SilentlyContinue |
    Where-Object { $_.Length -gt 0 } | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $newest) {
    throw "采集后没有找到非空的 creator_contents_*.jsonl：$jsonlDir"
}
Write-Step ("最新 JSONL：{0}（{1:N0} 字节）" -f $newest.Name, $newest.Length)

$bridgeJsonlDir = Join-Path $BridgeRoot "output\douyin\jsonl"
New-Item -ItemType Directory -Force -Path $bridgeJsonlDir | Out-Null
# 桥接仓库始终只保留一个固定文件名，避免 Actions 端 mtime 排序歧义
Get-ChildItem -LiteralPath $bridgeJsonlDir -Filter "creator_contents_*.jsonl" -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -ne "creator_contents_latest.jsonl" } | Remove-Item -Force
Copy-Item -LiteralPath $newest.FullName -Destination (Join-Path $bridgeJsonlDir "creator_contents_latest.jsonl") -Force

$lineCount = 0
Get-Content -LiteralPath $newest.FullName -ReadCount 1000 | ForEach-Object { $lineCount += $_.Count }
$manifest = [ordered]@{
    generated_at  = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    source_file   = $newest.Name
    line_count    = $lineCount
    creator_count = $secUids.Count
    max_notes     = $MaxNotes
}
$manifestPath = Join-Path $BridgeRoot "manifest.json"
($manifest | ConvertTo-Json) | Set-Content -LiteralPath $manifestPath -Encoding UTF8

# ---------- 5. 提交并推送桥接仓库 ----------
Write-Step "推送桥接仓库 $BridgeRoot"
if ((Invoke-Git $BridgeRoot @("pull", "--ff-only")) -ne 0) {
    Write-Warning "桥接仓库 pull 失败，尝试直接提交推送"
}
Invoke-Git $BridgeRoot @("add", "-A") | Out-Null
& git -C $BridgeRoot diff --cached --quiet
if ($LASTEXITCODE -eq 0) {
    Write-Step "桥接仓库无变化，不需要推送。"
    exit 0
}
if ((Invoke-Git $BridgeRoot @("commit", "-m", "数据：更新抖音采集 JSONL")) -ne 0) {
    throw "桥接仓库 commit 失败"
}
if ((Invoke-Git $BridgeRoot @("push")) -ne 0) {
    throw "桥接仓库 push 失败（检查凭证/网络）"
}
Write-Step ("完成：{0} 行 JSONL 已推送，等待线上下一次刷新。" -f $lineCount)

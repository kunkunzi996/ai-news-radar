# 家里电脑采集一轮新闻快照。读本机名单，写出 data/，不提交 GitHub。
$ErrorActionPreference = 'Stop'
$Root = if ($env:RADAR_ROOT) { $env:RADAR_ROOT } else { 'C:\AI-news-reader\ai-news-radar-run' }
Set-Location $Root
$LogDir = Join-Path $Root 'logs'
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$Log = Join-Path $LogDir 'home-collect.log'
$Lock = Join-Path $LogDir 'home-collect.lock'

function Write-Log([string]$Message) {
  $line = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss') + ' ' + $Message
  Add-Content -Path $Log -Value $line -Encoding utf8
}

if (Test-Path $Lock) {
  $old = Get-Content -Raw $Lock
  $oldPid = 0
  [void][int]::TryParse($old.Trim(), [ref]$oldPid)
  if ($oldPid -gt 0 -and (Get-Process -Id $oldPid -ErrorAction SilentlyContinue)) {
    Write-Log "skip: already running pid=$oldPid"
    exit 0
  }
}
Set-Content -Path $Lock -Value $PID -Encoding ascii

try {
  $env:HTTP_PROXY = 'http://127.0.0.1:7897'
  $env:HTTPS_PROXY = 'http://127.0.0.1:7897'
  $env:NO_PROXY = '127.0.0.1,localhost'
  $tokenFile = 'C:\AI-news-reader\secrets\snapshot-dispatch.token'
  if (Test-Path $tokenFile) {
    $env:GITHUB_TOKEN = (Get-Content -Raw $tokenFile).Trim()
  }
  $douyin = 'C:\AI-news-reader\douyin-bridge'
  if (Test-Path $douyin) { $env:MEDIACRAWLER_LOCAL_DIR = $douyin }
  $wechat = 'C:\AI-news-reader\wechat-bridge\output\wechat\jsonl'
  if (Test-Path $wechat) { $env:WE_MP_RSS_JSONL_DIR = $wechat }
  $cookie = Join-Path $Root 'local-secrets\bilibili-cookies.txt'
  if (Test-Path $cookie) { $env:BILIBILI_COOKIE_FILE = $cookie }

  $config = Join-Path $Root '.local\online-sources.json'
  if (-not (Test-Path $config)) { $config = Join-Path $Root 'config\online-sources.json' }
  $python = Join-Path $Root '.venv\Scripts\python.exe'
  Write-Log "start config=$config"
  & $python 'scripts\update_news.py' '--source-config' $config '--output-dir' 'data' '--window-hours' '24' '--archive-days' '14' '--all-time'
  $code = $LASTEXITCODE
  Write-Log "exit=$code"
  exit $code
} finally {
  Remove-Item -Force $Lock -ErrorAction SilentlyContinue
}

#Requires -Version 5.1
<#
  订阅源采集快捷方式（菜单版）。
  增删订阅源后跑一下，选对应入口，马上看是否生效。

  三个入口：
    [1] 全部采集      本机抓抖音+微信推桥接 -> 再触发云端聚合（最全，约 10~20 分钟）
    [2] 只刷云端      只触发 Actions，刷新 B站/RSS/GitHub/YouTube 直连源（最快，约 3~10 分钟）
    [3] 只采本机源    只抓抖音+微信并推桥接仓库（备料，页面不变；跑完可再选是否触发云端）

  为什么分三个：微信/抖音靠本机 sidecar 先抓再推桥接，云端只克隆桥接不去直接抓；
  只动 B站/RSS 等直连源时走 [2] 就够快，动了微信/抖音才需要 [1]。
#>

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$Workflow = 'update-news.yml'
$Branch   = 'master'

# 切到脚本所在目录（保证 gh 认得当前仓库）
Set-Location -Path $PSScriptRoot

# ---------- 路径（本机布局：各仓库是雷达仓库的同级目录）----------
$RadarRoot    = $PSScriptRoot
$ParentDir    = Split-Path $RadarRoot -Parent
$DouyinScript = Join-Path $RadarRoot 'deploy\cloud-pc\collect-douyin-and-push.ps1'
$CrawlerRoot  = Join-Path $ParentDir 'MediaCrawler-local-test'
$DouyinBridge = Join-Path $ParentDir 'douyin-bridge'
$DouyinLog    = Join-Path $ParentDir 'douyin-collect.log'
$WechatScript = Join-Path $RadarRoot 'deploy\local\collect-wechat-and-push.ps1'
$WechatLog    = Join-Path $ParentDir 'wechat-collect.log'

# ============================================================
# 工具函数
# ============================================================

function Assert-GhReady {
  try {
    gh auth status 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) { throw }
  } catch {
    Write-Host '✗ gh 未登录，请先在终端执行： gh auth login' -ForegroundColor Red
    return $false
  }
  return $true
}

# 以独立子进程跑一个本机采集脚本，实时输出、返回是否成功。
# 用子进程隔离：这些脚本内部 ErrorActionPreference=Stop 且带 trap，
# 在本进程内联跑一旦 throw 会掀翻整个菜单。
function Invoke-LocalScript {
  param(
    [string]$Label,
    [string]$ScriptPath,
    [string[]]$ScriptArgs
  )
  if (-not (Test-Path -LiteralPath $ScriptPath)) {
    Write-Host ("⚠ 跳过{0}：找不到脚本 {1}" -f $Label, $ScriptPath) -ForegroundColor Yellow
    return $false
  }
  Write-Host ("▶ 开始{0}…" -f $Label) -ForegroundColor Cyan
  $psArgs = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $ScriptPath) + $ScriptArgs
  & powershell.exe @psArgs
  $ok = ($LASTEXITCODE -eq 0)
  if ($ok) {
    Write-Host ("✔ {0}完成。" -f $Label) -ForegroundColor Green
  } else {
    Write-Host ("✗ {0}失败（exit={1}），继续后续步骤。" -f $Label, $LASTEXITCODE) -ForegroundColor Red
  }
  return $ok
}

function Invoke-DouyinCollect {
  return (Invoke-LocalScript -Label '抖音采集' -ScriptPath $DouyinScript -ScriptArgs @(
      '-CrawlerRoot', $CrawlerRoot,
      '-BridgeRoot',  $DouyinBridge,
      '-SkipGitPull',
      '-LogFile',     $DouyinLog
    ))
}

function Invoke-WechatCollect {
  return (Invoke-LocalScript -Label '微信公众号采集' -ScriptPath $WechatScript -ScriptArgs @(
      '-LogFile', $WechatLog
    ))
}

# 触发云端 Actions 采集并盯到跑完，返回是否成功。
function Invoke-CloudRefresh {
  if (-not (Assert-GhReady)) { return $false }

  Write-Host '▶ 正在触发线上采集…' -ForegroundColor Cyan
  gh workflow run $Workflow --ref $Branch
  if ($LASTEXITCODE -ne 0) {
    Write-Host '✗ 触发失败，请检查网络或仓库权限。' -ForegroundColor Red
    return $false
  }

  Write-Host '  等待任务登记…' -ForegroundColor DarkGray
  $runId = $null
  foreach ($i in 1..15) {
    Start-Sleep -Seconds 2
    $runId = gh run list --workflow $Workflow --branch $Branch --event workflow_dispatch --limit 1 --json databaseId --jq '.[0].databaseId' 2>$null
    if ($runId) { break }
  }
  if (-not $runId) {
    Write-Host '⚠ 已触发，但没抓到运行编号。可去 GitHub Actions 页面查看进度。' -ForegroundColor Yellow
    return $false
  }

  Write-Host ("▶ 采集进行中（运行编号 {0}），预计 3~10 分钟…" -f $runId) -ForegroundColor Cyan
  gh run watch $runId --exit-status
  $ok = ($LASTEXITCODE -eq 0)
  Write-Host ''
  if ($ok) {
    Write-Host '✔ 采集完成！线上页面已更新。' -ForegroundColor Green
    Write-Host '  打开页面后按 Ctrl+F5 强制刷新，即可看到最新结果。' -ForegroundColor Green
  } else {
    Write-Host '✗ 采集失败或超时，去 GitHub Actions 页面看日志：' -ForegroundColor Red
    gh run view $runId --web
  }
  return $ok
}

# ============================================================
# 菜单
# ============================================================

Write-Host ''
Write-Host '========== 订阅源采集 ==========' -ForegroundColor Cyan
Write-Host '  [1] 全部采集    本机抖音+微信 -> 云端聚合（最全，约 10~20 分钟）'
Write-Host '  [2] 只刷云端    仅触发 Actions，刷 B站/RSS/GitHub/油管（最快）'
Write-Host '  [3] 只采本机源  仅抓抖音+微信推桥接（备料，页面不变）'
Write-Host '  [Q] 退出'
Write-Host '================================' -ForegroundColor Cyan
$choice = (Read-Host '请选择').Trim().ToUpper()

switch ($choice) {
  '1' {
    Write-Host '— 全部采集 —' -ForegroundColor Cyan
    Write-Host '提示：抖音会弹出 Chrome 窗口，跑的时候别关；若登录过期需手动扫码。' -ForegroundColor DarkGray
    Invoke-DouyinCollect | Out-Null
    Invoke-WechatCollect | Out-Null
    Write-Host ''
    Write-Host '本机采集结束，开始触发云端聚合…' -ForegroundColor Cyan
    Invoke-CloudRefresh | Out-Null
  }
  '2' {
    Write-Host '— 只刷云端 —' -ForegroundColor Cyan
    Invoke-CloudRefresh | Out-Null
  }
  '3' {
    Write-Host '— 只采本机源 —' -ForegroundColor Cyan
    Write-Host '提示：抖音会弹出 Chrome 窗口，跑的时候别关；若登录过期需手动扫码。' -ForegroundColor DarkGray
    Invoke-DouyinCollect | Out-Null
    Invoke-WechatCollect | Out-Null
    Write-Host ''
    Write-Host '本机料已备好并推到桥接仓库，但页面还不会变——上页面必须靠云端聚合。' -ForegroundColor Yellow
    $go = (Read-Host '现在顺手触发一次云端聚合吗？(Y/N)').Trim().ToUpper()
    if ($go -eq 'Y') {
      Invoke-CloudRefresh | Out-Null
    } else {
      Write-Host '好，已跳过云端。下次想上页面时选 [2] 即可。' -ForegroundColor DarkGray
    }
  }
  'Q' {
    Write-Host '已退出。' -ForegroundColor DarkGray
  }
  default {
    Write-Host '没识别到选项，什么都没做。重开脚本再选一次即可。' -ForegroundColor Yellow
  }
}

Write-Host ''
Read-Host '按回车退出'

# Windows Auto Refresh Guide

这份手册只做一件事：让本机自动刷新 `data/*.json`。

它不负责公网部署，也不会打开 Nginx。你可以先把它理解成“让电脑每 30 分钟自动点一次刷新看板数据”。

## 自动化方式

- `scripts/windows/refresh-ai-news-radar.ps1`：真正执行采集刷新。
- `scripts/windows/register-ai-news-radar-refresh-task.ps1`：把刷新脚本注册成 Windows 计划任务。
- 计划任务名称：`AI News Radar Refresh`。
- 默认频率：每 30 分钟一次。
- 日志位置：`%LOCALAPPDATA%\AINewsRadarAutomation`。

默认采集范围是 `since-last`，意思是从上次 `data/source-status.json` 的生成时间算起，自动决定本轮刷新窗口；如果找不到上次时间，就退回 24 小时。

## 第一次注册

在 PowerShell 里运行：

```powershell
cd E:\AI-news-reader\ai-news-radar-run
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\register-ai-news-radar-refresh-task.ps1
```

注册完成后，Windows 会在约 2 分钟后开始第一次自动刷新，之后每 30 分钟刷新一次。

## 手动跑一次

```powershell
Start-ScheduledTask -TaskName "AI News Radar Refresh"
```

看最近一次任务状态：

```powershell
Get-ScheduledTaskInfo -TaskName "AI News Radar Refresh"
```

查看日志：

```powershell
explorer "$env:LOCALAPPDATA\AINewsRadarAutomation"
```

如果 `latest.err.log` 是空文件，通常说明没有错误。

## 只测试命令，不真正刷新

```powershell
.\scripts\windows\refresh-ai-news-radar.ps1 -DryRun
```

这个命令会打印实际要执行的 Python、参数、采集窗口和日志目录。

## 改刷新频率

例如改成每 60 分钟：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\register-ai-news-radar-refresh-task.ps1 -IntervalMinutes 60
```

## 暂停自动刷新

```powershell
Disable-ScheduledTask -TaskName "AI News Radar Refresh"
```

恢复：

```powershell
Enable-ScheduledTask -TaskName "AI News Radar Refresh"
```

彻底取消：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\register-ai-news-radar-refresh-task.ps1 -Mode Unregister
```

## 注意事项

- 电脑睡眠时不会刷新；唤醒后 Windows 会尽量补跑。
- 这个任务只刷新 `data/*.json`，不会自动启动抖音/小红书 MediaCrawler 采集器。
- 如果 `sources.config.json` 存在，刷新会读取它；如果不存在，就走项目默认源。
- 不要把 cookie、token、私有 OPML 提交进 Git。
- 如果刷新失败，先看 `%LOCALAPPDATA%\AINewsRadarAutomation\latest.err.log`。

## 验收标准

自动化成功后应该看到：

1. `Get-ScheduledTaskInfo -TaskName "AI News Radar Refresh"` 有最近运行时间。
2. `%LOCALAPPDATA%\AINewsRadarAutomation` 里有 `refresh-*.out.log`。
3. `data/source-status.json` 的 `generated_at` 会随刷新更新。
4. 打开本地页面后，页面右上角更新时间变新。

# 施工说明：微信公众号采集「健康看门狗 + MeoW 手机推送告警」

> 给 Codex 的任务说明。请严格按本文件执行，不要自由发挥，不要顺手改其它无关代码。
> 施工中保持聚焦：只输出必要的简短进度，不插播计划外的概念科普和非阻塞建议；阻塞问题、
> 测试失败、高风险动作、用户新指令和范围变化必须立即说明。
> 项目根目录：`E:\AI-news-reader\ai-news-radar-run`（下文相对路径均相对该根目录）
> 当前分支：`feat/wechat-watchdog-meow-push`（已由用户创建并确认）
> 分支策略：就在本分支施工；优先遵守项目 `CLAUDE.md`。**未获用户授权，不要 commit / push、不要合回 master。**

---

## 背景（为什么做这个）

2026-07-18 微信公众号采集悄悄断了两天，用户 07-19 才偶然从公网页面发现。事后定位：
微信登录会话过期（sidecar 抓取抛 `Invalid Session`），采集脚本其实**已经打了告警**，
但告警只落进日志文件和 `E:\AI-news-reader\wechat-collect-status.json`——采集是
`conhost --headless` 无窗口后台任务，用户根本不会去翻这两个文件。**报警在原地自生自灭。**

**现状**：本机链路是
`sidecar 采集 → collect-wechat-and-push.ps1 导出 JSONL → 推 wechat-bridge 仓库 →
GitHub Actions 只读克隆 → 公网页面`。采集计划任务 `DouyinCollectAndPush` 每天
10:00 / 15:00 / 23:00 跑（微信采集是它的第二个动作）。缺的是一条**能主动够到用户**的告警通道。

**已确认的产品决策**：
1. 告警渠道用 **MeoW**（纯血鸿蒙原生消息 app，`POST https://api.chuckfang.com/<昵称>`）。
2. 自检要**独立于采集脚本**：采集早崩 / 压根没跑，看门狗也要能响。
3. 看门狗**纯读本地信号，绝不去探活 sidecar**（sidecar 平时可能没在跑，探活必误报）。
4. 本次只做「手机推送告警」；「公网/本地看板健康横幅」等 NUC 自建服务器落地后再做，本次不碰。

---

## 一、目标（做成什么样）

新增一个**每小时自动跑一次**的健康看门狗。它只读两个本地信号判断微信采集是否健康：

- 信号①（新鲜度）：sidecar 库 `feeds.sync_time` 的最大值＝最近一次**成功**采集时间。
  超过阈值（默认 26 小时，容忍错过一两轮）没更新 → 判「停更」。
  （`sync_time` 只在抓取成功时前进，天然就是新鲜度信号。）
- 信号②（原因）：`wechat-collect-status.json` 的 `state` / `message`。若最近一次采集
  `state=failed` 且 `message` 含 `Invalid Session` 之类、且该失败发生在最近一次成功之后
  → 判「登录失效」，走快速通道**立刻告警**（不等停更阈值，因为登录失效不会自愈）。

判为异常时，往用户 MeoW 昵称推一条中文告警（登录失效就提示「去 sidecar 扫码」）。
**防骚扰**：只在「正常→异常」翻转时推一次，恢复时推一条「已恢复」，中间不反复。

**本次范围只做「本机看门狗 + MeoW 推送」，不做**：看板健康横幅、一键重采按钮、
改动采集脚本本身的抓取逻辑、任何 sidecar 侧改动。

---

## 二、关键技术点（需要动的硬骨头）

1. **检测逻辑抽成可单测的 Python 纯函数** → PS5.1 没法直接读 SQLite，且判定逻辑要能跑
   pytest。所以拆成：Python 探针（读信号 + 判健康，纯函数可测）＋ PowerShell 编排
   （推送 + 去重 + 任务）。探针**只读**打开库（`mode=ro`），绝不写、绝不锁死采集。
2. **去重状态机** → 用一个仓库外的状态文件记「上次是正常还是告警中、什么原因」，实现
   「一次事故只推一条 + 恢复推一条」。
3. **MeoW 昵称是唯一凭证（软密钥）** → 存 gitignored 的 `local-secrets/`，绝不进仓库；
   仓库里只放一个占位示例文件。推送走 try/catch，网络失败只记日志不崩。
4. **编码红线** → 新 `.ps1` 必须存 **UTF-8 带 BOM**（PS5.1 否则中文字面量乱码，项目已踩过）；
   `.ps1` 写出的 JSON 沿用现有 `Write-AtomicJson` 的 **UTF-8 无 BOM**（两者不是一回事，别搞混）。

---

## 三、文件清单

**新建**
1. `deploy/local/wechat_health_probe.py` —— 健康探针：读信号 + 纯函数判定 + 打印判定 JSON。
2. `deploy/local/wechat-health-watchdog.ps1` —— 看门狗编排：调探针 → 比对去重状态 → 推 MeoW → 写状态 / 日志。**存 UTF-8 带 BOM。**
3. `deploy/local/meow-push.example.json` —— MeoW 配置的占位示例（**可提交**，不含真昵称）。
4. `tests/test_wechat_health_probe.py` —— 探针判定逻辑的 pytest 用例（覆盖每条分支）。

**本机侧（不在仓库里、由施工时创建，不提交）**
5. `local-secrets/meow-push.json` —— 真实 MeoW 昵称（`local-secrets/` 已在 .gitignore，天然不提交）。
6. 新计划任务 `WechatHealthWatchdog`（Windows 任务计划程序，非仓库文件）。

**不改动**：`.gitignore` 无需改（`local-secrets/` 已被忽略）；`data/archive.json`、
`collect-wechat-and-push.ps1`、任何 sidecar 文件**一律不碰**。

---

## 四、详细改动

### 4.1 `deploy/local/wechat_health_probe.py`（新建）

纯读本地信号、判定健康、打印 JSON。判定核心 `evaluate()` 写成纯函数，方便单测。

```python
"""微信采集健康探针：纯读本地信号，输出健康判定 JSON。

只读 feeds.sync_time（最近一次成功采集）+ wechat-collect-status.json（失败原因）。
绝不触碰 sidecar 进程、绝不写 sidecar 库。判定逻辑（evaluate）为纯函数，可单测。
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# 登录/会话失效的判定模式（大小写不敏感）
LOGIN_FAIL_PATTERNS = re.compile(
    r"invalid session|session.*(invalid|expire)|登录.*(失效|过期)|凭证.*(失效|过期)",
    re.IGNORECASE,
)


def read_last_success_epoch(db_path: Path) -> int | None:
    """取 feeds 表中最大的 sync_time（active 号）。读不到返回 None。只读打开。"""
    if not db_path.exists():
        return None
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
    try:
        row = con.execute(
            "select max(sync_time) from feeds where status=1 and sync_time is not null"
        ).fetchone()
        return int(row[0]) if row and row[0] else None
    except sqlite3.Error:
        return None
    finally:
        con.close()


def read_collect_status(status_path: Path) -> dict[str, Any] | None:
    """读采集状态文件；不存在或坏了返回 None（不因它崩，靠信号①兜底）。"""
    if not status_path.exists():
        return None
    try:
        return json.loads(status_path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None


def _parse_iso_epoch(value: Any) -> float | None:
    if not value:
        return None
    try:
        text = str(value).replace("Z", "+00:00")
        return datetime.fromisoformat(text).timestamp()
    except ValueError:
        return None


def _fmt(epoch: int | float | None) -> str:
    if not epoch:
        return "未知"
    return datetime.fromtimestamp(epoch, timezone.utc).astimezone().strftime("%m-%d %H:%M")


def _compose(reason: str, hours_stale: float | None, last_success_epoch: int | None) -> tuple[str, str]:
    """返回 (title, msg)。内容只给运维提示，不含敏感信息。"""
    last = _fmt(last_success_epoch)
    if reason == "login_expired":
        return ("⚠️ 微信采集登录失效",
                f"最近成功采集 {last}。登录会话已失效，请到本机 sidecar 重新扫码登录后手动补一轮。")
    if reason == "stale":
        h = f"{hours_stale:.0f}" if hours_stale is not None else "?"
        return ("⚠️ 微信采集停更",
                f"已 {h} 小时没有新的成功采集（最近成功 {last}）。请检查本机采集是否正常。")
    if reason == "no_data":
        return ("⚠️ 微信采集无数据",
                "读不到任何成功采集记录，请检查 sidecar 库与采集任务。")
    if reason == "recovered":
        return ("✅ 微信采集已恢复", f"最新成功采集 {last}，通道恢复正常。")
    return ("微信采集正常", f"最近成功采集 {last}。")


def evaluate(
    *,
    last_success_epoch: int | None,
    status: dict[str, Any] | None,
    now: datetime,
    stale_hours: float,
) -> dict[str, Any]:
    """纯函数：给定信号算健康判定。单测直接喂参数即可。"""
    hours_stale: float | None = None
    if last_success_epoch:
        hours_stale = (now.timestamp() - last_success_epoch) / 3600.0

    # 快速通道：登录失效（且失败发生在最近一次成功之后 → 会话是之后才断的）
    login_active = False
    if status and str(status.get("state")) == "failed":
        msg = str(status.get("message") or "")
        finished_epoch = _parse_iso_epoch(status.get("finished_at"))
        after_last_success = (
            last_success_epoch is None
            or (finished_epoch is not None and finished_epoch > last_success_epoch)
        )
        if LOGIN_FAIL_PATTERNS.search(msg) and after_last_success:
            login_active = True

    if login_active:
        healthy, reason = False, "login_expired"
    elif last_success_epoch is None:
        healthy, reason = False, "no_data"
    elif hours_stale is not None and hours_stale > stale_hours:
        healthy, reason = False, "stale"
    else:
        healthy, reason = True, "ok"

    title, message = _compose(reason, hours_stale, last_success_epoch)
    return {
        "healthy": healthy,
        "reason": reason,
        "hours_stale": round(hours_stale, 1) if hours_stale is not None else None,
        "last_success_epoch": last_success_epoch,
        "last_success_iso": (_fmt(last_success_epoch) if last_success_epoch else None),
        "title": title,
        "message": message,
    }


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="WeChat collection health probe.")
    p.add_argument("--db", required=True, help="sidecar db.db 路径")
    p.add_argument("--status", required=True, help="wechat-collect-status.json 路径")
    p.add_argument("--stale-hours", type=float, default=26.0)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    verdict = evaluate(
        last_success_epoch=read_last_success_epoch(Path(args.db)),
        status=read_collect_status(Path(args.status)),
        now=datetime.now(timezone.utc),
        stale_hours=args.stale_hours,
    )
    print(json.dumps(verdict, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

> 安全要点（必须遵守）：
> - 库**只读**打开（`mode=ro`），任何读失败都返回 None，**绝不**写 sidecar 库、**绝不**触发采集。
> - 状态文件坏/缺一律当 None，靠信号①（新鲜度）兜底，不因它崩。
> - `login_expired` 必须满足「失败发生在最近一次成功之后」，避免一条陈旧的失败状态在恢复后还反复报。

### 4.2 `deploy/local/wechat-health-watchdog.ps1`（新建，**UTF-8 带 BOM**）

编排：调探针 → 读去重状态 → 只在翻转时推 MeoW → 写状态 / 日志。原子写 JSON 照抄
`collect-wechat-and-push.ps1` 里的 `Write-AtomicJson`（UTF-8 无 BOM）。

```powershell
param(
    [string]$RadarRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path,
    [string]$DbPath = "E:\AI-news-reader\we-mp-rss-sidecar\data\db.db",
    [string]$CollectStatusFile = "E:\AI-news-reader\wechat-collect-status.json",
    [string]$SecretFile = "",     # 默认 <RadarRoot>\local-secrets\meow-push.json
    [string]$StateFile = "E:\AI-news-reader\wechat-watchdog-state.json",
    [string]$LogFile = "E:\AI-news-reader\wechat-watchdog.log",
    [int]$StaleHours = 26,
    [string]$PythonExe = "python"
)
$ErrorActionPreference = "Stop"
$env:PYTHONIOENCODING = "utf-8"
if (-not $SecretFile) { $SecretFile = Join-Path $RadarRoot "local-secrets\meow-push.json" }

function Write-Log([string]$Message) {
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    Write-Host $line
    if ($LogFile) { try { Add-Content -LiteralPath $LogFile -Value $line -Encoding UTF8 } catch {} }
}

# 原子写 JSON（UTF-8 无 BOM）——照抄 collect-wechat-and-push.ps1 的写法
function Write-AtomicJson([string]$Path, [object]$Value) {
    $temp = "$Path.$PID.tmp"
    $json = $Value | ConvertTo-Json -Depth 8
    $enc = New-Object Text.UTF8Encoding($false)
    [IO.File]::WriteAllText($temp, $json + "`n", $enc)
    if (Test-Path -LiteralPath $Path) { [IO.File]::Replace($temp, $Path, $null) }
    else { [IO.File]::Move($temp, $Path) }
}

function Send-MeoW([string]$Nickname, [string]$Title, [string]$Msg) {
    $uri = "https://api.chuckfang.com/{0}" -f [uri]::EscapeDataString($Nickname)
    $body = @{ title = $Title; msg = $Msg } | ConvertTo-Json -Depth 4
    $bytes = [Text.Encoding]::UTF8.GetBytes($body)
    Invoke-RestMethod -Uri $uri -Method Post -Body $bytes `
        -ContentType "application/json; charset=utf-8" -TimeoutSec 15 | Out-Null
}

try {
    # 1) 读昵称（软密钥）
    if (-not (Test-Path -LiteralPath $SecretFile)) {
        Write-Log "缺少 MeoW 配置：$SecretFile（参照 deploy/local/meow-push.example.json 建一个）"; exit 3
    }
    $nickname = (Get-Content -LiteralPath $SecretFile -Raw | ConvertFrom-Json).nickname
    if (-not $nickname) { Write-Log "MeoW 配置里 nickname 为空"; exit 3 }

    # 2) 跑探针拿判定
    $probe = Join-Path $PSScriptRoot "wechat_health_probe.py"
    $raw = & $PythonExe $probe --db $DbPath --status $CollectStatusFile --stale-hours $StaleHours
    if ($LASTEXITCODE -ne 0 -or -not $raw) { Write-Log "探针执行失败，本轮跳过"; exit 4 }
    $verdict = $raw | ConvertFrom-Json

    # 3) 读上次去重状态
    $prev = $null
    if (Test-Path -LiteralPath $StateFile) {
        try { $prev = Get-Content -LiteralPath $StateFile -Raw | ConvertFrom-Json } catch { $prev = $null }
    }
    $prevStatus = if ($prev) { [string]$prev.status } else { "ok" }
    $prevReason = if ($prev) { [string]$prev.reason } else { "ok" }

    $nowIso = (Get-Date).ToUniversalTime().ToString("o")
    $pushed = $false

    if (-not $verdict.healthy) {
        # 异常：仅在「之前不是告警中」或「原因变了」时推一次
        if ($prevStatus -ne "alerting" -or $prevReason -ne $verdict.reason) {
            try { Send-MeoW $nickname ([string]$verdict.title) ([string]$verdict.message); $pushed = $true
                  Write-Log "已推送告警：$($verdict.reason) - $($verdict.message)" }
            catch { Write-Log "MeoW 推送失败（本轮不改状态，下轮重试）：$_"; exit 5 }
        } else { Write-Log "仍处告警中（$($verdict.reason)），不重复推送" }
        Write-AtomicJson $StateFile @{ status = "alerting"; reason = $verdict.reason;
            last_success_iso = $verdict.last_success_iso; updated_at = $nowIso; last_pushed = $pushed }
    } else {
        # 正常：若上次是告警中，推一条「已恢复」
        if ($prevStatus -eq "alerting") {
            try { Send-MeoW $nickname "✅ 微信采集已恢复" ([string]$verdict.message); $pushed = $true
                  Write-Log "已推送恢复通知" }
            catch { Write-Log "恢复通知推送失败：$_" }
        } else { Write-Log "健康（最近成功 $($verdict.last_success_iso)）" }
        Write-AtomicJson $StateFile @{ status = "ok"; reason = "ok";
            last_success_iso = $verdict.last_success_iso; updated_at = $nowIso; last_pushed = $pushed }
    }
    exit 0
}
catch {
    Write-Log "看门狗自身异常：$_"
    exit 1
}
```

> 安全要点（必须遵守）：
> - 昵称只从 `local-secrets/` 读，**绝不**硬编码进脚本、**绝不**打进日志。
> - MeoW 推送 try/catch：网络失败只记日志、**不崩**；告警推送失败时**不写「已告警」状态**，
>   让下一轮重试（避免「以为推了其实没推」）。
> - 探针失败 / 缺配置各自独立退出码（3/4/5），方便排查，但都不影响采集主链路。

### 4.3 `deploy/local/meow-push.example.json`（新建，可提交，占位）

```json
{
  "nickname": "在这里填你在 MeoW app 里设置的昵称（真实文件请建在 local-secrets/meow-push.json，勿提交）"
}
```

### 4.4 计划任务 `WechatHealthWatchdog`（施工时执行，非仓库文件）

每小时一次、无窗口。**待用户确认计划后再执行注册命令**：

```powershell
$action = New-ScheduledTaskAction -Execute "C:\Windows\System32\conhost.exe" `
  -Argument '--headless powershell.exe -NoProfile -ExecutionPolicy Bypass -File "E:\AI-news-reader\ai-news-radar-run\deploy\local\wechat-health-watchdog.ps1" -LogFile "E:\AI-news-reader\wechat-watchdog.log"'
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).Date.AddHours(8) `
  -RepetitionInterval (New-TimeSpan -Hours 1)
Register-ScheduledTask -TaskName "WechatHealthWatchdog" -Action $action -Trigger $trigger `
  -RunLevel Highest -User $env:USERNAME -Description "微信采集健康看门狗，异常推 MeoW"
```

---

## 五、自测（改完必须跑，全绿才算完成）

在项目根目录依次执行：

```bash
python -m py_compile deploy/local/wechat_health_probe.py
python -m pytest tests/test_wechat_health_probe.py -q
```

`tests/test_wechat_health_probe.py` 必须覆盖 `evaluate()` 的**每条分支**（用临时 sqlite / 直接喂参数）：

1. **健康**：`last_success` 在阈值内 → `healthy=True, reason=ok`。
2. **停更**：`last_success` 超过 `stale_hours` → `healthy=False, reason=stale`。
3. **登录失效（快速通道）**：`status.state=failed`、`message` 含 `Invalid Session`、
   `finished_at` 晚于 `last_success` → `healthy=False, reason=login_expired`（哪怕还没到停更阈值）。
4. **失败早于成功（已恢复）**：同上但 `finished_at` 早于 `last_success` → `healthy=True`
   （验证不会因陈旧失败状态误报）。
5. **无数据**：`last_success=None` → `reason=no_data`。
6. **状态文件坏/缺**：`status=None` 但 `last_success` 新鲜 → `healthy=True`（不因它崩）。
7. 额外测 `read_last_success_epoch` 对临时库能取到 `max(sync_time)`、库缺失返回 None。

全绿后本次任务**算完成，停下汇报，不要自行 commit**。

---

## 六、人工验收清单（用户在真机上点）

> ⚠️ MeoW 真机推送、计划任务真实触发，单测覆盖不到，**必须亲手走一遍**：

1. **建配置**：`local-secrets/meow-push.json` 填真实 MeoW 昵称；确认 `git status` 里**看不到**它。
2. **手动跑一次（健康态）**：命令行执行
   `powershell -File deploy\local\wechat-health-watchdog.ps1`，
   看日志 `E:\AI-news-reader\wechat-watchdog.log` 打「健康」，手机**不该**收到推送。
3. **模拟登录失效（关键）**：临时把 `E:\AI-news-reader\wechat-collect-status.json` 复制一份备份，
   然后手改副本让 `state=failed`、`message` 含 `Invalid Session`、`finished_at` 设成当前时间；
   用 `-CollectStatusFile` 指向该副本再跑一次看门狗 → **手机 MeoW 应弹出「微信采集登录失效」告警**。
4. **验证不重复骚扰**：紧接着再跑一次（状态没变）→ 日志打「仍处告警中，不重复推送」，手机**不再**弹。
5. **验证恢复通知**：把副本改回 `state=succeeded`（或指回真实且新鲜的状态）再跑 → 手机弹一条「已恢复」。
6. **验证真机口径的计划任务**：注册 `WechatHealthWatchdog` 后，在任务计划程序里「运行」一次，
   确认无窗口、日志有新行、状态文件 `wechat-watchdog-state.json` 有更新。
7. 验收完删掉第 3 步的临时副本，恢复现场。

---

## 七、红线（务必遵守）

- 分支策略以顶部为准：就在 `feat/wechat-watchdog-meow-push` 施工；**未获授权不要 commit / push / 合并**。
- **只动第三节文件清单里的文件**，不许顺手改 `collect-wechat-and-push.ps1`、sidecar 或其它无关代码。
- **绝不触碰 `data/archive.json`**，也不触发任何采集 / 写 sidecar 库（探针只读）。
- **MeoW 昵称绝不进仓库**：真配置放 `local-secrets/`（已 gitignore），仓库里只留 `.example.json` 占位；
  昵称不得出现在任何被提交的文件或日志里。
- 新 `.ps1` 存 **UTF-8 带 BOM**（PS5.1 中文不乱码）；`.ps1` 写出的 JSON 用 **UTF-8 无 BOM**（照抄现有 `Write-AtomicJson`）。
- 不做批量文件删除。
- 如无必要，勿增实体：本次不加看板横幅、不加一键重采、不改采集抓取逻辑；这些留给 NUC 落地后。
- MeoW 推送必须 **try/catch 容错**：网络失败只记日志不崩，且推送失败时不得把状态标成「已告警」。
```

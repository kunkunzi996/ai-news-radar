# 施工说明 V2：微信公众号采集「健康看门狗 + MeoW 手机推送告警」

> 本文件是 2026-07-19 修订后的**推荐执行版**。原计划保留作对照，但后续施工以本文件为唯一依据。
>
> 项目根目录：`E:\AI-news-reader\ai-news-radar-run`
>
> 当前分支：`feat/wechat-watchdog-meow-push`（已存在，不再创建分支）
>
> 未获用户授权，不得 commit、push、合并、注册或覆盖计划任务。

---

## 0. AI 速读卡

- **一句话目标**：微信采集、导出或 bridge 推送异常时，主动给用户手机发 MeoW 告警；恢复后只发一次恢复通知。
- **核心闭环**：真实采集状态 + 每个启用公众号的新鲜度 → 健康判定 → 去重状态机 → MeoW → 运行状态留证。
- **P0 验收**：第一阶段先让 `bridge_preflight failed` 和任一启用公众号停更可告警；第二阶段再让真实格式的 `state=warning + login_state=expired` 走登录失效快速告警。
- **最容易翻车**：用测试里虚构的状态字段代替真实采集脚本输出，造成“单测全绿、手机不响”。
- **硬约束**：看门狗运行时不探活 sidecar、不触发采集、不写 sidecar 数据库、不改抓取业务、不泄露 MeoW 昵称；第二阶段改动采集脚本后，必须经用户确认真实跑一轮采集验收。

---

## 一、背景与已确认事实

2026-07-18 微信公众号采集因登录会话失效停更，现有告警只落在后台日志和状态 JSON，用户无法及时看到。

真实本机链路是：

```text
sidecar 抓取
  → collect-wechat-and-push.ps1
  → 导出公开 JSONL
  → 推送 wechat-bridge
  → GitHub Actions 只读克隆
  → 公网页面
```

已有计划任务 `DouyinCollectAndPush` 每天 10:00、15:00、23:00 运行，微信采集是第二个 action。

### 施工前必须承认的真实状态契约

当前 `wechat-collect-status.json` 不是只有 `succeeded/failed` 两种状态：

| 字段 | 真实取值或含义 |
|---|---|
| `state` | `running` / `succeeded` / `warning` / `failed` |
| `stage` | `starting`、`fetching`、`fetch_warning`、`bridge_preflight`、`completed_*` 等 |
| `started_at` / `finished_at` | 本轮采集起止时间，UTC ISO 字符串 |
| `login_state` | 字段已经存在，但当前没有可靠写入真实登录状态 |
| `failed_creator_count` | 字段已经存在，但当前没有完整写入失败公众号数量 |
| `message` | 顶层结果说明；抓取不完整时通常是通用提示，不保证含 `Invalid Session` |

**因此禁止继续使用以下旧假设：**

```text
state=failed 且 message 含 Invalid Session，才算登录失效
```

真实抓取不完整通常会落成 `state=warning`，而 `Invalid Session` 只在采集输出里出现。因此分两步交付：第一阶段先用现有 `state/stage` 和逐 Feed 新鲜度做只读兜底；第二阶段再补齐结构化登录状态，让看门狗给出更准确的“登录失效”快速告警。

---

## 二、目标与成功标准

新增一个每小时运行的本机健康看门狗，覆盖以下三层本地信号：

1. **公众号级新鲜度**：只读 sidecar 数据库中所有 `status=1` 的 Feed，逐个检查 `sync_time`；不能只看最大值。
2. **采集与 bridge 结果**：读取 `wechat-collect-status.json` 的真实 `state/stage/login_state/finished_at`。
3. **看门狗自身状态**：每一轮都写独立运行状态 JSON，配置、Python、探针、MeoW 失败也必须留下机器可读结果。

### 默认新鲜度阈值

默认使用 **14 小时**：当前计划任务最大正常间隔是 11 小时，再留 3 小时缓冲。

- 这个口径通常容忍 1 次、最多约 2 次漏跑。
- 旧计划的 26 小时会容忍约 3 次连续漏跑，不符合“一两轮”的描述。
- 14 小时只用于“未运行/停更”的新鲜度兜底；真实 `warning/failed` 仍立即告警，不能靠把阈值调到 16 小时掩盖采集失败。
- 某个 Feed 偶发一轮未更新并跨过 14 小时、下一轮又自愈时，预期会收到一条告警和一条恢复。若上线观察后确认这类提示过多，可由用户把 `StaleHours` 调为 16；这只能减少部分边界告警，并会让停更发现更晚，所以本版默认仍为 14。
- 如果以后修改采集时间，必须同时重新核对该阈值。

### 异常时

- `login_state=expired`：立即推送“微信登录失效，请重新扫码”。
- 近期 `state=warning`：立即推送“微信抓取不完整”。
- 近期 `state=failed`：立即推送对应阶段失败，例如 bridge 推送失败。
- 任一启用公众号超过阈值未成功同步：推送部分停更或全部停更。
- 状态文件缺失、损坏、采集长时间停在 `running`、数据库不可读：推送“健康检查自身异常”。

### 防骚扰规则

- 同一次异常只发一条首次告警。
- 异常期间原因变化只更新状态文件中的 `latest_reason`，不重复推送。
- 恢复后发一条恢复通知。
- 恢复通知发送失败时保持 `alerting + recovery_pending`，下一轮继续重试，不能提前写成 `ok`。
- 极端情况下，如果 MeoW 已成功但状态文件在落盘前断电，下一轮可能重复一条；本功能选择“宁可极小概率重复，不允许静默漏警”。

### 本次不做

- 不做公网或本地看板健康横幅。
- 不做一键重采、自动重登或自动修复。
- 不联网探活 sidecar、GitHub Actions 或公网页面。
- 不修改 sidecar 代码、数据库结构、抓取规则或 bridge 数据格式。
- 不增加第二种推送渠道。
- 不修改现有 `DouyinCollectAndPush` 的 action、触发时间或任务设置。

---

## 三、架构与模块边界

```text
阶段 A：只读看门狗

wechat_health_probe.py
  ├─ SQLite mode=ro 读取所有启用 Feed
  ├─ 读取真实采集状态 JSON
  └─ 输出统一 verdict JSON，不发送消息、不写业务数据

wechat-health-watchdog.ps1
  ├─ 调用探针
  ├─ 执行去重/恢复状态机
  ├─ 调用 MeoW 并校验业务响应
  ├─ 写 incident state
  └─ 写每轮 run status + 日志

Windows 计划任务 WechatHealthWatchdog
  └─ 每小时在半点运行，避开现有采集任务的整点启动

阶段 B：登录状态快速通道

collect-wechat-and-push.ps1
  └─ 只补结构化健康元数据，不改变抓取与 bridge 逻辑
```

### 第一性原理结论

- 最底层问题不是 sidecar 不稳定，而是**真实失败没有一个能主动到达用户的结构化出口**。
- 不需要改数据库、sidecar 或整个采集架构。
- 最小治本方案是：先新增只读探针和独立通知状态机兜底，再给现有状态 JSON 补可靠字段提升告警准确度。

---

## 四、允许改动的文件

### 第二阶段（B）才允许修改

1. `deploy/local/collect-wechat-and-push.ps1`
   - 只允许补写 `login_state`、`failed_creator_count` 等健康元数据。
   - 禁止改变抓取、导出、bridge、Git 或退出状态的原有业务逻辑。

### 第一阶段（A）新建

2. `deploy/local/wechat_health_probe.py`
3. `deploy/local/wechat-health-watchdog.ps1`（必须 UTF-8 带 BOM）
4. `deploy/local/meow-push.example.json`
5. `tests/test_wechat_health_probe.py`
6. `tests/test_wechat_health_watchdog.py`

### 本机运行文件，不提交

7. `local-secrets/meow-push.json`
8. `E:\AI-news-reader\wechat-watchdog-state.json`
9. `E:\AI-news-reader\wechat-watchdog-run-status.json`
10. `E:\AI-news-reader\wechat-watchdog.log`
11. Windows 计划任务 `WechatHealthWatchdog`

### 明确禁止改动

- `.gitignore`（`local-secrets/` 已忽略）
- `data/**`
- `scripts/export_we_mp_rss_jsonl.py`
- 任何 sidecar 文件
- 现有 `DouyinCollectAndPush` 任务
- `.github/**`、前端页面和线上配置
- 用户现有 stash、其它未跟踪计划或运行数据

如实现必须越过以上边界，立即停下说明，不得自行扩大范围。

---

## 五、详细施工步骤

### 推荐执行顺序：拆成两个可独立验收的阶段

1. **阶段 A：只读看门狗 + MeoW**。只新增探针、编排脚本、测试和独立计划任务，不修改 `collect-wechat-and-push.ps1`。它先用现有 `state/stage` 和逐 Feed 新鲜度兜住停更、抓取不完整、bridge 失败和看门狗自身失败。
2. 阶段 A 真机验收通过后必须停下汇报。未经用户决定，不进入阶段 B，也不自动 commit、push。
3. **阶段 B：登录状态快速通道**。只给采集状态补 `login_state/failed_creator_count`，不改业务流程；自动化通过后，经用户明确确认真实跑一轮完整采集。
4. 两阶段应分别形成完整、可回滚的代码提交；是否提交仍由用户决定。

这样即使阶段 B 暂缓，2026-07-18 这类停更仍会被阶段 A 的新鲜度兜底发现，只是登录问题会先显示为“抓取不完整/停更”，而不是更精确的“登录失效”。

### 阶段 A1：实现只读健康探针

`wechat_health_probe.py` 必须把读取与判定分开：

#### 读取层

- `read_active_feed_syncs(db_path)`：
  - 使用 SQLite URI `mode=ro`。
  - 查询全部 `status=1` 的 `id/mp_name/sync_time`。
  - 连接创建也必须在异常处理范围内。
  - 数据库不存在、不可读、表缺失时返回结构化错误，不能伪装成“无数据”。
- `read_collect_status(status_path)`：
  - 强制按 UTF-8 读取。
  - 文件缺失、坏 JSON、字段类型非法时返回结构化错误。
- 绝不写数据库，测试必须验证数据库文件哈希或修改时间不变。

#### 判定层

`evaluate()` 必须是纯函数，输出统一 verdict：

```json
{
  "schema_version": 1,
  "decision": "healthy | alert | defer",
  "reason": "ok",
  "title": "微信采集正常",
  "message": "...",
  "active_feed_count": 3,
  "stale_feed_count": 0,
  "latest_success_epoch": 0,
  "checked_at": "UTC ISO time"
}
```

#### 判定优先级

| 优先级 | 条件 | 结果 |
|---|---|---|
| 1 | 数据库或状态文件不可读、时间字段非法、未来时间明显异常 | `alert / probe_error` |
| 2 | `state=running` 且运行不足 90 分钟 | `defer / collection_running`，不改变 incident state |
| 3 | `state=running` 超过 90 分钟 | `alert / collector_stuck` |
| 4 | 最新终态在最近一次数据库成功之后，且 `login_state=expired` | `alert / login_expired` |
| 5 | 最新终态在最近一次数据库成功之后，且 `state=warning` | `alert / fetch_incomplete` |
| 6 | 最新终态在最近一次数据库成功之后，且 `state=failed` | `alert / pipeline_failed`，消息带安全的 `stage` |
| 7 | 有新鲜 Feed，也有超时 Feed | `alert / partial_stale` |
| 8 | 全部启用 Feed 超时 | `alert / stale` |
| 9 | 全部启用 Feed 新鲜，旧失败早于新成功 | `healthy / ok` |

补充规则：

- 禁止继续使用 `max(sync_time)` 代表整体健康；必须逐 Feed 判断。
- `sync_time > now + 10 分钟` 视为时钟异常，不能直接判健康。
- `stale_hours <= 0` 视为参数错误。
- 如果没有启用 Feed，输出 `alert / no_active_feeds`，由用户确认是否确实不再使用微信采集。
- 探针只负责输出 verdict；它不读 MeoW 昵称、不发送网络请求、不写 incident state。

### 阶段 A2：实现 PowerShell 编排与状态机

`wechat-health-watchdog.ps1` 默认参数：

```text
RadarRoot        = 当前仓库根目录
DbPath           = E:\AI-news-reader\we-mp-rss-sidecar\data\db.db
CollectStatusFile= E:\AI-news-reader\wechat-collect-status.json
SecretFile       = <RadarRoot>\local-secrets\meow-push.json
StateFile        = E:\AI-news-reader\wechat-watchdog-state.json
RunStatusFile    = E:\AI-news-reader\wechat-watchdog-run-status.json
LogFile          = E:\AI-news-reader\wechat-watchdog.log
StaleHours       = 14
PythonExe        = <RadarRoot>\.venv\Scripts\python.exe
```

#### incident state 契约

```json
{
  "schema_version": 1,
  "status": "ok | alerting",
  "primary_reason": "ok",
  "latest_reason": "ok",
  "incident_started_at": null,
  "alert_sent_at": null,
  "recovery_pending": false,
  "updated_at": "UTC ISO time"
}
```

#### run status 契约

每一轮开始先写 `running`，每个退出路径都必须更新：

```json
{
  "schema_version": 1,
  "state": "running | succeeded | failed | deferred",
  "stage": "starting",
  "exit_code": null,
  "message_code": "starting",
  "started_at": "UTC ISO time",
  "finished_at": null
}
```

run status 和日志不得包含昵称、完整 MeoW URL、原始请求体或未经清洗的异常文本。

如果 Python 不存在、进程启动失败、退出码非 0 或输出不是合法 verdict JSON：

- 昵称配置可用时，PowerShell 必须在本地构造 `alert / watchdog_failed` verdict，继续走同一去重状态机并尝试推送；
- 昵称配置不可用时无法手机告警，但必须写 `run status=failed` 并返回非 0；
- 无论哪种情况，都不能把 incident state 伪装成 `ok`。

#### 状态转换

| 上次状态 | 本轮 verdict | 推送与落盘 |
|---|---|---|
| 无状态 | healthy | 初始化 `ok`，不推送 |
| 无状态/ok | alert | 推首次告警；成功后写 `alerting`，失败则不标记已告警 |
| alerting | alert | 不重复推送；只更新 `latest_reason` |
| alerting | healthy | 推恢复；成功后写 `ok` |
| alerting | healthy，但恢复推送失败 | 保持 `alerting`，写 `recovery_pending=true`，下轮重试 |
| 任意 | defer | 只写 run status，不改变 incident state |

必须增加命名互斥锁，防止计划任务与人工运行并发改写状态文件。

#### 可测试入口

脚本要提供显式测试参数，使 Python 测试可以在 PS5.1 下验证状态机而不访问真实 MeoW：

- `-ProbeFixtureFile`：读取测试 verdict，不调用真实 Python 探针。
- `-PushSinkFile`：把待推送的安全字段写进测试临时文件，不发网络请求。
- 两者只用于测试；生产计划任务不得传入。

### 阶段 A3：MeoW 安全与响应校验

真实配置：

```json
{
  "nickname": "用户在 MeoW 中设置的专属昵称"
}
```

要求：

1. PowerShell 5.1 必须用 `Get-Content -Raw -Encoding UTF8` 读取配置和状态 JSON。
2. 昵称为空或包含 `/` 时拒绝发送。
3. 使用 HTTPS 和 JSON POST：`https://api.chuckfang.com/<编码后的昵称>`。
4. 不仅检查 HTTP 异常，还要校验 MeoW 响应体 `status == 200`；缺字段或非 200 都算失败。
5. 异常日志只记录错误类别和安全状态码，不允许直接记录 `$_` 或完整 URI。
6. MeoW 昵称只是低强度路由标识，不是真正鉴权密钥；建议用户使用不容易被猜到的昵称。
7. 推送失败不得把 incident state 写成“已发送”。

### 阶段 A4：注册独立计划任务

只有阶段 A 的代码、自动化测试、PS5.1 真机测试和用户 MeoW 验收全部通过后，才能请求用户确认注册。

先检查是否已存在同名任务：

```powershell
Get-ScheduledTask -TaskName "WechatHealthWatchdog" -ErrorAction SilentlyContinue
```

如果已存在，立即暂停，不得覆盖。

用户确认后采用直接 PowerShell action，保留真实退出码，不使用 `conhost --headless`：

```powershell
$now = Get-Date
$firstRun = $now.Date.AddHours($now.Hour).AddMinutes(30)
if ($firstRun -le $now) { $firstRun = $firstRun.AddHours(1) }

$powershellExe = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
$arguments = '-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "E:\AI-news-reader\ai-news-radar-run\deploy\local\wechat-health-watchdog.ps1" -LogFile "E:\AI-news-reader\wechat-watchdog.log" -RunStatusFile "E:\AI-news-reader\wechat-watchdog-run-status.json"'
$action = New-ScheduledTaskAction -Execute $powershellExe -Argument $arguments
$trigger = New-ScheduledTaskTrigger -Once -At $firstRun `
  -RepetitionInterval (New-TimeSpan -Hours 1) `
  -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
  -ExecutionTimeLimit (New-TimeSpan -Minutes 10) -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName "WechatHealthWatchdog" -Action $action -Trigger $trigger `
  -Settings $settings -RunLevel Limited -User $env:USERNAME `
  -Description "微信采集健康看门狗，异常推送 MeoW"
```

约束：

- 每小时半点运行，尽量避开现有采集整点启动。
- 显式设置 3650 天重复期限，避免某些 Windows 版本把“只有间隔、没有期限”的 `-Once` 触发器处理成非持续重复；到期前如仍使用，再人工续期。
- 仅在用户已登录、机器开机且联网时可告警；关机、睡眠或未登录期间无法推送，这是本机方案的已知限制。
- `StartWhenAvailable` 用于错过后补跑。
- `MultipleInstances IgnoreNew` 与脚本互斥锁双重防并发。
- 任务不需要最高权限，禁止使用 `RunLevel Highest`。

注册后先核对触发器和下一次运行时间：

```powershell
$task = Get-ScheduledTask -TaskName "WechatHealthWatchdog"
$info = Get-ScheduledTaskInfo -TaskName "WechatHealthWatchdog"
$task.Triggers | Format-List StartBoundary,Repetition
$info | Select-Object LastRunTime,LastTaskResult,NextRunTime
```

手动“运行”只能证明 action 可执行，不能证明每小时重复。必须等到首次半点自动触发后再次执行上面的检查，确认 `LastRunTime` 已前进、`LastTaskResult=0`，且 `NextRunTime` 继续排到下一小时半点；否则阶段 A 不算完成。

### 阶段 B1：补齐真实采集状态契约

阶段 A 真机验收完成并停下汇报后，只有用户决定继续，才修改 `collect-wechat-and-push.ps1`：

1. 抓取开始前把 `login_state` 置为 `not_checked`。
2. 从现有 `$syncOutput` 中识别登录/会话失效：
   - `Invalid Session`
   - `session invalid/expired`
   - 中文“登录失效/过期”“凭证失效/过期”
3. 检测到上述模式时写 `login_state=expired`。
4. 只有同步脚本退出码为 0 且没有失败公众号时，才能写 `login_state=valid`。
5. 同步脚本非 0、输出无法解析，或有失败公众号但无法确定是否登录问题时，写 `login_state=unknown`。
6. 把 `$fetchFailedAccounts.Count` 写入 `failed_creator_count`。
7. 现有 `state`、`stage`、`message`、`exit_code`、抓取、导出、bridge 和 Git 行为保持不变。

禁止把整段原始异常写进新增字段，避免路径、账号或外部地址扩散。完成代码和自动化测试后，必须继续执行第七节的“阶段 B 真实完整采集验收”，不能只用临时状态文件宣告完成。

---

## 六、自动化测试

### Python 探针必须覆盖

1. 全部启用 Feed 新鲜 + 最新状态成功 → `healthy/ok`。
2. 一个新鲜、一个超时 → `alert/partial_stale`。
3. 全部超时 → `alert/stale`。
4. 真实格式 `state=warning + stage=fetch_warning + login_state=expired` → 立即 `login_expired`。
5. `state=warning` 但非登录问题 → `fetch_incomplete`。
6. `state=failed + stage=bridge_preflight` 且失败晚于 DB 成功 → `pipeline_failed`。
7. 旧失败早于后来成功的 DB 时间 → 不误报。
8. `running` 未满 90 分钟 → `defer`；超过 90 分钟 → `collector_stuck`。
9. 状态文件缺失、坏 JSON、非法时间。
10. 数据库缺失、损坏、表缺失、路径含空格或中文。
11. 未来 `sync_time`、空 Feed、`stale_hours <= 0`。
12. 临时 SQLite 只读检查：探针运行前后文件哈希或修改时间不变。

### PowerShell 状态机必须在 Windows PowerShell 5.1 下覆盖

1. 首次健康不推送。
2. 首次异常只推一条。
3. 同一异常重复运行不重复推送。
4. 异常原因变化不再次推送，只更新 `latest_reason`。
5. 恢复成功后只推一条恢复通知并写 `ok`。
6. 恢复推送失败时保持 `alerting/recovery_pending`，下一轮成功后再写 `ok`。
7. 告警推送失败时不标记已告警。
8. API 响应业务 `status != 200` 时算失败。
9. 中文昵称的 UTF-8 配置在 PS5.1 下读取正确。
10. 缺配置时 run status 为 `failed` 且退出码非 0；缺 Python或探针坏 JSON时，在昵称可用的测试条件下还必须产生一次 `watchdog_failed` 推送事件。
11. `defer` 不改变 incident state。
12. 并发第二实例被互斥锁安全跳过。

### Windows-only 测试必须带平台守卫

`tests/test_wechat_health_watchdog.py` 会拉起 Windows PowerShell，模块级必须写 `skipif`，非 Windows 或找不到 `powershell.exe` 时整模块跳过，不能让 Linux CI 因缺少系统程序而失败：

```python
import os
import shutil

import pytest

IS_WINDOWS = os.name == "nt"
POWERSHELL_EXE = shutil.which("powershell.exe") if IS_WINDOWS else None

pytestmark = pytest.mark.skipif(
    not IS_WINDOWS or POWERSHELL_EXE is None,
    reason="requires Windows PowerShell 5.1",
)
```

测试中的 `subprocess` 必须复用已解析的 `POWERSHELL_EXE`，不要再次硬编码命令名。平台守卫只解决跨平台兼容，不降低目标机验收：在本机 Windows 上必须先确认版本确为 5.1，并且该测试文件 **0 skipped**；若被跳过，阶段 A 不能完成。

### 必跑命令

跨平台基础门禁：

```powershell
cd E:\AI-news-reader\ai-news-radar-run

.\.venv\Scripts\python.exe -m py_compile deploy\local\wechat_health_probe.py
.\.venv\Scripts\python.exe -m pytest tests\test_wechat_health_probe.py tests\test_wechat_health_watchdog.py -q
.\.venv\Scripts\python.exe -m pytest -q
```

在非 Windows 环境，`test_wechat_health_watchdog.py` 因平台原因显示 skipped 可以接受；其余测试仍必须全绿。在目标 Windows 机器还必须执行：

```powershell
$ps51 = (Get-Command powershell.exe -ErrorAction Stop).Source
$ps51Version = & $ps51 -NoProfile -Command '$PSVersionTable.PSVersion.ToString()'
if (-not $ps51Version.StartsWith("5.1")) { throw "需要 Windows PowerShell 5.1，实际为 $ps51Version" }

.\.venv\Scripts\python.exe -m pytest tests\test_wechat_health_watchdog.py -q -rs
```

最后一条在目标机必须 PASS 且摘要中没有 skipped。阶段 B 修改采集脚本后，以上目标测试和全量 `pytest -q` 必须重新跑一遍。

PowerShell AST 与 BOM：

```powershell
$tokens = $null
$errors = $null
[System.Management.Automation.Language.Parser]::ParseFile(
  "E:\AI-news-reader\ai-news-radar-run\deploy\local\wechat-health-watchdog.ps1",
  [ref]$tokens,
  [ref]$errors
) | Out-Null
if ($errors.Count -ne 0) { $errors | Format-List; exit 1 }

$tokens = $null
$errors = $null
[System.Management.Automation.Language.Parser]::ParseFile(
  "E:\AI-news-reader\ai-news-radar-run\deploy\local\collect-wechat-and-push.ps1",
  [ref]$tokens,
  [ref]$errors
) | Out-Null
if ($errors.Count -ne 0) { $errors | Format-List; exit 1 }

$bytes = [IO.File]::ReadAllBytes("E:\AI-news-reader\ai-news-radar-run\deploy\local\wechat-health-watchdog.ps1")
if ($bytes.Length -lt 3 -or $bytes[0] -ne 0xEF -or $bytes[1] -ne 0xBB -or $bytes[2] -ne 0xBF) {
  throw "wechat-health-watchdog.ps1 不是 UTF-8 BOM"
}
```

最后执行：

```powershell
git diff --check
git status --short --branch
```

---

## 七、真机人工验收

> 自动化全绿不等于完成。MeoW、PS5.1、任务计划程序必须走真实路径。

### 阶段 A：只读看门狗验收

1. 用户亲自创建 `local-secrets/meow-push.json`；AI 不要求用户把真实昵称发进聊天。
2. 执行 `git check-ignore -v local-secrets/meow-push.json`，必须确认被忽略。
3. 用真实数据库和真实状态文件手动运行一次健康态：日志为健康，手机不推送，run status 为 `succeeded`。
4. 使用临时状态文件模拟真实格式：
   - `state=warning`
   - `stage=fetch_warning`
   - `login_state=expired`
   - `finished_at=当前时间`
   并给看门狗传独立的临时 StateFile/RunStatusFile/LogFile，手机必须收到“登录失效”。
5. 原样再运行一次，手机不得重复推送。
6. 把临时状态改为成功且 Feed 新鲜，手机收到一次“已恢复”。
7. 模拟恢复通知失败，确认 incident state 不会提前变 `ok`；随后恢复网络再跑，必须补发恢复通知。
8. 用临时状态模拟 `state=failed + stage=bridge_preflight`，必须收到“采集链路失败”，不能因数据库新鲜而判健康。
9. 检查日志、incident state、run status 均不含真实昵称；检查时只输出 `NICKNAME_LEAK=False`，不得把昵称打印到终端。
10. 用户确认后注册计划任务，在任务计划程序中手动“运行”一次：
    - 无可见窗口；
    - `LastTaskResult=0`；
    - `NextRunTime` 有值且落在下一次半点附近；
    - run status 更新时间前进；
    - 日志新增一行；
    - 健康态不打扰手机。
11. 等到首次半点自动触发后再次检查，确认 `LastRunTime` 已前进、`LastTaskResult=0`，且 `NextRunTime` 又排到下一小时半点。只做过手动“运行”不算验证了持续重复。
12. 验收产生的临时文件逐个按明确路径清理，禁止批量删除。

阶段 A 全部通过后停下汇报。此时“停更/抓取不完整/bridge 失败”告警已经可用；是否进入阶段 B 由用户决定。

### 阶段 B：真实完整采集验收（强制，不得用模拟文件替代）

修改 `collect-wechat-and-push.ps1` 属于敏感主链路变更。自动化测试通过后，先暂停并向用户说明：下面的命令会真实抓取、真实导出，并可能在 `E:\AI-news-reader\wechat-bridge` 产生提交和推送。只有用户明确确认后才能执行。

执行前要求：

1. `E:\AI-news-reader\wechat-bridge` 工作区必须干净；如有未提交改动立即停下，不得替用户清理。
2. 记录 bridge 当前分支和本地 HEAD 供验收比较，但汇报时不必展示完整提交 ID。
3. 确认 `wechat-collect-status.json` 和日志路径是现有正式路径，不用临时模拟状态文件。

用户确认后只运行一轮，不自动重试：

```powershell
cd E:\AI-news-reader\ai-news-radar-run

$ps51 = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
& $ps51 -NoProfile -ExecutionPolicy Bypass `
  -File ".\deploy\local\collect-wechat-and-push.ps1" `
  -LogFile "E:\AI-news-reader\wechat-collect.log" `
  -StatusFile "E:\AI-news-reader\wechat-collect-status.json"
$collectExitCode = $LASTEXITCODE
if ($collectExitCode -ne 0) { throw "真实微信采集失败，exit=$collectExitCode" }

$collectStatus = Get-Content -Raw -Encoding UTF8 "E:\AI-news-reader\wechat-collect-status.json" | ConvertFrom-Json
$collectStatus | Select-Object state,stage,exit_code,login_state,failed_creator_count,output_rows,content_changed,bridge_changed
```

必须同时满足：

- 抓取确实执行，正式导出文件仍可读取；`output_rows` 与实际导出结果一致。
- `state=succeeded`、`exit_code=0`，且 `stage` 只能是原有成功终态：`completed_no_change`、`completed_pushed` 或 `completed_pushed_subscription_only`。
- `message` 与对应成功终态的原有语义一致，没有因新增字段改变原有状态流程。
- `login_state=valid` 且 `failed_creator_count=0`，证明新增字段来自这次真实采集，而不是测试夹具。
- 若 `stage=completed_no_change`，bridge HEAD 不应变化；若为两个 `completed_pushed*` 之一，本地与远端 HEAD 必须一致，证明原有 commit/push 闭环仍正常。
- 再用正式状态文件手动运行一次看门狗，应判为健康，不发送误报告警。
- 最终 `git diff` 证明采集脚本只补健康元数据，没有改变抓取、导出、bridge、Git 或退出码逻辑。

只要真实采集得到 `warning/failed`、登录未变成 `valid`、导出不一致或 bridge 本地/远端不一致，就保留当轮状态和日志并立即停下汇报；不得自动重跑、自动扫码、自动改数据或把模拟测试当成替代验收。

---

## 八、回归与回滚

### 旧功能回归

- `collect-wechat-and-push.ps1` 的原有抓取、导出、bridge、Git 行为不得改变。
- 原有 `state/stage/message/exit_code` 语义不得改变，只补健康元数据。
- sidecar 数据库修改时间和内容不得因探针变化。
- `DouyinCollectAndPush` 的两个 action、三个触发器和现有设置不得变化。

### 运行时回滚

优先采用可恢复操作：

```powershell
Disable-ScheduledTask -TaskName "WechatHealthWatchdog"
```

恢复：

```powershell
Enable-ScheduledTask -TaskName "WechatHealthWatchdog"
```

禁止施工 AI 自动注销任务或批量删除状态、日志。确需永久移除时，先向用户确认，再一次只处理一个明确对象。

### 代码回滚

- 未提交前，只能逐个恢复本计划列出的文件，不能使用 `git reset --hard`。
- 已提交后使用正常 `git revert`，不强推、不重写历史。
- 新增的 collector 字段为向后兼容补充；回滚看门狗时不需要改 sidecar 或数据库。

---

## 九、强制暂停条件

遇到任一情况立即停下汇报：

1. 当前分支不是 `feat/wechat-watchdog-meow-push`。
2. 阶段 A 已完成，但用户还没有决定进入阶段 B。
3. 用户尚未明确确认执行阶段 B 的真实完整采集。
4. 真实采集前发现 `E:\AI-news-reader\wechat-bridge` 工作区不干净。
5. 真实采集脚本的状态字段或状态流程与本计划再次不符。
6. 必须改 sidecar、数据库结构、抓取逻辑、bridge 格式或现有计划任务才能继续。
7. 需要安装新依赖、联网安装软件或新增服务。
8. MeoW 官方响应不再包含可验证的成功状态。
9. PS5.1 自动化测试无法运行、被意外 skip 或中文编码验收失败。
10. 同名计划任务已经存在。
11. 全量测试出现与本次改动相关的失败。
12. Git diff 出现本计划允许清单以外的文件。

---

## 十、完成定义与汇报格式

### 阶段 A 可独立交付的完成条件

- 未修改 `collect-wechat-and-push.ps1`，只读探针、MeoW 状态机及独立任务已完成。
- 登录失效可先由 `warning/停更` 兜底；部分停更、全部停更、bridge 失败、看门狗自身失败能被区分。
- 目标 Windows 上 PowerShell 测试为 0 skipped，MeoW 真机告警/去重/恢复通过。
- 首次半点自动触发后 `NextRunTime` 继续前进，证明任务确实每小时重复。
- 完成后已停下汇报，未擅自进入阶段 B。

### 整体 V2 的完成条件

只有阶段 A 和阶段 B 同时满足以下条件，整体 V2 才算完成：

- 真实状态契约已对齐，不再依赖虚构的 `failed + message` 组合。
- 登录失效、部分停更、全部停更、bridge 失败、看门狗自身失败都能被区分。
- 告警不重复，恢复失败可以重试。
- MeoW 业务响应经过校验，昵称不泄露。
- PS5.1、目标测试、全量测试、AST、BOM、diff 检查全部通过。
- 用户确认后真实完整运行过一轮 `collect-wechat-and-push.ps1`，原有抓取/导出/bridge 行为正常，且正式状态中的 `login_state=valid`、`failed_creator_count=0`。
- 用户完成真机 MeoW 和计划任务验收。
- 最终 diff 只包含允许文件。
- 未经授权没有 commit、push、合并或覆盖任务。

完成后只汇报：

1. 修改文件清单。
2. 每条命令的真实 PASS/FAIL。
3. 真机 MeoW 与计划任务验收结果。
4. 当前分支和 `git status`。
5. 未验证项与剩余风险。
6. 两阶段建议分别提交，中文 Commit Message：
   - 阶段 A：`功能：新增微信采集只读看门狗与 MeoW 告警`
   - 阶段 B：`功能：补充微信登录失效快速告警状态`

汇报后停下，等待用户决定是否提交代码。

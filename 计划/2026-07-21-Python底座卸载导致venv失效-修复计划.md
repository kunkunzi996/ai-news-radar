# Python 底座卸载导致 .venv 失效 · 开发记录

> 通道：轻量 ｜ 版本：PLAN v1.0 — FROZEN ｜ 冻结时间：2026-07-22 00:24:34 +08:00 ｜ 状态：FROZEN（产品负责人接受遗留风险）

## ① 计划正文

### 0. 通道声明

**轻量通道 · PLAN v1.0 — FROZEN**

> **冻结裁决**：产品负责人于 2026-07-22 明确决定“就这样，先冻结”。`PLAN-01`、`PLAN-02` 的 `STILL OPEN` 结论保留为已知风险，不伪装为已关闭；产品负责人接受按当前版本冻结，后续不得自行重开架构讨论。冻结仅代表计划定稿，**不代表已经授权执行施工命令**。

因 PLAN-04 取消了"回滚成本近似为零"这一原始依据，此处**重新评估**通道判定。轻量仍然成立，但依据换成以下四条：

1. 根因已实测确认，非假设；
2. 业务代码零改动（全项目无硬编码 3.11 路径，已 grep 验证）；
3. 不触碰 `data/`、归档清理路径、接口、权限，无数据迁移；
4. 方案无设计空间——重建虚拟环境是唯一标准解，不存在"另一种架构"。

**但必须显式承认：本方案是单向的（forward-only），没有回退路径。** 详见第 4.3 节与 P0 风险。这一点不改变通道，但改变施工纪律：**T1 停服务之后到 T6 恢复之前，没有中途放弃的选项。**

### 1. 本轮目标

> **【v0.9.4 · 产品负责人决策】先停用采集计划任务，修好再恢复（取代 v0.9.2 的方案 B「让 23:00 挂一轮」）。**
> 新增 **T0.5 停用** 与 **T7.5 恢复**，成对强制执行。23:00 那轮将**不跑**而非**跑了失败**，因此 `wechat-collect-status.json` 保持 `succeeded`，T4 应返回 `healthy`，**T5B 预期不再触发**。时间压力随之解除。

1. 微信采集链路恢复可用；采集任务在 T7.5 恢复自动运行（**代价**：停用期间跳过的轮次不自动补，如需补回走 T5B）。
2. 微信健康看门狗恢复正常判定，推送「微信采集已恢复」，`alerting` 状态清零。
3. 本地面板从"活死人"状态转为**真正可重启**，4 个 worktree 逐一验证可用。
4. 消除"重启即永久挂掉"的悬顶风险（见 3.2）。

### 2. 本轮不做什么

| 排除项 | 理由 |
|---|---|
| 改任何 `.py` / `.ps1` 业务代码 | 根因在环境不在代码 |
| 改计划任务配置 | 任务定义本身没问题 |
| 重装 Python 3.11 | 用户已确认有意卸载去重；仅在 T2/T3 失败时作为**用户决策项**重新提出 |
| 删除任何目录或文件 | 项目红线；旧 venv 只改名，残留清理列清单交用户手动 |
| 手工把 `405f65f.rbf` 改回 `python.exe` 抢救 | 属对抗 MSI 卸载状态的 hack，重启即失效，且与用户去重意图相反 |
| 碰 `data/` / 线上 Actions | 与本次故障无关 |
| 排查 10:30–14:30 那轮 `pipeline_failed` | 15:30 已自愈，独立事件 |
| 改造 venv 管理方式（uv / 集中式 / 版本守护） | 见 P2 延期项 |

### 3. 项目调查结果

#### 3.1 根因（已确认）

venv 的 `Scripts\python.exe` 是转接头（stub），启动时读 `pyvenv.cfg` 找底座解释器。底座没了，转接头失效——但**stub 文件本身还在**。

```
# .venv/pyvenv.cfg
home = C:\Program Files\Python311
executable = C:\Program Files\Python311\python.exe    ← 已不存在
version = 3.11.9

$ ./.venv/Scripts/python.exe deploy/local/wechat_health_probe.py ...
No Python at '"C:\Program Files\Python311\python.exe'
EXIT=103
```

评审员独立复核结论一致，并追加验证：**系统 Python 3.13 直接运行只读探针返回 `decision=healthy`、退出码 0**——这是 3.13 可行性的最强前置证据，等价于一次免费的兼容性预检。

#### 3.2 【v0.9.1 新增】卸载未完成，当前服务是"活死人"

评审后追加实测，发现比原计划描述严重：

| 证据 | 命令 / 输出 |
|---|---|
| `C:\Program Files\Python311` **空无一物** | `Get-ChildItem -File` 返回空 |
| 底座被 MSI 改名待删 | 3 个进程 `ProcessName = 405f65f.rbf`，`Path = C:\Program Files\Python311\python.exe` |
| 已进重启删除队列 | 注册表 `HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\PendingFileRenameOperations` 含大量 `C:\Config.Msi\*.rbf` |
| 面板**仍然活着** | `http://127.0.0.1:8080/` 与 `:8093/` 均 HTTP 200，27749 bytes |

**机理**：用户卸载 3.11 时 python.exe 正被面板占用，Windows Installer 无法删除，遂将其改名为 `405f65f.rbf` 并登记为"重启后删除"。已启动的进程握着文件句柄仍可运行，但**任何新进程都找不到该路径**。

**三条推论，直接决定施工纪律**：

- **P0-A**：面板现在能用是假象。**停止即无法重启**——T1 停服务是一道单向门。
- **P0-B**：**这台机器只要重启一次，3 个面板进程全部消失且起不来。** 所以本修复不是"今晚可选项"，是必须做，且拖得越久越可能被一次意外重启引爆。
- **P0-C**：反过来说，修复本身**必须**停这些进程——Windows 文件锁下 `.venv` 被占用时无法改名。停服务不可回避。

#### 3.3 【v0.9.3 重写｜PLAN-01 二轮】进程树真相：持有端口的是**子进程**，且命令行不含 `.venv`

二轮复审指出原盘点漏掉底座子进程。经实测复核，**评审判断成立**，且实际结构比原表更关键：

```
PID 32368  "E:\...\ai-news-radar-run\.venv\Scripts\python.exe" scripts/local_server.py --port 8080   ← stub，父进程
  └─ PID 23396  "C:\Program Files\Python311\python.exe" scripts/local_server.py --port 8080          ← 底座，子进程【真正监听 8080】

PID 37604  "E:\...\ai-news-radar-run\.venv\Scripts\python.exe" scripts\local_server.py --port 8093   ← stub，父进程
  └─ PID 28688  "C:\Program Files\Python311\python.exe" scripts\local_server.py --port 8093          ← 底座，子进程【真正监听 8093】
```

**三条决定性事实**：

1. **venv stub 只是启动器，真正 listen 端口的是它拉起的底座子进程。**
2. **子进程命令行是 `"C:\Program Files\Python311\python.exe" ...`，不含 `ai-news-radar-run\.venv` 字样** → v0.9.2 的筛选条件 `CommandLine -like "*ai-news-radar-run\.venv*"` **匹配不到它们**。照原方案执行会杀掉父进程、留下持有端口的孤儿子进程，`Rename-Item .venv` 随即失败。
3. **两类进程的命令行都含 `local_server.py`** → 这是能同时覆盖父子的共同特征，但**唯一权威依据仍是端口反查**（`Get-NetTCPConnection -OwningProcess`），因为要释放的正是端口本身。
4. 工具差异需注意：`Get-Process` 显示子进程名为 `405f65f.rbf`（文件已被 MSI 改名），`Get-CimInstance` 显示 `python.exe`（记录的是创建时名称）。**按进程名匹配不可靠，不要用。**

PID 每次重启服务都会变（对比 v0.9.2 记录的 21572/7268 现已变为 28688），**施工时一律以 T0 实测为准，禁止照抄本表**。

**8093 上有 3 个进程、8080 上 1 个，两个端口返回内容完全相同（同为 27749 bytes）**——8093 那几个疑似历史重复启动的残留。**恢复时只恢复 8080（面板启动器 `open-ai-news-radar.ps1` 的默认口），8093 是否恢复交用户决定**（对应 PLAN-01「只恢复本轮确认需要保留的服务」）。

WeRSS sidecar（8001）**当前未运行**——影响 T5 验证设计，见该任务说明。

#### 3.4 受影响清单（grep 实测）

| 入口 | 引用位置 | 后果 |
|---|---|---|
| 微信采集 | `deploy/local/collect-wechat-and-push.ps1:176` → `:395` 执行 `scripts/export_we_mp_rss_jsonl.py` | **23:00 那轮必挂**（该脚本 `import requests`） |
| 健康看门狗 | `deploy/local/wechat-health-watchdog.ps1:21` | 已挂，每小时半点复发 |
| 本地面板启动器 | `scripts/windows/open-ai-news-radar.ps1:9`，目标 `http://127.0.0.1:8080/` | 现在起不来（活死人状态） |
| 4 个 worktree | `.venv` 均为符号链接 → `ai-news-radar-run/.venv/`，四条链接现均 `Test-Path = True` | 连带失效 |

**不受影响**（已核实）：抖音采集（走 `MediaCrawler-local-test` 自带 venv）、`we-mp-rss-sidecar`（其 `pyvenv.cfg` 底座已是 Python 3.13）、线上 GitHub Actions。

#### 3.5 兼容性与验证手段

- **无任何脚本硬编码 `Program Files\Python311`**，全部引用相对路径 → 重建同名目录即可全链路自动恢复，零代码改动。
- 依赖极少且全为纯 Python 包，3.13 零兼容风险：requests 2.32.3 / beautifulsoup4 4.12.3 / feedparser 6.0.11 / python-dateutil 2.9.0.post0 / tzdata 2026.2 ＋ pytest 8.3.4 / PyYAML 6.0.2 / pyflakes 3.2.0。
- **探针只用标准库** → venv 一建起来看门狗即可恢复，与装包成败解耦。
- **【v0.9.1 新增】存在无副作用的采集链路验证方式**：`collect-wechat-and-push.ps1` 的 `-SkipSync` 开关，脚本第 407-410 行注释明确「只允许产出 TEMP 诊断文件；不 pull、不替换、不暂存、不 commit」，并自带断言 `if ($headAfterDiagnostic -ne $bridgeHeadBefore) { throw "-SkipSync changed bridge HEAD unexpectedly." }`。此即 PLAN-02 所要求的安全验证路径，**无需用户批准受控真跑**。

#### 3.6 顺带发现的既有缺陷（本轮不修）

`collect-wechat-and-push.ps1:238` 的 preflight 只校验 `$PythonExe` **文件存在**。本次故障中 stub 文件一直存在、只是跑不起来 → preflight 放行，直到 395 行才炸。记为 P2 延期。

#### 3.7 【v0.9.2 新增｜v0.9.3 补时点】选择方案 B 的连锁影响：23:00 失败会打歪两个验收关卡

> **⚠ v0.9.4 已使本节所述连锁不再发生。** 产品负责人决定改走 **T0.5 停用采集任务**：23:00 那轮**不跑**，`wechat-collect-status.json` 保持 `succeeded`，探针返回 `healthy`，T7 恢复推送直接可达，**T5B 预期不触发**。
> 本节予以保留，作为两个用途：① 记录"为什么必须停用而不是放任失败"的推理依据；② 万一 T0.5 未及时生效、已有轮次跑了并失败，本节即是当时的判读手册（T4 失败处置已引用）。

产品负责人决策放弃 23:00 那轮后，追查探针判定逻辑（`deploy/local/wechat_health_probe.py:311-346`）发现该决策**并非只是"少一轮内容"**：

```python
terminal_after_success = bool(finished_epoch > latest_success_epoch)
if terminal_after_success and state == "failed":
    return _safe_result(decision="alert", reason="pipeline_failed", ...)
```

23:00 那轮失败时，`collect-wechat-and-push.ps1` 会把 `E:\AI-news-reader\wechat-collect-status.json` 写成 `state: failed`，且 `finished_at` 晚于最近一次成功时间 → 探针此后**必然返回 `decision=alert` / `reason=pipeline_failed`**。两处连锁：

| 受影响关卡 | 原完成标准 | 选 B 后的实际情况 |
|---|---|---|
| **T4 静态验证** | 探针须返回 `decision: healthy` | **必然返回 `alert/pipeline_failed`**。原失败处置写的是"返回 alert 即暂停上报"，会让开发者误判为撞上第二故障而错误中止施工 |
| **T7 看门狗恢复** | 须 `recovery_sent`、`status` 回 `ok` | 看门狗判 alert，因已处于 `alerting` 而走 `alert_suppressed`，**不发恢复推送、状态清不掉，警报持续是哑的** |

**处置**：新增 **T5B 手动补跑一轮真实采集**（需用户批准，见该任务）。它同时解决三件事：

1. 补回 23:00 丢失的那轮内容——**抵消方案 B 的数据代价**；
2. 把采集状态写回 `succeeded`，使 T7 的 `recovery_sent` 重新可达，警报真正上膛；
3. 提供比 `-SkipSync` 更强的端到端证据（真实推 bridge 全链路）。

T4 与 T7 的完成标准已按此重写。

### 4. 技术方案

#### 4.1 核心变更

```
旧：.venv/pyvenv.cfg → C:\Program Files\Python311\python.exe（已改名待删）✗
新：.venv/pyvenv.cfg → C:\Program Files\Python313\python.exe（现存）      ✓
     ↑ 目录名不变，所有脚本与 4 条符号链接零感知
```

走最小改动第 1 档：复用现有结构，不新增不重构。

#### 4.2 服务生命周期（PLAN-01）

```
T0 盘点(只读)  →  T1 停服务+改名  →  T2 建  →  T3 装依赖  →  T4/T5 验证  →  T6 恢复服务
                 └────────────── 面板不可用窗口（预计 3–6 分钟）──────────────┘
```

**不可用窗口内 8080/8093 全断，这是预期的，不是故障。**

#### 4.3 【v0.9.1 修订】关于回滚——本方案单向不可逆

**原 v0.9 的"改名即可回滚 / 回滚成本近似为零"是错误表述，此处作废。**

`.venv.broken-py311` 的 `pyvenv.cfg` 仍指向已被改名待删的 3.11 底座，**把名字改回去照样退出码 103**。它**只是故障留档**，不是恢复手段。

因此本方案的真实性质是：**前向修复，无回退。** 唯一的"真回滚"是重装 Python 3.11——那是**用户决策**，不是开发者可以自行执行的操作（见 T3 失败处置）。

这也是 4.2 那个窗口必须连续走完的原因：**中途放弃 = 面板持续不可用**。

### 5. 文件改动清单

**业务代码改动：0 个文件。** 仅环境目录变更：

| 路径 | 操作 | 是否新建 | 影响范围 | 失败处置 |
|---|---|---|---|---|
| `ai-news-radar-run/.venv` | 改名为 `.venv.broken-py311` | 否 | 全部本机 Python 入口 | 改名失败即进程未停干净，回 T1 |
| `ai-news-radar-run/.venv` | 由 Python 3.13 新建 | 是 | 同上 | 见 T2/T3 失败处置，**不删除**，隔离+上报 |
| `.venv/Lib/site-packages/*` | pip 安装 8 个包 | 是 | 采集链路 | 重跑 pip；仍失败则上报 |

**回滚列已按 PLAN-04 移除**——本方案无回滚，仅有失败处置路径。

### 6. 分步施工任务

> 全程在 `E:\AI-news-reader\ai-news-radar-run` 下执行。
> **T1 一旦开始，必须连续走到 T6**，中途没有可停留的安全状态（见 4.3）。

#### T0 — 盘点与基线记录（只读，不停任何服务）

- **目标**：拿到本次要停/要恢复的精确清单，作为 T6 恢复依据
- **前置**：无
- **操作**（v0.9.3 按 PLAN-01 二轮重写：**端口反查为主，命令行匹配为辅，两路取并集**）：
  ```powershell
  # 1【权威路】按端口反查真正的持有者（含底座子进程）
  $byPort = Get-NetTCPConnection -State Listen -LocalPort 8080,8093 -ErrorAction SilentlyContinue |
    ForEach-Object {
      $p = Get-CimInstance Win32_Process -Filter "ProcessId=$($_.OwningProcess)"
      [pscustomobject]@{ Port=$_.LocalPort; PID=$p.ProcessId; Parent=$p.ParentProcessId; Cmd=$p.CommandLine }
    }
  $byPort | Format-List

  # 2【补漏路】按 local_server.py 匹配，可同时覆盖 stub 父进程与底座子进程
  $byCmd = Get-CimInstance Win32_Process |
    Where-Object { $_.CommandLine -like "*local_server.py*" -and
                   ($_.CommandLine -like "*ai-news-radar-run*" -or $_.CommandLine -like "*Python311*") } |
    Select-Object ProcessId, ParentProcessId, CommandLine
  $byCmd | Format-List

  # 3【待停清单】两路并集，去重后落进施工报告
  $targets = @($byPort.PID) + @($byCmd.ProcessId) | Sort-Object -Unique
  "待停 PID: $($targets -join ', ')"

  # 4【基线】记录服务可用性，供 T6 恢复后对比
  foreach ($p in 8080,8093) { try { "$p -> " + (Invoke-WebRequest "http://127.0.0.1:$p/" -TimeoutSec 5 -UseBasicParsing).StatusCode } catch { "$p -> DOWN" } }
  ```
- **禁止**：
  - 本步不得 `Stop-Process`，不得改名任何目录；
  - **不得按进程名（`python.exe` / `405f65f.rbf`）匹配**——`Get-Process` 与 `Get-CimInstance` 对同一进程报的名字不同（见 3.3 第 4 条），按名匹配必漏必错。
- **完成标准**：四份输出已记录到 ③ 施工报告，其中**待停清单必须同时含 stub 父进程与底座子进程**（正常应为 4–6 个 PID，只有 4 个纯 `.venv` 进程说明漏了子进程，需重查）
- **验收**：施工报告中可见端口反查表（含 Parent 列）、命令行匹配表、待停 PID 并集、HTTP 基线

#### T0.5 — 【v0.9.4 新增｜产品负责人决策】停用采集计划任务，解除时间压力

- **决策来源**：产品负责人提出「先完全停止，修好再重启」，取代"抢在 23:00 前完成"。
- **目标**：让 23:00 那轮**根本不跑**（而不是跑了失败），从而保住 `wechat-collect-status.json` 的 `succeeded` 状态，使整条验收链不必绕行 T5B
- **为什么优于让它失败**：
  | | 让它跑（原方案 B） | 停用（本任务） |
  |---|---|---|
  | 23:00 那轮 | 跑了并失败 | 不跑 |
  | `wechat-collect-status.json` | 被写成 `failed` | **保持 `succeeded`** |
  | T4 探针预期 | `alert/pipeline_failed` | **`healthy`** |
  | T7 恢复推送 | 发不出，需 T5B 救场 | **直接可达** |
- **前置**：T0 完成
- **操作**：
  ```powershell
  Disable-ScheduledTask -TaskName "DouyinCollectAndPush"
  Get-ScheduledTask -TaskName "DouyinCollectAndPush" | Select-Object TaskName, State   # 应为 Disabled
  ```
- **⚠ 副作用（已获产品负责人知情同意）**：该任务挂着**两个动作**——抖音采集 + 微信采集，停用是整任务停，**抖音也会一起停**。计划任务不支持只禁用其中一个动作（需改任务定义，风险更高，不做）。若修复在 23:00 前完成并恢复，两者均不受影响；若跨过 23:00，抖音同样少一轮（其下一轮为次日 07:00）。
- **`WechatHealthWatchdog` 保持启用**：施工窗口内它会记 `probe_failed`，但因已处 `alerting` 会被抑制、**不打扰用户**；同时充当安全网——即使 T7 被遗漏，它下个半点会自动发出恢复推送。
- **禁止**：修改任务定义 / 触发器 / 动作；停用除 `DouyinCollectAndPush` 之外的任何任务
- **完成标准**：`DouyinCollectAndPush` 状态为 `Disabled`
- **验收**：上述 `Get-ScheduledTask` 回显
- **🔴 强制回收项**：本任务与 **T7.5 成对存在**。**未执行 T7.5 恢复启用，本次施工不算完成**——遗漏会导致采集永久停摆且无告警（看门狗只看采集结果，不看任务是否被禁用）。

#### T1 — 停止服务并隔离旧环境（⚠ 单向门）

- **目标**：释放文件锁，旧 venv 退出使用但完整保留
- **前置**：T0 完成；**已向用户确认可以开始不可用窗口**
- **操作**（v0.9.3 按 PLAN-01 二轮重写：**停子+停父 → 硬闸门 → 才改名**）：
  ```powershell
  # 1. 停掉 T0 待停清单的全部 PID（父子都在内；PID 以 T0 实测为准，禁止照抄计划示例）
  foreach ($id in $targets) { Stop-Process -Id $id -Force -ErrorAction SilentlyContinue }

  # 2.【硬闸门】重查两路，必须同时为空才允许继续
  $stillPort = Get-NetTCPConnection -State Listen -LocalPort 8080,8093 -ErrorAction SilentlyContinue
  $stillProc = Get-CimInstance Win32_Process |
    Where-Object { $_.CommandLine -like "*local_server.py*" -and
                   ($_.CommandLine -like "*ai-news-radar-run*" -or $_.CommandLine -like "*Python311*") }
  if ($stillPort -or $stillProc) {
      "闸门未通过：残留端口 $($stillPort.LocalPort -join ',') / 残留 PID $($stillProc.ProcessId -join ',')"
      # → 补停残留 PID 后重跑本闸门；连续两次仍不通过则暂停上报，不得强行改名
  } else {
      Rename-Item .venv .venv.broken-py311
  }
  ```
- **为什么必须有闸门**（3.3）：stub 父进程与底座子进程是两个进程，只停父会留下**持有端口和文件句柄的孤儿子进程**，此时 `Rename-Item` 必然失败或改出半锁状态。
- **禁止**：
  - 使用 `Remove-Item -Recurse`（项目红线，且断了故障留档）
  - **闸门未通过就执行 `Rename-Item`**——包括"重试几次说不定就好了"
  - 在改名失败时反复重试——那说明还有进程占用，回头补停
  - 顺手 kill 无关的 python 进程（sidecar / MediaCrawler / WeRSS 不在本轮范围）
  - 按进程名匹配（见 3.3 第 4 条）
- **完成标准**：闸门通过（两路均空）；`.venv.broken-py311` 存在、`.venv` 不存在
- **验收**：`Test-Path .venv` → False；`Test-Path .venv.broken-py311` → True；`Get-NetTCPConnection -State Listen -LocalPort 8080,8093` → 空
- **失败处置**：闸门连续两次不通过 → **暂停并上报**，附残留 PID 与其命令行；不得强行改名

#### T2 — 用 Python 3.13 重建

- **目标**：同名 venv 回到位，底座换成现存解释器
- **前置**：T1 完成
- **操作**：`py -3.13 -m venv .venv`
- **完成标准**：`.venv/pyvenv.cfg` 的 `home` 为 `C:\Program Files\Python313`
- **验收**：`.venv/Scripts/python.exe -V` → `Python 3.13.x`，且不再出现 `No Python at`
- **失败处置**（PLAN-04）：
  1. **不要删除**任何东西；
  2. 把半成品改名隔离：`Rename-Item .venv .venv.failed-<时间戳>`；
  3. **立即上报用户**，说明面板处于不可用窗口中；
  4. 是否改用其它 Python 版本（含重装 3.11）**由用户决定**，开发者不得自行安装或卸载任何 Python。

#### T3 — 安装依赖

- **目标**：采集链路第三方包齐全
- **前置**：T2 验收通过
- **操作**：`.venv/Scripts/python.exe -m pip install -r requirements-dev.txt`（首行 `-r requirements.txt`，一次装齐 8 个）
- **禁止**：装不带版本号的散装包；升级 requirements 里的钉版；用 `--force-reinstall` 掩盖报错
- **完成标准**：pip 无 ERROR
- **验收**：`.venv/Scripts/python.exe -c "import requests, feedparser, bs4, dateutil, yaml, pytest; print('ok')"`
- **失败处置**：同 T2 第 1–3 条；另需在报告中贴出 pip 完整报错（可能推翻 3.13 兼容性判断）

#### T4 — 静态验证（无副作用）

- **目标**：确认探针与测试全绿，**本步不产生任何 MeoW 推送**
- **前置**：T3 验收通过
- **操作**：
  ```powershell
  # 探针
  .venv\Scripts\python.exe deploy\local\wechat_health_probe.py `
    --db-path "E:\AI-news-reader\we-mp-rss-sidecar\data\db.db" `
    --status-path "E:\AI-news-reader\wechat-collect-status.json" --stale-hours 14
  # 单测
  .venv\Scripts\python.exe -m pytest tests\test_wechat_health_probe.py tests\test_wechat_health_watchdog.py -q
  ```
- **完成标准**（v0.9.4 按 T0.5 重写）：探针输出**合法 JSON 且退出码 0**——这是本步真正要证明的事（venv 能跑起来），`decision` 判读如下：
  | 情形 | 预期 decision | 判读 |
  |---|---|---|
  | **已执行 T0.5**（本轮实际路径） | **`healthy`** | 采集任务已停用，23:00 那轮不会跑，状态保持 `succeeded`，探针应报健康 |
  | 未执行 T0.5 且已过 23:00 | `alert` / `reason: pipeline_failed` | 那轮跑了并失败，探针如实反映（见 3.7），属预期而非第二故障 |
  - 两个测试文件全绿（不受上述影响）
- **验收**：命令回显 + 退出码 + `decision` / `reason` 字段
- **失败处置**（v0.9.4 收窄）：
  - `healthy` → 正常，走 T5，**并跳过 T5B**；
  - `reason` 为 `pipeline_failed` → 若已执行 T0.5，说明**停用没生效或另有轮次跑过**，需先查清原因再决定是否走 T5B；若未执行 T0.5 则属预期；
  - `reason` 为 `login_expired` / `fetch_incomplete` / 其它任何值 → 存在被环境故障掩盖的第二故障，**暂停并上报**；
  - 探针崩溃、输出非法 JSON 或退出码非 0 → **暂停并上报**（venv 本身没修好）

#### T5 — 【v0.9.1 新增｜PLAN-02】采集链路真跑验证（无副作用模式）

- **目标**：**真实走通** `collect-wechat-and-push.ps1` → 导出器 → 桥接链路，而不是靠 `import` 成功来推断
- **前置**：T4 全绿
- **为什么安全**：`-SkipSync` 只产出 TEMP 诊断文件，不 pull、不替换、不暂存、不 commit，脚本自带 bridge HEAD 未变的断言（见 3.5）
- **操作**（v0.9.3 按 PLAN-02 二轮修订）：
  ```powershell
  powershell -NoProfile -ExecutionPolicy Bypass -File deploy\local\collect-wechat-and-push.ps1 `
    -SkipSync `
    -StatusFile "$env:TEMP\t5-verify-status.json" `
    -LogFile    "$env:TEMP\t5-verify.log"
  $LASTEXITCODE
  ```
- **⚠ 关键：`-StatusFile` 必须指向 TEMP 临时路径，绝不可指向 `E:\AI-news-reader\wechat-collect-status.json`。** 正式文件是看门狗的判定依据，被覆盖会污染 T7。
  （`Write-RunStatus` 实现为 `if ($StatusFile) {...}`——不传则完全不落盘，那样就拿不到结构化证据，所以这里改为传临时路径。）
- **🔴 退出码契约（PLAN-02 二轮核心）：`-SkipSync` 成功路径的退出码是 `1`，不是 `0`。**
  脚本第 412 行：
  ```powershell
  Exit-Run "warning" "skip_sync_diagnostic_only" "Diagnostic export completed; bridge HEAD and formal files were not changed." 1
  ```
  `Exit-Run` 末尾 `exit $ExitCode` → **退出码 1 且 state=warning 才是本任务的成功信号**。
  v0.9.2 写的"退出码 0"是错的，照此执行会把成功判成失败。**反过来，若真的返回 0，说明没走 SkipSync 诊断路径，属异常，必须暂停排查。**
- **允许的副作用**（仅此四项）：
  1. 在 TEMP 生成诊断用 JSONL / 快照文件（**不会被自动清理**——`Exit-Run` 仅在 `state=succeeded` 时删 TEMP，本路径是 `warning`，正好留作验收物证）；
  2. 在 TEMP 生成上述临时状态文件与日志；
  3. 若 WeRSS sidecar（8001）未运行，脚本会将其拉起——**实测 8001 当前未运行，预期会被启动**；
  4. 只读访问 sidecar 数据库。
- **禁止**：去掉 `-SkipSync` 真推 bridge；把 `-StatusFile` 指向正式路径；手工改 `wechat-collect-status.json`；为"让它过"而修改脚本
- **完成标准**（全部满足）：
  | 检查项 | 期望值 |
  |---|---|
  | 退出码 | **`1`**（不是 0） |
  | `$env:TEMP\t5-verify-status.json` → `state` | `warning` |
  | 同上 → `stage` | `skip_sync_diagnostic_only` |
  | 同上 → `exit_code` | `1` |
  | 是否抛出 `-SkipSync changed bridge HEAD unexpectedly` | **否** |
  | `git -C E:\AI-news-reader\wechat-bridge status --short` | 无改动 |
  | TEMP 诊断 JSONL | 存在 |
  - 注：脚本会调 `Show-FetchAlert` 打红字告警，这在 `-SkipSync` 路径属**正常提示**，不作为失败判据；以上表格为准。
- **验收**：上述七项逐条记入 ③ 施工报告
- **失败处置**：暂停上报。**这是唯一能在不动生产数据的前提下暴露真实链路问题的关卡，不得因"import 都过了"而跳过。**
- **与采集状态的关系**（v0.9.3 修订）：本任务证明代码路径可跑通，但**刻意不改变正式采集状态**；数据补回与状态复位由 T5B 按条件负责

#### T5B — 【v0.9.2 新增｜方案 B 配套】手动补跑一轮真实采集（⚠ 有副作用，需用户批准）

- **触发条件**（v0.9.4 更新）：**当且仅当 T4 探针返回 `alert / pipeline_failed`**（即确有某轮跑了并失败）。
  **采用 T0.5 后，本任务预期不会被触发**——任务已停用，23:00 那轮不跑，状态保持 `succeeded`，T4 应返回 `healthy` → **直接跳到 T6/T7**。
  本任务保留为两种情形的兜底：① T0.5 未及时生效、已有失败轮次；② 用户希望**手动补回**因停用而跳过的那一轮内容（此时属自愿补数据，非故障修复，同样需用户批准）。
- **目标**：三合一——① 补回 23:00 丢失的那轮内容；② 把 `wechat-collect-status.json` 写回 `succeeded`，使 T7 的恢复推送重新可达；③ 提供真实推 bridge 的端到端证据
- **前置**：T5 按其**退出码契约**通过（退出码 `1` + `state=warning` + `stage=skip_sync_diagnostic_only`，见 T5 完成标准表）；**且已取得用户对"真实采集（含推送 bridge 仓库）"的明确批准**（PLAN-02 所要求的受控真跑授权）
- **⚠ 两个任务退出码契约相反，别混淆**（v0.9.3）：**T5 成功 = exit 1**（诊断路径）；**T5B 成功 = exit 0 + `state: succeeded`**（真跑完成路径）。用 T5 的标准判 T5B、或反过来，都会得出错误结论。
- **操作**（参数对齐计划任务实际调用，**这次要传 `-StatusFile`**）：
  ```powershell
  powershell -NoProfile -ExecutionPolicy Bypass -File deploy\local\collect-wechat-and-push.ps1 `
    -LogFile "E:\AI-news-reader\wechat-collect.log" `
    -StatusFile "E:\AI-news-reader\wechat-collect-status.json"
  ```
- **与 T5 的关键差别**：T5 带 `-SkipSync`、**禁止**传 `-StatusFile`（避免污染判据）；T5B **不带** `-SkipSync`、**必须**传 `-StatusFile`（目的就是更新判据）。两者不可互换，也不可合并。
- **允许的副作用**（真跑，均为 23:00 那轮本应发生的事，只是延后执行）：
  1. 向 `wechat-bridge` 仓库真实 commit / push；
  2. 覆写 `wechat-collect-status.json`；
  3. 写入 `data/` 下的采集产物（走正常采集管线，**不涉及任何归档清理路径**）。
- **禁止**：
  - 未获用户批准即执行；
  - 为"让它过"而修改脚本、手改状态文件、或补跑失败后伪造 `succeeded`；
  - 触碰任何归档清理开关（`WE_MP_ORPHAN_CLEANUP_MODE` 等保持默认 `off`）。
- **完成标准**：退出码 0；`wechat-collect-status.json` → `state: succeeded`；日志无 failed creator。
  - 注：`new_unique_items` 为 0 属正常（该时段可能确无新文章），**不作为失败判据**——本任务验的是链路，不是产量。
- **验收**：退出码 + 状态文件内容 + `git -C E:\AI-news-reader\wechat-bridge log --oneline -3`
- **失败处置**：**暂停并上报**。不得重复重试掩盖问题；保留日志与状态文件原样供诊断。

#### T6 — 【v0.9.1 新增｜PLAN-01 + PLAN-03】恢复服务并逐一验证

- **目标**：结束不可用窗口，并**逐个**证明 4 个 worktree 与面板真的可用
- **前置**（v0.9.3 明确）：T5 按其退出码契约通过（exit `1` + `skip_sync_diagnostic_only`）；**若 T5B 被触发，则 T5B 亦须通过（exit `0` + `state: succeeded`）**。两者退出码契约相反，判定时对号入座。
- **操作**：
  ```powershell
  # 1. 恢复面板（8080，启动器默认口）
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\windows\open-ai-news-radar.ps1 -NoBrowser

  # 2. 四个 worktree 逐一验证（缺一不可，逐条记录输出）
  foreach ($d in "ai-news-radar-aihot","ai-news-radar-github-stars","ai-news-radar-wechat-flat","ai-news-radar-workbench-bridge") {
    "$d -> " + (& "E:\AI-news-reader\$d\.venv\Scripts\python.exe" -V 2>&1)
  }
  ```
- **8093 的处置**（v0.9.3 按实测更新）：8093 上有 **3 个 stub 进程争抢同一端口，实际只有 1 个底座子进程抢到监听权**（典型的重复启动残留），且返回内容与 8080 完全相同。**默认不恢复**；是否需要保留由用户决定后再起（PLAN-01「只恢复本轮确认需要保留的服务」）。
- **完成标准**：
  - 8080 返回 HTTP 200；
  - **4 条 worktree 全部输出 `Python 3.13.x`**，逐条记入施工报告（一条都不能省略或推断）；
  - **面板须用真实浏览器验证**（项目 CLAUDE.md 铁律：browser-visible flow 必须浏览器工具实测，不得以 HTTP 200 代替）：
    - 打开 `http://127.0.0.1:8080/`
    - 页面正常渲染、信息流有条目（非空白/非报错页）
    - **浏览器控制台无 error 级别报错**
    - 留存截图
- **禁止**：以 `curl` / `Invoke-WebRequest` 200 作为面板验收结论；以任一 worktree 的结果推断其余三个
- **验收**：4 条解释器输出 + 浏览器截图 + 控制台无错记录

#### T7 — 看门狗端到端恢复（会真发推送）

- **目标**：清掉 `alerting` 状态，用户手机收到恢复确认
- **前置**：T6 通过；**且采集状态已为 `succeeded`**——即 T5B 已成功执行，或 T4 当时就返回 `healthy`（未触发 T5B）
- **⚠ 前置不满足会静默失败**（v0.9.2）：若采集状态仍是 `failed`，探针判 alert，看门狗因已处于 `alerting` 而走 `alert_suppressed`——**不推送、状态不变、退出码 4**，看上去"跑完了"其实什么也没恢复。**不得把这种情况当作通过。**
- **操作**：
  ```powershell
  powershell -NoProfile -ExecutionPolicy Bypass -File deploy\local\wechat-health-watchdog.ps1 `
    -LogFile "E:\AI-news-reader\wechat-watchdog.log" `
    -RunStatusFile "E:\AI-news-reader\wechat-watchdog-run-status.json"
  ```
- **预期副作用**：**用户会收到一条「微信采集已恢复」推送——预期结果，不是新故障。**
- **完成标准**：日志新增 `recovery_sent`；`wechat-watchdog-state.json` → `status: ok` / `primary_reason: ok`；`wechat-watchdog-run-status.json` → `state: succeeded` / `exit_code: 0`
- **为什么必须做**：当前 `alerting` 状态会让后续故障走 `alert_suppressed` 被静默吞掉。这一步是"警报系统重新上膛"。
- **验收**：三个文件内容 + 用户确认收到推送

#### T7.5 — 【v0.9.4 新增】恢复采集计划任务（🔴 强制，与 T0.5 成对）

- **目标**：把 T0.5 停用的任务放回自动运行，结束"人工托管"状态
- **前置**：T7 通过（或 T7 因故未跑但环境已验证可用——**任务恢复不得因 T7 未完成而拖延**，两者失败模式不同）
- **操作**：
  ```powershell
  Enable-ScheduledTask -TaskName "DouyinCollectAndPush"
  Get-ScheduledTask -TaskName "DouyinCollectAndPush" | Select-Object TaskName, State
  Get-ScheduledTaskInfo -TaskName "DouyinCollectAndPush" | Select-Object TaskName, LastRunTime, NextRunTime, LastTaskResult
  ```
- **完成标准**：
  - `State` = `Ready`（不是 `Disabled`）；
  - **`NextRunTime` 有值且是未来时刻**——若在 23:00 前恢复则应为**今日 23:00**，若已跨过则应为**次日 07:00**。`NextRunTime` 为空说明触发器出了问题，须暂停排查。
- **验收**：上述三行回显逐条记入 ③ 施工报告
- **失败处置**：`State` 未回到 `Ready` 或 `NextRunTime` 为空 → **立即上报**，并明确告知用户"采集目前仍处于停摆状态"，不得默认它会自愈
- **为什么单列一个任务而不并进 T8**：T8 是交用户手动执行的收尾清单；本任务是**开发者必须亲自完成的强制回收项**，两者责任人不同，合并会造成遗漏。

#### T8 — 收尾移交（不由开发者执行）

按项目红线，目录删除由用户手动完成。开发者只列清单：

1. `E:\AI-news-reader\ai-news-radar-run\.venv.broken-py311`（故障留档，观察 1–2 天后删）
2. `C:\Program Files\Python311\`（空壳目录）
3. **建议用户择机重启一次**——让 Windows 执行 `PendingFileRenameOperations` 清掉 `C:\Config.Msi\*.rbf`，把 3.11 的卸载真正做完。**修复完成后重启是安全的**（届时面板已能正常重启）。

### 7. 数据和接口变化

| 项 | 旧 | 新 | 兼容性 | 迁移 | 失败处置 |
|---|---|---|---|---|---|
| `.venv/pyvenv.cfg` home | Python311 | Python313 | 环境元数据，非业务接口 | 无需 | 隔离+上报（无回滚） |
| site-packages | 3.11 编译产物 | 3.13 重装 | 纯 Python 包，无 ABI 依赖 | 无需 | 重装 |
| 业务数据 / 归档 / 配置 | — | 不涉及 | — | — | — |

**本轮不触碰 `data/archive.json` 及任何归档清理路径。**

### 8. 风险清单

| 级别 | 风险 | 应对 |
|---|---|---|
| **P0** | **【新增】任何一次系统重启都会让 3 个面板进程永久消失**（`PendingFileRenameOperations` 生效） | 尽快完成 T1–T6；施工期间不重启机器 |
| **P0** | **【修订】本方案无回退路径**，T1 后中途放弃 = 面板持续不可用 | 4.3 已明示；T1 前必须取得用户开工确认；T2/T3 失败按"隔离+上报+用户决策"处置 |
| **P0** | **【v0.9.4 新增】忘记执行 T7.5 恢复计划任务** → 采集**永久停摆且无任何告警**（看门狗只看采集结果，不看任务是否被禁用；采集不跑 = 状态文件不更新 = 探针看到的仍是旧的 `succeeded`，**不会报警**） | T7.5 列为强制回收项并写入交接清单；完成标准要求 `State=Ready` 且 `NextRunTime` 有值 |
| **P0** | **【v0.9.4 改判】23:00 那轮被跳过**（原方案 B 是"跑了失败"，现改为"不跑"）——状态文件因此保持干净 | 由产品负责人决策接受；如需补回内容走 T5B（自愿，非故障修复） |
| **P0** | 当前处于 `alerting`，期间任何新故障都会被 `alert_suppressed` **静默吞掉**（含 23:00 那轮失败——**不会有新推送**，别误以为没事） | T7 重新武装警报；T7 前置不满足时不得判通过 |
| **P1** | T1 停服务时误杀 sidecar / MediaCrawler 等无关 python 进程 | 停止条件严格限定 `*ai-news-radar-run\.venv*local_server.py*` |
| **P1** | T5 若误传 `-StatusFile` 会覆盖采集状态、污染看门狗判定 | 已在 T5 显式禁止 |
| **P1** | T7 会真发 MeoW 推送 | 已标注为预期副作用，提前告知用户 |
| **P1** | T4 探针若返回 `alert`，说明存在被掩盖的第二故障 | T4 设失败处置：暂停上报 |
| **P2** | `collect-wechat-and-push.ps1:238` preflight 只验存在不验可执行 | 延期；建议改为跑一次 `python -V` 探活 |
| **P2** | 无机制守护 venv 底座版本，下次卸 Python 会重演 | 延期；可选在探针加底座自检 |
| **P2** | 8093 三个疑似残留进程来历不明 | T6 默认不恢复，交用户决定 |

### 9. 验收剧本

| 场景 | 操作 | 期望 | 归属任务 |
|---|---|---|---|
| 正常路径 | 跑探针 | 合法 JSON、exit 0；`decision` 按 3.7 分情况判读（23:00 后预期 `alert/pipeline_failed`） | T4 |
| **补跑真采集** | 不带 `-SkipSync` 真跑（需用户批准） | exit 0、状态回 `succeeded`、bridge 有新 commit | **T5B** |
| 依赖完整性 | `import requests, feedparser, bs4, dateutil, yaml, pytest` | 无 ImportError | T3 |
| 原功能回归 | `pytest tests/ -q` | 与基线一致，无新增失败 | T4 |
| **采集链路真跑** | `collect-wechat-and-push.ps1 -SkipSync` | exit 0、bridge HEAD 未变、TEMP 诊断文件生成 | **T5** |
| **worktree 逐一** | 4 个目录各跑一次 `python -V` | **4 条全部** 3.13.x | **T6** |
| **面板浏览器实测** | 真实浏览器打开 8080 | 页面渲染正常、有内容、控制台无 error、留截图 | **T6** |
| 告警状态机 | 跑一次看门狗 | 发「已恢复」，state 回 `ok` | T7 |
| 重复操作 | 紧接着**再跑一次**看门狗 | 日志 `healthy`，**不重复推送** | T7 |
| 错误输入 | 探针传不存在的 db 路径 | 输出结构化 verdict，不崩溃、不误报 watchdog_failed | T4 |
| 次日复核 | 查 23:00 那轮 `wechat-collect-status.json` | `state: succeeded` | ④ 台账 |

### 10. 开发者交接

- **执行顺序**：T0（只读盘点）→ **T0.5（停用采集任务）** → T1 → T2 → T3 → T4 → T5 →〔T5B 条件触发，预期跳过〕→ T6 → T7 → **T7.5（恢复采集任务，强制）** → T8（交用户）。
- **T1 开工前必须拿到用户对"面板不可用窗口"的明确确认。**
- **T1–T6 必须连续完成**，中途没有安全停留点（4.3）。
- **🔴 T0.5 与 T7.5 成对，缺 T7.5 则本次施工不算完成**——采集会永久停摆且无告警（看门狗只看采集结果，不看任务是否被禁用）。
- **已冻结不可改**：不删目录只改名；不改业务代码；不自行安装/卸载任何 Python；依赖钉版不动；T5 必须带 `-SkipSync` 且**不带** `-StatusFile`；**T5B 必须先取得用户批准，且必须传 `-StatusFile`、不带 `-SkipSync`**；T6 必须逐一验证 4 个 worktree 且面板须浏览器实测。
- **开发者可自定**：命令用 PowerShell 还是 Bash 写法；pip 是否加 `--no-cache-dir`；截图工具选择。
- **必须暂停并上报**：
  1. T2/T3 失败（隔离半成品，等用户决定 Python 版本，**不得自行装卸 Python**）；
  2. T4 探针返回 `alert` **且 reason 不是 `pipeline_failed`**（被掩盖的第二故障）；`pipeline_failed` 属方案 B 预期，继续走；
  3. T5 抛出 bridge HEAD 变更断言，或退出码非 0；T5B 退出码非 0 或状态未回 `succeeded`；
  4. T6 中任一 worktree 不是 3.13.x，或浏览器控制台有 error；
  5. 发现除 4 个 worktree 外还有其它软链/硬编码指向该 venv；
  6. 任何需要动 `data/` 的念头——直接停。
- **时间窗**（v0.9.4 已解除）：产品负责人决定采用 **T0.5 停用 → 修复 → T7.5 恢复**，**施工不再有工期压力**，也不必赶 23:00。
  - 早于 23:00 完成并恢复 → 那轮照常跑，什么也没丢；
  - 晚于 23:00 完成 → 那轮被跳过（**不是失败**），状态干净，如需补内容再走 T5B。
  - **不得因"想赶在 23:00 前"而跳过任何验收步骤**——停用任务的全部意义就是买下这个从容。
- **两条硬约束**（与时点无关）：
  1. **施工完成前不要重启这台机器**（重启会让面板进程永久消失，见 3.2 / P0）；
  2. 施工若跨过次日 07:00 那轮采集，需在 ④ 台账中额外复核该轮结果。

---

## ② 评审台账（计划）

### 第一轮评审 · PLAN_REVIEW

**结论：BLOCK** ｜ 架构师处理：**4 条 P1 全部接受，无拒绝、无延期。**

评审员追加的实测证据（旧 venv exit 103、系统 3.13 跑探针 healthy/exit 0）已并入 3.1 节作为兼容性前置证据。

另：处理评审意见期间追加实测，发现**卸载未完成 + 面板处于"活死人"状态 + 重启即永久挂掉**（新 3.2 节），已升为 P0 风险，并据此重排任务顺序与失败处置。此为新增信息，非评审意见所要求，提请二轮一并复核。

#### PLAN-01 · P1 · 服务生命周期缺失

- **架构师回应：接受改。**
- 新增 **T0**（只读盘点：进程 / 端口 / HTTP 基线，附可执行命令），新增 **T6**（恢复服务）。
- 新增 3.3 节，附实测进程端口表：8080×1、8093×3，两口内容相同（均 27749 bytes）。
- T6 按评审要求「只恢复本轮确认需要保留的服务」：**默认只恢复 8080**，8093 三个疑似残留进程交用户决定。
- 停止条件收窄为 `*ai-news-radar-run\.venv*local_server.py*`，避免误杀 sidecar / MediaCrawler（新增 P1 风险）。
- T0 与 T6 均给出可验收命令（`Test-Path`、`Get-NetTCPConnection`、HTTP 基线对比）。

#### PLAN-02 · P1 · 未真正走过采集链路

- **架构师回应：接受改。**
- 调查后确认**存在无副作用验证方式**，因此不需要"用户批准受控真跑"：`collect-wechat-and-push.ps1 -SkipSync`，脚本第 407-410 行注释与 bridge HEAD 断言为证（见 3.5）。
- 新增 **T5**，为 23:00 前**必须完成**的阻塞任务，写明：安全命令、三项允许副作用（TEMP 诊断文件 / 拉起 sidecar / 只读访问 db）、成功标准（exit 0 + HEAD 未变 + 诊断文件存在）、失败暂停条件。
- 追加一条评审未提及的坑：**T5 不得传 `-StatusFile`**，否则覆盖 `wechat-collect-status.json` 污染看门狗判定（已列 P1）。
- 关于「是否需等 23:00 状态文件复核」：**T5 通过即可下施工结论**，23:00 那轮复核列入 ④ 验收台账次日执行，**不作为本轮阻塞条件**——理由是 T5 已覆盖同一条代码路径，再等 2 小时不增加信息量。

#### PLAN-03 · P1 · worktree 与面板验收不足

- **架构师回应：接受改。**
- 4 个 worktree 改为**逐一执行并逐条记录**，写进 T6 完成标准，并显式禁止「以一个推断其余三个」。
- 面板验收补齐：启动命令（`open-ai-news-radar.ps1 -NoBrowser`）、URL（`http://127.0.0.1:8080/`）、**按项目 CLAUDE.md 铁律用真实浏览器验证**（页面渲染 / 有内容 / 控制台无 error / 留截图），并**显式禁止以 HTTP 200 代替浏览器验收**。
- 以上验收已从"可选剧本"**归属到 T6 施工任务**，第 9 节验收剧本表新增「归属任务」列，消除孤儿验收项。

#### PLAN-04 · P1 · 回滚表述失实且与删除红线冲突

- **架构师回应：接受改。评审判断完全正确，原表述是错的。**
- 删除「改名即可回滚」「回滚成本近似为零」全部表述；第 5 节「回滚」列改为「失败处置」列。
- 新增 **4.3 节**明确定性：`.venv.broken-py311` 指向已改名待删的 3.11 底座，**改回名字仍 exit 103，只是故障留档，不是恢复手段**；本方案为 **forward-only 单向修复，无回退路径**。
- 第 0 节通道声明**重新论证**：撤掉"回滚成本近似为零"这条依据，改以「根因确认 / 零代码改动 / 不动数据接口权限 / 方案无设计空间」四条支撑轻量判定，并显式声明单向性对施工纪律的约束。
- T2/T3 失败处置改为**符合删除红线**的三步：不删除 → 改名隔离为 `.venv.failed-<时间戳>` → 上报用户；并写明**是否重装/改用其它 Python 版本由用户决定，开发者不得自行安装或卸载任何 Python**。
- 「无回退路径」升为 P0 风险，并据此要求 T1 开工前取得用户对不可用窗口的明确确认。

### 产品负责人决策（v0.9.2）

**决策：采用方案 B——不抢 23:00，先走完二轮复审再从容施工。**

架构师据此追查连锁影响，发现该决策**不止是"少一轮内容"**（详见 3.7）：23:00 失败会把采集状态写成 `failed`，导致

1. T4 的"探针须 healthy"必然不达标，且原失败处置会误导开发者中止施工；
2. T7 因看门狗走 `alert_suppressed` 而**无法发出恢复推送、`alerting` 清不掉**，警报持续是哑的。

**处理**：新增 **T5B 手动补跑真实采集**（条件触发 + 需用户批准），一并解决数据补回、状态复位与端到端验证；T4 完成标准改为分情况判读，T7 补充前置与"静默失败"警示；风险表、验收剧本、交接章节同步更新。

**提请二轮复审注意**：T5B 是**新引入的有副作用任务**，与 PLAN-02「若不存在无副作用方式，必须明确由用户批准受控真跑」直接相关，请一并核对其授权门槛与失败处置是否充分。

### 第二轮关闭复审 · PLAN_CLOSE_REVIEW

**结论：BLOCK**

#### PLAN-01 · P1 · PARTIALLY CLOSED

- **已关闭部分**：已补充 T0 只读盘点、T1 停服前置、T6 服务恢复、端口验收和用户开工确认，原先“没有服务生命周期步骤”的问题已处理。
- **仍未关闭**：T0/T1 的筛选条件只匹配命令行中带 `ai-news-radar-run\.venv` 的 `local_server.py` 进程；调查表中记录的 `405f65f.rbf` 底座子进程命令行不含该路径，因此会被漏掉。执行 `Stop-Process` 后它仍可能占用端口，导致“端口已释放”或 `Rename-Item .venv` 失败。
- **关闭要求**：补齐底座子进程/进程树的盘点与停止规则，并在改名前用“无匹配进程 + 端口为空”作为硬闸门。

#### PLAN-02 · P1 · OPEN

- **已关闭部分**：已增加 T5 的 `-SkipSync` 安全链路验证，也为需要真实补跑的 T5B 增加了用户批准、状态文件和 bridge 推送验收。
- **仍未关闭**：计划要求 T5 成功时“退出码 0”（第 6 节 T5 完成标准），但实际脚本 `collect-wechat-and-push.ps1` 在 `-SkipSync` 成功诊断路径调用 `Exit-Run ... 1`，会以退出码 `1` 结束。开发者照计划执行时，即使链路验证成功也会被判失败，无法按计划继续。
- **关闭要求**：使 T5 的预期退出码/状态判定与脚本真实契约一致，并同步修正 T5、T5B、T6 的前置和验收门槛。

#### PLAN-03 · P1 · CLOSED

- T6 已明确逐一验证 4 个 worktree，并要求真实浏览器、页面内容、控制台无 error 和截图；原验收覆盖不足问题已关闭。

#### PLAN-04 · P1 · CLOSED

- 已删除“改名即可回滚”和“回滚成本近似为零”的错误表述，明确 forward-only；T2/T3 失败只改名隔离、不删除，并交由用户决定 Python 版本，已关闭原回滚与删除红线问题。

两轮评审已用尽；PLAN-01、PLAN-02 尚未关闭，不建议冻结，**不得发起第三轮评审**。

【下一步交给：产品负责人裁决】

### 架构师对二轮的回应（v0.9.3）

> 遵守收敛规则：**不发起第三轮评审**。以下修改仅针对二轮点名的两个未关闭项，未重开任何已 CLOSED 的议题，亦未扩大方案范围。

#### PLAN-01（PARTIALLY CLOSED）→ 已按关闭要求修订

- **架构师处理：接受，评审判断成立。** 实测复核确认漏判，且拿到了确切进程树：
  ```
  PID 32368  .venv\Scripts\python.exe  scripts/local_server.py --port 8080   ← stub 父进程（原筛选条件只能匹配到它）
    └─ PID 23396  "C:\Program Files\Python311\python.exe" ...--port 8080     ← 底座子进程【真正 listen 8080】
  PID 37604  .venv\Scripts\python.exe  ...--port 8093
    └─ PID 28688  "C:\Program Files\Python311\python.exe" ...--port 8093     ← 底座子进程【真正 listen 8093】
  ```
  底座子进程命令行确实**不含 `ai-news-radar-run\.venv`**，原方案会留下持有端口的孤儿进程。
- **修订内容**：
  1. **3.3 节整节重写**为进程树真相，含四条决定性事实；
  2. **T0 改为双路盘点**：端口反查（权威）＋ `local_server.py` 命令行匹配（补漏），取并集形成待停清单；并给出"只有 4 个纯 `.venv` 进程即说明漏了子进程"的自检标准；
  3. **T1 加硬闸门**：停完后重查「端口无监听 **且** 无匹配进程」，两路同时为空才允许 `Rename-Item`；闸门未过禁止改名，连续两次不过则暂停上报；
  4. 追加禁令：**禁止按进程名匹配**——`Get-Process` 报 `405f65f.rbf`、`Get-CimInstance` 报 `python.exe`，同一进程两个名字，按名匹配必错（此为评审未提及、实测发现的额外陷阱）。

#### PLAN-02（OPEN）→ 已按关闭要求修订

- **架构师处理：接受，评审判断成立。** 复核脚本第 412 行确认：
  ```powershell
  Exit-Run "warning" "skip_sync_diagnostic_only" "Diagnostic export completed; ..." 1
  ```
  `Exit-Run` 末尾 `exit $ExitCode` → `-SkipSync` 成功路径**退出码就是 1**。v0.9.2 写"退出码 0"确会把成功判成失败。
- **修订内容**：
  1. **T5 完成标准改为七项检查表**，退出码期望值改为 **`1`**，并明确 **`state=warning` + `stage=skip_sync_diagnostic_only`** 才是成功信号；反向补充：**若返回 0 属异常**（说明没走诊断路径），须暂停排查；
  2. **T5 改为传 TEMP 临时 `-StatusFile`**——原"不传 StatusFile"会导致 `Write-RunStatus` 的 `if ($StatusFile)` 直接跳过、拿不到结构化证据；改为临时路径后既有物证又不污染正式判据（正式路径仍为硬禁止）；
  3. 补充 TEMP 诊断文件**不会被自动清理**的依据（`Exit-Run` 仅在 `state=succeeded` 时删 TEMP，本路径为 `warning`），使其可作为验收物证；
  4. 注明 `Show-FetchAlert` 红字在此路径属正常提示，不作失败判据；
  5. **同步修正前置与门槛**（评审明确要求）：T5B 前置改为引用 T5 新契约；T6 前置改为"T5 按退出码契约通过；若 T5B 触发则其亦须通过"；并加粗提示 **T5 成功=exit 1 / T5B 成功=exit 0**，两者契约相反，禁止互套。

### 产品负责人裁决（v0.9.4）

**裁决：不抢 23:00，也不放任它失败——改为「先停用采集任务，修好再恢复」。**

原话：「我们修的都不知道要多久，能不能先完全停止，等我们修好了，再重启呢」。

架构师评估：**该方案严格优于 v0.9.2 的方案 B**，因为它把"跑了失败"变成"根本不跑"，从而保住 `wechat-collect-status.json` 的 `succeeded` 状态，使 T4→T7 整条验收链不必绕行 T5B（对比表见 T0.5）。据此修订：

1. 新增 **T0.5 停用 `DouyinCollectAndPush`**，并向产品负责人明示副作用——该任务挂着抖音+微信两个动作，**停用会连抖音一起停**，已获知情同意；
2. 新增 **T7.5 恢复启用**，列为开发者**强制回收项**，与 T0.5 成对；
3. 新增 P0 风险「忘记 T7.5」——此项**不会触发任何告警**（采集不跑 → 状态文件不更新 → 探针看到旧的 `succeeded` → 不报警），故在交接、完成标准、风险表三处冗余标注；
4. `WechatHealthWatchdog` **保持启用**，理由：施工期噪音被 `alert_suppressed` 吸收不打扰用户，且它是 T7 被遗漏时的自动安全网；
5. T4 完成标准改为预期 `healthy`；T5B 降级为条件兜底（预期不触发）；3.7 节保留为判读手册；第 10 节时间窗宣告解除。

#### 一并提请裁决的时点变化（非评审意见，已被上述裁决取代）

v0.9.3 修订完成于 **22:0x**，**23:00 那轮尚未开始**，采集状态仍为 `succeeded`。这使方案 B 决策时不存在的"仍可赶上 23:00"重新成为选项。计划两条路都已覆盖（T5B 条件触发），**无需再改方案**，仅需产品负责人按裁决时点选择即可。详见第 10 节时间窗。

### 第三次核对（产品负责人授权 · 定向确认）

**范围**：仅核对第二轮仍未关闭的 `PLAN-01`、`PLAN-02`；不重新评审其它内容，不新增问题编号。

#### PLAN-01 · P1 · STILL OPEN

- **已核实**：端口反查 + 命令行补漏 + 父子进程并集，已经能覆盖原先漏掉的 `405f65f.rbf` 底座子进程；停后“双路为空”硬闸门也已写入。
- **仍未关闭**：按 T0 命令原样在 PowerShell 执行时，命令行匹配条件会把执行这段盘点命令的 PowerShell 自身纳入 `$byCmd`（本次只读复现的待停 PID 并集包含当前检查 shell）。T1 随后对 `$targets` 逐个 `Stop-Process`，可能先杀掉正在执行施工的 shell，导致硬闸门和改名步骤中断。
- **关闭要求**：从待停清单中明确排除当前执行 shell 及其必要祖先进程（或改用不会匹配自身命令文本的进程识别方式），并增加“待停清单不得包含施工执行器 PID”的硬验收。

#### PLAN-02 · P1 · STILL OPEN

- **已核实**：T5 主任务已采用正确契约：TEMP `-StatusFile`、`exit 1`、`state=warning`、`stage=skip_sync_diagnostic_only`；T5B/T6 的主要门槛也已同步。
- **仍未关闭**：T5B 说明第 6 节仍写“**T5 ... 禁止传 `-StatusFile`”，但 T5 实际命令明确要求传 TEMP `-StatusFile`；第 9 节验收表仍把 T5 期望写成 `exit 0`。开发者按旧文案执行会丢失结构化物证，或把正确的诊断结果误判为失败。
- **关闭要求**：清除同一计划内所有旧契约文字，统一为“正式 `wechat-collect-status.json` 禁止覆盖；TEMP `-StatusFile` 必须传；T5 成功为 exit 1”，并用全文检索确认无残留 `T5 + exit 0` / “T5 禁止传 -StatusFile”表述。

**定向确认结论：仍有 STILL OPEN，不能建议冻结。** 本次授权的定向确认已用尽，不得再次发起；
【下一步交给：产品负责人】

### 产品负责人最终裁决（2026-07-22）

- **裁决**：接受 `PLAN-01`、`PLAN-02` 仍为 `STILL OPEN` 的已知风险，按当前内容冻结，不再继续评审。
- **冻结状态**：`PLAN v1.0 — FROZEN`，冻结时间 `2026-07-22 00:24:34 +08:00`。
- **边界**：本裁决只授权冻结计划书，未授权执行 T0.5、T1 或任何停任务、停服务、改名、安装依赖等施工操作。
- **后续规则**：施工必须另行取得产品负责人开工指令；冻结后不得自行修改目标、范围或技术方向。

【下一步交给：产品负责人（终审完成，待另行下达开工指令）】

---

## ③ 施工报告

_待开发者填写。_

---

## ④ 代码评审与验收台账

_待代码评审员 / QA 填写。次日需复核 23:00 那轮 `wechat-collect-status.json`。_

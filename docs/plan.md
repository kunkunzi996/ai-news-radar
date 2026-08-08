# 采集结束后清理残留标签页 PLAN

Status: **PLAN v1.0 — FROZEN**（2026-08-08 由用户确认冻结）
上游：BUG-01（`docs/bugs/BUG-01-采集后浏览器窗口不关闭.md`，已稳定复现、根因已定位）
分支：`fix/close-browser-after-collect`
基线：`master` @ 6fc91bd + 本分支文档提交

> 文件位置说明：本项目原有 `计划/` 与 `docs/plans/` 两处历史计划目录。本轮按导航手册
> 规范落到 `docs/plan.md` + `docs/task.md`，不改动历史目录。

## 1. 目标与非目标

**目标**

1. 一轮抖音采集结束后，自动关闭该轮在采集专用 Chrome 中新开的标签页，使标签页数
   不随采集轮次增长。
2. 清理动作不得影响采集结果，也不得掩盖采集本身的失败。

**非目标（本轮明确不碰）**

- 不关闭浏览器进程本身（用户已拍板选口径 A，见第 3 章）。
- 不动抖音登录态、`chrome-profile` 目录、登录检查逻辑。
- 不改 `deploy/cloud-pc/collect-douyin-and-push.ps1` 及任何 PowerShell 采集脚本。
- 不改计划任务 `DouyinCollectAndPush` 的配置。
- 不碰 `data/archive.json` 或任何历史数据（本功能与历史清理逻辑零交集）。
- 不改 MediaCrawler 外部项目（`C:\AI-news-reader\MediaCrawler-local-test`）。
- 不处理微信通道（`we_mp_rss_jsonl` 是 sidecar 抓取，不经过本 runner，与本问题无关）。

**关于小红书（PLAN-01 修正）**：`main()` 是抖音与小红书共用的入口，清理逻辑接在其中
后会**天然对小红书同样生效**——这是正确的，两者共用同一套专用浏览器机制，泄漏成因相同。
故不将其列为非目标。但本轮**只对抖音做人工验收**（小红书采集触发路径不同，另行观察），
若小红书出现行为变化，触发第 7 章暂停条件 3。

## 2. 现状调查

每条结论均来自实际读取的文件或 2026-08-08 的 NUC 实测，出处随附。

1. **采集专用 Chrome 由 runner 启动，端口 9333，独立 profile。**
   `scripts/run_mediacrawler_douyin.py:244` `launch_dedicated_browser()` 以
   `subprocess.Popen` + `DETACHED_PROCESS` 启动，参数见 `:217` `dedicated_browser_args()`
   （含 `--remote-debugging-port`、`--user-data-dir`、`--remote-debugging-address=127.0.0.1`）。

2. **浏览器是复用的，不是每轮新建。**
   `scripts/run_mediacrawler_douyin.py:499` `ensure_dedicated_browser()`：
   `is_port_open(start_port)` 为真则校验后直接 `return start_port`，只有端口未监听才
   `launch_dedicated_browser()`（`:506`）。NUC 实测两轮全程只有一个浏览器，与此一致。

3. **整条链路没有任何浏览器/标签页收尾代码。**
   - Python 侧：`main()`（`:1003-1099`）从头到尾无关闭动作。
   - PowerShell 侧：`deploy/cloud-pc/collect-douyin-and-push.ps1` 全文涉及浏览器的
     只有 `:33`（声明 `-BrowserOffscreen`）和 `:360`（据此追加 `--offscreen`）。
   - 计划任务侧：`DouyinCollectAndPush` 的两个 Action 只调用上述 PowerShell 脚本。

4. **本仓库现有的两处 CDP 代码只读不写，且不是可复用的清理点。**
   `set_dedicated_browser_window_mode()`（`:345`）读 `context.pages[0]` 调窗口位置；
   `douyin_login_state()`（`:379`）遍历 `context.pages` 查登录态。两者结尾的
   `await browser.close()`（`:372`、`:403`）在 `connect_over_cdp` 模式下**只断开
   playwright 连接**，不关浏览器也不关标签页。

5. **新标签页由外部项目 MediaCrawler 产生。**
   `run_mediacrawler()`（`:911`）以子进程方式启动 `<CrawlerRoot>/main.py`，后者通过
   CDP 连上 9333 开页面采集。该项目不在本仓库，**清理只能由本仓库在采集结束后补做**。

6. **CDP 请求沿用本文件既有的 urllib 模式，无需新增依赖。**（PLAN-02 修正，2026-08-08 施工时发现）

   原计划写「复用 `scripts/radar/server/cdp.py:36` 的 `cdp_json`」。实测
   `scripts/run_mediacrawler_douyin.py` **完全不导入 `scripts.radar` 包**，
   它自己用 `urllib.request` 直连 CDP —— 见 `:195` `cdp_ready()`。该脚本由计划任务以
   `python scripts/run_mediacrawler_douyin.py` 直接运行，`sys.path` 未必包含仓库根，
   强行引入包依赖有 ImportError 风险。

   **故改为沿用本文件既有写法**：新增内部 `cdp_request_text(port, path)`，
   `list_cdp_page_targets` 在其上做 JSON 解析，`close_cdp_page_targets` 直接调用。
   注意 `/json/close/<id>` 返回纯文本（实测 body 为 `Target is closing`），**不是 JSON**，
   不能统一走 JSON 解析。

   方向、文件白名单、验收标准与「不新增第三方依赖」均不受影响，故不重新冻结计划。

7. **实测数据（2026-08-08，NUC `C:\AI-news-reader\ai-news-radar-run`）**
   两轮采集 tabs 依次为 1→2→3，采集结束后不回落；稳态内存 0.6~0.8 GB，峰值约 2.1 GB。
   完整采样见 BUG-01 第 1 项。

8. **测试基线（改动前，本机 `E:\AI-news-reader\ai-news-radar-run`）**
   - 全量：`729 passed, 0 failed`，耗时 714.95 秒。
   - 本模块：`tests/test_mediacrawler_runner.py` `23 passed`，耗时 0.13 秒。
   - 测试风格：`unittest` + `unittest.mock`，以导入纯函数直接断言为主。

9. **关键能力已做最小验证（2026-08-08 02:2x，NUC 实测，非推测）**
   对采集浏览器真实执行了一次关标签页：

   ```
   BEFORE tabs = 3   （三个 id 各不相同，url 全部相同：https://www.douyin.com/jingxuan）
   GET /json/close/9B0BBA02...  →  HTTP 200, body "Target is closing"
   AFTER  tabs = 2
   chrome.exe 进程数 = 11（浏览器未退出）
   ```

   证实三点：`/json/close/<targetId>` 端点可用且为 GET；关闭标签页**不会**导致
   浏览器进程退出（不会滑向已放弃的口径 B）；**URL 相同而 id 不同**，坐实第 3.4 节
   约束 4「必须按 id 差集判断」。

**已知限制**：`--browser-only` 模式（`:1042`）用于人工扫码恢复登录，此时浏览器与页面
必须保留给人操作，不能清理。

## 3. 方案

### 3.1 关键决策：收尾口径选 A（用户 2026-08-08 拍板）

只关闭本轮新增的标签页，保留浏览器进程与原有页面。

**放弃的选项及理由：**

| 放弃项 | 内容 | 放弃理由 |
|---|---|---|
| B | 采集结束后关闭整个浏览器进程 | 内存虽归零，但强杀时 `chrome-profile` 可能来不及落盘，抖音登录态有丢失风险（丢了要人工扫码恢复）；且与 `ensure_dedicated_browser()` 的复用设计相悖，每轮多 20~30 秒重启开销 |
| C | A + 把保留页面导航到空白页 | 内存更低，但 `douyin_login_state()`（`:379`）优先读 douyin 页面的 `localStorage`，无 douyin 页面时退化为 cookie 判断，登录态误判风险上升 |
| D | 在 PowerShell 脚本里 `Stop-Process chrome` | 无法区分采集浏览器与用户自己的 Chrome，会误杀；且违反「按 profile 隔离」的现有设计 |
| E | 改 MediaCrawler 让它自己关页面 | 外部项目，不在本仓库白名单内，升级即丢失改动 |

### 3.2 模块划分

在 `scripts/run_mediacrawler_douyin.py` 内新增三个函数，职责单一、便于单测：

| 函数 | 职责 | 可测性 |
|---|---|---|
| `list_cdp_page_targets(port)` | 调 `/json/list`，过滤 `type == "page"`，返回 `[{"id":…, "url":…}]` | mock `cdp_json` |
| `select_leaked_page_targets(before_ids, after_targets, min_keep=1)` | **纯函数**：算出该关哪些 id | 直接断言，无 I/O |
| `close_cdp_page_targets(port, target_ids)` | 逐个调 `/json/close/<id>`，返回 `{"closed": n, "failed": n}` | mock `cdp_json` |

核心判断收敛在纯函数 `select_leaked_page_targets` 里，与项目现有测试风格一致。

### 3.3 数据流

```
ensure_dedicated_browser()  →  拿到 cdp_port
        ↓
before_ids = list_cdp_page_targets(port) 的 id 集合      ← 采集前快照
        ↓
run_mediacrawler(...)  （MediaCrawler 子进程，期间新开标签页）
        ↓
after = list_cdp_page_targets(port)                      ← 采集后快照
leaked = select_leaked_page_targets(before_ids, after)
close_cdp_page_targets(port, leaked)                     ← 只关新增的
```

### 3.4 关键约束（实现必须满足）

1. **至少保留一个标签页。** Chrome 关光全部标签页会退出进程，那就变成口径 B 了。
   `select_leaked_page_targets` 的 `min_keep=1` 负责兜底：若关完不足 1 个，从待关清单
   末尾回退保留。
2. **`--browser-only` 模式不清理**（`:1042` 提前 `return 0`，清理逻辑必须在其之后接入，
   或显式跳过）。该模式是给人扫码用的。
3. **清理失败不得掩盖采集结果。** 整个清理块用 `try/except Exception` 包住，失败只往
   stderr 打印告警，不改变 `main()` 的返回码，也不覆盖已有异常。
4. **只按快照差集判断，不按 URL 猜。** 三个标签页 URL 完全相同（都是
   `douyin.com/jingxuan`），按 URL 去重会误关采集前就存在的页面。
5. **清理发生在采集之后**，无论成功或失败都执行（放在采集调用的 `finally` 语义位置），
   失败轮次同样会留下泄漏标签页。

6. **清理必须落在既有采集锁之内。** `main()` 用 `with collection_lock_context(args, run_id):`
   （`scripts/run_mediacrawler_douyin.py:1029`）串行化整轮采集。快照与清理都必须在这个
   `with` 块内，否则另一轮采集可能在两次快照之间开新标签页，导致误关正在使用的页面。
   本改动不新增任何锁。

## 4. 界面与流程

无。本功能全部发生在 NUC 后台采集进程内，无页面、无按钮、无用户交互入口。
浏览器窗口在 `--offscreen` 模式下位于屏幕外，用户只在任务栏 / Alt+Tab 感知其存在。

## 5. 文件白名单

**允许改（精确路径，仅此两个）**

- `scripts/run_mediacrawler_douyin.py`
- `tests/test_mediacrawler_runner.py`

**禁止碰**

- `scripts/radar/server/cdp.py`（复用其 `cdp_json`，不修改）
- `deploy/cloud-pc/collect-douyin-and-push.ps1`
- `deploy/local/collect-wechat-and-push.ps1`
- `scripts/windows/douyin-collect-now.cmd`
- `data/**`（尤其 `data/archive.json`）
- `config/**`
- `assets/js/**`、`index.html`
- 计划任务 `DouyinCollectAndPush` 的配置

## 6. 验证方式

### 6.1 自测命令（均已于 2026-08-08 当场跑通）

| 命令 | 预期 |
|---|---|
| `.venv\Scripts\python.exe -m pytest tests/test_mediacrawler_runner.py -q` | 改动前 `23 passed`（0.13 秒）；a 卡后新增用例变红；b 卡后全绿 |
| `.venv\Scripts\python.exe -m pytest -q` | 改动前 `729 passed`（约 12 分钟）；改动后 = 729 + 本轮新增，且原 729 条全部仍通过 |
| `.venv\Scripts\python.exe -m py_compile scripts/run_mediacrawler_douyin.py` | 无输出即通过 |

本轮不改 `assets/js/**`，按项目规则**不需要**跑 `npm run test:e2e`。

### 6.2 人工验收（在 NUC 上做，不含任何命令）

1. 打开 NUC 桌面，在任务栏找到采集专用 Chrome 的图标，点开它，数一下有几个标签页，记下这个数字。
2. 双击 `C:\AI-news-reader\ai-news-radar-run\scripts\windows\douyin-collect-now.cmd`，
   等窗口提示采集已触发。
3. 等约 6 分钟（实测一轮约 5 分钟），期间任务栏的 Chrome 图标会短暂多出标签页。
4. 再点开任务栏那个 Chrome，重新数标签页。
   **应该看到：数字和第 1 步记下的一样，没有增加。**
5. 重复第 2~4 步再做一轮。**应该看到：数字仍然不变。**
6. 打开雷达页面，确认这两轮采集到的抖音内容正常出现（证明清理没有影响采集结果）。

### 6.3 异常路径验收

7. 断开 NUC 网络或让采集失败一次，重复第 4 步。
   **应该看到：标签页数同样没有增加**（失败轮次也要清理）。

## 7. 回滚与暂停条件

**回滚**

- 代码回滚：`git restore scripts/run_mediacrawler_douyin.py tests/test_mediacrawler_runner.py`
  （未提交时）；已提交则 `git revert <commit>`。本轮改动只涉及两个文件，无数据迁移、
  无配置变更、无外部副作用，回滚后行为与今日基线完全一致。
- NUC 侧回滚：NUC 通过 `RadarAutoFF` 跟随 `origin/master`；主线 revert 后 NUC 自动跟随，
  无需手工覆盖 `data/**`（见 CLAUDE.md「同步线上的 git 编排禁区」第 4 条）。

**暂停条件（出现任一必须停下来问人）**

1. 发现需要修改白名单之外的文件——尤其是 `deploy/**`、`data/**` 或 MediaCrawler 外部项目。
2. 实现过程中发现必须改动登录态检查逻辑（`douyin_login_state` / `check_douyin_login_state`）。
3. 小红书（xhs）通道因本改动出现行为变化。
4. 全量测试出现基线之外的失败，且原因不能在 10 分钟内说清。
5. 人工验收时发现采集结果缺失或登录态失效。
6. 发现关闭标签页会导致浏览器进程退出（说明 `min_keep` 兜底失效，等于滑向口径 B）。

# BUG-03: GitHub Actions 采集卡满 15 分钟，网站快照停更三天

状态：**已修复并由用户验收通过**（2026-08-26）
修复提交：`3a5ae6c`｜合并：`05a39f3`（PR #26）

## 验收结论（2026-08-26）

| 层 | 验收项 | 结果 |
|---|---|---|
| 云端任务 | Update AI News Snapshot 不再 timeout | ✅ run `32917647783` 成功，**1 分 29 秒**（此前连续 cancelled / 15m） |
| 采集步骤 | Update data 能跑完并提交 | ✅ 67 秒写完 `data/**`；`[timing] collect=18.7s enrich=47.2s` |
| B 站 | 预算内采完 | ✅ `ok=True`、51 条、4.2 秒、`deferred=0` |
| 抖音 | 吃进 NUC 已有 JSONL | ✅ 52 条 |
| 站点 | 用户能看到最新 | ✅ `generated_at=2026-08-26T01:05:45Z`；用户确认「能看见最新的了」 |
| 测试 | 本轮新增预算测试 | ✅ `test_budget_skips_remaining_accounts_when_requests_hang`、`test_collect_session_has_no_automatic_retries` 通过。全量 `pytest -q` **723 passed**；另 3 条 `Get-FileHash` 失败为本机 PowerShell 环境问题，与本 diff 无关 |

## 现象

公开站点快照停在 `2026-08-22T19:27:39Z`（北京时间 8 月 23 日凌晨）。用户看到「上一次更新还在 8 月 23 号」。

GitHub Actions `Update AI News Snapshot` 从 **2026-08-22T19:36Z** 起每次在 **Update data** 卡满 15 分钟被杀掉，`conclusion=cancelled`，`Commit and push` 走不到。脚本本身 8 月 22 日之后没有采集逻辑改动。

## 根因（第一性原理）

- 任务硬上限：`.github/workflows/update-news.yml` `timeout-minutes: 15`。
- `create_session()` 对 429/5xx **自动重试 3 次**，一次 20 秒超时会被放大到 80 秒以上。
- B 站线上 6 个号、每号最多 8 页，**没有像 GitHub 源那样的总预算**。
- 最坏：`6 × 8 × 4 × 20s ≈ 64 分钟`。一个号卡住，整轮快照无法提交。
- 采集过程原先几乎不打进度，超时日志看起来像「什么都没干」。

不需要改架构或 schema。GitHub 源已经用 `create_github_session`（`Retry total=0`）和 `GITHUB_REPO_SUBSCRIPTION_BUDGET_SECONDS=180` 解决过同类问题。

## 修法

1. 采集会话与 GitHub 会话对齐：禁止自动重试。
2. B 站总预算默认 90 秒（`BILIBILI_DYNAMIC_BUDGET_SECONDS`）；超时跳过剩余号，已采到的照常发布。
3. 标题翻译最多 45 秒，避免 enrich 再把 15 分钟吃光。
4. `[collect]` 进度日志（`flush=True`），下次再卡能看见卡在哪一步。

## 同期排查、但不是本 bug 根因

NUC 当时连在 WiFi「多乐之家-5G」、地址 `192.168.1.3`；开发机在网线 `192.168.3.47`。UU 远程能进 NUC，局域网旧 SSH `192.168.3.66` 不通。抖音桥接 8 月 25 日 20:44 仍有成功推送。网站停更是云端任务卡死，不是 NUC 关机。

## 改这块前必读

`CLAUDE.md`「GitHub Actions 采集超时的禁区」。

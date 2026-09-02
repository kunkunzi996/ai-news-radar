# Claude Code Notes

Before changing this project, read:

- `skills/ai-news-radar/SKILL.md`
- `docs/SOURCE_COVERAGE.md`
- `README.md`

Do not commit private OPML files, API keys, cookies, browser exports, or `.env`
values. Keep the public repo usable without secrets.

Project iron rules:

- For every bug fix, start from first principles before changing code. Write down the bottom-level fact/root cause, whether an architecture/schema/API change is truly required, and the smallest reversible fix that solves the root cause.
- For acceptance or testing of any browser-visible flow, local dashboard, or UI interaction, use a browser tool for real validation before reporting back. Do not stop at unit tests, static checks, or asking the user to click first. If browser-tool validation is impossible, state the blocker and what remains unverified.
- 改动 `scripts/**` 后，同一轮必须运行项目已有的 Python 相关检查，并记录完整命令与结果；改动 `assets/js/**` 后，同一轮必须运行 `npm run test:e2e`，记录通过数、失败数及环境阻塞原因；同时改动两类目录时，两类检查都必须运行。不新增测试框架、CI 配置或流程工具。

## 产品方向

个人订阅聚合器：默认是用户自己的订阅流（「我的订阅」+ 各平台 tab），不是 AI 精选。
微信公众号历史仍可看，不再采集。`AI_RELEVANCE_THRESHOLD` 缺省 `0.65`，生产为 `0`。
不要为了「填满 AI 主榜」加公开新闻源。加源优先官方 RSS/Atom/OPML。

YouTube 订阅成员、已阅计数键、脚本 `?v=` / 工作台 `wb=` 见 `AGENTS.md`。

## 禁区索引

事故经过在 `docs/rules/` 与 `docs/bugs/`。这里只留硬规则和别处没有的操作事实。

### 清理历史条目的禁区

能删 `data/archive.json` 的默认只有「保存/同步信源配置」。窄例外见
`docs/rules/archive-cleanup-exceptions.md`。

1. 采集范围 `active_source_ids` 绝不可用来过滤归档。
2. 判断「源被删了」必须 previous 与 current 都排除 `enabled: false`。
3. 往 `PURGE_TRACKED_SITE_IDS` 加 site_id 前，该 type 必须先能被 `source_identity_names()` 认出。
4. 容器型记录（`type: opmlrss` 订阅包、逗号串 B 站 target）不是订阅对象。
5. `data/pending-purge.json` 补做前必须用当前配置复核；源已加回则划掉、拒绝清理。

回滚只用各自 `scripts/restore_*.py` 按 ID 回插，禁止用旧 `archive.json` 整文件覆盖。

### 同步线上（sync_online_source_config）的 git 编排禁区

`stash 隔离 → rebase+push → finally 覆盖恢复`。`merge_sync` 逐条契约见
`docs/rules/sync-online-merge-contract.md`。

1. 恢复只能 `git restore --source=stash@{0} -- .`，不要 `git checkout stash@{0} -- .`。
2. 不可改用 `pull --rebase --autostash`。
3. stash 不带 `-u`；只碰本次压入的 `stash@{0}`。
4. NUC `RadarAutoFF` 只跑 Git 跟踪的 `scripts/windows/auto-ff.sh`；成败以 `logs/auto-ff.log` 的结构化 `reason` 为准。失败保留工作区，禁止 reset/强推/覆盖 `data/**`。

`merge_sync` 必须先推送合并提交再 CAS 移动本机 `master`；永远不得 purge 或改写归档历史。

### 本机 git 仓库维护禁区

1. 禁止随手 `git gc --prune=now` / `git prune`。误删的 GitHub Release 历史完整副本挂在不可达提交 `d85b916^`；找回用 `git show d85b916^:data/archive.json`。
2. `git stash list` 空 ≠ stash 丢了。先查 `refs/stash` / packed-refs。重建 reflog 时 `git update-ref --create-reflog` 与 `git stash store` 在新旧 ref 相同会报成功却不写；只能手写该文件，字段间单空格、message 前 tab、行尾 LF。
3. `fetch` 成功但 remote-tracking 不落盘：先查 `remote.origin.fetch` 是否被浅克隆钉成只认 `master`。历史文档「git 2.54 吞 refs」作废。
4. 本仓库仍可能是浅克隆；对比很老的分支结果可疑时再 `git fetch --unshallow`。

### 给源状态加字段的必查清单

线上少字段而单测全绿，见 `docs/bugs/BUG-02-抖音采集回执不完整导致整轮作废.md`。

1. 抖音 fetcher 两条路都要改：`maybe_fetch_mediacrawler_douyin`（环境变量 JSONL，线上 Actions 走这条）与 `fetch_mediacrawler_douyin_subscriptions`（订阅驱动）。
2. `cli.py` 会逐字段重构 statuses，新键必须在主管线显式透传（抖音收敛点 `mediacrawler_douyin_status_entry()`）。
3. 先复用已有 `site.partial`「部分完成」，别新造语义。
4. 排查先分清「键不存在」还是「值为 False」。

### GitHub Actions 采集超时的禁区

job 上限 15 分钟。见 `docs/bugs/BUG-03-GitHub采集卡满15分钟整轮停更.md`。

1. 不要把采集会话 429/5xx 自动重试加回去。
2. 会打外部 HTTP 的通道要有墙钟预算，不要只给单次 `timeout=`。
3. `cancelled` 且约 15m20s、卡在 Update data，先当 timeout，不是人手取消。

### 新增数据源必查清单

1. `ONLINE_ALLOWED_TYPES` 漏了会让整份线上配置读取失败并清空面板。
2. `RawItem.site_id` 必须等于启用源 id，否则会被白名单静默丢弃。
3. 前端 `SUBSCRIPTION_SITE_IDS` / `HIDDEN_PLATFORM_IDS` 要同步。
4. 改 `assets/js/**` 必须 bump `index.html` 的 `?v=`。
5. 新建 `.ps1` 用 UTF-8 带 BOM；新建 `.cmd`/`.bat` 用 CRLF，含中文时用 GBK，且必须用 cmd.exe 验收。

### 采集窗挪位的禁区

专用 Chrome 挪到屏幕外是尽力而为。见 PR #46。

1. 不许把精确像素失败（`browser_window_bounds_not_applied` / 窗口仍在屏幕内）重新改成整轮 `failed`。
2. CDP 端口健康且确认是本采集 profile 后，必须继续采集。
3. 计划任务 `LastTaskResult=0` 不等于采集成功；以 `C:\AI-news-reader\douyin-collect-status.json` 的 `state` 为准。

### 采集浏览器收尾的禁区

只关本轮新增标签页。见 `docs/bugs/BUG-01-采集后浏览器窗口不关闭.md`。

1. 不许改成关整个浏览器进程。
2. 按标签页 id 差集，不能按 URL。
3. 只关 `type == "page"`。
4. 始终保留至少一个页面。
5. `--browser-only` 不清理。
6. 清理失败只告警，不改变采集返回码；必须在 `collection_lock_context` 内。

### 本机维护按钮的派发禁区

常驻按钮必须走开头的无条件字典派发（`fixed_start_actions` / `scope_free_start_actions`），不能依赖 `find_maintenance_action`。
`fixed_start_actions` 无条件传 `collection_scope`。
微信启动返回 `wechat_collection_retired`，不要接回可点按钮。
前端新按钮必须在 `boot.js` 绑定点击。

### 远程管理后台（token 公开模式）的禁区

改公开模式前必读 `docs/rules/remote-admin-public-mode.md`。
静态白名单只许收缩；绑定非回环且无令牌必须拒绝启动。

### 新增桥接类信源自动采集的禁区

改前必读 `docs/rules/bridge-auto-collect-contract.md`。

1. 必须触发计划任务 `DouyinCollectAndPush`，不能自己起采集进程；任务只留抖音 action。
2. 派发只能在同步推送成功之后。
3. 若将来恢复微信：只能全量重采，禁止单号覆盖 JSONL。
4. 只在「新增」时触发；本模块不碰 `data/archive.json`。

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

## 产品方向（2026-07-11 调整）

本项目已从「AI 新闻精选雷达」转向**个人订阅聚合器**：核心价值是把用户自己的订阅源
（B站、抖音、小红书、YouTube、RSS、GitHub Release）聚合到一个页面，
按时间流查看。微信公众号历史仍可看，但不再采集。**内容是否与 AI 相关不再是筛选标准。**

- 默认层：用户订阅源的统一信息流（「我的订阅」+ 各平台 tab）。
- 高级层：自定义源配置（OPML / 线上信源面板）与源健康详情。

AI 相关性打分算法（`scripts/ai_relevance.py`）**保留但不再是默认筛选器**：阈值由环境
变量 `AI_RELEVANCE_THRESHOLD` 控制（缺省 0.65），线上 Actions 变量当前设为 `0`，即
不过滤、主榜等于全量。不要再以「填满 AI 主榜」为优化目标，也不要主动建议添加 AI
新闻源来提升 AI 相关内容占比——除非用户明确要求。

When adding sources, prefer official RSS/Atom feeds or OPML first. Add custom
fetchers only for stable, public, high-signal sources.

## 清理历史条目的禁区

除下述“微信公众号 schema 2 清理窄例外”外，能删 `data/archive.json` 历史条目的只有
「保存/同步信源配置」这一条路径。下面每一条都
真删过数据（2026-07-12 丢 9 条 GitHub Release；2026-07-13 差点再丢 174 条和 78 条）：

1. **「本轮采集哪些源」≠「历史里允许留哪些源」。** 采集范围（`active_source_ids`）
   **绝不可**用来过滤归档。曾这么干过，结果线上与本机两份配置互删对方独有的源。
   采集管线只负责抓新的、去重、按 `--archive-days` 裁过期，**不负责删源**。

2. **判断「源被删了」必须 `previous` 与 `current` 两边都排除 `enabled: false`。**
   `enabled: false` 背着两种含义——「我取消订阅了」和「这通道本机不跑」。只排除 current
   会让长期处于 off 的源被误判成刚取消订阅（实测：原样保存一次就清掉抖音、小红书历史）。

3. **往 `PURGE_TRACKED_SITE_IDS` 加 site_id 前，先确认该 type 能被 `source_identity_names()`
   认出身份。** `SOURCE_CONFIG_TYPE_SITE_IDS` 里没有的 type 认出的是**空集** → 存活名单为空
   → 该通道**全部**条目变孤儿。先修身份映射，再加白名单，**顺序不可颠倒**（实测：反了会清光
   78 条 RSS）。

4. **容器型记录不是订阅对象**：`type: opmlrss` 的「订阅包」、`target` 是逗号串的 B站记录，
   绝不可进订阅身份表或 `ENUMERABLE_SUBSCRIPTION_SITE_IDS`。

5. 延后清理台账 `data/pending-purge.json`（已 gitignore）**补做前必须用当前配置复核**：
   源若被重新加回，只从台账划掉、拒绝清理。

### 两个窄例外（详细契约在 `docs/rules/archive-cleanup-exceptions.md`）

只有两条通道允许在上述路径之外删历史，各自有独立的逐条契约，**改到它们之前必读那份文档**：

- **微信 `we_mp_rss_jsonl`**：仅当 sidecar Feed 被 hard delete（ID 不再出现在 schema 2 快照
  `known` 中）才可清理；`status=0` 必须停采但保留全部历史。身份只认稳定 `we_mp_feed_id`。
  `WE_MP_ORPHAN_CLEANUP_MODE` 默认且非法值一律按 `off`。
- **GitHub 星标托管**：仅 `managed_by=github_stars` 且 `managed_state=auto_disabled` 可成为候选；
  身份只认规范十进制 `managed_repo_id`；须在两个不同 `GITHUB_RUN_ID` 的非空快照中连续缺失。
  `STAR_SUBSCRIPTION_CLEANUP_MODE` 默认 `off`。

两者共同的硬要求：任何校验不成立都必须 fail-safe 一条不删；回滚只能用各自的
`scripts/restore_*.py` 按 ID 精确回插，**禁止用旧 `archive.json` 整文件覆盖当前归档**。
改微信这块还必须真在浏览器里走一遍「删除 / 停用 / 改名 / 原样保存」四种操作，
逐一核对 `data/archive.json` 的条数与 site_id 分布——光跑单测不算数。

## 同步线上（sync_online_source_config）的 git 编排禁区

该函数用「stash 隔离 → rebase+push → finally 覆盖恢复」处理工作区脏 data（2026-07-14 上线）。改动时：

1. 恢复只能用 `git restore --source=stash@{0} -- .`（只回写工作区）。**换成 `git checkout
   stash@{0} -- .` 会把文件写进暂存区**，下一次同步被开头的 `unrelated_files_already_staged`
   闸拦住（真踩过：单测全绿也没拦住，必须测「连续两次同步」和 staged/unstaged 状态）。
2. 不可改用 `pull --rebase --autostash`：线上 Actions 每轮提交 `data/**`，autostash pop 必
   三方冲突，且此时 rebase 已完成、abort 无效。
3. stash 不带 `-u`；函数只碰自己压入的 `stash@{0}`，用户已有的遗留 stash 会自动回位、不可误 drop。
4. NUC 的 `RadarAutoFF` 只允许执行 Git 跟踪的 `scripts/windows/auto-ff.sh`；成功或失败必须以
   `logs/auto-ff.log` 的结构化事件和 `reason` 为准。失败时保留当前工作区，禁止 reset、强推或手工覆盖
   `data/**` 来“修复”同步。

### merge_sync（详细契约在 `docs/rules/sync-online-merge-contract.md`）

云端信源文件也变更时走 `operation_kind=merge_sync`，是与上述普通同步并列的另一个事务，
有 7 条独立契约，**改到它之前必读那份文档**。三条最容易踩的：合并结果的 GitHub 星标受管投影
必须与云端完全相等；必须先推送合并提交、成功后才能以 CAS 移动本机 `master`；
该路径**永远不得调用 purge 或改写 `data/archive.json` 历史**。

## 本机 git 仓库维护禁区

1. **本仓库禁止随手跑 `git gc --prune=now` / `git prune`。** 被误删的 70 条
   `github_foundation_sunshine_releases` 历史唯一的完整副本挂在**不可达提交** `d85b916^` 上
   （`d85b916` =「数据：清理已退订信源 AlkaidLab/foundation-sunshine 的 14 条历史条目」），
   gc 会把它连同其它不可达对象一起清掉。要找回用
   `git show d85b916^:data/archive.json`，不要去翻 stash（现存 stash 里 0 条）。
2. **`git stash list` 显示为空 ≠ stash 丢了。** `stash list` 读的是 reflog
   （`.git/logs/refs/stash`），不是 `refs/stash` 本身。先查
   `grep -i stash .git/packed-refs` 确认本体在不在，再谈丢没丢（2026-08-01 真踩过：
   reflog 文件丢失，list 空，但数据完好）。重建 reflog 时注意 `git update-ref --create-reflog`
   与 `git stash store` 在新旧 ref 值相同时**会报成功却什么都不写**（被判定为空操作），
   只能手写该文件，字段间单空格、message 前是 tab、行尾 LF。
3. **遇到「`fetch` 不报错但 remote-tracking ref 不落盘」，第一件事查
   `git config --get-all remote.origin.fetch`**，别先怀疑 git 版本、杀软或文件系统。
   2026-08-01 查明真因是浅克隆隐含 `--single-branch` 留下的
   `+refs/heads/master:refs/remotes/origin/master`（只认 master）。修复为改成
   `+refs/heads/*:refs/remotes/origin/*` 后重新 fetch。**历史文档里「git 2.54.0.windows.1
   吞 refs」「提交后手工钉 ref」的表述全部作废。**
4. 本仓库仍是**浅克隆**（`.git/shallow` 存在）。当前分支点都在浅克隆边界内，`--merged`
   判断可信；若将来对比很老的分支、结果可疑，再跑 `git fetch --unshallow`。

## 给源状态加字段的必查清单（2026-08-08 BUG-02 真实踩过两次）

想让某个源的新信息出现在看板上时，下面三处漏一处，线上就一个字段都看不到，
而**单元测试会全绿**——这两个坑都是在真机验收阶段才暴露的：

1. **抖音 fetcher 有两条路，必须都改。** `scripts/radar/fetchers/mediacrawler.py` 里
   `maybe_fetch_mediacrawler_douyin`（环境变量 `MEDIACRAWLER_DOUYIN_JSONL` 驱动，
   **线上 Actions 实际走的就是这条**）与 `fetch_mediacrawler_douyin_subscriptions`
   （订阅驱动）各自构造 status。只改订阅分支，测试照样全绿，线上拿不到任何新字段。
   判别线上走哪条：看 `data/source-status.json` 里该源有没有 `subscriptions` 字段。

2. **`scripts/radar/cli.py` 逐字段重构 statuses 条目，fetcher 加的字段默认被丢弃。**
   抖音的收敛点是 `mediacrawler_douyin_status_entry()`；其它源仍是内联字典。
   fetcher 里 `status["x"] = ...` 之后，**必须在主管线对应位置显式透传**，否则
   `source-status.json` 里那个键**根本不存在**（不是值为 False——这个区别是排查的关键线索）。

3. **前端 `site.partial` 这套「部分完成」展示早就存在**（`assets/js/render-panels.js`、
   `render-meta.js`、`subscriptions.js`），GitHub 源的 `partial` + 三态计数是既有范例。
   加新的健康展示前先确认能否复用它，别新造字段语义，也别急着改前端。

**排查口诀**：线上少了字段，先看「键不存在」还是「值为 False」。
键不存在 = 上游根本没填或被主管线丢了；值为 False = 链路通了但数据本身如此。

## GitHub Actions 采集超时的禁区（2026-08-26 BUG-03）

`update-news.yml` 的 job 上限是 **15 分钟**。采集会话禁止 429/5xx 自动重试（与 `create_github_session` 同一原则）；B 站有总预算 `BILIBILI_DYNAMIC_BUDGET_SECONDS`（默认 90 秒），超时跳过剩余号，已采到的照常发布。

1. **不要把自动重试加回去。** 一次 20 秒超时 × 3 次重试 × 多号多页会超过 15 分钟，整轮快照提交不出去（2026-08-22 起连续三天 `cancelled`）。
2. **给会打外部 HTTP 的通道留墙钟预算**，不要只给单次 `timeout=`。GitHub 源 180 秒、B 站 90 秒是现成范例。
3. **排查先看是不是 timeout。** `gh run list` 里 `cancelled` 且时长约 15m20s、卡在 Update data，不是人手取消。现场日志看 `[collect]` 最后一条停在哪。

过程与验收见 `docs/bugs/BUG-03-GitHub采集卡满15分钟整轮停更.md`。

## 新增数据源必查清单

新增一种数据源 `type` 时，除了 fetcher 本身，以下几处漏一个都会出问题（均已真实踩过）：

1. `scripts/radar/server/online_sources.py` 的 `ONLINE_ALLOWED_TYPES` 白名单 —— 漏了会导致
   **整份线上配置读取失败**，进而让面板把配置全量覆盖清空（2026-07-11 事故）。
2. `scripts/radar/cli.py` 的 `active_source_ids` 过滤 —— RawItem 的 `site_id` 必须等于
   `config/online-sources.json` 里启用的源 id，否则条目会被白名单静默丢弃。前端归一显示
   靠 `site_name` 同名即可，不要复用别的通道的 site_id。
3. 前端 `assets/js/dom.js` 的 `SUBSCRIPTION_SITE_IDS`（新 site_id 要加进去）与
   `HIDDEN_PLATFORM_IDS`（别被历史遗留的平台隐藏挡住）。
4. 改了 `assets/js/*.js` 必须 bump `index.html` 里对应的 `?v=` 缓存版本号，否则浏览器复用旧脚本。
5. 新建 `.ps1` 必须存为 UTF-8 **带 BOM**，否则 PowerShell 5.1 按 GBK 解码，中文字面量全乱码。
6. 新建 `.cmd` / `.bat` 必须存为 **CRLF 换行**（且文件名/内容含中文时存 GBK/936），否则 cmd.exe
   把 `cd /d` 之类拆坏、双击瞬间闪退（2026-07-15 双击启动器真踩过）。**注意：bash 环境跑 .cmd
   不在乎换行符，会给出「通过」假象——验收 .cmd 必须用 cmd.exe 真实口径跑**，那才是双击的同一条路径。

## 采集浏览器收尾的禁区

`main()` 在 `finally` 里调 `close_leaked_pages`，只关**本轮新增**的标签页
（`scripts/run_mediacrawler_douyin.py`，BUG-01，2026-08-08 验收）。改这块时：

1. **不许改成关整个浏览器进程。** 已评估并放弃：强杀时 `chrome-profile` 可能来不及落盘，
   抖音登录态丢了要人工扫码；且与 `ensure_dedicated_browser` 的复用设计相悖。
2. **只能按标签页 id 差集判断，不能按 URL。** 实测多个标签页 URL 完全相同
   （全是 `douyin.com/jingxuan`），按 URL 判断会误关采集前就存在的页面。
3. **只关 `type == "page"`。** 同一浏览器还有 iframe / browser_ui / service_worker / worker
   共 7 个 CDP target，误关会影响采集。
4. **始终保留至少一个页面**（`min_keep`）——关光会让 Chrome 退出，等于绕回第 1 条。
5. **`--browser-only` 模式不清理**，那是留给人扫码恢复登录的。
6. 清理失败只告警，**绝不改变采集本身的成败与返回码**；快照与清理都必须在
   `collection_lock_context` 之内，否则并发轮次会误关正在用的页面。

## 本机维护按钮的派发禁区

`perform_maintenance_action`（`scripts/radar/server/refresh.py`）有两条派发路，加新按钮前先想清楚走哪条（2026-07-15 微信采集按钮真踩过）：

1. **常驻可见的按钮**（`source-config-tools` 工具条那排，现如「重启本地服务」；「启动微信采集」已下线）
   **必须**走函数开头的无条件字典派发（`fixed_start_actions` / `scope_free_start_actions`），
   **不能**依赖 `find_maintenance_action`。后者只在动态生成的「维护项列表」里查，而那个列表
   只装「检测到出问题的渠道」——系统健康时列表为空，请求会在 `find_maintenance_action`
   返回 None 后直接 `maintenance_action_not_found`，`kind == "start_service"` 里那些分支
   **永远到不了**（曾是死代码：微信按钮健康态恒定失败，WeWe RSS 按钮同病但被「只在挂掉时显示」掩盖）。
2. **签名要对齐入口**：`fixed_start_actions` 的调用**无条件传 `collection_scope`**，只有收这个
   参数的 handler（mediacrawler douyin/xhs）能进。微信 sidecar 启动已退役，请求返回
   `wechat_collection_retired`，不要再把 `start_we_mp_rss_sidecar` 接回可点按钮。
3. 前端新增按钮别忘了在 `boot.js` **绑定点击事件**——函数写好但没 `addEventListener`，
   表现为「点了完全没反应」（同一次事故的另一半）。

## 远程管理后台（token 公开模式）的禁区

2026-07-29 起 local_server 支持「公开模式」：设 `RADAR_ADMIN_TOKEN` 后经 Cloudflare 隧道
暴露到公网，公网页面即可管理订阅源。**两条安全底线**：

1. **静态白名单只许收缩、不许扩张。** `sources.config.json`、`feeds/follow.opml`、
   `local-secrets/`、`data/pending-purge.json`、`.git/`、日志、`计划/`、`.venv*`
   **永远禁止进入白名单**；判定必须先 `unquote` 再 `normpath` 防编码穿越。
2. **绑定非回环地址且无令牌必须拒绝启动**——origin 检查只是 CSRF 防线，挡不住局域网里的
   curl，公网/局域网暴露必须以令牌为前提。

**改 `scripts/radar/server/` 的公开模式逻辑前必读
`docs/rules/remote-admin-public-mode.md`** —— 完整白名单、令牌恒定时间比较、
默认模式逐字兼容与 CORS 精确反射五条契约都在那里。

## 新增桥接类信源自动采集的禁区

2026-08-01 起，新增抖音（`mediacrawler_jsonl`）或微信（`we_mp_rss_jsonl`）信源后会自动触发
一次本机采集（`scripts/radar/server/auto_collect.py`），结束后再触发一轮云端 Actions
（`actions_refresh.py`）。**三条核心红线**：

1. **必须触发计划任务 `DouyinCollectAndPush`，不能自己起采集进程**——身份、凭证、路径三条
   环境约束缺一条就跑不通。2026-08-22 微信采集已下线，**该任务只保留抖音 action**；不要把微信
   加回去（加回去会重新跑已停用的采集链）。旧规则「必须保留抖音、微信两条 action」作废。
2. **派发时机只能在「同步推送成功之后」**，不能在保存阶段——否则采集抢资源会把随后的
   `git push` 拖过 Cloudflare 120 秒读超时，前端报推送失败而后端其实成功了（真踩过）。
3. **若将来恢复微信采集：只能全量重采，禁止单号采集**——桥接 JSONL 是完整快照，单号覆盖会抹掉
   其它公众号的全部历史。当前任务不跑微信。抖音 `locator` 存有 `sec_uid`，可以定向。

只在「新增」时触发；删除、停用、改名一律不触发。本模块不触碰 `data/archive.json`。

**改 `auto_collect.py` / `actions_refresh.py` 前必读
`docs/rules/bridge-auto-collect-contract.md`** —— 七条逐条契约、实测依据、云端刷新的
标记文件位置与失败留痕的 10 字段要求都在那里。

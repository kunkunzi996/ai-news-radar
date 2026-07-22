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

## 产品方向（2026-07-11 调整）

本项目已从「AI 新闻精选雷达」转向**个人订阅聚合器**：核心价值是把用户自己的订阅源
（B站、抖音、小红书、微信公众号、YouTube、RSS、GitHub Release）聚合到一个页面，
按时间流查看。**内容是否与 AI 相关不再是筛选标准。**

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

### 微信公众号 schema 2 清理窄例外

`we_mp_rss_jsonl` 允许在采集管线内清理历史，但这不是通用通道规则，只能同时满足以下条件时启用：

1. 清理身份只能使用稳定 `we_mp_feed_id`。禁止按来源名称、URL 前缀、本轮文章集合或 active 采集范围
   猜测删除对象，也禁止把微信加入 `ENUMERABLE_SUBSCRIPTION_SITE_IDS` 或把本例外类推到其它通道。
2. 只有 sidecar 数据库中的 Feed 被 **hard delete**，即其 ID 不再出现在 schema 2 快照 `known` 中，
   才能成为候选；`status=0` 只是不在 `active` 中、仍在 `known` 中，必须停采但保留全部历史。
3. manifest、JSONL、订阅快照必须属于同一 bridge commit，并通过 schema、路径边界、SHA256、条数、
   `known/active` 集合和 `active ⊆ known` 校验；本轮微信通道还必须真实启用、读取成功且状态完整。
4. archive 中所有微信记录必须 100% 具备合法 ID。任何无 ID、重复 ID、坏行、坏快照、哈希不符、
   commit 不符、通道失败或门控缺失都必须 fail-safe：记录失败状态并且一条不删。非法 JSONL 行必须在
   `RawItem` 构造前拒绝，不能进入 archive。
5. `WE_MP_ORPHAN_CLEANUP_MODE` 只允许 `off/audit/on`，默认和非法值均按 `off`；`audit` 只报告候选，
   `on` 才能按候选 ID 删除。没有完成 100% ID 迁移、真实 audit 人工确认和发布授权前，保持 `off`。
6. 数据恢复只能用 `scripts/restore_we_mp_cleanup.py` 按 `item_id` 精确回插缺失记录；禁止用旧
   `archive.json` 整文件覆盖当前归档，以免抹掉清理后新增的其它数据。

改动这块时，光跑单测不算数——必须真在浏览器里走一遍「删除 / 停用 / 改名 / 原样保存」四种
操作，逐一核对 `data/archive.json` 的条数与 site_id 分布。

### GitHub 星标托管清理窄例外

GitHub 只能走独立的稳定 repo ID 契约，不能进入名称型订阅清理或复用 generic force：

1. 仅 `managed_by=github_stars` 且 `managed_state=auto_disabled` 的受管源可成为候选；手动 GitHub
   `enabled:false` 只表示暂停，绝不自动删历史。
2. 清理身份只能是规范十进制 `managed_repo_id` / `github_repo_identity`，禁止按 owner/repo、来源名称、
   URL、本轮采集范围或 target 推断。
3. 同一 repo 必须在两个不同 `GITHUB_RUN_ID` 的非空完整公开星标快照中连续缺失；空快照、分页/账户失败、
   重复 repo ID 和同一 run 重试都必须熔断，不能推进确认或停用。
4. audit/on 只接受与当前 `GITHUB_RUN_ID`、`GITHUB_RUN_ATTEMPT`、`GITHUB_SHA` 完全配对的 autosync
   状态，并重算 `github-star-purge-state.json` 的 SHA256；任一状态、账号、哈希或 100% 归档身份覆盖不成立，
   一条不删。
5. `STAR_SUBSCRIPTION_CLEANUP_MODE` 仅允许 `off/audit/on`，默认 `off`；`audit` 只写候选和摘要，
   `on` 还必须精确匹配本轮 `STAR_SUBSCRIPTION_CLEANUP_APPROVAL_DIGEST`。摘要失配必须回 audit 重审，
   不能复用或放宽。
6. 回滚只允许 `scripts/restore_github_subscription_cleanup.py --item-id <record.id>` 精确回插 GitHub
   条目；禁止拿旧 `archive.json` 整体覆盖当前归档。

## 同步线上（sync_online_source_config）的 git 编排禁区

该函数用「stash 隔离 → rebase+push → finally 覆盖恢复」处理工作区脏 data（2026-07-14 上线）。改动时：

1. 恢复只能用 `git restore --source=stash@{0} -- .`（只回写工作区）。**换成 `git checkout
   stash@{0} -- .` 会把文件写进暂存区**，下一次同步被开头的 `unrelated_files_already_staged`
   闸拦住（真踩过：单测全绿也没拦住，必须测「连续两次同步」和 staged/unstaged 状态）。
2. 不可改用 `pull --rebase --autostash`：线上 Actions 每轮提交 `data/**`，autostash pop 必
   三方冲突，且此时 rebase 已完成、abort 无效。
3. stash 不带 `-u`；函数只碰自己压入的 `stash@{0}`，用户已有的遗留 stash 会自动回位、不可误 drop。

### merge_sync 专属禁区

当云端信源文件也已变更时，`operation_kind=merge_sync` 是与上述普通同步并列的事务，必须同时满足：

1. 合并结果 M 的 GitHub 星标受管投影必须与云端 R 完全相等；本机不能覆盖云端受管状态。
2. 必须先推送合并提交 C，成功后才能以 CAS 移动本机 `master`；推送失败时本机 HEAD、信源文件和 stash 均不得前进。
3. 合并同步路径永远不得调用 purge 或改写 `data/archive.json` 历史。
4. 台账中 `files.before_sha256` 永远描述本机候选 L，不能改写成云端基线 B 或 R。
5. 每个恢复点在写盘、移动 ref 或删台账前都必须先核对台账摘要、文件 SHA256、HEAD 与 stash 归属；无法证明时保持 pending。
6. 两个信源文件只能从 L 单向一步到 M；任何先退回 B、`git merge --ff-only` 或让用户短暂看到基线的中间态都是缺陷。
7. 以 `git restore` 检出 C 中的路径前，未跟踪 `data/**` 碰撞预检是防止静默覆盖的必需门禁，必须在推送前和实际检出前各执行一次。

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

## 本机维护按钮的派发禁区

`perform_maintenance_action`（`scripts/radar/server/refresh.py`）有两条派发路，加新按钮前先想清楚走哪条（2026-07-15 微信采集按钮真踩过）：

1. **常驻可见的按钮**（`source-config-tools` 工具条那排，如「启动微信采集」「重启本地服务」）
   **必须**走函数开头的无条件字典派发（`fixed_start_actions` / `scope_free_start_actions`），
   **不能**依赖 `find_maintenance_action`。后者只在动态生成的「维护项列表」里查，而那个列表
   只装「检测到出问题的渠道」——系统健康时列表为空，请求会在 `find_maintenance_action`
   返回 None 后直接 `maintenance_action_not_found`，`kind == "start_service"` 里那些分支
   **永远到不了**（曾是死代码：微信按钮健康态恒定失败，WeWe RSS 按钮同病但被「只在挂掉时显示」掩盖）。
2. **签名要对齐入口**：`fixed_start_actions` 的调用**无条件传 `collection_scope`**，只有收这个
   参数的 handler（mediacrawler douyin/xhs）能进；不收 scope 的 sidecar handler
   （`start_we_mp_rss_sidecar` / `start_wewe_rss_sidecar`）必须走 `scope_free_start_actions`，
   误并进前者会 `unexpected keyword argument 'collection_scope'` 崩。
3. 前端新增按钮别忘了在 `boot.js` **绑定点击事件**——函数写好但没 `addEventListener`，
   表现为「点了完全没反应」（同一次事故的另一半）。

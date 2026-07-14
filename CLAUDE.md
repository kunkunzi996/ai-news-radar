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

能删 `data/archive.json` 历史条目的只有「保存/同步信源配置」这一条路径。下面每一条都
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

改动这块时，光跑单测不算数——必须真在浏览器里走一遍「删除 / 停用 / 改名 / 原样保存」四种
操作，逐一核对 `data/archive.json` 的条数与 site_id 分布。

## 同步线上（sync_online_source_config）的 git 编排禁区

该函数用「stash 隔离 → rebase+push → finally 覆盖恢复」处理工作区脏 data（2026-07-14 上线）。改动时：

1. 恢复只能用 `git restore --source=stash@{0} -- .`（只回写工作区）。**换成 `git checkout
   stash@{0} -- .` 会把文件写进暂存区**，下一次同步被开头的 `unrelated_files_already_staged`
   闸拦住（真踩过：单测全绿也没拦住，必须测「连续两次同步」和 staged/unstaged 状态）。
2. 不可改用 `pull --rebase --autostash`：线上 Actions 每轮提交 `data/**`，autostash pop 必
   三方冲突，且此时 rebase 已完成、abort 无效。
3. stash 不带 `-u`；函数只碰自己压入的 `stash@{0}`，用户已有的遗留 stash 会自动回位、不可误 drop。

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

# PROJECT_STATE

## 已阅后立刻下滚不再被二次校正拽回（2026-08-30，已部署并验收）

- **做了什么**：`consumeListStayRestore` 两帧后再校正时，若滚动位置已变，视为人已经开始滚，不再 `scrollBy` 拽回。新增 TEST-024。当时脚本戳 `stay-noscroll-0830a`；随后 continue-watch 把 `render-list.js?v=` 换成 `continue-watch-0830a`，守卫仍在。
- **Git**：PR #36 `131c4ec` 已合 `master`。工作台嵌页戳另仓 PR #47。
- **验收**：P5 `TEST-024` 与 TEST-018/019/021/022 通过。全量 e2e 15 红为油管订阅过滤 vs 旧夹具 81 条，本轮未改那些期望。P6 用户口头通过。NUC 生产仓已含 #36。
- **当前无活跃 SPEC/PLAN/TASK/TEST**。轻量修复，无四文件。
- **未做**：未改 `layout-timeline` 的 81 条断言。

## App 我的订阅对齐并停采公开博客（2026-08-30，已部署并验收）

- **做了什么**：公开博客 RSS（OpenAI / Hugging Face / Simon Willison / Google AI / DeepMind / Microsoft AI Blog）`enabled: false`，`feeds/online-sources.opml` 只留小岛大浪吹与脑总MrBrain。网页「我的订阅 / 油管」不再把 HighLevelz 当订阅；已阅只按工作台链接键计数。脚本 `?v=` 与工作台 iframe `wb=` 已换戳。
- **Git**：PR #30～#34 已合 `master`（含停采、油管口径、缓存戳、已阅链接键）。NUC `C:\AI-news-reader\ai-news-radar-run` 已 `git pull --ff-only`。
- **验收**：工作台侧 P5 `test:core` 173、P6 模拟器+Mate X6 通过。用户确认订阅内容对齐；已阅网页 145 / App 142 可接受。
- **当前无活跃 SPEC/PLAN/TASK/TEST**（本仓本轮无独立四文件；规格在工作台 `docs/archive/2026-08-30-App我的订阅对齐网页并停采公开博客/`）。
- **未做**：不要用采集范围清归档里这些博客的历史。

## 整理收口、微信采集下线、对外身份独立（2026-08-23～2026-08-26，已部署并验收）

- **做了什么**：清外围施工残骸；Git 里过期 `计划/` 与旧 docs 已删；微信采集下线（停抓新、留历史）；NUC 停 sidecar/看门狗并去掉计划任务里的微信 action；页面与 README 改为「我的订阅」/个人订阅聚合器。
- **Git**：`90b470c` 下线微信采集；`1af46f2` 对外身份。均已快进进 `master`。
- **验收**：Python 相关 `437 passed`；E2E 50 条中 49 过、1 条端口抢占失败后重跑通过；用户确认合并部署；NUC `auto-ff.sh` `ff-ok`，`DouyinCollectAndPush` 只剩抖音，`8001` 已关闭。
- **GitHub 仍显示 fork**：`LearnPrompt/ai-news-radar`。仓库 GitHub `diskUsage` 显示约 7GB（与本地 pack ~63MB 不符），脱离 fork 网络未做成。clone 地址未改。
- **未做**：四文件正式轮次（本轮无 `docs/spec.md` 等）；未拆当前整理 worktree；未迁 `E:\Ai-coding`。
- **当前无活跃 SPEC/PLAN/TASK/TEST。**

## GitHub Actions 采集卡满 15 分钟整轮停更（BUG-03，2026-08-26，已部署并验收）

- **现象**：公开快照停在 `2026-08-22T19:27:39Z`（北京时间 8 月 23 日凌晨）。定时任务 `Update AI News Snapshot` 从 19:36 UTC 起每次在 Update data 卡满 15 分钟被杀，数据提交不出去。采集脚本那之后没有改过。
- **根因**：job 上限 15 分钟；`create_session()` 自动重试 3 次；B 站 6 个号 × 最多 8 页没有总预算。最坏约 64 分钟。一个号卡住，整轮作废。
- **修法**：采集会话禁止自动重试；B 站总预算 90 秒，超时跳过剩余号；翻译预算 45 秒；`[collect]` 进度日志。
- **提交 / 合并**：`3a5ae6c` / `05a39f3`（PR #26）。
- **验收**：生产 run `32917647783` **成功 1 分 29 秒**（Update data 67 秒）；B 站 51 条 / 4.2 秒 / `deferred=0`；抖音 52 条；`generated_at=2026-08-26T01:05:45Z`；用户确认能看见最新。新增预算测试通过。全量 `pytest -q` **723 passed**；3 条 `Get-FileHash` 失败为本机 PowerShell 环境问题，与本 diff 无关。
- **过程文档**：`docs/bugs/BUG-03-GitHub采集卡满15分钟整轮停更.md`。施工约束在 `CLAUDE.md`「GitHub Actions 采集超时的禁区」。
- **同期事实（不是本 bug 根因）**：NUC 当时在 WiFi「多乐之家-5G」、`192.168.1.3`；开发机网线 `192.168.3.47`。UU 能连、旧 SSH `192.168.3.66` 不通。抖音桥接 8 月 25 日 20:44 仍有成功推送。

## 抖音风控容错与部分成功发布（2026-08-08，已部署并验收）

- **背景**：抖音详情接口（`/aweme/v1/web/aweme/detail/`）带 `ArgusSecurityPlugin` 风控，
  每轮 52 条里偶发拦 0~5 条。原回执口径要求「6 个号全部一条不少」，导致 2026-08-05 起
  **连续 10 轮 `state=failed`**，桥接仓库从 08-06 13:14 停更两天——而本机 JSONL 一直是完好的，
  纯粹是「采到了但不让发」。详见 `docs/bugs/BUG-02-抖音采集回执不完整导致整轮作废.md`。
- **修法**（用户拍板「采到多少发多少 + 缺失要能看见」）：创作者互相隔离、详情退避重试
  （3 次尝试 / 2s→5s）、回执改 `completed`/`partial`/`failed` 三态、发布门槛放宽为
  「至少一个号有产出」、缺失经桥接 `manifest.json`（schema 2）上云并在看板显示「部分完成」。
  保留 fail-safe：**六个号全失败仍不发布**。
- **数据安全**：全程不写 `data/archive.json`，与所有清理逻辑零交集；回滚只需 `git revert`。
- **验收证据**（NUC + 桥接 + 云端 + 浏览器四处实测）：
  - NUC：`state=succeeded`、6/6 号 `completed`、`crawl_output_rows=52`；
    `[DetailRetry]` 触发 2 次（均 `attempt=2/3`），**验收当轮就真的救回 2 条**。
  - 桥接：`d0d1e5a`(08-06 13:14) → `c27f20e`(08-08 17:20)，`manifest.schema_version=2`。
  - 云端：`source-status.json` 抖音条目含 `partial` / `missing_rows` /
    `collection_manifest_available` / `collection_generated_at`。
  - 浏览器：源状态表抖音行显示「正常」；注入 `partial=true` 后变黄色「部分完成」。
  - 测试：全量 **769 passed, 0 failed**（743 基线 + 26 条新增，精确吻合）。
- **遗留局限**：验收当轮 `Argus=0`，**未取得真实风控下的现场证据**；「一个号被拦 → 其余号
  照采 → 看板标黄」这条完整链路目前只由自动化测试与浏览器注入模拟覆盖。
- **过程教训**（已写入 `CLAUDE.md`「给源状态加字段的必查清单」）：真机验收抓出两个
  「单测全绿但线上不可用」的缺陷——fetcher 有两条分支只改了一条；`cli.py` 逐字段重构
  statuses 把新字段丢了。二者同源：验证了代码路径，没验证产品路径。

## 采集结束后清理残留标签页（BUG-01，2026-08-08，已部署并验收）

- 根因：从计划任务 → `deploy/cloud-pc/collect-douyin-and-push.ps1` → `scripts/run_mediacrawler_douyin.py`
  整条采集链路**没有任何浏览器收尾环节**。专用 Chrome（端口 9333）启动后常驻复用，
  MediaCrawler 每轮新开一个标签页且从不关闭，标签页与内存随轮次单调增长。
  NUC 实测修复前 tabs `1→2→3`，采集结束后不回落，稳态 756 MB 且持续上涨。
- 修复：`main()` 在采集前记录标签页 id 快照，`finally` 中只关闭本轮新增的那些
  （按 id 差集、只认 `type=page`、保留至少一个页面、`--browser-only` 跳过、
  清理失败只告警不改返回码、全程在 `collection_lock_context` 内）。
  提交 `f982675`，合并 `3896552`，验收文档 `e128885`；当前主线与 NUC 均已部署。
- 验收证据：全量 `python -m pytest -q` **743 passed**（改动前基线 729，新增 14 条，
  基线 729 条无一失败）；NUC 真实采集两轮，tabs 由 `1→2→3` 变为 `1→2→1`，
  稳态内存 756 MB → 341 MB，每轮产生一条 `[TabCleanup] closed 1 leaked tab(s), failed 0`；
  失败轮次（`state=failed`）同样完成清理，异常路径一并验证；用户人工验收通过。
- 过程文档：`docs/bugs/BUG-01-采集后浏览器窗口不关闭.md`（现象/根因/验收证据）。
  施工约束已固化进 `CLAUDE.md`「采集浏览器收尾的禁区」。
- **遗留的独立问题 → 已闭环**：`partial_creator_failure` 已由 BUG-02 于 2026-08-08 修复并验收，
  详见本文件顶部「抖音风控容错与部分成功发布」一节与 `docs/bugs/BUG-02-抖音采集回执不完整导致整轮作废.md`。

## NUC 脏工作区护栏与旧脚本迁移（2026-08-04，已部署并验收）

- 线上信源保存与同步已收敛为事务：保存阶段失败会回滚配置、OPML、待清理台账和自动采集登记；同步阶段失败会保留可识别的错误原因，不再把半完成状态当成成功。当前主线和 NUC HEAD 均为 `900c34b`；NUC 运行工作区干净，本地当前仅有本轮文档未提交改动。
- NUC `RadarAutoFF` 已改为执行 Git 跟踪的 `scripts/windows/auto-ff.sh`。成功写入 `event=ff-ok`，失败写入退出码、旧/新 HEAD、stderr 摘要和分类 `reason`；遇到脏工作区只记录并退出，不覆盖本机采集产物。
- 旧的未跟踪脚本已迁移完成。原脚本及 `previous-worktree` 副本保留在 NUC 的 `_deploy-backups\auto-ff-migration-20260804` 下，仅作回退依据，未删除运行时数据或凭据。
- 验收证据：NUC `tests/test_auto_ff.py` **4 passed**；保存同步专项 **8 passed**；`py_compile`、`node --check`、本地前端 E2E **31 passed**；API 配置读取 HTTP 200、CORS 预检 204、非法保存 409、本地状态 200；用户人工验收通过。

## 微信采集已下线（2026-08-23 NUC 停机，代码 2026-08-22 合入）

- 产品：公众号历史仍可看，不再抓新。`online_we_mp_rss_maobidao` 为 `enabled: false`，配置条目保留以免误清历史。
- 管线不再打开 `WE_MP_*` / `WEWE_*` 采集开关；维护接口 `start_we_mp_rss_sidecar` / `start_wewe_rss_sidecar` 返回 `wechat_collection_retired`。
- NUC：`WechatHealthWatchdog` 已禁用；we-mp 进程已停，`8001` 关闭；`DouyinCollectAndPush` 只留抖音；`start-server.cmd` 里微信公网地址已注释（备份 `start-server.cmd.bak-wechat-retire-20260823`）。sidecar 目录和数据库未删。
- Cloudflare `wechat.wanyouomnia.cn` 路由可能仍在，后端已无监听。不要把它当采集还活着。
- 归档清理窄例外与 `restore_we_mp_cleanup.py` 仍有效，禁止用「源已停用」去扫 `archive.json`。

## 工作台 AI 雷达配置页来源校验修复（2026-08-03，已部署并验收）

- 根因：工作台 iframe 的 `Origin/Referer` 可能来自 `radar.wanyouomnia.cn` 或
  `app.wanyouomnia.cn`，NUC 启动脚本当时只信任 GitHub Pages，接口返回 `403 non_local_origin`；
  服务端同时补充了带路径/query 的 iframe Referer 规范化匹配。
- 修复提交 `f7b2241` 已合入 `master`；当前主线与 NUC 部署点为 `900c34b`；NUC 实际白名单为
  `https://kunkunzi996.github.io`、`https://radar.wanyouomnia.cn`、`https://app.wanyouomnia.cn`。
- 验收证据：`tests/test_local_server.py` **155 passed**；`py_compile`、`git diff --check` 通过；
  公网 API 返回 200、线上信源 53 条；用户已实际打开工作台配置页并成功修改信源。

## GitHub 重大更新筛选与 NUC 同步（2026-08-03，已完成施工与部署验收）

- 任务等级：中型；流水线挡位：手动挡。
- 施工分支：`feature/github-important-updates`；独立工作区：
  `E:\AI-news-reader\ai-news-radar-important-updates`；基线：`origin/master@e59f366`。
- 用户已确认采用保守的“GitHub 重大更新可信度分”：满分 100，70 分展示；commit 必须同时具备
  功能意图和实质产品代码改动，预发布及纯文档/测试/CI/格式/依赖/自动同步噪音直接隐藏。
- 用户已复核设计并授权开始施工。该功能已合入主线，过期施工稿已从工作区移除。
- 已按失败用例优先完成最小实现；V1 Python 回归与 V2 本地浏览器检查均已通过。
- 验收证据：相关回归 **275 passed**；`py_compile`、`git diff --check` 通过；真实归档只读预览为
  GitHub `303 → 36` 条可见，历史归档未改写。Playwright 页面确认 `Partner 2.0.0`、`v8.5.0`
  可见，补丁版、预发布和“反应测试”提交隐藏；B 站栏目仍为 405 条。
- 施工约束：不删除历史归档、不安装依赖、不改前端交互、GitHub 星标同步或取消订阅清理契约；
  部署同步沿用既有 Pages/NUC 机制，不改部署契约。
- 当前流水线状态：`DONE`；功能提交 `e3d5983` 已通过 PR #18 合并（`2249cc7`），历史归档展示修复
  `551362a` 已通过 PR #19 合并（`53378af`），随后数据快照合并提交为 `fe1dcde`，当前
  `master` / `origin/master` 已继续推进到 `900c34b`。
- NUC `omnia-nuc`（`DESKTOP-H9RAKEH`）已部署并继续快进到 `900c34b`；NUC 专项
  `pytest -q tests/test_topic_filter.py` 为 **112 passed**。本机 `8080`、公网管理后台和 Pages
  均返回 HTTP 200。`scripts/windows/auto-ff.sh` 已纳入 Git 跟踪，旧脚本副本仅作为回退备份保留。
- Pages 部署和数据 Actions 均成功；feature 分支与 worktree 暂保留，未执行删除清理。

## 更早历史

2026-08-02 及以前的施工状态、下一轮入口与历史闭环记录已不在工作区保留，需要时从 Git 历史查看。

## 维护规则

- `PROJECT_STATE.md` 只记录当前状态与最近一周的关键交接。
- 刷新、采集等操作手册放入 `docs/guides/refresh-playbooks.md`。

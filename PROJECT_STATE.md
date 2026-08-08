# PROJECT_STATE

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
- 过程文档：`docs/bugs/BUG-01-采集后浏览器窗口不关闭.md`（现象/根因/验收证据）、
  `docs/plan.md`（七章，已 FROZEN）、`docs/task.md`（3 对 TDD 任务卡与红绿证据）。
  施工约束已固化进 `CLAUDE.md`「采集浏览器收尾的禁区」。
- **遗留的独立问题（未处理）**：`partial_creator_failure` —— 某创作者列出 10 条只写入 9 条，
  导致每轮采集 `state=failed`、桥接不更新。经 `logs/bridge-collection-failures.jsonl` 核对，
  修复前后行为完全一致，与本轮改动无关，已另开会话处理。

## NUC 脏工作区护栏与旧脚本迁移（2026-08-04，已部署并验收）

- 线上信源保存与同步已收敛为事务：保存阶段失败会回滚配置、OPML、待清理台账和自动采集登记；同步阶段失败会保留可识别的错误原因，不再把半完成状态当成成功。当前主线和 NUC HEAD 均为 `900c34b`；NUC 运行工作区干净，本地当前仅有本轮文档未提交改动。
- NUC `RadarAutoFF` 已改为执行 Git 跟踪的 `scripts/windows/auto-ff.sh`。成功写入 `event=ff-ok`，失败写入退出码、旧/新 HEAD、stderr 摘要和分类 `reason`；遇到脏工作区只记录并退出，不覆盖本机采集产物。
- 旧的未跟踪脚本已迁移完成。原脚本及 `previous-worktree` 副本保留在 NUC 的 `_deploy-backups\auto-ff-migration-20260804` 下，仅作回退依据，未删除运行时数据或凭据。
- 验收证据：NUC `tests/test_auto_ff.py` **4 passed**；保存同步专项 **8 passed**；`py_compile`、`node --check`、本地前端 E2E **31 passed**；API 配置读取 HTTP 200、CORS 预检 204、非法保存 409、本地状态 200；用户人工验收通过。

## 微信采集后台跨设备访问修复（2026-08-03，已提交并部署）

- 代码提交 `6202058` 已推送到 `master`；本地与 `origin/master` 一致。方案 A：远程模式打开
  `https://wechat.wanyouomnia.cn`，由 Cloudflare Tunnel 转发到 NUC 本机 `127.0.0.1:8001`；本机模式仍优先打开本地地址。
- NUC `omnia-nuc` Tunnel（ID `e8ff31f8-1b01-408d-8b4e-4d2d1e92916a`）已在现有
  `C:\OMNIA\staging-cloudflared\config.yml` 追加微信 ingress，并通过 Cloudflare CLI 创建
  `wechat.wanyouomnia.cn` DNS 路由。原有 `app/radar/collect/calendar` 路由保持不变。
- NUC `RadarAdminServer` 启动脚本已补 `WE_MP_RSS_PUBLIC_ADMIN_URL=https://wechat.wanyouomnia.cn`；
  `OMNIA Staging Tunnel` 与 `RadarAdminServer` 计划任务均已重启，8001/8080 正常监听。
- 验收证据：Tunnel 有 4 个活动连接；公网 `https://wechat.wanyouomnia.cn/` 与 `/docs` 均 HTTP 200；
  真实浏览器打开到微信后台登录页；后台维护接口返回 `local_url=http://127.0.0.1:8001`、
  `public_url=https://wechat.wanyouomnia.cn`。
- 配置回退副本保留在 NUC：`config.yml.before-wechat-20260803.bak`、
  `start-server.cmd.before-wechat-20260803.bak`。不删除运行时数据，不提交凭据。

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
- 用户已复核设计并授权开始施工。设计稿：`计划/2026-08-02-GitHub重大更新筛选设计.md`；
  施工计划：`计划/2026-08-02-GitHub重大更新筛选施工计划.md`。
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

## Harness 收尾验收（2026-08-02）

- 本轮文档收尾已通过 PR #16 合并至 `master`（合并提交 `c8acfbd`）；部署不适用，feature 分支与远程分支暂保留。
- 本条 Harness 待办已完成：未跟踪文件已分类，三个本地生成物目录已精确加入 `.gitignore`；两份 `计划/` 文档保留、未忽略，用户已确认纳入本次提交。
- `CLAUDE.md` 已绑定检查：改动 `scripts/**` 必跑并记录项目已有 Python 检查；改动 `assets/js/**` 必跑并记录 `npm run test:e2e`；两类同时改动时两类都跑。
- Python 专项实际命令：`.\.venv\Scripts\python.exe -m pytest -q tests\test_bridge_collection_failure_log.py tests\test_wechat_health_probe.py tests\test_wechat_health_watchdog.py tests\test_we_mp_rss_jsonl_source.py`，结果 **59 passed in 89.79s**。
- Harness 初次验收记录为 `19 passed、4 failed、3 did not run`，复验为 `20 passed、3 failed、3 did not run`；当时的 `#onlineSourceSyncBtn` 与工作台 `8765` 端口问题已在后续专项中完成复核，历史细节见 `BLOCKED.md`。
- 后续线上信源保存同步 E2E 已由提交 `7be45ba` 更新、经合并提交 `5fc7cc4` 纳入 `master`：专项测试 **5 passed**，完整 `npm run test:e2e` **26 passed、0 failed、0 skipped**；此前 `layout-timeline` 的 `81 条`/`0 条`差异未复现。
- `git diff --check`：通过（无输出）。

## 当前施工状态（2026-08-02）

- **桥接采集失败留痕已完成并合入、推送 `master`**：功能提交 `6cfc99f 修复桥接采集失败留痕`，
  洁癖门收口提交已 rebase 到期间产生的远端数据快照后推送；本轮收口完成时主线为 `9b14e3e`。
  `deploy/cloud-pc/collect-douyin-and-push.ps1` 和
  `deploy/local/collect-wechat-and-push.ps1` 在 `Exit-Run` / 异常收尾时写入
  `logs/bridge-collection-failures.jsonl`；记录固定 10 个字段，消息最多 512 字符，按渠道与
  `run_id` 去重，不写入原始输出、cookie 或凭证。失败留痕写入失败只告警，不改变原状态和退出码。
  `state` 非成功以及 `expired` / `login_required` / `invalid` 登录态都会留痕；成功且登录态正常不追加。
  本轮未修改 UI、`data/**`、bridge 仓库或推送流程。
  - 专项复核：`.\.venv\Scripts\python.exe -m pytest -q tests\test_bridge_collection_failure_log.py tests\test_wechat_health_probe.py tests\test_wechat_health_watchdog.py tests\test_we_mp_rss_jsonl_source.py`，**59 passed in 91.71s**。
  - 另有 `py_compile` 与 `git diff --check` 通过；全量 `python -m unittest discover -s tests -q` 曾运行 319 秒后以退出码 `124` 超时，不能记为全量通过。
- **变更分析已排除损坏虚拟环境**：`.gitignore` 已忽略 `.venv.broken-py311/`（提交 `8da5b77`）；目录本身保留，不删除。

## 当前施工状态（2026-08-01）

- **新增桥接类信源后自动采集 + 云端刷新已上线并真实验收**：解决「新增抖音博主/微信公众号后，
  最坏要等 12 小时（NUC 定时 `08:10/13:10/20:10`）才能看到内容」。功能提交 `e4ef1e0`、
  `0397467`，时序修复 `3207d45`，经 PR #12 / #13 合入 `master`（合并提交 `31c82a1`、`8c9402f`）。
  NUC 已快进部署并重启 `RadarAdminServer`。新增模块 `scripts/radar/server/auto_collect.py`
  （检测新增桥接源并触发采集）与 `scripts/radar/server/actions_refresh.py`（等采集结束后经
  GitHub Contents API 提交标记文件 `.bridge-refresh.json` 触发 workflow）；`local_server.py`
  仅新增挂钩点。**约束与踩坑已固化进 `CLAUDE.md`「新增桥接类信源自动采集的禁区」，改这块前必读。**
  - **真实端到端验收（2026-08-01 15:02→15:14，全程无人干预）**：公网新增抖音博主
    「芙芙家的洗碗君」→ 15:02:18 触发采集 → 15:12:34 抖音采完（6 博主、10 条新内容、Bridge 已推）
    → 15:13:39 微信采完 → 15:13:52 看门人自动提交 `e32dc1c` → 15:14 Actions 跑完 `dbb42ea`。
    公网 `archive.json` 已含「芙芙家的洗碗君」10 条、「Game AI Lab」10 条。
  - **三条被实测推翻的设计前提**（第一版实现按「服务自己起采集进程」写，必然失败）：服务是
    `SYSTEM/ServiceAccount` 而采集任务是 `beelink-pc/Interactive`（拿不到抖音登录态）；SYSTEM
    侧 PAT 只对本仓库有 Contents 权限、够不着 `douyin-bridge`；脚本默认推导的 `MediaCrawler`
    路径在 NUC 上不存在（实际是 `MediaCrawler-local-test`）。最终改为 `schtasks /run` 触发既有
    计划任务，参数与身份全部现成。
  - **一个真实 bug 及修复**：首版在「保存」阶段派发采集，采集抢占资源拖慢紧随其后的
    `git push`，超过 Cloudflare 120 秒读超时，前端红字「推送失败: Failed to fetch」而后端其实
    已成功。改为保存只登记、同步推送成功后才派发（`3207d45`）。
  - 验收数据：全量 `unittest discover tests` **586 passed**；NUC 上专项 46 passed；
    `py_compile`、`git diff --check` 通过。
- **同轮暴露的既有问题（已修复并补上护栏）**：NUC 的 `RadarAutoFF`（每 10 分钟自动快进）此前
  因 `data/` 下本机采集产物挡住 `merge --ff-only` 而静默跳过，导致 NUC 落后 11 个提交。
  现已改为可观测失败日志并保留脏工作区；若发现 NUC 代码不更新，先查 `logs/auto-ff.log` 的
  `reason` 和退出码，不要手工覆盖 `data/**`。
- **本机主工作区已同步**：`ai-news-radar-run` 已从 `26cf849`（7/18）快进到最新，
  此前落后 200+ 提交。
- **`git stash list` 曾显示为空，2026-08-01 查清：是账本丢失，不是数据丢失**（已恢复显示）。
  `stash list` 读的是 reflog（`.git/logs/refs/stash`）而非 `refs/stash` 本身；当时该 reflog 文件
  丢失，而 `refs/stash` 本体一直在 `.git/packed-refs` 里指向 `0e94dbf`「On master: 收尾前保护：
  本机旧数据与临时文件（2026-07-18）」。已手工重建 reflog。**当前实有 1 个 stash**（旧文档里
  「两份/三份保护存档」的说法已作废，见下文「本机保护存档」订正）。
  - 那 6 条 GitHub Release 历史（`github_foundation_sunshine_releases` / AlkaidLab）**没丢，
    且已提交进版本库**：工作区 / 本机 HEAD / `origin/master` 三处 `data/archive.json` 实测均为
    6 条，无未提交改动。「stash 是唯一备份」这个旧前提早已作废，现存 stash 里反而 **0 条**该记录。
  - 清理前的**完整 70 条**在提交 `d85b916^`（`d85b916` =「数据：清理已退订信源
    AlkaidLab/foundation-sunshine 的 14 条历史条目」）。找回用 `git show d85b916^:data/archive.json`。
  - ⚠️ `d85b916` 是**不可达提交**，`git gc --prune=now` 会清掉那 70 条备份 —— 本仓库勿随手 gc。

## 历史施工状态（2026-07-29，已闭环）

> 下条「待合入主线」为当时状态，**该功能已于 2026-07-29～30 合入并部署上线**，
> 公网远程管理后台目前是日常使用的主要入口。

- **公网页面远程管理后台已完成施工，待合入主线**：功能分支 `feature/remote-admin-console`，
  功能提交 `d67ba93`（基线 `2bbe272`）。实施后公网 Pages 页面配置「远程后台」
  （API 地址 + 管理令牌）即可直接增删改查订阅源，NUC 上 local_server 只绑回环、
  经 Cloudflare 命名隧道暴露。实施计划：`计划/2026-07-29-订阅源管理合并入公网页面实施计划.md`。
  验收：新增 19 个 pytest 用例全过；全量测试 FAILED 清单与未改动 HEAD 基线**完全一致**
  （84 个失败系本机 git 环境型——`refs/remotes` 引用写入不落盘，基线同挂，非本次引入；
  ⚠️ 该「环境型」归因于 2026-08-01 查明为**单分支 refspec**所致、与 git 版本无关，且已修复，
  见本文件 2026-08-01 段与 `HANDOFF.md`，该批测试可重跑）；
  真实浏览器验收通过：跨域连接、令牌持久化、线上信源读取、失败安全（环境故障时
  保存请求熔断且文件零污染）。**因本机 git 环境故障，「真实变更保存」的浏览器端到端
  路径未能走通**（保存事务的 `master@{upstream}` 预检必挂）；该路径为既有生产代码、
  本次未触碰，需到 NUC 真实环境补验。
- **预埋 bug 修复**：`process_is_running` 改字节匹配，根治中文进程名导致 tasklist
  GBK 解码异常只发生在读取线程、`stdout=None`、`/api/local-status` 500 的问题
  （本机陈旧 pid 被中文名进程复用时必现；NUC 迟早会踩）。
- ~~**本机 git 环境告警**：本机 git 2.54.0.windows.1（vendored 与系统两份同版本）出现
  `refs/remotes/*` 及部分 `refs/heads/*` 写入间歇性不落盘，导致线上同步事务预检
  （`master@{upstream}`）与 84 个 git 事务测试全部失败；提交/分支操作需手工钉 ref。
  NUC 部署前必须先确认 NUC 的 git 无此问题。~~
  **↑ 该告警已于 2026-08-01 撤销：归因是错的，问题已修复。** 真因与 git 版本、杀软、文件系统
  均无关，而是本机这份仓库为浅克隆（`.git/shallow` 存在，隐含 `--single-branch`），`.git/config`
  的取货清单被写死成 `fetch = +refs/heads/master:refs/remotes/origin/master` —— 只认 master，
  其余分支 `fetch` 压根没去问。修复即一行 `git config --replace-all remote.origin.fetch
  "+refs/heads/*:refs/remotes/origin/*"` 后重新 fetch；验收 `git branch -r`（排除 `HEAD ->`）
  = `git ls-remote --heads origin | wc -l` = 7，且在「新增分支 / master 前进 / 删除分支」三种
  场景下均正确同步。**「手工钉 ref」的绕行做法就此废止**，NUC 也不需要再做此项排查。

## 当前施工状态（2026-07-26）

- **NUC 采集节点迁移已完成**：NUC 已成为唯一启用的采集节点。`DouyinCollectAndPush` 保持每日
  `08:10 / 13:10 / 20:10`、`Interactive` 桌面会话和 `IgnoreNew` 防并发；在 `18:00`、`18:15`
  的两次真实计划触发均成功。两轮抖音均为 `4/4` 完成、失败 `0`，微信均成功；两个 Bridge 均为干净的
  `main`，且与实时远端一致。NUC 的 `WechatHealthWatchdog` 已迁移为每小时只读检查，最近回读为
  `Ready`；它不启动或停止采集，也不修改新闻数据。
- **观察期由用户明确跳过**：迁移直接记为完成，但不清理任何回退资源。旧电脑的
  `DouyinCollectAndPush`、`LaunchDouyinGuard`、`WechatHealthWatchdog` 均为停用状态并继续保留；
  只有发生故障时才按既有回退规则处理，禁止以旧历史覆盖 Bridge。
- **历史记录（2026-07-24，已闭环）**：NUC 采集节点迁移当时尚未完成验收，目标根目录为
  `C:\AI-news-reader`。主仓库、
  `MediaCrawler-local-test`、`we-mp-rss-sidecar`、`douyin-bridge`、`wechat-bridge` 已恢复或克隆；
  三套 Python 环境与 Playwright 浏览器已验收。微信公众号服务现运行于 `127.0.0.1:8001`，用户扫码后
  刷新仍保持登录，页面与订阅内容正常。抖音专用 Chrome 使用 `127.0.0.1:9333` 和独立
  `chrome-profile`，直接登录检测为 `logged_in`；NUC 的 `douyin-bridge` 曾快进至当时远端
  `5420d632f0aef1d67cde0809b52f437dc89b11f9`，工作区干净且读写 dry-run 已通过。
- **历史记录（2026-07-24，已闭环）**：首次抖音真实采集当时阻塞在进程入口诊断；采集命令被终端记录为已调用，但没有
  捕获子进程退出码，`douyin-collect-status.json` 也未生成；终态无采集进程、无锁、无输出、无 Bridge
  改动或远端写入。因此这不是 MediaCrawler 采集失败证据，也不能记为采集成功。下一轮先按
  `HANDOFF.md` 做只读的脚本加载、PowerShell 退出码、日志/owner/锁痕迹诊断；诊断前禁止重试。

- **线上信源自动合并同步（WS-3）已闭环并上线**：功能提交 `17a6e50` 已通过 PR #9 的合并提交
  `18b1f07` 纳入 `master`，当前主线为 `7efa8bf`。本机在云端配置推进时以共同基线 B、本机候选 L、
  云端 R 按稳定 `source.id` 做三方合并；安全可证明时先推送合并提交再将本机 L 一步切至 M，无法证明时
  保持零副作用并返回受限冲突明细。台账 schema v2、stash 恢复、未跟踪 data 碰撞门禁、冲突前端提示
  与文档禁区均已完成。验收包含 20 个 local-server 剧本、两条真实浏览器路径以及
  `tests/test_local_server.py` 134 passed、`tests/test_online_sources.py` 94 passed；合并后云端
  GitHub 星标自动同步与 Pages 均正常。用户已决定暂不处理冲突折叠提示、分类标签和英文内部码三个小迭代。

- GitHub 取消星标联动清历史已在 `E:\AI-news-reader\ai-news-radar-unsubscribe-purge-github` 的
  `feature/unsubscribe-purge-github` 完成施工和验收；功能提交为 `a16f81a`，已由合并提交 `ef4ddf2`
  纳入 `master`。**流水线挡位：手动挡**；专项测试、全量 pytest（`600 passed, 1 warning, 109 subtests passed`）、
  `py_compile` 和 `git diff --check` 已通过。尚未修改 Actions Variables 或触发线上清理。
- 本轮边界是稳定 repo ID、两次非空完整快照、本轮状态哈希配对和 `off -> audit -> on` 一次性审批；不改
  B站、抖音、微信、RSS、小红书、前端、数据库、依赖或部署结构。
- 本地只读 audit 已确认当前没有可删除候选：本机没有本轮 Actions 身份与 purge-state 配对，这是预期
  fail-safe。合入后仍须先保持 `STAR_SUBSCRIPTION_CLEANUP_MODE=off`，等待两个不同 run 的成功非空完整同步，
  再由用户按 audit -> on 灰度。
- **线上信源合并与停用联动修复已完成并验收**：功能提交 `b94039e` 已由 PR #7 的合并提交 `db47d62`
  纳入 `master`。修复会在停用信源清理历史后，同步重写展示数据及统计字段；用户已完成实际验收。当前云端
  配置保留“中二的大暄哥”为停用状态，并保留云端新增的 `Wechat-ggGitHub/wechat-claude-code` 信源。

## 下一轮入口（2026-07-26 更新）

- **NUC 迁移无需重复执行**：保持 NUC 正式排程和旧电脑任务停用状态；不要重跑阶段 1-6、不要重新启用
  旧电脑任务，也不要删除旧电脑资源。阶段 7 已由用户授权跳过，后续只在真实故障时走回退决策。
- **历史入口（2026-07-24，已闭环）**：当时的最高优先级曾是继续 NUC 迁移诊断：先读
  `HANDOFF.md` 的“NUC 迁移下一轮入口”，对首次抖音调用未生成状态文件做只读定位；当时旧电脑采集任务
  仍启用，NUC 每次真实采集前都必须重新查询 Bridge 实时远端并只做可证明的 `--ff-only` 同步。
  后续两次成功计划运行已完成验收，旧电脑任务现已停用；不要再执行这条诊断入口。

- **2026-07-19 微信采集健康看门狗与 MeoW 告警已完成并真实验收（当前在 NUC 运行）**：功能已通过
  `b2a8614 合并：微信采集健康看门狗与登录状态告警` 合入并推送 `master`。Windows 计划任务
  NUC 计划任务 `WechatHealthWatchdog` 每小时执行；验收时状态为 `Ready`、上次结果 `0`。它只读取采集和登录状态，
  不启动或停止采集，也不修改新闻数据。手机 MeoW 触达已验收；真实采集为
  `succeeded / completed_no_change / exit_code=0 / login_state=valid / output_rows=60`，正式看门狗为
  `succeeded / healthy / exit_code=0`。合并后全量测试为 `585 passed, 1 warning, 98 subtests passed`，
  PowerShell AST、UTF-8 BOM 与 `git diff --check` 均通过。密钥继续仅保留在
  `local-secrets/meow-push.json`；工作区外的看门狗状态、日志和采集运行文件均须保留，不提交或删除。

- **主工作区同步与洁癖（2026-07-22）**：主工作区当前为 `7efa8bf`，与 `origin/master` 一致；云端
  Actions 会持续产生 `data/**` 快照。同步前本机数据、配置和计划草稿已保护为当前 `stash@{0}`（名称为
  “收尾前保护：本机快照与计划草稿（2026-07-20）”）；该存档中的四份计划书与当前受 Git 管理的版本逐字一致，
  但整份存档仍不得自动丢弃。此前旧数据、临时截图和实测脚本当前为 `stash@{1}`，6 条 GitHub Release
  历史的唯一备份当前为 `stash@{2}`，同样严禁丢弃。stash 编号会随新存档变化，下一轮必须先用
  `git stash list` 按名称核对，再逐个恢复。
  ⚠️ **以上三份 stash 的描述已于 2026-08-01 作废**：现在只剩 1 份（`0e94dbf`），且那 6 条
  GitHub Release 已提交进版本库、不再依赖任何 stash。以本文件 2026-08-01 段和 `HANDOFF.md`
  「本机保护存档」节为准，本段仅作历史记录。

- **2026-07-18 工作台收藏桥（雷达侧）已合入并推送 `master`**：功能提交为
  `4badc1b 功能：接入工作台收藏桥`，隔离 worktree 为
  `E:\AI-news-reader\ai-news-radar-workbench-bridge`，分支为
  `feature/workbench-collect-bridge`，基线来自 `origin/master` 的 `39375d3`；原工作区的运行数据、
  未跟踪文件和 `stash@{0}` 均未触碰。已实现 iframe 白名单握手、收藏回执配对、卡片收藏按钮及 4 组真实
  iframe E2E；新增桥接 E2E 为 `4 passed`，完整 `npm run test:e2e` 为 `24 passed`，两份 Node 语法检查与
  `git diff --check` 均通过。测试期间临时停止的 `万有 OMNIA 服务` 已恢复运行，8765 端口已由工作台重新监听。
  用户已在 `万有 OMNIA → AI 雷达 → 本机版` 确认卡片显示收藏按钮并通过人工验收；独立打开雷达不显示该按钮是预期行为。
  本轮未改 Python、`.github/workflows/**`、`config/**` 或 `data/**`。下一轮只需在 GitHub Pages 部署完成后，从工作台
  “公网版”确认收藏按钮出现并完成一次真实收藏；若 Pages 未更新，先检查本次推送后的工作流状态。

- **2026-07-16 微信公众号退订历史清理修复已完成线上灰度与真实验收**：代码在独立 worktree
  `E:\AI-news-reader\ai-news-radar-wechat-cleanup`、分支 `fix/wechat-unsubscribe-cleanup` 施工，功能提交
  `fdec276`，合并最新主线后普通推送至 `master`，全程未 force/rebase 覆盖远端。原脏 master、用户
  stash 和本机 `data/**` 未改；当前远端运行模式为 `on`，workflow 已恢复 `active`。
  - **最终业务契约**：sidecar 数据库一次读取后生成 schema 2 权威快照；`known` 是仍存在的非系统
    Feed，`active` 与 `DB.get_all_mps()` 同口径。Feed hard delete 才清对应稳定 `feed_id` 的历史；
    `status=0` 只停采，因 ID 仍在 `known` 中而保留历史。exporter 只消费该权威输入，不再把
    `/rss/fresh` 或 `WE_MP_RSS_FEEDS` 当有效订阅名单。
  - **完整安全门**：manifest、JSONL、订阅快照必须在同一 bridge commit，并通过 schema 2、路径边界、
    哈希、条数、集合和通道状态校验。缺失或非法 `feed_id` 的行在 `RawItem` 前拒绝；无 ID、快照不完整、
    commit 不符、通道失败或任何门控不通过都 fail-safe，一条不删。清理只按 ID，禁止按名称、URL 或
    本轮文章集合推断；回滚只按 `item_id` 精确回插，禁止整份 archive 覆盖。
  - **真实 bridge 与迁移**：bridge commit `2295f32` 发布 schema 2 三件套，60 条文章、known/active=3/3，
    完整哈希链通过。维护窗口基线 `00daa9f` 的 archive 共 625 条、微信 103 条；当时缺 ID 的 43 条全部
    唯一补齐，0 未匹配、0 冲突、0 删除、覆盖率 100%。迁移提交 `b9315ba`，完整 Radar 重建后总数和
    所有通道数量均未下降。
  - **真实灰度结果**：`off` run `29484708544` 确认 103/103 微信记录有 ID、候选/删除 0；`audit` run
    `29484779366` 的 30 个唯一候选只属于 `MP_WXS_3893127105 / 财联社`，异常候选 0；`on` run
    `29484879533` 精确删除这 30 条，archive 625→595、微信 103→73、其它通道下降 0；下一轮 run
    `29484975158` 候选/删除均为 0，财联社未反弹。清理提交为 `399fb67`，清理前回滚基线为 `1f89713`。
  - **自动与浏览器验收**：`test_we_mp_rss_sync_once.py` 17 passed；`test_we_mp_rss_jsonl_source.py`
    22 passed；`test_orphan_subscription_cleanup.py` 20 passed（另 5 subtests）；合并最新主线后全量 pytest
    529 passed、1 warning（另 98 subtests）；PowerShell AST 解析错误 0，`git diff --check` 退出码 0。
    公网页微信公众号栏目显示 73 条、4/4 源正常；搜索财联社为 0，猫笔刀/卡尔的AI沃茨/数字生命卡兹克
    分别有 25/23/25 条可见记录，控制台错误 0。新 worktree 没有独立
    `.venv`，验收从该 worktree cwd 使用原仓库只读虚拟环境
    `E:\AI-news-reader\ai-news-radar-run\.venv\Scripts\python.exe` 执行。
  - **临时 bridge 验收**：文章与快照都不变时不提交；仅快照语义改变时提交；只改 `generated_at`
    不制造提交；`-SkipSync` 不改 HEAD 或正式三件套；三件套同 commit 且全哈希通过；坏 `feed_id`
    行不入 archive；`status=0` 停采留历史；hard delete 只命中目标 ID；精确恢复后新增数据仍保留。
  - **精确回滚**：紧急时把 mode 保持/切回 `off`；代码用正常 revert，不强推、不重写历史；数据恢复
    从 `1f89713` 取本次 30 个目标 `item_id`，用 `scripts/restore_we_mp_cleanup.py` 只补当前 archive 缺失项，
    前后核对 SHA256、总条数和 site_id/source 分布，再重建派生文件。
  - 方案与施工边界：`计划/微信公众号退订后历史消息残留-修复方案.md`。后续 hard delete 会由 `on`
    模式按同一 ID-only 契约清理；`status=0` 仍只停采、不删历史。任何异常先把 Actions 变量切回 `off`。
## GitHub 星标安全同步 V3 与定时自动同步：真实上线完成（2026-07-18）

- 手动 V3、云端定时自动同步及两次线上面板修复均已合并到 `master`；自动同步功能提交为 `699f34a`，随后修复为 `e0c9ca5` 与 `98868a5`。Actions 在每轮采集前同步星标配置，配置变更单独以“配置：GitHub星标自动同步”提交；本机 8092 页面只读本地文件，需拉取后刷新才能显示云端新配置。
- 真实账号 `kunkunzi996`（数字 account id `284580915`）已绑定；当前公开星标 16 个，对应 16 个受管信源，`multica-ai/multica` 已由自动同步新增并启用。最新状态心跳为 `2026-07-18T13:58:59Z` 的 `no_change`。固定门禁仍为单账号、最多 50 个公开星标、第 51 个整次中止、每仓库每 UTC 日最多一个最新 commit 快照。
- §17.2 真实验收已完成：临时取消并恢复 `joeseesun/qiaomu-goal-meta-skill` 星标，停用 operation commit 为 `450d6b5f42fabc11bbd39c4a497f9871d132ccf7`，恢复为 `b8e51e7fa5330ff14d430955145879ed42110e8e`；随后解绑为 `c6643d99e1bb89fece21d74230419891c1cd26de`，重新绑定为 `cb21d9bcb16de63718bc7f0e5f7c026a0ffbaca1`。四个提交都只修改 `config/online-sources.json`，并带有独立 operation trailer。
- 取消星标只自动停用、不删除信源、不触发 pending purge；目标 source id `online_github_repo_1266385233`、repo id `1266385233` 在停用/恢复与解绑/重绑全程稳定，历史仍保留。此前取消星标的 `AlkaidLab/moonlight-harmony` 保持停用且历史仍为 1 条。
- 重新绑定后再次 Preview/Apply 得到 `no_change`：HEAD、配置字节、OPML、`updated_at=2026-07-16T13:26:41Z` 均未变化。最终配置 SHA256 为 `C4B1E08F8D6F2CF61E5986B8BACD5D6F188778FB8984A35172E7111808CF88E8`，OPML SHA256 为 `25A7984823CA46F4591CEC90E23A7707455BE596A882960EF49E0BE962B67058`。
- 公网 Actions 与 Pages 已成功：Update run `29502225101`、Pages run `29502283288`；公网配置/OPML 哈希与本地一致，GitHub 采集状态为 eligible/succeeded 15、failed/deferred 0、fallback 5。
- 自动验收：专项 pytest `344 passed, 91 subtests`；全量 pytest `529 passed, 1 warning, 98 subtests`；Playwright `20 passed`；390/768/1440 mock 浏览器 `6 passed`，0 pageerror、0 console error；编译、Node 语法和 diff 检查通过。真实本地浏览器确认绑定账号和 15 个仓库状态；公网页面在内置浏览器直开时超时，但公网 HTTP、Pages workflow 和本地真实浏览器证据均已通过。
- 用户原有 stash 未改，仍保留 `stash@{0}: On master: 本地刷新生成的 data 快照（可丢弃，下次刷新会重新生成）`。回滚只能对精确 operation commit 使用普通 `git revert <sha>`，一次一个并复核只改配置；禁止 reset、强推或重写历史。

## 更早历史（2026-07-15 及以前）

> 已迁往 `docs/PROJECT_STATE_ARCHIVE.md`（2026-08-01 归档），含「历史入口（2026-07-15）」
> 与「历史状态（截至 2026-07-14）」两节。需要追溯旧决策时去那里查。

## 维护规则

- `PROJECT_STATE.md` 只记录当前状态与最近一周的关键交接。
- 旧状态条目移入 `docs/PROJECT_STATE_ARCHIVE.md`。
- 刷新、采集等操作手册放入 `docs/guides/refresh-playbooks.md`。

# HANDOFF.md

> 跨窗口接力用，只写下一轮必须知道的。长期施工规则在 `CLAUDE.md`，完整状态在 `PROJECT_STATE.md`。

## 抖音风控容错与部分成功发布（BUG-02，2026-08-08，已验收）

- 抖音详情接口偶发风控，原口径「6 个号一条不少才发布」导致 2026-08-05 起**连续 10 轮 failed**、
  桥接停更两天。现已改为：创作者互相隔离、详情退避重试（3 次 / 2s→5s）、回执三态、
  **采到多少发多少**；仅「六个号全失败」才不发布。
- 主线与 NUC 均已部署（验收轮 NUC 为 `44ecd6b`，采集侧代码已就位）。
- **看板黄标含义**：抖音行显示「部分完成」= 本轮被风控少采了几条，属正常自愈范围，
  下轮通常补回；显示「异常」才需要查。缺失明细在 NUC 的
  `logs/bridge-collection-failures.jsonl`（`stage=partial_collection`）。
- **改这块前必读 `CLAUDE.md`「给源状态加字段的必查清单」**——本轮真机验收抓出两个
  「单测全绿但线上不可用」的缺陷（fetcher 两条分支只改一条、`cli.py` 逐字段重构丢字段）。
- **尚未取得的证据**：验收轮 `Argus=0`，「真被风控 → 其余号照采 → 看板变黄」这条链路
  **没有真实现场证据**。下次真碰上风控时，去看板确认抖音行是否变黄即可完成这一验证。

## 采集结束后清理残留标签页（BUG-01，2026-08-08，已验收）

- 主线与 NUC 均已部署本修复；修复提交 `f982675`、合并 `3896552`、验收文档 `e128885`。
  NUC 靠 `RadarAutoFF` 每 10 分钟跟随 `origin/master`，本轮已确认同步成功。
- 采集浏览器现在会在每轮结束时自动关掉**本轮新开的**标签页，日志行是
  `[TabCleanup] closed N leaked tab(s), failed N`。排查内存先看这行在不在。
- **改这块前必读 `CLAUDE.md`「采集浏览器收尾的禁区」**六条，尤其第 1 条：
  不许改成关整个浏览器进程（会丢抖音登录态）。完整方案与放弃理由见 `docs/plan.md`。
- ~~已知未处理：`partial_creator_failure`~~ → **已由 BUG-02 于同日修复验收**，见本文件第一节。
- NUC 远程取证要用 Windows 原生 `ssh.exe`（Git Bash 的 ssh 读不到 ssh-agent），
  且 NUC 的 sshd 默认 shell 是 bash，传 PowerShell 命令要用 `-EncodedCommand`。

## NUC 脏工作区护栏与旧脚本迁移（2026-08-04，已部署并验收）

- 当前主线、`origin/master` 与 NUC `omnia-nuc` 均为 `900c34b`；NUC 运行工作区干净，本地当前仅有本轮文档未提交改动。
- 保存信源与同步线上已是事务流程；失败会回滚或留下可识别错误，不再把半完成状态留在 NUC 工作区。
- `RadarAutoFF` 现在执行 Git 跟踪的 `scripts/windows/auto-ff.sh`：成功记 `event=ff-ok`，失败记退出码、旧/新 HEAD、stderr 摘要和 `reason`。遇到 `worktree_dirty` 只记录，不覆盖采集产物。
- 旧未跟踪脚本已迁移，原件和 `previous-worktree` 副本保留在 NUC `_deploy-backups\auto-ff-migration-20260804` 下，仅作回退依据。
- 验收：NUC auto-ff **4 passed**、保存同步专项 **8 passed**、本地 E2E **31 passed**；API 与人工验收均通过。

## 微信采集后台跨设备访问（2026-08-03，已部署）

- 代码提交 `6202058` 已在 `master`，NUC 已同步运行。
- Cloudflare `omnia-nuc` Tunnel 已追加 `wechat.wanyouomnia.cn -> 127.0.0.1:8001`，DNS 路由已创建；
  原有 `app/radar/collect/calendar` 路由未改。
- NUC `RadarAdminServer` 已加载 `WE_MP_RSS_PUBLIC_ADMIN_URL=https://wechat.wanyouomnia.cn`；
  `OMNIA Staging Tunnel` 和 `RadarAdminServer` 计划任务均处于运行态。
- 公网根页、`/docs` 和真实浏览器登录页均已通过；维护接口已返回正确的本地/公网地址。
- 若再次打不开，先核对 `cloudflared tunnel info omnia-nuc`、`netstat :8001 :8080`、
  `start-server.cmd` 的公开地址行和 `POST /api/maintenance-action` 的返回，不要先改代码。

## 工作台 AI 雷达配置页来源校验修复（2026-08-03）

- 修复提交 `f7b2241` 已合入 `master`；当前主线与 NUC 部署点为 `900c34b`。
- 根因是工作台 iframe 的 `Origin/Referer` 可能来自雷达域名或工作台域名，而 NUC 只信任
  GitHub Pages；服务端现已规范化带路径/query 的 Referer。NUC 白名单为
  `https://kunkunzi996.github.io`、`https://radar.wanyouomnia.cn`、`https://app.wanyouomnia.cn`。
- `tests/test_local_server.py` **155 passed**，`py_compile`、`git diff --check` 通过；公网 API 返回
  200、线上信源 53 条，用户已实际修改信源成功。
- 下一轮入口：若再次出现配置页加载失败，先核对 NUC `start-server.cmd` 的三项白名单、
  `RadarAdminServer` 日志和 `/api/online-source-config` 的 HTTP 状态，不要先改 iframe 传参。

## GitHub 重大更新筛选与 NUC 同步（2026-08-03）

- GitHub 重大更新过滤已合入 `master`：功能合并提交 `2249cc7`，历史归档展示修复合并提交
  `53378af`；随后数据快照继续推进，当前 `master` / `origin/master` 为 `900c34b`。
- NUC `omnia-nuc`（`DESKTOP-H9RAKEH`）已部署并继续快进到 `900c34b`。NUC 专项
  `pytest -q tests/test_topic_filter.py` 为 **112 passed**；本机管理服务 `8080`、公网管理后台和
  GitHub Pages 均返回 HTTP 200。
- `scripts/windows/auto-ff.sh` 已在 2026-08-04 纳入 Git 跟踪；旧脚本原件和 `previous-worktree` 副本
  仅作为回退备份保留，不删除、不覆盖。采集任务每次启动时加载过滤代码，管理服务当前正常。
- 下一轮入口：若发现 NUC 不再跟随主线，先在 NUC 核对 `git status --short`、
  `git ls-remote origin refs/heads/master` 和 `logs/auto-ff.log`，根据结构化 `reason` 定位；
  不要用 reset、强推或手工覆盖 `data/**` 代替诊断。

## 更早的交接记录

2026-08-02 及以前的交接条目已归档到 `docs/HANDOFF_ARCHIVE.md`
（2026-08-08 洁癖门归档，逐行搬迁未删减）。本文件只保留最近一周与仍然生效的实测事实。

## 本机保护存档（2026-08-01 实测订正，以本节为准）

**当前实有 1 个 stash**，不是旧文档说的两份或三份：

- `stash@{0}` = `0e94dbf`「On master: 收尾前保护：本机旧数据与临时文件（2026-07-18）」：
  旧数据快照、临时截图和实测脚本。不要整批恢复、提交或丢弃；需要时只按单个文件恢复并重新评估。
  （它就是旧清单里的 `stash@{1}`；`stash list` 曾因 reflog 丢失而显示为空，reflog 已手工重建。）

以下两条**旧记载已作废**，下一轮不要再去找它们：

- ~~`stash@{0}`：本轮同步前的本机数据、配置和计划草稿保护存档~~ —— 已不存在。
- ~~`stash@{2}`（原 `a8d0acd`）：包含工作区已缺失的 6 条 `github_foundation_sunshine_releases`
  历史，是唯一备份，严禁丢弃，是否恢复待定~~ —— 该 stash 已不存在（`git fsck --unreachable
  --no-reflogs` 的 60 个不可达 commit 里也没有任何 stash 型 commit），**但那 6 条数据没丢**：
  已提交进版本库（工作区 / HEAD / `origin/master` 三处 `data/archive.json` 实测均为 6 条），
  完整 70 条在 `d85b916^`。「待用户决定是否恢复」这个悬案就此关闭。

## 下一轮入口

1. 先运行 `git status --short --branch` 和 `git stash list`，确认主线和**那 1 份**保护存档在
   （见上节订正；`stash list` 若又显示为空，先查 `.git/logs/refs/stash` 是否丢失，别当数据没了）。
2. 改历史清理逻辑前，先读 `CLAUDE.md` 的“清理历史条目的禁区”；任何无法证明名单、身份与文件同源的情况都不能删除数据。
3. 改线上同步逻辑前，先读 `CLAUDE.md` 的 Git 编排禁区；恢复工作区只允许 `git restore`，不能用 `git checkout`。
4. 新增本机维护按钮前，先读 `CLAUDE.md` 的派发禁区；常驻按钮不能依赖“故障时才出现”的维护项。
5. 已清理 `agent/online-source-sync-20260720` 在内的 12 个已合并本地分支；
   `E:\AI-news-reader\ai-news-radar-online-source-sync` 的 Git worktree 登记也已移除。该路径目前只剩被
   `pwsh.exe` 占用的空目录，不能强删；关闭占用它的终端后再手动移除即可。
6. `backup/local-opml-trigger-20260709-80fe98f` 与 `fix/online-sync-directed-stash-restore` 未合入主线，
   必须保留。`E:\AI-news-reader\ai-news-radar-github-stars-integration` 仍有未提交改动，严禁删除；已合并的
   `feature/local-trigger-console` 与 `fix/wechat-unsubscribe-cleanup` 远端分支已于 2026-07-20 删除。
7. 本轮状态与交接文档已经完成收口；无需重复执行微信看门狗、GitHub 星标自动同步施工或线上面板修复。
8. 2026-07-22 洁癖门已完成状态同步；未执行终态删除。根目录的 `AGENTS.md`、`.agent_context/`、
   `.multica/` 是 Multica 运行时生成状态，不能手工编辑或提交。根目录的同名 WS-3 计划书与 `计划/`
   正文逐行一致，哈希差异仅来自换行符；仍须由用户确认后才可按单一路径删除。已合并 feature worktree、分支、patch 和旧虚拟环境仅是
   终态清理候选，须由用户逐路径确认后才能处理。

# HANDOFF.md

> 跨窗口接力用，只写下一轮必须知道的。长期施工规则在 `CLAUDE.md`，完整状态在 `PROJECT_STATE.md`。

## 当前状态（2026-07-29）

- **远程管理后台功能已提交在 `feature/remote-admin-console`（提交 `d67ba93`），未合入 master、未推送。**
  合并前注意：(1) 本机 git 环境间歇性吞 ref 写入，合并/推送操作若异常，手工钉 ref
  （提交对象本身在 odb 中持久）；(2) 合并后推送 master 会自动部署 Pages 新前端（无配置时
  对访客零影响）；(3) NUC 部署清单见 `计划/2026-07-29-订阅源管理合并入公网页面实施计划.md`
  阶段 5：pull、生成 48 位令牌、建 `RadarAdminServer` 计划任务、cloudflared 命名隧道
  指到回环 8080、用户浏览器完成一次 `cloudflared tunnel login` 授权、按阶段 5 第 4 条
  做公网带令牌/无令牌/私密文件 404 三项验证。(4) NUC 上先确认 git 无本机的
  `refs/remotes` 不落盘问题（`git fetch` 后 `git for-each-ref refs/remotes/` 非空即正常）。
- 本机 84 个 git 事务测试失败为环境问题（未改动 HEAD 基线同挂，清单与功能分支完全一致），
  不是本功能引入；如需恢复本地测试环境，排查 git 2.54.0.windows.1 的 ref 写入。

## 当前状态（2026-07-26）

- **NUC 迁移已完成，后续不要重复阶段 1-6**：NUC 为唯一启用采集节点；`DouyinCollectAndPush` 保持每日
  `08:10 / 13:10 / 20:10`、`Interactive` 与 `IgnoreNew`。 `18:00`、`18:15` 两次真实计划触发均成功，
  抖音两轮 `4/4` 完成、失败 `0`，微信两轮成功；最终两个 Bridge 均为干净的 `main`，且与实时远端一致。
  NUC 的 `WechatHealthWatchdog` 已迁移为每小时只读检查，阶段 6 回读为 `Ready`。
- **观察期由用户明确跳过**：旧电脑的 `DouyinCollectAndPush`、`LaunchDouyinGuard`、
  `WechatHealthWatchdog` 保持停用但不删除；旧数据、浏览器环境、Bridge 工作区和任务定义均保留作回退。
  故障时不得用旧历史覆盖 Bridge，先核对远端最新提交再决定恢复节点。
- **历史记录（2026-07-24，已闭环）**：NUC 迁移当时尚未完成，目标根目录为 `C:\AI-news-reader`。五个仓库均已恢复或克隆，
  三套 Python 环境、Playwright WebKit/Chromium、两个 Bridge 的 GitHub 读取和 dry-run 写权限均已验收。
  `we-mp-rss-sidecar` 正在 `127.0.0.1:8001` 运行；用户已完成扫码，订阅列表有内容且刷新后登录仍保持。
- **历史记录（2026-07-24，已闭环）—抖音登录与 Bridge 前置门**：专用 Chrome 当时监听 `127.0.0.1:9333`，独立 profile 位于
  `C:\AI-news-reader\MediaCrawler-local-test\chrome-profile`，直接检测为 `logged_in`。NUC 的
  `douyin-bridge` 已从 `bb15b6d` 快进到当时远端 `5420d632`，TREE 为 `7fd8088c`，工作区干净、fsck
  成功。当时旧电脑任务仍会继续推新提交，所以该 HEAD 只能作为历史基线；旧电脑任务现已停用，当前以 NUC
  Bridge 的实时远端为准。
- **历史记录（2026-07-24，已闭环）**：首次真实抖音采集当时尚未进入可验收状态；命令被记录为已调用，但终端没有捕获退出码，状态文件未生成；
  随后确认无采集进程、无锁、无输出、Bridge 无变化、没有 commit/push。按脚本实现，状态文件应在读取
  配置、启动浏览器和联网前写出，因此问题位于子 PowerShell/脚本加载或极早期初始化，不能归因于采集器。
  当时明确禁止直接重试，先执行下面的只读诊断；后续两次成功计划运行已完成验收，不要再重复该诊断。

- **WS-3「线上信源自动合并同步」已合入、部署并闭环**：功能提交 `17a6e50` 经 PR #9 合并提交
  `18b1f07` 进入 `master`，当前主线 `7efa8bf` 与 `origin/master` 一致。实现按稳定 `source.id`
  进行 B/L/R 三方合并，安全时先推远端提交再把本机 L 一步检出为 M；冲突、恢复、stash 与未跟踪
  `data/**` 碰撞均 fail-safe。自动验证为 local-server 134 passed、online-source 94 passed，20 个
  冻结剧本与两条真实浏览器路径已通过；合并后的 GitHub 星标自动同步和 Pages 均正常。后续不应重复
  施工该功能；三个小体验项（冲突折叠提示、分类标签、英文内部码）由用户明确暂不处理。

- **2026-07-20 GitHub 取消星标联动清历史 V2.1 已完成施工并合入主线**：工作区
  `E:\AI-news-reader\ai-news-radar-unsubscribe-purge-github`，分支
  `feature/unsubscribe-purge-github`，基线 `58b64c8`。实现了稳定 `github_repo_identity` 清理、两个不同
  run 的非空完整快照确认、`github-star-purge-state.json` 与 autosync SHA256 配对、`off/audit/on` 一次性
  摘要、只读审计和按 `record.id` 精确恢复；没有改动其它通道、前端、依赖或线上变量。验收为专项 89 passed、
  GitHub 相关兼容测试 28 passed、完整 pytest `600 passed, 1 warning, 109 subtests passed`、`py_compile`、
  `git diff --check` 和本地只读 audit。当前 audit 因没有本轮 Actions 身份/状态配对而安全地产生 0 候选。
  功能提交 `a16f81a` 已由 `ef4ddf2` 合入 `master`；线上仍保持 mode=off，等待两轮完整同步，再按计划人工
  audit 和 on。

- **线上信源合并与停用联动已完成并验收**：功能提交 `b94039e` 已由 PR #7 的合并提交 `db47d62` 纳入
  `master`。它保留云端新增的 GitHub 信源，同时保留“中二的大暄哥”的停用，并在清理历史后同步更新展示
  数据和统计字段。用户已完成实际验收；主工作区已快进至 `9f3ea85`，当前配置有 17 个 GitHub 受管源。

- 主工作区：`E:\AI-news-reader\ai-news-radar-run`，分支 `master`（当前 `7efa8bf`，与
  `origin/master` 一致）。云端 Actions 会持续写入
  `data/**` 快照；下一轮先用 `git status --short --branch` 确认本地与 `origin/master` 一致。四份本地计划草稿
  已与云端受管版本逐字一致，不再是未跟踪文件。
- 微信采集健康看门狗和 MeoW 告警已合入 `master`（`b2a8614`），手机触达与真实采集均已验收。该计划任务
  已迁移至 NUC，`WechatHealthWatchdog` 每小时只读检查；旧电脑同名任务已停用并保留作回退。
  后续改动必须保持其不启动/停止采集、不改新闻数据的边界，且不得提交
  `local-secrets/meow-push.json` 或工作区外的运行状态、日志文件。除非修改告警配置或计划任务，否则无需重复做真实验收。
- 已上线且无需重复施工：微信公众号按稳定 `feed_id` 清理退订历史、GitHub 星标安全同步 V3、工作台收藏桥。
  工作台收藏桥仅剩 GitHub Pages 部署后在工作台“公网版”完成一次真实收藏确认。
- GitHub 星标定时自动同步已于 2026-07-18 完成、合入并推送 `master`：每轮 Actions 采集前自动同步
  已绑定账号的公开星标；新星标自动新增、取消星标自动停用但不删历史。真实手动工作流已新增
  `multica-ai/multica`，后续定时轮次记录为 `no_change`（16 个公开星标）。本机 8092 页面不会被
  云端提交实时推送，拉取最新主线后刷新页面即可看到新信源。

## NUC 迁移历史入口（已完成，仅供追溯）

> 下面的诊断步骤是 2026-07-24 的历史过程记录；以本文件顶部的完成结论为准，不要再次执行。

1. 使用 `kun-coding-router`，本轮先按“Bug 诊断 / 部署中”处理；不要创建分支，不改代码，不重跑采集。
2. 在 NUC 只读核对 `collect-douyin-and-push.ps1`：预期 Windows 工作树文件为 21,332 字节、SHA-256
   `07B54CB4EDC6184B16039AAD24C188F15727A6864515A9DE2392EC9625B13122`，HEAD blob 为
   `9a308ba2a6be9ae1cab7f3883db5660bf956880c`；PowerShell Parser 应为 0 错误，且 10 个参数齐全。
3. 用无副作用子进程 `exit 37` 验证父终端能得到 `CHILD_EXIT_MARKER=37`；只看元数据或布尔值检查
   `douyin-collect.log`、状态文件临时痕迹、`%TEMP%` 下 owner/lock，以及上次实际命令是否用了反引号多行
   续行。禁止回显原始日志、Cookie、账号 ID 或作品正文，也禁止删除任何痕迹。
4. 只有诊断证明脚本和退出码通道正常后，才准备第二次采集。重试前必须重新查询 Bridge 实时远端；若旧电脑
   已推新提交，只允许 `git pull --ff-only`。正式重试必须是一整行命令，不含反引号续行、`Start-Process`、
   后台任务或复合前置包装；手动首跑仍不加 `-BrowserOffscreen`。
5. 抖音成功门：本轮新状态为 `succeeded / exit_code=0 / login_state=logged_in`，requested/completed=4、
   failed=0、4 条回执完整、`output_rows>0`；`new_unique_items=0` 允许。Bridge 最终必须干净且本地/实时远端
   HEAD 一致；若内容没变，`completed_no_change` 也是采集成功，但真实 push 路径仍记为未触发。
6. 抖音通过后再依次做：Actions 与公网页面冒烟、微信手动采集及 `wechat-bridge` 推送、按
   `C:\AI-news-reader` 重建计划任务。旧电脑的 `DouyinCollectAndPush`、`WechatHealthWatchdog` 和抖音 guard
   当前仍保留；NUC 全链路通过后只停用、不删除。避免在 `09:45-10:15`、`14:45-15:15`、
   `22:45-23:15` 启动 NUC 真实采集。

## 本机保护存档

- `stash@{0}`：本轮同步前的本机数据、配置和计划草稿保护存档；计划书已与当前受管版本一致，数据和配置
  也已由云端严格包含，但该存档仍不要自动丢弃。
- `stash@{1}`（原 `0e94dbf`）：旧数据快照、临时截图和实测脚本。不要整批恢复、提交或丢弃；需要时只按
  单个文件恢复并重新评估。
- `stash@{2}`（原 `a8d0acd`）：包含工作区已缺失的 6 条 `github_foundation_sunshine_releases` 历史，
  是唯一备份，**严禁丢弃**。是否精确恢复到 `data/archive.json` 仍待用户决定。

## 下一轮入口

1. 先运行 `git status --short --branch` 和 `git stash list`，确认主线和两份保护存档都在。
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

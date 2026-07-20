# HANDOFF.md

> 跨窗口接力用，只写下一轮必须知道的。长期施工规则在 `CLAUDE.md`，完整状态在 `PROJECT_STATE.md`。

## 当前状态（2026-07-20）

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

- 主工作区：`E:\AI-news-reader\ai-news-radar-run`，分支 `master`。云端 Actions 会持续写入
  `data/**` 快照；下一轮先用 `git status --short --branch` 确认本地与 `origin/master` 一致。四份本地计划草稿
  已与云端受管版本逐字一致，不再是未跟踪文件。
- 微信采集健康看门狗和 MeoW 告警已合入 `master`（`b2a8614`），手机触达与真实采集均已验收。计划任务
  `WechatHealthWatchdog` 每小时只读检查；后续改动必须保持其不启动/停止采集、不改新闻数据的边界，且不得提交
  `local-secrets/meow-push.json` 或工作区外的运行状态、日志文件。除非修改告警配置或计划任务，否则无需重复做真实验收。
- 已上线且无需重复施工：微信公众号按稳定 `feed_id` 清理退订历史、GitHub 星标安全同步 V3、工作台收藏桥。
  工作台收藏桥仅剩 GitHub Pages 部署后在工作台“公网版”完成一次真实收藏确认。
- GitHub 星标定时自动同步已于 2026-07-18 完成、合入并推送 `master`：每轮 Actions 采集前自动同步
  已绑定账号的公开星标；新星标自动新增、取消星标自动停用但不删历史。真实手动工作流已新增
  `multica-ai/multica`，后续定时轮次记录为 `no_change`（16 个公开星标）。本机 8092 页面不会被
  云端提交实时推送，拉取最新主线后刷新页面即可看到新信源。

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
5. `E:\AI-news-reader\ai-news-radar-online-source-sync` 的分支已合入且工作区干净，可作为删除候选；
   但必须由用户按明确路径确认后再删除。`E:\AI-news-reader\ai-news-radar-github-stars-integration` 仍有未提交
   改动，严禁删除。
6. 本轮状态与交接文档已经完成收口；无需重复执行微信看门狗、GitHub 星标自动同步施工或线上面板修复。

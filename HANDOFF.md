# HANDOFF.md

> 跨窗口接力用，只写下一轮必须知道的。长期施工规则在 `CLAUDE.md`，完整状态在 `PROJECT_STATE.md`。

## 当前状态（2026-07-18）

- 主工作区：`E:\AI-news-reader\ai-news-radar-run`，分支 `master`。当前基线为
  `da4250b`，与 `origin/master` 一致；本次收尾只会提交已核实的状态文档，计划草稿保持未跟踪。
- 已上线且无需重复施工：微信公众号按稳定 `feed_id` 清理退订历史、GitHub 星标安全同步 V3、工作台收藏桥。
  工作台收藏桥仅剩 GitHub Pages 部署后在工作台“公网版”完成一次真实收藏确认。
- GitHub 星标定时自动同步已于 2026-07-18 完成、合入并推送 `master`：每轮 Actions 采集前自动同步
  已绑定账号的公开星标；新星标自动新增、取消星标自动停用但不删历史。真实手动工作流已新增
  `multica-ai/multica`，后续定时轮次记录为 `no_change`（16 个公开星标）。本机 8092 页面不会被
  云端提交实时推送，拉取最新主线后刷新页面即可看到新信源。

## 本机保护存档

- `stash@{0}`（`0e94dbf`）：同步前的旧数据快照、临时截图/实测脚本及未提交历史计划文件。不要整批恢复、
  提交或丢弃；需要时只按单个文件恢复并重新评估。
- `stash@{1}`（`a8d0acd`）：包含工作区已缺失的 6 条 `github_foundation_sunshine_releases` 历史，
  是唯一备份，**严禁丢弃**。是否精确恢复到 `data/archive.json` 仍待用户决定。

## 下一轮入口

1. 先运行 `git status --short --branch` 和 `git stash list`，确认主线和两份保护存档都在。
2. 改历史清理逻辑前，先读 `CLAUDE.md` 的“清理历史条目的禁区”；任何无法证明名单、身份与文件同源的情况都不能删除数据。
3. 改线上同步逻辑前，先读 `CLAUDE.md` 的 Git 编排禁区；恢复工作区只允许 `git restore`，不能用 `git checkout`。
4. 新增本机维护按钮前，先读 `CLAUDE.md` 的派发禁区；常驻按钮不能依赖“故障时才出现”的维护项。

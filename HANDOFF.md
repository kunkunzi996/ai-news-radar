# HANDOFF.md

> 跨窗口接力用，只写下一轮必须知道的。长期施工规则在 `CLAUDE.md`，完整状态在 `PROJECT_STATE.md`。

## 当前状态（2026-07-18）

- 主工作区：`E:\AI-news-reader\ai-news-radar-run`，分支 `master`。已从 `853e6f4` 快进到
  `1757d34`，本次收尾文档提交后应保持与 `origin/master` 一致、工作区干净。
- 已上线且无需重复施工：微信公众号按稳定 `feed_id` 清理退订历史、GitHub 星标安全同步 V3、工作台收藏桥。
  工作台收藏桥仅剩 GitHub Pages 部署后在工作台“公网版”完成一次真实收藏确认。
- 未开始的 GitHub 星标定时自动同步只有本地施工草案，未审查、未提交、未实施；要做时必须从最新
  `origin/master` 新建独立 `feature/` 工作树，不能在主工作区直接施工。

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

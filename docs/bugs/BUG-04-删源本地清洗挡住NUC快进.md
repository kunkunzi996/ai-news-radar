# BUG-04: 删源的本地清洗弄脏 NUC 工作区，radar.wanyouomnia.cn 停更 13 小时

状态：**已修复，待部署与用户验收**（2026-09-12）
修复分支：`fix/nuc-data-ff-stale`（补丁随工作台 PR #94 的任务文档交付）

## 现象

工作台网页原生雷达左下角「更新时间」停在 09/11 17:03，采集状态胶囊却是 09/12 01:07 那一版。
云端 GitHub Actions 全程正常，每半小时一版；GitHub Pages 副本是新的，只有 NUC 源站旧。

## 根因（第一性原理）

- `radar.wanyouomnia.cn` 由 NUC `local_server.py` 直接供出 `data/**`，`data/**` 是 Actions 提交的成品，NUC 靠 `RadarAutoFF`（`git merge --ff-only origin/master`）跟随。
- 09/11 17:28 起用户删了 6 个源。每次「保存并同步」里 `purge_deleted_source_data` **就地改写** NUC 本地的 5 个 `data/*.json`，剔掉被删源的条目；这些路径不在同步允许提交的范围内，成为未提交改动。
- `merge_sync` 把脏文件 stash → 合并 `origin/master` → 提交推送 → `git restore --source=<stash>` **把合并前的旧列表盖回**合并后的新数据。`source-status.json` 没被本地改过、不在 stash 里，所以是新的；列表是旧的。
- 之后 `auto-ff.sh` 每次 `--ff-only` 都被脏文件挡住，按设计只记 `worktree_dirty` 退出。每次再删源又盖一遍，永不自愈。
- 底层事实：**清理结果以未提交改动的形式躺在 Git 跟踪、云端每半小时覆写的文件里，"删源"和"跟随云端"就是互斥的。** 不是参数问题，是清理放错了地方。

## 修法

- 新增 `scripts/radar/deleted_sources.py`：台账挂在 `config/online-sources.json` 顶层 `deleted_sources`（`site_id → {token → 删除时刻}`），token 口径与本地清理一直用的一样（抖音 / B 站 / 油管稳定 ID，其它按显示名）。
- 保存时服务端把这次删掉的源登记进台账，随配置一起提交推送（不新增文件，不动 git 事务台账）；源加回则划掉，老过 30 天划掉。`merge_sync` 两边台账并集。
- Actions 管线 `prepare_run_context` 在既有「第二层清理」之后按台账剔除归档，结果写进 `source-status.json` 顶层 `deleted_source_cleanup`。
- 本机不再改写 `data/**`：`purge_deleted_source_data` / `flush_pending_purge` / `pending-purge.json` 全部拆除；「清理已退订历史」入口改为登记台账 + 同步；保存响应沿用前端认识的 `{"deferred": {...}}` 形态，提示「将在本次采集结束后清理」。
- 事务快照 `SAVE_SYNC_FILE_PATHS` 只剩配置与 OPML 两个文件。
- `auto-ff.sh` 连续 3 次失败写 `event=alert`；`scripts/windows/check-radar-freshness.sh` 比本地与 `origin/master` 的 `generated_at`，超 90 分钟记 `stale`。
- `config/online-sources.json` 已预填 09/11～09/12 删掉的 6 个源，云端下一轮即把仍留在归档里的 23 条博客条目剔掉。

## 部署

1. NUC `C:\AI-news-reader\ai-news-radar-run`：确认 `logs/auto-ff.log` 末行 `reason=worktree_dirty`、脏文件全在 `data/`、没有恢复台账，然后 `git restore --worktree -- data/` + `git fetch origin && git merge --ff-only origin/master`。
2. 合并本分支到 `master` 后，Actions 的 `[push]` 一轮会按台账重写 `data/**`；`RadarAutoFF` 十分钟内跟上。
3. 重启 8080 本机服务（`local_server.py` 有改动）。
4. 网页里删一个源、加回一个源、点一次「删除选中的历史」，核对 `config/online-sources.json` 的 `deleted_sources`、`git status -- data/` 为空、下一轮云端 `source-status.json` 的 `deleted_source_cleanup`。

## 验收（待填）

| 层 | 验收项 | 结果 |
|---|---|---|
| 本机 | 删源后 `git status --porcelain -- data/` 为空 | |
| 本机 | `RadarAutoFF` 下一轮 `ff-ok` | |
| 云端 | `source-status.json.deleted_source_cleanup.removed_total` = 23 | |
| 站点 | `radar.wanyouomnia.cn` 与 GitHub Pages 的 `generated_at` 同一轮 | |

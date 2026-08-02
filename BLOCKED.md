# 阻塞与待确认

## E2E 基线差异

- 任务说明给定基线为 `20 passed、3 failed、3 did not run`；首次执行得到 `19 passed、4 failed、3 did not run`，复验得到 `20 passed、3 failed、3 did not run`。
- 当前已知失败：两个 `tests/e2e/github-stars-sync.spec.js` 用例等待缺失的 `#onlineSourceSyncBtn`；工作台桥接用例提示本机 `8765` 端口已被占用。
- 首次执行中 `tests/e2e/layout-timeline.spec.js:429` 的 `81 条`/`0 条`差异在复验未复现；本任务不修复 E2E 红灯、不改测试或业务代码。

## 已确认纳入本次提交

- `计划/2026-07-26-AI看板采集节点迁移至NUC实施计划.md`：保留、未忽略，用户已确认纳入版本库。
- `计划/2026-07-29-远程管理后台部署-handoff.md`：保留、未忽略，用户已确认纳入版本库。

## 本任务记录（2026-08-02）

- 本任务无新增阻塞。

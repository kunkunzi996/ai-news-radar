# NUC 信源保存同步事务护栏设计

## 1. 背景与问题

工作台的“保存信源”目前是两个 HTTP 请求：先写本地配置，再提交并推送线上配置。保存阶段还可能改写 `data/**`，并登记本机采集。若第二步因为远端冲突、推送竞态或 Git 环境故障失败，第一步已经留下的配置、OPML、待清理台账或历史数据不会完整恢复，NUC 工作区因此变脏。`auto-ff.sh` 又吞掉了合并失败的 stderr，只记录一个没有原因的 `skipped`，导致问题只能靠事后猜测。

现有 `scripts/radar/server/online_sources.py` 已有 `manual_save` 操作台账和精确恢复能力，但保存成功后会立即删除台账，无法覆盖“保存完成、同步失败”的完整事务。

## 2. 目标

1. 工作台保存按钮走一次“保存并同步”事务；远端预检失败时，本地零写入。
2. 本地写入后同步失败时，恢复本次操作触碰的配置、OPML、数据和待清理台账；不覆盖用户原有的其它脏文件。
3. 只有远端推送成功后，才清理事务台账、派发新增桥接信源采集，并向前端报告成功。
4. `auto-ff.sh` 记录 fetch、快进合并的退出码、stderr 摘要、旧/新 HEAD 和明确失败原因。
5. 用回归测试锁住远端冲突、推送竞态、保存写盘失败、连续保存同步和自动快进失败的行为。

## 3. 非目标与边界

- 设计阶段（部署前）不修改 NUC 当前运行分支，也不触碰其未跟踪的 `scripts/windows/auto-ff.sh`；本轮设计只修改仓库中的代码和测试。部署替换已另行确认并完成旧脚本迁移，当前事实见 `PROJECT_STATE.md`。
- 不把运行时 `data/**`、日志、凭据或 Cookie 放入功能提交。
- 不改变“删除信源时清理本地历史”的既有业务口径；本轮只保证失败时可恢复，成功后的历史清理仍由现有清理函数负责。
- 不使用 `git reset --hard`、`git clean`、`pull --rebase --autostash` 或 `git checkout` 恢复文件；恢复继续使用现有 `git restore` 和台账 proof 机制。
- 不改 Actions 的数据提交契约，不让本地配置同步直接强推或覆盖远端数据。

## 4. 事务设计

### 4.1 请求边界

新增本地接口 `/api/save-and-sync-online-source-config`，接收现有配置 JSON 和 `If-Match`。前端保存按钮改为调用该接口；已有只读配置接口和“单独同步”接口保留，供兼容调用和故障恢复使用。

后端复用现有 `save_and_sync_online_source_config()`，但把它改成真正的事务编排：

```text
校验 If-Match 与 payload
  -> 读取当前配置并生成候选配置/OPML（内存）
  -> Git 远端预检（不写业务文件）
  -> 建立 manual_save 事务台账（记录文件 before/after 摘要）
  -> 写配置与 OPML，并校验写后摘要
  -> 执行现有 purge / pending-purge 逻辑
  -> 提交并推送
  -> 推送成功后清理台账、刷新待清理结果、派发 pending collect
```

### 4.2 预检门禁

- 预检必须在写 `config/online-sources.json`、`feeds/online-sources.opml` 和 `data/**` 之前完成。
- 预检沿用 `_manual_sync_git_preflight()`：检查暂存区、未完成 Git 操作、已有恢复台账、远端快进关系以及远端提交路径。
- 远端出现非允许路径、历史分叉、已有恢复任务或预检不可用时，返回现有错误体系中的明确 reason；候选配置、OPML、数据、`HEAD`、stash 和 index 均保持原样。
- 预检完成后到实际 push 前仍需保留 CAS/HEAD 校验，防止远端在预检后再次前进。

### 4.3 台账与回滚

- 沿用 `manual_save` 台账格式，增加“事务尚未推送”的状态标记，不另建第二种恢复格式。
- 台账记录线上配置文件、OPML 和本次 purge 可能触碰的受控数据文件的 before/after SHA-256；记录 `HEAD`、暂存区状态和 pending-purge 原始状态。
- 任一写入、清理、commit、push 或写后校验失败时，只在 proof 仍匹配、HEAD 未被外部改变、暂存区没有无关改动的前提下执行精确回滚。
- 回滚使用 `git restore --source=<pre_head> --staged --worktree -- <受控路径>`，并按台账恢复未跟踪的 pending-purge 文件；用户原有的其它 `data/**` 脏文件不纳入恢复范围。
- 回滚自身无法证明安全时，不强行覆盖文件，保留恢复台账并返回 `recovery_pending`，让已有恢复接口接管。

### 4.4 成功与失败响应

- 只有 push 成功后才返回 `ok: true`，并返回最终 `etag`、commit、purged summary 和 auto-collect summary。
- 预检或事务失败返回可识别的 error code/reason；前端不把 `onlineSourceDirty` 误清为 `false`，而是重新读取当前配置并显示失败原因。
- 兼容保留现有 `/api/online-source-config` 保存接口，但工作台默认路径不再用它承担“保存后再同步”的半事务流程。

## 5. auto-ff 可观测性

仓库版本的 `scripts/windows/auto-ff.sh` 改为分别记录：

- fetch 失败：命令、退出码、stderr 摘要；
- `merge --ff-only` 失败：旧 HEAD、远端 HEAD、退出码、stderr 摘要和分类 reason；
- 成功：旧 HEAD、新 HEAD、耗时和 `ff-ok`；
- 日志单行长度受限，不写 token、Cookie 或完整敏感 URL。

NUC 当前未跟踪脚本不在本轮直接覆盖；部署阶段必须单独确认替换方案。

## 6. 测试与验收

### 后端回归

在 `tests/test_local_server.py` 和 `tests/test_online_sources.py` 增加：

1. 远端非 `data/**` 提交：保存接口在写文件前失败，配置、OPML、数据、HEAD、stash、index 全部不变。
2. 保存写盘失败：事务台账可自动回滚，pending-purge 与历史数据字节不变。
3. 远端在预检后前进：push CAS 失败，事务自动回滚，不留下半成品台账或脏线上文件。
4. 同步失败后再次保存：第二次操作不继承第一次的配置、台账或 purge 状态。
5. 推送成功：台账被删除，已有 purge/auto-collect 顺序保持“推送后派发”。

### 脚本与前端

- 对 `auto-ff.sh` 使用临时 Git 仓库覆盖成功、非快进、fetch 失败三种路径，断言日志含明确 reason 和退出码。
- 修改 `assets/js/**` 后运行项目要求的 `npm run test:e2e`。
- 修改 `scripts/**` 后运行项目已有 Python 检查、相关 pytest、`py_compile` 和 `git diff --check`。

## 7. 交付顺序

1. 先提交本设计稿。
2. 施工后端事务与回滚，再改前端保存请求和错误状态。
3. 补自动快进日志及回归测试。
4. 在本地分支完成两轮验证；本轮不部署 NUC、不替换其未跟踪脚本。


# merge_sync 专属禁区（详细契约）

> 本文是 `CLAUDE.md`「同步线上（sync_online_source_config）的 git 编排禁区」的展开。
> **普通同步的 4 条禁区仍在 `CLAUDE.md` 正文**；本文只装 `operation_kind=merge_sync`
> 这条并列事务的逐条契约——只有改合并同步路径时才需要逐条对照。

当云端信源文件也已变更时，`operation_kind=merge_sync` 是与普通同步并列的事务，必须同时满足：

1. 合并结果 M 的 GitHub 星标受管投影必须与云端 R 完全相等；本机不能覆盖云端受管状态。
2. 必须先推送合并提交 C，成功后才能以 CAS 移动本机 `master`；推送失败时本机 HEAD、信源文件和 stash 均不得前进。
3. 合并同步路径永远不得调用 purge 或改写 `data/archive.json` 历史。
4. 台账中 `files.before_sha256` 永远描述本机候选 L，不能改写成云端基线 B 或 R。
5. 每个恢复点在写盘、移动 ref 或删台账前都必须先核对台账摘要、文件 SHA256、HEAD 与 stash 归属；无法证明时保持 pending。
6. 两个信源文件只能从 L 单向一步到 M；任何先退回 B、`git merge --ff-only` 或让用户短暂看到基线的中间态都是缺陷。
7. 以 `git restore` 检出 C 中的路径前，未跟踪 `data/**` 碰撞预检是防止静默覆盖的必需门禁，必须在推送前和实际检出前各执行一次。

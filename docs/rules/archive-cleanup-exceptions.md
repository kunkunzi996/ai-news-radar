# 归档清理的两个窄例外（详细契约）

> 本文是 `CLAUDE.md`「清理历史条目的禁区」的展开。**通用红线（1~5 条）仍在 `CLAUDE.md` 正文，
> 那五条任何时候都生效**；本文只装两个窄例外的逐条契约——改微信清理或 GitHub 星标清理代码时
> 必须逐条对照，其它情况不需要读。
>
> 前提：除下述两个窄例外外，能删 `data/archive.json` 历史条目的**只有**「保存/同步信源配置」
> 这一条路径。

## 微信公众号 schema 2 清理窄例外

`we_mp_rss_jsonl` 允许在采集管线内清理历史，但这不是通用通道规则，只能同时满足以下条件时启用：

1. 清理身份只能使用稳定 `we_mp_feed_id`。禁止按来源名称、URL 前缀、本轮文章集合或 active 采集范围
   猜测删除对象，也禁止把微信加入 `ENUMERABLE_SUBSCRIPTION_SITE_IDS` 或把本例外类推到其它通道。
2. 只有 sidecar 数据库中的 Feed 被 **hard delete**，即其 ID 不再出现在 schema 2 快照 `known` 中，
   才能成为候选；`status=0` 只是不在 `active` 中、仍在 `known` 中，必须停采但保留全部历史。
3. manifest、JSONL、订阅快照必须属于同一 bridge commit，并通过 schema、路径边界、SHA256、条数、
   `known/active` 集合和 `active ⊆ known` 校验；本轮微信通道还必须真实启用、读取成功且状态完整。
4. archive 中所有微信记录必须 100% 具备合法 ID。任何无 ID、重复 ID、坏行、坏快照、哈希不符、
   commit 不符、通道失败或门控缺失都必须 fail-safe：记录失败状态并且一条不删。非法 JSONL 行必须在
   `RawItem` 构造前拒绝，不能进入 archive。
5. `WE_MP_ORPHAN_CLEANUP_MODE` 只允许 `off/audit/on`，默认和非法值均按 `off`；`audit` 只报告候选，
   `on` 才能按候选 ID 删除。没有完成 100% ID 迁移、真实 audit 人工确认和发布授权前，保持 `off`。
6. 数据恢复只能用 `scripts/restore_we_mp_cleanup.py` 按 `item_id` 精确回插缺失记录；禁止用旧
   `archive.json` 整文件覆盖当前归档，以免抹掉清理后新增的其它数据。

改动这块时，光跑单测不算数——必须真在浏览器里走一遍「删除 / 停用 / 改名 / 原样保存」四种
操作，逐一核对 `data/archive.json` 的条数与 site_id 分布。

## GitHub 星标托管清理窄例外

GitHub 只能走独立的稳定 repo ID 契约，不能进入名称型订阅清理或复用 generic force：

1. 仅 `managed_by=github_stars` 且 `managed_state=auto_disabled` 的受管源可成为候选；手动 GitHub
   `enabled:false` 只表示暂停，绝不自动删历史。
2. 清理身份只能是规范十进制 `managed_repo_id` / `github_repo_identity`，禁止按 owner/repo、来源名称、
   URL、本轮采集范围或 target 推断。
3. 同一 repo 必须在两个不同 `GITHUB_RUN_ID` 的非空完整公开星标快照中连续缺失；空快照、分页/账户失败、
   重复 repo ID 和同一 run 重试都必须熔断，不能推进确认或停用。
4. audit/on 只接受与当前 `GITHUB_RUN_ID`、`GITHUB_RUN_ATTEMPT`、`GITHUB_SHA` 完全配对的 autosync
   状态，并重算 `github-star-purge-state.json` 的 SHA256；任一状态、账号、哈希或 100% 归档身份覆盖不成立，
   一条不删。
5. `STAR_SUBSCRIPTION_CLEANUP_MODE` 仅允许 `off/audit/on`，默认 `off`；`audit` 只写候选和摘要，
   `on` 还必须精确匹配本轮 `STAR_SUBSCRIPTION_CLEANUP_APPROVAL_DIGEST`。摘要失配必须回 audit 重审，
   不能复用或放宽。
6. 回滚只允许 `scripts/restore_github_subscription_cleanup.py --item-id <record.id>` 精确回插 GitHub
   条目；禁止拿旧 `archive.json` 整体覆盖当前归档。

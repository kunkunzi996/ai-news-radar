# 新增桥接类信源自动采集的禁区（详细契约）

> 本文是 `CLAUDE.md`「新增桥接类信源自动采集的禁区」的展开。
> **三条核心红线仍在 `CLAUDE.md` 正文**（必须触发计划任务、只在同步推送成功后派发、
> 微信只能全量重采）；本文装七条逐条契约与它们的实测依据——
> 只有改 `scripts/radar/server/auto_collect.py` 或 `actions_refresh.py` 时才需要逐条对照。

2026-08-01 起，新增抖音（`mediacrawler_jsonl`）或微信（`we_mp_rss_jsonl`）信源后，
`scripts/radar/server/auto_collect.py` 会自动触发一次本机采集，采集结束后
`scripts/radar/server/actions_refresh.py` 再触发一轮云端 Actions。改这块时：

1. **必须触发计划任务，不能自己起采集进程。** 三条环境约束缺一条就跑不通（均实测）：
   **身份**——`RadarAdminServer` 是 `SYSTEM/ServiceAccount`，`DouyinCollectAndPush` 是
   `beelink-pc/Interactive`，会话隔离让 SYSTEM 拿不到带登录态的专用 Chrome（CDP 9333）；
   **凭证**——SYSTEM 侧 PAT 只对 `ai-news-radar` 有 Contents 权限，够不着
   `douyin-bridge` / `wechat-bridge`；**路径**——脚本默认推导的
   `CrawlerRoot=<父目录>/MediaCrawler` 在 NUC 上根本不存在（实际是 `MediaCrawler-local-test`）。
   计划任务里已配好全部正确参数。

2. **派发时机只能在「同步推送成功之后」，不能在「保存成功之后」。** 保存与同步是两个独立
   HTTP 请求。在保存阶段派发，采集拉起的浏览器会抢资源，把紧随其后的 `git push` 拖过
   Cloudflare 的 120 秒读超时，前端报「推送失败: Failed to fetch」而后端其实推成功了
   （2026-08-01 真踩过）。故保存只 `queue_pending_collect` 登记，确认推送成功后才
   `flush_pending_collect`。

3. **微信只能全量重采，禁止单号采集。** 桥接 JSONL 是**完整快照**，拿单个 feed 的结果覆盖
   会抹掉其它公众号的全部历史；且微信源 `locator` 为空、无稳定 `feed_id`，本就无法定位单号。
   抖音相反，`locator` 存有 `sec_uid`，可以定向。

4. **`DouyinCollectAndPush` 必须保留抖音、微信两条 action。** 本功能只触发一次任务就覆盖两个
   渠道，靠的正是这个前提；改成一条，微信会静默漏采。运维说明见
   `docs/guides/douyin-cloud-pc-automation.md`。

5. **只在「新增」时触发**：删除、停用、改名一律不触发，避免与历史清理逻辑产生交集。停用后
   重新启用算新增（其历史可能已在停用时被清理）。本模块不触碰 `data/archive.json`。

6. 云端刷新走 GitHub Contents API 在远端直接建提交，标记文件 `.bridge-refresh.json` 必须放
   仓库根（`data/**` 会被 workflow 的 `paths-ignore` 忽略、触发不了）。**不要改用本地
   git commit/push**——那会掉进 `CLAUDE.md`「同步线上的 git 编排禁区」。

7. **失败留痕必须可见且无敏感信息**：抖音与微信桥接脚本在失败终态、登录态
   `expired/login_required/invalid` 或异常收尾时写 `RadarRoot\logs\bridge-collection-failures.jsonl`，
   每行固定 10 个字段、`message` ≤512 字符、按渠道与 `run_id` 去重，禁止写入原始输出、cookie
   或 token。写日志失败只告警，不覆盖原状态或退出码；成功且登录态有效时不追加记录。
   （2026-08-08 起抖音新增 `state=warning` / `stage=partial_collection` 一类：本轮采到了但
   被风控少采几条时也会留痕，`message` 由脚本自拼、不引用 runner 原始错误文本。）

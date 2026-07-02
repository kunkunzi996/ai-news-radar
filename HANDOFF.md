# HANDOFF.md

## 当前最新交接：信源配置可本地写入并一键刷新

- 日期：2026-07-02
- 用户选择：方案 1，在当前 `master` 上做静态配置编辑器。
- 当前阶段：信源配置面板、本地写入、一键刷新、AI HOT 映射修复均已验收；代码已 commit 并 push 到用户自己的 GitHub 仓库。
- 主项目路径：`E:\AI-news-reader\ai-news-radar-run`
- 当前分支：`master`
- 当前远端：`origin=https://github.com/kunkunzi996/ai-news-radar.git`
- 最新已推送 commit：`a86c493 feat: add configurable local source dashboard`
- 本轮实现：
  - `index.html` 增加“信源配置”面板。
  - `assets/app.js` 增加 localStorage 本地草稿、增删改、导入 JSON、导出/复制 `sources.config.json`。
  - `assets/app.js` 已把官方源、精选媒体、社区聚合、高级 API 源和“我的订阅”一起列入配置目录；旧浏览器草稿会自动补齐缺失的内置源。
  - `assets/app.js` 增加“写入”按钮；启动 `scripts/local_server.py` 时可直接 POST 到 `/api/source-config`；按钮现在会显示“写入中... / 已写入 / 写入失败”。
  - `assets/app.js` 增加“刷新数据”按钮，会先写入当前配置，再调用 `/api/refresh`，成功后自动重载页面。
  - `scripts/local_server.py` 新增本地静态服务器，只绑定 `127.0.0.1`，只允许读写项目根目录 `sources.config.json`，并只允许运行固定的本地刷新命令。
  - `scripts/update_news.py` 增加 `--source-config`，会读取导出的 `sources.config.json`，按启用项设置本次抓取范围和必要运行参数。
  - `assets/styles.css` 增加桌面/移动端样式。
  - README 和 `PROJECT_STATE.md` 已写明边界。
- 当前边界：
  - 只加本地小后台，不加线上后端。
  - 写文件接口只允许写项目根目录 `sources.config.json`。
  - 不保存 cookie、token、`.env`、微信登录态、QR 登录文件或浏览器 profile。
  - 如果仍用 `python -m http.server`，页面没有写文件接口，也没有一键刷新接口，只能导出/复制兜底。
- 当前建议：新窗口先不要继续改功能；先处理剩余生成数据 / 临时文件的策略，或在确认无需提交它们后直接开始下一阶段产品工作。
- 手动验收重点：刷新 `http://127.0.0.1:8080/` 后，“信源配置”不应只剩 6 条订阅源，应能看到官方一手源包、精选AI媒体包、Hacker News、TopHub、OPML/RSS、X API、TikHub 等内置源。
- 本轮已验证：内置浏览器刷新后显示 `4/28 启用`，首批列表项为 `官方一手源包`、`精选AI媒体包`、`AI HOT`、`AI Breakfast`、`AIHubToday`、`Hacker News` 等。
- 配置生效验收：临时 `sources.config.json` 只启用 `github_foundation_sunshine` 时，刷新脚本输出 `source_scope=configured_sources`、`source_config.active=True`，且 `sites=github_foundation_sunshine_releases`。
- 本地后台验收：`GET /api/source-config` 返回 HTTP 200；`POST /api/source-config` 返回 `ok=true`；内置浏览器刷新后可见“写入”按钮，并显示 `已读取 sources.config.json`。
- 一键刷新验收：`POST /api/refresh` 返回 HTTP 200、`ok=true`、`source_scope=configured_sources`、`fetched_raw_items=316`；5 个启用源全 OK：GitHub Release 5 条、WeWe RSS 20 条、B站 25 条、抖音 68 条、小红书 198 条。
- AI HOT 映射修复：配置里 `id=aihot` 但 `type=rss` 时，刷新脚本原来没映射到内置 `aihot` 抓取器。现已改为内置源 `id` 优先识别；真实刷新后 `aihot.ok=true`、`item_count=109`，源状态为 `6/6 源正常`。
- 口径说明：配置面板显示 `7/28 启用`，源状态显示 `6/6 源正常` 是正常的，因为两个 B站账号配置项会合并成一个运行时抓取器 `bilibili_dynamic`。
- 浏览器插件自动化本轮两次读取 DOM 超时；最终验收依据是本地 HTTP 静态资源、真实写入接口、真实刷新接口和生成后的 `data/source-status.json`。
- Git 保存状态：已提交并推送到 `kunkunzi996/ai-news-radar`；`git log` 显示 `a86c493` 同时位于 `HEAD -> master, origin/master, origin/HEAD`。
- 剩余未提交项：`data/*.json` 生成数据、`bilibili-account-preview.html`、`server.err.log`、`server.out.log`。其中 `data/*.json` 未提交的关键原因是本地刷新后包含 Xiaohongshu `xsec_token` URL 参数。
- 本地文件策略已补充：见 `docs/LOCAL_ARTIFACT_POLICY.md`；`.gitignore` 已忽略 `bilibili-account-preview.html`、`server.err.log`、`server.out.log`。
- 2026-07-03 已补生成数据脱敏逻辑：`scripts/update_news.py` 会清理小红书 `xsec_token` / `xsec_source`，公开 JSON 写出前也会兜底清理 URL 字符串；旧的本地 `data/*.json` 需要重新生成后才会变干净。
- 下一轮必须先读：
  - `PROJECT_STATE.md`
  - `HANDOFF.md`
  - `AGENTS.md`
  - `docs/SOURCE_COVERAGE.md`
- 下一轮禁止：
  - 不要批量删除。
  - 不要提交 Cookie、登录态、`.env`、wewe-rss 数据库、QR 登录文件、浏览器 profile 或私有 token。
  - 不要把所有 dirty 文件一股脑提交。
  - 不要提交当前 `data/*.json`，除非先确认已经去掉 Xiaohongshu `xsec_token` 等平台临时参数。
  - 不要把 `/api/source-config` 扩展成任意路径写入；它只能写 `sources.config.json`。
  - 不要把 `/api/refresh` 扩展成前端可传任意命令；它只能跑项目内固定刷新命令。

## WeWe RSS 公众号桥接详情

- 日期：2026-07-02
- 本轮目标：把已经本地部署并订阅猫笔刀的 WeWe RSS 汇总回 AI News Radar 主页面。
- 当前实现：
  - 新增可选 source id：`wewe_rss`
  - 开关：`WEWE_RSS_ENABLED=1`
  - 默认 base URL：`http://127.0.0.1:4000`
  - 指定 feed 示例：`WEWE_RSS_FEEDS=猫笔刀:MP_WXS_3198966508`
  - 读取接口：`/feeds` 和 `/feeds/<feed_id>.json?limit=<n>`
  - 主页面会把它归入“我的订阅”，来源显示为“公众号订阅”。
- 隐私边界：
  - AI News Radar 只读 WeWe RSS JSON Feed。
  - 不读取 wewe-rss 数据库、cookie、`.env`、微信登录态或浏览器 profile。
  - `maobidao_wudaolu_backup` 未删除；但启用 `WEWE_RSS_ENABLED=1` 后刷新流程会跳过旧备份源，避免重复。
- 本轮建议验收命令：

```powershell
$env:PYTHONIOENCODING='utf-8'
$env:WEWE_RSS_ENABLED='1'
$env:WEWE_RSS_BASE_URL='http://127.0.0.1:4000'
$env:WEWE_RSS_FEEDS='猫笔刀:MP_WXS_3198966508'
.\.venv\Scripts\python.exe scripts/update_news.py --output-dir data --window-hours 24 --archive-days 3650 --all-time
```

验收后重点看：

- `data/source-status.json` 里 `wewe_rss.ok=true`
- `data/latest-24h-all.json` 的 `creator_items_all` 里出现 `site_id=wewe_rss`
- 主页面 `http://127.0.0.1:8080/` 的“我的订阅”能看到猫笔刀公众号文章

本轮已执行验收结果：

- `wewe_rss.ok=true`
- `wewe_rss.item_count=20`
- `creator_items_all` 中 `wewe_rss=20`
- `creator_items_all` 中 `maobidao_wudaolu_backup=0`
- `http://127.0.0.1:8080/data/latest-24h-all.json` HTTP 200
- 最新两条：`又要制裁了`（2026-07-01T14:24:08Z）、`上限锁死了`（2026-06-30T14:22:26Z）
- 自动化浏览器曾打开过主页面并确认过“我的订阅”和猫笔刀标题；后续刷新时浏览器自动化等待超时，但同源 `8080/data/*.json` 验收已通过。

## 历史交接：小红书本地桥接

- 在 AI News Radar 主页面接入已经验收通过的小红书博主动态。
- 执行项目洁癖，生成下一轮 Codex 可直接接手的交接说明。

## 本轮已完成

- 已确认主项目路径是 `E:\AI-news-reader\ai-news-radar-run`，外层 `E:\AI-news-reader` 不是主要工作树。
- 已新增本地 MediaCrawler Xiaohongshu JSONL 桥接：
  - source id: `mediacrawler_xhs`
  - toggle: `MEDIACRAWLER_XHS_ENABLED=1`
  - JSONL path: `MEDIACRAWLER_XHS_JSONL`
  - source name: `MEDIACRAWLER_XHS_SOURCE_NAME`
  - long alias vars also work: `MEDIACRAWLER_XIAOHONGSHU_*`
- 主页面已识别 `mediacrawler_xhs` 为“小红书博主”，并纳入“自媒体”栏目、来源筛选和覆盖池统计。
- 已用真实 JSONL 刷新本地数据：
  - source status: `mediacrawler_xhs.ok=true`
  - item count: `198`
  - `items_all_raw`: 198 条
  - `items_all`: 198 条
  - `creator_items_all`: 198 条
- 浏览器验收已通过：
  - `http://127.0.0.1:8080/`
  - 来源筛选包含 `MediaCrawler Xiaohongshu (2/198 · 1%AI)`
  - “自媒体”tab 显示 215 条 AI 相关自媒体信号
  - 页面文本包含 `陈抱一`

## 本轮修改文件

- `scripts/update_news.py`
  - 新增 `mediacrawler_xhs` 常量、JSONL 解析、环境变量开关和 source-status 输出。
- `assets/app.js`
  - 新增“小红书博主”来源标签、统计、自媒体栏目归类。
- `tests/test_private_bridge_sources.py`
  - 新增小红书 JSONL 解析测试和缺少 JSONL 配置时的错误测试。
- `README.md`
  - 新增本地小红书 MediaCrawler JSONL 接入命令和说明。
- `docs/SOURCE_COVERAGE.md`
  - 新增小红书本地私有桥接的覆盖与风险说明。
- `PROJECT_STATE.md`
  - 已记录小红书桥接验收结果、刷新命令和下一轮入口。
- `HANDOFF.md`
  - 本文件，跨窗口交接用。
- `data/*.json`
  - 真实刷新生成的本地页面数据，包含小红书 198 条结果。

## 本轮未完成

- 历史说明：本段来自小红书桥接收尾时的旧状态；当前代码已经 commit / push，以上方“当前最新交接”为准。
- 生成数据仍未纳入提交范围，尤其 `data/latest-24h.json` 变动很大，且本地刷新数据包含 Xiaohongshu `xsec_token` URL 参数。
- 未清理已有本地临时文件：
  - `bilibili-account-preview.html`
  - `server.err.log`
  - `server.out.log`
  这些不是本轮必须处理项，不要擅自删除。

## 当前项目状态

- 当前阶段：功能验收通过，Git 保存和 push 已完成；准备切换窗口继续。
- 当前分支：`master`
- 最新 commit：`a86c493 feat: add configurable local source dashboard`
- 当前远端：`origin=https://github.com/kunkunzi996/ai-news-radar.git`
- 本地服务：`http://127.0.0.1:8080/`
- 最新已完成：Bilibili 动态源、MediaCrawler Douyin 本地桥、MediaCrawler Xiaohongshu 本地桥、foundation-sunshine GitHub 版本订阅、WeWe RSS `猫笔刀` 公众号桥接均可在本地页面验收；默认部署输出已收窄为 `tested_creator_sources`。
- 用户确认：信源配置、本地写入、一键刷新、AI HOT `6/6 源正常` 均已验收成功。
- 下一步：先决定生成数据和临时文件处理策略；不要直接提交当前 `data/*.json`。
- 2026-07-02 已记录策略：`data/*.json` 保留本地但不能盲提交；`sources.config.json`、私有 OPML、MediaCrawler JSONL/profile 保留本地或仓库外；临时预览 HTML 和 server 日志加入忽略；删除必须逐个明确确认。
- 2026-07-03 已实现生成数据脱敏：新生成的公开 JSON 会去掉小红书 `xsec_token` / `xsec_source` 这类临时参数；当前工作区已有的 `data/*.json` 仍是旧刷新结果，提交前应重新生成并审查。

## 验收状态

- 已执行：
  - `.\.venv\Scripts\python.exe -m py_compile scripts/update_news.py`
  - `.\.venv\Scripts\python.exe -m unittest tests.test_private_bridge_sources`
  - 用真实小红书 JSONL 运行 `scripts/update_news.py --output-dir data --window-hours 24 --archive-days 3650 --all-time`
  - 浏览器打开 `http://127.0.0.1:8080/` 做页面验收
- 结果：
  - 语法检查通过。
  - 单测 `19 tests OK`。
  - 小红书 `mediacrawler_xhs.item_count=198`。
  - 主页面“自媒体”栏目和来源筛选可见小红书数据。
- 手动验收路径：
  - 打开 `http://127.0.0.1:8080/`
  - 切到“自媒体”
  - 查看来源筛选中是否有 `MediaCrawler Xiaohongshu`
  - 搜索或页面文本中应能看到 `陈抱一`

## Git 状态

- 分支：`master...origin/master`
- commit：`a86c493 feat: add configurable local source dashboard`
- push：已推送到 `https://github.com/kunkunzi996/ai-news-radar.git`
- 工作区仍有未提交生成数据和本地临时文件，下一轮不要误以为这些都是待提交代码。
- 当前已知 dirty/untracked 包括：
  - Bilibili / Douyin / Xiaohongshu / WeWe RSS 桥接相关代码和文档
  - `data/*.json` 生成数据
  - `requirements.txt` 早前本地环境变动
  - `tests/test_topic_filter.py` 早前变动
  - `bilibili-account-preview.html`
  - `server.err.log`
  - `server.out.log`

## 下一轮建议任务

1. 如果要提交生成数据，先重新生成 `data/*.json`，确认不再包含 Xiaohongshu `xsec_token` / `xsec_source`，再审查 diff。
2. 如果要删除 `bilibili-account-preview.html`、`server.err.log`、`server.out.log`，必须让用户逐个确认路径后再一次删一个。
3. 如果继续开发新功能，先确认当前工作区脏文件不会被误提交。
4. 暂时不要扩大 `/api/source-config` 或 `/api/refresh` 权限边界。

## 下一轮建议调用

- Kun Coding Router
- `references/08` 保存 / Git 流程
- `references/12` Verification / Git / Report
- 必要时再用 `references/13` Project Cleanup Gate

## 下一轮必须先读

- `PROJECT_STATE.md`
- `HANDOFF.md`
- `AGENTS.md`
- `docs/SOURCE_COVERAGE.md`
- `README.md` 中 MediaCrawler Douyin / Xiaohongshu 本地桥接段落

## 下一轮禁止事项

- 不要删除文件或目录；如果确实要清理临时文件，必须一次一个明确路径并先征得用户确认。
- 不要提交 Cookie、浏览器 profile、`MediaCrawler-local-test/chrome-profile`、`.env`、登录态或私有 token。
- 不要把 `E:\AI-news-reader\MediaCrawler-local-test` 的爬虫运行目录当成主项目提交范围。
- 不要用 `git reset --hard`、`git checkout --` 或批量删除来“清理”工作区。
- 不要把默认 AI 强相关里的 `2/198` 误判为只抓到了 2 条；全量池是 198 条，2 条只是 AI 强相关筛选结果。

## 当前风险 / 待确认

- 小红书和抖音都属于登录态/平台规则敏感来源，后续可能因为平台改接口、签名、限流或账号状态而失效。
- 主项目只读本地 JSONL，不负责自动爬取；更新动态需要先跑 MediaCrawler。
- `data/latest-24h.json` diff 很大，提交前需要确认是否真的要把生成数据入库。
- 工作区已有历史改动，Git 保存时必须精确分组，避免把无关变动一起提交。
- GitHub Actions 上如果没有可访问的本地 MediaCrawler JSONL 路径，线上默认可能只刷新 B站；抖音/小红书本地桥更适合本机生成数据后再决定是否提交。

## 下一轮 Codex 入口

使用 Kun Coding Router 继续当前项目。

请先读取：
1. `PROJECT_STATE.md`
2. `HANDOFF.md`
3. `AGENTS.md`
4. `docs/SOURCE_COVERAGE.md`

本轮建议任务：
- 生成数据脱敏逻辑已加入；下一步可选择重新生成并审查 `data/*.json`，或继续保持本地不提交。

禁止：
- 不要批量删除。
- 不要提交 Cookie、登录态或 MediaCrawler profile。
- 不要直接提交当前 `data/*.json`；里面可能包含 Xiaohongshu `xsec_token` URL 参数。
- 不要重构主页面或采集脚本。
- 不要把所有 dirty 文件一股脑提交。

建议启用：
- Kun Coding Router
- 保存 / Git 流程
- Verification / Git / Report

## 2026-07-01 追加：项目洁癖收尾

- 用户已确认整体验收成功。
- `PROJECT_STATE.md` 已更新为最终当前状态和下一轮入口。
- README、`docs/SOURCE_COVERAGE.md`、GitHub Actions、数据输出范围已在上一轮同步完成，本轮未重复扩大修改。
- AGENTS.md / CLAUDE.md 未改：没有新增长期 AI 施工规则，现有禁止删除、禁止提交密钥等规则仍适用。
- 下一轮建议只做 Git 保存前审查，不要继续改功能。
- 默认未处理 Obsidian 或个人知识库。

## 备注

- 本文件是跨窗口交接用，不是长期变更日志。
- 默认未处理 Obsidian 或个人知识库。

## 2026-07-01 追加：猫笔刀公众号订阅

- 用户要求使用伯乐Skill订阅公众号 `猫笔刀`，抓取最近 2 次更新，并在 `http://127.0.0.1:8080/` 本地页面展示。
- 伯乐判断：
  - 公众号不是稳定默认 RSS 源。
  - 最初接入的 `https://www.maobidao.net/` 最新只有 2025-12，已判定太旧并替换。
  - 当前采用公开备份站 `https://wudaolu.com/c/dav/7` 的 Discourse 分类 JSON 作为低权限桥接。
  - 不登录微信，不读取 cookie，不抓微信后台，不保存全文。
- 新增 source id：`maobidao_wudaolu_backup`。
- 抓取接口：`https://wudaolu.com/c/dav/7.json`。
- 预期最新两条：
  - `猫笔刀-又要制裁了-2026-07-01`
  - `猫笔刀-上限锁死了-2026-06-30`
- 已同步文件：
  - `scripts/update_news.py`
  - `assets/app.js`
  - `tests/test_topic_filter.py`
  - `README.md`
  - `docs/SOURCE_COVERAGE.md`
  - `PROJECT_STATE.md`
  - `HANDOFF.md`
- 风险：
  - 这是第三方公开备份源，不是微信官方 RSS；如果备份站停更或接口变化，`source-status.json` 会显示失败或 0 条。
  - 不要为这个源添加微信 cookie、登录态或浏览器 profile。

## 2026-07-02 历史：wewe-rss 部署交接（已完成）

> 状态：这段是部署前历史计划。当前已经完成本地 WeWe RSS 部署、猫笔刀订阅、AI News Radar 桥接和页面验收；最新入口以文件顶部“当前最新交接”为准。

### 本轮目标

- 用户当时准备在另一个 Codex 窗口部署 `cooderl/wewe-rss`，用于把微信公众号转成 RSS/JSON。
- 最终产品目标不变：每天只打开 AI News Radar，不打开多个软件。
- `wewe-rss` 只做后台取数 sidecar，AI News Radar 仍然是最终看板。

### 当前判断

- `wewe-rss` 可用于实现公众号订阅思路：
  - 基于微信读书扫码登录。
  - 支持微信公众号订阅。
  - 支持历史文章、定时更新、`.atom` / `.rss` / `.json` 输出。
  - 支持 OPML 导出。
- 但该 GitHub 仓库已在 2026-05-11 archived，属于可用但维护风险较高的方案。
- 本项目当前临时使用 `maobidao_wudaolu_backup` 读取 `https://wudaolu.com/c/dav/7.json`，只应视为临时备份源。

### 原下一窗口建议目标（已完成）

1. 独立部署 `wewe-rss`，不要在 AI News Radar 主项目里混装。
2. 先只订阅一个公众号：`猫笔刀`。
3. 确认 `wewe-rss` 能输出猫笔刀的 RSS 或 JSON。
4. 记录实际 feed URL，例如：
   - `http://127.0.0.1:4000/feeds/<feed_id>.json`
   - 或 `http://127.0.0.1:4000/feeds/<feed_id>.rss`
5. 验收成功后，再回到 AI News Radar 新增可选桥接源读取该 feed。

### 推荐部署边界

- 优先使用 `docker-compose.sqlite.yml` 或 SQLite Docker 模式做本地验证，少引入 MySQL 复杂度。
- `wewe-rss` 默认端口通常是 `4000`；AI News Radar 当前本地看板端口是 `8080`。
- 不要把 `wewe-rss` 的数据库、微信读书登录态、扫码凭证、cookie、`.env` 或 `AUTH_CODE` 提交进 AI News Radar 仓库。
- 不要把 `wewe-rss` 当成每天要打开的前台软件；它只负责给 AI News Radar 供水。

### 下一窗口验收标准

- 能打开 `wewe-rss` 管理页。
- 能扫码登录微信读书账号。
- 能添加 `猫笔刀` 公众号。
- 能通过本地 HTTP 访问 RSS/JSON 输出。
- 输出里能看到最近文章标题、链接、发布时间。
- 不要求本轮立刻接入 AI News Radar；先证明 `wewe-rss -> feed` 这段能跑通。

### 后续回到 AI News Radar 的接入草案

- 未来可新增环境变量：
  - `WEWE_RSS_ENABLED=1`
  - `WEWE_RSS_BASE_URL=http://127.0.0.1:4000`
  - `WEWE_RSS_FEEDS=猫笔刀:<feed_id>`
- AI News Radar 只读取 `wewe-rss` 的 RSS/JSON 输出。
- 输出进入现有 `我的订阅` 栏目。
- `maobidao_wudaolu_backup` 可以保留为 fallback，或在 wewe-rss 验收稳定后移出默认范围。

### 下一窗口必须先读

1. 本文件 `HANDOFF.md`
2. `PROJECT_STATE.md`
3. `README.md`
4. `docs/SOURCE_COVERAGE.md`
5. `AGENTS.md`

### 下一窗口禁止事项

- 不要在 AI News Radar 仓库里保存微信读书登录态、cookie、扫码结果、数据库文件、`.env` 或真实 `AUTH_CODE`。
- 不要删除当前 `maobidao_wudaolu_backup`，除非 wewe-rss 已经验收通过并且用户确认切换。
- 不要把部署失败误判为 AI News Radar 页面问题；先单独验证 `wewe-rss` 的 `4000` 端口和 feed 输出。
- 不要自动 commit / push；当前工作区已经有较多历史脏改，保存前必须先做 Git 范围审查。

### 下一窗口 Codex 入口

使用 Kun Coding Router 继续。

任务：独立部署 `cooderl/wewe-rss`，只验证 `猫笔刀` 一个公众号能输出 RSS/JSON。

验收后回报：
- wewe-rss 部署路径
- 本地访问 URL
- 是否扫码成功
- 猫笔刀 feed URL
- 最近 2 条文章标题和时间
- 是否准备回到 AI News Radar 做 `WEWE_RSS_*` 桥接源

## 2026-07-01 追加：GitHub 版本订阅

- 用户要求用伯乐 Skill 订阅 GitHub 项目 `AlkaidLab/foundation-sunshine`，并在 `http://127.0.0.1:8080/` 展示版本更新。
- 已按伯乐 Skill 判断走公开 GitHub Releases API，不需要 GitHub 登录态、token 或 Watch 权限。
- 新增 source id：`github_foundation_sunshine_releases`。
- 默认 `tested_creator_sources` 已包含该 source id。
- 页面“我的订阅”会显示订阅源全量更新，但该仓库只进入 release，不再进入普通 commit。
- 下一轮验收重点：
  - 跑 `scripts/update_news.py` 生成数据。
  - 打开 `http://127.0.0.1:8080/`，切到“我的订阅”，搜索 `foundation-sunshine` 或 `v2026`。

## 2026-07-01 追加：我的订阅只剩 1 条 Bug

- 用户反馈：点着点着，页面只剩 1 条信息。
- 复现状态：页面在 `我的订阅 + 过去 24 小时`，所以只显示当前 24 小时内的 1 条小红书订阅。
- 原因：订阅页需要看“已订阅源的全量可见更新”，不应该沿用默认 24 小时过滤。
- 已修复：点击顶部“我的订阅”tab 或高级筛选里的“我的订阅”栏目时，自动把时间范围切到 `不限`。
- 已验证：刷新 `http://127.0.0.1:8080/` 后点击“我的订阅”，时间范围变为 `不限`，列表显示订阅全量，并能看到 `foundation-sunshine` 版本发布。

## 2026-07-01 追加：GitHub 只追踪版本发布

- 用户认为 GitHub 普通 commit 噪音太多，只想追踪是否有版本更新，并给出 release 链接 `v2026.611.71453.杂鱼`。
- 已调整：
  - 不再读取 `AlkaidLab/foundation-sunshine` commits API。
  - 改读 GitHub Releases API。
  - source id 改为 `github_foundation_sunshine_releases`，避免旧 commit 记录留在默认数据里。
  - 默认读取最近 5 个公开 release，因此包含用户给出的 `v2026.611.71453.杂鱼`。
- 已验证：
  - `source-status.json` 中 `github_foundation_sunshine_releases.item_count=5`。
  - 页面“我的订阅”显示 `GitHub版本订阅`。
  - 旧 commit 文案 `chore: update docs` / `move borrowed texture telemetry` 不再出现。

## 2026-07-01 追加：信源范围已收窄

本轮已按用户要求完成信源架构修正：默认部署输出只保留刚才测试过的订阅信源。

- 默认 `source_scope`：`tested_creator_sources`
- 默认保留：
  - `bilibili_dynamic`
  - `mediacrawler_douyin`
  - `mediacrawler_xhs`
- 默认排除：
  - 原项目内置官方 RSS / 精选媒体 / Follow Builders / AI HOT / Hacker News / WaytoAGI
  - OPML/RSS 示例源
  - AgentMail / X API / SocialData / TikHub 高级源
- 老抓取函数没有删除；如果以后确实需要临时恢复旧全源模式，手动运行 `scripts/update_news.py --source-scope all_sources ...`。
- GitHub Actions 默认刷新已同步为已验收订阅源范围，不再准备 OPML 或传入旧高级源 env。
- `data/` 已重新生成，实际输出只包含：
  - `bilibili_dynamic: 261`
  - `mediacrawler_douyin: 68`
  - `mediacrawler_xhs: 198`
  - `github_foundation_sunshine_releases: 5`
  - 总计 532 条 all-mode items
- 不要删除旧源相关函数；当前策略是“默认不启用”，避免顺手拆坏其它功能。

## 2026-07-01 追加：最终洁癖收尾

- 用户已确认 release-only GitHub 追踪验收成功。
- `PROJECT_STATE.md` 与 `HANDOFF.md` 已同步为下一轮入口。
- README 与 `docs/SOURCE_COVERAGE.md` 已包含 GitHub release-only 订阅说明，无需重复扩写。
- AGENTS.md 未改：没有新增长期施工禁区或硬规则。
- 没有删除文件或目录。
- 没有执行 Git commit / push。
- 下一轮最建议做 Git 保存前审查：区分“应提交代码/文档/测试”和“是否提交生成数据 data/*.json”。

## 2026-07-01 追加：我的订阅标签

- 用户要求把今天追踪的 B站、小红书、油管、抖音博主统一归类为“我的订阅”。
- 已完成：
  - 前端栏目仍使用内部 `creator` id，但展示名从 `自媒体` 改为 `我的订阅`。
  - 高级筛选里的来源类型也改为 `我的订阅`。
  - B站、抖音、小红书、YouTube/youtu.be 都会被识别为订阅项。
  - `bilibili_dynamic` source tier 补为 `我的订阅`。
  - `index.html` 的 `assets/app.js` 版本参数已更新，避免旧浏览器缓存继续显示旧标签。
- 已验证：
  - `node --check assets/app.js`
  - `.\.venv\Scripts\python.exe -m py_compile scripts/update_news.py`
  - 4 个相关 `tests.test_topic_filter` 单测
  - 本地 HTTP 200，且 served `index.html` / `assets/app.js` 能读到“我的订阅”相关文字
- 注意：
  - in-app browser 自动控制两次导航超时，未完成点击式 UI 验收；手动验收请刷新 `http://127.0.0.1:8080/` 看栏目条是否出现“我的订阅”。

## 2026-07-01 追加：时间范围不限

- 用户要求高级筛选里的“时间范围”增加“不限”。
- 已完成：
  - `index.html` 的 `timeRangeSelect` 新增 `<option value="all">不限</option>`。
  - `assets/app.js` 新增 `state.timeRangeFilter`，默认 `24h`。
  - 选择“不限”时会加载 `latest-24h-all.json`，并取消前端 24 小时过滤。
  - 选择“过去 24 小时”时按 `generated_at` 往前 24 小时过滤当前视图。
  - `app.js` 缓存参数更新为 `time-range-all-0701a`。
- 注意：
  - 这里的“不限”是前端对当前已生成数据不再加 24 小时过滤，不会自动重新抓全历史；要真正全历史数据仍需用已有 `--all-time` 刷新命令生成。

## 2026-07-01 追加：YouTube 订阅可见性

- 用户反馈“我的订阅”页面没看到油管相关订阅。
- 排查结果：
  - `data/latest-24h-all.json` 里已有 1 条来自 `feeds/follow.opml` 的 YouTube 记录。
  - `creator_items_all` 里没有 YouTube，因为数据是在前端订阅合并规则完善前生成的。
- 已修复：
  - `assets/app.js` 的“我的订阅”列表现在会把预生成 `creator_items_*` 和当前 AI/全量列表中符合订阅规则的项目合并去重。
  - YouTube 只在来自 OPML/RSS (`opmlrss` / `opmlrss:*`) 时动态补进“我的订阅”，避免把普通新闻源中的 YouTube 链接误当成个人订阅。
- 已验证：
  - `node --check assets/app.js`
  - served `assets/app.js` 包含 `subscriptionModeItems()`、OPML YouTube 规则和合并调用。
  - 当前 `latest-24h-all.json` 中有 1 条 OPML YouTube 订阅项。

## 2026-07-01 追加：TopHub 误入我的订阅

- 用户反馈 TopHub 也出现在“我的订阅”里。
- 原因：
  - TopHub 是聚合热榜源，里面有 Bilibili/Douyin 热榜 URL。
  - 上一轮前端订阅判断只看 URL 平台关键字，导致 TopHub 被误判为订阅源。
- 已修复：
  - `assets/app.js` 的订阅判断改为：
    - 明确追踪源 id 永远算订阅。
    - OPML/RSS (`opmlrss` / `opmlrss:*`) 里的平台链接算订阅。
    - TopHub/Buzzing/TechURLs 等聚合源即使链接到 B站/抖音/YouTube，也不算订阅。
- 已验证：
  - 当前 `latest-24h-all.json` 用新规则计算：TopHub 订阅数 0，OPML YouTube 订阅数 1。
  - `node --check assets/app.js` 通过。

## 2026-07-02 追加：wewe-rss 本地部署已启动

### 已完成

- 已按交接要求把 `wewe-rss` 作为独立 sidecar 部署，不混装进 AI News Radar 主项目。
- 部署目录：`E:\AI-news-reader\wewe-rss-sidecar`
- 上游仓库：`cooderl/wewe-rss`，当前拉取版本 v2.6.1；仓库已归档只读。
- 本机没有 `docker` 命令，因此没有走 Docker Compose。
- 已用本地 Node/pnpm 路线跑通：
  - 旧锁文件需要 `corepack pnpm@8.15.9`
  - 依赖安装使用 `--ignore-scripts --frozen-lockfile`
  - SQLite Prisma client 使用 `apps/server/prisma-sqlite/schema.prisma` 生成
  - Prisma migrate 在当前 Windows/Node 24 环境下失败，已用仓库自带 SQLite migration SQL 手动建库
  - 前后端构建通过
- 当前服务进程：
  - PID：`24144`
  - 本地地址：`http://127.0.0.1:4000/dash`
  - 只监听 `127.0.0.1`
  - 数据库：`E:\AI-news-reader\wewe-rss-sidecar\apps\server\data\wewe-rss.db`
  - 日志：`E:\AI-news-reader\wewe-rss-sidecar\wewe-rss.out.log` / `wewe-rss.err.log`
- 已验证：
  - `127.0.0.1:4000` 端口在监听
  - 首页 HTTP 200
  - 浏览器可进入 dashboard
  - 当前为 `共0个订阅`，符合未扫码/未添加公众号前的状态

### 注意事项

- 登录页可能要求 `AuthCode`。这是 archived 版本前端模板的布尔值小坑：后端没设真实 `AUTH_CODE` 时，前端仍可能显示登录页。
- 本轮本地运行没有设置真实 `AUTH_CODE`；输入本地占位值 `local` 可以进入 dashboard。不要把它当密钥。
- 不要提交 `wewe-rss` 数据库、日志、登录态、二维码、cookie、`.env` 或任何扫码结果。
- 不要删除 `maobidao_wudaolu_backup`；它仍是当前 AI News Radar 的临时公众号来源。

### 下一步

1. 打开 `http://127.0.0.1:4000/dash`。
2. 如果看到 `AuthCode`，输入 `local` 进入 dashboard。
3. 添加微信读书账号并用用户自己的微信扫码。
4. 只添加一个公众号：`猫笔刀`。
5. 找到该公众号的 feed id，验证：
   - `http://127.0.0.1:4000/feeds/<feed_id>.json`
   - 或 `http://127.0.0.1:4000/feeds/<feed_id>.rss`
6. 回报最近 2 条文章标题、发布时间和 feed URL。
7. 只有 feed 验收通过后，才回到 AI News Radar 增加可选 `WEWE_RSS_*` 桥接。

## 2026-07-02 追加：油管 OPML 订阅缺失修复

- 用户反馈：最新部署的本地版本缺失油管博主订阅。
- 根因：
  - `feeds/follow.opml` 没丢，里面仍有 `小岛大浪吹-非正经政经频道` 的 YouTube RSS。
  - `assets/app.js` 也没丢 YouTube 订阅合并逻辑。
  - 真正问题是本地 `sources.config.json` 里 `opmlrss` 被设为 `enabled: false`，所以本地刷新根本没抓 OPML/RSS。
- 已修复：
  - 已把本地 `sources.config.json` 中 `opmlrss` 改为启用。
  - 注意：`sources.config.json` 是本地配置文件，不提交，`git status` 不会显示它。
- 已验证：
  - 真实刷新命令已跑通：`.\.venv\Scripts\python.exe scripts\update_news.py --source-config sources.config.json --output-dir data --window-hours 24 --archive-days 3650 --all-time`
  - `data/source-status.json` 显示 `rss_opml.enabled=true`、`ok_feeds=1/1`、`opmlrss.item_count=15`。
  - `data/latest-24h-all.json` 的 `creator_items_all` 中有 15 条 `opmlrss` YouTube 订阅。
  - `http://127.0.0.1:8080/data/latest-24h-all.json` 也能读到同样 15 条。
  - 样例标题：`【小岛浪吹】从阿嫲的情书到印加坡：一个华人多数国家的身份焦虑`。
  - `py_compile`、`node --check assets\app.js`、2 个相关单测均通过。
- 下一轮注意：
  - 如果页面又缺 YouTube，先查 `sources.config.json` 里 `OPML/RSS 订阅包` 是否启用，再看 `data/source-status.json.rss_opml`。
  - 当前刷新造成 `data/*.json` 继续脏，不要直接全部提交。

## 2026-07-02 追加：信源配置面板实时生效修复

- 用户反馈：信源配置界面里的修改目前不会生效。
- 根因：
  - 原交互需要先点 `保存草稿`，再点 `写入` 或 `刷新数据`。
  - 如果用户只改勾选/字段，左侧列表、启用数和 JSON 预览不会马上变，看起来就像“没生效”。
- 已修复：
  - `assets/app.js` 增加表单 `input/change` 实时同步本地草稿。
  - 修改字段或勾选启用后，会马上更新左侧列表、`8/28 启用` 这类摘要、JSON 预览和 localStorage 草稿。
  - `index.html` 的脚本版本号已改为 `source-config-live-draft-0702a`，避免浏览器继续用旧 JS。
- 已验证：
  - `node --check assets\app.js` 通过。
  - `.\.venv\Scripts\python.exe -m unittest tests.test_local_server tests.test_topic_filter.TopicFilterTests.test_apply_source_config_runtime_sets_fetcher_env_without_secrets` 通过，5 tests OK。
  - 浏览器在 `http://127.0.0.1:8080/` 已加载新脚本。
  - 临时勾选 `官方一手源包` 后，摘要从 `8/28 启用` 立即变 `9/28 启用`，JSON 中 `official_ai_sources.enabled=true`；随后已取消勾选恢复为 `8/28 启用`。
- 注意：
  - 这只是让“当前页面草稿”实时更新。
  - 真正写入文件仍要点 `写入`。
  - 真正重新生成新闻数据仍要点 `刷新数据`。

## 2026-07-02 追加：删除内置信源后不再复活

- 用户反馈：没用的源删掉后，点 `保存草稿`、`写入`、`刷新数据`，已经删除的源又会出现。
- 根因：
  - `mergeSourceConfigWithSeed()` 每次读配置都会把内置种子源补齐。
  - 它原本是为了补新版本新增源，但误伤了用户主动删除的内置源。
- 已修复：
  - `assets/app.js` 新增 `deleted_source_ids` 墓碑字段。
  - 删除内置源时会记录它的 id，后续读取、写入、刷新时不会再自动补回来。
  - 对当前版本的旧配置做兼容：如果配置里已经少了某些内置源，会自动把这些缺失项记为已删除。
  - `index.html` 脚本版本号已更新为 `source-config-delete-tombstone-0702a`。
- 已验证：
  - `node --check assets\app.js` 通过。
  - `.\.venv\Scripts\python.exe -m unittest tests.test_local_server tests.test_topic_filter.TopicFilterTests.test_apply_source_config_runtime_sets_fetcher_env_without_secrets` 通过，5 tests OK。
  - 浏览器刷新后，已删除的 `官方一手源包`、`精选AI媒体包` 没复活。
  - 实测删除 `AI Breakfast`，点 `写入` 后刷新页面没有复活。
  - 再点 `刷新数据` 完整刷新后仍没有复活；当前页面显示 `9/26 启用`。
- 注意：
  - 这是删配置项，不是删除代码或文件。
  - 想恢复被删内置源，可以点 `恢复当前`，或导入/新增对应配置。

## 2026-07-02 追加：信源配置折叠面板

- 用户反馈：信源配置区域不美观，希望参考上方 `高级筛选`，做成点击才打开的样式。
- 已完成：
  - `index.html` 把信源配置区域改成 `<details>` 折叠面板。
  - 默认只显示一行：`信源配置` + 当前启用数量。
  - 点开后才显示 `写入`、`刷新数据`、`导出`、`复制`、信源列表、表单和 JSON。
  - `assets/styles.css` 复用高级筛选的紧凑行、圆形加减号、浅色边框视觉。
  - `index.html` 脚本版本号已更新为 `source-config-collapsible-0702a`。
- 已验证：
  - 浏览器加载了新脚本。
  - 默认折叠时高度约一行，显示 `信源配置 9/16 启用`。
  - 点开后 `open=true`，16 个配置项和 `写入 刷新数据 导出 复制` 按钮都正常显示。
- 注意：
  - 这只是界面呈现优化，不改变配置写入、刷新数据、删除源逻辑。

## 2026-07-02 追加：B站信源按渠道合并

- 用户反馈：`Koji杨远骋at十字路口` 和 `技术爬爬虾` 都属于 B站信源，不应该在左侧列表分成两条；后续同一渠道会关注很多 UP 主。
- 已完成：
  - `assets/app.js` 的默认信源从两条 B站记录改为一条 `B站动态`。
  - 旧配置中的 `bilibili_*` 多条记录会在页面读取时自动合并为 `bilibili_dynamic_sources`。
  - 合并后的 `地址 / ID / 路径` 是 `505301413,316183842`，`关注对象` 是 `Koji杨远骋at十字路口,技术爬爬虾`。
  - `tests/test_topic_filter.py` 已改用合并后的 B站配置，验证刷新时环境变量仍正确。
  - `index.html` 脚本版本号已更新为 `source-config-channel-merge-0702a`。
- 已验证：
  - 浏览器里左侧列表只显示一条 `B站动态`。
  - JSON 中只有一个 `bilibili_dynamic_sources` 记录。
  - 点击该记录后，表单里能看到两个 UID 和两个 UP 主名。
- 注意：
  - 本轮先合并 B站渠道。抖音、小红书等渠道如果后面也出现多个账号，可以按同样模式继续合并。

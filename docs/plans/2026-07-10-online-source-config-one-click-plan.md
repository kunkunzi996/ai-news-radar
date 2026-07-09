# 线上信源配置一键同步需求与施工计划

日期：2026-07-10

主项目路径：`E:\AI-news-reader\ai-news-radar-run`

## 1. 需求背景

AI News Radar 已经完成 GitHub Pages 最小上线，公网页面只负责读取静态资源和 `data/*.json`。

现在的问题是：

- 公网页面上的“信源配置”不能直接修改 GitHub Actions 真正使用的线上信源。
- 本地 `sources.config.json` 是本机私有配置，不提交，也不是线上真实配置。
- 线上实际刷新由 `.github/workflows/update-news.yml` 控制，目前每 30 分钟跑一次，也会在推送到 `master` 后触发一次。

用户想要的结果是：

> 在本地页面里像普通软件一样增删线上信源，点一个按钮，就能同步到 GitHub，等待 Actions 自动刷新后，公网页面跟着变。

## 2. 本轮目标

下一轮要做的是“线上信源配置傻瓜式一键同步 MVP”。

一句话版本：

> 新增一个可提交到仓库的公开线上信源配置文件，让 GitHub Actions 读取它；再在本地 8080 控制台加一个“一键同步到线上”按钮，自动完成校验、写文件、提交、推送。

## 3. 不做范围

下一轮不要混入这些任务：

- 不做抖音 / 小红书非本机采集。
- 不恢复微信公众号采集。
- 不把 `scripts/local_server.py` 暴露到公网。
- 不在公网浏览器里放 GitHub token。
- 不大重构数据管线。
- 不提交本地生成的 `data/*.json`。
- 不提交 `sources.config.json`、`feeds/follow.opml`、`local-secrets/`、cookie、token、`.env`、浏览器 profile。

## 4. 现状判断

当前代码已经有一块可复用基础：

- `scripts/update_news.py` 支持 `--source-config <path>`。
- `scripts/radar/config_runtime.py` 会读取 source config，并让配置接管刷新范围。
- 本地后台已有 `GET/POST /api/source-config`，但它写的是私有 `sources.config.json`。
- 公网页面通过 `canUseLocalBackend()` 判断，不会连接本地后台。
- GitHub Actions 当前使用 workflow env 配 B站 UID、OPML fallback、GitHub release 默认源。

所以本需求不需要推翻架构，只需要补一个“公开线上配置层”和“本地同步按钮”。

## 5. MVP 支持的线上信源类型

第一版只支持安全、公开、适合 GitHub Actions 跑的来源：

1. B站动态
   - 用户输入：UP 主名称、UID。
   - 运行方式：写入公开配置后转成 `BILIBILI_DYNAMIC_UIDS` / `BILIBILI_DYNAMIC_SOURCE_NAMES`。

2. GitHub Release
   - 用户输入：`owner/repo` 或 GitHub 仓库 URL。
   - 运行方式：现有 `github_release` 配置已经能转成 Releases API。

3. RSS / YouTube feed
   - 用户输入：feed 标题、RSS/Atom/YouTube feed URL。
   - 推荐实现：写入一个公开 OPML 文件，例如 `feeds/online-sources.opml`，再由 `config/online-sources.json` 的 `opmlrss` 记录指向它。

暂不支持：

- 抖音 / 小红书线上云采集，因为当前依赖本机 MediaCrawler、登录态和 JSONL。
- WeChat / WeWe RSS，因为当前默认云端源已退役。
- X / TikHub / SocialData / AgentMail，因为涉及 API key 或费用，不能作为傻瓜式第一版。

## 6. 推荐文件设计

新增两个可提交的公开文件：

1. `config/online-sources.json`

   作用：GitHub Actions 的线上真实信源配置。

   建议沿用现有 `sources.config.json` schema，避免新造一套：

   ```json
   {
     "version": "1.0",
     "mode": "online-public-source-config",
     "updated_at": "2026-07-10T00:00:00Z",
     "sources": [
       {
         "id": "bilibili_dynamic_sources",
         "name": "B站动态",
         "type": "bilibili_dynamic",
         "enabled": true,
         "channel": "B站动态",
         "target": "技术爬爬虾",
         "locator": "316183842",
         "env": "",
         "notes": "公开 UID，不含 cookie"
       },
       {
         "id": "github_alkaidlab_foundation_sunshine",
         "name": "AlkaidLab/foundation-sunshine",
         "type": "github_release",
         "enabled": true,
         "channel": "GitHub Release",
         "target": "AlkaidLab/foundation-sunshine",
         "locator": "AlkaidLab/foundation-sunshine",
         "env": "",
         "notes": "只追踪 release"
       },
       {
         "id": "online_opmlrss",
         "name": "线上 RSS/YouTube 订阅包",
         "type": "opmlrss",
         "enabled": true,
         "channel": "RSS/OPML",
         "target": "feeds/online-sources.opml",
         "locator": "feeds/online-sources.opml",
         "env": "",
         "notes": "公开 feed 列表"
       }
     ]
   }
   ```

2. `feeds/online-sources.opml`

   作用：保存公开 RSS / YouTube feed 列表。

   注意：继续禁止提交 `feeds/follow.opml`；`feeds/online-sources.opml` 是刻意公开的线上配置文件。

## 7. GitHub Actions 改造计划

下一轮建议这样改：

1. `.github/workflows/update-news.yml`
   - `Update data` 命令增加：

     ```bash
     python scripts/update_news.py --source-config config/online-sources.json --output-dir data --window-hours 24 --archive-days 21
     ```

   - 保留 `FOLLOW_OPML_B64` 作为高级兜底可以，但 MVP 推荐让线上公开 RSS 走 `feeds/online-sources.opml`。
   - `RADAR_SOURCE_SCOPE: tested_creator_sources` 可保留作为 fallback，但只要 `--source-config` 存在，实际输出应变成 `source_scope=configured_sources`。

2. 验收标准
   - Actions 成功运行。
   - 公网 `data/source-status.json` 中：
     - `source_config.active=true`
     - `source_scope=configured_sources`
     - `source_config.path=config/online-sources.json`

## 8. 本地后台改造计划

新增一组 local-only API。只允许 `127.0.0.1` / `localhost` 使用，不允许公网页面调用。

推荐接口：

- `GET /api/online-source-config`
  - 读取 `config/online-sources.json` 和 `feeds/online-sources.opml`。
  - 返回给页面展示。

- `POST /api/online-source-config`
  - 只写 `config/online-sources.json` 和必要的 `feeds/online-sources.opml`。
  - 严格校验来源类型和字段。
  - 不运行 git。

- `POST /api/sync-online-source-config`
  - 执行保存、校验、精确 stage、commit、push。
  - 只允许 stage 这几个明确文件：
    - `config/online-sources.json`
    - `feeds/online-sources.opml`
    - 本轮确实改到的代码 / 文档文件
  - 禁止 `git add .`。
  - 禁止 stage `data/*.json`、`sources.config.json`、`feeds/follow.opml`、`local-secrets/`。

## 9. 前端改造计划

在本地 `http://127.0.0.1:8080/` 的信源配置区域增加一个清晰入口：

- 标题：`线上信源`
- 按钮：`同步到线上`
- 状态：
  - `未保存`
  - `已写入本地线上配置`
  - `正在提交并推送`
  - `已推送，等待 GitHub Actions 刷新`
  - `推送失败，请查看错误`

第一版表单不要复杂，建议只给三个新增入口：

- `添加 B站 UP`
- `添加 GitHub Release`
- `添加 RSS/YouTube`

每条记录支持：

- 启用 / 停用
- 删除
- 名称
- 关键字段
- 备注

公网 GitHub Pages 上同一区域必须是只读或提示：

> 公网静态页不能直接修改线上配置；请在本机打开 127.0.0.1:8080 使用本地控制台同步。

## 10. 校验与安全规则

下一轮必须加严格校验，避免新手误把私密内容写进公开仓库。

必须拒绝：

- 字段名或字段值里出现明显敏感词：`token`、`cookie`、`secret`、`password`、`authorization`、`xsec_token`、`.env`。
- 本地私密路径：`local-secrets`、`chrome-profile`、`MediaCrawler-local-test`、`creator_contents_*.jsonl`。
- `feeds/follow.opml`。
- 任意非 http/https 的 RSS URL。
- 不在白名单内的 type。

必须做到：

- 写 JSON 前先格式化并排序稳定。
- 写 OPML 前用 XML parser 或明确转义，不能拼危险字符串。
- commit message 使用中文，例如：`配置：同步线上信源`。
- git stage 必须使用明确路径，禁止 `git add .`。

## 11. 下一轮施工步骤

建议按这个顺序做：

1. 读档与确认
   - 读 `AGENTS.md`、`PROJECT_STATE.md`、`HANDOFF.md`、本计划文件。
   - 跑 `git status --short --branch`。
   - 确认本轮不提交本地 `data/*.json` 和 `计划/`。

2. 建公开配置样例
   - 新增 `config/online-sources.json`。
   - 新增 `feeds/online-sources.opml`。
   - 用当前线上实际 3 类源做初始配置：B站、GitHub Release、OPML/RSS。

3. 让刷新脚本读取线上配置
   - 修改 workflow 使用 `--source-config config/online-sources.json`。
   - 必要时补测试，确认 source config 生效后 `source_scope=configured_sources`。

4. 做本地 backend API
   - 新增读写线上配置的 local-only endpoint。
   - 新增校验函数。
   - 新增同步 git 的 endpoint，先只 stage 白名单文件。

5. 做本地 UI
   - 增加“线上信源”入口和“一键同步到线上”按钮。
   - 公网页面禁用写操作。

6. 验收
   - 本地验证配置写入。
   - 本地验证 git stage 范围。
   - 推送后看 GitHub Actions。
   - 公网 `source-status.json` 确认新配置生效。

7. 文档收尾
   - 更新 `README.md` 的线上信源配置说明。
   - 更新 `HANDOFF.md`。

## 12. 手动验收剧本

下一轮实现后，用这条路验收：

1. 启动本地后台：

   ```powershell
   .\.venv\Scripts\python.exe scripts\local_server.py --host 127.0.0.1 --port 8080
   ```

2. 打开：

   ```text
   http://127.0.0.1:8080/
   ```

3. 展开信源配置，进入 `线上信源`。

4. 新增或删除一个公开安全源，例如：

   - B站 UP：输入名称和 UID。
   - GitHub Release：输入 `owner/repo`。
   - RSS/YouTube：输入标题和 feed URL。

5. 点击 `同步到线上`。

6. 页面应显示：

   - 已写入公开配置。
   - 已提交。
   - 已推送。
   - 等待 GitHub Actions 刷新。

7. 本地检查 git 范围：

   ```powershell
   git show --name-only --oneline -1
   ```

   预期只包含线上配置、OPML、必要代码/文档，不包含 `data/*.json`、`sources.config.json`、`feeds/follow.opml`、`local-secrets/`。

8. 打开 GitHub Actions：

   ```text
   https://github.com/kunkunzi996/ai-news-radar/actions/workflows/update-news.yml
   ```

   预期最新 `Update AI News Snapshot` 成功。

9. 打开公网 JSON：

   ```text
   https://kunkunzi996.github.io/ai-news-radar/data/source-status.json
   ```

   预期看到：

   - `source_config.active=true`
   - `source_scope=configured_sources`
   - 新增 / 删除的源已经体现在 `sites` 或对应 subscriptions 里。

10. 打开公网首页：

   ```text
   https://kunkunzi996.github.io/ai-news-radar/
   ```

   预期页面能正常加载，源状态正常，新增公开源有内容时会出现在对应栏目。

## 13. 下一窗口 Codex 入口

使用 Kun Coding Router 继续当前项目。

请先读取：

1. `AGENTS.md`
2. `PROJECT_STATE.md`
3. `HANDOFF.md`
4. `README.md`
5. `.github/workflows/update-news.yml`
6. `docs/plans/2026-07-10-online-source-config-one-click-plan.md`
7. `assets/js/source-config.js`
8. `assets/js/utils.js`
9. `scripts/radar/cli.py`
10. `scripts/radar/config_runtime.py`
11. `scripts/local_server.py`
12. `scripts/radar/server/refresh.py`
13. `scripts/radar/server/common.py`

本轮任务：

> 实现“线上信源配置傻瓜式一键同步 MVP”：本地页面可增删 B站 / GitHub Release / RSS-YouTube 公开源，一键写入公开线上配置、提交并推送，GitHub Actions 读取该配置刷新公网 `data/*.json`。

本轮禁止：

- 不做抖音 / 小红书非本机采集。
- 不恢复公众号采集。
- 不暴露本地后台到公网。
- 不在公网浏览器里保存 GitHub token。
- 不提交 `data/*.json` 本地生成产物。
- 不提交 `sources.config.json`、`feeds/follow.opml`、`local-secrets/` 或任何私密文件。
- 不使用 `git add .`。

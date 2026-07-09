# HANDOFF.md

## 当前最新交接：GitHub Pages 最小上线准备已完成，等待后台开启

- 日期：2026-07-09
- 主项目路径：`E:\AI-news-reader\ai-news-radar-run`
- 当前阶段：GitHub Pages 静态站代码已按当前仓库收口；仍需用户在 GitHub 仓库后台开启 Pages 并提交/推送本轮代码改动。
- 推荐路线：提交代码改动（不要带 `data/*.json` 本地脏改和私密文件）后，在 GitHub `Settings` -> `Pages` 选择 `Deploy from a branch`，分支 `master`，目录 `/(root)`。

## 本轮目标

- 让 AI News Radar 具备 GitHub Pages 最小静态上线条件，并给出手动开启/验收步骤。

## 本轮已完成

- 远端自动采集已跑通：GitHub Actions 定时/推送刷新 `data/*.json`。
- 本地远程展示已跑通：本地页面通过 `?dataBase=https://raw.githubusercontent.com/kunkunzi996/ai-news-radar/master/data/` 读取远端数据。
- 公众号相关默认源已移除：`wewe_rss` / `maobidao_wudaolu_backup` 不再进入默认云端采集，也不会从默认信源目录自动复活。
- Git 状态已收口：本地 `master` 已对齐远端；旧本地 OPML 触发提交保存在 `backup/local-opml-trigger-20260709-80fe98f`。
- `PROJECT_STATE.md` 已记录稳定基线。
- 本轮新增 `.nojekyll`，页面 canonical/OG/README 链接已指向 `https://kunkunzi996.github.io/ai-news-radar/`。
- 公网静态页分支已跳过 `./api/*` 本地后台请求，页面显示 `静态数据`；本机 `127.0.0.1` 采集控制台仍保持原行为。
- Playwright 用真实 Pages URL 形态模拟验收通过：首页、`assets/styles.css`、`site.webmanifest`、`data/source-status.json`、`data/latest-24h.json` 均能加载，控制台 0 错误。
- 当前真实公网 `https://kunkunzi996.github.io/ai-news-radar/` 仍返回 404，GitHub Pages API 也返回 404；说明仓库后台 Pages 尚未开启/部署。

## 本轮修改文件

- `.nojekyll`：让 GitHub Pages 原样发布静态文件。
- `index.html`：当前仓库公网 canonical/OG/GitHub 链接、前端脚本缓存号。
- `assets/js/utils.js` / `boot.js` / `render-meta.js` / `source-config.js` / `local-collect.js` / `subscriptions.js`：公网静态页跳过本地后台 API，显示 `静态数据`。
- `README.md`：GitHub Pages 最小上线地址、开启方式和验收地址。
- `PROJECT_STATE.md` / `HANDOFF.md`：记录本轮部署状态和下一步。

## 本轮未完成

- 还没有在 GitHub 网页后台开启 Pages。
- 还没有提交/推送本轮代码改动。
- 还没有处理抖音 / 小红书“非本机自动采集”；这应作为部署后单独任务。
- 本地仍有历史脏文件：`data/*.json` 本地刷新产物、未跟踪的 `计划/` review/计划文件。不要把它们混进部署提交。

## 当前项目状态

- 当前分支：`master`
- 当前远端基线：`313192b chore: update ai news snapshot`；新窗口开始时先 `git fetch origin master` 并看最新 `git status --short --branch`。
- 当前线上数据：远端 `source-status.json` 最近验收为 `3/3 源正常`，站点为 `github_foundation_sunshine_releases`、`bilibili_dynamic`、`opmlrss`。
- 当前展示方式：本地 `http://127.0.0.1:8080/` 可加 `dataBase` 参数读取远端数据；上线后目标是让公网网站直接读取同仓库 `/data/*.json`。

## 验收状态

- 已执行：
  - Python 编译与全量单测在公众号源退役任务中通过：`222 tests OK`。
  - GitHub Actions 在稳定基线提交后成功刷新。
  - 浏览器验收通过：页面显示 `远程数据`、`3/3 源正常`，无 `公众号 / WeWe RSS / 猫笔刀` 可见文本。
  - 本轮 Playwright 模拟真实 Pages URL 验收通过：静态资源和 `data/*.json` 可加载，控制台 0 错误。
  - 远端 raw `data/source-status.json` 可访问，当前为 `3/3` 源正常。
- 未执行：
  - 真实 GitHub Pages 页面还没法验收：当前公开地址仍是 404。
- 下一轮手动验收目标：
  - 打开 GitHub Pages 公网地址。
  - 应看到 AI News Radar 页面正常加载。
  - 应能读到 `data/source-status.json`，显示约 `3/3 源正常`。
  - 不需要本机 `scripts/local_server.py` 或 `127.0.0.1:8080`。

## Git 状态提醒

- 下一轮开始必须先运行：`git status --short --branch`
- 不要提交：
  - `data/*.json` 本地刷新产物，除非明确是在处理 Actions 自动数据提交。
  - `sources.config.json`
  - `feeds/follow.opml`
  - `local-secrets/`
  - cookie、token、`.env`、浏览器 profile、MediaCrawler 登录态。

## 下一轮建议任务

1. 只提交本轮代码/文档改动，明确排除 `data/*.json` 和 `计划/` 下历史脏文件。
2. 推送到 `origin/master`。
3. 在 GitHub 仓库后台 `Settings` -> `Pages` 选择 `Deploy from a branch`，分支 `master`，目录 `/(root)`。
4. 等 Pages 部署完成后，验收公网 URL、`assets/styles.css`、`data/source-status.json`。

## 下一轮建议调用

- `kun-coding-router`
- `references/16-task-routing-map.md` 第 7 节“部署 / 上线”
- `references/10-codex-safe-construction.md`
- `references/12-verification-git-report.md`
- 如改动页面数据路径，再用 `browser:control-in-app-browser` 做真实页面验收。

## 下一轮必须先读

- `AGENTS.md`
- `PROJECT_STATE.md`
- `HANDOFF.md`
- `README.md`
- `docs/SOURCE_COVERAGE.md`
- `.github/workflows/update-news.yml`
- 如需要改页面：`index.html`、`assets/js/dom.js`、`assets/js/utils.js`、`assets/js/boot.js`

## 下一轮禁止事项

- 不要把 `scripts/local_server.py` 当成公网服务发布。
- 不要提交私密订阅、cookie、token、`.env`、`sources.config.json`、`feeds/follow.opml`。
- 不要把本地 `data/*.json` 脏改混进部署提交。
- 不要恢复公众号默认源。
- 不要在 GitHub Pages 第一版里解决抖音 / 小红书非本机采集；先把静态网站上线跑通。
- 不要批量删除文件或目录；如确实要删除，必须一次一个明确路径，并说明原因。

## 当前风险 / 待确认

- GitHub Pages 是否已经开启，需要用户在 GitHub 网页后台确认或由下一轮指导操作。
- 如果仓库是项目页而不是用户页，公网路径可能是 `/ai-news-radar/`，需要确认静态资源和数据路径是否兼容项目子路径。
- 抖音 / 小红书目前仍是本机 MediaCrawler/JSONL 路线，不属于 GitHub Pages 第一阶段能力。

## 下一轮 Codex 入口

使用 Kun Coding Router 继续当前项目。

任务：把 AI News Radar 做成 GitHub Pages 最小上线版。

请先读取：
1. `AGENTS.md`
2. `PROJECT_STATE.md`
3. `HANDOFF.md`
4. `README.md`
5. `.github/workflows/update-news.yml`

本轮只做：
- GitHub Pages 最小上线。
- 确认公网页面能加载静态资源和 `data/*.json`。
- 给用户清晰的手动验收步骤。

本轮不做：
- 抖音 / 小红书非本机采集。
- 公众号采集恢复。
- 大重构。
- 提交本地生成数据或任何私密文件。

## 历史 Handoff 摘要（仅查旧问题时阅读）

## 2026-07-08：结构优化第二轮任务1/2/3/4已提交，下一轮从任务5开始

- 日期：2026-07-08
- 当前阶段：结构优化第二轮已完成任务1、任务2、任务3、任务4；不要继续重复任务1/2/3/4。下一轮从任务5开始。
- 主项目路径：`E:\AI-news-reader\ai-news-radar-run`
- 当前分支：`master`
- 已推送提交：
  - `1774f99 chore: 完成结构优化任务1和任务2`
  - `1c75813 refactor: 拆分新闻更新命令主流程`
- 本地未推送提交：
  - `6b171f3 refactor: 拆分前端渲染模块`
- 本轮已完成：
  - 任务1：新增 Playwright 冒烟测试防护网，`npm run test:e2e` 可跑本地页面基础加载、tab 切换和时间范围筛选。
  - 任务2：移除 `wire_modules` / `_wire_server_modules` 动态注入，改为显式导入；拆出 `scripts/radar/server/common.py`；清理 fetchers/server 之间的违规依赖。
  - 任务3：拆分 `scripts/radar/cli.py` 的超长 `main()`，新增阶段函数 `parse_cli_args`、`prepare_run_context`、`collect_stage`、`merge_archive_stage`、`enrich_stage`、`write_outputs_stage`，并新增 `[timing]` 输出。
  - 任务3 review 修复：`build_latest_payloads(latest_payload)` 重复调用已修掉，现在只有 `enrich_stage()` 内一次实际调用。
  - 任务4：已将 `assets/js/render.js` 三分为 `render-meta.js`、`render-list.js`、`render-panels.js`，`index.html` 已按 `render-meta -> render-list -> render-panels` 顺序加载，版本号统一为 `render-split-0707a`，旧 `assets/js/render.js` 已删除。
- 任务3最终验收：
  - `rg -n "build_latest_payloads" scripts/radar/cli.py`：1 个 import，1 个实际调用。
  - `.\.venv\Scripts\python.exe -m pyflakes scripts\radar\cli.py`：0 输出。
  - `Compare-Object help_before/help_after`：无差异。
  - `.\.venv\Scripts\python.exe -m unittest discover -s tests -q`：221 tests OK。
  - `npm run test:e2e`：2 passed。
  - 真实刷新通过，终端出现 `[timing] collect=5.0s merge=0.8s enrich=0.2s write=0.2s total=6.3s`。
  - 刷新后 `data/source-status.json.generated_at=2026-07-08T02:35:34.825561Z`，`latest-24h.json` 150 条，没有异常清零；`latest-24h-all.json` 结构正常，`items_all` 341 条。
- 当前风险 / 待确认：
  - 真实刷新后 `opmlrss` 失败，错误为 `2 feeds failed`，两个失败项都是 YouTube RSS feed。用户已确认可接受，不阻塞任务3提交。
  - 当前工作区仍有 `data/*.json` 刷新产物未提交；除非用户明确允许提交数据快照，否则不要把它们混进后续任务提交。
  - `计划\结构优化第二轮实施计划.md` 是施工计划留档；当前实际进度以 HANDOFF.md 最新交接为准，不要默认提交它。
- 本轮清理：
  - 已按用户“不保留”删除临时 review diff 和 help 文件：`计划\help_before_task3.txt`、`计划\help_after_task3.txt`、`计划\review-task1-task2-fixed-no-data.diff`、`计划\review-task1-task2-no-data.diff`、`计划\task1-task2-review.diff`、`计划\task3-cli-split-review.diff`、`计划\task3-cli-split-review-fixed.diff`。
  - 未删除施工计划原文 `计划\结构优化第二轮实施计划.md`。
- 下一轮建议任务：
  1. 先运行 `git status --short`，确认本地未推送提交、`data/*.json` 和计划目录未跟踪文件的真实状态。
  2. 如果用户确认任务4验收通过，再决定是否 push 本地提交 `6b171f3`。
  3. 用户明确确认进入任务5后，再执行 `PROJECT_STATE.md` 瘦身和工作区空壳清理；不要重复任务4。
- 下一轮必须先读：
  - `PROJECT_STATE.md`
  - `HANDOFF.md`
  - `计划\结构优化第二轮实施计划.md`
  - `index.html`
- 下一轮禁止事项：
  - 不要继续任务5。
  - 不要提交 `data/*.json`，除非用户明确允许。
  - 不要删除施工计划原文。
  - 不要改 `sources.config.json`、`local-secrets/`、`assets/motion.js`、`scripts/ai_relevance.py`、`scripts/run_mediacrawler_douyin.py`。
  - 删除文件必须逐个明确路径执行；任务4若删除 `assets/js/render.js`，必须先确认三个新文件对账通过。
- 下一轮 Codex 入口：
  - 使用 Kun Coding Router 继续当前项目。
  - 下一轮任务：在用户明确确认后进入任务5；不要重复执行任务4。
  - 验收重点：任务5只做文档瘦身和明确空壳清理；不要改业务代码、不要提交 `data/*.json`。

## 当前最新交接：匿名用户996 已跑到账号但公开视频为 0

- 日期：2026-07-07
- 当前阶段：已复查并真实重跑。现在本地链路能把 4 个抖音账号都交给 MediaCrawler，`匿名用户996` 也被 MediaCrawler 成功解析到；但抖音侧返回该账号 `videos_count=0`，所以内容 JSONL 没有它的视频，主看板也不会显示。
- 主项目路径：`E:\AI-news-reader\ai-news-radar-run`
- 当前分支：`master`
- 本轮原因判断：
  - 之前 12:28 那轮失败，是 MediaCrawler 访问本机 CDP `localhost:9333` 时被 `ALL_PROXY=socks5://127.0.0.1:4780` 误导去走 SOCKS，但环境缺 `socksio`，随后回退标准 Playwright 又缺浏览器包。
  - 本轮已让 `scripts/run_mediacrawler_douyin.py` 对本机 CDP 设置 `NO_PROXY/no_proxy`，并移除 SOCKS 型 `ALL_PROXY/all_proxy`，避免本机连接再走 SOCKS。
  - 本轮还把抖音主页 URL 在启动前规范成纯 `sec_uid`，避免整条 URL 查询参数影响 MediaCrawler 多账号解析。
- 本轮真实验收：
  - 已重启本地 8080 服务：PID `31988` -> `33288`，`/api/local-status` 正常。
  - 已触发 `start_mediacrawler_douyin`：PID `33856`。
  - MediaCrawler 日志确认解析 4 个账号：Simon林、珍妮丁丁说AI、FredTalk、匿名用户996。
  - `creator_creators_2026-07-07.jsonl` 里有 `匿名用户996`，但 `videos_count=0`。
  - `creator_contents_2026-07-07.jsonl` 共 25 行：Simon林 10、珍妮丁丁说AI 10、FredTalk 5、匿名用户996 0。
  - 已刷新看板数据；`data/source-status.json` 里 `匿名用户996 item_count=0`，错误为 `mediacrawler_douyin_no_items`。
- 下一步：
  - 用采集专用 Chrome profile 打开 `匿名用户996` 主页，确认这条视频是不是公开视频、是否已过审、是否仅自己可见/朋友可见、是否被新号风控限制展示。只要该 profile 看到主页公开视频数仍是 0，本项目就读不到。

## 当前最新交接：网页端快速重启本地服务按钮

- 日期：2026-07-07
- 当前阶段：已新增网页端 `重启本地服务` 按钮，用于让 8080 本地后台加载最新代码，不再需要用户手动找 PowerShell 窗口按 Ctrl+C。
- 主项目路径：`E:\AI-news-reader\ai-news-radar-run`
- 当前分支：`master`
- 本轮改动：
  - `index.html`：在信源配置 / 本地采集工具栏新增 `重启本地服务` 按钮，并把 `assets/app.js` 缓存号更新为 `local-server-restart-0707a`。
  - `assets/app.js`：点击按钮后调用 `POST /api/restart-local-server`，显示重启状态，等待 `/api/local-status` 恢复后自动刷新页面。
  - `scripts/local_server.py`：新增本地-only 重启接口；沿用非本地来源拦截；如果正在刷新看板数据则返回 `refresh_already_running`；实际重启通过一个临时 Python helper 在旧服务退出后重新启动当前命令，不杀其它进程。
  - `tests/test_local_server.py`：新增重启命令复用当前 Python 和参数的单测。
- 本轮验收：
  - `.\.venv\Scripts\python.exe -m py_compile scripts\local_server.py` 通过。
  - `node --check assets\app.js` 通过。
  - `.\.venv\Scripts\python.exe -m unittest tests.test_local_server -q` 通过：64 tests OK。
  - 真实接口验收通过：`POST /api/restart-local-server` 返回 202；8080 从 PID 28940 切到 PID 30548；随后 `/api/local-status` 返回 OK。
- 下一轮手动验收：
  - 先用原来的方式启动一次本地服务：`.\.venv\Scripts\python.exe scripts\local_server.py --host 127.0.0.1 --port 8080`。
  - 打开 `http://127.0.0.1:8080/`，强刷，确认页面加载的是 `assets/app.js?v=local-server-restart-0707a`。
  - 展开 `信源配置`，点击 `重启本地服务`。
  - 预期：按钮显示重启中，几秒后页面自动刷新；之后点 `检查状态` 能正常读到本地采集状态。
- 风险点：
  - 如果正在 `刷新看板数据`，接口会拒绝重启；需要等刷新结束后再点。

## 当前最新交接：抖音新增账号启动采集只抓第一个账号修复

- 日期：2026-07-07
- 当前阶段：已定位并修复“新增抖音测试账号 `匿名用户996` 后，采集完页面不显示”的启动链路问题。
- 主项目路径：`E:\AI-news-reader\ai-news-radar-run`
- 当前分支：`master`
- 根因：`sources.config.json` 里已经有 4 个启用的抖音账号，包括 `匿名用户996`；但 `scripts/local_server.py` 启动 MediaCrawler 时，`mediacrawler_creator_id()` 只返回第一个启用的抖音主页 URL。结果 MediaCrawler 实际没有收到 `匿名用户996`，最新导出 `creator_contents_2026-07-07.jsonl` 也只包含 Simon林 和 珍妮丁丁说AI，`data/source-status.json` 对 `匿名用户996` 报 `item_count=0`。
- 本轮改动：
  - `scripts/local_server.py`：启动 MediaCrawler 时，把所有启用的抖音主页 URL 用逗号拼起来传给 `--creator-id`；MediaCrawler 自身已经支持多个 creator。
  - `tests/test_local_server.py`：新增回归测试，确保两个启用抖音主页会同时进入启动命令。
  - `PROJECT_STATE.md` / `HANDOFF.md`：记录根因、修复和下一轮验收入口。
- 本轮验收：
  - `.\.venv\Scripts\python.exe -m py_compile scripts\local_server.py` 通过。
  - `node --check assets\app.js` 通过。
  - `.\.venv\Scripts\python.exe -m unittest tests.test_local_server -q` 通过：63 tests OK。
  - 当前真实配置 dry-run：`creator_count=4`，且包含 `匿名用户996` 的 creator 前缀；`collect_window=24`，`max_notes=5`。
- 下一轮手动验收：
  - 如果 `http://127.0.0.1:8080/` 已经开着，先重启本地服务，让它加载新的 `scripts/local_server.py`。
  - 打开 `http://127.0.0.1:8080/`，展开 `信源配置` / 本地采集概览，点 `启动抖音采集`。
  - 采集完成后点 `刷新看板数据`。
  - 预期：`data/source-status.json` 的 `mediacrawler_douyin.subscriptions` 里，`匿名用户996 item_count>0`；页面 `抖音` 栏目能看到该小号公开视频。
- 仍需注意：
  - 如果修复后真实重跑仍是 `item_count=0`，下一步就不是本项目桥接问题，而要检查该视频是否公开、是否已过审、采集专用 Chrome profile 是否能访问这个小号主页、以及抖音是否对新/小号内容做了可见性限制。

## 当前最新交接：微信公众号功能先隐藏

- 日期：2026-07-07
- 当前阶段：已按用户要求把微信公众号相关功能先隐藏起来；订阅源不稳定时，不再让它污染首页、订阅管理、源配置和维护状态。
- 主项目路径：`E:\AI-news-reader\ai-news-radar-run`
- 当前分支：`master`
- 本轮改动：
  - `assets/app.js`：新增可逆隐藏名单，当前隐藏平台为 `wechat`，隐藏源为 `wewe_rss` / `maobidao_wudaolu_backup`。
  - `assets/app.js`：顶部栏目、订阅成员平台 Tab、高级信源筛选/列表/统计、本地采集概览、源健康、失败源/维护项、站点筛选和最终渲染列表，都不再展示公众号相关内容。
  - `sources.config.json`：将 `wewe_rss_maobidao.enabled` 改为 `false`，以后刷新默认不会再请求 WeWe RSS sidecar。
  - `index.html`：更新 `assets/app.js` 缓存版本号到 `hide-wechat-source-0707a`。
- 验收重点：
  - 打开 `http://127.0.0.1:8080/` 强刷后，顶部不应再有 `微信公众号` 栏目。
  - 展开信源配置/订阅成员管理时，不应再出现公众号筛选和公众号平台 Tab。
  - 本地采集状态里不应再因为 `127.0.0.1:4000` 的 WeWe RSS 连接失败而显示公众号维护项。
- 本轮验收：
  - `node --check assets\app.js` 通过。
  - `GET http://127.0.0.1:8080/api/source-config` 返回 `wewe_rss_maobidao.enabled=false`。
  - `GET http://127.0.0.1:8080/index.html` 已服务 `assets/app.js?v=hide-wechat-source-0707a`。
  - Playwright 页面检查：正文不含 `微信公众号 / 公众号 / WeWe RSS / 猫笔刀`，仍保留 `B站` 和 `油管/YouTube` 入口；顶部 tabs 为 `我的订阅304 / 抖音5 / 小红书5 / B站279 / 油管10 / 已阅0`。
- 恢复方式：把 `assets/app.js` 里的 `HIDDEN_PLATFORM_IDS` / `HIDDEN_SOURCE_IDS` 移除对应项，并把 `sources.config.json` 的 `wewe_rss_maobidao.enabled` 改回 `true`。

## 当前最新交接：订阅栏目 24 小时时间筛选修复

- 日期：2026-07-06
- 当前阶段：已修复“选择 `过去 24 小时` 后，B站和油管仍显示全量订阅历史”的前端筛选问题。
- 主项目路径：`E:\AI-news-reader\ai-news-radar-run`
- 当前分支：`master`
- 根因：`assets/app.js` 的 `setActiveSection()` 在进入 `我的订阅 / B站 / 油管 / 已阅` 等订阅栏目时，会强制把 `state.timeRangeFilter` 改回 `all`。所以用户刚选了 24h，点进 B站/油管又被前端悄悄切回“不限”。采集数据本身不是根因。
- 本轮改动：
  - `assets/app.js`：删除订阅栏目强制重置时间范围的逻辑，保留用户选择的 `24h` / `不限`。
  - `index.html`：更新 `assets/app.js` 缓存版本号到 `subscription-time-filter-0706a`。
  - `PROJECT_STATE.md` / `HANDOFF.md`：记录根因和验收入口。
- 本轮验收：
  - `node --check assets\app.js` 通过。
  - 当前数据直接计算：`B站 all=279 last24=1`，`油管 all=10 last24=0`，`generated_at=2026-07-06T14:22:44.284161Z`。
  - 真实页面 `http://127.0.0.1:8080/` 已服务 `assets/app.js?v=subscription-time-filter-0706a`。
  - Playwright + Edge 验证：默认不限时 tabs 为 `我的订阅326 / B站279 / 油管10`；切换 24h 后 tabs 为 `我的订阅1 / B站1 / 油管0`；进入 B站保持 `timeRangeSelect=24h` 且 `result=1 条`；进入油管保持 `timeRangeSelect=24h` 且 `result=0 条`。
- 下一轮手动验收：
  - 打开 `http://127.0.0.1:8080/` 并强刷。
  - 展开 `高级筛选`，把 `时间范围` 从 `不限` 改成 `过去 24 小时`。
  - 预期：顶部栏目数量同步变成最近 24 小时口径；进入 `B站` 不再回到 279 全量；进入 `油管` 不再回到 10 全量。

## 当前最新交接：B站“分享动态”已阅误伤修复

- 日期：2026-07-06
- 当前阶段：已修复“点一条 B站 `分享动态` 已阅后，所有同标题动态都进入已阅”的前端读状态问题。
- 主项目路径：`E:\AI-news-reader\ai-news-radar-run`
- 当前分支：`master`
- 根因：已阅状态复用了 `itemIdentityKeys()` 里的宽泛事件/标题 key。`title:分享动态` / `event:title:分享动态` 对故事聚合有用，但对“单张卡片已阅”太粗，导致同标题 B站动态互相误判。
- 本轮改动：
  - `assets/app.js`：新增已阅专用强身份逻辑，优先使用 `url`、后端 `id`、`bilibili_dynamic_id`、`bilibili_opus_id`；只有没有强身份时才使用非泛化标题兜底。
  - `index.html`：更新 `assets/app.js` 缓存版本号到 `read-key-specificity-fix-0706a`。
- 本轮验收：
  - `node --check assets\app.js` 通过。
  - 真实数据检查：`技术爬爬虾 / 分享动态` 共 59 条，按新逻辑有 59 个唯一强身份 key，且无空 key。
  - `http://127.0.0.1:8080/` 已服务 `assets/app.js?v=read-key-specificity-fix-0706a`。
- 下一轮手动验收：
  - 打开 `http://127.0.0.1:8080/`，强刷页面。
  - 进入 `B站`，找到 `技术爬爬虾` 的一条 `分享动态`，点 `已阅`。
  - 预期：只这一条消失；其它 `分享动态` 仍留在 B站列表里。切到 `已阅`，应只看到刚点的那条，点 `恢复` 后它回到列表。

## 当前最新交接：抖音/小红书刷新后消失的配置回退修复

- 日期：2026-07-06
- 当前阶段：已修复“刷新看板数据后抖音和小红书消失”的本地配置回退问题，并完成真实刷新验收。
- 主项目路径：`E:\AI-news-reader\ai-news-radar-run`
- 当前分支：`master`
- 根因：MediaCrawler 今天的抖音/小红书 JSONL 实际存在且非空；问题出在刷新前页面把一个旧的高级信源草稿写回 `sources.config.json`，导致 `mediacrawler_douyin` / `mediacrawler_xhs` 被关闭，B站也从 4 个 UP 回退到 2 个。刷新脚本随后严格按旧配置重建数据，所以页面不再显示这两个平台。
- 本轮改动：
  - `assets/app.js`：浏览器草稿只因 seed/catalog 自动合并而变化时，不再把 `updated_at` 刷成当前时间，避免旧草稿假装比磁盘配置更新。
  - `index.html`：更新 `assets/app.js` 缓存版本号到 `source-config-draft-fix-0706a`。
  - `sources.config.json`：本机私有配置已恢复为启用 OPML、4 个 B站 UP、抖音、小红书、微信公众号、GitHub Release。
  - `data/*.json`：已通过本地 8080 后台真实刷新重新生成。
- 本轮验收：
  - `node --check assets\app.js` 通过。
  - `.\.venv\Scripts\python.exe -m py_compile scripts\local_server.py scripts\update_news.py` 通过。
  - `.\.venv\Scripts\python.exe -m unittest tests.test_local_server tests.test_topic_filter tests.test_private_bridge_sources -q` 通过：190 tests OK。
  - `POST http://127.0.0.1:8080/api/refresh` 通过，生成 `data/latest-24h-all.json` 320 条。
  - `http://127.0.0.1:8080/data/source-status.json` 显示 `mediacrawler_douyin.ok=true item_count=5`、`mediacrawler_xhs.ok=true item_count=5`。
  - `http://127.0.0.1:8080/data/latest-24h-all.json` 显示 `mediacrawler_douyin=5`、`mediacrawler_xhs=5`。
- 下一轮手动验收：
  - 打开 `http://127.0.0.1:8080/`，强刷页面，确认 HTML 加载 `assets/app.js?v=source-config-draft-fix-0706a`。
  - 进入 `抖音` 和 `小红书` 栏目，确认能看到 `珍妮丁丁说AI` / `中二的大暄哥` 相关内容。
  - 下次点 `刷新看板数据` 后，再查 `信源配置` 中抖音和小红书不要被自动关掉。

## 当前最新交接：B站新订阅首批入库 + 已阅状态稳定性修复

- 日期：2026-07-06
- 当前阶段：已修复“新增 B站 UP 后一键采集没有刷新出动态”和“刷新后已阅状态容易失效”的核心路径；用户已在本地页面验收成功。
- 主项目路径：`E:\AI-news-reader\ai-news-radar-run`
- 当前分支：`master`
- 根因：
  - B站采集实际能抓到新 UP 的原始动态，但 `自上次采集` 窗口会按发布时间过滤；如果新 UP 最近 9 小时没有新动态，它的历史最新内容就不会首次进入归档。
  - `已阅` 原来主要按单个 identity key 判断；刷新后同一条内容如果从不同数据池/字段形态渲染，可能认不回原来的已阅记录。
- 本轮改动：
  - `scripts/update_news.py`：采集窗口过滤新增 `archive_source_counts()` 保护，归档里从未出现过或首批不足 5 条的订阅对象会补齐首批内容；B站动态 id / opus id 也会进入公开安全字段。
  - `assets/app.js`：已阅读写改为多 key 匹配/写入，包含 URL、后端 id、B站动态 id / opus id、标题事件 key。
  - `index.html`：更新 `assets/app.js` 缓存版本号。
  - `tests/test_topic_filter.py`：新增“新订阅首批内容不被窗口误挡”和“首批不足时继续补到 5 条”的回归测试。
  - `data/*.json`：已用带 B站 cookie 的 `cookie_full_dynamic` 口径真实刷新；`清华姜学长` 已进入 `data/archive.json` 和 `data/latest-24h-all.json`，归档首批 5 条。
- 本轮验收：
  - `node --check assets\app.js` 通过。
  - `.\.venv\Scripts\python.exe -m py_compile scripts\update_news.py scripts\local_server.py` 通过。
  - `.\.venv\Scripts\python.exe -m unittest tests.test_topic_filter.TopicFilterTests.test_collect_window_filters_new_raw_items_by_publish_time tests.test_topic_filter.TopicFilterTests.test_collect_window_keeps_first_batch_for_new_subscription_source tests.test_topic_filter.TopicFilterTests.test_collect_window_tops_up_underseeded_subscription_source -q` 通过。
  - `.\.venv\Scripts\python.exe -m unittest tests.test_topic_filter tests.test_private_bridge_sources tests.test_local_server -q` 通过：190 tests OK。
  - 带 B站 cookie 的真实刷新命令 `.\.venv\Scripts\python.exe scripts\update_news.py --source-config sources.config.json --output-dir data --window-hours 24 --archive-days 3650 --all-time --collect-window-hours 9` 通过；`data/source-status.json` 显示 B站 `fetch_mode=cookie_full_dynamic`、4 个 UP 都 OK、每个 5 条。
  - HTTP 验证 `http://127.0.0.1:8080/data/latest-24h-all.json` 包含 `清华姜学长`。
  - 用户手动验收成功。
- 下一轮手动验收：
  - 打开 `http://127.0.0.1:8080/`，强刷页面，确认加载的是 `assets/app.js?v=read-state-seed-fix-0706a`。
  - 进入 `我的订阅` 或 `B站`，搜索/查看 `清华姜学长`。
  - 点几条订阅卡片 `已阅`，再点 `刷新看板数据` 或刷新页面，确认它们不会回到未读列表；在 `已阅` 栏目点 `恢复` 应能回来。
- 下一轮注意：
  - 推荐固定使用 `http://127.0.0.1:8080/`；浏览器会把 `localhost:8080` 和 `127.0.0.1:8080` 的 localStorage 分开。
  - 已阅状态当前仍是浏览器本地 localStorage；如果未来部署到服务器并且公司/家里多设备使用，建议做“单用户服务器端已阅同步”，否则不同电脑/浏览器仍会各记各的。

## 当前最新交接：本地采集新增可见进度条

- 日期：2026-07-06
- 当前阶段：`刷新看板数据` 已从同步等待改为后台任务；页面会轮询 `/api/refresh-progress`，在 `本地采集` 面板顶部显示进度条、当前步骤、粗略剩余时间和最近步骤日志。`一键采集` 在抖音、小红书和最终看板刷新之间也会写入可见小字提示。
- 主项目路径：`E:\AI-news-reader\ai-news-radar-run`
- 当前分支：`master`
- 本轮改动：
  - `scripts/local_server.py`：新增刷新进度状态、步骤计划、后台刷新线程、`GET /api/refresh-progress`，并让 `/api/local-status` 透传 `refresh_progress`。
  - `assets/app.js`：新增本地采集进度卡渲染、刷新进度轮询、刷新完成后再更新概览并重载；一键采集会追加平台完成日志。
  - `assets/app.js` follow-up：一键采集轮询抖音/小红书时，后端 `idle` 进度不再覆盖当前前端进度；普通页面刷新后也不会展示上一轮遗留的 `completed` 进度条。
  - `assets/styles.css` / `index.html`：新增紧凑进度条容器和样式。
  - `tests/test_local_server.py`：补进度步骤计划测试。
- 本轮验收：
  - `node --check assets\app.js` 通过。
  - `.\.venv\Scripts\python.exe -m py_compile scripts\local_server.py` 通过。
  - `.\.venv\Scripts\python.exe -m unittest tests.test_local_server -q` 通过：62 tests OK。
  - `.\.venv\Scripts\python.exe -m unittest discover -s tests -q` 通过：213 tests OK。
  - 重启 `http://127.0.0.1:8080/` 本地服务后，`GET /api/refresh-progress` 返回 `ok=true` 和 idle progress JSON；Playwright CLI 可正常截取本地页面。
  - Follow-up 验收：`node --check assets\app.js` 通过；`.\.venv\Scripts\python.exe -m unittest tests.test_local_server -q` 通过；Playwright 截图确认刷新页面后首屏不再显示旧进度条。
- 下一轮建议入口：
  - 先读 `PROJECT_STATE.md` 和本文件。
  - 手动验收：打开 `http://127.0.0.1:8080/`，展开 `信源配置`，点 `刷新看板数据`，确认 `本地采集` 顶部出现进度条、小字日志和百分比；完成后页面自动刷新。
  - Follow-up 手动验收：页面刚刷新、未开始采集时不应显示旧进度条；点击 `一键采集` 后，抖音/小红书阶段的进度条不应被轮询刷新隐藏。
- 下一轮注意：
  - 进度条的刷新阶段是本地后台的步骤级进度，能告诉用户当前在处理哪类订阅源和大概剩余时间；它不是每条具体内容的逐条计数器。
  - 不要把当前已有 `data/*.json` 脏改一股脑提交。

## 当前最新交接：本地状态接口补齐窗口/原始口径

- 日期：2026-07-06
- 当前阶段：`data/source-status.json` 已经有每个站点的 `raw_item_count`、`window_item_count` 和 `collection_window_hours`，现在 `/api/local-status` 也会把这些字段透传给前端，避免页面只看到“原始”看不到“窗口”。
- 主项目路径：`E:\AI-news-reader\ai-news-radar-run`
- 当前分支：`master`
- 本轮改动：
  - `scripts/local_server.py`：`source_status_summary()` 保留全局窗口字段和每个站点的原始/窗口数量、最近 5 条上限元数据。
  - `tests/test_local_server.py`：新增接口摘要字段透传测试。
  - `PROJECT_STATE.md` 更新当前状态。
- 本轮验收：
  - `.\.venv\Scripts\python.exe -m py_compile scripts\local_server.py scripts\update_news.py` 通过。
  - `.\.venv\Scripts\python.exe -m unittest tests.test_local_server -q` 通过：61 tests OK。
  - `.\.venv\Scripts\python.exe -m unittest discover -s tests -q` 通过：212 tests OK。
  - `node --check assets/app.js` 通过。
- 下一轮建议入口：
  - 先读 `PROJECT_STATE.md` 和本文件。
  - 如果浏览器仍显示旧字段，先重启 `scripts/local_server.py --host 127.0.0.1 --port 8080`，再刷新页面。
- 下一轮注意：
  - 当前真实数据里多个站点是 `原始 > 0 / 窗口 = 0`，含义是“抓到了最近 5 条原始候选，但它们发布时间不在自上次采集窗口内”。
  - 不要把当前已有 `data/*.json` 脏改一股脑提交。

## 历史交接：订阅采集统一最近 5 条和窗口/原始口径

- 日期：2026-07-06
- 当前阶段：YouTube/OPML、B站动态、GitHub Release 的采集上限已向抖音/小红书靠齐：先尽量只取最近 5 条，再走 `--collect-window-hours` 的“自上次采集”过滤。GitHub 原本就是 5 条，本轮主要补齐 YouTube/OPML 和 B站默认值。
- 主项目路径：`E:\AI-news-reader\ai-news-radar-run`
- 当前分支：`master`
- 本轮改动：
  - `scripts/update_news.py`：`BILIBILI_DYNAMIC_DEFAULT_MAX_ITEMS` 从 20 改为 5；OPML/RSS 每个 feed 解析后按发布时间倒序只保留最近 5 条；过滤窗口前后给每个站点状态补 `raw_item_count`、`window_item_count`、`collection_window_hours`。
  - `assets/app.js`：本地采集概览优先用新状态字段显示 `窗口 X / 原始 Y`，旧状态文件没有新字段时仍兼容显示原始数量。
  - `.github/workflows/update-news.yml` 和 `docs/guides/bilibili-dynamic-source.md`：同步 B站默认上限为 5。
  - `tests/test_private_bridge_sources.py`：补 OPML 最近 5 条和 B站默认 5 条测试。
  - `PROJECT_STATE.md` 更新当前状态。
- 本轮验收：
  - `node --check assets/app.js` 通过。
  - `.\.venv\Scripts\python.exe -m py_compile scripts\update_news.py` 通过。
  - `.\.venv\Scripts\python.exe -m unittest tests.test_private_bridge_sources -q` 通过：37 tests OK。
  - `.\.venv\Scripts\python.exe -m unittest discover -s tests -q` 通过：211 tests OK。
- 下一轮建议入口：
  - 先读 `PROJECT_STATE.md` 和本文件。
  - 手动验收：打开 `http://127.0.0.1:8080/`，点 `刷新看板数据` 或 `一键采集` 跑一次；刷新后展开 `信源配置`，确认 YouTube/B站/GitHub 也显示 `窗口 X / 原始 Y`。
- 下一轮注意：
  - 当前磁盘上的旧 `data/source-status.json` 是本轮代码修改前生成的，里面还没有每站点 `window_item_count`；需要下一次真实刷新后才会出现新口径。
  - 不要把当前已有 `data/*.json` 脏改一股脑提交。

## 当前最新交接：订阅源采集概览改为平台层级

- 日期：2026-07-06
- 当前阶段：`信源配置` 里的 `订阅源采集概览` 已从“所有订阅源平铺”改成“平台一级 + 订阅源二级”。一级展示 YouTube 订阅、B站动态、抖音、小红书、微信公众号、GitHub Release；点开一级后显示具体订阅对象。
- 主项目路径：`E:\AI-news-reader\ai-news-radar-run`
- 当前分支：`master`
- 本轮改动：
  - `assets/app.js` 新增本地采集概览的分组逻辑，按运行时源归并到平台一级，并用 `<details>` 展开二级订阅源。
  - YouTube 二级明细从 `/api/subscriptions/youtube` 读取 OPML 订阅；B站二级明细从统一的 B站动态配置拆出 UP 主；抖音、小红书、微信公众号、GitHub 沿用各自 source record。
  - 展开后的二级行继续复用原有状态、最近刷新、采集结果和维护 issue；抖音/小红书仍保留 `启动采集` 按钮。
  - `assets/styles.css` 新增一级/二级行样式和缩进。
  - `PROJECT_STATE.md` 更新当前状态。
- 本轮验收：
  - `node --check assets/app.js` 通过。
  - `git diff --check -- assets/app.js assets/styles.css PROJECT_STATE.md HANDOFF.md` 通过，仅有 Windows LF/CRLF warning。
  - Playwright 打开 `http://127.0.0.1:8080/`，展开 `信源配置` 后确认一级分组显示 YouTube、B站、抖音、小红书、微信公众号、GitHub；点开 YouTube 显示 2 个频道，点开 B站显示 3 个 UP 主，点开抖音显示 3 个账号，点开微信公众号显示猫笔刀和数字生命卡兹克各自维护提示。
- 下一轮建议入口：
  - 先读 `PROJECT_STATE.md` 和本文件。
  - 手动验收：打开 `http://127.0.0.1:8080/`，展开 `信源配置`，逐个点开平台一级行，确认二级订阅对象符合当前订阅配置。
- 下一轮注意：
  - 抖音多个账号、小红书账号目前仍共享平台级 MediaCrawler collector 统计；二级行能显示账号归属，但采集数量仍是平台级统计。
  - 不要把当前已有 `data/*.json` 脏改一股脑提交。

## 当前最新交接：本地采集面板汇总所有订阅源

- 日期：2026-07-05
- 当前阶段：`信源配置` 里的本地采集面板不再只展示抖音/小红书采集卡片，而是新增一张紧凑的 `订阅源采集概览` 汇总卡，把当前启用的所有订阅源按行展示出来。
- 主项目路径：`E:\AI-news-reader\ai-news-radar-run`
- 当前分支：`master`
- 本轮改动：
  - `assets/app.js` 的本地采集状态渲染改为优先使用 `/api/local-status` 返回的 `source_config.enabled_sources`，并结合 `source_status.sites`、`maintenance_issues` 和 MediaCrawler collector 摘要生成每个订阅源的状态行。
  - 每行显示订阅源名称、平台、状态、采集结果、最近更新时间和操作/维护提示；抖音和小红书仍保留 `启动采集` 操作。
  - WeWe RSS 多公众号共用同一个运行时源时，会优先用公众号名称匹配各自的维护 issue，避免两个公众号都显示同一个失败原因。
  - `assets/styles.css` 新增汇总卡和行布局样式，避免给每个订阅源单独做大卡片。
  - `PROJECT_STATE.md` 更新当前状态。
- 本轮验收：
  - `node --check assets/app.js` 通过。
  - `git diff --check -- assets/app.js assets/styles.css PROJECT_STATE.md HANDOFF.md` 通过，仅有 Windows LF/CRLF warning。
  - Playwright 打开 `http://127.0.0.1:8080/`，展开 `信源配置` 后确认汇总卡显示 `9 个订阅源`；油管、B站、抖音、小红书、微信公众号、GitHub Release 都在同一张卡内；猫笔刀和数字生命卡兹克分别显示自己的公众号读取失败提示。
- 下一轮建议入口：
  - 先读 `PROJECT_STATE.md` 和本文件。
  - 手动验收：打开 `http://127.0.0.1:8080/`，展开 `信源配置`，确认 `订阅源采集概览` 只有一张汇总卡，并检查每行状态是否符合当前 `/api/local-status`。
- 下一轮注意：
  - 抖音多个账号、小红书账号目前仍共享平台级 MediaCrawler collector 统计；这张概览卡展示的是平台级采集结果，不是每个创作者单独的 JSONL 命中数。
  - 不要把当前已有 `data/*.json` 脏改一股脑提交。

## 当前最新交接：采集窗口已改为自上次采集

- 日期：2026-07-05
- 当前阶段：本地采集范围下拉中原 `过去24小时` 已改为 `自上次采集`；内部值仍是 `24h`，所以一键采集和手动刷新继续走原有接口，只是后端传给 `update_news.py` 的 `--collect-window-hours` 不再固定为 24。
- 主项目路径：`E:\AI-news-reader\ai-news-radar-run`
- 当前分支：`master`
- 本轮改动：
  - `scripts/local_server.py` 新增 `last_collection_time()`、`resolve_collect_window_hours()`、`collect_window_hours_for_scope()`，从上一次 `data/source-status.json.generated_at` 算本轮采集窗口，向上取整小时数。
  - 缺失、非法、未来时间戳都会回退到 24 小时；`collection_scope=all` 仍然不追加 `--collect-window-hours`。
  - `index.html` 和 `assets/app.js` 只改显示文案为 `自上次采集`，没有改 `value="24h"` 或 `selectedCollectionScope()`。
  - `assets/app.js` 的 MediaCrawler 状态卡把 `24h作品` 改成 `窗口作品`，把详情里的 `最近X小时` 改成 `窗口命中`。这里的 `窗口作品` 只是采集器原始 JSONL 中命中时间窗口的候选数；最终看板新增还要经过 Radar 刷新、去重、时间校验、归档合并和展示过滤。
  - `tests/test_local_server.py` 补了动态窗口、向上取整、兜底和全量不加窗口的测试。
- 本轮验收：
  - `.\.venv\Scripts\python.exe -m unittest tests.test_local_server -q` 通过：60 tests OK。
  - `.\.venv\Scripts\python.exe -m unittest discover -s tests -q` 通过：209 tests OK。
  - `node --check assets/app.js` 通过。
  - `.\.venv\Scripts\python.exe -m py_compile scripts\local_server.py` 通过。
  - `git diff --check -- scripts/local_server.py index.html assets/app.js tests/test_local_server.py` 仅有 Windows LF/CRLF warning。
  - `http://127.0.0.1:8080/index.html` 返回 200，并已服务出 `自上次采集`。
  - 直接探针确认：当前磁盘上次采集时间为 `2026-07-05 09:06:36.561958+00:00`，`refresh_command(root, "24h")` 生成 `--collect-window-hours 7`，`refresh_command(root, "all")` 不生成该参数。
  - 重启本地 8080 后真实采集复验通过：上次 `generated_at=2026-07-05T15:21:58.901276Z`，本次 `generated_at=2026-07-05T15:33:40.837860Z`，间隔约 11 分 42 秒，`collection_window_hours=1`，符合向上取整预期。
- 下一轮建议入口：
  - 先读 `PROJECT_STATE.md` 和本文件。
  - 手动验收：打开 `http://127.0.0.1:8080/`，展开 `信源配置`，确认下拉显示 `自上次采集`；点 `刷新看板数据` 后检查 `data/source-status.json.collection_window_hours` 是否接近距上次采集的小时数，而不是固定 24。
- 下一轮禁止：
  - 不要改 `scripts/update_news.py` 的窗口过滤逻辑；本轮只改本地服务传参。
  - 不要改 `value="24h"` 或 `selectedCollectionScope()` 返回值。
  - 不要改 MediaCrawler 启动处固定 24h 统计参数。
  - 不要把 `data/*.json` 脏改一股脑提交。

## 当前最新交接：订阅卡片已支持已阅与恢复

- 日期：2026-07-05
- 当前阶段：`我的订阅` 及各订阅平台栏目已支持把订阅卡片标记为“已阅”，标记后从常规订阅栏目隐藏，并汇总到顶部新增的 `已阅` 栏目；在 `已阅` 栏目点击“恢复”后会回到原订阅流。
- 主项目路径：`E:\AI-news-reader\ai-news-radar-run`
- 当前分支：`master`
- 本轮改动：
  - `assets/app.js` 新增 `READ_ITEMS_STORAGE_KEY`、`state.readItemIds`、已阅读写辅助函数和订阅卡片按钮。
  - `SECTION_DEFS` 新增 `read` 虚拟栏目，`sectionItems()` 统一处理“已阅只显示已阅 / 其它栏目排除已阅”。
  - Review 后补修：订阅栏目扁平时间线会把当前订阅池里的卡片统一标记为可渲染“已阅/恢复”按钮，避免后端已放进订阅池但前端 `isSubscriptionItem()` 判窄时按钮缺失；已阅 key 改为复用现有 `itemIdentityKey()`。
  - `assets/styles.css` 新增 `.item-actions` 和 `.read-toggle-btn` 样式。
- 本轮验收：
  - `node --check assets/app.js` 通过。
  - `git diff --check -- assets/app.js assets/styles.css` 通过，仅有 Windows LF/CRLF warning。
  - Playwright 打开 `http://127.0.0.1:8080/` 验证：顶部出现 `已阅` tab；订阅卡片显示“已阅”按钮；点击后 `我的订阅` 数量减少、`已阅` 数量增加；`已阅` 栏目内按钮变为“恢复”；刷新页面后已阅状态仍保留；恢复后 `localStorage ai-news-radar-read-items-v1=[]`，Console 无 error。
- 下一轮建议入口：
  - 先读 `PROJECT_STATE.md` 和本文件。
  - 手动验收：打开 `http://127.0.0.1:8080/`，在 `我的订阅` 标记一条 B站或公众号，再切到 `已阅` 恢复；需要完整验收时再覆盖抖音、小红书、油管和一次真实“刷新看板数据”后仍隐藏。
- 下一轮禁止：
  - 不要把已阅状态写回 `data/*.json` 或后端；它应继续只存在浏览器 `localStorage`。
  - 不要给非订阅源普通信息流卡片加“已阅”按钮。
  - 不要把当前已有 `data/*.json` 脏改一股脑提交。

## 当前最新交接：删除信源后立即清理历史展示数据

- 日期：2026-07-05
- 当前阶段：信源配置保存时已联动清理本地展示数据。用户删除整条信源记录，或在订阅成员面板删掉 B站/公众号/抖音/小红书/GitHub Release 成员后，只要点一次“保存草稿”或“保存成员”，`scripts/local_server.py` 会在写入 `sources.config.json` 成功后尝试清理 `data/archive.json`、`data/latest-24h.json`、`data/latest-24h-all.json`、`data/stories-merged.json`、`data/daily-brief.json` 里对应的旧条目。
- 主项目路径：`E:\AI-news-reader\ai-news-radar-run`
- 当前分支：`master`
- 本轮改动：
  - `scripts/local_server.py` 新增 `PURGE_TRACKED_SITE_IDS`、存活来源名计算、孤儿条目判断、JSON 原子写回和 `purge_deleted_source_data()`。
  - `/api/source-config` 保存配置成功后，用非阻塞 `REFRESH_LOCK.acquire(blocking=False)` 执行清理；如果正在采集则返回 `purged_items.skipped=refresh_in_progress`，不会卡住保存。
  - `assets/app.js` 读取后端 `purged_items`，只有清理数量大于 0 时才提示“已清理 N 条已删除信源的历史数据”。
  - `tests/test_local_server.py` 覆盖 B站成员拆分、非追踪 site_id 不误删、端到端清理、缺失 data 目录跳过、无删除时不重写。
- 本轮验收：
  - `.\.venv\Scripts\python.exe -m py_compile scripts\local_server.py` 通过。
  - `node --check assets\app.js` 通过。
  - `.\.venv\Scripts\python.exe -m unittest tests.test_local_server -q` 通过：45 tests OK。
  - `.\.venv\Scripts\python.exe -m unittest discover -s tests -q` 通过：193 tests OK。
  - `git diff --check -- scripts/local_server.py assets/app.js tests/test_local_server.py` 通过，仅有 Windows LF/CRLF warning。
- 下一轮建议入口：
  - 先读 `PROJECT_STATE.md` 和本文件。
  - 手动验收：打开 `http://127.0.0.1:8080/`，在“信源配置”里删除一个测试成员或单账号源，点“保存成员/保存草稿”，看状态提示是否出现清理数量；刷新后确认这个来源旧内容消失，其它来源还在。
- 下一轮禁止：
  - 不要批量删除。
  - 不要改 `scripts/update_news.py` 来重复实现这套本地保存时清理逻辑。
  - 不要扩大到计划外 site_id；当前只清理 `wewe_rss`、`bilibili_dynamic`、`mediacrawler_douyin`、`mediacrawler_xhs`、`github_foundation_sunshine_releases`。
  - 不要把当前已有 `data/*.json` 脏改一股脑提交。

## 当前最新交接：我的订阅改为全局时间线

- 日期：2026-07-05
- 当前阶段：`我的订阅` 和各平台订阅栏目已从“先按来源/平台分组，再展开条目”改为“一条全局时间线”。用户阅读习惯是最新内容优先，不管来自 GitHub、微信公众号、B站、抖音、小红书还是 YouTube，都按发布时间倒序混排。
- 主项目路径：`E:\AI-news-reader\ai-news-radar-run`
- 当前分支：`master`
- 本轮改动：
  - `assets/app.js` 中订阅栏目基础排序改为 `timelineMs` 倒序优先，热度分只作为同时间兜底。
  - `assets/app.js` 新增扁平时间线渲染，订阅栏目不再调用 `renderSiteGroups()`，因此不会出现先 GitHub 一组、再微信公众号一组的阅读断层。
  - 首屏默认渲染 80 条订阅卡片，底部提供“继续看剩余”按钮；非订阅栏目仍保留原有来源分组。
  - `index.html` app 脚本版本号更新为 `subscription-timeline-0705a`，避免浏览器缓存旧 JS。
- 本轮验收：
  - `node --check assets\app.js` 通过。
  - `http://127.0.0.1:8080/` 返回 HTTP 200，并加载 `assets/app.js?v=subscription-timeline-0705a`。
  - Playwright DOM 验收：`#newsList` 下 `siteGroups=0`、`sourceGroups=0`、首屏 `articles=80`。
  - Playwright 读到前 8 条时间为 `07/04 16:20`、`07/04 13:10`、`07/03 22:24`、`07/03 21:48`、`07/03 20:00`、`07/03 18:23`、`07/03 17:01`、`07/03 14:00`，确认已按时间混排。
- 下一轮建议入口：
  - 先读 `PROJECT_STATE.md` 和本文件。
  - 手动验收：打开 `http://127.0.0.1:8080/`，停在 `我的订阅`，确认列表顶部直接出现新闻卡片，不再先显示 `GitHub` / `微信公众号` 这种大分组标题；看前几条是否按时间从新到旧排列。
- 下一轮禁止：
  - 不要批量删除。
  - 不要提交 Cookie、登录态、`.env`、WeWe RSS 数据库、二维码、浏览器 profile、`local-secrets` 或私有 token。
  - 不要把当前 `data/*.json` 脏改一股脑提交。

## 当前最新交接：本地采集范围已覆盖刷新与平台采集器

- 日期：2026-07-04
- 当前阶段：本地采集控制台的“执行采集”已拆清楚“采集范围”和“展示范围”。默认 `过去24小时` 只限制本轮新入库内容；页面仍展示已有全量归档加新采集的 24h 数据。抖音/小红书维护按钮也会吃同一个范围：24h 模式启动 MediaCrawler 后会统计 24 小时内命中数，但不再覆盖原始 JSONL；需要第一次补历史或重建历史数据时手动选 `全量`。
- 主项目路径：`E:\AI-news-reader\ai-news-radar-run`
- 当前分支：`master`
- 本轮改动：
  - `scripts/local_server.py` 新增 `collection_scope` 白名单，只接受 `24h` / `all`，并继续拼固定 `scripts/update_news.py` 命令。
  - `24h` 模式运行 `--window-hours 24 --archive-days 3650 --collect-window-hours 24 --all-time`：本轮只接收 24h 内可信发布时间内容，但输出仍发布全量归档。
  - `all` 模式运行全量补历史命令，保留 `--all-time`，不加 `--collect-window-hours 24`。
  - `scripts/update_news.py` 新增采集窗口过滤；没有真实 `published_at` 或发布时间超出窗口的新抓取项不会进入本轮 24h 增量归档。
  - `assets/app.js` 会把当前采集范围同时传给 `/api/refresh` 和 `/api/maintenance-action`。
  - `scripts/local_server.py` 会把 24h 范围传给 `scripts/run_mediacrawler_douyin.py --collect-window-hours 24`；`all` 范围不传该统计参数。24h 模式默认每个抖音/小红书博主最多取最近 5 条，再按发布时间判断是否在 24 小时内。
  - `scripts/run_mediacrawler_douyin.py` 给抖音 creator 获取加了运行时硬限制，避免抖音继续翻取超过 5 条的历史作品。
  - `scripts/run_mediacrawler_douyin.py` 在 MediaCrawler 完成后写出 `mediacrawler-<platform>-collection-window.json`，记录原始行数、24h 命中数和跳过数，不再改写 `creator_contents_*.jsonl`。
  - `scripts/local_server.py` 和 `scripts/update_news.py` 读取 MediaCrawler JSONL 时会跳过 0 字节的最新文件，回退到同目录最新非空文件，避免本轮空文件继续影响主站读取。
  - 抖音/小红书状态卡当时显示“24h作品”和“原始写入”；当前最新口径已改为“窗口作品”和“原始写入”，`窗口作品=0` 表示当前统计窗口没有命中，不代表原始导出被清空。
  - YouTube/微信公众号这类 RSS/JSON 来源没有单独浏览器采集器，仍由 `scripts/update_news.py --collect-window-hours 24` 在入库时过滤。
  - README 和 `PROJECT_STATE.md` 已同步这个运行口径。
- 下一轮建议入口：
  - 先读 `PROJECT_STATE.md` 和本文件。
  - 历史手动验收口径：当时“采集范围”默认是 `过去24小时`，状态卡显示 24h 命中数和原始写入数；当前最新口径请以文件顶部“采集窗口已改为自上次采集”为准。
- 下一轮禁止：
  - 不要批量删除。
  - 不要把 `/api/refresh` 改成可传任意命令或任意参数。
  - 不要提交 Cookie、登录态、`.env`、WeWe RSS 数据库、二维码、浏览器 profile、`local-secrets` 或私有 token。
  - 不要把当前 `data/*.json` 脏改一股脑提交。

## 当前最新交接：WeWe RSS 公众号一键同步已接入

- 日期：2026-07-04
- 当前阶段：微信公众号订阅维护已从“手动找 feed_id”升级为“在 AI News Radar 里点同步 WeWe RSS”。本轮不读取 WeWe RSS 数据库、Cookie、微信登录态或二维码文件，只通过本地 HTTP JSON Feed 获取公众号列表。
- 主项目路径：`E:\AI-news-reader\ai-news-radar-run`
- 当前分支：`master`
- 最新已推送 commit：`3975004 fix: use readable source group names`
- 本轮已完成：
  - `scripts/local_server.py` 新增只读接口 `GET /api/wewe-rss/feeds`。
  - 该接口只允许本地 `WEWE_RSS_BASE_URL`，默认 `http://127.0.0.1:4000`，读取 `/feeds` 后只返回 `id/name/intro/updateTime/syncTime` 等展示字段。
  - `index.html` 在订阅成员表单里新增 `同步 WeWe RSS` 按钮。
  - `assets/app.js` 只在 `微信公众号` tab 显示该按钮；点击后会读取 WeWe RSS 公众号列表，转换成 WeWe RSS source records，并写入 `sources.config.json`。
  - 已保留上一轮保护：删除 seed 公众号成员会写入 `deleted_source_ids`；`maobidao_wudaolu_backup` 不会被误判成 WeWe RSS。
- 本轮验收：
  - `node --check assets\app.js` 通过。
  - `.\.venv\Scripts\python.exe -m py_compile scripts\local_server.py scripts\update_news.py` 通过。
  - `.\.venv\Scripts\python.exe -m unittest tests.test_local_server tests.test_topic_filter` 通过：119 tests OK。
  - 本地 HTTP：`GET http://127.0.0.1:8080/api/wewe-rss/feeds` 返回 `猫笔刀 / MP_WXS_3198966508`。
  - 浏览器验收：`http://127.0.0.1:8080/` 加载 `assets/app.js?v=wewe-rss-sync-feeds-0704a`；展开 `信源配置` -> `微信公众号`，`同步 WeWe RSS` 按钮可见；点击后状态为 `已同步并保存 1 个公众号，点“读取结果”后出现在看板。`
- 下一轮建议入口：
  - 先读 `PROJECT_STATE.md` 和本文件。
  - 手动验收时：先在 WeWe RSS 后台添加一个新公众号，再回 AI News Radar 点 `同步 WeWe RSS`，确认新公众号自动出现；最后点 `读取结果` 更新看板。
  - 若 `同步 WeWe RSS` 报错，先查 `http://127.0.0.1:4000/feeds` 是否能打开；若 4000 不通，用维护卡片或 `start_wewe_rss_sidecar` 启动 sidecar。
- 下一轮禁止：
  - 不要批量删除。
  - 不要提交 Cookie、登录态、`.env`、WeWe RSS 数据库、二维码、浏览器 profile、`local-secrets` 或私有 token。
  - 不要让 AI News Radar 直接读取 WeWe RSS 数据库；继续只走本地 JSON Feed。
  - 不要把当前 `data/*.json` 脏改一股脑提交。

## 当前最新交接：微信公众号订阅成员增删已接入

- 日期：2026-07-04
- 当前阶段：信源配置里的“订阅成员”面板已可管理微信公众号成员；本轮只处理 WeWe RSS 公众号配置增删的稳定性和误判问题，不删除文件、不提交生成数据、不改登录态。
- 主项目路径：`E:\AI-news-reader\ai-news-radar-run`
- 当前分支：`master`
- 最新已推送 commit：`3975004 fix: use readable source group names`
- 本轮已完成：
  - `assets/app.js` 的微信公众号订阅成员保存逻辑会在删除默认种子成员时写入 `deleted_source_ids`，所以删除 `wewe_rss_maobidao` 后不会被内置源合并逻辑自动补回来。
  - `assets/app.js` 与 `scripts/local_server.py` 都收紧了 WeWe RSS 识别规则：只有 `type=wewe_rss`、id 以 `wewe_rss` 开头、或明确含 `wewe_rss` / `wewe rss` 的配置才算 WeWe RSS。
  - `maobidao_wudaolu_backup` 这种“微信公众号备用”公开 API 源仍可作为备份源，但不会再被误当成 WeWe RSS feed，也不会触发假的 feed_id 缺失维护提示。
  - `index.html` app 脚本版本号已更新为 `wechat-subscription-members-0704a`。
- 本轮验收：
  - `node --check assets\app.js` 通过。
  - `.\.venv\Scripts\python.exe -m py_compile scripts\local_server.py scripts\update_news.py` 通过。
  - `.\.venv\Scripts\python.exe -m unittest tests.test_local_server tests.test_topic_filter` 通过：117 tests OK。
  - `git diff --check -- assets\app.js scripts\local_server.py index.html tests\test_local_server.py tests\test_topic_filter.py` 通过，仅有 Windows LF/CRLF warning。
  - 浏览器只读验收：打开 `http://127.0.0.1:8080/`，展开 `信源配置`，切到 `微信公众号`，能看到 `猫笔刀 / MP_WXS_3198966508`；未点击删除、保存或读取结果。
- 下一轮建议入口：
  - 先读 `PROJECT_STATE.md` 和本文件。
  - 若继续验收新增/删除，建议先新增一个临时公众号 feed_id 测试项，点 `保存成员` 写入，再删除该临时项确认刷新后不复活；不要拿真实 `猫笔刀` 作为第一次破坏性验收对象。
  - 若 8080 打不开，启动：`.\.venv\Scripts\python.exe scripts\local_server.py --host 127.0.0.1 --port 8080`。
- 下一轮禁止：
  - 不要批量删除。
  - 不要提交 Cookie、登录态、`.env`、WeWe RSS 数据库、二维码、浏览器 profile、`local-secrets` 或私有 token。
  - 不要把 `maobidao_wudaolu_backup` 误判成 WeWe RSS；它是公开 API 备份源。
  - 不要把当前 `data/*.json` 脏改一股脑提交。

## 当前最新交接：订阅平台栏目与来源标题清理已保存

- 日期：2026-07-04
- 当前阶段：主页内容栏目已从主题分类重构为订阅/平台分类；无意义的 `TODAY'S SIGNALS` / `今日重点信号` 板块已删除；来源分组标题已从技术源名改为平台名，并已由用户在本地浏览器验收通过。
- 主项目路径：`E:\AI-news-reader\ai-news-radar-run`
- 当前分支：`master`
- 最新已推送 commit：`3975004 fix: use readable source group names`
- 本轮已完成：
  - 首页默认进入 `我的订阅`。
  - 顶部内容栏目只保留 `我的订阅`、`抖音`、`小红书`、`微信公众号`、`B站`、`油管`。
  - 平台栏目会从订阅记录的 source id、source name、URL、标题等字段判断归属。
  - WeWe RSS sidecar 已恢复：`http://127.0.0.1:4000/dash/accounts` 可打开，账号 `547013436` 状态为启用。
  - 猫笔刀 feed 已恢复到 2026-07-03 最新文章：`诚实回答`，发布时间 `2026-07-03 22:24:51`。
  - AI News Radar 本地服务已恢复：`http://127.0.0.1:8080/` 返回 HTTP 200，`/api/local-status` 返回 `ok=true`。
  - `index.html` 已移除重点信号板块 DOM，`assets/motion.js` 已移除对应动画绑定；浏览器验证 `#bolePicksWrap` 为 0 且控制台无 error。
  - `assets/app.js` 新增 `sourceDisplayName()`，列表分组、来源筛选和源状态表显示 `微信公众号`、`YouTube`、`GitHub`、`小红书`、`抖音`、`B站` 等平台名，不再把 `WeWe RSS`、`MediaCrawler Xiaohongshu` 等技术名暴露给读者。
- 本轮验收：
  - 用户确认“没问题，验收成功”。
  - 本地页面已可打开，后续可在页面点 `执行采集` 同步最新 WeWe RSS 数据。
- 下一轮建议入口：
  - 先读 `PROJECT_STATE.md` 和本文件。
  - 若 8080 打不开，启动：`.\.venv\Scripts\python.exe scripts\local_server.py --host 127.0.0.1 --port 8080`。
  - 若 4000 打不开，从 `E:\AI-news-reader\wewe-rss-sidecar\apps\server` 用 SQLite 环境启动 `node dist/main.js`，并确认 `http://127.0.0.1:4000/dash/accounts` 可访问。
  - 如果继续做信源 UI，优先从 `assets/app.js` 的 `SECTION_DEFS`、`isSubscriptionSection()`、`itemPlatformSection()`、`sectionItems()` 看起。
  - 如果继续做洁癖，可评估是否彻底删除 `assets/app.js` / `assets/styles.css` 中已不再显示的旧 `bole` 相关函数和样式；当前保留不会影响页面。
- 下一轮禁止：
  - 不要批量删除。
  - 不要提交 Cookie、登录态、`.env`、WeWe RSS 数据库、二维码、浏览器 profile、`local-secrets` 或私有 token。
  - 不要把 `/api/refresh` 或维护动作扩展成前端可传任意命令。

## 当前最新交接：本地采集控制台继续增强维护动作入口

- 日期：2026-07-03
- 当前阶段：本地采集控制台已完成主要维护入口收口；B站、抖音、小红书、WeWe RSS 维护动作均已具备本地入口和状态反馈。
- 主项目路径：`E:\AI-news-reader\ai-news-radar-run`
- 当前分支：`feature/local-trigger-console`
- 最新已推送 commit：`cb82374 feat: add dedicated Bilibili cookie login flow`
- 本轮已实现：
  - `scripts/local_server.py` 新增 `GET /api/local-status`。
  - 本地状态会读取 `sources.config.json` 和 `data/source-status.json`，输出启用信源数、采集状态和维护项。
  - 新增维护诊断：失败源、0 条结果、B站 cookie 未配置、B站账号级失败、WeWe RSS feed 失败、WeWe RSS sidecar 不可访问、WeWe feed id 缺失、MediaCrawler JSONL 缺失/为空/超过 36 小时未更新、`sources.config.json` 格式错误、`source-status.json` 缺失。
  - 页面“信源配置”区新增“本地采集”状态面板。
  - “刷新数据”改为“执行采集”，“检查状态”会读取本地维护诊断。
  - 信源列表新增筛选：全部、启用、需维护、公众号、小红书、抖音、B站、RSS、GitHub。
  - 维护提示新增“定位信源”，可跳到对应配置项；信源列表会标记需关注/需处理。
  - 维护提示新增白名单动作按钮：WeWe RSS 启动后台/扫码，B站打开登录页，MediaCrawler 打开 JSONL 文件夹和平台页。
  - B站维护入口新增小号专用 profile 流程：启动 `local-secrets/bilibili-profile` 登录窗口，同步该专用窗口的 B站 cookie 到 `local-secrets/bilibili-cookies.txt`；本地刷新会自动把该文件作为 `BILIBILI_COOKIE_FILE` 传入固定采集命令。
  - 新增 `POST /api/maintenance-action`，只接受当前维护项里存在的 `action_id`，用于打开已验证的本地文件夹或启动固定的本机 WeWe RSS sidecar；不接受前端传任意路径或命令。
  - WeWe RSS feed 失败提示已去重，不再同时显示总失败和单 feed 失败。
  - 抖音维护项新增固定动作 `start_mediacrawler_douyin`：通过 `scripts/run_mediacrawler_douyin.py` 从 `E:\AI-news-reader\MediaCrawler-local-test` 启动 MediaCrawler creator 模式；该 runner 使用采集专用 Chrome profile，不应连接用户日常浏览器。Radar 常规刷新仍只读 JSONL，不读取 Chrome profile/cookie。
  - 小红书维护项新增固定动作 `start_mediacrawler_xhs`：复用同一个 runner 和采集专用 Chrome profile，以 `--platform xhs --type creator` 启动；默认从已有 JSONL 的 `user_id` 推断干净的小红书博主主页 URL，也可用 `MEDIACRAWLER_XHS_CREATOR_ID` 覆盖。
  - 本地采集面板新增抖音/小红书采集进度卡：显示采集中/已完成、JSONL 写入条数、最近写入时间、最近采集动作和下一步提示；任一平台采集中都会自动轮询。
  - MediaCrawler JSONL 读取现在会自动选择同目录最新的 `creator_contents_*.jsonl`，避免配置还指向旧日期文件时继续读旧数据。
  - README 和 `PROJECT_STATE.md` 已同步本地工具边界。
- 当前边界：
  - 不读取或保存 Cookie、token、`.env`、微信登录态、WeWe RSS 数据库、QR 登录文件、MediaCrawler profile。
  - WeWe RSS 探针只检查 `localhost` / `127.0.0.1` 的 `/feeds` HTTP 端点；MediaCrawler 探针只看显式配置的 JSONL 文件元信息。
  - 维护动作只打开页面、文件夹，或启动固定路径 `E:\AI-news-reader\wewe-rss-sidecar` 的 WeWe RSS sidecar / 固定路径 `E:\AI-news-reader\MediaCrawler-local-test` 的抖音 MediaCrawler；抖音启动会走专用 Chrome profile，不应劫持日常浏览器，不会自动提交登录态、不会读取 profile，也不会运行前端传入的任意命令。
  - `/api/source-config` 仍只能写项目根目录 `sources.config.json`。
  - `/api/refresh` 仍只能运行固定刷新命令，不能由前端传任意命令。
- 已验证：
  - `.\.venv\Scripts\python.exe -m py_compile scripts\local_server.py scripts\update_news.py`
  - `.\.venv\Scripts\python.exe -m unittest tests.test_local_server`
  - `node --check assets\app.js`
  - `GET http://127.0.0.1:8080/api/local-status` 返回 HTTP 200，当前维护项为 `bilibili_cookie_missing`。
  - `GET http://127.0.0.1:8080/index.html` 包含 `sourceConfigCheckBtn`、`localOpsStatus`、`localOpsSummary`、`执行采集`。
  - 2026-07-03 继续开发后，`GET /api/local-status` 返回 2 个维护项：`wewe_feed_MP_WXS_3198966508_failed` 和 `bilibili_cookie_missing`。
  - 2026-07-03 修复 WeWe 维护入口后，`POST /api/maintenance-action` with `start_wewe_rss_sidecar` 启动 PID `20128`，`http://127.0.0.1:4000/dash` 和 `/feeds` 均返回 HTTP 200；`wewe_rss_sidecar_unreachable` 维护项消失。
  - 2026-07-03 B站小号 cookie 维护入口已由用户验收：`打开B站小号登录` 使用独立 `local-secrets/bilibili-profile`，`同步cookie` 写入 `local-secrets/bilibili-cookies.txt`，页面显示生效；后续 `执行采集` 会自动使用该文件。
  - 2026-07-03 用户执行采集后，本地状态确认 B站 `cookie_present=true`、`fetch_mode=cookie_full_dynamic`、`ok=true`、`item_count=40`、`error=null`；B站 cookie 流程验收通过。
  - 浏览器 DOM 曾验证到筛选条：`全部 14`、`启用 8`、`需维护 2`、`公众号 1`、`小红书 1`、`抖音 1`、`B站 1`、`RSS 6`、`GitHub 1`，且 `定位信源` 出现；后续一次浏览器自动化刷新超时，HTTP 验证仍通过。
- 下一步建议：
  - 本地采集控制台当前可收口；后续如果继续优化，优先做“关闭/停止采集专用窗口”“重新同步 cookie”“维护项完成后自动折叠”等体验小改。
  - 如准备合并/发布，先决定是否重新生成并审查 `data/*.json`；默认继续不提交本地生成数据。
- 下一轮禁止：
  - 不要批量删除。
  - 不要提交 Cookie、登录态、`.env`、wewe-rss 数据库、QR 登录文件、浏览器 profile 或私有 token。
  - 不要把所有 dirty 文件一股脑提交。
  - 不要把 `/api/refresh` 扩展成前端可传任意命令。

## 历史交接：信源配置可本地写入并一键刷新

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

# HANDOFF.md

> 跨窗口接力用，只写下一轮必须知道的。长期施工规则在 `CLAUDE.md`，项目状态在 `PROJECT_STATE.md`。

## 当前最新交接：订阅源二级页时间平铺（2026-07-16）

- 分支：`master`，提交 `9e24f01`，已推送到 `origin/master`。
- 施工提交：`cbed720`（修复代码）+ `9e24f01`（合并远端最新数据快照）。
- 修改文件：`assets/js/render-list.js`、`index.html`、`tests/e2e/layout-timeline.spec.js`。
- 验收：浏览器验证 8 个栏目时间流、微信公众号排序切换、已阅/恢复、刷新缓存和控制台无错误；
  `node --check` 与 `git diff --check` 通过。Playwright 因本机 `spawn EPERM` 未进入断言。
- 下一轮：本功能无待施工项。保留 `stash@{0}`、原工作区数据脏改动和未跟踪文件，不要清理或提交它们。

## 历史交接：启动微信采集按钮修复 + 双击启动器（2026-07-15）

- 分支：`master`，已推送（`1d73577`），本地与远程 HEAD 已核对相等。
- 计划书：`计划/一键启动微信sidecar按钮-施工计划.md`。

### 本轮做了什么

**1. 「启动微信采集」按钮全链路打通（commit `c45ef74`）** —— 三处坏点一并修复：

- `boot.js` 漏绑按钮点击事件（表现：点了完全没反应）→ 已补 `addEventListener`。
- **根因**：`perform_maintenance_action`（`scripts/radar/server/refresh.py`）分派设计错配。该按钮是
  `source-config-tools` 工具条里**常驻可见**的按钮，派发却依赖「渠道出问题才生成」的维护项列表；
  系统健康时列表为空，请求走到 `find_maintenance_action` 即返回 `maintenance_action_not_found`，
  `kind == "start_service"` 里的正确分支**永远够不到**（死代码）。已改为给两个常驻 sidecar 按钮
  （微信 8001 / WeWe 4000）单开一条 **scope-free 无条件派发入口**（不传 `collection_scope`，
  避开签名不匹配的 TypeError），并删掉够不到的死分支。
- 顺手消除 WeWe RSS(4000) 按钮的同类隐患（此前只在 4000 挂掉时才可派发）。

**2. 双击启动采集入口（commit `1d73577`）** —— 新增 `双击运行-刷新线上采集.cmd`：双击即弹出采集
菜单，不用再开终端敲命令。原 `刷新线上采集.ps1` 一字未改，是纯增量入口。

### ⚠️ 一个真踩过的坑（改 `.cmd`/`.bat` 前必读）

**`.cmd` 文件必须存 CRLF 换行，不能是 LF。** LF 会让 cmd.exe 把 `cd /d` 拆坏、双击瞬间闪退。
第一次用 bash 环境验收「通过」是假象——bash 不在乎换行符；必须用 **cmd.exe 同口径**验证。
（已沉淀进 `CLAUDE.md` 必查清单第 6 条。）

### 本轮验收

新增 2 个单测锁住「健康状态下两个 sidecar 按钮仍可派发」；全量 `unittest discover tests` 289 passed；
HTTP API 实测 `ok:true`；用户浏览器实测通过（进 8001 后台并成功新增「财联社」公众号，随后用
双击启动器跑「全部采集」成功）。双击 `.cmd` 已用 cmd.exe 真实口径 + 用户手动双击双重验收，不闪退。

---

## 未完成 / 待用户拍板（跨窗口仍有效）

1. **⚠️ git `stash@{0}`（备注「本地刷新生成的 data 快照」）里有 6 条工作区已丢失的 GitHub Release
   历史**（`github_foundation_sunshine_releases`，2026-07-11 快照），是这 6 条数据的**唯一备份**。
   **严禁 drop 该 stash。** 待决策：要不要恢复进 `data/archive.json`。核对报告见根目录
   `stash_cmp_report.txt`（未跟踪）。

2. `sources.config.json` 已退为本机私有参数，但 `/api/source-config` 接口仍在。要不要彻底下线它，
   是个独立话题。

3. `flush_pending_purge()` 用**线上配置**算存活名单，台账却也可能来自 `/api/source-config` 的保存。
   该偏差**偏保守**（最坏是「该清的没清」，不会误删），随第 2 项完成自然消失。

4. 小红书 `mediacrawler_xhs` 仍不在 `ENUMERABLE_SUBSCRIPTION_SITE_IDS`（取消订阅不清历史）。
   当前无小红书数据，不紧急。

---

## 下一轮开工前必读

- 改**清理历史条目**逻辑前：必读 `CLAUDE.md`「清理历史条目的禁区」五条（真删过数据）。
- 改**同步线上**（`sync_online_source_config`）逻辑前：必读 `CLAUDE.md`「同步线上的 git 编排禁区」
  三条——恢复工作区只能用 `git restore --source=stash@{0} -- .`，**不能用 `git checkout`**（会写进
  暂存区，下次同步被 `unrelated_files_already_staged` 闸拦住）。
- 新增**本机维护按钮**前：必读 `CLAUDE.md`「本机维护按钮的派发禁区」三条（本轮 2026-07-15 教训）。
- 提交推送时注意：线上 Actions 常在你推送前后自动提交 `data/**` 快照，导致分叉。本轮做法是
  先 commit 自己的改动 → `git rebase origin/master`（代码改动与 data 快照零交集，无冲突）→ push。

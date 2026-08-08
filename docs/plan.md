# 抖音采集风控容错与部分成功发布 PLAN

Status: **PLAN v1.0 — FROZEN**（2026-08-08 由用户确认冻结）
P5 评审：`PLAN-01` ~ `PLAN-06` 全部关闭，详见第 2 章第 8~11 条与第 3.2 节决策 6。
上游：`docs/bugs/BUG-02-抖音采集回执不完整导致整轮作废.md`（已稳定复现、根因已定位）
分支：`claude/inspiring-carson-299158`（独立 worktree）
基线：`master` @ c30f695（已合入 origin/master）；全量 **743 passed, 0 failed**（9 分 02 秒）
风险级别：**高风险**（导航规范第 5 节：跨仓库、跨机器、跨平台同步）

> 上一轮 BUG-01 的计划已归档到 `docs/plans/BUG-01-采集后清理残留标签页-{plan,task}.md`。

---

## 1. 目标与非目标

### 目标（3 条，全部来自用户 2026-08-08 的口头拍板）

1. **号与号隔离**：一个抖音号被风控，其余 5 个号照常采完，不再连坐。
2. **详情先重试**：视频详情被风控拦下时先退避重试，把偶发拦截消化掉。
3. **采到多少发多少 + 缺失可见**：重试仍失败的如实记下来，本轮**不管采到多少都发布到看板**，并在看板上以「部分完成」让用户看见缺了几条。

### 非目标（这次明确不碰）

- **不改 MediaCrawler**（`C:\AI-news-reader\MediaCrawler-local-test`）。它是外部项目，不在本仓库白名单内。
- **不碰 `data/archive.json` 及任何清理逻辑**。本轮所有改动与 CLAUDE.md 的清理禁区零交集。
- **不新增手机推送渠道**（Bark / 微信 / 邮件）。用户本轮选的是「看板上直接显示」；手机推送要引外部服务和密钥，属于新功能，另开一轮。
- **不改前端 JS 与 `index.html`**。现状调查已证实前端「部分完成」展示能力已存在（见第 2 章第 5 条），因此不触发 CLAUDE.md 的「改 `assets/js/**` 必跑 E2E + bump `?v=`」条款。
- **不碰小红书通道**（`fetch_mediacrawler_xhs_subscriptions` 及其 runner 分支）。
- ~~**不改 `scripts/radar/cli.py`**。抖音状态由 fetcher 自己返回，不需要动主管线。~~
  **⚠️ 本条假设已在 P8 真实验收中被证伪（QA-02），经用户 2026-08-08 授权撤销。**
  实际情况：`scripts/radar/cli.py:636-652` **逐字段重新构造** statuses 条目，
  fetcher 返回的健康字段在主管线被整体丢弃。要让看板拿到 `partial`，
  必须在该字典里显式透传。`scripts/radar/cli.py` 已加入第 5 章白名单，
  改动范围严格限定为「该字典多透传 5 个字段」，不碰采集、清理或其它源。
- **不解决抖音风控本身**。风控是抖音服务端行为，本轮只做容错，不做对抗。

---

## 2. 现状调查

每条结论都附文件路径与行号，均为读代码/实测所得，无推测。

1. **风控落点是「视频详情」接口**。MediaCrawler 采集流程是「先要列表 → 再逐条要详情 → 拿到详情才落盘」：
   `media_platform/douyin/core.py:291` 取列表 → `:301` 对每条调 `get_aweme_detail` → `:305` 只有非 None 才落盘。
   `:227-229` 的 `except DataFetchError` 把风控异常吞掉并 `return None`，于是该条静默丢失。
   （NUC 路径：`C:\AI-news-reader\MediaCrawler-local-test\media_platform\douyin\core.py`）

2. **我们的回执判定要求「一条不少」**。`scripts/run_mediacrawler_douyin.py:902` 的 `finalize()`
   要求 `written_rows == listed_count` 才判 `completed`；`:1157` 只要 `failed_creator_count` 非 0
   就 `raise RuntimeError("partial_creator_failure: ...")`，runner 退出码 1。

3. **外层脚本见非零退出即中止**。`deploy/cloud-pc/collect-douyin-and-push.ps1:377`
   `if ($runnerExit -ne 0) { throw }`，桥接不提交、不推送。
   其自身 `:384-397` 的 receipt 复核因为永远走不到，目前是死路径。

4. **创作者之间没有隔离**。`core.py:277-291` 的创作者 for 循环只对 URL 解析做了 try/except，
   对 `get_user_info` 与 `get_all_user_aweme_posts` 两个网络调用**没有任何保护**；
   而我们在 `scripts/run_mediacrawler_douyin.py:958-970` 的包装里记录失败后**原样 `raise`**，
   异常一路冒泡终止整个爬虫，排在后面的号一条不采。

5. **前端「部分完成」展示已经存在，无需新建**：
   - `assets/js/render-panels.js:208-209` 读 `site.partial`，显示黄色「部分完成」；
   - `assets/js/render-meta.js:10,55,268`、`assets/js/subscriptions.js:51` 同样消费该字段；
   - `scripts/radar/cli.py:508` 的 GitHub 源已经在用同一套语义
     （`partial` + `succeeded_count` / `failed_count`），本轮照抄即可，不发明新字段语义。

6. **云端看板看不到 NUC 的采集健康**。`scripts/radar/fetchers/mediacrawler.py:299-374`
   的抖音 fetcher **只读 JSONL 内容**，全文不读 `manifest.json`（grep 无匹配）。
   桥接仓库的 `manifest.json` 是 NUC 唯一能把采集元信息送到云端的载体
   （`collect-douyin-and-push.ps1:457-470` 写它，`:472` 与 JSONL 一起精确暂存并推送）。
   NUC 实测现有内容：`schema_version=1`，含 `crawl_output_rows` / `creator_count` / `max_notes` 等 9 个字段。

7. **失败留痕契约已存在**：`collect-douyin-and-push.ps1:117` 指向
   `logs\bridge-collection-failures.jsonl`；CLAUDE.md 规定每行固定 10 字段、
   `message` ≤512 字符、按渠道与 `run_id` 去重、禁写原始输出/cookie/token。本轮复用，不新建通道。

8. **PowerShell 脚本有端到端自动化测试**（P5 评审 PLAN-02 更正了初稿的错误结论）。
   `tests/test_bridge_collection_failure_log.py:28-130` 的夹具是
   「假 runner（吐预设 result JSON 的 Python 脚本）+ 真 `.ps1` + 真 git 桥接仓库（bare + working）」，
   已经在断言退出码、`status.json` 内容、桥接 HEAD 是否前进、留痕日志的字段集合。
   本轮 TASK-05 直接扩展这套夹具，**不新增测试框架**。

9. **抖音异常消息含原始响应体**（P5 评审 PLAN-06 新发现）。
   MediaCrawler `media_platform/douyin/client.py:135` 抛的是
   `raise DataFetchError(f"{e}, {response.text}")` —— 把抖音返回的**原始响应体拼进了异常消息**。
   NUC 日志里 `Expecting value: line 1 column 1 (char 0), Blocked by ArgusSecurityPlugin Validate Error`
   的后半段就是它。**因此异常字符串绝不可原样落进留痕日志或 result JSON**，必须先净化。

10. **前端不会隐藏抖音**（P5 评审 PLAN-03 验证）。`assets/js/dom.js:229` 的
    `HIDDEN_PLATFORM_IDS` 是空集合，`:230` 的 `HIDDEN_SOURCE_IDS` 只含 `wewe_rss` 与
    `maobidao_wudaolu_backup`；抖音 site_id 为 `mediacrawler_douyin`（`scripts/radar/common.py:253`）。
    当前 `data/source-status.json` 只有 5 个 site，远低于 `render-panels.js:197` 的 `.slice(0, 12)` 上限。

11. **云端桥接仓库路径已确认**（P5 评审 PLAN-05 验证）。
    `.github/workflows` 中 `bridge_dir="$RUNNER_TEMP/douyin-bridge"`，
    JSONL 落在 `$RUNNER_TEMP/douyin-bridge/output/douyin/jsonl/`，
    故 `manifest.json` 恰好是 JSONL 目录**上溯 3 级**。

### 已知限制

- **本仓库无法直接触发 NUC 采集**，真机验收需要用户授权后经 `ssh omnia-nuc` 触发计划任务。
- **抖音风控本身无法预测**，真机验收时可能恰好一条都没被拦。此时「部分完成」路径拿不到
  真实现场证据，只能靠自动化测试覆盖；验收记录里必须**如实写明这一点**，不得含糊成「已验证」。

---

## 3. 方案

### 3.1 模块划分与数据流

```
【NUC 本机】
 runner  scripts/run_mediacrawler_douyin.py
   ├─ A1 创作者隔离   包装层吞掉异常 → MediaCrawler 循环得以跑完 6 个号
   ├─ A2 详情重试     包装 get_video_by_id，退避重试后仍失败才放行给上游 except
   └─ A3 回执汇总     算出 missing_rows / partial，写进 result JSON；有内容就退 0
                                   │
 采集脚本 deploy/cloud-pc/collect-douyin-and-push.ps1
   ├─ B1 放宽发布口径  至少 1 个号完成 + 有内容 → 允许发布（原本要求 6/6 完整）
   ├─ B2 manifest 扩字段  schema_version 2，带上 partial / missing_rows / 完成数
   └─ B3 缺失留痕      有缺失时往 bridge-collection-failures.jsonl 追加 warning 记录
                                   │
                          git push 桥接仓库
                                   │
【云端 Actions】
 fetcher scripts/radar/fetchers/mediacrawler.py
   └─ C1 读桥接 manifest.json → 把 partial / missing_rows 填进抖音 status
                                   │
                       data/source-status.json
                                   │
【前端】assets/js/render-panels.js:208  —— 零改动，已支持 partial → 显示黄色「部分完成」
```

### 3.2 关键决策

**决策 1：重试放在 `DouYinClient.get_video_by_id`，不放在 `DouYinCrawler.get_aweme_detail`。**
理由：`get_aweme_detail` 是 MediaCrawler 的爬虫方法，包装它等于替换业务逻辑；
`get_video_by_id` 是纯网络调用，包装它只是在同一层加重试，语义最小。
重试耗尽后必须**抛回原异常对象**（保持 `DataFetchError` 类型），
让 `core.py:227` 的既有 except 照常接住并 `return None` —— 上游行为完全不变。

**决策 2：隔离用「返回空结果」，不用「吞掉异常继续」。**
`get_user_info` 失败返回 `{}` → `core.py:287` 的 `if creator_info:` 自然跳过 `save_creator`；
`get_all_user_aweme_posts` 失败返回**已收集到的 rows**（可能是空列表）→ `core.py:293` 的
`video_ids` 推导照常工作。两处都不改变 MediaCrawler 对返回值的既有假设。

**决策 3：`state` 取值扩为 `completed` / `partial` / `failed` 三态，而不是放宽 `completed` 的定义。**
理由：`completed` 现在的含义是「一条不少」，很多地方（含 PS 脚本 `:384-397`）依赖它。
改它的含义会让所有下游静默变宽。新增 `partial` 态则是显式的、可被单独检查的。
判定：`written == listed` → `completed`；`written < listed` 但 `written > 0` → `partial`；
`written == 0` 或 profile/api 校验没过 → `failed`。

**决策 4：`manifest.json` 的 `schema_version` 提到 2。**
理由：加字段虽向后兼容，但云端需要能区分「这份 manifest 有没有健康信息」。
配套把 `collect-douyin-and-push.ps1:447` 的 `-ne 1` 改成 `-ne 2`，
让首次运行就重写 manifest 带上新字段。云端一律用 `.get()` 容错读取，**读不到不报错、不阻断主流程**。

**决策 5：发布门槛设为「至少 1 个号完成或部分完成，且本轮有新内容」。**
用户明确要求「不管采集了多少，都同步到 AI 看板上」，故不设百分比阈值。
但保留一个 fail-safe：**6 个号全 `failed`（一条没采到）时仍判失败不发布**——
那不是风控偶发，是登录态失效或网络全断，发布空快照没有意义。

**决策 6（P5 评审 PLAN-06 新增）：异常消息一律净化后才允许外泄。**
因第 2 章第 9 条，`DataFetchError` 的消息里拼着抖音原始响应体。任何写入
`logs/bridge-collection-failures.jsonl`、result JSON、`manifest.json`、`source-status.json`
的错误描述，都必须先经过净化：
- 只保留**归一化后的错误分类**（如 `douyin_risk_control` / `detail_fetch_failed`），不透传原始字符串；
- 需要保留细节时，只取异常消息的**前 200 字符**并去掉换行，且必须先剥掉响应体部分；
- 绝不写入 cookie、token、Set-Cookie、Authorization 或任何请求头。

这条同时约束 runner（Python）与采集脚本（PowerShell）两侧，且必须有测试断言
「留痕记录里不出现响应体原文」。

### 3.3 放弃的选项及理由

| 放弃的选项 | 为什么放弃 |
|---|---|
| 用列表数据兜底填补详情失败的那条 | 列表与详情的字段完整度不同，落盘数据会出现两种形状，下游解析要分叉。BUG-02 卡第 5 节已评估：风险高于收益。**漏采可自愈**（实测 08-08 当天 6 个号里 5 个已回满 10 条），不值得为它改数据形状。 |
| 设百分比阈值（如缺失 >10% 才判失败） | 用户明确要求「采到多少发多少」。设阈值等于替用户重新收紧口径。 |
| 直接改 MediaCrawler 的 `core.py` 加 try/except | 外部项目，改了以后它升级就冲突，且不在本仓库白名单内。用 monkeypatch 在自己这边包装是既有做法（`install_douyin_observer` 本来就这么干）。 |
| 新建一个独立的采集健康 JSON 文件推到桥接仓库 | `manifest.json` 已经在推送清单里（`:472` 精确暂存），复用它零新增文件、零新增推送路径。新建文件要同步改暂存清单和云端读取，多一处出错点。 |
| 手机推送（Bark / 微信） | 见「非目标」。要引外部服务和密钥，跨出 BUG 修复范围。 |

---

## 4. 界面与流程

**无新增界面。** 唯一的用户可见变化在既有的「源状态详情」表格里：

- 用户从哪进入：打开雷达网页 → 「源状态详情」区块（`index.html:162` 的 `sourceStatusTable`）
- 看到什么：抖音那一行的「状态」列，从 `正常`（绿）变成 `部分完成`（黄）
- 成功态：本轮 6 个号全采全 → 仍显示 `正常`
- 部分态：有号被风控少采了几条 → 显示 `部分完成`
- 失败态：6 个号全军覆没 → 显示 `异常`（并且本轮不发布，看板停在上一轮数据）
- 多端差异：无。同一份 `source-status.json`，PC 与手机渲染一致。
- 是否写真实数据：**否**。本轮改动不写 `data/archive.json`，只写 `data/source-status.json`（由云端 Actions 每轮重新生成）与桥接仓库的 `manifest.json`。

---

## 5. 文件白名单

### 允许改（精确路径，无通配）

| 路径 | 改什么 |
|---|---|
| `scripts/run_mediacrawler_douyin.py` | A1 隔离、A2 重试、A3 回执三态与缺失汇总 |
| `deploy/cloud-pc/collect-douyin-and-push.ps1` | B1 放宽口径、B2 manifest schema 2、B3 缺失留痕 |
| `scripts/radar/fetchers/mediacrawler.py` | C1 读桥接 manifest，填 `partial` / `missing_rows`（**两条分支都要改**，见 QA-01） |
| `scripts/radar/cli.py` | C2 主管线 statuses 条目透传健康字段（**P8 验收 QA-02 后经用户授权加入**，仅限 `:636-652` 那个字典） |
| `tests/test_mediacrawler_runner.py` | TASK-01a / 02a / 03a 的红测试 |
| `tests/test_private_bridge_sources.py` | TASK-04a 的红测试（fetcher 读 manifest） |
| `tests/test_bridge_collection_failure_log.py` | TASK-05a 的红测试（扩展既有 PS 端到端夹具） |
| `docs/plan.md` | 本文件 |
| `docs/task.md` | 任务清单与施工记录 |
| `docs/bugs/BUG-02-抖音采集回执不完整导致整轮作废.md` | 验收结论回填 |

### 禁止碰

- `data/**` —— 尤其 `data/archive.json`、`data/pending-purge.json`
- `assets/js/**`、`index.html` —— 前端已支持 `partial`，本轮零改动
- `scripts/radar/cli.py` —— 主管线不动
- 任何清理相关模块（`filter_archive_by_subscriptions`、purge 系列、`orphan_*`）
- `C:\AI-news-reader\MediaCrawler-local-test\**` —— 外部项目
- `deploy/local/collect-wechat-and-push.ps1` —— 微信通道不动
- `config/online-sources.json`、`sources.config.json`、`feeds/**`

---

## 6. 验证方式

### 6.1 每步自测命令（全部已当场跑通，附实测结果）

| # | 命令 | 实测结果（2026-08-08 改动前基线） |
|---|---|---|
| V1 | `.venv\Scripts\python.exe -m pytest -q tests/test_mediacrawler_runner.py tests/test_bridge_collection_failure_log.py` | **38 passed** in 6.56s |
| V2 | `.venv\Scripts\python.exe -m pytest -q tests/test_private_bridge_sources.py` | **40 passed** in 0.68s |
| V3 | `.venv\Scripts\python.exe -m py_compile scripts/run_mediacrawler_douyin.py scripts/radar/fetchers/mediacrawler.py` | **OK** |
| V4 | PowerShell 语法检查（见下方原文命令） | **0 错误** |
| V5 | `.venv\Scripts\python.exe -m pytest -q` 全量回归 | **743 passed, 0 failed**（9 分 02 秒） |

V4 的完整命令：

```powershell
$errors = $null; $null = [System.Management.Automation.Language.Parser]::ParseFile((Resolve-Path "deploy\cloud-pc\collect-douyin-and-push.ps1").Path, [ref]$null, [ref]$errors); if ($errors.Count) { $errors } else { "PS 语法检查 OK（0 错误）" }
```

**不跑 `npm run test:e2e`**：本轮白名单不含 `assets/js/**`，未触发 CLAUDE.md 的 E2E 条款。
若施工中发现必须改前端，**停下来重新评审**，不得顺手改完再补跑。

### 6.2 人工验收步骤（打开什么 → 点什么 → 看到什么）

分三层，缺一层不算验收完成。

**第一层 · NUC 真机采集（需用户授权触发）**

1. 打开 NUC 上的采集日志文件 `C:\AI-news-reader\douyin-collect.log`，记下当前行数。
2. 触发一轮采集：`schtasks /run /tn "DouyinCollectAndPush"`。
3. 等采集结束（约 4~5 分钟），打开 `C:\AI-news-reader\douyin-collect-status.json`：
   - 看到 `state` 是 `succeeded`（而不是 `failed`）
   - 看到 6 个号的 `creator_results` **全部有回执**，不再出现「后 4 个号 `profile_valid=false`」
   - 若本轮确实被风控，看到对应号的 `state` 是 `partial`，并带 `missing_rows` 数字
4. 打开 `C:\AI-news-reader\douyin-collect.log` 新增部分，看到重试日志（形如 `[DetailRetry] ...`）。

**第二层 · 桥接仓库真的更新了**

5. 在 NUC 上看桥接仓库最后一次提交：`git -C C:\AI-news-reader\douyin-bridge log -1 --date=iso --format='%h %ad %s'`
   —— 时间应该是**刚才那一轮**，不再停在 2026-08-06 13:14。
6. 打开 `C:\AI-news-reader\douyin-bridge\manifest.json`，看到 `schema_version` 是 `2`，
   并且带 `partial` / `missing_rows` / `completed_creator_count` 字段。
7. 若本轮有缺失，打开 `C:\AI-news-reader\ai-news-radar-run\logs\bridge-collection-failures.jsonl`
   最后一行，看到 `state=warning`、`stage` 指向部分完成，且**没有**任何 cookie / token / 原始输出。

**第三层 · 看板上真的看得见（浏览器实测，CLAUDE.md 铁律要求）**

8. 等云端 Actions 跑完一轮后，用浏览器打开雷达网页。
9. 滚动到「源状态详情」区块，找到抖音那一行。
10. 本轮有缺失时 → 状态列显示黄色 **「部分完成」**；本轮全采全 → 显示绿色 **「正常」**。
11. 抖音的内容条目在时间流里出现了**本轮采到的新视频**（不再停在 08-06）。

---

## 7. 回滚与暂停条件

### 回滚

| 层 | 回滚动作 | 影响 |
|---|---|---|
| 代码 | `git revert` 本分支的实现提交，或直接不合并本分支 | 恢复到「一条不少才发布」的旧口径，即回到当前停更状态 |
| NUC 部署 | NUC 上 `git -C C:\AI-news-reader\ai-news-radar-run reset --hard <上一个 commit>` 后重跑一轮 | 同上 |
| 桥接 manifest | 无需回滚。`schema_version=2` 的多余字段对旧云端代码无害（旧 fetcher 根本不读 manifest） | 无 |
| 数据 | **无数据回滚需求**——本轮不写 `data/archive.json`，不删任何历史条目 | 无 |

**回滚不需要碰任何数据文件**，这是本轮方案刻意保持的性质。

### 必须暂停并问人的情况

1. 施工中发现必须改 `assets/js/**` 或 `index.html` —— 触发 E2E 条款，范围变了。
2. 施工中发现必须改 `data/**` 或任何清理逻辑 —— 触碰 CLAUDE.md 清理禁区，立即停。
3. 施工中发现必须改 MediaCrawler 才能实现隔离 —— 方案前提不成立，回 P5 重新评审。
4. 真机验收时发现放宽口径导致**桥接 JSONL 出现回退或截断**（`creator_output_delta` 报
   `output file was truncated or rewritten`）—— 立即停，这意味着有数据覆盖风险。
5. 真机验收时看板抖音条目**减少**而不是增加 —— 立即停，与预期相反。
6. 需要在 NUC 上执行任何 `git reset` / 强推 / 覆盖 `data/**` —— 按 CLAUDE.md 一律先问。

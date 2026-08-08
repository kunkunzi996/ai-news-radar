# 抖音采集风控容错与部分成功发布 TASKS

上游：`docs/plan.md` **PLAN v1.0 — FROZEN**（2026-08-08）
分支：`claude/inspiring-carson-299158`
基线：`tests/test_mediacrawler_runner.py` + `tests/test_bridge_collection_failure_log.py` **38 passed**；全量 **743 passed, 0 failed**

功能点 **5 个**（5 对 a/b 卡），在护栏「≤10 个功能点」之内。
（P5 评审 PLAN-02 后，原本的「TASK-05 免测卡」已改为可测的 05a/05b 配对。）

执行纪律：
- 一次只执行一张卡；`a` 卡交付时代码库里**只能有测试、没有实现**。
- 不许改测试来迁就实现。要改期望值，回 P5 重新确认。
- 基线本来就失败的测试不许顺手修（本轮基线 0 失败，任何红灯都是本轮引入的）。

---

## TASK-01a · 写测试：一个号被风控，其余号照常采完

状态：**red**
前置：无
测什么：
- `install_douyin_observer` 包装后的 `get_user_info` 抛错时，**不向外抛**，返回空 dict，
  且该号在 observer 里被记为失败。
- 包装后的 `get_all_user_aweme_posts` 在翻页途中抛错时，**不向外抛**，返回已收集到的 rows，
  且该号被记为失败。
- 用一个模拟的「6 个号顺序调用」场景断言：第 2 个号抛错后，第 3~6 个号**仍被调用到**。
期望值出处：BUG-02 卡「现象对比」——「一个号的列表被风控 → 应该：该号记失败，其余号继续采」
允许改：`tests/test_mediacrawler_runner.py`
禁止碰：`scripts/run_mediacrawler_douyin.py`（出现在 diff 里就是越界）
验收：`.venv\Scripts\python.exe -m pytest -q tests/test_mediacrawler_runner.py` **必须失败**，
      且失败原因是「异常被抛出/后续号未被调用」，不是 SyntaxError 或 import 失败
回滚：删掉新增的测试用例
--- 施工后填 ---
红证据：`pytest -q tests/test_mediacrawler_runner.py -k DouyinCreatorIsolation` → **3 failed, 37 deselected**

```
scripts\run_mediacrawler_douyin.py:954: in get_user_info
    response = await original_get_user_info(self, sec_user_id)
E   RuntimeError: Blocked by ArgusSecurityPlugin Validate Error

FAILED ... ::test_listing_failure_returns_collected_rows_without_raising
FAILED ... ::test_one_blocked_creator_does_not_stop_the_remaining_ones
FAILED ... ::test_profile_failure_is_isolated_and_returns_empty
```

失败原因是「包装层把异常原样抛出」，不是 SyntaxError / import 失败 —— 是合格的红。
实际改动：`tests/test_mediacrawler_runner.py` +144 行（`git diff --stat` 确认无实现代码混入）

## TASK-01b · 写实现：创作者隔离

状态：**green**
前置：TASK-01a（必须已经是 red）
目标：让 01a 那几条变绿
实现要点（`scripts/run_mediacrawler_douyin.py` `install_douyin_observer` 内）：
- `get_user_info` 包装：`except` 分支改为 `observer.fail(...)` 后 `return {}`，不再 `raise`
- `get_all_user_aweme_posts` 自实现循环：包住 `self.get_user_aweme_posts(...)` 调用，
  出错时 `observer.fail(...)` 并 `break`，返回已收集的 `rows`
- `get_user_aweme_posts` 包装保持 `raise`（由上面的循环接住），不改语义
允许改：`scripts/run_mediacrawler_douyin.py`
禁止碰：`tests/test_mediacrawler_runner.py`（01a 写的测试）
自测：V1 命令，预期 01a 那几条由红转绿，其余 38 条状态不变
验收：01a 全绿，且基线里原本通过的还通过
回滚：`git revert` 本卡提交
--- 施工后填 ---
实际改动：`scripts/run_mediacrawler_douyin.py` +10 −2（两处 `except` 分支）
- `get_user_info` 的 `raise` → `return {}`
- `get_all_user_aweme_posts` 的翻页调用包 try/except，失败时 `break` 保留已采行

自测结果：V1 → **41 passed**（基线 38 + 新增 3），无回归。
`git diff --name-only` 确认测试文件 0 处改动，未改 01a 写的测试。
未完成项：无。异常消息的净化（PLAN-06）按计划留给 TASK-03b 统一处理。

---

## TASK-02a · 写测试：详情被风控先重试再放行

状态：**red**
前置：TASK-01b
测什么：
- 包装后的 `get_video_by_id` 首次抛错、第二次成功时，**对外表现为成功**，且底层被调用 2 次。
- 连续失败超过重试上限时，**抛回原异常对象**（类型不变，供 MediaCrawler 既有 `except DataFetchError` 接住）。
- 重试之间有退避等待（用可注入的 sleep 断言被调用，不真的睡）。
期望值出处：`docs/plan.md`「决策 1」
允许改：`tests/test_mediacrawler_runner.py`
禁止碰：`scripts/run_mediacrawler_douyin.py`
验收：V1 命令必须失败，失败原因是「重试未发生 / 异常类型被改写」
回滚：删掉新增的测试用例
--- 施工后填 ---
红证据：`pytest -q tests/test_mediacrawler_runner.py -k DouyinDetailRetry` → **3 failed, 40 deselected**

```
tests/test_mediacrawler_runner.py:768: TypeError
E   TypeError: install_douyin_observer() got an unexpected keyword argument 'sleeper'
```

**第一次红是假的，已修正并如实记录**：初版用
`fake_mediacrawler_modules = DouyinCreatorIsolationTests.fake_mediacrawler_modules` 复用夹具，
少了 `staticmethod()` 包装，红的原因是 `TypeError: takes 0 positional arguments`——
那是测试自己写坏了，按导航规范 P6 第 ② 步不算合格的红，已修好重跑。

**第三条一度直接变绿，已加强**：`test_detail_wrapper_does_not_retry_on_success`
最初对「实现前」和「实现后」都成立（没有重试逻辑时自然也不重试），没有区分能力。
补上 `assertEqual(slept, [])` 并改为经 `sleeper` 注入后，三条才一起变红。
实际改动：`tests/test_mediacrawler_runner.py` +85 行（`git diff --stat` 确认无实现代码混入）

## TASK-02b · 写实现：详情重试

状态：**green**
前置：TASK-02a（必须已经是 red）
目标：让 02a 那几条变绿
实现要点：在 `install_douyin_observer` 内新增 `DouYinClient.get_video_by_id` 包装，
退避重试（默认 2 次重试，间隔可配），耗尽后 `raise` **原异常对象**；
重试事件打一行可见日志（形如 `[DetailRetry] aweme=<id> attempt=2/3`），不打印任何 cookie/token。
允许改：`scripts/run_mediacrawler_douyin.py`
禁止碰：`tests/test_mediacrawler_runner.py`
自测：V1 命令，预期 02a 转绿，01a/01b 保持绿
验收：同上
回滚：`git revert` 本卡提交
--- 施工后填 ---
实际改动：`scripts/run_mediacrawler_douyin.py` +40 −1
- 新增常量 `DOUYIN_DETAIL_RETRY_ATTEMPTS = 2`、`DOUYIN_DETAIL_RETRY_BACKOFF_SECONDS = (2.0, 5.0)`
  与 `douyin_detail_backoff_seconds()`（总尝试 3 次，退避 2s → 5s）
- `install_douyin_observer` 增加可选关键字参数 `sleeper`（默认 `asyncio.sleep`，仅供测试注入）
- 新增 `get_video_by_id` 包装并挂上 `DouYinClient`；耗尽后 `raise last_error` 抛回原对象
- 重试日志只打 `aweme` 与 `attempt`，**不打异常消息**（它拼着抖音原始响应体，见 PLAN-06）

自测结果：V1 → **44 passed**（41 + 新增 3），无回归；V3 `py_compile` OK。
`git diff --stat` 确认只动实现文件，未改 02a 写的测试。
未完成项：无。

---

## TASK-03a · 写测试：回执三态与「采到多少发多少」

状态：**red**
前置：TASK-02b
测什么：
- `finalize()` 三态判定：`written == listed` → `completed`；`0 < written < listed` → `partial`；
  `written == 0` 或 profile/api 未通过 → `failed`。
- `summary()` 返回 `partial_creator_count`、`missing_rows`（各号 `listed - written` 之和）、
  `partial`（有任一号非 completed 且至少一号有内容时为 True）。
- `main()` 行为：至少一个号 `completed`/`partial` 且本轮有新增行时，**退出码 0**、
  result JSON 带 `partial=true` 与 `missing_rows`；6 个号全 `failed` 时**仍然失败**（fail-safe）。
- **PLAN-06 净化**：喂一个含响应体的异常（如
  `DataFetchError("Expecting value: line 1 column 1 (char 0), <html>SECRET_BODY</html>")`），
  断言写进 result JSON 的 `creator_results[].error` 与 `warnings` 里**不出现 `SECRET_BODY`**，
  只出现归一化分类，且单条长度 ≤200 字符。
期望值出处：`docs/plan.md`「决策 3」「决策 5」「决策 6」；用户 2026-08-08 拍板「不管采集了多少，都同步到看板」
允许改：`tests/test_mediacrawler_runner.py`
禁止碰：`scripts/run_mediacrawler_douyin.py`
验收：V1 命令必须失败，失败原因是「无 partial 态 / 仍然 raise partial_creator_failure」
回滚：删掉新增的测试用例
--- 施工后填 ---
红证据：`pytest -q tests/test_mediacrawler_runner.py -k DouyinPartialReceipt` → **7 failed, 43 deselected**

```
E   KeyError: 'partial_creator_count'
tests/test_mediacrawler_runner.py:868: KeyError
```

7 条全红，原因是三态与新字段尚不存在（KeyError / 状态值不匹配），不是测试写坏。
实际改动：`tests/test_mediacrawler_runner.py` +156 行（`git diff --stat` 确认无实现代码混入）

## TASK-03b · 写实现：回执三态与放宽退出条件

状态：**green**
前置：TASK-03a（必须已经是 red）
目标：让 03a 那几条变绿
实现要点（`scripts/run_mediacrawler_douyin.py`）：
- `DouyinRunObserver.finalize()` 增加 `partial` 态；`summary()` 增加
  `partial_creator_count` / `missing_rows` / `partial`
- `runner_result_payload()` 透传上述字段
- `main():1157` 的无条件 `raise` 改为：**只有在没有任何号采到内容时**才 raise，
  否则正常走到写 result JSON 并 `return 0`
允许改：`scripts/run_mediacrawler_douyin.py`
禁止碰：`tests/test_mediacrawler_runner.py`
自测：V1 命令 + V3 `py_compile`
验收：03a 全绿，01/02 保持绿
回滚：`git revert` 本卡提交
--- 施工后填 ---
实际改动：`scripts/run_mediacrawler_douyin.py` +59 −7
- 新增 `sanitize_douyin_error()` 与 `DOUYIN_ERROR_MESSAGE_MAX_CHARS = 200`：
  风控归一为 `douyin_risk_control`，其余丢弃 `", "` 之后的响应体并截断 200 字符
- `_new_record` 增 `missing_rows`；`fail()` 改为存净化后的消息
- `finalize()` 改三态（合法空账号仍判 `completed`）；`summary()` 增
  `partial_creator_count` / `missing_rows` / `partial`
- `runner_result_payload()` 默认字典补齐新字段
- `main()` 的 `raise partial_creator_failure` 改为 `all_creators_failed`，
  **仅在没有任何号产出回执时**才抛
- `main()` 的 except 分支：先按原文判 `login_required`，再净化后才写日志与 payload

**一处经用户授权的基线测试改动**（`tests/test_mediacrawler_runner.py` +7 −1）：
`test_partial_creator_receipt_cannot_finalize_as_success` 原断言 `failed_creator_count == 1`，
锁的是被本轮有意替换掉的旧口径。经用户 2026-08-08 拍板「保留意图、适配三态」，
改为断言该号是 `partial`、显式 `assertNotEqual(..., "completed")`，并新增
`partial_creator_count` 与 `summary["partial"]` 断言。测试名与保护意图未变。

自测结果：V1 → **51 passed**（44 + 新增 7），无回归；V3 `py_compile` OK。
未完成项：无。

---

## TASK-04a · 写测试：云端从桥接 manifest 读出采集健康

状态：**red**
前置：TASK-03b
测什么：
- `fetch_mediacrawler_douyin_subscriptions` 返回的 status 里带
  `partial` / `missing_rows` / `completed_creator_count` / `failed_creator_count`，值来自
  桥接仓库根的 `manifest.json`（schema_version 2）。
- manifest **缺失 / 是坏 JSON / 是旧 schema 1** 三种情况下，**不抛异常、不影响条目解析**，
  status 里标出 manifest 不可用，`partial` 回落为 False。
期望值出处：`docs/plan.md`「决策 4」；前端字段语义对齐 `scripts/radar/cli.py:508`
允许改：`tests/test_private_bridge_sources.py`
禁止碰：`scripts/radar/fetchers/mediacrawler.py`
验收：`.venv\Scripts\python.exe -m pytest -q tests/test_private_bridge_sources.py` **必须失败**
回滚：删掉新增的测试用例
--- 施工后填 ---
红证据：`pytest -q tests/test_private_bridge_sources.py -k DouyinBridgeManifestHealth` → **5 failed, 40 deselected**

```
tests/test_private_bridge_sources.py:1174: KeyError
E   KeyError: 'partial'
```

5 条全红，原因是 status 里还没有健康字段，不是测试写坏。
实际改动：`tests/test_private_bridge_sources.py` +107 行（`git diff --stat` 确认无实现代码混入）

## TASK-04b · 写实现：fetcher 读 manifest 填 partial

状态：**green**
前置：TASK-04a（必须已经是 red）
目标：让 04a 那几条变绿
实现要点（`scripts/radar/fetchers/mediacrawler.py`）：
从已解析的 JSONL 路径上溯到桥接仓库根，容错读取 `manifest.json`，
把健康字段并入 `fetch_mediacrawler_douyin_subscriptions` 的返回 status；
**任何读取失败都必须静默降级**，不得影响条目产出。
允许改：`scripts/radar/fetchers/mediacrawler.py`
禁止碰：`tests/test_private_bridge_sources.py`
自测：V2 + V3 命令
验收：04a 全绿，前面各卡保持绿
回滚：`git revert` 本卡提交
--- 施工后填 ---
实际改动：`scripts/radar/fetchers/mediacrawler.py` +62
- 新增常量 `DOUYIN_BRIDGE_MANIFEST_SCHEMA = 2` 与 `douyin_bridge_collection_health()`
- 上溯用 `jsonl_path.resolve().parents[3]` 定位桥接仓库根（已由 PLAN-05 实测确认：
  云端 `bridge_dir="$RUNNER_TEMP/douyin-bridge"`，JSONL 在其 `output/douyin/jsonl/` 下）
- 循环里记录首个可用 JSONL 作为 manifest 溯源点，返回 status 时以 `**health` 并入
- 缺文件 / 坏 JSON / 旧 schema 1 / 任意异常一律降级为
  `collection_manifest_available=False` 且 `partial=False`，条目产出完全不受影响

自测结果：V2 → **45 passed**（40 + 新增 5），无回归；V3 `py_compile` OK。
`git diff --stat` 确认只动实现文件，未改 04a 写的测试。
未完成项：无。

---

## TASK-05a · 写测试：采集脚本在「部分完成」时照样发布

状态：**red**
前置：TASK-03b

> P5 评审 PLAN-02 更正：初稿误判「PS 脚本无法自动化测试」。
> `tests/test_bridge_collection_failure_log.py:28-130` 已有
> 「假 runner + 真 `.ps1` + 真 git 桥接仓库」的端到端夹具，本卡直接扩展它，不新增测试框架。

测什么（复用既有夹具，把假 runner 的 result JSON 换成部分完成场景）：
- **B1 发布口径**：6 个号里 1 个 `completed`、1 个 `partial`、4 个 `failed`，且
  `crawl_output_rows > 0` 时，PS 脚本**退出码 0**，桥接仓库 **HEAD 前进**（原本会停住不推）。
- **fail-safe**：6 个号全 `failed`、`crawl_output_rows = 0` 时，仍然不发布，HEAD 不动。
- **B2 manifest**：发布后 `manifest.json` 的 `schema_version` 为 `2`，且含
  `partial` / `missing_rows` / `completed_creator_count` / `partial_creator_count` / `failed_creator_count`。
- **B3 留痕**：有缺失时 `logs/bridge-collection-failures.jsonl` 追加一条 `state=warning` 记录，
  字段集合**恰好是既有的 10 个**（照抄既有断言的 `assert set(...) == {...}` 写法）。
- **PLAN-06 净化**：把假 runner 的错误消息设成含响应体的字符串
  （如 `Expecting value: line 1 column 1 (char 0), <html>SECRET_BODY</html>`），
  断言留痕记录的 `message` 里**不出现 `SECRET_BODY`**，且长度 ≤512。
期望值出处：`docs/plan.md`「决策 5」「决策 6」；用户 2026-08-08 拍板「采到多少发多少」
允许改：`tests/test_bridge_collection_failure_log.py`
禁止碰：`deploy/cloud-pc/collect-douyin-and-push.ps1`
验收：`.venv\Scripts\python.exe -m pytest -q tests/test_bridge_collection_failure_log.py`
      **必须失败**，且失败原因是「HEAD 未前进 / manifest 仍是 schema 1 / 无 warning 记录」
回滚：删掉新增的测试用例
--- 施工后填 ---
红证据：`pytest -q tests/test_bridge_collection_failure_log.py` → **2 failed, 2 passed**

```
test_partial_collection_still_publishes_and_is_recorded
E   assert 1 == 0        ← PS 脚本退出码 1，部分完成时拒绝发布（正是 BUG-02 的现象）

test_fully_completed_collection_leaves_no_failure_record
E   assert manifest["schema_version"] == 2
E   assert 1 == 2        ← manifest 仍是 schema 1，没有健康字段
```

**一条新测试直接为绿，已查明原因并保留**：`test_all_creators_failed_does_not_publish`
验证的 fail-safe（一个号都没采到时不发布）在改动前后都应成立，它是**防止本轮放宽口径时
把保险丝一起拆掉**的回归护栏，不是本卡的红证据。按导航规范「测试一开始就绿必须停下来查」，
已查明并如实记录，不当作已验证的新功能。
实际改动：`tests/test_bridge_collection_failure_log.py` +215 行
（`git diff --stat` 确认无 `.ps1` 改动混入）

## TASK-05b · 写实现：采集脚本放宽口径、写 manifest、缺失留痕

状态：**green**
前置：TASK-05a（必须已经是 red）
目标：让 05a 那几条变绿

实现要点（`deploy/cloud-pc/collect-douyin-and-push.ps1`）：
- **B1** `:384-397` 的 receipt 校验：从「6 个号全 completed」改为
  「至少 1 个号 completed 或 partial，且 `crawl_output_rows > 0`」；全 failed 时仍 `Exit-Run warning`
- **B2** `:443-470` manifest：`schema_version` 1 → 2，新增
  `partial` / `missing_rows` / `completed_creator_count` / `partial_creator_count` / `failed_creator_count`；
  `:447` 的迁移判断同步改为 `-ne 2`
- **B3** 本轮有缺失时，往 `logs\bridge-collection-failures.jsonl` 追加一条
  `state=warning` 记录。**必须遵守 CLAUDE.md 的留痕契约**：固定 10 字段、
  `message` ≤512 字符、按渠道与 `run_id` 去重、禁写原始输出/cookie/token/凭证；
  写日志失败只能告警，不得覆盖原状态或退出码
- **净化**（`docs/plan.md` 决策 6）：`message` 只写归一化分类 + 计数，
  **绝不拼接 runner 的原始错误字符串**（它含抖音响应体）

允许改：`deploy/cloud-pc/collect-douyin-and-push.ps1`
禁止碰：`deploy/local/collect-wechat-and-push.ps1`、`data/**`、
        `tests/test_bridge_collection_failure_log.py`（05a 写的测试）
自测：`.venv\Scripts\python.exe -m pytest -q tests/test_bridge_collection_failure_log.py` +
      V4 PowerShell 语法检查（预期 0 错误）
人工验收：`docs/plan.md` 第 6.2 节第一层第 3 步、第二层第 5~7 步
回滚：`git revert` 本卡提交；NUC 侧回退到上一个 commit 重跑一轮
--- 施工后填 ---
实际改动：`deploy/cloud-pc/collect-douyin-and-push.ps1` +41 −13
- **B1**：receipt 校验从「6/6 全 completed」改为「至少 1 个 completed 或 partial，
  且这些号的 profile/api 校验都通过」；全失败仍 `Exit-Run warning` 不发布
- **B2**：`schema_version` 1 → 2，新增 `partial` / `missing_rows` /
  `completed_creator_count` / `partial_creator_count` / `failed_creator_count`；
  迁移判断同步改为 `-ne 2`，首轮即重写 manifest
- **B3**：`$script:Status` 增 `partial` / `missing_rows` / `partial_creator_count`
  三个字段并加入 runner result 拷贝列表；`Write-BridgeFailureRecord` 的
  「succeeded 且登录态正常就 return」门槛加上 `-not $isPartialRun`，
  部分完成轮次改记 `state=warning` / `stage=partial_collection`
- **净化**：留痕 message 由脚本自己拼装（缺失行数 + 不完整号数），
  **完全不引用 runner 的原始错误文本**

自测结果：
- `pytest -q tests/test_bridge_collection_failure_log.py` → **4 passed**（05a 的 2 红转绿，
  回归护栏与基线各 1 条保持绿），含 `SECRET_BODY` 不外泄的断言
- V4 PS 语法检查 → **0 错误**
- 文件编码复核：**BOM 保留 True**、CRLF 515 行（CLAUDE.md 对 `.ps1` 的硬要求）
- `git diff --name-only` 确认只动 `.ps1`，未改 05a 写的测试

未完成项：无。

---

---

## TASK-06a · 写测试：健康状态变化时 manifest 必须刷新（P7 代码评审补卡）

状态：**red**
前置：TASK-05b
来源：**P7 代码评审 CODE-01**，不是原冻结计划里的功能点。

**发现的缺陷**：`collect-douyin-and-push.ps1` 只在
`$contentChanged -or $manifestNeedsMigration` 时重写 manifest。于是——

1. 某轮被风控 → manifest 写入 `partial=true` 并推送；
2. 下一轮全采全，但**没有新视频**（`source_sha256` 与桥接里相同）→ `contentChanged=false`；
3. schema 已经是 2 → `manifestNeedsMigration=false`；
4. **manifest 不被重写** → 桥接里 `partial` 永远停在 `true`
   → 云端看板的黄色「部分完成」再也下不去，用户看到的是过期的健康状态。

测什么：连跑两轮同一夹具——第一轮 partial（写入 `partial=true`），
第二轮内容完全相同但六个号全 completed，断言第二轮后 `manifest.json` 的
`partial` 变回 `false`、`missing_rows` 归 0。
期望值出处：`docs/plan.md` 第 4 章「成功态：本轮 6 个号全采全 → 仍显示 `正常`」
允许改：`tests/test_bridge_collection_failure_log.py`
禁止碰：`deploy/cloud-pc/collect-douyin-and-push.ps1`
验收：`pytest -q tests/test_bridge_collection_failure_log.py` 必须失败，
      失败原因是「第二轮 manifest 仍是 partial=true」
回滚：删掉新增的测试用例
--- 施工后填 ---
红证据：`pytest -q tests/test_bridge_collection_failure_log.py::test_manifest_health_refreshes_even_when_content_is_unchanged` → **1 failed**

```
E   AssertionError: 健康恢复后 manifest 必须刷新，否则看板黄标下不去
E   assert True is False
```

第一轮写入 partial=true 正常；第二轮 JSONL 内容完全相同、六个号全 completed，
manifest 却没被重写，partial 仍是 true —— CODE-01 稳定复现。
实际改动：`tests/test_bridge_collection_failure_log.py` +57 行（只有测试）

## TASK-06b · 写实现：健康字段变化也触发 manifest 重写

状态：**green**
前置：TASK-06a（必须已经是 red）
目标：让 06a 变绿
实现要点：读旧 manifest 时额外算出 `$manifestHealthChanged`（比较 `partial` /
`missing_rows` / 三态计数），并入 manifest 重写条件。
允许改：`deploy/cloud-pc/collect-douyin-and-push.ps1`
禁止碰：`tests/test_bridge_collection_failure_log.py`
自测：`pytest -q tests/test_bridge_collection_failure_log.py` + V4 语法检查
验收：06a 转绿，05a 的三条保持绿
回滚：`git revert` 本卡提交
--- 施工后填 ---
实际改动：`deploy/cloud-pc/collect-douyin-and-push.ps1` +12 −2
- 读旧 manifest 时新增 `$manifestHealthChanged`：逐一比较 `partial` / `missing_rows` /
  `completed_creator_count` / `partial_creator_count` / `failed_creator_count`
- 重写条件从 `$contentChanged -or $manifestNeedsMigration`
  扩为 `... -or $manifestHealthChanged`

自测结果：
- `pytest -q tests/test_bridge_collection_failure_log.py` → **5 passed**（06a 转绿，05a 三条保持绿）
- V4 PS 语法检查 → **0 错误**；BOM 保留 True
未完成项：无。

---

---

## TASK-07a · 写测试：云端实际走的默认分支也要带健康字段（P8 验收补卡）

状态：**red**
前置：TASK-06b
来源：**P8 真实验收 QA-01**。这是本轮唯一一条「自动化测试全绿但产品不能用」的失败。

**验收现场**：NUC 采集成功、桥接更新成功、manifest 是 schema 2 且字段齐全，
但云端 `data/source-status.json` 的抖音条目里**一个健康字段都没有**——
只有 `item_count: 52`，没有 `partial` / `missing_rows` / `collection_manifest_available`。

**根因**：抖音 fetcher 有两条路。TASK-04b 只改了订阅分支
`fetch_mediacrawler_douyin_subscriptions`，而**云端实际走的是默认分支**
`maybe_fetch_mediacrawler_douyin`（由 `MEDIACRAWLER_DOUYIN_JSONL` 环境变量驱动）。
线上 status 的 `site_name` 是 `MediaCrawler Douyin` 且没有 `subscriptions` 字段，即为铁证。
04a 写的 5 条测试全绿，是因为它们全都在测那条**云端根本不走的路**。

测什么：
- `maybe_fetch_mediacrawler_douyin` 在 schema 2 manifest 下，status 同样带
  `partial` / `missing_rows` / `completed_creator_count` / `partial_creator_count` /
  `collection_manifest_available`。
- manifest 缺失时静默降级，条目产出不受影响。
期望值出处：`docs/plan.md` 第 4 章「界面与流程」；P8 验收现场观测
允许改：`tests/test_private_bridge_sources.py`
禁止碰：`scripts/radar/fetchers/mediacrawler.py`
验收：`pytest -q tests/test_private_bridge_sources.py -k default_branch` 必须失败
回滚：删掉新增的测试用例
--- 施工后填 ---
红证据：`pytest -q tests/test_private_bridge_sources.py -k default_branch` → **2 failed, 45 deselected**

```
tests/test_private_bridge_sources.py:1270: KeyError
E   KeyError: 'partial'
```

默认分支的 status 里根本没有健康字段，与线上观测完全一致。
实际改动：`tests/test_private_bridge_sources.py` +60 行（只有测试）

## TASK-07b · 写实现：默认分支并入健康字段

状态：**green**
前置：TASK-07a（必须已经是 red）
目标：让 07a 转绿
实现要点：`maybe_fetch_mediacrawler_douyin` 的成功路径 `status.update(douyin_bridge_collection_health(jsonl_path))`；
把 `DOUYIN_BRIDGE_MANIFEST_SCHEMA` 与 `douyin_bridge_collection_health` 上移到两个 fetcher 之前（纯移动，无逻辑变化）。
允许改：`scripts/radar/fetchers/mediacrawler.py`
禁止碰：`tests/test_private_bridge_sources.py`
自测：V2 + V3 命令
验收：07a 转绿，04a 的 5 条保持绿
回滚：`git revert` 本卡提交
--- 施工后填 ---
实际改动：`scripts/radar/fetchers/mediacrawler.py` +64 −57（其中 57 行是纯位置移动）
- 把 `DOUYIN_BRIDGE_MANIFEST_SCHEMA` 与 `douyin_bridge_collection_health` 上移到
  两个 fetcher 之前，并在注释里写明**两条分支都必须并入**（初版就是漏了默认分支）
- `maybe_fetch_mediacrawler_douyin` 成功路径加 `status.update(douyin_bridge_collection_health(jsonl_path))`

自测结果：V2 → **47 passed**（45 + 新增 2），无回归；V3 `py_compile` OK。
未完成项：无。

---

## 施工后的整体动作（不是任务卡，是过门条件）

| 阶段 | 动作 | 过关标准 |
|---|---|---|
| P7 整体回归 | V5 全量 `pytest -q` | 与基线三条对照：743 passed 里原本通过的还通过；0 失败保持 0；本轮新增测试全绿 |
| P7 代码评审 | 审整体 diff | 无越界文件、无隐藏失败、错误处理完整 |
| P8 真实验收 | `docs/plan.md` 第 6.2 节三层 | **由用户本人确认接受**；AI 只负责产出证据 |

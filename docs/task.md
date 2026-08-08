# 采集结束后清理残留标签页 TASKS

上游：`docs/plan.md`（待冻结）
分支：`fix/close-browser-after-collect`
基线：`tests/test_mediacrawler_runner.py` 23 passed；全量 729 passed

功能点 3 个（3 对卡），在护栏「≤10 个功能点」之内。
执行纪律：一次只执行一张卡；`a` 卡交付时代码库里只能有测试、没有实现。

---

## TASK-01a · 写测试：算出「本轮新增的标签页」

状态：pending
前置：无
测什么：`select_leaked_page_targets(before_ids, after_targets, min_keep=1)` 的判断逻辑。
期望值出处：BUG-01「现象对比」——「重复采集不会让标签页数量随轮次单调增长」，
以及 plan.md 第 3.4 节的四条硬约束。至少覆盖：

1. **正常泄漏**：`before={"A"}`，`after=[A,B,C]` → 返回 `["B","C"]`（只关新增的）。
2. **无泄漏**：`before={"A"}`，`after=[A]` → 返回 `[]`。
3. **保底不关光**：`before=set()`，`after=[A,B]` → 只返回 1 个，保留至少 1 个页面
   （对应约束 1：关光会导致 Chrome 退出，等于滑向已放弃的口径 B）。
4. **不按 URL 判断**：三个 target 的 `url` 全部相同（都是 `https://www.douyin.com/jingxuan`）
   时，仍按 id 差集正确区分（对应约束 4）。
5. **采集前的页面被关掉过**：`before={"A","B"}`，`after=[B,C]` → 返回 `["C"]`
   （消失的 A 不参与判断，不报错）。

允许改：`tests/test_mediacrawler_runner.py`
禁止碰：`scripts/run_mediacrawler_douyin.py`（出现在 diff 里就是越界）
验收：跑测试必须失败，且失败原因是 `ImportError` / `AttributeError` —— 即
      「`select_leaked_page_targets` 这个函数还不存在」。
      **注意**：本项目测试在文件头部集中 `from scripts.run_mediacrawler_douyin import (...)`，
      新函数加进该导入列表后，未实现时整个文件会 ImportError。这属于「功能不存在」，
      是有效的红；但要确认报错指向的正是新函数名，不是拼写错误或语法错误。
自测：`.venv\Scripts\python.exe -m pytest tests/test_mediacrawler_runner.py -q`
回滚：删掉新增的测试方法与导入项
--- 施工后填 ---
状态：**red**（2026-08-08）
红证据：

```
ImportError while importing test module '...\tests\test_mediacrawler_runner.py'.
tests\test_mediacrawler_runner.py:14: in <module>
    from scripts.run_mediacrawler_douyin import (
E   ImportError: cannot import name 'select_leaked_page_targets' from
    'scripts.run_mediacrawler_douyin' (...\scripts\run_mediacrawler_douyin.py)
ERROR tests/test_mediacrawler_runner.py
1 error in 0.20s
```

失败原因确为「功能不存在」，报错精确指向新函数名 `select_leaked_page_targets`，
不是语法错误或拼写错误。符合本卡验收条件。

实际改动：`git diff --stat` = `tests/test_mediacrawler_runner.py | 36 ++++++`，
**1 file changed, 36 insertions(+)**，无实现代码混入。新增 5 个测试方法 + 1 个导入项
+ 1 个测试辅助方法 `page_target`。

## TASK-01b · 写实现：算出「本轮新增的标签页」

状态：pending
前置：TASK-01a（必须已经是 red）
目标：让 01a 的全部用例变绿。只实现 `select_leaked_page_targets` 这个纯函数，不碰 CDP、不碰 main。
允许改：`scripts/run_mediacrawler_douyin.py`
禁止碰：`tests/test_mediacrawler_runner.py`（不许改测试来迁就实现）
自测：`.venv\Scripts\python.exe -m pytest tests/test_mediacrawler_runner.py -q`
      预期：01a 那几条从红变绿，原有 23 条仍全部通过
验收：该文件全绿且总数 = 23 + 01a 新增条数
回滚：撤回 `select_leaked_page_targets` 函数
--- 施工后填 ---
状态：**green**（2026-08-08）
实际改动：`scripts/run_mediacrawler_douyin.py` 新增纯函数 `select_leaked_page_targets`
（+21 行，插在 `ensure_dedicated_browser` 之后）。未改测试文件。
自测结果：`28 passed in 0.14s` = 基线 23 + 本卡 5。原有 23 条全部仍通过。
未完成项：无。

---

## TASK-02a · 写测试：列出与关闭 CDP 标签页

状态：pending
前置：TASK-01b
测什么：两个 I/O 函数对 DevTools HTTP 端点的调用契约（`cdp_json` 全程 mock，不起真实浏览器）。
期望值出处：plan.md 第 2 章第 6 条（现有 `cdp_json` 的既有用法）与第 3.2 节的职责定义。

1. `list_cdp_page_targets(port)` 调用 `/json/list`，**过滤掉 `type != "page"` 的条目**
   （service_worker、iframe、background_page 都不算标签页，误关会出问题）。
2. `list_cdp_page_targets` 返回结构含 `id` 与 `url`；缺字段的条目不得抛异常。
3. `close_cdp_page_targets(port, ["B","C"])` 对每个 id 各调一次 `/json/close/<id>`，
   顺序与入参一致。
4. 其中一个 id 关闭抛异常时，**其余仍继续关**，返回值如实反映 `closed` / `failed` 计数
   （对应 plan.md 约束 3：清理失败不掩盖、不中断）。
5. 空列表入参时不发起任何请求。

允许改：`tests/test_mediacrawler_runner.py`
禁止碰：`scripts/run_mediacrawler_douyin.py`
验收：跑测试必须失败，失败原因是这两个函数不存在
自测：`.venv\Scripts\python.exe -m pytest tests/test_mediacrawler_runner.py -q`
回滚：删掉新增的测试方法
--- 施工后填 ---
状态：**red**（2026-08-08）
红证据：

```
tests\test_mediacrawler_runner.py:14: in <module>
    from scripts.run_mediacrawler_douyin import (
E   ImportError: cannot import name 'close_cdp_page_targets' from 'scripts.run_mediacrawler_douyin'
ERROR tests/test_mediacrawler_runner.py
1 error in 0.16s
```

实际改动：本卡增量仅 `tests/test_mediacrawler_runner.py`（+53 行，5 个测试方法 + 2 个导入项）。
`git diff --stat` 中 `scripts/` 的 21 行是 TASK-01b 已交付的实现（累积 diff），不属于本卡增量。

## TASK-02b · 写实现：列出与关闭 CDP 标签页

状态：pending
前置：TASK-02a（必须已经是 red）
目标：让 02a 全绿。复用 `scripts/radar/server/cdp.py:36` 的 `cdp_json`，**不新增第三方依赖**，
      **不修改 cdp.py**。
允许改：`scripts/run_mediacrawler_douyin.py`
禁止碰：`tests/test_mediacrawler_runner.py`、`scripts/radar/server/cdp.py`
自测：`.venv\Scripts\python.exe -m pytest tests/test_mediacrawler_runner.py -q`
验收：该文件全绿，且 01a/01b 的用例仍然通过
回滚：撤回这两个函数
--- 施工后填 ---
状态：**green**（2026-08-08）
实际改动：`scripts/run_mediacrawler_douyin.py` 新增 `cdp_request_text`、`list_cdp_page_targets`、
`close_cdp_page_targets`（+38 行）。**按 PLAN-02 修正，沿用本文件既有的 urllib 直连模式，
未引入 `scripts.radar` 包依赖，未修改 `scripts/radar/server/cdp.py`。**
自测结果：`33 passed in 0.13s` = 23 + 5 + 5。
未完成项：无。

---

## TASK-03a · 写测试：把清理接进采集主流程

状态：pending
前置：TASK-02b
测什么：`main()` 在采集前后的接线行为（全程 mock，不起浏览器、不跑 MediaCrawler）。
期望值出处：BUG-01「现象对比」的「应该」栏 + plan.md 第 3.4 节约束 2/3/5。

1. **正常采集**：采集前调用一次 `list_cdp_page_targets` 取快照，采集后再调一次，
   并以差集结果调用 `close_cdp_page_targets`。
2. **`--browser-only` 模式不清理**：该模式给人扫码用，必须一个标签页都不关
   （对应约束 2）。
3. **采集失败也要清理**：`run_mediacrawler` 抛异常时，清理仍然执行（对应约束 5）。
4. **清理失败不改变返回码、不掩盖原始错误**：`close_cdp_page_targets` 抛异常时，
   采集成功仍返回 0；采集失败时原始错误信息不被替换（对应约束 3）。

允许改：`tests/test_mediacrawler_runner.py`
禁止碰：`scripts/run_mediacrawler_douyin.py`
验收：跑测试必须失败，失败原因是主流程尚未接线（断言「清理被调用」不成立），
      不是 import 或语法错误
自测：`.venv\Scripts\python.exe -m pytest tests/test_mediacrawler_runner.py -q`
回滚：删掉新增的测试方法
--- 施工后填 ---
状态：**red**（2026-08-08）
红证据：

```
E   AssertionError: Expected 'close_cdp_page_targets' to be called once. Called 0 times.
FAILED ...::test_cleanup_failure_does_not_change_exit_code
FAILED ...::test_collect_closes_only_pages_opened_during_run
FAILED ...::test_failed_collection_still_closes_leaked_pages
3 failed, 34 passed in 0.24s
```

失败原因是主流程未接线（清理从未被调用），不是 import 或语法错误。

**关于第 4 个用例 `test_browser_only_keeps_every_page_open` 一开始就是绿的**：
它断言「browser-only 模式下一个标签页都不关」，在尚未接线时必然成立。这是**守卫型测试**，
价值在 b 卡之后——若实现遗漏了「跳过 browser-only」，它会立刻变红。经确认属于合理情况，
不是「功能已存在」也不是「测试写错了」，故未按手册停止条件中止。

实际改动：本卡增量仅 `tests/test_mediacrawler_runner.py`（+85 行，4 个测试方法 + 2 个测试夹具）。

## TASK-03b · 写实现：把清理接进采集主流程

状态：pending
前置：TASK-03a（必须已经是 red）
目标：让 03a 全绿。在 `main()` 中接入快照与清理，满足 plan.md 第 3.4 节全部五条约束。
允许改：`scripts/run_mediacrawler_douyin.py`
禁止碰：`tests/test_mediacrawler_runner.py`、`douyin_login_state`、`check_douyin_login_state`
        （改到登录态逻辑就触发 plan.md 第 7 章暂停条件 2，必须停下来问人）
自测：
  1. `.venv\Scripts\python.exe -m pytest tests/test_mediacrawler_runner.py -q` → 全绿
  2. `.venv\Scripts\python.exe -m py_compile scripts/run_mediacrawler_douyin.py` → 无输出
验收：本文件全绿；随后进 P7 跑全量对照基线 729 passed
回滚：撤回 `main()` 中的接线改动（三个新函数可保留，不影响行为）
--- 施工后填 ---
状态：**green**（2026-08-08）
实际改动：
1. 新增 `snapshot_cdp_page_ids(port)`：采集前取 id 快照，失败返回 `None` 表示放弃本轮清理
   （不知道采集前有什么就宁可不关，也不误关）。
2. 新增 `close_leaked_pages(port, before_ids)`：算差集并关闭，全程 `try/except`，
   任何失败只往 stderr 告警。
3. `main()` 接线：快照点放在 `if args.browser_only: return 0` **之后**（约束 2 自动满足）；
   采集段整体包进 `try/…/finally: close_leaked_pages(...)`（约束 5：失败轮次同样清理）；
   整块仍在 `with collection_lock_context(...)` 之内（约束 6：并发保护）。
未改动 `douyin_login_state` / `check_douyin_login_state`，未触发暂停条件 2。

自测结果：
- `.venv\Scripts\python.exe -m pytest tests/test_mediacrawler_runner.py -q` → `37 passed in 0.14s`
  （= 基线 23 + 本轮新增 14）
- `.venv\Scripts\python.exe -m py_compile scripts/run_mediacrawler_douyin.py` → 退出码 0，无输出

未完成项：P8 真实验收（NUC 上人工走一遍）尚未进行，需先部署到 NUC。

---

## 施工后的整体验证（P7 / P8，不属于任何单卡）

- P7 全量回归：`.venv\Scripts\python.exe -m pytest -q`
  三条对照必须同时成立：基线 729 条全部仍通过 / 基线无失败项故无「顺手修好」嫌疑 /
  本轮新增用例全绿。
- P8 真实验收：按 `docs/plan.md` 第 6.2、6.3 节在 NUC 上人工走一遍，由用户本人确认接受。

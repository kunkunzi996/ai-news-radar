# BUG-02: 抖音一条视频详情被风控拦下，整轮 52 条全部作废，桥接停更两天

状态：**已修复，三层真实验收全部通过（2026-08-08）**｜等待用户最终接受

## 验收结论（2026-08-08，NUC + 桥接 + 云端 + 浏览器实测）

| 层 | 验收项 | 结果 |
|---|---|---|
| 一 | 六个号都拿到回执 | ✅ 6/6 全 `completed`（故障轮里后 4 个号 `profile=False` 压根没被访问） |
| 一 | 不再整轮作废 | ✅ `state=succeeded`、`exit=0`、`bridge_changed=True` |
| 一 | 采集量 | ✅ `crawl_output_rows=52`，正常值 |
| 一 | 重试真的生效 | ✅ `[DetailRetry]` 触发 **2 次**，均 `attempt=2/3` 一次救回 |
| 一 | 日志不泄露响应体 | ✅ 只打 aweme id 与次数，无异常消息 |
| 二 | 桥接停更终结 | ✅ `d0d1e5a`(08-06 13:14) → `c27f20e`(08-08 17:20) |
| 二 | manifest 升级 | ✅ `schema_version: 2`，健康字段齐全 |
| 二 | 全采全不留痕 | ✅ 本轮无新增抖音留痕记录 |
| 三 | 云端读到健康字段 | ✅ `collection_manifest_available: true`、`collection_generated_at` 与 NUC 采集时间戳一致 |
| 三 | 看板真的显示 | ✅ 浏览器实测：抖音行「正常」；注入 `partial=true` 后变「**部分完成**」(`warn`) |
| 三 | 既有字段未丢 | ✅ `raw_item_count` / `window_item_count` 仍在 |

**修复前后对比**（同一台 NUC，同一条计划任务路径）：

```
修复前：08-05 起连续 10 轮 state=failed，桥接停更 2 天，本机 JSONL 却一直是好的
修复后：state=succeeded，52 条全数发布，桥接 HEAD 前进，看板出现 8/7 的新视频
```

**重试机制在验收当轮就救了一次**：`DetailRetry` 触发 2 次说明真有 2 条详情请求失败过，
改动前这 2 条会直接丢失，对应的号变成 `written < listed`，整轮 52 条照旧作废。

### 如实记录的三个验收局限

1. **「被风控」的现场证据没拿到**。验收当轮 `Argus 次数 = 0`，抖音没触发风控。
   因此「一个号被风控 → 其余号照采 → 看板标黄」这条完整链路**没有真实现场证据**，
   由 26 条自动化测试 + 浏览器注入模拟覆盖。注入模拟只证明**渲染链路**通，
   不等于真实风控下端到端可用。
2. **P8 验收抓出两个「测试全绿但产品不能用」的缺陷**（QA-01 改错分支、QA-02 主管线丢字段），
   两次同源：验证的是代码路径，不是产品路径。QA-02 还推翻了冻结计划的一条非目标，
   已按规范暂停并取得用户授权后才改。
3. **一次偶发测试失败**：某轮全量回归里 `test_local_server.py::...test_preview_route_uses_strict_json_gate_and_small_body`
   失败一次；单条重跑通过、该文件单跑 172 passed、本轮 diff 完全不含该模块，判定为偶发（该测试起 HTTP 服务、对负载敏感）。

（以下为修复前的调查记录，保留备查）

原状态：**取证完成，根因已定位（未改代码，修法待拍板）**
分支：`claude/inspiring-carson-299158`（worktree）｜基线：`master` @ c4e6ec6
来源：`docs/bugs/BUG-01-采集后浏览器窗口不关闭.md` 第「遗留的独立问题」节拆出

> 一句话：抖音对「视频详情」接口偶发风控，一轮里拦掉 1~5 条；我们的验收口径是
> 「一条不少才算数」，于是**已经采到手的 47~51 条被连坐丢弃**，桥接仓库整整两天没更新。

## 0. 现场环境（2026-08-08 经 SSH 实测确认）

| 项 | 实际值 | 出处 |
|---|---|---|
| NUC 主机 / 账户 | `DESKTOP-H9RAKEH` / `beelink-pc` | `ssh omnia-nuc "hostname & whoami"` |
| NUC 项目根 | `C:\AI-news-reader\ai-news-radar-run`（开发机是 `E:\`） | 计划任务 Actions |
| MediaCrawler 根 | `C:\AI-news-reader\MediaCrawler-local-test` | 同上 |
| 桥接仓库 | `C:\AI-news-reader\douyin-bridge` | 同上 |
| 采集入口 | 计划任务 `DouyinCollectAndPush`（每日 08:10 / 13:10 / 20:10） | `schtasks` |
| 每轮参数 | `-MaxNotes 10`、6 个创作者、`--offscreen` | `collect-douyin-and-push.ps1:27` + 计划任务 |
| 正常一轮写入量 | **52 行**（6 个创作者，部分号不足 10 条） | 日志逐轮统计，见第 1.2 项 |

## 1. 复现步骤

### 1.1 步骤

1. NUC 上按现状运行一轮抖音采集（`schtasks /run /tn "DouyinCollectAndPush"`，
   或等计划任务自动触发）。
2. 只要本轮里**任意一条**视频的详情接口被抖音风控拦下（日志出现
   `[DouYinCrawler.get_aweme_detail] Get aweme detail error: ... Blocked by ArgusSecurityPlugin Validate Error`），
3. runner 就会在收尾时抛 `partial_creator_failure: creator receipt is incomplete`，退出码 1；
4. 外层 PowerShell 判定 `state=failed`、`bridge_changed=false`，桥接仓库不提交、不推送。

这不需要人为构造——**2026-08-05 起 10 轮里有 10 轮命中**，见下表。

### 1.2 逐轮统计（`C:\AI-news-reader\douyin-collect.log`，共 19871 行）

按「PowerShell 脚本开始」切段，统计每段的 store 写入行数与风控错误次数：

```
08-04 20:10  store=52  正常
08-05 08:10  store=51  argus=1  partial=1   ← 首次出现，少 1 条
08-05 13:10  store=42  argus=1  （类型 B，见 4.2）
08-05 20:10  store=52  正常
08-06 08:10  store=52  正常
08-06 13:10  store=52  正常        ← 桥接最后一次成功更新
08-06 20:10  store=47  argus=5  partial=1
08-07 08:10  store=50  argus=2  partial=1
08-07 13:10  store=39  argus=2  （类型 B）
08-07 20:10  store=48  argus=4  partial=1
08-08 01:52  store=47  argus=5  partial=1   ← BUG-01 取证时手动触发
08-08 02:05  store=47  argus=5  partial=1   ← 同上
08-08 12:17  store=51  argus=1  partial=1
08-08 12:34  store=10  argus=1  （类型 B，最严重：6 个号只跑完 1 个）
```

`store` = 日志里 `[store.douyin.update_douyin_aweme] douyin aweme id:` 的出现次数，
即真正落盘的行数；正常值恒为 52。**少几条，就恰好对应几次 Argus 风控。**

### 1.3 最后一轮的完整回执（`C:\AI-news-reader\douyin-collect-status.json`）

```
run_id=a08041921ff14d6bbc7a6c1197ef067a state=failed stage=runner exit=1
requested=6 completed=1 failed=5   crawl_output_rows=10  output_rows=155

MS4wLjABAAAAOzTvIhQX  completed  profile=T api=T  listed=10 written=10
MS4wLjABAAAACsVvwoWh  failed     profile=T api=F  listed=0  written=0
                      err=Expecting value: line 1 column 1 (char 0), Blocked by ArgusSecurityPlugin Validate Error
MS4wLjABAAAAjg-p3MxH  failed     profile=F api=F  listed=0  written=0  err=creator receipt is incomplete
MS4wLjABAAAAbsEkiVbK  failed     profile=F api=F  listed=0  written=0  err=creator receipt is incomplete
MS4wLjABAAAADkIjUrje  failed     profile=F api=F  listed=0  written=0  err=creator receipt is incomplete
MS4wLjABAAAABQ86JBTz  failed     profile=F api=F  listed=0  written=0  err=creator receipt is incomplete
```

注意后 4 个号 `profile=False`——它们**根本没被访问过**。第 2 个号的列表接口被风控，
异常一路冒泡终止了整个爬虫，后面的号全体陪葬。这是类型 B，与用户报告的
「listed=10 / written=9」（类型 A）是同一个风控源头的两种表现。

## 2. 现象对比

| | 现在 | 应该 |
|---|---|---|
| 一条详情被风控 | 整轮 `state=failed`，47~51 条已采数据全部不发布 | 已完整采到的部分照常发布，缺的下轮补 |
| 一个号的列表被风控 | 后面所有号一条不采 | 该号记失败，**其余号继续采** |
| 桥接仓库 | 最后更新停在 `d0d1e5a` **2026-08-06 13:14**，已停更约 2 天 | 每轮有新内容就更新 |
| 本机 JSONL | **一直是好的**（08-07 315 KB、08-08 352 KB 照常追加） | 同左 |

最后一行是本卡最关键的对比：**数据其实采到了，只是被验收口径挡在门外没发出去。**

## 3. 影响范围

- **受影响对象**：公网页面上的抖音内容。桥接仓库 = 云端 Actions 的唯一数据入口，
  它不更新 → 网页上的抖音条目就停在 08-06。
- **数据是否会错**：不会。本机 JSONL 完整无损，`data/archive.json` 一条没动
  （本卡涉及的代码路径不触碰归档，不涉及任何清理逻辑）。**这是「少发」不是「发错」。**
- **能否自愈**：**能，且已被实测证实**。每轮都是重新拉取每个号最近 10 条，
  08-08 当天的 JSONL 里 6 个号中 5 个的 `uniq_aweme_id` 都是满额 10——
  某轮被风控漏掉的那条，下一轮就补回来了。所以放宽口径**不会**留下永久空洞。
- **热修还是排队**：排队。无数据损坏风险，但停更每多一天，公网页面就多缺一天抖音内容。

## 4. 根因

### 4.1 底层事实（第一性）

> 抖音的**视频详情接口**（`get_video_by_id`，MediaCrawler 内部叫 `get_aweme_detail`）
> 带有 `ArgusSecurityPlugin` 风控，会偶发地返回一段非 JSON 的拦截页。
> 这是抖音服务端的行为，**我们改不了，也不该假设它不会发生**。
> 发生概率实测约每轮 52 条中 0~5 条（0~10%），2026-08-05 起明显变频繁。

### 4.2 从底层事实到「整轮作废」的两条链路

**类型 A — 详情被拦（占多数，7/10 轮）**

MediaCrawler 的采集流程是「先列表、再逐条要详情、拿到详情才落盘」：

```
core.py:291  get_all_user_aweme_posts(...)      → 列表返回 10 条  → 我们的 listed_count += 10
core.py:301  get_aweme_detail(aweme_id) x10     → 其中 1 条被 Argus 拦
core.py:227-229   except DataFetchError: 记一条 ERROR，return None   ← MediaCrawler 自己吞掉
core.py:305  if aweme_item is not None:  ← None 被跳过，不落盘      → 我们的 written_rows 只 += 9
```

于是 `listed_count=10, written_rows=9`。接着：

- `DouyinRunObserver.finalize()`（`scripts/run_mediacrawler_douyin.py:902`）
  要求 `written_rows == listed_count` 才算 `completed`，否则判 `failed`；
- `main()`（同文件 `:1157`）只要 `failed_creator_count` 非 0 就
  `raise RuntimeError("partial_creator_failure: ...")`；
- 外层 `collect-douyin-and-push.ps1:377` 见 `runnerExit != 0` 直接 `throw`，
  桥接不提交（其自身第 384-397 行的 receipt 复核因此永远走不到）。

**类型 B — 列表 / 主页被拦（3/10 轮，后果更重）**

我们在 `install_douyin_observer()`（`:962-970`）里包装了 `get_user_info` 与
`get_user_aweme_posts`，失败时记录后 **`raise` 原样抛出**。而 MediaCrawler 的
`get_creators_and_videos()`（`core.py:277-291`）在创作者循环里**只对 URL 解析做了
try/except，对这两个网络调用没有任何保护**。异常一路冒泡终止整个爬虫进程——
排在后面的创作者一条都不采。08-08 12:34 那轮 6 个号只完成 1 个，就是这么来的。

### 4.3 判定：是「真丢了 1 条」还是「口径过严」？——两者都有，但要分开看

用户提的这个问题必须拆成两问，答案相反：

| 问题 | 答案 | 依据 |
|---|---|---|
| 少写的那 1 条，本身是不是真的没抓到？ | **是真没抓到**，不是数错了 | detail 返回 None → 从未进 store；日志与 store 计数逐条对得上 |
| 那么整轮判 failed 合理吗？ | **不合理，这是口径的放大效应** | 为了 1 条缺失，丢弃同轮另外 51 条**已完整校验通过**的数据 |

所以本卡的根因不是「校验算错了」，而是：

> **把一个「可自愈、局部、外部不可控」的偶发缺失，当成了「全局致命错误」处理，
> 且缺失一条的代价被放大成整轮 52 条不发布 + 桥接连续 10 轮停更。**

严格口径本身有其来历（防止把残缺快照当完整快照覆盖桥接），但那个担忧在这里不成立：
桥接复制的 `source_file` 是**当天累积的 JSONL**（`creator_output_delta` 只允许追加、
禁止截断重写，见 `:811`），不是本轮快照——本轮少 1 条，文件里也不会少那条历史。

## 5. 修法候选（**待用户拍板，尚未动任何代码**）

三处缺陷可独立修，建议按 ①②③ 的顺序，①② 是本次要做的：

**① 创作者之间必须互相隔离**（对应类型 B，必修）

在我们自己的包装层里捕获 `get_user_info` / `get_all_user_aweme_posts` 的异常：
记录该创作者失败后**返回空结果而非抛出**，让 MediaCrawler 的循环继续跑完剩下的号。
只改本仓库 `scripts/run_mediacrawler_douyin.py`，不碰 MediaCrawler。
收益：一个号被风控，不再连累另外 5 个。

**② 详情失败先重试，仍失败则不再判整轮死刑**（对应类型 A，必修）

- 2a. 包装 `get_video_by_id`，遇风控退避重试 2 次——多数偶发拦截可直接消除；
- 2b. 重试仍失败的，在回执里如实记为 `missing_rows`，并把发布门槛从
  「一条不少」改为「**每个创作者的完整率达标 + 全局缺失不超过阈值**」，
  同时把缺失明细写进 `logs/bridge-collection-failures.jsonl` 留痕（不静默）。

  阈值取值需要拍板。按实测数据，每轮缺 0~5 条 / 52 条；建议起步值：
  单创作者缺失 ≤ 2 条且全局缺失 ≤ 10%，超阈值仍判 failed。

**③（可选）用列表数据兜底**

列表接口返回的 `aweme_list` 本身就含标题、时间、作者等字段，详情只是补充。
重试仍失败时可直接用列表里那条原始数据落盘，做到 `written == listed`。
数据是真实的，但字段完整度与详情不同，需要单独标记。**本轮不建议做**——
它改变落盘数据的形状，风险高于收益，等 ①② 上线观察后再评估。

## 6. 相关文件（只读调查，尚未修改）

- `scripts/run_mediacrawler_douyin.py`
  - `:872-915` `DouyinRunObserver`：`finalize()` 的 `written == listed` 判定
  - `:944-1000` `install_douyin_observer()`：三个 monkeypatch 包装点
  - `:1157` `raise RuntimeError("partial_creator_failure: ...")`
- `deploy/cloud-pc/collect-douyin-and-push.ps1`
  - `:377` runner 非零退出即 throw
  - `:384-397` 自身的 receipt 复核（当前是死路径）
- `tests/test_mediacrawler_runner.py:378-380` — 现有 receipt 测试落点
- `tests/test_bridge_collection_failure_log.py` — 失败留痕契约测试落点
- NUC 证据：`C:\AI-news-reader\douyin-collect.log`、
  `C:\AI-news-reader\douyin-collect-status.json`、
  `C:\AI-news-reader\ai-news-radar-run\logs\bridge-collection-failures.jsonl`

## 7. 与 BUG-01 的关系

无因果关系。BUG-01（标签页残留）修复前后本失败行为完全一致——
`08-05 08:10` 首次出现时 BUG-01 尚未修复，`08-08 12:17` 修复后仍然出现，
两者只是碰巧在同一台机器上同时被观察到。

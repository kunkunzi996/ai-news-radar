# BUG-01: NUC 上每轮采集结束后残留标签页，累积多了会吃光内存

状态：取证中（根因未定位，禁止改代码）
分支：`fix/close-browser-after-collect`
基线：`master` @ 6fc91bd（2026-08-08 已同步 origin/master）

> 现象修订记录：初版记为「每轮多一个浏览器窗口」，经用户澄清更正为
> **「始终只有一个浏览器，但标签页逐轮累积」**。据此排除两类候选根因，见第 4 项。

## 0. 现场环境（2026-08-08 经 SSH 实测确认）

| 项 | 实际值 | 出处 |
|---|---|---|
| NUC 主机 / 账户 | `DESKTOP-H9RAKEH` / `beelink-pc`（192.168.1.2） | `ssh omnia-nuc "hostname; whoami"` |
| **NUC 上的项目根** | **`C:\AI-news-reader\ai-news-radar-run`**（开发机是 `E:\`，勿混淆） | 计划任务 Actions |
| MediaCrawler 根 | `C:\AI-news-reader\MediaCrawler-local-test` | 同上 |
| 连续运行时长 | 221 小时未重启（自 07/29 20:48） | `Win32_OperatingSystem.LastBootUpTime` |
| 采集入口 | **所有入口都触发同一个计划任务 `DouyinCollectAndPush`**；`douyin-collect-now.cmd` 只是一句 `schtasks /run` | `scripts/windows/douyin-collect-now.cmd` |
| 该任务的浏览器模式 | 带 **`-BrowserOffscreen`** → runner 收到 `--offscreen`，窗口被移到 (-32000,-32000) | 计划任务 Actions + `deploy/cloud-pc/collect-douyin-and-push.ps1:360` |
| 用户观察到窗口的位置 | **任务栏 / Alt+Tab**（屏幕上看不到窗口本体） | 用户确认 |

最后一项与离屏模式的表现自洽：离屏窗口在桌面上不可见，但任务栏图标和 Alt+Tab 仍在。

## 1. 复现步骤

待 NUC 现场取证确认。用户描述的现象路径：

1. 在 NUC（`beelink-pc`）上触发一轮抖音采集（计划任务 `DouyinCollectAndPush`，
   或 `scripts/windows/douyin-collect-now.cmd`——后者等价于前者）。
2. 等采集正常结束。
3. 重复第 1~2 步若干轮。
4. 观察任务栏 / Alt+Tab：采集专用 Chrome 始终只有一个，但标签页逐轮增加，不会自动关闭。

### 已排除的干扰项

- 2026-08-08 01:48 实测「Chrome 进程数 0、9333 未监听」，一度以为程序会自行关闭浏览器。
  **经用户确认是他本人手动关掉的**，不能据此推断程序有收尾逻辑。该观测作废。

**取证方式（NUC 上跑，只读）：** 采集专用 Chrome 开着 CDP 端口 9333，直接问它有几个
标签页，比肉眼数 tab 准确。**关键是采集前后各跑一次，用差值证明「逐轮累积」。**

采集前：

```powershell
$p = (Invoke-RestMethod "http://127.0.0.1:9333/json/list") | Where-Object { $_.type -eq 'page' }; "采集前标签页数: $($p.Count)"; $p | Select-Object title, url | Format-Table -AutoSize
```

跑完一轮采集后，再跑同一条，并补一条内存数据：

```powershell
"Chrome 进程数: $((Get-Process chrome -ErrorAction SilentlyContinue).Count)"; "Chrome 总内存: $([math]::Round((Get-Process chrome -ErrorAction SilentlyContinue | Measure-Object WorkingSet64 -Sum).Sum / 1MB)) MB"
```

取证要回答四个问题：
- 一轮采集让标签页净增几个？
- 新增的 tab 是什么 URL（抖音创作者页？about:blank？）？
- 采集结束后这些 tab 是否长期停留，还是延迟几分钟自己消失？
- 每轮净增多少内存？

### 复现记录（2026-08-08 01:52–02:03，经 SSH 实测，用户授权触发）

触发方式：`schtasks /run /tn "DouyinCollectAndPush"`（与日常定时采集同一条路径，带 `--offscreen`）。
每 20 秒采样一次，覆盖采集中与采集结束后各约 5 分钟。

```
01:52:33 | BEFORE  | task=Ready   | chrome_proc= 0 | mem=   0MB | tabs=-1
01:52:54 | T+20s   | task=Running | chrome_proc= 9 | mem= 534MB | tabs= 1
01:53:36 | T+60s   | task=Running | chrome_proc=12 | mem=2118MB | tabs= 2   ← 峰值
01:57:26 | T+280s  | task=Running | chrome_proc=11 | mem= 907MB | tabs= 2
01:57:47 | T+300s  | task=Ready   | chrome_proc=11 | mem= 854MB | tabs= 2   ← 采集结束
02:02:59 | T+600s  | task=Ready   | chrome_proc=11 | mem= 721MB | tabs= 2   ← 结束 5 分钟后
```

最终标签页清单（`/json/list`）：

```
[1] https://www.douyin.com/jingxuan
[2] https://www.douyin.com/jingxuan
```

**三条已证实的事实：**

1. **采集结束后无任何收尾**：任务回到 `Ready` 后 5 分钟，仍是 11 个 chrome 进程、
   **721 MB 常驻**、2 个标签页，数字不再下降。与代码走查（第 4 项）完全吻合。
2. **一轮采集净增 1 个标签页**：浏览器启动时按 `start_url` 开 1 个，
   采集过程中新增 1 个，两个 URL 相同，结束后都不关。
3. 峰值内存约 2.1 GB，稳态约 0.72 GB。

### 第二轮（02:05–02:15，浏览器已在运行，走 `is_port_open` 复用分支）

```
02:05:27 | BEFORE  | task=Ready   | chrome_proc=11 | mem= 593MB | tabs=2   ← 第一轮遗留
02:05:49 | T+20s   | task=Running | chrome_proc=12 | mem=1878MB | tabs=3   ← 立刻 +1
02:10:21 | T+280s  | task=Ready   | chrome_proc=12 | mem=1084MB | tabs=3   ← 采集结束
02:14:30 | T+520s  | task=Ready   | chrome_proc=12 | mem= 756MB | tabs=3   ← 结束 4 分钟后
```

最终标签页清单：3 个，URL 全部为 `https://www.douyin.com/jingxuan`。

**跨轮累积性已证实：每轮采集净增 1 个标签页，采集结束后一个都不关。**
浏览器进程常驻不退出，稳态内存 0.6~0.8 GB 且随标签页数增长。

→ **BUG-01 稳定复现，可进入 PLAN 阶段。**

> 备注：上述两轮为取证而手动触发，因此 NUC 当前遗留 3 个标签页、约 756 MB 常驻。
> 修复上线后应一并清理。

## 2. 现象对比

现在：一轮采集结束后，采集专用 Chrome 里新开的标签页不关闭；跑 N 轮就累积 N 批标签页。
应该：一轮采集结束后不残留本轮新开的标签页；重复采集不会让标签页数量随轮次单调增长。

（「应该」这一栏还有一个待拍板的边界，见第 3 项。）

## 3. 影响范围

- 受影响对象：NUC 本机（`beelink-pc`）的内存。**Chrome 内存按标签页算，不按窗口算**
  ——每个 tab 是独立渲染进程。抖音页面含视频播放器和大量 JS，单 tab 占用可达数百 MB，
  累积后可拖慢乃至拖死机器，进而影响后续所有采集轮次。
- 数据是否会错：**否**。标签页残留不写 `data/archive.json`，不影响已采内容。
- 热修还是排队：排队。无数据损坏风险，走正常流程。
- **待用户拍板的争议点**：这个 Chrome 用专用 profile
  （`--user-data-dir=<CrawlerRoot>/chrome-profile`）保存着抖音登录态，CDP 端口 9333。
  三种收尾口径后果不同：
  - A. **只关本轮新增的标签页**，保留浏览器进程和至少一个页面 →
    登录态最安全，代码里 `ensure_dedicated_browser()` 的复用逻辑照常工作，下轮免重启。
    但浏览器主进程常驻，不释放全部内存。
  - B. **采集结束就结束整个专用 Chrome 进程** → 内存全释放，但下轮要重新拉起；
    且 `douyin_login_state()`（:379）依赖 `context.pages` 与 cookie，
    进程被强杀时 profile 可能来不及落盘，有 `login_required` 风险。
  - C. **超过阈值才清理**（如 tab 数 > 5） → 折中，但引入新参数和新的边界情况。

  倾向 A（保留浏览器、只清标签页），因为它和现有复用逻辑同向、不碰登录态；
  但取证结果出来前不锁定。

## 4. 根因

**已定位（2026-08-08 两轮实测 + 代码走查双向印证）**：

> 采集链路**自始至终没有浏览器收尾环节**。专用 Chrome 一旦启动就永久常驻，
> 每轮采集在其中新开一个标签页且从不关闭，于是标签页数随采集轮次单调增长，
> 内存随之累积。

三类候选的最终判定：

| 候选 | 判定 |
|---|---|
| ① 每轮重开新浏览器，旧的残留 | **排除** —— 全程只有一个浏览器，`ensure_dedicated_browser()` 复用逻辑工作正常 |
| ② 浏览器复用成功，但新开的标签页没关，逐轮累积 | **✅ 确认** —— 两轮实测 tabs 1→2→3，且结束后不回落 |
| ③ 残留的不是这个采集浏览器（微信 sidecar 等） | **排除** —— `/json/list` 显示全部挂在 9333 这个采集浏览器上 |

支撑候选 ② 的已确认事实（读代码得到，非推测）：

- `ensure_dedicated_browser()`（`scripts/run_mediacrawler_douyin.py:499`）：端口 9333
  已监听就复用现有浏览器，只有端口没开时才 `launch_dedicated_browser()`（:506）。
  **这段逻辑与「只有一个浏览器」的现象一致，本身没有缺陷。**
- 本仓库自己的两处 CDP 代码**只读取已有页面，不新建标签页**：
  - `set_dedicated_browser_window_mode()`（:345）读 `context.pages[0]` 调窗口位置；
  - `douyin_login_state()`（:379）遍历 `context.pages` 查登录态。
  两处末尾的 `await browser.close()`（:372、:403）在 `connect_over_cdp` 模式下
  **只断开 playwright 连接**，既不关浏览器也不关标签页——所以它们不是泄漏源，
  也不构成现成的清理点。
- `main()`（:1003-1099）全程没有任何标签页或浏览器的收尾动作。
- **外层的 PowerShell 采集脚本同样没有。** `deploy/cloud-pc/collect-douyin-and-push.ps1`
  全文涉及浏览器的只有两处：`:33` 声明 `-BrowserOffscreen` 开关、`:360` 据此追加
  `--offscreen` 参数。**没有任何 `Stop-Process` / `taskkill` / 关标签页的代码。**
  也就是说从计划任务到 Python runner，整条链路都没有浏览器收尾环节。
- 采集主体是外部项目 MediaCrawler（`<CrawlerRoot>/main.py`，由 `run_mediacrawler()` :911
  以子进程启动），它通过 CDP 连上这个浏览器开页面采集。**新增标签页最可能由它产生，
  而它是外部代码，不在本仓库白名单内——所以清理动作只能由我们这边在采集结束后补做。**

待取证证实/证伪的点：新增 tab 确实由 MediaCrawler 产生且确实不自行关闭。

## 5. 相关文件（只读调查，尚未修改）

- `scripts/run_mediacrawler_douyin.py` — 专用 Chrome 的启动、复用、登录态检查、主流程
- `scripts/radar/server/cdp.py` — 已有 `cdp_json(port, path)`（:36），可直接调
  `/json/list` 列标签页、`/json/close/<id>` 关标签页，无需新引依赖
- `scripts/windows/douyin-collect-now.cmd` — NUC 手动采集入口
- `tests/test_mediacrawler_runner.py` — 现有测试落点

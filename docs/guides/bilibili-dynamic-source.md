# B站动态抓取技术实现说明

Date: 2026-06-30
Scope: AI News Radar 中 `bilibili_dynamic` 信源的抓取、cookie 登录态、翻页、状态输出和本地验收方式。

## 一句话结论

当前实现是“双通道”：

1. 没有 cookie 时，走 B站公开 opus 动态接口，只能拿到较浅的一批动态，发布时间不够可靠。
2. 有 cookie 时，优先走登录态完整动态接口，通过 WBI 签名和 `offset` 翻页，可以拿到更完整、更早的账号动态。

如果登录态接口失败，程序不会直接整次失败，而是回退到公开接口，并在 `data/source-status.json` 里写清楚 `fetch_mode` 和 `fallback_reason`。

## 当前默认抓取对象

默认账号配置在 `scripts/update_news.py` 中：

```text
BILIBILI_DYNAMIC_UIDS=505301413,316183842
BILIBILI_DYNAMIC_SOURCE_NAMES=Koji杨远骋at十字路口,技术爬爬虾
```

也就是说，默认抓两个 B站账号的空间动态：

| UID | 来源名 |
| --- | --- |
| `505301413` | `Koji杨远骋at十字路口` |
| `316183842` | `技术爬爬虾` |

后续如果要换账号或加账号，不需要改代码，改环境变量即可。

## 相关文件

| 文件 | 作用 |
| --- | --- |
| `scripts/update_news.py` | B站抓取主实现，包括 cookie 解析、WBI 签名、公开接口、登录态接口、翻页、数据映射、状态输出 |
| `.github/workflows/update-news.yml` | GitHub Actions 定时跑数时注入 B站环境变量和 `BILIBILI_COOKIE` Secret |
| `README.md` | 面向使用者的简短配置说明 |
| `tests/test_private_bridge_sources.py` | B站相关单元测试，包括 cookie 格式、WBI 签名、完整动态解析、翻页 |
| `data/source-status.json` | 每次运行后的信源状态，能看 B站是否成功、用了哪种模式、抓到几条 |
| `bilibili-account-preview.html` | 当前本地调试用的账号预览页，不属于主抓取链路的核心代码 |

## 环境变量

### 开关与账号

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `BILIBILI_DYNAMIC_ENABLED` | 项目默认开启 | 是否启用 B站动态源；设置为 `0` 可关闭 |
| `BILIBILI_DYNAMIC_UIDS` | `505301413,316183842` | 要抓取的 B站账号 UID 列表，用逗号、分号或换行分隔 |
| `BILIBILI_DYNAMIC_SOURCE_NAMES` | `Koji杨远骋at十字路口,技术爬爬虾` | 和 UID 一一对应的来源名列表 |
| `BILIBILI_DYNAMIC_UID` | 无 | 旧版单账号兼容配置；设置后只抓这一个账号 |
| `BILIBILI_DYNAMIC_SOURCE_NAME` | 无 | 旧版单账号来源名 |

### 数量与翻页

| 环境变量 | 默认值 | 代码上限 | 说明 |
| --- | --- | --- | --- |
| `BILIBILI_DYNAMIC_MAX_ITEMS` | `5` | `200` | 每个账号最多保留多少条 B站动态 |
| `BILIBILI_DYNAMIC_MAX_PAGES` | `5` | `20` | 登录态完整动态接口最多往前翻几页 |

这两个值只影响 B站源本身。多账号模式下，`BILIBILI_DYNAMIC_MAX_ITEMS` 是“每个账号”的最大条数，不是所有账号合计。前端主页面仍然会受 `--window-hours`、归并、去重、排序和筛选影响，所以“抓到了很多”和“首页展示很多”不是同一件事。

### Cookie

| 环境变量 | 适用场景 | 说明 |
| --- | --- | --- |
| `BILIBILI_COOKIE` | 本地或 GitHub Actions | 直接放 cookie 文本，适合放进 GitHub Secret |
| `BILIBILI_DYNAMIC_COOKIE` | 本地或 GitHub Actions | `BILIBILI_COOKIE` 的兼容别名 |
| `BILIBILI_COOKIE_FILE` | 本地 | 指向本地 cookie 文件，例如浏览器插件导出的 `cookies.txt` |
| `BILIBILI_DYNAMIC_COOKIE_FILE` | 本地 | `BILIBILI_COOKIE_FILE` 的兼容别名 |

推荐做法：

- 本地调试：用 `BILIBILI_COOKIE_FILE` 指向本机文件。
- GitHub Actions：用 `BILIBILI_COOKIE` Secret。
- 不要把 cookie 文件提交到 Git。
- 不要把真实 cookie 写进 Markdown、README、日志或截图。

### 接口地址覆盖

一般不用动。只有 B站接口路径变化、临时排查或做测试替身时才需要：

| 环境变量 | 默认接口 |
| --- | --- |
| `BILIBILI_DYNAMIC_API_URL` | `https://api.bilibili.com/x/polymer/web-dynamic/v1/opus/feed/space` |
| `BILIBILI_DYNAMIC_FULL_API_URL` | `https://api.bilibili.com/x/polymer/web-dynamic/v1/feed/space` |

## Cookie 支持的格式

代码入口是 `bilibili_cookie_header_from_env()`，它会先读环境变量，再读文件。

真正解析文本的是 `bilibili_cookie_header_from_file_text()`，目前支持三种常见格式。

### 1. 普通 Cookie 请求头

形如：

```text
SESSDATA=[REDACTED]; bili_jct=[REDACTED]; DedeUserID=[REDACTED]
```

如果文本里有 `=`，但不是 JSON 或 Netscape 格式，代码会把它当普通 cookie header 使用。

### 2. Netscape cookies.txt

很多浏览器插件会导出这种格式，例如：

```text
# Netscape HTTP Cookie File
.bilibili.com	TRUE	/	TRUE	1782817200	SESSDATA	[REDACTED]
#HttpOnly_.bilibili.com	TRUE	/	TRUE	1782817200	bili_jct	[REDACTED]
```

实现细节：

- 以 tab 分隔字段。
- 支持 `#HttpOnly_` 前缀。
- 只保留 domain 包含 `bilibili.com` 的 cookie。
- 自动跳过已经过期的 cookie。
- 如果过期时间是毫秒，会自动转成秒。

### 3. Cookie-Editor JSON 导出

形如：

```json
[
  {
    "domain": ".bilibili.com",
    "name": "SESSDATA",
    "value": "[REDACTED]",
    "expirationDate": 1782817200
  }
]
```

实现细节：

- 支持数组格式。
- 也支持 `{ "cookies": [...] }` 这种外层对象格式。
- 识别 `expirationDate`、`expires`、`expiry` 这几类过期字段。

## 哪些 cookie 字段比较关键

程序不会硬编码检查每个字段，但登录态完整动态通常至少依赖这些 B站登录 cookie：

```text
SESSDATA
bili_jct
DedeUserID
DedeUserID__ckMd5
buvid3
buvid4
```

简单理解：

- `SESSDATA` 代表登录会话，是最核心的凭证。
- `bili_jct` 常用于 B站请求校验。
- `DedeUserID` / `DedeUserID__ckMd5` 表示登录用户身份。
- `buvid3` / `buvid4` 是设备和风控相关标识。

如果 cookie 文件里缺 `SESSDATA`，大概率只能走公开接口，或者登录态接口失败后回退。

## 抓取主流程

入口在 `maybe_fetch_bilibili_dynamic(session, now)`。

整体流程如下：

```text
读取 B站基础配置
  |
  v
检查 BILIBILI_DYNAMIC_ENABLED
  |
  v
读取 UID 列表、来源名列表、max_items、max_pages
  |
  v
读取 cookie
  |
  +-- 有 cookie --> 注入 requests.Session
  |                  对每个 UID 循环：
  |                    获取 WBI keys
  |                    对完整动态接口参数做 WBI 签名
  |                    调登录态完整动态接口
  |                    按 offset 翻页
  |                    成功则该账号 fetch_mode=cookie_full_dynamic
  |
  +-- 无 cookie 或某个账号登录态失败 --> 对该账号调公开 opus 接口
                                      成功则 fetch_mode=public_opus 或 public_opus_fallback
  |
  v
转成 RawItem
  |
  v
写入 raw_items，进入项目后续归并、打分、前端数据生成流程
  |
  v
写 source-status.json 状态
```

## 公开 opus 接口

函数：`fetch_bilibili_dynamic()`

接口：

```text
https://api.bilibili.com/x/polymer/web-dynamic/v1/opus/feed/space
```

请求参数：

```text
host_mid=<B站 UID>
page=1
type=all
web_location=333.1387
```

请求头会模拟浏览器：

```text
User-Agent: 浏览器 UA
Accept: application/json, text/plain, */*
Accept-Language: zh-CN,zh;q=0.9,en;q=0.8
Origin: https://space.bilibili.com
Referer: https://space.bilibili.com/<UID>/dynamic
```

特点：

- 不需要 cookie。
- 适合作为默认公共能力。
- 拿到的数据较浅。
- `published_at` 不可靠，所以代码把 `published_at` 设为 `None`，让归档里的 `first_seen_at` 表示第一次看见它的时间。
- 状态里的 `fetch_mode` 是 `public_opus`。

## 登录态完整动态接口

函数：`fetch_bilibili_full_dynamic()`

接口：

```text
https://api.bilibili.com/x/polymer/web-dynamic/v1/feed/space
```

请求参数主体：

```text
host_mid=<B站 UID>
timezone_offset=-480
features=itemOpusStyle,listOnlyfans,opusBigCover,onlyfansVote,decorationCard,forwardListHidden,ugcDelete
web_location=333.1387
offset=<上一页返回的 offset，可选>
wts=<当前时间戳>
w_rid=<WBI 签名>
```

特点：

- 需要 cookie。
- 需要 WBI 签名。
- 返回的 `modules.module_author.pub_ts` 可以作为可靠发布时间。
- 返回 `data.has_more` 和 `data.offset`，所以可以往前翻页。
- 状态里的 `fetch_mode` 是 `cookie_full_dynamic`。

## WBI 签名是什么

B站部分 Web API 不只看 cookie，还要求请求参数里带两个字段：

```text
wts
w_rid
```

本项目通过这几个函数完成签名：

| 函数 | 作用 |
| --- | --- |
| `bilibili_wbi_keys()` | 访问 nav 接口，拿 `img_key` 和 `sub_key` |
| `bilibili_mixin_key()` | 用 B站固定混淆表把 `img_key + sub_key` 混成 32 位 key |
| `sign_bilibili_wbi_params()` | 给参数加 `wts`，清洗特殊字符，排序 urlencode，再 md5 得到 `w_rid` |

获取 key 的接口：

```text
https://api.bilibili.com/x/web-interface/nav
```

重要细节：

- 之前卡住的地方是 nav 请求容易被 B站返回 `412`。
- 修复方式是在 `bilibili_wbi_keys()` 里加浏览器请求头，尤其是 `User-Agent`、`Accept-Language`、`Referer`。
- 这样 nav 可以正常返回 `wbi_img.img_url` 和 `wbi_img.sub_url`，再从 URL 文件名里提取 key。

签名过程用大白话说就是：

1. 先问 B站拿两段临时 key。
2. 按 B站固定顺序把两段 key 打乱重组。
3. 把真实请求参数排序。
4. 拼上时间戳 `wts`。
5. 算出 md5，作为 `w_rid`。
6. 带着 `wts` 和 `w_rid` 去请求完整动态接口。

## 翻页机制

登录态完整动态接口返回：

```json
{
  "data": {
    "items": [],
    "has_more": true,
    "offset": "1198976215620255800"
  }
}
```

代码处理方式：

1. 第一页不传 `offset`。
2. 如果 `has_more=true` 且返回了新的 `offset`，下一页带上这个 `offset`。
3. 每页解析出动态后加入结果。
4. 如果已经达到 `BILIBILI_DYNAMIC_MAX_ITEMS`，停止。
5. 如果达到 `BILIBILI_DYNAMIC_MAX_PAGES`，停止。
6. 如果没有 `has_more`、没有新 `offset`、或者新旧 `offset` 一样，停止，避免死循环。
7. 每页之间睡眠 `0.25` 秒，降低连续请求压力。

本地验证时，当前 cookie 已经能翻到更早日期：

```text
第 1 页：最早约 2026-05-05 / 2026-05-06
第 2 页：最早约 2026-03-09
第 3 页：最早约 2025-12-28
第 4 页：最早约 2025-10-29
第 5 页：最早约 2025-07-14
```

这个结果说明：只要 cookie 有效、B站接口不变，继续调大页数和条数就可以继续往前抓，但不要无限加，避免触发风控。

## 数据如何转成项目里的新闻项

项目内部统一用 `RawItem` 表示一条原始信源内容。B站动态会被转成类似结构：

```text
site_id=bilibili_dynamic
site_name=Bilibili Dynamic
source=<对应 UID 的来源名>
title=<动态正文前 90 个字符>
url=<动态链接>
published_at=<B站 pub_ts 或抓取时间>
meta.summary=<完整动态正文>
meta.bilibili_uid=<UID>
meta.bilibili_dynamic_id=<动态 ID>
meta.bilibili_dynamic_type=<动态类型>
meta.timestamp_source=bilibili_pub_ts / fetch_time / first_seen_at
```

### 标题生成

函数：`bilibili_dynamic_item_title()`

规则：

- 去掉多余空白。
- 如果正文为空，标题兜底为 `B站动态 <id>`。
- 如果正文超过 90 字，只保留前 87 字，再加 `...`。

这样做是为了避免一条长动态把首页卡片撑爆。

### 发布时间

登录态完整动态：

- 优先读取 `modules.module_author.pub_ts`。
- `meta.timestamp_source` 写 `bilibili_pub_ts`。

公开 opus 动态：

- 接口不稳定提供真实发布时间。
- `published_at` 设为 `None`。
- 后续归档用 `first_seen_at` 表示第一次被系统看到。

## 去重方式

解析阶段和翻页阶段都有去重：

- 优先用 B站动态 ID，例如 `bilibili_dynamic_id`。
- 如果没有 ID，就用规范化后的 URL。

这样可以避免：

- 同一页里重复。
- 翻页边界重复。
- 某些转发或接口返回异常导致同一条进入多次。

项目后续还有全局层面的 URL 归并和故事合并，所以 B站源自身去重只是第一道保险。

## 状态输出

每次运行后，B站状态会进入 `data/source-status.json`。

关键字段：

| 字段 | 含义 |
| --- | --- |
| `site_id` | 固定为 `bilibili_dynamic` |
| `ok` | B站源本次是否成功 |
| `item_count` | 本次抓到几条 |
| `uid` | 抓取的 B站 UID，多个账号时用逗号连接 |
| `uids` | 多账号 UID 列表 |
| `uid_count` | 本次账号数量 |
| `source_name` | 来源显示名 |
| `cookie_present` | 程序是否读到了 cookie |
| `fetch_mode` | 实际使用的抓取模式 |
| `fallback_reason` | 如果从登录态回退到公开接口，这里写失败原因 |
| `max_items` | 本次配置的最大条数 |
| `max_items_per_account` | 每个账号最大条数 |
| `max_pages` | 本次配置的最大页数 |
| `accounts` | 每个账号自己的 `uid`、`source_name`、`ok`、`item_count`、`fetch_mode` |
| `privacy` | 固定提示 cookie 只来自环境变量或本地文件，不写入日志 |
| `coverage_note` | 当前策略说明 |

常见 `fetch_mode`：

```text
cookie_full_dynamic    有 cookie，完整动态接口成功
public_opus            没有 cookie，公开接口成功
public_opus_fallback   有 cookie，但登录态接口失败，回退公开接口成功
mixed                  多账号模式下，不同账号用了不同 fetch_mode
```

如果你看到：

```text
cookie_present=true
fetch_mode=cookie_full_dynamic
ok=true
uid_count=2
```

说明 B站 cookie 登录态链路是真的跑通了。

## 为什么网页上看起来还是少

这个问题容易误会。原因通常不是“没抓到”，而是展示层有过滤。

主页面 `http://localhost:8080/` 默认看的是项目生成后的新闻视图，会受这些因素影响：

- `--window-hours`，例如只看最近 24 小时。
- AI 打分、去重、故事聚合。
- 搜索词或分类筛选。
- 前端默认只展开一部分列表。

所以如果想看“这些 B站账号目前能抓到的全部动态”，应该看 B站账号预览页，或者直接检查 `data/source-status.json` 和归档数据，而不是只看首页卡片数。

## 本地运行命令

### 只跑最近 24 小时

```powershell
cd E:\AI-news-reader\ai-news-radar-run
$env:BILIBILI_DYNAMIC_ENABLED='1'
$env:BILIBILI_DYNAMIC_UIDS='505301413,316183842'
$env:BILIBILI_DYNAMIC_SOURCE_NAMES='Koji杨远骋at十字路口,技术爬爬虾'
$env:BILIBILI_COOKIE_FILE='C:\Users\Administrator\Pictures\cookies.txt'
.\.venv\Scripts\python.exe scripts/update_news.py --output-dir data --window-hours 24
```

适合日常更新。

### 往前抓更久

```powershell
cd E:\AI-news-reader\ai-news-radar-run
$env:BILIBILI_DYNAMIC_ENABLED='1'
$env:BILIBILI_COOKIE_FILE='C:\Users\Administrator\Pictures\cookies.txt'
$env:BILIBILI_DYNAMIC_UIDS='505301413,316183842'
$env:BILIBILI_DYNAMIC_SOURCE_NAMES='Koji杨远骋at十字路口,技术爬爬虾'
$env:BILIBILI_DYNAMIC_MAX_ITEMS='80'
$env:BILIBILI_DYNAMIC_MAX_PAGES='8'
.\.venv\Scripts\python.exe scripts/update_news.py --output-dir data --window-hours 1440 --archive-days 120
```

说明：

- `BILIBILI_DYNAMIC_MAX_ITEMS=80` 表示每个 B站账号最多保留 80 条。
- `BILIBILI_DYNAMIC_MAX_PAGES=8` 表示最多翻 8 页。
- `--window-hours 1440` 表示主数据窗口放到 60 天。
- `--archive-days 120` 表示归档保留 120 天。

如果只调大 B站翻页，但 `--window-hours` 仍然是 24，首页仍然可能只显示最近 24 小时相关内容。

### 只看两个 B站账号，取消时间限制

如果要把本地页面临时变成 B站追踪页，可以使用 B站-only 全时间模式：

```powershell
cd E:\AI-news-reader\ai-news-radar-run
$env:BILIBILI_DYNAMIC_ENABLED='1'
$env:BILIBILI_COOKIE_FILE='C:\Users\Administrator\Pictures\cookies.txt'
$env:BILIBILI_DYNAMIC_UIDS='505301413,316183842'
$env:BILIBILI_DYNAMIC_SOURCE_NAMES='Koji杨远骋at十字路口,技术爬爬虾'
$env:BILIBILI_DYNAMIC_MAX_ITEMS='200'
$env:BILIBILI_DYNAMIC_MAX_PAGES='20'
.\.venv\Scripts\python.exe scripts/update_news.py --output-dir data --archive-days 3650 --bilibili-only --all-time
```

这个模式会让前端数据只发布 `bilibili_dynamic`，并把 `time_scope` 写成
`all_time`、`source_scope` 写成 `bilibili_only`。它不会删除其它信源代码；
只是本次生成的页面数据只展示 B站两个账号。

## GitHub Actions 配置

工作流文件：`.github/workflows/update-news.yml`

当前注入：

```yaml
BILIBILI_DYNAMIC_ENABLED: ${{ vars.BILIBILI_DYNAMIC_ENABLED || '1' }}
BILIBILI_DYNAMIC_UIDS: ${{ vars.BILIBILI_DYNAMIC_UIDS || vars.BILIBILI_DYNAMIC_UID || '505301413,316183842' }}
BILIBILI_DYNAMIC_SOURCE_NAMES: ${{ vars.BILIBILI_DYNAMIC_SOURCE_NAMES || vars.BILIBILI_DYNAMIC_SOURCE_NAME || 'Koji杨远骋at十字路口,技术爬爬虾' }}
BILIBILI_DYNAMIC_MAX_ITEMS: ${{ vars.BILIBILI_DYNAMIC_MAX_ITEMS || 5 }}
BILIBILI_DYNAMIC_MAX_PAGES: ${{ vars.BILIBILI_DYNAMIC_MAX_PAGES || 5 }}
BILIBILI_COOKIE: ${{ secrets.BILIBILI_COOKIE }}
```

推荐配置方式：

1. 在 GitHub 仓库 Settings 里添加 Secret：`BILIBILI_COOKIE`。
2. Secret 内容可以是普通 Cookie header，也可以是插件导出的 cookies.txt 全文或 JSON。
3. 非敏感参数用 Variables，例如 `BILIBILI_DYNAMIC_MAX_ITEMS=80`。
4. 多账号用 `BILIBILI_DYNAMIC_UIDS` 和 `BILIBILI_DYNAMIC_SOURCE_NAMES`，单账号旧变量仍然兼容。
5. 不要在 Actions 里用 `BILIBILI_COOKIE_FILE`，除非工作流真的先创建了那个文件。

## 本地验收方式

### 1. 语法检查

```powershell
.\.venv\Scripts\python.exe -m py_compile scripts/update_news.py
```

期望：无输出，退出码为 0。

### 2. 单元测试

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_private_bridge_sources
```

期望：B站相关测试通过，包括：

- 公开动态解析。
- 长标题截断。
- Netscape cookie 解析。
- JSON cookie 解析。
- 完整动态解析。
- WBI 签名。
- nav 请求浏览器头。
- 完整动态 `offset` 翻页。

### 3. 看状态文件

运行更新后检查：

```powershell
Get-Content data\source-status.json
```

重点看 `bilibili_dynamic`：

```json
{
  "ok": true,
  "cookie_present": true,
  "fetch_mode": "cookie_full_dynamic",
  "item_count": 24,
  "uid_count": 2
}
```

如果 `fetch_mode` 是 `public_opus_fallback`，说明 cookie 被读到了，但登录态完整动态接口失败，程序退回公开接口了。多账号时也可以看 `accounts` 数组，逐个账号确认 `item_count`。

### 4. 浏览器检查

本地启动静态服务器后打开：

```text
http://localhost:8080/
```

如果要专门看 B站账号预览，打开当前调试页：

```text
http://localhost:8080/bilibili-account-preview.html
```

注意：这个预览页是当前本地调试页。如果后续要做成正式功能，建议把它纳入前端构建和数据生成流程。

## 常见问题排查

### `cookie_present=false`

说明程序没读到 cookie。

检查：

- `BILIBILI_COOKIE` 是否设置。
- `BILIBILI_COOKIE_FILE` 路径是否正确。
- PowerShell 路径是否用了英文引号。
- 文件是否真的存在。

本地检查：

```powershell
Test-Path 'C:\Users\Administrator\Pictures\cookies.txt'
```

### `fetch_mode=public_opus`

说明没有 cookie，走的是公开接口。

这不是错误，只是抓取深度有限。

### `fetch_mode=public_opus_fallback`

说明：

1. 程序读到了 cookie。
2. 尝试登录态完整动态失败。
3. 公开接口兜底成功。

继续看 `fallback_reason`。

常见原因：

- cookie 过期。
- cookie 缺关键字段。
- B站风控。
- WBI 签名规则变化。
- 接口路径变化。
- 网络请求被拦截。

### `HTTPError 412`

这通常是 B站风控或请求头不像浏览器。

当前代码已经给 nav 和动态接口加了浏览器请求头。如果又出现 412，优先检查：

- cookie 是否来自同一浏览器登录态。
- 是否短时间请求太频繁。
- B站接口是否调整。
- 请求头是否在后续改动中被删掉。

### 首页只有几条

先不要直接判断是抓取失败。按顺序查：

1. `data/source-status.json` 里的 `item_count`。
2. `fetch_mode` 是否为 `cookie_full_dynamic`。
3. 当前运行命令的 `--window-hours`。
4. 前端是否有搜索词、分类、排序过滤。
5. 是否只展开了列表的一部分。

### 能抓到 5 月 6 日，还能不能往前

可以，前提是：

- cookie 仍然有效。
- 登录态完整动态接口继续返回 `has_more=true` 和 `offset`。
- `BILIBILI_DYNAMIC_MAX_ITEMS` 和 `BILIBILI_DYNAMIC_MAX_PAGES` 足够大。

例如：

```powershell
$env:BILIBILI_DYNAMIC_MAX_ITEMS='120'
$env:BILIBILI_DYNAMIC_MAX_PAGES='12'
```

但不要一次调太夸张。建议从 `80/8`、`120/12` 逐步试。

## 安全边界

cookie 等同于账号登录凭证，要按密码处理。

必须避免：

- 提交 cookie 文件。
- 在文档里写真实 cookie。
- 在日志里打印完整 cookie。
- 把 cookie 发到公开 issue、PR 或聊天窗口。

当前实现的安全设计：

- cookie 只从环境变量或本地文件读。
- `source-status.json` 只写 `cookie_present=true/false`，不写 cookie 内容。
- `privacy` 字段固定标明 `cookie_env_only_not_logged`。
- GitHub Actions 使用 Secret 注入。

## 已知风险

1. B站 Web API 不是稳定公开协议，接口路径、参数、WBI 签名规则都可能变化。
2. cookie 会过期，过期后需要重新从浏览器导出。
3. 请求太频繁可能触发风控，所以翻页和定时频率要保守。
4. 公开 opus 接口不提供可靠发布时间，只适合作为兜底。
5. 当前 B站账号预览页还是本地调试产物，尚未整理成正式产品页。
6. GitHub Actions 上的真实效果取决于 Secret 是否配置正确，以及云端 IP 是否被 B站风控。

## 后续建议

优先级从高到低：

1. 把 `bilibili-account-preview.html` 整理成正式页面，接入项目的常规数据生成流程。
2. 在页面上单独显示 B站源状态：`fetch_mode`、`item_count`、`max_pages`、最早/最新动态日期。
3. 给 B站源增加独立的本地诊断命令，只检查 cookie 和动态接口，不触发全量新闻刷新。
4. 增加 cookie 过期提醒，例如检测到 `public_opus_fallback` 时在状态页高亮。
5. 如果以后要继续加账号，可以直接扩展 `BILIBILI_DYNAMIC_UIDS` 和 `BILIBILI_DYNAMIC_SOURCE_NAMES`。

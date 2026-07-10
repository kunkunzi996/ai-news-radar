# 施工说明：接入 we-mp-rss（WeRSS）恢复微信公众号订阅源

> 给 Codex 的任务说明。请严格按本文件执行，不要自由发挥，不要顺手改其它无关代码。
> 项目根目录：`E:\AI-news-reader\ai-news-radar-run`（下文 radar 仓库内路径均相对此目录）
> 当前分支：`master`（继续在此分支改即可，**不要**新建分支、不要 commit / push，除非用户另行授权）
> sidecar 部署目录：`E:\AI-news-reader\we-mp-rss-sidecar\`（radar 仓库之外，新建）

---

## 背景（为什么做这个）

radar 的微信公众号源（猫笔刀）此前走 WeWe RSS sidecar（Node 项目，端口 4000，JSON Feed 输出），因 sidecar 不稳定已在 `sources.config.json` 里停用（条目 `wewe_rss_maobidao`，notes 写明"等 sidecar 稳定后恢复"）。

替代方案选定 [we-mp-rss](https://github.com/rachelos/we-mp-rss)（WeRSS）：MIT 协议、维护活跃（2026-06 仍有提交）、Python + FastAPI、走微信公众平台扫码授权（比 WeWe RSS 的微信读书凭证稳定）、自带定时抓取和 RSS 输出。

**现状**：radar 是 Python 拉取式聚合器，`scripts/update_news.py` 按 `sources.config.json` 驱动各 fetcher；wewe_rss 通道的完整链路是：config_runtime 把源配置转成环境变量 → cli.py 按开关调 fetcher → fetcher 拉 sidecar 的 HTTP 接口 → 产出 RawItem 进管线。本次照这条链路并行复制一条 we_mp_rss 通道，不删旧通道。

**已确认的产品决策**：
1. we_mp_rss 作为**新增类型**与 wewe_rss 并存，迁移期共存，旧通道代码不删、旧配置条目保持停用。
2. 采用**拉模式**（radar 定时拉 sidecar 的 RSS XML），本次不做 Webhook 推送。
3. sidecar 只在本机跑（127.0.0.1），**绝不暴露公网**——已核实其 RSS 端点默认无鉴权（`apis/rss.py` 中 auth 依赖被注释掉）。

---

## 关键技术点（均已核实过源码，不要再猜）

1. **we-mp-rss 的输出端点**（源码 `apis/rss.py`，路由挂在根路径）：
   - `GET {base}/feed/{feed_id}.rss?limit=N` —— 单公众号 RSS 2.0 XML；`feed_id` 传 `all` 返回全部订阅的合集。
   - `GET {base}/rss?limit=N` —— 订阅列表（RSS XML，每个 `<item>` 的 `<link>` 形如 `{domain}rss/{feed_id}`，可用来自动发现 feed id）。
   - `ext=json` 是**自定义 JSON 结构**，不是 JSON Feed 标准，所以解析走 RSS XML + feedparser（radar 的 `requirements.txt` 第 3 行已锁定 `feedparser==6.0.11`）。
2. **sidecar 部署**：本机无 Docker，从源码跑。README 要求 Python>=3.13.1（本机默认 3.11.9，需装 3.13）。默认端口 `8001`（`config.example.yaml` 第 73 行 `port: ${PORT:-8001}`），默认 SQLite（`data/db.db`），启动命令 `python main.py -job True -init True`。
3. **radar 侧接入**：照 `fetch_wewe_rss_subscription`（`scripts/radar/fetchers/subscriptions.py:269`）的结构复制一条通道，涉及 7 个文件的小改动，见下文逐条说明。feed 配置格式复用 `wewe_rss_feeds_from_env`（`name:id` 分号分隔），该函数与 wewe 无耦合，直接复用不复制。

---

## 文件清单

**新建**
- `E:\AI-news-reader\we-mp-rss-sidecar\`（git clone we-mp-rss，radar 仓库外，不进 radar 的 git）
- `E:\AI-news-reader\we-mp-rss-sidecar\start-we-mp-rss.ps1`（启动脚本）
- `tests/test_we_mp_rss_source.py`（radar 仓库内，新 fetcher 的单测）

**修改（radar 仓库内，只动这 7 个）**
1. `scripts/radar/common.py` —— 新增 4 个常量 + 2 处映射表条目
2. `scripts/radar/fetchers/subscriptions.py` —— 新增 base_url helper、XML 解析函数、fetcher 函数
3. `scripts/radar/config_runtime.py` —— sources.config → 环境变量的映射加 we_mp_rss 分支
4. `scripts/radar/cli.py` —— RunContext 字段、开关判断、fetch 调用与状态上报
5. `scripts/update_news.py` —— re-export 新函数
6. `scripts/radar/server/subscriptions_store.py` —— PURGE_TRACKED_SITE_IDS 加一项
7. `scripts/radar/server/common.py` —— runtime id 识别加一个分支
8. `sources.config.json` —— 新增源条目（旧 `wewe_rss_maobidao` 条目**保持原样不动**）

**数据库**：不需要任何迁移（radar 无表结构变化；sidecar 用自己的 SQLite 自行初始化）。

---

## 阶段一：部署 we-mp-rss sidecar（不动 radar 代码）

### 1.1 准备 Python 3.13
```powershell
py -0        # 查看已装版本
# 若列表中没有 3.13：
winget install Python.Python.3.13
```
若 winget 不可用或安装失败，**停下汇报**，不要改用 3.11 硬跑。

### 1.2 克隆并安装
```powershell
cd E:\AI-news-reader
git clone https://github.com/rachelos/we-mp-rss.git we-mp-rss-sidecar
cd we-mp-rss-sidecar
py -3.13 -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
copy config.example.yaml config.yaml
```
若 pip 安装因编译依赖失败，停下汇报具体包名，不要自行换包。

### 1.3 绑定检查与启动脚本
- 先确认 8001 端口空闲：`netstat -ano | findstr :8001`（被占则在 config.yaml 里改 port 为 8002 并在后续所有 base_url 同步）。
- 查 `main.py` 里 uvicorn 的 host 参数：若可通过配置/环境变量设监听地址，设为 `127.0.0.1`；若硬编码 `0.0.0.0`，保持默认但在完工汇报里**明确注明**"依赖 Windows 防火墙阻挡外网入站"。
- 新建 `start-we-mp-rss.ps1`：

```powershell
# 启动 we-mp-rss sidecar（微信公众号订阅服务，端口 8001）
Set-Location $PSScriptRoot
& .\.venv\Scripts\python.exe main.py -job True -init True *>> we-mp-rss.out.log
```

- 运行脚本，确认 `http://127.0.0.1:8001` 能打开登录页（默认账号见其 README/config，首次 `-init True` 会初始化管理员）。

> 安全要点（必须遵守）：sidecar 的 `data/` 目录含微信授权凭证，**不得**复制进 radar 仓库、不得出现在任何 git 提交里。RSS 端点无鉴权，不得做端口转发/内网穿透。

**扫码授权和添加"猫笔刀"公众号是人工步骤**，Codex 做到"服务能起、页面能开"即可，然后进入阶段二（代码不依赖 sidecar 里已有订阅）。

---

## 阶段二：radar 代码接入

### 2.1 `scripts/radar/common.py`
在第 269 行 `WEWE_RSS_DEFAULT_MAX_ITEMS = 20` 之后追加：

```python
WE_MP_RSS_SITE_ID = "we_mp_rss"
WE_MP_RSS_SITE_NAME = "WeRSS 公众号"
WE_MP_RSS_BASE_URL_DEFAULT = "http://127.0.0.1:8001"
WE_MP_RSS_DEFAULT_MAX_ITEMS = 20
```

第 393 行附近的 `SOURCE_CONFIG_ID_SITE_IDS`（现有 `"wewe_rss_maobidao": (WEWE_RSS_SITE_ID,),`）加一行：

```python
    "we_mp_rss_maobidao": (WE_MP_RSS_SITE_ID,),
```

第 421 行附近的 `SOURCE_CONFIG_TYPE_SITE_IDS`（现有 `"wewe_rss": (WEWE_RSS_SITE_ID,),`）加一行：

```python
    "we_mp_rss": (WE_MP_RSS_SITE_ID,),
```

### 2.2 `scripts/radar/fetchers/subscriptions.py`
文件头部 `from ..common import` 处（第 36-38 行附近已导入 WEWE_RSS_* 常量）补充导入 `WE_MP_RSS_BASE_URL_DEFAULT / WE_MP_RSS_DEFAULT_MAX_ITEMS / WE_MP_RSS_SITE_ID / WE_MP_RSS_SITE_NAME`。

在 `fetch_wewe_rss_subscription`（第 269-362 行）之后新增三个函数。整体照 wewe 版本的结构与状态字段写，差异点：拉 RSS XML 而非 JSON Feed、用 feedparser 解析、自动发现走 `{base}/rss`。

```python
def we_mp_rss_base_url() -> str:
    return (os.environ.get("WE_MP_RSS_BASE_URL") or WE_MP_RSS_BASE_URL_DEFAULT).strip().rstrip("/")


def parse_we_mp_rss_feed_items(
    feed_content: bytes,
    now: datetime,
    *,
    source_name: str,
    feed_id: str,
    max_items: int,
) -> list[RawItem]:
    if feedparser is None:
        return []
    parsed = feedparser.parse(feed_content)
    out: list[RawItem] = []
    seen: set[str] = set()
    for entry in parsed.entries:
        if len(out) >= max_items:
            break
        title = clean_wp_rendered_text(entry.get("title"), max_chars=160)
        url = normalize_url(first_non_empty(entry.get("link")))
        if not title or not url:
            continue
        key = url or title
        if key in seen:
            continue
        seen.add(key)
        published = parse_date_any(
            first_non_empty(entry.get("published"), entry.get("updated")),
            now,
        ) or now
        summary = clean_wp_rendered_text(
            first_non_empty(entry.get("summary"), entry.get("description")),
            max_chars=220,
        )
        out.append(
            RawItem(
                site_id=WE_MP_RSS_SITE_ID,
                site_name=WE_MP_RSS_SITE_NAME,
                source=source_name or "WeRSS",
                title=title,
                url=url,
                published_at=published,
                meta={
                    "summary": summary or title,
                    "source_kind": "we_mp_rss_wechat_subscription",
                    "wechat_account": source_name,
                    "we_mp_feed_id": feed_id,
                    "search_surface": "we_mp_rss_xml_feed",
                },
            )
        )
    return out


def discover_we_mp_rss_feeds(session: requests.Session, base: str) -> list[dict[str, str]]:
    """从 {base}/rss 的订阅列表 RSS 里提取 feed id（item link 形如 .../rss/{feed_id}）。"""
    resp = session.get(
        f"{base}/rss",
        params={"limit": 30},
        headers={"Accept": "application/xml", "User-Agent": "AI-News-Radar/0.7 we-mp-rss-bridge"},
        timeout=15,
    )
    resp.raise_for_status()
    if feedparser is None:
        return []
    parsed = feedparser.parse(resp.content)
    feeds: list[dict[str, str]] = []
    for entry in parsed.entries:
        link = first_non_empty(entry.get("link")) or ""
        match = re.search(r"/rss/([^/?#]+)", link)
        if not match:
            continue
        feeds.append({"id": match.group(1), "name": first_non_empty(entry.get("title")) or match.group(1)})
    return feeds


def fetch_we_mp_rss_subscription(
    session: requests.Session,
    now: datetime,
    *,
    base_url: str | None = None,
    feeds_config: str | None = None,
    max_items: int | None = None,
) -> tuple[list[RawItem], dict[str, Any]]:
    start = time.perf_counter()
    base = (base_url or we_mp_rss_base_url()).strip().rstrip("/")
    max_items_per_feed = max(1, min(100, int(max_items or env_int("WE_MP_RSS_MAX_ITEMS", WE_MP_RSS_DEFAULT_MAX_ITEMS))))
    status: dict[str, Any] = {
        "enabled": True,
        "ok": False,
        "item_count": 0,
        "duration_ms": 0,
        "error": None,
        "source_kind": "we_mp_rss_wechat_subscription",
        "base_url": base,
        "max_items_per_feed": max_items_per_feed,
        "feeds": [],
        "coverage_note": "reads_local_we_mp_rss_xml_feed_without_wechat_login_state",
        "privacy": "local_sidecar_no_cookies_in_radar_repo",
    }
    if not base:
        status["error"] = "missing_we_mp_rss_base_url"
        status["duration_ms"] = int((time.perf_counter() - start) * 1000)
        return [], status
    if feedparser is None:
        status["error"] = "feedparser_missing"
        status["duration_ms"] = int((time.perf_counter() - start) * 1000)
        return [], status

    configured_feeds = wewe_rss_feeds_from_env(feeds_config if feeds_config is not None else os.environ.get("WE_MP_RSS_FEEDS"))
    try:
        feeds = configured_feeds or discover_we_mp_rss_feeds(session, base)
        if not feeds:
            status["ok"] = True
            status["error"] = "we_mp_rss_no_feeds"
            return [], status

        all_items: list[RawItem] = []
        feed_statuses: list[dict[str, Any]] = []
        for feed in feeds:
            feed_id = feed["id"]
            source_name = feed.get("name") or feed_id
            feed_status = {"id": feed_id, "name": source_name, "ok": False, "item_count": 0, "error": None}
            try:
                resp = session.get(
                    f"{base}/feed/{feed_id}.rss",
                    params={"limit": max_items_per_feed},
                    headers={"Accept": "application/xml", "User-Agent": "AI-News-Radar/0.7 we-mp-rss-bridge"},
                    timeout=20,
                )
                resp.raise_for_status()
                items = parse_we_mp_rss_feed_items(
                    resp.content,
                    now,
                    source_name=source_name,
                    feed_id=feed_id,
                    max_items=max_items_per_feed,
                )
                all_items.extend(items)
                feed_status.update({"ok": True, "item_count": len(items)})
            except Exception as exc:
                feed_status["error"] = str(exc)
            feed_statuses.append(feed_status)

        status["feeds"] = feed_statuses
        status["item_count"] = len(all_items)
        status["ok"] = all(feed.get("ok") for feed in feed_statuses)
        failed = [feed for feed in feed_statuses if not feed.get("ok")]
        if failed:
            status["error"] = f"failed_we_mp_rss_feeds:{len(failed)}"
        return all_items, status
    except Exception as exc:
        status["error"] = str(exc)
        return [], status
    finally:
        status["duration_ms"] = int((time.perf_counter() - start) * 1000)
```

> 安全要点（必须遵守）：单个 feed 抓取失败只标记该 feed 的 error，不得让整轮采集抛异常（外层 try/except 结构照抄 wewe 版本）；`re` / `feedparser` 均为文件内已有导入，不要重复导入。

### 2.3 `scripts/radar/config_runtime.py`
- 头部 import 处补 `WE_MP_RSS_SITE_ID`（与 `WEWE_RSS_SITE_ID` 同一处导入）。
- `apply_source_config_runtime`（第 149 行起）：
  - 第 155 行 `wewe_feeds: list[str] = []` 旁加 `we_mp_feeds: list[str] = []`；
  - 循环内第 171-172 行（wewe 的 locator 收集）之后加：

```python
        if WE_MP_RSS_SITE_ID in site_ids and locator:
            we_mp_feeds.append(f"{target or name or locator}:{locator}")
```

  - 第 203-208 行（wewe 的环境变量落地）之后加：

```python
    if WE_MP_RSS_SITE_ID in enabled_site_ids:
        os.environ["WE_MP_RSS_ENABLED"] = "1"
        applied_env.append("WE_MP_RSS_ENABLED")
        if we_mp_feeds:
            os.environ["WE_MP_RSS_FEEDS"] = ";".join(we_mp_feeds)
            applied_env.append("WE_MP_RSS_FEEDS")
```

注意：locator 允许为空（走 fetcher 的自动发现），所以启用判断只看 `enabled_site_ids`，与 wewe 的写法一致。

### 2.4 `scripts/radar/cli.py`
- import 区（第 82 行 `fetch_wewe_rss_subscription,` 附近）补 `fetch_we_mp_rss_subscription` 与 `WE_MP_RSS_SITE_ID / WE_MP_RSS_SITE_NAME`。
- RunContext dataclass 第 126 行 `wewe_rss_enabled: bool` 下加 `we_mp_rss_enabled: bool`。
- 第 229-233 行（wewe 的开关判断）之后加：

```python
    we_mp_rss_enabled = env_flag("WE_MP_RSS_ENABLED") and (
        active_source_ids is None or WE_MP_RSS_SITE_ID in active_source_ids
    )
    if we_mp_rss_enabled and active_source_ids is not None:
        active_source_ids = frozenset(site_id for site_id in active_source_ids if site_id != MAOBIDAO_WECHAT_SITE_ID)
```

（第二段与 wewe 的 232-233 行同义：公众号源启用时跳过"猫笔刀备份源"，避免重复条目——这是 `sources.config.json` 里 `maobidao_wudaolu_backup` 条目 notes 写明的既有约定。）

- 第 265 行 RunContext 构造处加 `we_mp_rss_enabled=we_mp_rss_enabled,`；第 290 行附近取用处加 `we_mp_rss_enabled = ctx.we_mp_rss_enabled`。
- 第 356-374 行（wewe 的 fetch + statuses.append 块）之后照同样结构加一块：

```python
    if we_mp_rss_enabled:
        we_mp_rss_items, we_mp_rss_status = fetch_we_mp_rss_subscription(session, now)
        raw_items.extend(we_mp_rss_items)
        statuses.append(
            {
                "site_id": WE_MP_RSS_SITE_ID,
                "site_name": WE_MP_RSS_SITE_NAME,
                "ok": bool(we_mp_rss_status.get("ok")),
                "item_count": int(we_mp_rss_status.get("item_count") or 0),
                "duration_ms": int(we_mp_rss_status.get("duration_ms") or 0),
                "error": we_mp_rss_status.get("error"),
                "source_kind": we_mp_rss_status.get("source_kind"),
                "base_url": we_mp_rss_status.get("base_url"),
                "max_items_per_feed": we_mp_rss_status.get("max_items_per_feed"),
                "feeds": we_mp_rss_status.get("feeds"),
                "coverage_note": we_mp_rss_status.get("coverage_note"),
                "privacy": we_mp_rss_status.get("privacy"),
            }
        )
```

注意：第 375 行现有 `elif scoped_by_config ... MAOBIDAO_WECHAT_SITE_ID ...` 分支（猫笔刀备份源回退）**保持原样**，新块用独立 `if`，插在该 `elif` 所属的 `if wewe_rss_enabled` 块之后、`elif` 之前会破坏语法——正确做法：把新块放在整个 wewe `if/elif` 结构**之后**作为独立语句。

### 2.5 `scripts/update_news.py`
第 124-130 行 re-export 区（`fetch_wewe_rss_subscription = ...` 附近）追加：

```python
fetch_we_mp_rss_subscription = _subscriptions.fetch_we_mp_rss_subscription
parse_we_mp_rss_feed_items = _subscriptions.parse_we_mp_rss_feed_items
discover_we_mp_rss_feeds = _subscriptions.discover_we_mp_rss_feeds
```

### 2.6 `scripts/radar/server/subscriptions_store.py`
第 157-165 行 `PURGE_TRACKED_SITE_IDS` 集合加 `"we_mp_rss",`。

### 2.7 `scripts/radar/server/common.py`
第 56-57 行（wewe 的 runtime id 识别）之后加同构分支：

```python
    if raw_type == "we_mp_rss" or raw_id.startswith("we_mp_rss") or "we_mp_rss" in haystack:
        runtime_ids.add("we_mp_rss")
```

注意 wewe 那行的匹配串 `"wewe_rss" in haystack` 不会命中 `we_mp_rss`（子串不同），两分支互不干扰；本文件其余 wewe 专属逻辑（fix actions、扫码按钮等）**本次不做**。

### 2.8 `sources.config.json`
在 `wewe_rss_maobidao` 条目之后新增（旧条目原样保留）：

```json
{
  "id": "we_mp_rss_maobidao",
  "name": "猫笔刀 (WeRSS)",
  "type": "we_mp_rss",
  "enabled": true,
  "channel": "微信公众号",
  "target": "猫笔刀",
  "locator": "",
  "env": "WE_MP_RSS_ENABLED / WE_MP_RSS_BASE_URL / WE_MP_RSS_FEEDS",
  "notes": "we-mp-rss sidecar（127.0.0.1:8001）。locator 留空=自动发现 sidecar 内全部订阅；也可填单个公众号的 feed id 精确锁定。"
}
```

---

## 三、自测（改完必须跑，全绿才算完成）

在 `E:\AI-news-reader\ai-news-radar-run` 依次执行：

```powershell
python -m pytest tests/test_we_mp_rss_source.py -q
python -m pytest -q
python scripts/update_news.py --source-config sources.config.json
```

新建 `tests/test_we_mp_rss_source.py`（照 `tests/` 下现有测试的风格），**本次新写的每条分支都要有用例**：

1. `parse_we_mp_rss_feed_items`：合法 RSS 2.0 XML 样例 → 正确产出 RawItem（标题/链接/时间/meta 字段齐全）；
2. 去重分支：重复 link 只出一条；超过 max_items 截断；
3. `discover_we_mp_rss_feeds`：从含 `.../rss/{id}` 链接的列表 XML 中提取 id 与名称；链接不含 `/rss/` 时跳过；
4. `fetch_we_mp_rss_subscription`（mock session）：单 feed HTTP 报错 → 该 feed error、整体不抛、`error` 为 `failed_we_mp_rss_feeds:1`；无 feed 时 `ok=True` 且 `error=we_mp_rss_no_feeds`；坏 XML → 产出 0 条不崩；
5. `config_runtime`：含 `type: we_mp_rss` 且 enabled 的配置 → `WE_MP_RSS_ENABLED=1`；locator 为空时不设 `WE_MP_RSS_FEEDS`。

第三条命令要求 sidecar 已启动；跑完检查 `feeds/source-status.json`（或输出目录下同名文件）中 `we_mp_rss` 条目：sidecar 已授权并添加公众号时应 `ok:true` 且 `item_count>0`；sidecar 未授权时允许 `we_mp_rss_no_feeds`，也算通过，但要在汇报里注明。

全部通过后**停下**，向用户汇报，**不要自行 commit**。

---

## 四、人工验收清单（交给用户在真实环境点）

1. 双击/运行 `start-we-mp-rss.ps1`，浏览器打开 `http://127.0.0.1:8001`，用初始化的管理员账号登录。
2. ⚠️ **扫码授权**（微信扫公众平台二维码）——这条没法自动测，务必亲手扫一遍并确认后台显示"已授权"。
3. ⚠️ 在 we-mp-rss 后台**添加订阅"猫笔刀"**并手动触发一次更新——同样没法自动测，确认它的文章列表里出现猫笔刀近期文章。
4. 浏览器打开 `http://127.0.0.1:8001/feed/all.rss`，能看到 XML 里有猫笔刀文章。
5. 在 radar 目录跑 `python scripts/update_news.py --source-config sources.config.json`，然后打开 radar 本地看板（项目铁律：浏览器真实验证），确认"微信公众号"频道出现猫笔刀文章、来源健康面板中 `WeRSS 公众号` 为绿色。
6. ⚠️ 容错验证：停掉 sidecar 再跑一次 update_news——radar 不崩，看板该源显示错误状态，其它源正常出数。
7. 边界确认：重启电脑后 sidecar 不会自启（本次未做自启），需手动跑 `start-we-mp-rss.ps1`；微信授权过期后需回后台重新扫码（可在 we-mp-rss 设置里配过期通知，本次不强制）。

---

## 五、红线（务必遵守）

- 不要新建分支、不要 commit / push（用户验收后自己决定）。
- 只动"文件清单"列出的文件；wewe_rss 旧通道的代码与配置**一行都不许删改**。
- 不要做批量文件删除操作。
- sidecar 的 `data/` 目录（含微信授权凭证、SQLite 库）不得进入 radar 仓库、不得出现在任何提交里；radar 仓库内不得写入任何 cookie/token（CLAUDE.md 既有铁律）。
- sidecar 只允许本机访问：不改防火墙、不做端口映射；其 RSS 端点无鉴权，暴露公网等于公开代理。
- 不要调高 we-mp-rss 的抓取频率配置（保持默认定时任务），降低微信风控风险。
- 单 feed 失败必须被 try/except 包住（2.2 节安全要点），不得影响 radar 整轮采集。

---

## 遵循的规范（`CLAUDE.md` + `docs/SOURCE_COVERAGE.md`）

新源走"官方 RSS/Atom 优先"路线（we-mp-rss 输出标准 RSS 2.0）；来源状态统一进 `statuses` 列表由看板消费；不提交任何私密凭证；浏览器可见流程必须真实浏览器验收。若 `docs/SOURCE_COVERAGE.md` 中维护了源清单表格，同步补一行 we_mp_rss（属文档更新，允许）。

# PROJECT_STATE

## Current State

- Date: 2026-07-02
- Local path: `E:\AI-news-reader\ai-news-radar-run`
- Branch: `master`
- Task type: Local source configuration backend
- Server: `http://localhost:8080/`
- Current local view: source configuration UI added to the local dashboard; the editor lists both built-in sources and personal subscriptions; `scripts/local_server.py` lets the page read/write project-root `sources.config.json` directly and trigger a fixed local refresh from the page.
- Default output source ids: `bilibili_dynamic`, `mediacrawler_douyin`, `mediacrawler_xhs`, `github_foundation_sunshine_releases`, `maobidao_wudaolu_backup`, `wewe_rss`
- Source config catalog: built-in official/media/community/API sources are visible in the editor and default to disabled; after exporting to `sources.config.json`, the refresh script uses enabled rows as the active source set.
- WeWe RSS runtime: set `WEWE_RSS_ENABLED=1`, `WEWE_RSS_BASE_URL=http://127.0.0.1:4000`, and optionally `WEWE_RSS_FEEDS=猫笔刀:MP_WXS_3198966508` to read the local sidecar.

## What Was Done

- Created and used the runnable repo copy at `E:\AI-news-reader\ai-news-radar-run`.
- Added a static source configuration panel on the main page:
  - supports local draft editing in browser localStorage.
  - supports add/edit/enable/disable/delete inside the draft.
  - supports import/export/copy of `sources.config.json`.
  - lists the built-in official/media/community/API source catalog as well as `我的订阅` sources.
  - auto-merges newly added built-in catalog entries into older browser localStorage drafts.
  - does not add a backend and does not write local files directly.
  - does not store cookies, tokens, `.env`, WeChat login state, QR login artifacts, or browser profiles.
  - exported `sources.config.json` is now consumable by `scripts/update_news.py` via `--source-config` or the project-root default file.
  - when served through `scripts/local_server.py`, the page can read and write project-root `sources.config.json` through `/api/source-config`.
  - the write button now gives visible in-button feedback (`写入中...`, `已写入`, `写入失败`) instead of silently finishing.
  - the new `刷新数据` button writes the current config, calls `/api/refresh`, runs the fixed `scripts/update_news.py --source-config sources.config.json --output-dir data --window-hours 24 --archive-days 3650 --all-time` command, and reloads the page after success.
  - if served through plain `python -m http.server`, the page still falls back to browser localStorage plus export/copy.
- Added optional WeWe RSS bridge:
  - source id: `wewe_rss`
  - toggle: `WEWE_RSS_ENABLED=1`
  - base URL: `WEWE_RSS_BASE_URL` (default `http://127.0.0.1:4000`)
  - feed selection: `WEWE_RSS_FEEDS`, for example `猫笔刀:MP_WXS_3198966508`
  - default behavior: disabled unless explicitly enabled; reads only WeWe RSS JSON Feed endpoints and does not read wewe-rss DB, cookies, `.env`, or WeChat login state.
  - when enabled, the old `maobidao_wudaolu_backup` fallback is skipped to avoid duplicate 猫笔刀 articles.
- Added Bilibili dynamic tracking for two accounts:
  - UID `505301413`: `Koji杨远骋at十字路口`
  - UID `316183842`: `技术爬爬虾`
- Added multi-account config:
  - `BILIBILI_DYNAMIC_UIDS`
  - `BILIBILI_DYNAMIC_SOURCE_NAMES`
  - old single-account vars remain compatible: `BILIBILI_DYNAMIC_UID`, `BILIBILI_DYNAMIC_SOURCE_NAME`
- Added browser-cookie support:
  - raw cookie env: `BILIBILI_COOKIE` / `BILIBILI_DYNAMIC_COOKIE`
  - browser export file: `BILIBILI_COOKIE_FILE` / `BILIBILI_DYNAMIC_COOKIE_FILE`
  - supports Netscape `cookies.txt` and Cookie-Editor style JSON exports
- Added signed full dynamic fetching with WBI signing, browser-like headers, and pagination.
- Added fallback behavior: if cookie full dynamic fails, the source can fall back to public opus dynamic.
- Added pagination controls:
  - `BILIBILI_DYNAMIC_MAX_ITEMS`
  - `BILIBILI_DYNAMIC_MAX_PAGES`
- Added Bilibili-only local refresh mode with `--bilibili-only`.
- Added all-time local view mode with `--all-time`.
- Updated the frontend so Bilibili-only all-time data shows as `全部时间`, uses only Bilibili sources, and does not force the old 24-hour wording.
- Updated GitHub Actions defaults so scheduled refresh can track both Bilibili UIDs when cookie secret/config exists.
- Added detailed implementation documentation in `docs/guides/bilibili-dynamic-source.md`.
- Added a private local Douyin bridge:
  - source id: `mediacrawler_douyin`
  - enable toggle: `MEDIACRAWLER_DOUYIN_ENABLED=1`
  - JSONL path: `MEDIACRAWLER_DOUYIN_JSONL`
  - source display name override: `MEDIACRAWLER_DOUYIN_SOURCE_NAME`
  - default behavior: disabled, reads exported JSONL only, does not launch MediaCrawler or Chrome from the radar repo.
- Added a private local Xiaohongshu bridge:
  - source id: `mediacrawler_xhs`
  - enable toggle: `MEDIACRAWLER_XHS_ENABLED=1`
  - JSONL path: `MEDIACRAWLER_XHS_JSONL`
  - source display name override: `MEDIACRAWLER_XHS_SOURCE_NAME`
  - long alias env names are also accepted: `MEDIACRAWLER_XIAOHONGSHU_*`
  - default behavior: disabled, reads exported JSONL only, does not launch MediaCrawler or Chrome from the radar repo.

## Verification

- 2026-07-02 WeWe RSS bridge verification:
  - `.\.venv\Scripts\python.exe -m py_compile scripts/update_news.py` passed.
  - `node --check assets\app.js` passed.
  - `.\.venv\Scripts\python.exe -m unittest tests.test_topic_filter` passed: 83 tests OK.
  - `git diff --check -- scripts/update_news.py assets/app.js tests/test_topic_filter.py README.md docs/SOURCE_COVERAGE.md PROJECT_STATE.md HANDOFF.md` passed; PowerShell reported only Windows LF-to-CRLF warnings.
  - Real local refresh with `WEWE_RSS_ENABLED=1`, `WEWE_RSS_BASE_URL=http://127.0.0.1:4000`, and `WEWE_RSS_FEEDS=猫笔刀:MP_WXS_3198966508` wrote fresh `data/*.json`.
  - `data/source-status.json`: `wewe_rss.ok=true`, `wewe_rss.item_count=20`.
  - `data/latest-24h-all.json`: `creator_items_all` has 20 `wewe_rss` records and 0 `maobidao_wudaolu_backup` records.
  - Latest two WeWe RSS records: `又要制裁了` (`2026-07-01T14:24:08Z`) and `上限锁死了` (`2026-06-30T14:22:26Z`).
  - `http://127.0.0.1:8080/data/latest-24h-all.json` returned HTTP 200 with the same WeWe RSS counts and latest two records.
  - User confirmed the local page acceptance succeeded at `http://127.0.0.1:8080/`.
- 2026-07-02 source configuration UI verification:
  - `node --check assets\app.js` passed.
  - `git diff --check -- index.html assets/app.js assets/styles.css` passed; PowerShell reported only Windows LF-to-CRLF warnings.
  - `http://127.0.0.1:8080/index.html` returned HTTP 200 and contains `source-config-ui-0702a` plus `sourceConfigTitle`.
  - Static scan confirmed `index.html`, `assets/app.js`, and `assets/styles.css` contain the source-config UI hooks.
  - In-app browser automation timed out while connecting, so direct click-through validation is still manual.
- 2026-07-02 source configuration catalog fix verification:
  - `node --check assets\app.js` passed.
  - `git diff --check -- assets/app.js index.html PROJECT_STATE.md HANDOFF.md` passed; PowerShell reported only Windows LF-to-CRLF warnings.
  - `http://127.0.0.1:8080/index.html` returned HTTP 200 and contains `source-config-ui-0702b`.
  - `http://127.0.0.1:8080/assets/app.js?v=source-config-ui-0702b` returned HTTP 200 and contains `官方一手源包`, `TikHub 抖音/小红书`, and `mergeSourceConfigWithSeed`.
  - In-app browser refresh at `http://127.0.0.1:8080/` confirmed the source config list now shows 28 rows and summary `4/28 启用`.
  - The first visible rows are built-in sources such as `官方一手源包`, `精选AI媒体包`, `AI HOT`, `Hacker News`, and aggregation/community sources, not only `我的订阅`.
- 2026-07-02 source configuration effective-runtime verification:
  - `.\.venv\Scripts\python.exe -m py_compile scripts\update_news.py` passed.
  - `node --check assets\app.js` passed.
  - `.\.venv\Scripts\python.exe -m unittest tests.test_topic_filter` passed: 85 tests OK.
  - `git diff --check -- scripts/update_news.py assets/app.js index.html README.md PROJECT_STATE.md HANDOFF.md .gitignore tests/test_topic_filter.py` passed; PowerShell reported only Windows LF-to-CRLF warnings.
  - Smoke run with a temporary `sources.config.json` enabling only `github_foundation_sunshine` wrote output under `%TEMP%\ai-news-radar-source-config-smoke-output`.
  - The smoke `data/source-status.json` reported `source_config.active=True`, `source_scope=configured_sources`, and `sites=github_foundation_sunshine_releases`.
  - `http://127.0.0.1:8080/index.html` returned HTTP 200 and contains `source-config-effective-0702a`.
  - `http://127.0.0.1:8080/assets/app.js?v=source-config-effective-0702a` returned HTTP 200 and contains the new `sources.config.json` apply hint.
- 2026-07-02 local source configuration backend verification:
  - Added `scripts/local_server.py`, a local-only static server with `GET/POST /api/source-config`.
  - `.\.venv\Scripts\python.exe -m py_compile scripts\local_server.py scripts\update_news.py` passed.
  - `node --check assets\app.js` passed.
  - `.\.venv\Scripts\python.exe -m unittest tests.test_local_server tests.test_topic_filter.TopicFilterTests.test_apply_source_config_runtime_sets_fetcher_env_without_secrets tests.test_topic_filter.TopicFilterTests.test_source_config_enabled_site_ids_maps_ui_records_to_fetchers` passed: 5 tests OK.
  - `git diff --check -- scripts/local_server.py assets/app.js index.html README.md .gitignore tests/test_local_server.py` passed; PowerShell reported only Windows LF-to-CRLF warnings.
  - Replaced the current port 8080 preview with `.\.venv\Scripts\python.exe scripts\local_server.py --host 127.0.0.1 --port 8080`.
  - `GET http://127.0.0.1:8080/api/source-config` returned HTTP 200 and `ok=true`.
  - `POST http://127.0.0.1:8080/api/source-config` with the current config returned HTTP 200, `ok=true`, and `source_count=7`.
  - `http://127.0.0.1:8080/index.html` returned HTTP 200 and contains `source-config-local-server-0702a`.
  - In-app browser refresh confirmed the page shows the new `写入` button and status `已读取 sources.config.json`.
- 2026-07-02 local one-click refresh verification:
  - `scripts/local_server.py` now exposes `POST /api/refresh`, guarded by a single refresh lock and a fixed local command only.
  - `node --check assets\app.js` passed.
  - `.\.venv\Scripts\python.exe -m py_compile scripts\local_server.py scripts\update_news.py` passed.
  - `.\.venv\Scripts\python.exe -m unittest tests.test_local_server tests.test_topic_filter` passed: 89 tests OK.
  - `git diff --check -- scripts/local_server.py tests/test_local_server.py index.html assets/app.js assets/styles.css README.md PROJECT_STATE.md HANDOFF.md` passed; PowerShell reported only Windows LF-to-CRLF warnings.
  - Restarted local preview with `.\.venv\Scripts\python.exe scripts/local_server.py --host 127.0.0.1 --port 8080`.
  - `GET http://127.0.0.1:8080/api/source-config` returned HTTP 200 and `ok=true`.
  - `POST http://127.0.0.1:8080/api/source-config` returned HTTP 200, `ok=true`, and `source_count=27`.
  - `http://127.0.0.1:8080/index.html` returned HTTP 200 and contains `source-config-refresh-0702a`.
  - `http://127.0.0.1:8080/assets/app.js?v=source-config-refresh-0702a` returned HTTP 200 and contains `sourceConfigRefreshBtn` plus `./api/refresh`.
  - `POST http://127.0.0.1:8080/api/refresh` returned HTTP 200, `ok=true`, `source_scope=configured_sources`, and `fetched_raw_items=316`.
  - Refresh status sites were all OK: `github_foundation_sunshine_releases=5`, `wewe_rss=20`, `bilibili_dynamic=25`, `mediacrawler_douyin=68`, `mediacrawler_xhs=198`.
  - In-app browser automation timed out twice while reading DOM, so final UI verification used local HTTP/static checks plus real API refresh result.
- 2026-07-02 AI HOT source-config mapping fix:
  - Root cause: the UI config row had `id=aihot` but `type=rss`, so `source_config_record_site_ids()` did not map it to the built-in `aihot` fetcher.
  - Fix: built-in source ids that already match known source types are now mapped by `id` before falling back to `type`.
  - `.\.venv\Scripts\python.exe -m py_compile scripts\update_news.py` passed.
  - Targeted unittest `tests.test_topic_filter.TopicFilterTests.test_source_config_enabled_site_ids_maps_ui_records_to_fetchers` passed.
  - `.\.venv\Scripts\python.exe -m unittest tests.test_local_server tests.test_topic_filter` passed: 89 tests OK.
  - `node --check assets\app.js` passed.
  - `POST http://127.0.0.1:8080/api/refresh` returned HTTP 200 and `ok=true`.
  - `data/source-status.json` now reports `successful_sites=6`, `enabled_source_count=7`, and `enabled_site_ids=aihot,bilibili_dynamic,github_foundation_sunshine_releases,mediacrawler_douyin,mediacrawler_xhs,wewe_rss`.
  - AI HOT is now active: `aihot.ok=true`, `aihot.item_count=109`.
  - Note: `enabled_source_count=7` can still show as `6/6 源正常` because two Bilibili UI rows collapse into one runtime fetcher `bilibili_dynamic`.
- `.\.venv\Scripts\python.exe -m py_compile scripts/update_news.py` passed.
- `.\.venv\Scripts\python.exe -m unittest tests.test_private_bridge_sources` passed: 19 tests OK.
- `git diff --check -- scripts/update_news.py assets/app.js tests/test_private_bridge_sources.py docs/SOURCE_COVERAGE.md PROJECT_STATE.md` passed; PowerShell reported only Windows LF-to-CRLF warnings.
- Real local cookie refresh with `C:\Users\Administrator\Pictures\cookies.txt` passed without printing cookie values.
- Latest all-source refresh with local MediaCrawler Douyin JSONL wrote:
  - `data/latest-24h.json`: 17751 items
  - `data/latest-24h-all.json`: 126212 all-mode items
  - `data/stories-merged.json`: 15015 stories
  - `data/archive.json`: 135913 retained archive items
  - `data/source-status.json`: source status OK
- Local Douyin data check confirmed:
  - `mediacrawler_douyin.ok=true`
  - `mediacrawler_douyin.item_count=68`
  - `items_all_raw` contains 68 `mediacrawler_douyin` records
  - `items_all` contains 68 `mediacrawler_douyin` records
  - `creator_items_all` contains 67 `mediacrawler_douyin` records after existing near-duplicate suppression
- `http://127.0.0.1:8080/data/source-status.json` returned HTTP 200 and `mediacrawler_douyin.item_count=68`.
- Latest all-source refresh with local MediaCrawler Xiaohongshu JSONL wrote:
  - `data/latest-24h.json`: 17861 items
  - `data/latest-24h-all.json`: 127284 all-mode items
  - `data/stories-merged.json`: 15107 stories
  - `data/archive.json`: 137049 retained archive items
  - `data/source-status.json`: source status OK
- Local Xiaohongshu data check confirmed:
  - `mediacrawler_xhs.ok=true`
  - `mediacrawler_xhs.item_count=198`
  - `items_all_raw` contains 198 `mediacrawler_xhs` records
  - `items_all` contains 198 `mediacrawler_xhs` records
  - `creator_items_all` contains 198 `mediacrawler_xhs` records
  - latest sampled source/title decode correctly as `陈抱一` / `【开箱】小米NAS终于来了...`
- Browser check at `http://127.0.0.1:8080/` confirmed:
  - site filter includes `MediaCrawler Xiaohongshu (2/198 · 1%AI)`
  - the `自媒体` tab shows 215 AI-relevant creator signals
  - page text includes `陈抱一` after entering the `自媒体` tab
- Latest Bilibili-only all-time refresh wrote:
  - `data/latest-24h.json`: 119 items
  - `data/latest-24h-all.json`: 261 all-mode Bilibili items
  - `data/stories-merged.json`: 118 stories
  - `data/archive.json`: 133599 retained archive items
  - `data/source-status.json`: source status OK
- Local data check confirmed:
  - `time_scope=all_time`
  - `source_scope=bilibili_only`
  - only site is `bilibili_dynamic`
  - `技术爬爬虾`: 200 items
  - `Koji杨远骋at十字路口`: 61 items
  - total Bilibili items in all-mode payload: 261
  - oldest visible tracked item: 2025-01-27

## Notes

- Do not paste Bilibili cookies into chat or commit them. Use local environment variables or GitHub Secrets only.
- Do not commit `E:\AI-news-reader\MediaCrawler-local-test\chrome-profile` or MediaCrawler login/session output. The radar bridge only needs the generated `creator_contents_*.jsonl` path at runtime.
- `data/*.json` files are generated runtime data for local preview. They are useful for checking the page, but they are not staged as source-code changes.
- `requirements.txt` has an unstaged local setup change from earlier Windows environment work; it is not part of the Bilibili tracking commit scope right now.
- `bilibili-account-preview.html`, `server.err.log`, and `server.out.log` are local preview/log artifacts and are not staged.
- Bilibili APIs, WBI signing behavior, cookie validity, and rate limits can change, so this source should be treated as integration-sensitive.
- Keep pagination limits moderate to avoid putting too much pressure on Bilibili endpoints.
- WeWe RSS is now the preferred local source for `猫笔刀`; keep `maobidao_wudaolu_backup` as fallback code, but when `WEWE_RSS_ENABLED=1` the generated output intentionally excludes the old backup records.
- Do not commit wewe-rss database files, cookies, `.env`, QR login artifacts, browser profiles, or `AUTH_CODE`.
- The source configuration UI can now write `sources.config.json` directly when served by `scripts/local_server.py`. Plain `python -m http.server` remains read-only and should only be used with export/copy fallback.

## How To Refresh The Bilibili-Only All-Time View

```powershell
$env:PYTHONIOENCODING='utf-8'
$env:BILIBILI_DYNAMIC_ENABLED='1'
$env:BILIBILI_COOKIE_FILE='C:\Users\Administrator\Pictures\cookies.txt'
$env:BILIBILI_DYNAMIC_UIDS='505301413,316183842'
$env:BILIBILI_DYNAMIC_SOURCE_NAMES='Koji杨远骋at十字路口,技术爬爬虾'
$env:BILIBILI_DYNAMIC_MAX_ITEMS='200'
$env:BILIBILI_DYNAMIC_MAX_PAGES='20'
.\.venv\Scripts\python.exe scripts/update_news.py --output-dir data --window-hours 24 --archive-days 3650 --bilibili-only --all-time
```

## Next Entry

- Overall acceptance is complete for Bilibili, Douyin, Xiaohongshu, foundation-sunshine GitHub release subscription, and WeWe RSS `猫笔刀` public-account subscription.
- Source configuration UI v1 is implemented as a local editor; `scripts/local_server.py` lets the page persist `sources.config.json`, and that file drives the refresh script.
- User confirmed the source configuration UI, local write, one-click refresh, and AI HOT fix in the in-app browser at `http://127.0.0.1:8080/`.
- Git save is complete: commit `a86c493 feat: add configurable local source dashboard` is pushed to `https://github.com/kunkunzi996/ai-news-radar.git` on `master`.
- Current `origin` is `https://github.com/kunkunzi996/ai-news-radar.git`.
- Next window should read `HANDOFF.md` first, then inspect `git status --short --branch`.
- Remaining local dirty files are intentionally not committed:
  - generated `data/*.json` from local refresh, because the refreshed Xiaohongshu URLs include `xsec_token` parameters.
  - `bilibili-account-preview.html`, `server.err.log`, and `server.out.log` local preview/log artifacts.
- Next recommended task: decide a safe generated-data policy, such as stripping Xiaohongshu `xsec_token` before committing snapshots, or keeping local subscription data untracked.

## How To Refresh The All-Source View With Local Douyin Creator JSONL

```powershell
$env:PYTHONIOENCODING='utf-8'
$env:MEDIACRAWLER_DOUYIN_ENABLED='1'
$env:MEDIACRAWLER_DOUYIN_JSONL='E:\AI-news-reader\MediaCrawler-local-test\output\douyin\jsonl\creator_contents_2026-07-01.jsonl'
$env:MEDIACRAWLER_DOUYIN_SOURCE_NAME='Simon林'
.\.venv\Scripts\python.exe scripts/update_news.py --output-dir data --window-hours 24 --archive-days 3650 --all-time
```

## How To Refresh The All-Source View With Local Xiaohongshu Creator JSONL

```powershell
$env:PYTHONIOENCODING='utf-8'
$env:MEDIACRAWLER_XHS_ENABLED='1'
$env:MEDIACRAWLER_XHS_JSONL='E:\AI-news-reader\MediaCrawler-local-test\output\xhs\jsonl\creator_contents_2026-07-01.jsonl'
$env:MEDIACRAWLER_XHS_SOURCE_NAME='陈抱一'
.\.venv\Scripts\python.exe scripts/update_news.py --output-dir data --window-hours 24 --archive-days 3650 --all-time
```

## 2026-07-01 Source Scope Correction

- Default deployed source scope is now `tested_creator_sources`.
- Only these source ids are published by default:
  - `bilibili_dynamic`
  - `mediacrawler_douyin`
  - `mediacrawler_xhs`
  - `github_foundation_sunshine_releases`
- Legacy built-in fetchers remain in code for manual `--source-scope all_sources` runs, but they are no longer part of the default deployed output.
- GitHub Actions no longer prepares OPML or passes AgentMail, X API, SocialData, or TikHub env vars into the default refresh.
- Project data was regenerated with the tested subscription sources only:
  - `data/source-status.json.source_scope=tested_creator_sources`
  - `bilibili_dynamic`: 261 items
  - `mediacrawler_douyin`: 68 items
  - `mediacrawler_xhs`: 198 items
  - `github_foundation_sunshine_releases`: 5 items
  - `data/latest-24h-all.json`: 532 all-mode items
  - `data/archive.json`: 532 retained archive items
- No files or directories were deleted.

## Verification For Source Scope Correction

- `.\.venv\Scripts\python.exe -m py_compile scripts/update_news.py` passed.
- `.\.venv\Scripts\python.exe -m unittest tests.test_private_bridge_sources` passed: 19 tests OK.
- `.\.venv\Scripts\python.exe -m unittest tests.test_topic_filter.TopicFilterTests.test_default_source_scope_keeps_only_tested_creator_sources tests.test_topic_filter.TopicFilterTests.test_build_latest_payloads_keeps_initial_payload_slim tests.test_topic_filter.TopicFilterTests.test_tikhub_default_off_does_not_request_network` passed: 3 tests OK.
- `node --check assets/app.js` passed.
- `git diff --check` passed with only Windows LF-to-CRLF warnings.
- User confirmed overall acceptance success in the in-app browser at `http://127.0.0.1:8080/`.

## 2026-07-01 Cleanup Status

- Project cleanup gate executed after user acceptance.
- `PROJECT_STATE.md` and `HANDOFF.md` were synchronized as the next-round entry points.
- README and `docs/SOURCE_COVERAGE.md` already describe the new default source scope, so no additional cleanup edit was needed there.
- AGENTS.md / CLAUDE.md were left unchanged because no new permanent AI施工 rule was introduced beyond the existing no-secret/no-delete boundaries.
- No files or directories were deleted.
- No Git commit or push was performed.

## 2026-07-02 Maobidao WeChat Subscription

- User requested using 伯乐Skill to subscribe to the WeChat public account `猫笔刀` and show the latest two updates at `http://127.0.0.1:8080/`.
- Source classification: WeChat public-account source, handled through a public Discourse backup JSON endpoint, not through WeChat login, cookies, or browser automation.
- Added source id: `maobidao_wudaolu_backup`.
- Initial `maobidao.net` probe was rejected because its latest records were from 2025-12, which is too stale for "recent updates".
- Current fetch path: `https://wudaolu.com/c/dav/7.json`.
- The source enters the existing `我的订阅` lane and default `tested_creator_sources` scope.
- Latest verified records from the source:
  - `猫笔刀-又要制裁了-2026-07-01`
  - `猫笔刀-上限锁死了-2026-06-30`
- Risk: this is a third-party public backup path, so it can break if the backup site changes or stops updating. It is not an official WeChat RSS feed.

## 2026-07-02 WeWe RSS Deployment Plan

- User clarified the final daily dashboard must remain AI News Radar; separate tools are acceptable only as background collectors.
- `wewe-rss` should be treated as an independent sidecar service:
  - WeChat public account -> wewe-rss RSS/JSON -> AI News Radar `我的订阅`
  - The user should not need to open wewe-rss daily after setup.
- Next planned acceptance loop:
  - Deploy `cooderl/wewe-rss` separately.
  - Log in through WeChat Reading only inside wewe-rss.
  - Add `猫笔刀`.
  - Confirm a local RSS/JSON feed URL returns recent article data.
  - Only after that, add an optional AI News Radar bridge such as `WEWE_RSS_ENABLED`, `WEWE_RSS_BASE_URL`, and `WEWE_RSS_FEEDS`.
- Safety boundary:
  - Do not commit wewe-rss database files, QR/login artifacts, cookies, `.env`, or `AUTH_CODE`.
  - Do not delete `maobidao_wudaolu_backup` until wewe-rss is validated and the user confirms switching.
  - The `cooderl/wewe-rss` repository is archived/read-only as of 2026-05-11, so treat it as useful but maintenance-sensitive.

## 2026-07-01 Subscription Tab Update

- Renamed the reader-facing `自媒体` section to `我的订阅`.
- The existing internal `creator` section id remains unchanged to keep the change small.
- Bilibili, Douyin, Xiaohongshu, and YouTube/youtu.be records are now treated as subscription items for section grouping and creator-hot payloads.
- `bilibili_dynamic` now maps to the `我的订阅` source tier instead of falling through to `其他来源`.
- `index.html` app script cache-buster was updated so the browser loads the new tab label.

## Verification For Subscription Tab Update

- `node --check assets/app.js` passed.
- `.\.venv\Scripts\python.exe -m py_compile scripts/update_news.py` passed.
- Targeted unittest passed: `tests.test_topic_filter.TopicFilterTests.test_source_tiers_separate_discussion_signals_from_core_sources`, `test_build_creator_hot_items_includes_bilibili_without_metrics`, `test_build_creator_hot_items_can_use_all_time_window_for_bilibili`, `test_build_creator_hot_items_includes_youtube_subscription_without_metrics`.
- Local HTTP checks passed:
  - `http://127.0.0.1:8080/index.html` returned 200.
  - served `index.html` contains `<option value="creator">我的订阅</option>`.
  - served `assets/app.js` contains `我的订阅`, `B站订阅`, `YouTube订阅`, and `订阅热度`.
- In-app browser automation attempted twice but timed out during navigation/control, so final UI verification used local HTTP output plus syntax/tests instead of a successful browser click-through.

## 2026-07-01 Time Range Unlimited Option

- Added a `不限` option to the time range select.
- Default remains `过去 24 小时`.
- Selecting `不限` removes the front-end 24-hour cutoff for the currently loaded data and loads `latest-24h-all.json` when needed.
- Selecting `过去 24 小时` applies a 24-hour cutoff anchored to `generated_at`.
- `index.html` app script cache-buster was updated again so the browser loads the new time-range logic.

## 2026-07-01 YouTube Subscription Visibility Fix

- Current `latest-24h-all.json` already contains a YouTube item from `feeds/follow.opml`, but `creator_items_all` was generated before YouTube subscription merging existed.
- Frontend `我的订阅` now merges prebuilt `creator_items_*` with current mode items that match subscription rules.
- YouTube is only dynamically added to `我的订阅` when the item comes from OPML/RSS (`opmlrss` / `opmlrss:*`) to avoid treating random YouTube links from generic news sources as personal subscriptions.
- Verified local all-mode data contains 1 OPML YouTube item.
- `node --check assets/app.js` passed.

## 2026-07-01 TopHub Subscription False Positive Fix

- TopHub was incorrectly appearing under `我的订阅` because generic TopHub rows can link to Bilibili/Douyin hot-list URLs.
- Tightened frontend subscription detection:
  - Always include explicit tracked source ids: Bilibili Dynamic, MediaCrawler Douyin/XHS, TikHub Douyin/Xiaohongshu.
  - Only include platform URLs from personal RSS/OPML (`opmlrss` / `opmlrss:*`).
  - Do not classify generic aggregate sources such as TopHub as subscriptions just because their item URL points to Bilibili/Douyin/YouTube.
- Verified against current `latest-24h-all.json`:
  - TopHub subscription matches: 0
  - OPML YouTube subscription matches: 1
- `node --check assets/app.js` passed.

## 2026-07-01 GitHub Project Subscription

- Added `AlkaidLab/foundation-sunshine` as a public GitHub release subscription.
- Source id: `github_foundation_sunshine_releases`.
- Fetch path: GitHub Releases API, latest 5 public releases only, no token required.
- The source is included in default `tested_creator_sources` output and appears under `我的订阅`.
- The `我的订阅` section now uses all subscription items first, so non-AI GitHub releases are visible instead of being hidden by the AI relevance filter.
- Latest live fetch confirmed recent releases, not commits.
- Verification:
  - `.\.venv\Scripts\python.exe -m py_compile scripts/update_news.py` passed.
  - `node --check assets/app.js` passed.
  - Targeted unittest passed for GitHub parsing, default source scope, and source tier mapping.
  - `.\.venv\Scripts\python.exe scripts/update_news.py --output-dir data --window-hours 24 --archive-days 3650 --all-time` wrote 532 all-mode items.
  - `data/source-status.json` shows `github_foundation_sunshine_releases.ok=true` and `item_count=5`.
  - Browser at `http://127.0.0.1:8080/` confirmed release entries after selecting `我的订阅` and time range `不限`.

## 2026-07-01 Subscription Time Filter Bug Fix

- Bug: after clicking around, `我的订阅` could show only 1 item.
- Root cause: the active section was `我的订阅`, but the time range stayed at `过去 24 小时`; only one subscription item was inside that rolling 24-hour window.
- Fix: switching into `我的订阅` now automatically changes the time range to `不限` and refreshes the time control.
- Browser verification at `http://127.0.0.1:8080/`:
  - before clicking: default tab could be `热点`, time selector `24h`.
  - after clicking `我的订阅`: time selector becomes `all`, section shows the full subscription list.
  - page text includes `foundation-sunshine`; this bug fix was later followed by switching GitHub tracking from commits to releases.

## 2026-07-01 GitHub Release-Only Tracking

- User clarified that `AlkaidLab/foundation-sunshine` should track version updates only, not ordinary commits.
- Switched the GitHub subscription from the commits API to the public Releases API.
- Source id changed from the earlier commit-oriented id to `github_foundation_sunshine_releases` so old commit rows are filtered out of regenerated default data.
- Default fetch count is the latest 5 public releases, which includes the user-provided `v2026.611.71453.杂鱼` release.
- Verification:
  - `data/source-status.json` shows `github_foundation_sunshine_releases.ok=true`, `item_count=5`, and `source_kind=github_release_subscription`.
  - Current `creator_items_all` contains `v2026.611.71453.杂鱼`.
  - Current `creator_items_all` no longer contains old commit text `chore: update docs` or `move borrowed texture telemetry`.
  - Browser at `http://127.0.0.1:8080/` shows `GitHub版本订阅` and the linked release in `我的订阅`.

## 2026-07-01 Final Cleanup After User Acceptance

- User confirmed acceptance after switching GitHub tracking to releases only.
- Project cleanup synchronized `PROJECT_STATE.md` and `HANDOFF.md` as the next-round entry points.
- README and `docs/SOURCE_COVERAGE.md` already describe the release-only GitHub subscription.
- AGENTS.md was left unchanged because no new permanent AI施工 rule was introduced.
- No files or directories were deleted.
- No Git commit or push was performed.

## 2026-07-02 WeWe RSS Local Sidecar Deployment Progress

- Deployment task type: local sidecar deployment, not AI News Radar code integration.
- Sidecar path: `E:\AI-news-reader\wewe-rss-sidecar`.
- Upstream: `cooderl/wewe-rss` v2.6.1, archived/read-only on GitHub as of 2026-05-11.
- Docker was not available on this Windows machine, so the Docker Compose path was skipped.
- Local Node/pnpm path used instead:
  - `corepack pnpm@8.15.9 install --ignore-scripts --frozen-lockfile`
  - SQLite Prisma client generated from `apps/server/prisma-sqlite/schema.prisma`
  - Prisma migrate failed on this Windows/Node 24 environment with an empty schema-engine error, so the existing SQLite migration SQL files were applied directly with local `sqlite3.exe`.
  - `corepack pnpm@8.15.9 run -r build` passed.
- Runtime:
  - process id: `24144`
  - URL: `http://127.0.0.1:4000/dash`
  - host binding: `127.0.0.1` only
  - database: `E:\AI-news-reader\wewe-rss-sidecar\apps\server\data\wewe-rss.db`
  - logs: `E:\AI-news-reader\wewe-rss-sidecar\wewe-rss.out.log` and `E:\AI-news-reader\wewe-rss-sidecar\wewe-rss.err.log`
- Verification passed:
  - port `4000` is listening on `127.0.0.1`
  - `http://127.0.0.1:4000/` returned HTTP 200
  - in-app browser opened `http://127.0.0.1:4000/dash`
  - dashboard reached with `共0个订阅`, which is expected before WeChat Reading login and feed setup.
- Important UI note:
  - Because the archived frontend treats template string `'false'` as auth enabled, the dashboard may show an `AuthCode` login page even when the backend has no real `AUTH_CODE`.
  - For this local-only run, entering any local placeholder such as `local` reaches the dashboard; do not treat this as a secret.
- Next manual step:
  - User should use the visible `wewe-rss` dashboard to add a WeChat Reading account by QR scan.
  - Then add only one public account first: `猫笔刀`.
  - After that, record the real feed id / feed URL and verify `.json` or `.rss` returns recent article data.
- Still not done:
  - No WeChat Reading account has been scanned in.
  - No `猫笔刀` feed URL exists yet.
  - No AI News Radar `WEWE_RSS_*` bridge has been added.
  - No files were deleted.
  - No Git commit or push was performed.

## 2026-07-02 YouTube OPML Subscription Local Config Fix

- Task type: Bug fix.
- User symptom: latest local deployed version did not show the YouTube creator subscription.
- First-principles root cause:
  - `feeds/follow.opml` still existed and still contained the YouTube channel `UCYPT3wl0MgbOz63ho166KOw`.
  - Frontend subscription logic still recognized OPML YouTube items for `我的订阅`.
  - The break was in local runtime config: project-root `sources.config.json` had the `opmlrss` source disabled, so the one-click/local refresh did not run OPML/RSS at all.
- Fix applied:
  - Enabled the local `opmlrss` row in `sources.config.json`.
  - This file is local/private config and is ignored by Git; do not expect it to appear in `git status`.
- Verification:
  - Ran `.\.venv\Scripts\python.exe scripts\update_news.py --source-config sources.config.json --output-dir data --window-hours 24 --archive-days 3650 --all-time`.
  - `data/source-status.json`: `source_scope=configured_sources`, `rss_opml.enabled=true`, `ok_feeds=1`, `effective_feed_total=1`, `opmlrss.item_count=15`.
  - `data/latest-24h-all.json`: `creator_items_all` contains 15 `opmlrss` YouTube items.
  - `http://127.0.0.1:8080/data/latest-24h-all.json` also returns 15 `opmlrss` creator items.
  - Latest visible sample: `小岛大浪吹-非正经政经频道` / `【小岛浪吹】从阿嫲的情书到印加坡：一个华人多数国家的身份焦虑`.
  - `.\.venv\Scripts\python.exe -m py_compile scripts\update_news.py scripts\local_server.py` passed.
  - `node --check assets\app.js` passed.
  - Targeted unittest for source config OPML runtime and YouTube creator items passed.
- Current warning:
  - `data/*.json` changed because of the local refresh. They remain generated runtime data; do not commit them blindly, especially while Xiaohongshu URLs may contain platform parameters.

## 2026-07-02 Source Config Live Draft Fix

- Task type: Bug fix.
- User symptom: source config panel edits looked ineffective.
- Root cause:
  - The panel originally required a separate `保存草稿` step before the left list, enabled count, JSON preview, `写入`, or `刷新数据` could reliably reflect the latest visible form edits.
  - For a non-programmer user, changing a checkbox or field and then seeing stale JSON/list state makes the UI feel like the change did not take effect.
- Fix applied:
  - `assets/app.js` now syncs source-config form `input` and `change` events directly into the local draft.
  - Enabled count, left source list, JSON preview, and localStorage draft now update immediately while editing.
  - `index.html` app script cache-buster was updated to `source-config-live-draft-0702a`.
- Verification:
  - `node --check assets\app.js` passed.
  - `.\.venv\Scripts\python.exe -m unittest tests.test_local_server tests.test_topic_filter.TopicFilterTests.test_apply_source_config_runtime_sets_fetcher_env_without_secrets` passed: 5 tests OK.
  - Browser at `http://127.0.0.1:8080/` loaded `assets/app.js?v=source-config-live-draft-0702a`.
  - In-browser check: toggling `官方一手源包` from off to on immediately changed summary from `8/28 启用` to `9/28 启用` and JSON `official_ai_sources.enabled=true`; toggling back restored `8/28 启用`.
- Current warning:
  - The UI still requires `写入` to persist to `sources.config.json` and `刷新数据` to regenerate `data/*.json`. The fix makes the visible draft live, not an automatic background refresh.

## 2026-07-02 Source Config Deleted Built-in Sources Fix

- Task type: Bug fix.
- User symptom: unused built-in sources deleted from the source config panel reappeared after `保存草稿` -> `写入` -> `刷新数据`.
- Root cause:
  - `mergeSourceConfigWithSeed()` always merged the built-in seed source catalog back into loaded config.
  - That behavior was useful for adding newly shipped built-in sources, but it could not distinguish "missing because newly added" from "missing because the user deliberately deleted it".
- Fix applied:
  - `assets/app.js` now stores deleted built-in source ids in `deleted_source_ids`.
  - Seed merge skips ids listed in `deleted_source_ids`, so user-deleted built-in sources stay deleted after write, refresh, and reload.
  - Existing current-version configs that already omitted seed sources are backfilled into `deleted_source_ids` on load.
  - `index.html` app script cache-buster updated to `source-config-delete-tombstone-0702a`.
- Verification:
  - `node --check assets\app.js` passed.
  - `.\.venv\Scripts\python.exe -m unittest tests.test_local_server tests.test_topic_filter.TopicFilterTests.test_apply_source_config_runtime_sets_fetcher_env_without_secrets` passed: 5 tests OK.
  - Browser loaded `assets/app.js?v=source-config-delete-tombstone-0702a`.
  - Existing deleted sources `official_ai_sources` and `curated_ai_media_sources` were not re-added; they appeared in `deleted_source_ids`.
  - Browser test deleted `AI Breakfast`, clicked `写入`, reloaded, then clicked `刷新数据`; after reload it still showed 26 sources and `deleted_source_ids=[official_ai_sources, curated_ai_media_sources, aibreakfast]`.
- Current warning:
  - This removes records from local source config only. It does not delete code, files, or built-in fetcher support.
  - To restore deleted built-in sources, use `恢复当前`, import a config containing them, or add them manually again.

## 2026-07-02 Source Config Collapsible Panel UI

- Task type: UI small change.
- User request: make the source config area less visually heavy, matching the `高级筛选` click-to-open style.
- Fix applied:
  - `index.html` changed the source config section into a `<details>` panel.
  - Default collapsed row now shows only `信源配置` plus the enabled/source count.
  - Clicking the row expands the existing write/refresh/export/copy tools, source list, form, and JSON editor.
  - `assets/styles.css` reuses the visual language of the advanced filter row: compact bordered row, plus/minus circle, muted collapsed text, and content border when open.
  - `index.html` app script cache-buster updated to `source-config-collapsible-0702a`.
- Verification:
  - Browser at `http://127.0.0.1:8080/` loaded `assets/app.js?v=source-config-collapsible-0702a`.
  - Default state is collapsed: panel height about one row and summary text `信源配置 9/16 启用`.
  - Clicking the row opens the panel; browser check confirmed `open=true`, 16 config rows, and tools `写入 刷新数据 导出 复制`.
- Current warning:
  - This is a presentation change only. It does not change how writing, refreshing, deleting, or source fetching works.

## 2026-07-02 Source Config Channel Merge For Bilibili

- Task type: Small feature / config UI cleanup.
- User request: multiple Bilibili UP hosts should be represented as one Bilibili channel source, because the same channel may track many creators later.
- Fix applied:
  - `assets/app.js` seed config now uses one `bilibili_dynamic_sources` record instead of separate Bilibili records per UP host.
  - Existing local configs with legacy `bilibili_*` rows are automatically merged into that one record on load.
  - The merged record stores UID values in `locator` as comma-separated values and UP names in `target` as comma-separated values.
  - `index.html` app script cache-buster updated to `source-config-channel-merge-0702a`.
  - `tests/test_topic_filter.py` now verifies the merged Bilibili config still sets runtime env correctly.
- Verification:
  - Browser at `http://127.0.0.1:8080/` showed only one `B站动态` row in the source config list.
  - JSON contained one `bilibili_dynamic_sources` record with `locator=505301413,316183842` and `target=Koji杨远骋at十字路口,技术爬爬虾`.
  - Clicking the row showed the same merged values in the form.
- Current warning:
  - This merge is implemented for Bilibili first. Other same-channel sources such as Douyin/Xiaohongshu can be grouped in a follow-up using the same pattern.

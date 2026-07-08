# Refresh Playbooks

> 操作手册从 `PROJECT_STATE.md` 迁出；项目最新状态见根目录 `PROJECT_STATE.md`。

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

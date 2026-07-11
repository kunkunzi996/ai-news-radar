from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

from scripts.radar.fetchers.subscriptions import (
    fetch_we_mp_rss_jsonl_subscription,
    parse_we_mp_rss_jsonl_items,
)


NOW = datetime(2026, 7, 11, 8, 0, tzinfo=timezone.utc)


def test_exporter_supports_direct_script_execution() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    result = subprocess.run(
        [sys.executable, str(repo_root / "scripts" / "export_we_mp_rss_jsonl.py"), "--help"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def jsonl_line(**overrides: str) -> str:
    payload = {
        "title": "\u6d4b\u8bd5\u6587\u7ae0",
        "url": "https://mp.weixin.qq.com/s/example",
        "published_at": "2026-07-11T04:36:07+00:00",
        "account": "\u732b\u7b14\u5200",
        "feed_id": "MP_WXS_3198966508",
        "summary": "\u516c\u5f00\u6458\u8981",
    }
    payload.update(overrides)
    return json.dumps(payload, ensure_ascii=False)


def test_parse_we_mp_rss_jsonl_maps_public_fields() -> None:
    items = parse_we_mp_rss_jsonl_items(jsonl_line(), NOW, max_items=20)

    assert len(items) == 1
    item = items[0]
    assert item.site_id == "we_mp_rss_jsonl"
    assert item.site_name == "WeRSS \u516c\u4f17\u53f7"
    assert item.source == "\u732b\u7b14\u5200"
    assert item.published_at == datetime(2026, 7, 11, 4, 36, 7, tzinfo=timezone.utc)
    assert item.meta == {
        "summary": "\u516c\u5f00\u6458\u8981",
        "we_mp_feed_id": "MP_WXS_3198966508",
        "source_kind": "we_mp_rss_wechat_subscription",
        "search_surface": "we_mp_rss_jsonl_bridge",
    }


def test_parse_we_mp_rss_jsonl_skips_bad_lines_and_deduplicates_urls() -> None:
    text = "\n".join(["{bad", jsonl_line(), jsonl_line(title="duplicate")])

    items = parse_we_mp_rss_jsonl_items(text, NOW, max_items=20)

    assert [item.title for item in items] == ["\u6d4b\u8bd5\u6587\u7ae0"]


def test_parse_we_mp_rss_jsonl_truncates_to_max_items() -> None:
    text = "\n".join(
        jsonl_line(title=f"article {index}", url=f"https://mp.weixin.qq.com/s/{index}")
        for index in range(3)
    )

    items = parse_we_mp_rss_jsonl_items(text, NOW, max_items=2)

    assert [item.title for item in items] == ["article 0", "article 1"]


def test_fetch_we_mp_rss_jsonl_reports_missing_file(tmp_path) -> None:
    items, status = fetch_we_mp_rss_jsonl_subscription(requests.Session(), NOW, jsonl_dir=str(tmp_path))

    assert items == []
    assert status["ok"] is False
    assert status["error"] == "missing_we_mp_rss_jsonl"


def test_fetch_we_mp_rss_jsonl_default_limit_keeps_multi_account_rows(tmp_path) -> None:
    # 模拟两个公众号共 40 行的桥接文件：默认上限必须一条不截。
    lines = []
    for account, count in (("数字生命卡兹克", 20), ("猫笔刀", 20)):
        for idx in range(count):
            lines.append(
                json.dumps(
                    {
                        "title": f"{account} 文章 {idx}",
                        "url": f"https://mp.weixin.qq.com/s/{account}-{idx}",
                        "published_at": "2026-07-10T08:00:00+00:00",
                        "account": account,
                        "feed_id": account,
                        "summary": "",
                    },
                    ensure_ascii=False,
                )
            )
    jsonl_path = tmp_path / "wechat_contents_latest.jsonl"
    jsonl_path.write_text("\n".join(lines), encoding="utf-8")

    items, status = fetch_we_mp_rss_jsonl_subscription(requests.Session(), NOW, jsonl_dir=str(tmp_path))

    assert status["ok"] is True
    assert len(items) == 40
    accounts = {item.source for item in items}
    assert accounts == {"数字生命卡兹克", "猫笔刀"}


def test_fetch_we_mp_rss_jsonl_accepts_empty_file(tmp_path) -> None:
    (tmp_path / "wechat_contents_latest.jsonl").write_text("", encoding="utf-8")

    items, status = fetch_we_mp_rss_jsonl_subscription(requests.Session(), NOW, jsonl_dir=str(tmp_path))

    assert items == []
    assert status["ok"] is True
    assert status["item_count"] == 0

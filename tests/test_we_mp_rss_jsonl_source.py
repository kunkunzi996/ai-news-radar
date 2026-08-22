from __future__ import annotations

import json
import hashlib
import http.server
import os
import shutil
import socketserver
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

import scripts.radar.fetchers.subscriptions as subscription_module

from scripts.radar.fetchers.subscriptions import (
    fetch_we_mp_rss_jsonl_subscription,
    parse_we_mp_rss_jsonl_items,
)
from scripts.radar.cli import apply_we_mp_subscription_cleanup


NOW = datetime(2026, 7, 11, 8, 0, tzinfo=timezone.utc)


def authority_payload(*, complete: bool = True, feeds: list[dict] | None = None) -> dict:
    feed_rows = feeds if feeds is not None else [
        {"feed_id": "active-id", "account": "启用号", "status": 1, "active": True},
        {"feed_id": "paused-id", "account": "停用号", "status": 0, "active": False},
    ]
    return {
        "schema_version": 1,
        "generated_at": "2026-07-16T00:00:00+00:00",
        "complete": complete,
        "reason": None if complete else "sync_skipped",
        "authority_source": "sidecar_db_feed_table",
        "retention_policy": "feed_row_exists",
        "active_policy": "status_1_excluding_featured_v1",
        "known_count": len(feed_rows),
        "active_count": sum(1 for feed in feed_rows if feed["active"]),
        "feeds": feed_rows,
    }


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


def test_missing_feed_id_is_rejected_before_raw_item(tmp_path) -> None:
    (tmp_path / "wechat_contents_latest.jsonl").write_text(
        "\n".join([jsonl_line(), jsonl_line(url="https://mp.weixin.qq.com/s/bad", feed_id="")]),
        encoding="utf-8",
    )

    items, status = fetch_we_mp_rss_jsonl_subscription(
        requests.Session(),
        NOW,
        jsonl_dir=str(tmp_path),
    )

    assert [item.url for item in items] == ["https://mp.weixin.qq.com/s/example"]
    assert status["ok"] is False
    assert status["error"] == "invalid_we_mp_rss_jsonl"
    assert status["rejected_rows"] == 1
    assert status["rejected_row_details"][0]["line"] == 2


def test_schema_two_manifest_rejects_path_escape(tmp_path) -> None:
    bridge_root = tmp_path / "bridge"
    bridge_root.mkdir()
    (bridge_root / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "article_file": "../outside.jsonl",
                "article_sha256": "0" * 64,
                "subscription_file": "output/wechat/jsonl/wechat_subscriptions_latest.json",
                "subscription_sha256": "0" * 64,
                "output_rows": 0,
                "known_feed_count": 0,
                "active_feed_count": 0,
                "max_items": 20,
            }
        ),
        encoding="utf-8",
    )

    fetch = getattr(subscription_module, "fetch_we_mp_rss_jsonl_subscription")
    items, status = fetch(
        requests.Session(),
        NOW,
        bridge_root=str(bridge_root),
    )

    assert items == []
    assert status["ok"] is False
    assert status["error"] == "invalid_we_mp_rss_manifest_path"


def test_schema_two_manifest_rejects_symlink_escape_when_supported(tmp_path) -> None:
    bridge = tmp_path / "bridge"
    bridge.mkdir()
    outside = tmp_path / "outside.jsonl"
    outside.write_text("", encoding="utf-8")
    link = bridge / "linked.jsonl"
    try:
        link.symlink_to(outside)
    except OSError:
        return
    (bridge / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "article_file": "linked.jsonl",
                "article_sha256": hashlib.sha256(outside.read_bytes()).hexdigest(),
                "subscription_file": "linked.jsonl",
                "subscription_sha256": hashlib.sha256(outside.read_bytes()).hexdigest(),
                "output_rows": 0,
                "known_feed_count": 0,
                "active_feed_count": 0,
            }
        ),
        encoding="utf-8",
    )
    items, status = fetch_we_mp_rss_jsonl_subscription(requests.Session(), NOW, bridge_root=str(bridge))
    assert items == []
    assert status["error"] == "invalid_we_mp_rss_manifest_path"


def write_schema_two_bridge(tmp_path: Path, lines: list[str], *, complete: bool = True) -> Path:
    bridge = tmp_path / "bridge"
    data_dir = bridge / "output" / "wechat" / "jsonl"
    data_dir.mkdir(parents=True)
    article = data_dir / "wechat_contents_latest.jsonl"
    article.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8", newline="\n")
    article_hash = hashlib.sha256(article.read_bytes()).hexdigest()
    snapshot = authority_payload(complete=complete)
    snapshot.update({"source_jsonl_sha256": article_hash, "empty_confirmations": 0})
    snapshot_path = data_dir / "wechat_subscriptions_latest.json"
    snapshot_path.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8", newline="\n")
    manifest = {
        "schema_version": 2,
        "article_file": "output/wechat/jsonl/wechat_contents_latest.jsonl",
        "article_sha256": article_hash,
        "subscription_file": "output/wechat/jsonl/wechat_subscriptions_latest.json",
        "subscription_sha256": hashlib.sha256(snapshot_path.read_bytes()).hexdigest(),
        "output_rows": len(lines),
        "known_feed_count": 2,
        "active_feed_count": 1,
        "max_items": 200,
    }
    (bridge / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8", newline="\n")
    return bridge


def test_schema_two_validates_full_chain_and_preserves_paused_known_feed(tmp_path) -> None:
    bridge = write_schema_two_bridge(tmp_path, [jsonl_line(feed_id="active-id", account="启用号")])
    items, status = fetch_we_mp_rss_jsonl_subscription(requests.Session(), NOW, bridge_root=str(bridge))

    assert status["ok"] is True
    assert status["cleanup_capable"] is True
    assert status["known_feed_ids"] == ["active-id", "paused-id"]
    assert status["active_feed_ids"] == ["active-id"]
    assert [item.meta["we_mp_feed_id"] for item in items] == ["active-id"]


def test_schema_two_binds_cleanup_to_actual_git_checkout_head(tmp_path) -> None:
    bridge = write_schema_two_bridge(tmp_path, [jsonl_line(feed_id="active-id", account="启用号")])
    subprocess.run(["git", "init", "-b", "main"], cwd=bridge, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=bridge, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=bridge, check=True)
    subprocess.run(["git", "add", "."], cwd=bridge, check=True)
    subprocess.run(["git", "commit", "-m", "桥接契约"], cwd=bridge, check=True, capture_output=True)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=bridge, text=True).strip()
    items, status = fetch_we_mp_rss_jsonl_subscription(requests.Session(), NOW, bridge_root=str(bridge))
    assert items
    assert status["bridge_commit"] == head
    archive = {
        "kept": {"id": "kept", "site_id": "we_mp_rss_jsonl", "source": "启用号", "we_mp_feed_id": "active-id"},
        "deleted": {"id": "deleted", "site_id": "we_mp_rss_jsonl", "source": "旧号", "we_mp_feed_id": "old-id"},
    }
    matching = dict(status)
    result = apply_we_mp_subscription_cleanup(
        archive, matching, channel_enabled=True, mode="on", expected_bridge_commit=head
    )
    assert set(result) == {"kept"}
    forged = dict(status)
    result = apply_we_mp_subscription_cleanup(
        archive, forged, channel_enabled=True, mode="on", expected_bridge_commit="0" * 40
    )
    assert result is archive
    assert "bridge_commit_not_bound" in forged["subscription_cleanup"]["skip_reasons"]


def test_non_git_schema_two_is_readable_but_not_commit_bound(tmp_path) -> None:
    bridge = write_schema_two_bridge(tmp_path, [jsonl_line(feed_id="active-id", account="启用号")])
    items, status = fetch_we_mp_rss_jsonl_subscription(requests.Session(), NOW, bridge_root=str(bridge))
    assert items and status["ok"] is True
    assert status["bridge_commit"] is None


def test_schema_two_scans_bad_tail_beyond_item_limit_before_raw_item(tmp_path) -> None:
    bridge = write_schema_two_bridge(
        tmp_path,
        [
            jsonl_line(feed_id="active-id", account="启用号"),
            jsonl_line(feed_id="", account="启用号", url="https://mp.weixin.qq.com/s/bad-tail"),
        ],
    )
    items, status = fetch_we_mp_rss_jsonl_subscription(
        requests.Session(), NOW, bridge_root=str(bridge), max_items=1
    )

    assert len(items) == 1
    assert status["ok"] is False
    assert status["cleanup_capable"] is False
    assert status["rejected_row_details"][0]["line"] == 2


def test_schema_two_rejects_hash_mismatch_and_incomplete_snapshot(tmp_path) -> None:
    bridge = write_schema_two_bridge(tmp_path, [jsonl_line(feed_id="active-id", account="启用号")])
    manifest_path = bridge / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["article_sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    items, status = fetch_we_mp_rss_jsonl_subscription(requests.Session(), NOW, bridge_root=str(bridge))
    assert items == []
    assert status["error"] == "we_mp_rss_manifest_hash_mismatch"

    incomplete = write_schema_two_bridge(tmp_path / "other", [jsonl_line(feed_id="active-id", account="启用号")], complete=False)
    items, status = fetch_we_mp_rss_jsonl_subscription(requests.Session(), NOW, bridge_root=str(incomplete))
    assert len(items) == 1
    assert status["ok"] is True
    assert status["cleanup_capable"] is False
    assert status["cleanup_contract_reason"] == "snapshot_incomplete"


def test_snapshot_nonempty_known_requires_zero_empty_confirmations(tmp_path) -> None:
    bridge = write_schema_two_bridge(tmp_path, [jsonl_line(feed_id="active-id", account="启用号")])
    snapshot_path = bridge / "output" / "wechat" / "jsonl" / "wechat_subscriptions_latest.json"
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    snapshot["empty_confirmations"] = 1
    snapshot_path.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
    manifest_path = bridge / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["subscription_sha256"] = hashlib.sha256(snapshot_path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    items, status = fetch_we_mp_rss_jsonl_subscription(requests.Session(), NOW, bridge_root=str(bridge))
    assert items == []
    assert status["ok"] is False
    assert status["error"] == "invalid_we_mp_rss_snapshot"


def test_workflow_emits_commit_only_from_wechat_bridge_step() -> None:
    workflow = (Path(__file__).resolve().parent.parent / ".github" / "workflows" / "update-news.yml").read_text(encoding="utf-8")
    douyin, remainder = workflow.split("      - name: Fetch WeChat bridge JSONL", 1)
    wechat, _update = remainder.split("      - name: Update data", 1)
    assert "commit=$(git" not in douyin
    assert 'echo "commit=$(git -C "$bridge_dir" rev-parse HEAD)" >> "$GITHUB_OUTPUT"' in wechat


def test_schema_one_remains_article_readable_but_cleanup_incapable(tmp_path) -> None:
    bridge = tmp_path / "bridge"
    data_dir = bridge / "output" / "wechat" / "jsonl"
    data_dir.mkdir(parents=True)
    (data_dir / "wechat_contents_latest.jsonl").write_text(jsonl_line() + "\n", encoding="utf-8")
    (bridge / "manifest.json").write_text(json.dumps({"schema_version": 1}), encoding="utf-8")
    items, status = fetch_we_mp_rss_jsonl_subscription(requests.Session(), NOW, bridge_root=str(bridge))
    assert len(items) == 1
    assert status["ok"] is True
    assert status["cleanup_capable"] is False

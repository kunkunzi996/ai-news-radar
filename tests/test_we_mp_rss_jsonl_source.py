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
import scripts.export_we_mp_rss_jsonl as exporter_module

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


def test_exporter_uses_only_authoritative_active_feeds(monkeypatch) -> None:
    monkeypatch.setenv("WE_MP_RSS_FEEDS", "env-id:环境变量不应生效")
    active_configs = getattr(exporter_module, "active_feed_configs")(authority_payload())

    assert active_configs == [{"id": "active-id", "name": "启用号"}]


def test_subscription_snapshot_preserves_known_paused_feed() -> None:
    snapshot = getattr(exporter_module, "build_subscription_snapshot")(
        authority_payload(),
        source_jsonl_sha256="a" * 64,
        previous_snapshot=None,
        generated_at="2026-07-16T01:00:00Z",
    )

    assert snapshot["complete"] is True
    assert snapshot["known_count"] == 2
    assert snapshot["active_count"] == 1
    assert next(feed for feed in snapshot["feeds"] if feed["feed_id"] == "paused-id")["active"] is False
    assert snapshot["source_jsonl_sha256"] == "a" * 64


def test_empty_confirmation_is_capped_at_two() -> None:
    empty = authority_payload(feeds=[])
    previous = {"known_count": 0, "empty_confirmations": 2}

    snapshot = getattr(exporter_module, "build_subscription_snapshot")(
        empty,
        source_jsonl_sha256="b" * 64,
        previous_snapshot=previous,
        generated_at="2026-07-16T01:00:00Z",
    )

    assert snapshot["empty_confirmations"] == 2


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


def test_powershell_bridge_transaction_semantics(tmp_path) -> None:
    repo_root = Path(__file__).resolve().parent.parent
    radar_root = tmp_path / "fake-radar"
    sidecar_root = tmp_path / "fake-sidecar"
    bridge_root = tmp_path / "bridge"
    bare_root = tmp_path / "bridge.git"
    for path in (
        radar_root / "scripts",
        radar_root / "deploy" / "local",
        sidecar_root,
        bridge_root / "output" / "wechat" / "jsonl",
    ):
        path.mkdir(parents=True, exist_ok=True)

    source_venv = Path(sys.executable).resolve().parent.parent
    for root in (radar_root, sidecar_root):
        scripts_dir = root / ".venv" / "Scripts"
        scripts_dir.mkdir(parents=True)
        shutil.copy2(sys.executable, scripts_dir / "python.exe")
        shutil.copy2(source_venv / "pyvenv.cfg", root / ".venv" / "pyvenv.cfg")
    (sidecar_root / "start-we-mp-rss.ps1").write_text("exit 0\n", encoding="utf-8")

    fake_sync = r'''
import argparse, json, time
from pathlib import Path
p=argparse.ArgumentParser(); p.add_argument("--subscriptions-out", required=True); p.add_argument("--snapshot-only", action="store_true")
a=p.parse_args(); root=Path(__file__).resolve().parents[2]; scenario=json.loads((root/"scenario.json").read_text(encoding="utf-8"))
time.sleep(float(scenario.get("sync_delay_seconds", 0)))
payload=dict(scenario["authority"]); payload["generated_at"]=scenario["generated_at"]
if a.snapshot_only: payload.update({"complete":False,"reason":"sync_skipped"})
Path(a.subscriptions_out).write_text(json.dumps(payload,ensure_ascii=False),encoding="utf-8")
for line in scenario.get("sync_output", ["[sync] 完成：成功 1 个 / 失败 0 个 / 新增 0 条"]): print(line, flush=True)
raise SystemExit(int(scenario.get("sync_exit", 0)))
'''.strip() + "\n"
    (radar_root / "deploy" / "local" / "we_mp_rss_sync_once.py").write_text(fake_sync, encoding="utf-8")

    fake_export = r'''
import argparse, hashlib, json
from pathlib import Path
p=argparse.ArgumentParser(); p.add_argument("--base-url"); p.add_argument("--subscriptions-in",required=True); p.add_argument("--out",required=True); p.add_argument("--snapshot-out",required=True); p.add_argument("--previous-snapshot",default=""); p.add_argument("--max-items")
a=p.parse_args(); root=Path(__file__).resolve().parents[1]; scenario=json.loads((root/"scenario.json").read_text(encoding="utf-8")); authority=json.loads(Path(a.subscriptions_in).read_text(encoding="utf-8"))
article=(scenario["jsonl"].rstrip("\n")+"\n").encode(); Path(a.out).write_bytes(article)
previous={}
if a.previous_snapshot and Path(a.previous_snapshot).is_file(): previous=json.loads(Path(a.previous_snapshot).read_text(encoding="utf-8"))
known=int(authority["known_count"]); empty=min(2,(int(previous.get("empty_confirmations",0))+1)) if known==0 and int(previous.get("known_count",-1))==0 else (1 if known==0 else 0)
snapshot={"schema_version":1,"generated_at":scenario["generated_at"],"complete":authority["complete"],"reason":authority.get("reason"),"authority_source":authority["authority_source"],"retention_policy":authority["retention_policy"],"active_policy":authority["active_policy"],"source_jsonl_sha256":hashlib.sha256(article).hexdigest(),"known_count":known,"active_count":authority["active_count"],"empty_confirmations":empty,"feeds":authority["feeds"]}
Path(a.snapshot_out).write_text(json.dumps(snapshot,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
'''.strip() + "\n"
    (radar_root / "scripts" / "export_we_mp_rss_jsonl.py").write_text(fake_export, encoding="utf-8")

    active = {"feed_id": "active-id", "account": "启用号", "status": 1, "active": True}
    paused = {"feed_id": "paused-id", "account": "停用号", "status": 0, "active": False}
    article_line = jsonl_line(feed_id="active-id", account="启用号")

    def write_scenario(
        generated_at: str,
        feeds: list[dict],
        *,
        sync_output: list[str] | None = None,
        sync_exit: int = 0,
        sync_delay_seconds: float = 0,
    ) -> None:
        payload = authority_payload(feeds=feeds)
        (radar_root / "scenario.json").write_text(
            json.dumps(
                {
                    "generated_at": generated_at,
                    "authority": payload,
                    "jsonl": article_line,
                    "sync_output": sync_output
                    if sync_output is not None
                    else ["[sync] 完成：成功 1 个 / 失败 0 个 / 新增 0 条"],
                    "sync_exit": sync_exit,
                    "sync_delay_seconds": sync_delay_seconds,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    def git(*args: str, cwd: Path = bridge_root) -> str:
        result = subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, text=True,
            encoding="utf-8", errors="replace", check=True,
        )
        return result.stdout.strip()

    subprocess.run(["git", "init", "--bare", "--initial-branch=main", str(bare_root)], check=True, capture_output=True)
    git("init", "-b", "main")
    git("config", "user.name", "test")
    git("config", "user.email", "test@example.com")
    article_path = bridge_root / "output" / "wechat" / "jsonl" / "wechat_contents_latest.jsonl"
    # 真实 bridge exporter 契约是 UTF-8 + 纯 LF；显式 bytes 避免 Windows text mode 改成 CRLF。
    article_path.write_bytes((article_line + "\n").encode("utf-8"))
    (bridge_root / "manifest.json").write_text(json.dumps({"schema_version": 1}), encoding="utf-8")
    git("add", ".")
    git("commit", "-m", "初始桥接")
    git("remote", "add", "origin", str(bare_root))
    git("push", "-u", "origin", "main")

    class QuietHandler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *_args) -> None:
            pass

    server = socketserver.TCPServer(("127.0.0.1", 0), QuietHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    script = repo_root / "deploy" / "local" / "collect-wechat-and-push.ps1"

    def build_bridge_command(
        *extra: str,
        fail_after_replace: int = 0,
        fail_git_add: bool = False,
    ) -> tuple[list[str], dict[str, str]]:
        env = os.environ.copy()
        if fail_after_replace or fail_git_add:
            env["WE_MP_RSS_ENABLE_TEST_FAILURES"] = "1"
        if fail_after_replace:
            env["WE_MP_RSS_TEST_FAIL_AFTER_REPLACE"] = str(fail_after_replace)
        if fail_git_add:
            env["WE_MP_RSS_TEST_FAIL_GIT_ADD"] = "1"
        return (
            [
                "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script),
                "-RadarRoot", str(radar_root), "-SidecarRoot", str(sidecar_root),
                "-BridgeRoot", str(bridge_root), "-BaseUrl", base_url, *extra,
            ],
            env,
        )

    def run_bridge(
        *extra: str,
        fail_after_replace: int = 0,
        fail_git_add: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        command, env = build_bridge_command(
            *extra,
            fail_after_replace=fail_after_replace,
            fail_git_add=fail_git_add,
        )
        return subprocess.run(
            command,
            capture_output=True, text=True, encoding="utf-8", errors="replace", check=False, env=env,
        )

    try:
        precheck_status_path = tmp_path / "precheck-status.json"
        write_scenario("2026-07-16T00:30:00Z", [active, paused], sync_delay_seconds=2)
        precheck_command, precheck_env = build_bridge_command(
            "-SkipSync", "-StatusFile", str(precheck_status_path)
        )
        precheck = subprocess.Popen(
            precheck_command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=precheck_env,
        )
        try:
            initial_status = None
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                if precheck_status_path.is_file():
                    try:
                        candidate = json.loads(precheck_status_path.read_text(encoding="utf-8-sig"))
                    except json.JSONDecodeError:
                        candidate = None
                    if candidate and candidate.get("stage") == "fetching":
                        initial_status = candidate
                        break
                time.sleep(0.05)
            stdout, stderr = precheck.communicate(timeout=15)
            assert initial_status is not None, stdout + stderr
            assert initial_status["login_state"] == "not_checked"
            assert initial_status["failed_creator_count"] == 0
            assert precheck.returncode == 1, stdout + stderr
        finally:
            if precheck.poll() is None:
                precheck.kill()
                precheck.communicate()

        write_scenario("2026-07-16T01:00:00Z", [active, paused])
        initial_head = git("rev-parse", "HEAD")
        initial_hashes = {
            path: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (article_path, bridge_root / "manifest.json")
        }
        injected_failure = run_bridge(fail_after_replace=2)
        assert injected_failure.returncode == 1
        assert git("rev-parse", "HEAD") == initial_head
        assert git("status", "--porcelain") == ""
        assert not (bridge_root / "output" / "wechat" / "jsonl" / "wechat_subscriptions_latest.json").exists()
        assert initial_hashes == {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in initial_hashes}

        add_failure = run_bridge(fail_git_add=True)
        assert add_failure.returncode == 1
        assert git("rev-parse", "HEAD") == initial_head
        assert git("status", "--porcelain") == ""
        assert not (bridge_root / "output" / "wechat" / "jsonl" / "wechat_subscriptions_latest.json").exists()
        assert initial_hashes == {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in initial_hashes}

        valid_status_path = tmp_path / "valid-status.json"
        first = run_bridge("-StatusFile", str(valid_status_path))
        assert first.returncode == 0, first.stdout + first.stderr
        valid_status = json.loads(valid_status_path.read_text(encoding="utf-8-sig"))
        assert valid_status["login_state"] == "valid"
        assert valid_status["failed_creator_count"] == 0
        head_one = git("rev-parse", "HEAD")

        write_scenario("2026-07-16T02:00:00Z", [paused, active])
        unchanged = run_bridge()
        assert unchanged.returncode == 0, unchanged.stdout + unchanged.stderr
        assert git("rev-parse", "HEAD") == head_one

        snapshot_path = bridge_root / "output" / "wechat" / "jsonl" / "wechat_subscriptions_latest.json"
        snapshot_bytes_before_manifest_only = snapshot_path.read_bytes()
        manifest_only = run_bridge("-MaxItems", "25")
        assert manifest_only.returncode == 0, manifest_only.stdout + manifest_only.stderr
        head_manifest = git("rev-parse", "HEAD")
        assert head_manifest != head_one
        assert snapshot_path.read_bytes() == snapshot_bytes_before_manifest_only
        manifest_after_max_items = json.loads((bridge_root / "manifest.json").read_text(encoding="utf-8-sig"))
        assert manifest_after_max_items["max_items"] == 25
        assert hashlib.sha256(snapshot_path.read_bytes()).hexdigest() == manifest_after_max_items["subscription_sha256"]

        write_scenario("2026-07-16T03:00:00Z", [active])
        snapshot_only = run_bridge("-MaxItems", "25")
        assert snapshot_only.returncode == 0, snapshot_only.stdout + snapshot_only.stderr
        head_two = git("rev-parse", "HEAD")
        assert head_two != head_manifest

        manifest = json.loads((bridge_root / "manifest.json").read_text(encoding="utf-8-sig"))
        snapshot_path = bridge_root / manifest["subscription_file"]
        published_article = bridge_root / manifest["article_file"]
        assert manifest["schema_version"] == 2
        assert hashlib.sha256(published_article.read_bytes()).hexdigest() == manifest["article_sha256"]
        assert hashlib.sha256(snapshot_path.read_bytes()).hexdigest() == manifest["subscription_sha256"]
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8-sig"))
        assert snapshot["source_jsonl_sha256"] == manifest["article_sha256"]
        assert snapshot["known_count"] == 1

        login_expiry_markers = [
            "Invalid Session",
            "session invalid",
            "session expired",
            "登录过期",
            "凭证失效",
        ]
        for index, marker in enumerate(login_expiry_markers):
            status_path = tmp_path / f"expired-status-{index}.json"
            write_scenario(
                f"2026-07-16T04:0{index}:00Z",
                [active],
                sync_output=[f"[sync] FAIL 公众号A {marker}"],
                sync_exit=1,
            )
            expired = run_bridge("-StatusFile", str(status_path))
            assert expired.returncode == 1, expired.stdout + expired.stderr
            expired_status = json.loads(status_path.read_text(encoding="utf-8-sig"))
            assert expired_status["login_state"] == "expired"
            assert expired_status["failed_creator_count"] == 1
            assert git("rev-parse", "HEAD") == head_two

        unknown_status_path = tmp_path / "unknown-status.json"
        write_scenario(
            "2026-07-16T04:30:00Z",
            [active],
            sync_output=["[sync] FAIL 公众号A RuntimeError: transport failed"],
            sync_exit=2,
        )
        unknown = run_bridge("-StatusFile", str(unknown_status_path))
        assert unknown.returncode == 1, unknown.stdout + unknown.stderr
        unknown_status = json.loads(unknown_status_path.read_text(encoding="utf-8-sig"))
        assert unknown_status["login_state"] == "unknown"
        assert unknown_status["failed_creator_count"] == 1
        assert git("rev-parse", "HEAD") == head_two

        unparsable_status_path = tmp_path / "unparsable-status.json"
        write_scenario(
            "2026-07-16T05:00:00Z",
            [active],
            sync_output=["sidecar output did not include a sync line"],
        )
        unparsable = run_bridge("-StatusFile", str(unparsable_status_path))
        assert unparsable.returncode == 0, unparsable.stdout + unparsable.stderr
        unparsable_status = json.loads(unparsable_status_path.read_text(encoding="utf-8-sig"))
        assert unparsable_status["state"] == "succeeded"
        assert unparsable_status["login_state"] == "unknown"
        assert unparsable_status["failed_creator_count"] == 0

        formal_hashes = {
            path: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (published_article, snapshot_path, bridge_root / "manifest.json")
        }
        head_before_skip = git("rev-parse", "HEAD")
        skipped = run_bridge("-SkipSync")
        assert skipped.returncode == 1
        assert git("rev-parse", "HEAD") == head_before_skip
        assert formal_hashes == {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in formal_hashes}
    finally:
        server.shutdown()
        server.server_close()

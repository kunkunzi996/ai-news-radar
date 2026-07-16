import json
import sys
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "deploy" / "local"))

from we_mp_rss_sync_once import (  # noqa: E402
    EXIT_ALL_FAILED,
    EXIT_ALL_OK,
    EXIT_PARTIAL_FAILED,
    exit_code_for,
    sync_feeds,
)

import we_mp_rss_sync_once as sync_module  # noqa: E402


def _feed(name: str) -> SimpleNamespace:
    return SimpleNamespace(id=f"MP_{name}", mp_name=name, faker_id=f"faker_{name}")


def _db_feed(
    feed_id: str,
    account: str,
    *,
    status: int,
    faker_id: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=feed_id,
        mp_name=account,
        status=status,
        faker_id=faker_id or f"faker_{feed_id}",
    )


class _FakeGather:
    def __init__(self, new_count: int = 0, raises: Exception | None = None) -> None:
        self._new_count = new_count
        self._raises = raises
        self.calls: list[dict] = []

    def get_Articles(self, faker_id, **kwargs):
        if self._raises:
            raise self._raises
        self.calls.append({"faker_id": faker_id, **kwargs})

    def all_count(self) -> int:
        return self._new_count


def test_sync_feeds_counts_new_articles():
    gathers = [_FakeGather(new_count=2), _FakeGather(new_count=0)]
    ok, failed, total = sync_feeds(
        [_feed("猫笔刀"), _feed("卡兹克")],
        gather_factory=lambda: gathers.pop(0),
        update_article=lambda *a, **k: None,
    )
    assert (ok, failed, total) == (2, 0, 2)


def test_sync_feeds_keeps_going_when_one_feed_fails():
    """单个号抓失败，其它号必须照抓 —— 这是本次改动的核心容错分支。"""
    gathers = [_FakeGather(raises=RuntimeError("wechat blocked")), _FakeGather(new_count=3)]
    ok, failed, total = sync_feeds(
        [_feed("猫笔刀"), _feed("卡兹克")],
        gather_factory=lambda: gathers.pop(0),
        update_article=lambda *a, **k: None,
    )
    assert (ok, failed, total) == (1, 1, 3)


def test_sync_feeds_passes_max_page_one():
    """MaxPage 必须是 1，与 sidecar 官方定时任务一致，避免触发微信风控。"""
    gather = _FakeGather(new_count=1)
    sync_feeds(
        [_feed("猫笔刀")],
        gather_factory=lambda: gather,
        update_article=lambda *a, **k: None,
    )
    assert gather.calls[0]["MaxPage"] == 1


def test_sync_feeds_handles_empty_list():
    ok, failed, total = sync_feeds(
        [],
        gather_factory=lambda: _FakeGather(),
        update_article=lambda *a, **k: None,
    )
    assert (ok, failed, total) == (0, 0, 0)


def test_sync_feeds_prints_failed_account_name(capsys):
    """失败行必须是 '[sync] FAIL <公众号名>' 格式 —— ps1 靠这个前缀捞名字去红字点名。"""
    sync_feeds(
        [_feed("猫笔刀")],
        gather_factory=lambda: _FakeGather(raises=RuntimeError("boom")),
        update_article=lambda *a, **k: None,
    )
    out = capsys.readouterr().out
    assert "[sync] FAIL 猫笔刀" in out


@pytest.mark.parametrize(
    "ok_count, failed_count, expected",
    [
        (3, 0, EXIT_ALL_OK),           # 全成功
        (0, 3, EXIT_ALL_FAILED),       # 全挂（凭证过期 / sidecar 挂了）
        (2, 1, EXIT_PARTIAL_FAILED),   # 只挂一个 —— 必须非 0，这是本次 bug 的翻车姿势
        (0, 0, EXIT_ALL_OK),           # 没有订阅的号
    ],
)
def test_exit_code_for(ok_count, failed_count, expected):
    assert exit_code_for(ok_count, failed_count) == expected


def test_partial_failure_is_not_silent():
    """守住核心诉求：部分失败绝不能返回 0（返回 0 就意味着用户收不到任何提示）。"""
    assert exit_code_for(2, 1) != EXIT_ALL_OK


def test_authority_keeps_status_zero_known_but_not_active():
    derive = getattr(sync_module, "derive_authoritative_feeds")
    featured = _db_feed(
        "featured",
        "精选文章",
        status=1,
        faker_id="MP_WXS_FEATURED_ARTICLES",
    )

    authority = derive(
        [
            _db_feed("active-a", "启用A", status=1),
            _db_feed("paused", "停用号", status=0),
            featured,
            _db_feed("active-b", "启用B", status=1),
        ]
    )

    assert {feed["feed_id"] for feed in authority["feeds"]} == {
        "active-a",
        "paused",
        "active-b",
    }
    assert {feed["feed_id"] for feed in authority["feeds"] if feed["active"]} == {
        "active-a",
        "active-b",
    }
    assert next(feed for feed in authority["feeds"] if feed["feed_id"] == "paused") == {
        "feed_id": "paused",
        "account": "停用号",
        "status": 0,
        "active": False,
    }


def test_derived_active_ids_match_sidecar_get_all_mps_contract():
    derive = getattr(sync_module, "derive_authoritative_feeds")
    rows = [
        _db_feed("active-a", "启用A", status=1),
        _db_feed("paused", "停用号", status=0),
        _db_feed(
            "featured",
            "精选文章",
            status=1,
            faker_id="MP_WXS_FEATURED_ARTICLES",
        ),
        _db_feed("active-b", "启用B", status=1),
    ]

    expected = {
        row.id
        for row in rows
        if row.status == 1 and row.faker_id != "MP_WXS_FEATURED_ARTICLES"
    }
    actual = {
        feed["feed_id"]
        for feed in derive(rows)["feeds"]
        if feed["active"]
    }

    assert actual == expected


def test_authority_is_not_truncated_at_one_hundred_or_by_env(monkeypatch):
    monkeypatch.setenv("WE_MP_RSS_FEEDS", "single-env-id")
    rows = [_db_feed(f"feed-{index:03d}", f"公众号{index}", status=1) for index in range(125)]

    authority = sync_module.derive_authoritative_feeds(rows)

    assert authority["known_count"] == 125
    assert authority["active_count"] == 125
    assert {feed["feed_id"] for feed in authority["feeds"]} == {row.id for row in rows}


def test_real_sidecar_active_contract_matches_db_get_all_mps():
    sidecar_root = Path(r"E:\AI-news-reader\we-mp-rss-sidecar")
    sidecar_python = sidecar_root / ".venv" / "Scripts" / "python.exe"
    sync_script = Path(__file__).resolve().parent.parent / "deploy" / "local" / "we_mp_rss_sync_once.py"
    if not sidecar_python.is_file() or not (sidecar_root / "core" / "db.py").is_file():
        pytest.skip("local read-only WeRSS sidecar environment is unavailable")
    probe = r'''
import importlib.util, json, sys
from pathlib import Path
sidecar_root=Path(sys.argv[1]); sync_path=Path(sys.argv[2]); sys.path.insert(0,str(sidecar_root))
spec=importlib.util.spec_from_file_location("authority_sync",sync_path); module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
import core.db as db
from core.config import cfg
from core.models.feed import Feed
db.DB.init(cfg.get("db"))
all_rows=module.read_all_feed_records(db.DB,Feed)
actual_rows=db.DB.get_all_mps()
if not isinstance(actual_rows,list): actual_rows=list(actual_rows)
derived={row["feed_id"] for row in module.derive_authoritative_feeds(all_rows)["feeds"] if row["active"]}
actual={str(row.id).strip() for row in actual_rows}
print(json.dumps({"derived_count":len(derived),"db_count":len(actual),"equal":derived==actual}))
raise SystemExit(0 if derived==actual else 3)
'''
    result = subprocess.run(
        [str(sidecar_python), "-c", probe, str(sidecar_root), str(sync_script)],
        cwd=sidecar_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    assert result.returncode == 0, f"read-only sidecar contract probe failed (exit={result.returncode})"
    summary = json.loads(result.stdout.strip().splitlines()[-1])
    assert summary["equal"] is True
    assert summary["derived_count"] == summary["db_count"]
    print(
        "real_sidecar_active_contract "
        f"derived_count={summary['derived_count']} db_count={summary['db_count']} equal=true"
    )


@pytest.mark.parametrize(
    "rows",
    [
        [_db_feed("dup", "A", status=1), _db_feed("dup", "B", status=1)],
        [_db_feed("blank-account", "", status=1)],
        [_db_feed("unknown-status", "A", status=2)],
    ],
)
def test_invalid_authority_rows_are_rejected(rows):
    derive = getattr(sync_module, "derive_authoritative_feeds")
    with pytest.raises(ValueError):
        derive(rows)

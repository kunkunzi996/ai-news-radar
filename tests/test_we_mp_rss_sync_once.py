import sys
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


def _feed(name: str) -> SimpleNamespace:
    return SimpleNamespace(id=f"MP_{name}", mp_name=name, faker_id=f"faker_{name}")


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

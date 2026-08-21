"""TEST-015：宽限、首次入库 14×24 小时裁剪、tombstone 不再入库。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
import json
import tempfile
import unittest

RETAIN_WINDOW = timedelta(hours=14 * 24)
GRACE_WINDOW = timedelta(hours=14 * 24)


def load_apply_retention() -> Callable[..., dict[str, Any]] | None:
    try:
        from scripts.radar.retention import apply_retention
    except ImportError:
        return None
    return apply_retention


def iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class RetentionPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 8, 21, 12, 0, tzinfo=timezone.utc)
        self.apply_retention = load_apply_retention()

    def require_apply_retention(self) -> Callable[..., dict[str, Any]]:
        self.assertTrue(
            callable(self.apply_retention),
            "缺少 scripts.radar.retention.apply_retention",
        )
        assert self.apply_retention is not None
        return self.apply_retention

    def test_grace_keeps_items_older_than_retain_window(self) -> None:
        apply_retention = self.require_apply_retention()
        first_seen = self.now - RETAIN_WINDOW - timedelta(days=20)
        archive = {
            "old": {
                "id": "old",
                "source": "王小七",
                "url": "https://example.com/old",
                "first_seen_at": iso(first_seen),
                "last_seen_at": iso(first_seen),
            }
        }
        result = apply_retention(
            archive,
            self.now,
            effective_at=self.now - timedelta(hours=1),
            tombstones=set(),
        )
        self.assertIn("old", result["archive"])
        self.assertEqual(result["removed"], {})

    def test_after_grace_drops_first_seen_older_than_14x24h(self) -> None:
        apply_retention = self.require_apply_retention()
        expired_seen = self.now - RETAIN_WINDOW - timedelta(seconds=1)
        fresh_seen = self.now - RETAIN_WINDOW + timedelta(hours=1)
        archive = {
            "expired": {
                "id": "expired",
                "source": "王小七",
                "url": "https://example.com/expired",
                "first_seen_at": iso(expired_seen),
                "last_seen_at": iso(expired_seen),
            },
            "fresh": {
                "id": "fresh",
                "source": "王小七",
                "url": "https://example.com/fresh",
                "first_seen_at": iso(fresh_seen),
                "last_seen_at": iso(self.now),
            },
        }
        result = apply_retention(
            archive,
            self.now,
            effective_at=self.now - GRACE_WINDOW - timedelta(hours=1),
            tombstones=set(),
        )
        self.assertNotIn("expired", result["archive"])
        self.assertIn("expired", result["removed"])
        self.assertIn("fresh", result["archive"])

    def test_after_grace_last_seen_refresh_does_not_renew(self) -> None:
        apply_retention = self.require_apply_retention()
        first_seen = self.now - RETAIN_WINDOW - timedelta(days=3)
        archive = {
            "stale": {
                "id": "stale",
                "source": "王小七",
                "url": "https://example.com/stale",
                "first_seen_at": iso(first_seen),
                "last_seen_at": iso(self.now),
            }
        }
        result = apply_retention(
            archive,
            self.now,
            effective_at=self.now - GRACE_WINDOW - timedelta(hours=1),
            tombstones=set(),
        )
        self.assertNotIn("stale", result["archive"])
        self.assertIn("stale", result["removed"])

    def test_tombstone_blocks_same_id_reinsert(self) -> None:
        apply_retention = self.require_apply_retention()
        first_seen = self.now - RETAIN_WINDOW - timedelta(days=3)
        record = {
            "id": "stale",
            "source": "王小七",
            "url": "https://example.com/stale",
            "first_seen_at": iso(first_seen),
            "last_seen_at": iso(self.now),
        }
        tombstones: set[str] = set()
        first = apply_retention(
            {"stale": record},
            self.now,
            effective_at=self.now - GRACE_WINDOW - timedelta(hours=1),
            tombstones=tombstones,
        )
        self.assertNotIn("stale", first["archive"])
        resurrected = {
            "stale": {
                **record,
                "first_seen_at": iso(self.now),
                "last_seen_at": iso(self.now),
            }
        }
        second = apply_retention(
            resurrected,
            self.now,
            effective_at=self.now - GRACE_WINDOW - timedelta(hours=1),
            tombstones=tombstones,
        )
        self.assertNotIn("stale", second["archive"])
        self.assertIn("stale", tombstones)

    def test_same_source_new_id_still_enters(self) -> None:
        apply_retention = self.require_apply_retention()
        expired_seen = self.now - RETAIN_WINDOW - timedelta(days=3)
        archive = {
            "old-post": {
                "id": "old-post",
                "source": "王小七",
                "url": "https://example.com/old-post",
                "first_seen_at": iso(expired_seen),
                "last_seen_at": iso(self.now),
            },
            "new-post": {
                "id": "new-post",
                "source": "王小七",
                "url": "https://example.com/new-post",
                "first_seen_at": iso(self.now),
                "last_seen_at": iso(self.now),
            },
        }
        tombstones: set[str] = set()
        result = apply_retention(
            archive,
            self.now,
            effective_at=self.now - GRACE_WINDOW - timedelta(hours=1),
            tombstones=tombstones,
        )
        self.assertNotIn("old-post", result["archive"])
        self.assertIn("new-post", result["archive"])
        self.assertNotIn("new-post", tombstones)


class SnapshotOrFailedPruneTests(unittest.TestCase):
    """TEST-016：第一次大裁前快照，失败则磁盘上仍是裁前归档。"""

    SNAPSHOT_RELATIVE = Path("retention-snapshots") / "archive-before-first-14d-prune.json"

    def setUp(self) -> None:
        self.now = datetime(2026, 8, 21, 12, 0, tzinfo=timezone.utc)
        self.apply_retention = load_apply_retention()
        self.tmp = Path(tempfile.mkdtemp())
        self.archive_path = self.tmp / "archive.json"
        self.snapshot_path = self.tmp / self.SNAPSHOT_RELATIVE
        expired_seen = self.now - RETAIN_WINDOW - timedelta(days=3)
        self.archive = {
            "old": {
                "id": "old",
                "source": "王小七",
                "url": "https://example.com/old",
                "first_seen_at": iso(expired_seen),
                "last_seen_at": iso(self.now),
            },
            "fresh": {
                "id": "fresh",
                "source": "王小七",
                "url": "https://example.com/fresh",
                "first_seen_at": iso(self.now),
                "last_seen_at": iso(self.now),
            },
        }
        self.original_payload = {
            "generated_at": iso(self.now),
            "total_items": 2,
            "items": [self.archive["old"], self.archive["fresh"]],
        }
        self.archive_path.write_text(
            json.dumps(self.original_payload, ensure_ascii=False),
            encoding="utf-8",
        )

    def _call(self, **extra: Any) -> dict[str, Any]:
        self.assertTrue(callable(self.apply_retention), "缺少 scripts.radar.retention.apply_retention")
        assert self.apply_retention is not None
        try:
            return self.apply_retention(
                self.archive,
                self.now,
                effective_at=self.now - GRACE_WINDOW - timedelta(hours=1),
                tombstones=set(),
                **extra,
            )
        except TypeError as exc:
            self.fail(f"apply_retention 尚未接受快照/写盘参数: {exc}")

    def test_snapshot_or_failed_prune_writes_copy_before_first_cut(self) -> None:
        result = self._call(output_dir=self.tmp, archive_path=self.archive_path)
        self.assertTrue(self.snapshot_path.is_file(), "第一次 14 天裁前应写出快照文件")
        snapshot = json.loads(self.snapshot_path.read_text(encoding="utf-8"))
        self.assertEqual(snapshot, self.original_payload)
        self.assertEqual((result.get("retention") or {}).get("last_prune_status"), "completed")
        self.assertNotIn("old", result["archive"])
        self.assertIn("fresh", result["archive"])

    def test_snapshot_or_failed_prune_failed_keeps_archive_and_status(self) -> None:
        result = self._call(
            output_dir=self.tmp,
            archive_path=self.archive_path,
            fail_commit=True,
        )
        self.assertEqual((result.get("retention") or {}).get("last_prune_status"), "failed")
        on_disk = json.loads(self.archive_path.read_text(encoding="utf-8"))
        self.assertEqual(on_disk, self.original_payload)
        self.assertTrue(self.snapshot_path.is_file(), "失败前仍应先留下快照")

    def test_prune_skipped_until_real_archive_snapshot(self) -> None:
        result = self._call(output_dir=self.tmp, archive_path=self.tmp / "missing-archive.json")
        self.assertEqual((result.get("retention") or {}).get("last_prune_status"), "not_run")
        self.assertIn("old", result["archive"])
        self.assertFalse(self.snapshot_path.exists())

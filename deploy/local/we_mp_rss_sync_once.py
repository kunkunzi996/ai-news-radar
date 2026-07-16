"""触发 WeRSS sidecar 抓取一轮公众号新文章。

必须用 sidecar 自己的 venv 执行，且 cwd 必须是 sidecar 根目录
（sidecar 的 config.yaml / data/db.db 都按相对路径读取）。

抓取逻辑照搬 sidecar 官方定时任务 jobs/mps.py::do_job()。
本脚本存在的原因：sidecar 的 message_tasks 表为空，官方定时采集任务
从未注册，所以它自己不会去微信拉新文章（2026-07-12 定位）。
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

# 退出码语义（调用方 collect-wechat-and-push.ps1 靠它决定怎么告警）：
EXIT_ALL_OK = 0          # 全部公众号抓取成功
EXIT_ALL_FAILED = 1      # 全部失败（大概率是凭证过期 / sidecar 挂了）
EXIT_PARTIAL_FAILED = 2  # 部分失败 —— 也必须告警，不许静默放过
FEATURED_FEED_ID = "MP_WXS_FEATURED_ARTICLES"
AUTHORITY_SOURCE = "sidecar_db_feed_table"
RETENTION_POLICY = "feed_row_exists"
ACTIVE_POLICY = "status_1_excluding_featured_v1"


def derive_authoritative_feeds(feeds: Iterable[Any]) -> dict[str, Any]:
    """从同一份 Feed 表快照派生 known/active，拒绝含糊身份。"""
    normalized: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for feed in feeds:
        feed_id = str(getattr(feed, "id", "") or "").strip()
        account = str(getattr(feed, "mp_name", "") or "").strip()
        faker_id = str(getattr(feed, "faker_id", "") or "").strip()
        if faker_id == FEATURED_FEED_ID:
            continue
        if not feed_id:
            raise ValueError("feed_id_missing")
        if feed_id in seen_ids:
            raise ValueError(f"feed_id_duplicate:{feed_id}")
        if not account:
            raise ValueError(f"feed_account_missing:{feed_id}")
        status = getattr(feed, "status", None)
        if status not in (0, 1):
            raise ValueError(f"feed_status_unsupported:{feed_id}:{status}")
        if not faker_id:
            raise ValueError(f"feed_faker_id_missing:{feed_id}")
        seen_ids.add(feed_id)
        normalized.append(
            {
                "feed_id": feed_id,
                "account": account,
                "status": int(status),
                "active": status == 1,
            }
        )
    normalized.sort(key=lambda item: item["feed_id"])
    return {
        "known_count": len(normalized),
        "active_count": sum(1 for item in normalized if item["active"]),
        "feeds": normalized,
    }


def read_all_feed_records(db_instance: Any, feed_model: Any) -> list[Any]:
    """只查询一次 Feed 全表；调用者后续只使用这份内存快照。"""
    session = db_instance.get_session()
    try:
        rows = session.query(feed_model).all()
        if not isinstance(rows, list):
            rows = list(rows)
        return rows
    finally:
        session.close()


def build_authority_payload(
    derived: dict[str, Any],
    *,
    complete: bool,
    reason: str | None,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "complete": bool(complete),
        "reason": reason,
        "authority_source": AUTHORITY_SOURCE,
        "retention_policy": RETENTION_POLICY,
        "active_policy": ACTIVE_POLICY,
        "known_count": int(derived["known_count"]),
        "active_count": int(derived["active_count"]),
        "feeds": list(derived["feeds"]),
    }


def write_atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(temp_path, path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run one authoritative WeRSS sync.")
    parser.add_argument("--subscriptions-out", default="")
    parser.add_argument("--snapshot-only", action="store_true")
    return parser


def sync_feeds(
    feeds: Iterable[Any],
    gather_factory: Callable[[], Any],
    update_article: Callable[..., Any],
    *,
    max_page: int = 1,
) -> tuple[int, int, int]:
    """逐个公众号抓取，单个失败不影响其它号。

    返回 (成功号数, 失败号数, 新增文章总数)。
    每个号用独立的 gather 实例，避免计数互相污染。
    """
    ok_count = 0
    failed_count = 0
    total_new = 0

    for feed in feeds:
        name = getattr(feed, "mp_name", "") or getattr(feed, "id", "?")
        try:
            gather = gather_factory()
            gather.get_Articles(
                feed.faker_id,
                CallBack=update_article,
                Mps_id=feed.id,
                Mps_title=feed.mp_name,
                MaxPage=max_page,
            )
            new_count = int(gather.all_count() or 0)
            total_new += new_count
            ok_count += 1
            print(f"[sync] OK {name} 新增 {new_count}", flush=True)
        except Exception as exc:  # 单个号失败不能拖垮其它号
            failed_count += 1
            print(f"[sync] FAIL {name} {type(exc).__name__}: {exc}", flush=True)

    return ok_count, failed_count, total_new


def exit_code_for(ok_count: int, failed_count: int) -> int:
    """把成败计数翻译成退出码。

    注意：部分失败 (ok>0 且 failed>0) 也要返回非 0。
    2026-07-12 的 bug 就是"只有一个号出问题、链路全程无声"，不能重演。
    """
    if failed_count == 0:
        return EXIT_ALL_OK
    if ok_count == 0:
        return EXIT_ALL_FAILED
    return EXIT_PARTIAL_FAILED


def main(argv: list[str] | None = None) -> int:
    # 用 `python <路径>/we_mp_rss_sync_once.py` 启动时，Python 把「脚本所在目录」
    # （radar 的 deploy/local）放进 sys.path[0]，而不是 cwd。sidecar 的 core/ jobs/
    # 包在 cwd（sidecar 根目录）下，不手动加进来就会 ModuleNotFoundError。
    import sys

    args = build_parser().parse_args(argv)

    sys.path.insert(0, os.getcwd())

    # sidecar 模块延迟导入：这样单测可以 import 本模块而无需安装 sidecar
    import core.db as db
    from core.config import cfg
    from core.models.feed import Feed
    from core.wx import WxGather
    from jobs.article import UpdateArticle

    db.DB.init(cfg.get("db"))
    all_feeds = read_all_feed_records(db.DB, Feed)
    derived = derive_authoritative_feeds(all_feeds)
    active_ids = {item["feed_id"] for item in derived["feeds"] if item["active"]}
    feeds = [feed for feed in all_feeds if str(getattr(feed, "id", "") or "").strip() in active_ids]
    subscriptions_out = Path(args.subscriptions_out) if args.subscriptions_out else None
    if args.snapshot_only:
        if subscriptions_out is not None:
            write_atomic_json(
                subscriptions_out,
                build_authority_payload(derived, complete=False, reason="sync_skipped"),
            )
        print(
            f"[sync] 诊断快照：known {derived['known_count']} / active {derived['active_count']}",
            flush=True,
        )
        return EXIT_ALL_OK

    if not feeds:
        print("[sync] 没有启用的公众号，跳过抓取", flush=True)
        if subscriptions_out is not None:
            write_atomic_json(
                subscriptions_out,
                build_authority_payload(derived, complete=True, reason=None),
            )
        return EXIT_ALL_OK

    ok_count, failed_count, total_new = sync_feeds(
        feeds,
        gather_factory=lambda: WxGather().Model(),
        update_article=UpdateArticle,
    )
    print(
        f"[sync] 完成：成功 {ok_count} 个 / 失败 {failed_count} 个 / 新增 {total_new} 条",
        flush=True,
    )
    exit_code = exit_code_for(ok_count, failed_count)
    if exit_code == EXIT_ALL_OK and subscriptions_out is not None:
        write_atomic_json(
            subscriptions_out,
            build_authority_payload(derived, complete=True, reason=None),
        )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

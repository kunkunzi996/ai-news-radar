"""触发 WeRSS sidecar 抓取一轮公众号新文章。

必须用 sidecar 自己的 venv 执行，且 cwd 必须是 sidecar 根目录
（sidecar 的 config.yaml / data/db.db 都按相对路径读取）。

抓取逻辑照搬 sidecar 官方定时任务 jobs/mps.py::do_job()。
本脚本存在的原因：sidecar 的 message_tasks 表为空，官方定时采集任务
从未注册，所以它自己不会去微信拉新文章（2026-07-12 定位）。
"""
from __future__ import annotations

from typing import Any, Callable, Iterable

# 退出码语义（调用方 collect-wechat-and-push.ps1 靠它决定怎么告警）：
EXIT_ALL_OK = 0          # 全部公众号抓取成功
EXIT_ALL_FAILED = 1      # 全部失败（大概率是凭证过期 / sidecar 挂了）
EXIT_PARTIAL_FAILED = 2  # 部分失败 —— 也必须告警，不许静默放过


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


def main() -> int:
    # 用 `python <路径>/we_mp_rss_sync_once.py` 启动时，Python 把「脚本所在目录」
    # （radar 的 deploy/local）放进 sys.path[0]，而不是 cwd。sidecar 的 core/ jobs/
    # 包在 cwd（sidecar 根目录）下，不手动加进来就会 ModuleNotFoundError。
    import os
    import sys

    sys.path.insert(0, os.getcwd())

    # sidecar 模块延迟导入：这样单测可以 import 本模块而无需安装 sidecar
    import core.db as db
    from core.config import cfg
    from core.wx import WxGather
    from jobs.article import UpdateArticle

    db.DB.init(cfg.get("db"))
    feeds = list(db.DB.get_all_mps())
    if not feeds:
        print("[sync] 没有已订阅的公众号，跳过", flush=True)
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
    return exit_code_for(ok_count, failed_count)


if __name__ == "__main__":
    raise SystemExit(main())

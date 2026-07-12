#!/usr/bin/env python3
"""审计归档中已取消订阅的对象；只读，不修改任何文件。"""

from __future__ import annotations

import argparse
from pathlib import Path

from scripts.radar.common import ENUMERABLE_SUBSCRIPTION_SITE_IDS
from scripts.radar.config_runtime import (
    is_online_panel_config,
    load_source_config,
    source_config_enabled_subscription_names,
)
from scripts.radar.pipeline import filter_archive_by_subscriptions, load_archive


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="只读审计取消订阅后将清理的历史条目")
    parser.add_argument(
        "--source-config",
        default="config/online-sources.json",
        help="要审计的信源配置文件（默认面板配置）",
    )
    parser.add_argument("--force", action="store_true", help="跳过熔断，仅预览强制清理结果")
    return parser


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    return build_parser().parse_args(argv)


def main() -> int:
    args = parse_args()

    config, status = load_source_config(args.source_config, output_dir=Path("data"))
    if not (status.get("ok") and config):
        print(f"配置未成功加载（{status.get('error')}），不会做任何清理。")
        return 2
    if not is_online_panel_config(config):
        print(f"当前加载的是 {status.get('path')}，不是面板配置，管线不会做任何清理。")
        return 2

    archive = load_archive(Path("data/archive.json"))
    allowed = source_config_enabled_subscription_names(config)

    print(f"归档条目总数：{len(archive)}")
    print(f"可枚举通道：{sorted(ENUMERABLE_SUBSCRIPTION_SITE_IDS)}")
    for site_id, allowlist in sorted(allowed.items()):
        print(f"  {site_id} 已订阅名称 {len(allowlist.names)} 个：{sorted(allowlist.names)}")
        if allowlist.sec_uids:
            print(f"    sec_uid {len(allowlist.sec_uids)} 个")

    kept, removed, fused_sites = filter_archive_by_subscriptions(archive, allowed, force=args.force)
    for site_id in fused_sites:
        print(f"\n警告：{site_id} 的归档条目没有一条命中订阅名单，判定为名单异常，本次不会清理该通道。")
        print("      若确认名单无误，可加 --force 查看强制清理的结果。")
    if not removed:
        print("\n没有需要清理的条目。")
        print("真正的清理发生在下一次采集：python scripts/update_news.py --source-config config/online-sources.json")
        return 0

    total = sum(removed.values())
    print(f"\n下次采集将清理 {total} 条（来自 {len(removed)} 个已取消订阅的对象）：")
    for (site_id, source), count in sorted(removed.items(), key=lambda kv: -kv[1]):
        print(f"  - {site_id} / {source}：{count} 条")
    print(f"\n清理后归档剩余：{len(kept)} 条")
    print("真正的清理发生在下一次采集：python scripts/update_news.py --source-config config/online-sources.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

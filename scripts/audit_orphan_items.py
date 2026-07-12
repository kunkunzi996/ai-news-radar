#!/usr/bin/env python3
"""审计归档中已取消订阅的对象；只读，不修改任何文件。"""

from __future__ import annotations

from pathlib import Path

from scripts.radar.common import ENUMERABLE_SUBSCRIPTION_SITE_IDS
from scripts.radar.config_runtime import (
    load_source_config,
    source_config_enabled_subscription_names,
)
from scripts.radar.pipeline import filter_archive_by_subscriptions, load_archive


def main() -> int:
    config, status = load_source_config("config/online-sources.json", output_dir=Path("data"))
    if not (status.get("ok") and config):
        print(f"线上配置未成功加载（{status.get('error')}），不会做任何清理。")
        return 2

    archive = load_archive(Path("data/archive.json"))
    allowed = source_config_enabled_subscription_names(config)

    print(f"归档条目总数：{len(archive)}")
    print(f"可枚举通道：{sorted(ENUMERABLE_SUBSCRIPTION_SITE_IDS)}")
    for site_id, names in sorted(allowed.items()):
        print(f"  {site_id} 已订阅 {len(names)} 个：{sorted(names)}")

    kept, removed = filter_archive_by_subscriptions(archive, allowed)
    if not removed:
        print("\n没有需要清理的条目。")
        return 0

    total = sum(removed.values())
    print(f"\n下次采集将清理 {total} 条（来自 {len(removed)} 个已取消订阅的对象）：")
    for (site_id, source), count in sorted(removed.items(), key=lambda kv: -kv[1]):
        print(f"  - {site_id} / {source}：{count} 条")
    print(f"\n清理后归档剩余：{len(kept)} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

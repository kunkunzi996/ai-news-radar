# 源状态原样透传，主管线不挑字段

采集通道回执曾经在 `cli.py` 逐字段重建，新键在主管线被丢掉（见 BUG-02）。我们决定 fetcher 回执只盖 `site_id` / `site_name` 后进入 `sites[]`。宁可公开 JSON 出现未知键，也不把主管线当成第二道过滤器；脱敏仍走 `sanitize_public_payload`。

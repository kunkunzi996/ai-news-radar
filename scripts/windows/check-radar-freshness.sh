#!/usr/bin/env bash

# 只看结果、不管过程的哨兵：本地 data/latest-24h-all.json 的 generated_at 是否落后云端或落后现在。
# 2026-09-11 快进停摆 13 小时期间 auto-ff.log 早就写满 worktree_dirty，但没人看日志；
# 这条把「网页上显示的那一版到底多旧」直接写成一行 event=stale，并可交给通知命令。
set -u

REPO_ROOT="${RADAR_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
LOG_FILE="${RADAR_FRESHNESS_LOG:-$REPO_ROOT/logs/freshness.log}"
STALE_AFTER_MINUTES="${RADAR_FRESHNESS_STALE_MINUTES:-90}"
DATA_FILE="data/latest-24h-all.json"

mkdir -p "$(dirname "$LOG_FILE")"

timestamp() {
    date -u '+%Y-%m-%dT%H:%M:%SZ'
}

generated_at_of() {
    # 兼容紧凑 JSON 与带缩进 JSON；只取第一处 generated_at。
    sed -n 's/.*"generated_at": *"\([^"]*\)".*/\1/p' | head -n 1
}

to_epoch() {
    local value="$1"
    [ -n "$value" ] || { echo ""; return; }
    date -u -d "${value%%.*}" +%s 2>/dev/null || echo ""
}

write_log() {
    printf '%s event=%s local=%s remote=%s lag_minutes=%s behind_remote_minutes=%s detail=%s\n' \
        "$(timestamp)" "$1" "$2" "$3" "$4" "$5" "$6" >> "$LOG_FILE"
}

local_generated=$(generated_at_of < "$REPO_ROOT/$DATA_FILE" 2>/dev/null)
git -C "$REPO_ROOT" fetch origin --quiet 2>/dev/null || true
remote_generated=$(git -C "$REPO_ROOT" show "origin/master:$DATA_FILE" 2>/dev/null | generated_at_of)

now_epoch=$(date -u +%s)
local_epoch=$(to_epoch "$local_generated")
remote_epoch=$(to_epoch "$remote_generated")

if [ -z "$local_epoch" ]; then
    write_log "unknown" "${local_generated:-missing}" "${remote_generated:-missing}" "" "" "local_generated_at_unreadable"
    exit 0
fi

lag_minutes=$(( (now_epoch - local_epoch) / 60 ))
behind_remote=""
if [ -n "$remote_epoch" ]; then
    behind_remote=$(( (remote_epoch - local_epoch) / 60 ))
fi

event="fresh"
detail=""
if [ "$lag_minutes" -ge "$STALE_AFTER_MINUTES" ]; then
    event="stale"
    if [ -n "$behind_remote" ] && [ "$behind_remote" -gt 0 ]; then
        detail="nuc_behind_cloud"
    else
        detail="cloud_not_producing"
    fi
fi

write_log "$event" "$local_generated" "${remote_generated:-unknown}" "$lag_minutes" "${behind_remote:-unknown}" "$detail"

if [ "$event" = "stale" ] && [ -n "${RADAR_FRESHNESS_ALERT_COMMAND:-}" ]; then
    RADAR_FRESHNESS_LAG_MINUTES="$lag_minutes" RADAR_FRESHNESS_DETAIL="$detail" \
        bash -c "$RADAR_FRESHNESS_ALERT_COMMAND" >/dev/null 2>&1 || true
fi
exit 0

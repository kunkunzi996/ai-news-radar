#!/usr/bin/env bash

# Keep the scheduled fast-forward job quiet on success but explain every skip.
set -u

REPO_ROOT="${RADAR_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
LOG_FILE="${RADAR_AUTO_FF_LOG:-$REPO_ROOT/logs/auto-ff.log}"
STARTED_AT_MS=$(date +%s%3N)

mkdir -p "$(dirname "$LOG_FILE")"

timestamp() {
    date -u '+%Y-%m-%dT%H:%M:%SZ'
}

clean_detail() {
    printf '%s' "$1" \
        | tr '\r\n\t' '   ' \
        | sed -E 's#https?://[^[:space:]]+#<url>#g; s/(token|cookie|pat|password)[=:][^[:space:]]*/\1=<redacted>/Ig' \
        | cut -c1-512
}

write_log() {
    local finished_at_ms
    finished_at_ms=$(date +%s%3N)
    printf '%s event=%s command=%s reason=%s exit=%s duration_ms=%s old_head=%s new_head=%s detail=%s\n' \
        "$(timestamp)" "$1" "$2" "$3" "$4" "$((finished_at_ms - STARTED_AT_MS))" "$5" "$6" "$(clean_detail "$7")" >> "$LOG_FILE"
}

old_head=$(git -C "$REPO_ROOT" rev-parse HEAD 2>&1)
old_head_status=$?
if [ "$old_head_status" -ne 0 ]; then
    write_log "failed" "rev_parse_head" "head_unavailable" "$old_head_status" "" "" "$old_head"
    exit 0
fi

fetch_detail=$(git -C "$REPO_ROOT" fetch origin --quiet 2>&1)
fetch_status=$?
if [ "$fetch_status" -ne 0 ]; then
    write_log "failed" "fetch_origin" "fetch_failed" "$fetch_status" "$old_head" "" "$fetch_detail"
    exit 0
fi

remote_head=$(git -C "$REPO_ROOT" rev-parse origin/master 2>&1)
remote_head_status=$?
if [ "$remote_head_status" -ne 0 ]; then
    write_log "failed" "rev_parse_remote_head" "remote_head_unavailable" "$remote_head_status" "$old_head" "" "$remote_head"
    exit 0
fi

merge_detail=$(git -C "$REPO_ROOT" merge --ff-only origin/master --quiet 2>&1)
merge_status=$?
if [ "$merge_status" -eq 0 ]; then
    new_head=$(git -C "$REPO_ROOT" rev-parse HEAD 2>&1)
    write_log "ff-ok" "merge_ff_only" "fast_forwarded" "0" "$old_head" "$new_head" ""
    exit 0
fi

if [ -n "$(git -C "$REPO_ROOT" status --porcelain --untracked-files=no 2>/dev/null)" ]; then
    reason="worktree_dirty"
elif ! git -C "$REPO_ROOT" merge-base --is-ancestor HEAD origin/master >/dev/null 2>&1; then
    reason="remote_diverged"
else
    reason="fast_forward_failed"
fi
write_log "failed" "merge_ff_only" "$reason" "$merge_status" "$old_head" "$remote_head" "$merge_detail"
exit 0

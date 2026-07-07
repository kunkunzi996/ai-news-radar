function fmtNumber(n) {
  return new Intl.NumberFormat("zh-CN").format(n || 0);
}
function fmtTime(iso) {
  if (!iso) return "时间未知";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "时间未知";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(d);
}
function fmtDate(iso) {
  if (!iso) return "未知日期";
  const d = new Date(`${iso}T00:00:00`);
  if (Number.isNaN(d.getTime())) return iso;
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
  }).format(d);
}
function windowLabel() {
  if (state.timeRangeFilter === "all") return "不限";
  return state.timeScope === "all_time" ? "全部时间" : "过去 24 小时";
}
function creatorWindowLabel() {
  if (state.timeRangeFilter === "24h") return "过去 24 小时";
  if (state.timeRangeFilter === "all") return "不限";
  return state.creatorTimeScope === "all_time" ? "全部时间" : `过去 ${fmtNumber(state.creatorWindowDays)} 天`;
}
function multiSourceEventKeys(items) {
  const map = new Map();
  (items || []).forEach((item) => {
    const key = eventKey(item);
    if (!map.has(key)) map.set(key, new Set());
    map.get(key).add(sourceSignal(item));
  });
  return new Set(Array.from(map.entries())
    .filter(([, sources]) => sources.size > 1)
    .map(([key]) => key));
}
function itemMatchesSignalLevel(item, multiSourceKeys = new Set()) {
  if (!state.signalLevelFilter) return true;
  if (state.signalLevelFilter === "high") return isHighPriorityItem(item);
  if (state.signalLevelFilter === "curated") return isCuratedItem(item);
  if (state.signalLevelFilter === "multi") return multiSourceKeys.has(eventKey(item));
  return true;
}
function itemIdentityKey(item) {
  const keys = itemIdentityKeys(item);
  return keys.size ? Array.from(keys)[0] : `fallback:${item?.site_id || ""}:${item?.url || item?.title || ""}`;
}
function timeRangeCutoffMs() {
  const baseMs = new Date(state.generatedAt || "").getTime();
  const anchorMs = Number.isFinite(baseMs) ? baseMs : Date.now();
  return anchorMs - 24 * 60 * 60 * 1000;
}
function itemMatchesTimeRange(item) {
  if (state.timeRangeFilter === "all") return true;
  const ms = timelineMs(item);
  return !ms || ms >= timeRangeCutoffMs();
}
function applyTimeRange(items) {
  const source = Array.isArray(items) ? items : [];
  if (state.timeRangeFilter === "all") return source;
  return source.filter(itemMatchesTimeRange);
}
function sectionItems(items = modeItems(), sectionId = state.activeSection) {
  if (isHiddenPlatformId(sectionId)) return [];
  if (sectionId === "read") {
    return applyTimeRange(subscriptionModeItems().filter((item) => isItemRead(item)))
      .sort((a, b) => timelineMs(b) - timelineMs(a) || creatorHotScore(b) - creatorHotScore(a));
  }
  if (sectionId === "creator") {
    return applyTimeRange(subscriptionModeItems().filter((item) => !isItemRead(item)))
      .sort((a, b) => timelineMs(b) - timelineMs(a) || creatorHotScore(b) - creatorHotScore(a));
  }
  if (isSubscriptionSection(sectionId)) {
    return applyTimeRange(subscriptionModeItems())
      .filter((item) => itemPlatformSection(item) === sectionId && !isItemRead(item))
      .sort((a, b) => timelineMs(b) - timelineMs(a) || creatorHotScore(b) - creatorHotScore(a));
  }
  const source = visibleItemList(applyTimeRange(items));
  return source.filter((item) => itemMatchesSection(item, sectionId) && !isItemRead(item));
}
function formatStoryTime(story) {
  const earliest = story.earliest_at;
  const latest = story.latest_at;
  if (latest && earliest && latest !== earliest) {
    return { latest, rangeLabel: storyDurationLabel(earliest, latest) };
  }
  return { latest: latest || earliest, rangeLabel: "" };
}
function hotStories(stories) {
  return stories
    .filter((story) => storyHotness(story) > 0)
    .sort((a, b) => {
      const byHotScore = storyHotScore(b) - storyHotScore(a);
      if (byHotScore !== 0) return byHotScore;
      const byHotRaw = storyHotness(b) - storyHotness(a);
      if (byHotRaw !== 0) return byHotRaw;
      const byEditorial = storyScore(b) - storyScore(a);
      if (byEditorial !== 0) return byEditorial;
      return storyTimeMs(b, "latest_at") - storyTimeMs(a, "latest_at");
    });
}
function latestStories(stories) {
  return [...(Array.isArray(stories) ? stories : [])].sort((a, b) => {
    const aLatest = storyTimeMs(a, "latest_at") || storyTimeMs(a, "earliest_at");
    const bLatest = storyTimeMs(b, "latest_at") || storyTimeMs(b, "earliest_at");
    if (aLatest !== bLatest) return bLatest - aLatest;
    return storyScore(b) - storyScore(a);
  });
}
function pickTopHeadlineClusters(clusters, limit = 3) {
  return [...clusters]
    .sort((a, b) => headlineClusterScore(b) - headlineClusterScore(a) || timelineMs(b.item) - timelineMs(a.item) || a.index - b.index)
    .slice(0, limit)
    .map((cluster) => ({ ...cluster, score: headlineClusterScore(cluster) }));
}

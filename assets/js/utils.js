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
function cacheBustedUrl(url) {
  const separator = String(url).includes("?") ? "&" : "?";
  return `${url}${separator}t=${Date.now()}`;
}
function normalizeDataBaseUrl(raw) {
  const text = String(raw || "").trim();
  if (!text || text.toLowerCase() === "local") return "";
  try {
    const url = new URL(text, window.location.href);
    if (url.protocol !== "http:" && url.protocol !== "https:") return "";
    url.hash = "";
    url.search = "";
    const value = url.toString();
    return value.endsWith("/") ? value : `${value}/`;
  } catch {
    return "";
  }
}
function canUseLocalBackend() {
  const host = String(window.location.hostname || "").toLowerCase();
  return ["localhost", "127.0.0.1", "::1", "0.0.0.0"].includes(host) || host.endsWith(".localhost");
}
function localBackendUnavailableMessage() {
  return "公网静态页不连接本地后台；请在本机用 scripts/local_server.py 打开采集控制台。";
}
function initDataSource() {
  state.dataBaseUrl = "";
  state.dataSourceMode = "local";
  state.dataSourceFallback = false;
  state.dataSourceError = "";

  let rawDataBase = "";
  let hasUrlOverride = false;
  try {
    const params = new URLSearchParams(window.location.search);
    rawDataBase = params.get("dataBase") || params.get("data_base") || "";
    hasUrlOverride = params.has("dataBase") || params.has("data_base");
  } catch {
    rawDataBase = "";
  }

  if (hasUrlOverride) {
    const text = String(rawDataBase || "").trim();
    if (!text || text.toLowerCase() === "local") {
      try {
        window.localStorage.removeItem(DATA_BASE_STORAGE_KEY);
      } catch {}
      return;
    }
    const normalized = normalizeDataBaseUrl(text);
    if (normalized) {
      state.dataBaseUrl = normalized;
      state.dataSourceMode = "remote";
      try {
        window.localStorage.setItem(DATA_BASE_STORAGE_KEY, normalized);
      } catch {}
    } else {
      state.dataSourceError = "远程数据地址无效，已使用本地数据";
      try {
        window.localStorage.removeItem(DATA_BASE_STORAGE_KEY);
      } catch {}
    }
    return;
  }

  try {
    const saved = normalizeDataBaseUrl(window.localStorage.getItem(DATA_BASE_STORAGE_KEY));
    if (saved) {
      state.dataBaseUrl = saved;
      state.dataSourceMode = "remote";
    }
  } catch {}
}
function localDataPathFor(path) {
  const raw = String(path || "").trim();
  if (/^https?:\/\//i.test(raw)) {
    try {
      const parts = new URL(raw).pathname.split("/").filter(Boolean);
      const fileName = parts[parts.length - 1] || "";
      return fileName ? `data/${fileName}` : "data/latest-24h.json";
    } catch {
      return "data/latest-24h.json";
    }
  }
  const clean = raw.replace(/^\.?\//, "");
  return clean.startsWith("data/") ? clean : `data/${clean}`;
}
function remoteDataPathFor(path) {
  const raw = String(path || "").trim();
  if (/^https?:\/\//i.test(raw)) return raw;
  return raw.replace(/^\.?\//, "").replace(/^data\//, "");
}
function dataFileUrl(path, options = {}) {
  if (!options.forceLocal && state.dataSourceMode === "remote" && state.dataBaseUrl) {
    const remotePath = remoteDataPathFor(path);
    return cacheBustedUrl(/^https?:\/\//i.test(remotePath)
      ? remotePath
      : new URL(remotePath, state.dataBaseUrl).toString());
  }
  return cacheBustedUrl(`./${localDataPathFor(path)}`);
}
async function fetchJson(url, label) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`加载 ${label} 失败: ${res.status}`);
  return res.json();
}
async function fetchDataJson(path, label, options = {}) {
  try {
    return await fetchJson(dataFileUrl(path), label);
  } catch (remoteErr) {
    if (state.dataSourceMode === "remote" && options.fallbackLocal !== false) {
      try {
        const payload = await fetchJson(dataFileUrl(path, { forceLocal: true }), label);
        state.dataSourceFallback = true;
        state.dataSourceError = `${label} 远程读取失败，已回退本地数据`;
        return payload;
      } catch (localErr) {
        throw new Error(`${remoteErr.message}；本地回退也失败: ${localErr.message}`);
      }
    }
    throw remoteErr;
  }
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

// 后端 purged_items 有三种形态：已清理（{文件名: 删除条数}）、延后（采集占着锁，
// 已记进待清理台账）、失败。三个保存入口共用这段解读，别各写一遍。
// 延后必须说出来——否则用户删了信源却看到"没清理任何东西"，会以为清理丢了。
function purgedItemsNote(purgedItems) {
  const payload = purgedItems && typeof purgedItems === "object" ? purgedItems : {};
  if (payload.error) return `；历史数据清理失败：${payload.error}`;

  if (payload.deferred && typeof payload.deferred === "object") {
    const pending = Object.values(payload.deferred).reduce(
      (sum, names) => sum + (Array.isArray(names) ? names.length : 0),
      0,
    );
    return pending > 0 ? `；${pending} 个已删除信源的历史数据将在本次采集结束后清理` : "";
  }

  const removed = Object.values(payload).reduce((sum, value) => {
    const n = Number(value);
    return sum + (Number.isFinite(n) ? n : 0);
  }, 0);
  return removed > 0 ? `；已清理 ${removed} 条已删除信源的历史数据` : "";
}

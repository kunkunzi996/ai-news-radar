function setLocalOpsStatus(message, tone = "") {
  if (!localOpsStatusEl) return;
  localOpsStatusEl.textContent = message || "";
  localOpsStatusEl.className = tone || "";
}
function localOpsMetric(label, value, tone = "") {
  const node = document.createElement("div");
  node.className = `local-ops-metric${tone ? ` ${tone}` : ""}`;
  const strong = document.createElement("strong");
  strong.textContent = value;
  const span = document.createElement("span");
  span.textContent = label;
  node.append(strong, span);
  return node;
}
function localOpsSourcePlatformLabel(source) {
  const channel = String(source?.channel || "").trim();
  if (channel) return channel;
  const key = sourceConfigPlatformKey(source);
  const labels = {
    wechat: "微信公众号",
    xhs: "小红书",
    douyin: "抖音",
    bilibili: "B站",
    github: "GitHub",
    rss: "RSS",
  };
  return labels[key] || "其他";
}
function localOpsSiteMap(sourceStatus = {}) {
  const sites = visibleSourceStatusSites(sourceStatus);
  return new Map(sites.map((site) => [String(site.site_id || ""), site]));
}
function localOpsSourceNeedles(source) {
  const fields = [source?.name, source?.target, source?.locator]
    .map((value) => String(value || "").trim().toLowerCase())
    .filter(Boolean);
  return Array.from(new Set(fields));
}
function localOpsIssueForSource(source, runtimeIds, issues) {
  const sourceIdText = String(source?.id || "").toLowerCase();
  const sourceNeedles = localOpsSourceNeedles(source);
  const platformIssues = issues.filter((issue) => {
    const sourceId = String(issue.source_id || "");
    const issueId = String(issue.id || "");
    return runtimeIds.has(sourceId) || (sourceIdText && issueId.toLowerCase().includes(sourceIdText));
  });
  return platformIssues.find((issue) => {
    const hay = `${issue.id || ""} ${issue.title || ""} ${(issue.details || []).join(" ")}`.toLowerCase();
    return sourceNeedles.some((needle) => hay.includes(needle));
  }) || platformIssues.find((issue) => !String(issue.id || "").includes("_sidecar_")) || platformIssues[0] || null;
}
function localOpsSourceTone(source, runtimeIds, siteMap, issue) {
  if (issue?.severity === "bad") return "bad";
  if (issue) return "warn";
  const sites = Array.from(runtimeIds).map((id) => siteMap.get(id)).filter(Boolean);
  if (!sites.length) return "warn";
  if (sites.every((site) => site.ok)) return "ok";
  if (sites.some((site) => site.ok)) return "warn";
  return "bad";
}
function localOpsSourceStatusText(tone, runtimeIds, siteMap) {
  if (tone === "bad") return "需维护";
  if (tone === "warn") {
    const hasSite = Array.from(runtimeIds).some((id) => siteMap.has(id));
    return hasSite ? "需关注" : "未生成";
  }
  return "正常";
}
function localOpsSourceResultText(runtimeIds, siteMap, collectors = {}) {
  for (const id of runtimeIds) {
    const collector = collectors?.[id];
    if (collector) {
      const windowCount = Number(collector.item_count || 0);
      const rawCount = Number(collector.raw_item_count ?? collector.item_count ?? 0);
      if (Number(collector.collection_window_hours || 0)) {
        return `窗口 ${fmtNumber(windowCount)} / 原始 ${fmtNumber(rawCount)}`;
      }
      return `原始 ${fmtNumber(rawCount)}`;
    }
  }
  const seen = new Set();
  const counts = Array.from(runtimeIds).reduce((acc, id) => {
    if (seen.has(id)) return acc;
    seen.add(id);
    const site = siteMap.get(id);
    if (!site) return acc;
    acc.raw += Number(site.raw_item_count ?? site.item_count ?? 0);
    acc.window += Number(site.window_item_count ?? 0);
    if (Number(site.collection_window_hours || 0)) acc.hasWindow = true;
    return acc;
  }, { raw: 0, window: 0, hasWindow: false });
  if (!seen.size) return "未生成";
  if (counts.hasWindow) return `窗口 ${fmtNumber(counts.window)} / 原始 ${fmtNumber(counts.raw)}`;
  return `原始 ${fmtNumber(counts.raw)}`;
}
function localOpsSourceUpdatedText(runtimeIds, collectors = {}, sourceStatus = {}) {
  for (const id of runtimeIds) {
    const updatedAt = collectors?.[id]?.updated_at;
    if (updatedAt) return fmtTime(updatedAt);
  }
  return sourceStatus.generated_at ? fmtTime(sourceStatus.generated_at) : "未生成";
}
function localOpsSourceAction(source, runtimeIds) {
  if (runtimeIds.has("mediacrawler_xhs")) {
    return { id: "start_mediacrawler_xhs", kind: "start_service", label: "启动采集" };
  }
  if (runtimeIds.has("mediacrawler_douyin")) {
    return { id: "start_mediacrawler_douyin", kind: "start_service", label: "启动采集" };
  }
  return null;
}
function localOpsSourceGroupKey(source, runtimeIds) {
  if (runtimeIds.has("opmlrss")) return "youtube";
  if (runtimeIds.has("bilibili_dynamic")) return "bilibili";
  if (runtimeIds.has("mediacrawler_douyin")) return "douyin";
  if (runtimeIds.has("mediacrawler_xhs")) return "xhs";
  if (runtimeIds.has("wewe_rss")) return "wechat";
  if (runtimeIds.has("github_foundation_sunshine_releases")) return "github";
  return sourceConfigPlatformKey(source);
}
function localOpsSourceGroupMeta(key) {
  const meta = {
    youtube: { label: "YouTube 订阅", platform: "YouTube" },
    bilibili: { label: "B站动态", platform: "B站" },
    douyin: { label: "抖音", platform: "抖音" },
    xhs: { label: "小红书", platform: "小红书" },
    wechat: { label: "微信公众号", platform: "微信公众号" },
    github: { label: "GitHub Release", platform: "GitHub" },
    rss: { label: "RSS 订阅", platform: "RSS" },
  };
  return meta[key] || { label: "其他订阅", platform: "其他" };
}
function localOpsGroupedSources(configuredSources) {
  const order = ["youtube", "bilibili", "douyin", "xhs", "github", "rss", "other"];
  const groups = new Map();
  configuredSources.forEach((source) => {
    if (isHiddenSourceConfig(source)) return;
    const runtimeIds = sourceConfigRuntimeIds(source);
    const key = localOpsSourceGroupKey(source, runtimeIds);
    if (isHiddenPlatformId(key)) return;
    if (!groups.has(key)) {
      const meta = localOpsSourceGroupMeta(key);
      groups.set(key, { key, ...meta, sources: [] });
    }
    groups.get(key).sources.push(source);
  });
  return Array.from(groups.values()).sort((a, b) => {
    const ai = order.indexOf(a.key);
    const bi = order.indexOf(b.key);
    return (ai === -1 ? order.length : ai) - (bi === -1 ? order.length : bi);
  });
}
function localOpsGroupRuntimeIds(sources) {
  const ids = new Set();
  sources.forEach((source) => {
    sourceConfigRuntimeIds(source).forEach((id) => ids.add(id));
  });
  return ids;
}
function localOpsGroupIssues(sources, issues) {
  return sources
    .map((source) => localOpsIssueForSource(source, sourceConfigRuntimeIds(source), issues))
    .filter(Boolean);
}
function localOpsGroupTone(sources, groupRuntimeIds, siteMap, issues) {
  if (issues.some((issue) => issue.severity === "bad")) return "bad";
  if (issues.length) return "warn";
  const tones = sources.map((source) => localOpsSourceTone(source, sourceConfigRuntimeIds(source), siteMap, null));
  if (tones.includes("bad")) return "bad";
  if (tones.includes("warn")) return "warn";
  return localOpsSourceTone(sources[0], groupRuntimeIds, siteMap, null);
}
function localOpsSplitNamesAndLocators(source) {
  const names = splitSourceConfigList(source?.target || source?.name);
  const locators = splitSourceConfigList(source?.locator);
  const total = Math.max(names.length, locators.length, 1);
  return Array.from({ length: total }, (_, index) => ({
    name: names[index] || source?.name || source?.target || source?.id || "未命名订阅",
    locator: locators[index] || "",
  }));
}
function localOpsSourceChildEntries(group) {
  if (group.key === "youtube") {
    const source = group.sources[0];
    const members = youtubeSubscriptionMembers();
    if (members.length) {
      return members.map((member) => ({
        source,
        name: member.name,
        platform: "YouTube",
        detail: member.locator,
        resultText: "频道订阅",
        actionText: "已接入",
      }));
    }
  }
  if (group.key === "bilibili") {
    const source = group.sources[0];
    return localOpsSplitNamesAndLocators(source).map((member) => ({
      source,
      name: member.name,
      platform: "B站",
      detail: member.locator,
      resultText: "UP主订阅",
      actionText: member.locator || "已接入",
    }));
  }
  return group.sources.map((source) => ({
    source,
    name: source.name || source.target || source.id || "未命名订阅",
    platform: localOpsSourcePlatformLabel(source),
    detail: source.locator || source.target || "",
  }));
}
function localOpsSourceRowNode({ source, name, platform, detail = "", resultText = "", actionText = "", collectors, sourceStatus, siteMap, issues }) {
  const runtimeIds = sourceConfigRuntimeIds(source);
  const issue = localOpsIssueForSource(source, runtimeIds, issues);
  const tone = localOpsSourceTone(source, runtimeIds, siteMap, issue);
  const row = document.createElement("div");
  row.className = `local-ops-source-row local-ops-source-child ${tone}`;
  const nameNode = document.createElement("strong");
  nameNode.textContent = name;
  const platformNode = document.createElement("span");
  platformNode.textContent = platform;
  const status = document.createElement("span");
  status.className = `local-ops-source-status ${tone}`;
  status.textContent = localOpsSourceStatusText(tone, runtimeIds, siteMap);
  const result = document.createElement("span");
  result.textContent = resultText || localOpsSourceResultText(runtimeIds, siteMap, collectors);
  const updated = document.createElement("span");
  updated.textContent = localOpsSourceUpdatedText(runtimeIds, collectors, sourceStatus);
  const action = localOpsSourceAction(source, runtimeIds);
  const actionWrap = document.createElement("span");
  actionWrap.className = "local-ops-source-action";
  if (action) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "local-ops-locate";
    button.textContent = action.label;
    button.addEventListener("click", () => runLocalOpsFixAction(action, button));
    actionWrap.appendChild(button);
  } else if (issue) {
    actionWrap.textContent = issue.title || "需处理";
  } else {
    actionWrap.textContent = actionText || detail || "已接入";
  }
  row.append(nameNode, platformNode, status, result, updated, actionWrap);
  return row;
}
function clearRefreshProgressPolling() {
  if (state.refreshProgressPollTimer) {
    window.clearTimeout(state.refreshProgressPollTimer);
    state.refreshProgressPollTimer = null;
  }
}
function progressLogMessages(progress) {
  return (Array.isArray(progress?.log) ? progress.log : [])
    .map((entry) => (typeof entry === "string" ? entry : entry?.message))
    .filter(Boolean);
}
function hasVisibleProgress(progress) {
  return Boolean(progress?.running)
    || (progress?.status && progress.status !== "idle")
    || progressLogMessages(progress).length > 0;
}
function hasLiveServerProgress(progress) {
  return Boolean(progress?.running) || progress?.status === "failed";
}
function progressEtaText(progress, percent) {
  if (!progress?.started_at || !progress?.running || percent <= 5 || percent >= 96) return "";
  const started = Date.parse(progress.started_at);
  if (!Number.isFinite(started)) return "";
  const elapsedSeconds = Math.max(1, Math.round((Date.now() - started) / 1000));
  const remainingSeconds = Math.max(1, Math.round((elapsedSeconds / percent) * (100 - percent)));
  if (remainingSeconds >= 90) return `预计还剩约 ${Math.ceil(remainingSeconds / 60)} 分钟`;
  return `预计还剩约 ${remainingSeconds} 秒`;
}
function renderCollectionProgress(progress = null) {
  if (!localOpsProgressEl) return;
  const status = progress?.status || "idle";
  const logs = progressLogMessages(progress);
  const shouldShow = status !== "idle" || Boolean(progress?.running) || logs.length > 0;
  if (!shouldShow) {
    localOpsProgressEl.hidden = true;
    localOpsProgressEl.innerHTML = "";
    return;
  }
  const percent = Math.max(0, Math.min(100, Number(progress?.percent || 0)));
  const currentStep = progress?.current_step || (status === "completed" ? "采集完成" : "准备采集");
  const statusLabel = status === "completed"
    ? "已完成"
    : status === "failed"
      ? "失败"
      : `${fmtNumber(percent)}%`;
  const eta = progressEtaText(progress, percent);
  localOpsProgressEl.hidden = false;
  localOpsProgressEl.className = `local-ops-progress ${status}`.trim();
  localOpsProgressEl.innerHTML = "";

  const head = document.createElement("div");
  head.className = "local-ops-progress-head";
  const title = document.createElement("strong");
  title.textContent = currentStep;
  const badge = document.createElement("span");
  badge.textContent = statusLabel;
  head.append(title, badge);

  const track = document.createElement("div");
  track.className = "local-ops-progress-track";
  const bar = document.createElement("div");
  bar.className = "local-ops-progress-bar";
  bar.style.width = `${percent}%`;
  track.appendChild(bar);

  const meta = document.createElement("div");
  meta.className = "local-ops-progress-meta";
  meta.textContent = eta || (status === "running" ? "正在采集，请保持本地后台运行。" : "采集状态已更新。");

  const log = document.createElement("ul");
  log.className = "local-ops-progress-log";
  logs.slice(-5).forEach((message) => {
    const item = document.createElement("li");
    item.textContent = message;
    log.appendChild(item);
  });

  localOpsProgressEl.append(head, track, meta);
  if (log.childElementCount) localOpsProgressEl.appendChild(log);
}
function appendCollectionProgress(message, options = {}) {
  const previous = state.refreshProgress || {};
  const log = [...(Array.isArray(previous.log) ? previous.log : []), { time: new Date().toISOString(), message }].slice(-12);
  state.collectionProgressActive = true;
  state.refreshProgress = {
    ...previous,
    running: options.status ? options.status === "running" : true,
    status: options.status || previous.status || "running",
    percent: options.percent ?? previous.percent ?? 0,
    current_step: options.currentStep || previous.current_step || message,
    started_at: previous.started_at || new Date().toISOString(),
    updated_at: new Date().toISOString(),
    log,
  };
  renderCollectionProgress(state.refreshProgress);
}
async function loadRefreshProgressFromServer() {
  const res = await fetch("./api/refresh-progress", {
    headers: { Accept: "application/json" },
    cache: "no-store",
  });
  const payload = await res.json().catch(() => ({}));
  if (!res.ok || payload.ok === false) {
    throw new Error(payload.error || `HTTP ${res.status}`);
  }
  state.collectionProgressActive = true;
  state.refreshProgress = payload.progress || null;
  renderCollectionProgress(state.refreshProgress);
  return state.refreshProgress;
}
async function waitForRefreshProgressDone() {
  clearRefreshProgressPolling();
  const deadline = Date.now() + (12 * 60 * 1000);
  while (Date.now() < deadline) {
    const progress = await loadRefreshProgressFromServer();
    if (progress?.status === "completed") return progress;
    if (progress?.status === "failed") {
      const logs = progressLogMessages(progress);
      throw new Error(progress.error || logs.at(-1) || "refresh_failed");
    }
    await sleepMs(1200);
  }
  throw new Error("refresh_progress_timeout");
}
function renderLocalOpsCollectors(collectors = {}, sourceConfig = {}, sourceStatus = {}) {
  if (!localOpsCollectorsEl) return;
  localOpsCollectorsEl.innerHTML = "";
  const configuredSources = visibleSourceConfigSources((Array.isArray(sourceConfig.enabled_sources) && sourceConfig.enabled_sources.length ? sourceConfig.enabled_sources : state.sourceConfig?.sources) || [])
    .filter((source) => source && source.enabled !== false);
  if (!configuredSources.length) return;

  const siteMap = localOpsSiteMap(sourceStatus);
  const issues = visibleIssueList(sourceStatus.maintenance_issues);
  const card = document.createElement("article");
  card.className = "local-ops-source-overview";
  const head = document.createElement("div");
  head.className = "local-ops-collector-head";
  const title = document.createElement("strong");
  title.textContent = "订阅源采集概览";
  const badge = document.createElement("span");
  badge.textContent = `${fmtNumber(configuredSources.length)} 个订阅源`;
  head.append(title, badge);

  const rows = document.createElement("div");
  rows.className = "local-ops-source-rows";
  localOpsGroupedSources(configuredSources).forEach((group) => {
    const runtimeIds = localOpsGroupRuntimeIds(group.sources);
    const groupIssues = localOpsGroupIssues(group.sources, issues);
    const tone = localOpsGroupTone(group.sources, runtimeIds, siteMap, groupIssues);
    const children = localOpsSourceChildEntries(group);
    const details = document.createElement("details");
    details.className = `local-ops-source-group ${tone}`;
    const summary = document.createElement("summary");
    summary.className = "local-ops-source-row local-ops-source-parent";
    const name = document.createElement("strong");
    name.textContent = group.label;
    const platform = document.createElement("span");
    platform.textContent = `${fmtNumber(children.length)} 个订阅`;
    const status = document.createElement("span");
    status.className = `local-ops-source-status ${tone}`;
    status.textContent = localOpsSourceStatusText(tone, runtimeIds, siteMap);
    const result = document.createElement("span");
    result.textContent = localOpsSourceResultText(runtimeIds, siteMap, collectors);
    const updated = document.createElement("span");
    updated.textContent = localOpsSourceUpdatedText(runtimeIds, collectors, sourceStatus);
    const actionWrap = document.createElement("span");
    actionWrap.className = "local-ops-source-action";
    actionWrap.textContent = "展开";
    details.addEventListener("toggle", () => {
      actionWrap.textContent = details.open ? "收起" : "展开";
    });
    summary.append(name, platform, status, result, updated, actionWrap);

    const childWrap = document.createElement("div");
    childWrap.className = "local-ops-source-children";
    children.forEach((entry) => {
      childWrap.appendChild(localOpsSourceRowNode({
        ...entry,
        collectors,
        sourceStatus,
        siteMap,
        issues,
      }));
    });
    details.append(summary, childWrap);
    rows.appendChild(details);
  });
  card.append(head, rows);
  localOpsCollectorsEl.appendChild(card);
}
function scheduleLocalOpsPolling(shouldPoll) {
  if (state.localOpsPollTimer) {
    window.clearTimeout(state.localOpsPollTimer);
    state.localOpsPollTimer = null;
  }
  if (!shouldPoll) return;
  state.localOpsPollTimer = window.setTimeout(() => {
    loadLocalStatusFromServer(false);
  }, 3500);
}
async function runLocalOpsFixAction(action, button) {
  const label = action?.label || "修复";
  if (!["open_path", "start_service"].includes(action?.kind) || !action.id) {
    setLocalOpsStatus("这个维护入口暂不可用", "bad");
    return;
  }
  const shouldOpenPendingWindow = action.kind === "start_service" && action.id === "start_wewe_rss_sidecar";
  const pendingWindow = shouldOpenPendingWindow ? window.open("about:blank", "_blank") : null;
  if (pendingWindow) pendingWindow.opener = null;
  const oldText = button?.textContent || label;
  if (button) {
    button.disabled = true;
    button.textContent = "打开中...";
  }
  try {
    const res = await fetch("./api/maintenance-action", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ action_id: action.id, collection_scope: selectedCollectionScope() }),
    });
    const payload = await res.json().catch(() => ({}));
    if (!res.ok || payload.ok === false) {
      throw new Error(payload.error || `HTTP ${res.status}`);
    }
    if (shouldOpenPendingWindow && action.kind === "start_service" && payload.url) {
      if (pendingWindow) {
        pendingWindow.location.href = payload.url;
      } else {
        window.location.href = payload.url;
      }
    }
    if (action.id === "open_bilibili_cookie_folder") {
      const cookieFile = payload.recommended_cookie_file || "local-secrets/bilibili-cookies.txt";
      setLocalOpsStatus(`已打开cookie文件夹，导出后保存为：${cookieFile}`, "ok");
    } else if (action.id === "open_bilibili_login") {
      setLocalOpsStatus("已打开B站小号专用窗口，登录后点同步cookie", "ok");
    } else if (action.id === "sync_bilibili_cookie") {
      setLocalOpsStatus("已同步B站小号cookie，下一步点读取结果", "ok");
      window.setTimeout(() => loadLocalStatusFromServer(false), 1200);
    }
    if (action.id === "start_mediacrawler_douyin" || action.id === "start_mediacrawler_xhs") {
      const scopeLabel = selectedCollectionScope() === "all" ? "全量" : "自上次采集";
      setLocalOpsStatus(`${action.id === "start_mediacrawler_xhs" ? "小红书" : "抖音"}采集中（${scopeLabel}）`, "warn");
      window.setTimeout(() => loadLocalStatusFromServer(false), 1200);
    } else if (!["open_bilibili_cookie_folder", "open_bilibili_login", "sync_bilibili_cookie"].includes(action.id)) {
      setLocalOpsStatus(`已打开：${label}`, "ok");
    }
    if (button) button.textContent = "已打开";
  } catch (err) {
    if (pendingWindow && !pendingWindow.closed) pendingWindow.close();
    setLocalOpsStatus(`打开失败：${err?.message || "unknown error"}`, "bad");
    if (button) button.textContent = oldText;
  } finally {
    if (button) {
      window.setTimeout(() => {
        button.disabled = false;
        button.textContent = oldText;
      }, 1200);
    }
  }
}
function renderLocalOpsStatus(payload = null) {
  if (!localOpsSummaryEl || !localOpsIssuesEl) return;
  localOpsSummaryEl.innerHTML = "";
  if (localOpsCollectorsEl) localOpsCollectorsEl.innerHTML = "";
  localOpsIssuesEl.innerHTML = "";
  const sourceStatus = payload?.source_status || payload?.summary || {};
  const sourceConfig = payload?.source_config || {};
  const collectors = payload?.collectors || {};
  const refreshProgress = payload?.refresh_progress || null;
  const collectorRunning = Object.values(collectors || {}).some((collector) => Boolean(collector?.running));
  const issues = visibleIssueList(sourceStatus.maintenance_issues);
  const visibleConfiguredSources = visibleSourceConfigSources(state.sourceConfig?.sources || sourceConfig.enabled_sources || []);
  const enabled = visibleConfiguredSources.filter((source) => source.enabled !== false).length;
  const total = visibleConfiguredSources.length;
  const visibleSites = visibleSourceStatusSites(sourceStatus);
  const siteCount = visibleSites.length;
  const okSites = visibleSites.filter((site) => site.ok).length;
  const fetched = Number(sourceStatus.fetched_raw_items || 0);
  const generatedAt = sourceStatus.generated_at ? fmtTime(sourceStatus.generated_at) : "未生成";
  const issueTone = issues.some((issue) => issue.severity === "bad") ? "bad" : (issues.length ? "warn" : "ok");

  localOpsSummaryEl.append(
    localOpsMetric("启用订阅", `${fmtNumber(enabled)}/${fmtNumber(total)}`),
    localOpsMetric("源状态", siteCount ? `${fmtNumber(okSites)}/${fmtNumber(siteCount)}` : "未生成", siteCount && okSites === siteCount ? "ok" : "warn"),
    localOpsMetric("本轮采集", fmtNumber(fetched)),
    localOpsMetric("最近刷新", generatedAt),
    localOpsMetric("维护项", fmtNumber(issues.length), issueTone)
  );

  if (hasLiveServerProgress(refreshProgress)) {
    state.refreshProgress = refreshProgress;
    renderCollectionProgress(refreshProgress);
  } else if (state.collectionProgressActive && hasVisibleProgress(state.refreshProgress)) {
    renderCollectionProgress(state.refreshProgress);
  } else if (!collectorRunning && !payload?.refresh_running && !state.oneClickActive) {
    renderCollectionProgress(null);
  }

  renderLocalOpsCollectors(collectors, sourceConfig, sourceStatus);
  scheduleLocalOpsPolling(collectorRunning || Boolean(payload?.refresh_running));

  if (collectorRunning) {
    setLocalOpsStatus("采集中", "warn");
  } else if (payload?.refresh_running) {
    setLocalOpsStatus("采集中", "warn");
  } else if (!sourceStatus.generated_at && !issues.length) {
    setLocalOpsStatus("等待状态", "");
  } else if (issues.some((issue) => issue.severity === "bad")) {
    setLocalOpsStatus("需要处理", "bad");
  } else if (issues.length) {
    setLocalOpsStatus("需要关注", "warn");
  } else {
    setLocalOpsStatus("状态正常", "ok");
  }

  if (!issues.length) {
    const empty = document.createElement("div");
    empty.className = "local-ops-empty";
    empty.textContent = "当前没有需要维护的渠道";
    localOpsIssuesEl.appendChild(empty);
    return;
  }

  issues.slice(0, 8).forEach((issue) => {
    const card = document.createElement("article");
    card.className = `local-ops-issue ${issue.severity || "warn"}`;
    const title = document.createElement("strong");
    title.textContent = issue.title || issue.id || "需要维护";
    const detail = document.createElement("span");
    detail.textContent = issue.detail || "";
    const action = document.createElement("em");
    action.textContent = issue.action || "";
    card.append(title, detail, action);
    if (issue.id === "bilibili_cookie_missing") {
      const cookie = sourceStatus.bilibili_cookie || {};
      const hint = document.createElement("small");
      hint.className = "local-ops-hint";
      hint.textContent = cookie.cookie_file_exists
        ? `已发现本地小号cookie文件：${cookie.cookie_file}。点“读取结果”会自动使用它。`
        : `推荐流程：点“打开B站小号登录”完成登录，再点“同步cookie”，最后点“读取结果”。`;
      card.appendChild(hint);
    }
    const actionRow = document.createElement("div");
    actionRow.className = "local-ops-actions";
    (Array.isArray(issue.fix_actions) ? issue.fix_actions : []).slice(0, 3).forEach((fixAction) => {
      if (fixAction.kind === "open_url" && fixAction.url) {
        const link = document.createElement("a");
        link.className = "local-ops-fix";
        link.href = fixAction.url;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        link.textContent = fixAction.label || "打开";
        link.addEventListener("click", () => setLocalOpsStatus(`已打开：${fixAction.label || "维护入口"}`, "ok"));
        actionRow.appendChild(link);
        return;
      }
      const button = document.createElement("button");
      button.type = "button";
      button.className = "local-ops-fix";
      button.textContent = fixAction.label || "修复";
      button.addEventListener("click", () => runLocalOpsFixAction(fixAction, button));
      actionRow.appendChild(button);
    });
    if (issue.source_id && (state.sourceConfig?.sources || []).some((source) => sourceConfigRuntimeIds(source).has(issue.source_id))) {
      const locate = document.createElement("button");
      locate.type = "button";
      locate.className = "local-ops-locate";
      locate.textContent = "定位信源";
      locate.addEventListener("click", () => selectSourceConfigByRuntimeId(issue.source_id));
      actionRow.appendChild(locate);
    }
    if (actionRow.childElementCount) card.appendChild(actionRow);
    localOpsIssuesEl.appendChild(card);
  });
}
async function loadLocalStatusFromServer(showErrors = false) {
  if (!localOpsSummaryEl) return null;
  try {
    const res = await fetch("./api/local-status", {
      headers: { Accept: "application/json" },
      cache: "no-store",
    });
    const payload = await res.json().catch(() => ({}));
    if (!res.ok || payload.ok === false) {
      throw new Error(payload.error || `HTTP ${res.status}`);
    }
    state.localOpsStatus = payload;
    renderLocalOpsStatus(payload);
    renderSourceConfig();
    return payload;
  } catch (err) {
    if (showErrors) {
      setLocalOpsStatus("本地后台未连接", "bad");
      localOpsIssuesEl.innerHTML = "";
      const card = document.createElement("article");
      card.className = "local-ops-issue bad";
      const title = document.createElement("strong");
      title.textContent = "无法读取本地采集状态";
      const detail = document.createElement("span");
      detail.textContent = err?.message || "unknown error";
      const action = document.createElement("em");
      action.textContent = "请用 scripts/local_server.py 启动本地后台。";
      card.append(title, detail, action);
      localOpsIssuesEl.appendChild(card);
    }
    return null;
  }
}
function setSourceConfigButton(button, label, disabled = false) {
  if (!button) return;
  button.textContent = label;
  button.disabled = Boolean(disabled);
}
function restoreSourceConfigButton(button, label, delay = 1200) {
  if (!button) return;
  window.setTimeout(() => {
    button.textContent = label;
    button.disabled = false;
  }, delay);
}
function selectedCollectionScope() {
  const value = sourceCollectionScopeSelectEl?.value === "all" ? "all" : "24h";
  try {
    window.localStorage.setItem(COLLECTION_SCOPE_STORAGE_KEY, value);
  } catch {}
  return value;
}
const ONE_CLICK_PLATFORM_TIMEOUT_MS = 12 * 60 * 1000;
const ONE_CLICK_POLL_MS = 3500;

function sleepMs(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}
async function startPlatformCollection(actionId) {
  try {
    const res = await fetch("./api/maintenance-action", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ action_id: actionId, collection_scope: selectedCollectionScope() }),
    });
    const payload = await res.json().catch(() => ({}));
    if (!res.ok || payload.ok === false) {
      return { ok: false, error: payload.error || `HTTP ${res.status}` };
    }
    return { ok: true };
  } catch (err) {
    return { ok: false, error: err?.message || "unknown error" };
  }
}
async function waitForCollectorDone(runtimeId, startedAt, label = "平台") {
  const deadline = Date.now() + ONE_CLICK_PLATFORM_TIMEOUT_MS;
  let sawRunning = false;
  await sleepMs(ONE_CLICK_POLL_MS);
  while (Date.now() < deadline) {
    const payload = await loadLocalStatusFromServer(false);
    const collector = payload?.collectors?.[runtimeId];
    if (collector) {
      if (collector.running && !sawRunning) {
        appendCollectionProgress(`${label}采集中`, { currentStep: `${label}采集中`, status: "running" });
        sawRunning = true;
      }
      const finished = collector.completed && !collector.running;
      const freshMs = collector.updated_at ? Date.parse(collector.updated_at) : 0;
      if (finished && (sawRunning || (freshMs && freshMs >= startedAt - 1500))) {
        appendCollectionProgress(`${label}采集结束`, { currentStep: `${label}采集结束`, status: "running" });
        return { done: true };
      }
    }
    await sleepMs(ONE_CLICK_POLL_MS);
  }
  return { done: false, reason: "timeout" };
}
async function runOneClickCollect() {
  if (state.oneClickActive) return;
  state.oneClickActive = true;
  setSourceConfigButton(oneClickCollectBtnEl, "一键采集中...", true);
  setSourceConfigButton(sourceConfigRefreshBtnEl, "刷新看板数据", true);

  const abort = (message) => {
    appendCollectionProgress(message, { percent: 100, currentStep: "一键采集失败", status: "failed" });
    setSourceConfigStatus(`${message}（可稍后手动点“刷新看板数据”继续）`, "bad");
    restoreSourceConfigButton(oneClickCollectBtnEl, "一键采集");
    restoreSourceConfigButton(sourceConfigRefreshBtnEl, "刷新看板数据");
    state.oneClickActive = false;
    loadLocalStatusFromServer(false);
  };

  try {
    appendCollectionProgress("准备启动抖音采集", { percent: 5, currentStep: "准备启动抖音采集", status: "running" });
    setSourceConfigStatus("① 启动抖音采集...（弹出的采集窗口如提示登录，请扫码）", "warn");
    const douyinStartedAt = Date.now();
    const douyinStart = await startPlatformCollection("start_mediacrawler_douyin");
    if (!douyinStart.ok) {
      abort(`抖音启动失败：${douyinStart.error}`);
      return;
    }
    const douyinDone = await waitForCollectorDone("mediacrawler_douyin", douyinStartedAt, "抖音");
    if (!douyinDone.done) {
      abort("抖音采集未在规定时间内完成");
      return;
    }

    appendCollectionProgress("抖音采集结束，接下来启动小红书采集", { percent: 32, currentStep: "启动小红书采集", status: "running" });
    setSourceConfigStatus("② 抖音已完成，启动小红书采集...（如提示登录，请扫码）", "warn");
    const xhsStartedAt = Date.now();
    const xhsStart = await startPlatformCollection("start_mediacrawler_xhs");
    if (!xhsStart.ok) {
      abort(`小红书启动失败：${xhsStart.error}`);
      return;
    }
    const xhsDone = await waitForCollectorDone("mediacrawler_xhs", xhsStartedAt, "小红书");
    if (!xhsDone.done) {
      abort("小红书采集未在规定时间内完成");
      return;
    }

    appendCollectionProgress("小红书采集结束，接下来刷新看板数据", { percent: 62, currentStep: "刷新看板数据", status: "running" });
    setSourceConfigStatus("③ 两个平台采集完成，正在刷新看板数据...", "warn");
    const refreshed = await refreshNewsDataFromLocalServer();
    if (refreshed) {
      setSourceConfigButton(oneClickCollectBtnEl, "已完成", true);
    } else {
      restoreSourceConfigButton(oneClickCollectBtnEl, "一键采集");
    }
  } catch (err) {
    abort(`一键采集出错：${err?.message || "unknown error"}`);
    return;
  } finally {
    state.oneClickActive = false;
  }
}
async function refreshNewsDataFromLocalServer() {
  const collectionScope = selectedCollectionScope();
  const scopeLabel = collectionScope === "all" ? "全量" : "自上次采集";
  setSourceConfigButton(sourceConfigRefreshBtnEl, "刷新中...", true);
  setSourceConfigStatus(`准备同步当前信源，并刷新${scopeLabel}看板数据；不会启动抖音/小红书采集。`, "warn");
  try {
    await writeSourceConfigToLocalServer({
      button: null,
      successLabel: "已保存",
      idleLabel: "保存高级配置",
    });
    setSourceConfigButton(sourceConfigRefreshBtnEl, "刷新中...", true);
    setSourceConfigStatus(`当前信源已同步，正在刷新${scopeLabel}看板数据；如刚新增抖音/小红书账号，请先点对应平台的“启动采集”。`, "warn");
    appendCollectionProgress(`开始刷新${scopeLabel}看板数据`, { percent: 3, currentStep: `刷新${scopeLabel}看板数据`, status: "running" });
    const res = await fetch("./api/refresh", {
      method: "POST",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
      },
      cache: "no-store",
      body: JSON.stringify({ collection_scope: collectionScope }),
    });
    const payload = await res.json().catch(() => ({}));
    if (!res.ok || payload.ok === false) {
      throw new Error(payload.error || `HTTP ${res.status}`);
    }
    if (payload.progress) {
      state.refreshProgress = payload.progress;
      renderCollectionProgress(payload.progress);
    }
    await waitForRefreshProgressDone();
    const latestStatus = await loadLocalStatusFromServer(false);
    const summary = latestStatus?.source_status || {};
    const sites = visibleSourceStatusSites(summary);
    const okSites = sites.filter((site) => site.ok).length;
    const totalItems = Number(summary.fetched_raw_items || 0);
    state.localOpsStatus = latestStatus || { source_config: state.localOpsStatus?.source_config || {}, source_status: summary };
    renderLocalOpsStatus(state.localOpsStatus);
    renderSourceConfig();
    setSourceConfigStatus(`${scopeLabel}看板刷新完成：${okSites}/${sites.length} 个源正常，读到 ${fmtNumber(totalItems)} 条；页面即将重载。`, "ok");
    setSourceConfigButton(sourceConfigRefreshBtnEl, "已完成", true);
    window.setTimeout(() => window.location.reload(), 1400);
    return true;
  } catch (err) {
    const message = err?.message || "unknown error";
    setSourceConfigStatus(`刷新失败：${message}`, "bad");
    setSourceConfigButton(sourceConfigRefreshBtnEl, "刷新失败", true);
    restoreSourceConfigButton(sourceConfigRefreshBtnEl, "刷新看板数据");
    loadLocalStatusFromServer(false);
    return false;
  }
}
function wait(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}
async function waitForLocalServerRestart() {
  await wait(1200);
  for (let attempt = 0; attempt < 12; attempt += 1) {
    try {
      const res = await fetch("./api/local-status", {
        headers: { Accept: "application/json" },
        cache: "no-store",
      });
      if (res.ok) return true;
    } catch (err) {
      // The server is expected to be briefly unavailable while it restarts.
    }
    await wait(700);
  }
  return false;
}
async function restartLocalServerFromPage() {
  setSourceConfigButton(localServerRestartBtnEl, "重启中...", true);
  setSourceConfigStatus("正在重启本地服务，稍等几秒后页面会自动刷新。", "warn");
  setLocalOpsStatus("本地服务重启中", "warn");
  try {
    const res = await fetch("./api/restart-local-server", {
      method: "POST",
      headers: { Accept: "application/json" },
      cache: "no-store",
    });
    const payload = await res.json().catch(() => ({}));
    if (!res.ok || payload.ok === false) {
      throw new Error(payload.error || `HTTP ${res.status}`);
    }
    const restarted = await waitForLocalServerRestart();
    if (restarted) {
      setSourceConfigStatus("本地服务已重启，正在刷新页面。", "ok");
      window.location.reload();
      return;
    }
    setSourceConfigStatus("重启请求已发送，但还没连回本地服务；请手动刷新页面。", "warn");
    restoreSourceConfigButton(localServerRestartBtnEl, "重启本地服务", 0);
  } catch (err) {
    const message = err?.message || "unknown error";
    setSourceConfigStatus(`重启失败：${message}`, "bad");
    setLocalOpsStatus("本地服务重启失败", "bad");
    restoreSourceConfigButton(localServerRestartBtnEl, "重启本地服务");
  }
}

function clusterBoleEvents(rows) {
  const clusters = new Map();
  rows.forEach((row) => {
    const key = eventKey(row.item);
    if (!clusters.has(key)) clusters.set(key, { key, rows: [], signals: new Set(), score: 0, primary: row });
    const cluster = clusters.get(key);
    cluster.rows.push(row);
    cluster.signals.add(sourceSignal(row.item));
    const currentPrimary = cluster.primary;
    const betterPrimary = sourcePriority(row.item) - sourcePriority(currentPrimary.item)
      || row.score - currentPrimary.score
      || timelineMs(row.item) - timelineMs(currentPrimary.item);
    if (betterPrimary > 0) cluster.primary = row;
  });
  return Array.from(clusters.values()).map((cluster) => {
    const signals = Array.from(cluster.signals);
    const maxScore = Math.max(...cluster.rows.map((row) => row.score));
    const sourceBonus = Math.min(12, Math.max(0, signals.length - 1) * 6);
    const candidateBonus = signals.some((s) => s === "AI HOT精选") ? 8
      : signals.some((s) => s === "HN热议" || s === "GitHub趋势") ? 6
      : signals.some((s) => s === "官方更新") ? 5
      : 0;
    return {
      item: cluster.primary.item,
      index: cluster.primary.index,
      rows: cluster.rows,
      sourceSignals: signals,
      sourceCount: signals.length,
      mergedCount: cluster.rows.length,
      score: Math.min(100, Math.round(maxScore + sourceBonus + candidateBonus)),
    };
  });
}
function storyTimeMs(story, key) {
  const iso = story && story[key];
  if (!iso) return 0;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? 0 : d.getTime();
}
function storyScore(story) {
  const raw = (story && (story.importance_score ?? story.score ?? story.importance)) || 0;
  const score = Number(raw);
  if (!Number.isFinite(score) || score <= 0) return 0;
  return Math.round(score <= 1 ? score * 100 : score);
}
function storyImportanceTone(label) {
  if (!label) return "watch";
  if (label.includes("重大")) return "hot";
  if (label.includes("官方")) return "official";
  if (label.includes("多源")) return "strong";
  if (label.includes("行业")) return "watch";
  return "watch";
}
function storyPrimaryTitleText(story) {
  const primary = (story && story.primary_item) || {};
  const bilingual = String(primary.title || (story && story.title) || "").trim();
  if (bilingual.includes(" / ")) {
    const [zh, en] = bilingual.split(" / ");
    return (zh || en || bilingual).trim();
  }
  return bilingual || "未命名更新";
}
function storyPrimaryEnText(story) {
  const primary = (story && story.primary_item) || {};
  const bilingual = String(primary.title || (story && story.title) || "").trim();
  if (bilingual.includes(" / ")) {
    const [, en] = bilingual.split(" / ");
    return (en || "").trim();
  }
  return "";
}
function storySourceCount(story) {
  const sources = Array.isArray(story && story.sources) ? story.sources : [];
  const explicit = Number(story && story.duplicate_count);
  if (Number.isFinite(explicit) && explicit > 0) return explicit;
  return Math.max(1, sources.length);
}
function storyDurationLabel(earliest, latest) {
  if (!earliest || !latest || earliest === latest) return "";
  const start = new Date(earliest).getTime();
  const end = new Date(latest).getTime();
  if (!Number.isFinite(start) || !Number.isFinite(end)) return "";
  const minutes = Math.round(Math.abs(end - start) / 60000);
  if (minutes < 20) return "短时集中";
  if (minutes < 60) return `发酵 ${minutes} 分钟`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest ? `发酵 ${hours}小时${rest}分` : `发酵 ${hours}小时`;
}
function pickBoleItems(items) {
  const ranked = [...items]
    .map((item, index) => ({ item, index, score: scorePercent(item) }))
    .filter((row) => row.score > 0)
    .sort((a, b) => {
      const byScore = b.score - a.score;
      if (byScore !== 0) return byScore;
      return timelineMs(b.item) - timelineMs(a.item) || a.index - b.index;
    });

  const sorted = clusterBoleEvents(ranked).sort((a, b) => {
    const byMultiSource = b.sourceCount - a.sourceCount;
    const byScore = b.score - a.score;
    return byMultiSource || byScore || timelineMs(b.item) - timelineMs(a.item) || a.index - b.index;
  });

  const picked = [];
  const addPick = (cluster) => {
    if (cluster && !picked.includes(cluster) && picked.length < 8) picked.push(cluster);
  };
  ["AI HOT精选", "HN热议", "GitHub趋势"].forEach((signal) => {
    addPick(sorted.find((cluster) => cluster.sourceSignals.includes(signal)));
  });
  sorted.forEach(addPick);
  return picked;
}
function boleReasonText(row) {
  const signals = row.sourceSignals || [];
  const sourceText = signals.length ? `来源命中：${signals.join(" / ")}` : "来源命中：单源";
  const mergeText = row.mergedCount > 1 ? `合并${row.mergedCount}条同事件` : "单条事件";
  return `${sourceText} · ${mergeText} · ${reasonText(row.item)}`;
}
function buildBoleLead(row) {
  const { item, score } = row;
  const lead = document.createElement("a");
  lead.className = "bole-lead-card";
  lead.href = item.url || "#";
  lead.target = "_blank";
  lead.rel = "noopener noreferrer";

  const top = document.createElement("div");
  top.className = "bole-lead-top";
  const kicker = document.createElement("span");
  kicker.className = "bole-kicker";
  kicker.textContent = `${labelText(item)} · ${fmtTime(timelineIso(item))}`;
  const scoreEl = document.createElement("strong");
  scoreEl.className = `bole-score-orb ${scoreTone(score)}`;
  scoreEl.innerHTML = `<span>${score}</span><small>分</small>`;
  top.append(kicker, scoreEl);

  const title = document.createElement("div");
  title.className = "bole-lead-title";
  title.textContent = itemTitleText(item);

  const reason = document.createElement("div");
  reason.className = "bole-lead-reason";
  reason.textContent = reasonText(item);

  const foot = document.createElement("div");
  foot.className = "bole-lead-foot";
  const site = document.createElement("span");
  site.textContent = item.site_name || "来源";
  const source = document.createElement("span");
  source.textContent = item.source || "未分区";
  foot.append(site, source);

  lead.append(top, title, reason, foot);
  return lead;
}
function buildBoleTimelineRow(row, rank) {
  const { item, score } = row;
  const link = document.createElement("a");
  link.className = "bole-row";
  link.href = item.url || "#";
  link.target = "_blank";
  link.rel = "noopener noreferrer";

  const time = document.createElement("time");
  time.className = "bole-row-time";
  time.textContent = fmtTime(timelineIso(item));

  const body = document.createElement("div");
  body.className = "bole-row-body";
  const meta = document.createElement("div");
  meta.className = "bole-row-meta";
  const rankEl = document.createElement("span");
  rankEl.textContent = `#${rank}`;
  const siteEl = document.createElement("span");
  siteEl.textContent = item.site_name || "来源";
  const scoreEl = document.createElement("strong");
  scoreEl.textContent = `${score}分`;
  meta.append(rankEl, siteEl, scoreEl);
  (row.sourceSignals || []).slice(0, 4).forEach((signal) => {
    appendSourceChip(meta, signal, sourceSignalTone(signal), "source-chip source-hit");
  });
  const title = document.createElement("div");
  title.className = "bole-row-title";
  title.textContent = itemTitleText(item);
  const reason = document.createElement("div");
  reason.className = "bole-row-reason";
  reason.textContent = boleReasonText(row);
  body.append(meta, title, reason);

  link.append(time, body);
  return link;
}
function buildStoryCard(story, rank) {
  const link = document.createElement("a");
  link.className = "story-row";
  const primary = story.primary_item || {};
  link.href = primary.url || story.primary_url || story.url || "#";
  link.target = "_blank";
  link.rel = "noopener noreferrer";

  const time = document.createElement("div");
  time.className = "story-time";
  const { latest, rangeLabel } = formatStoryTime(story);
  const labelEl = document.createElement("span");
  labelEl.className = "story-time-label";
  labelEl.textContent = "最新";
  const latestEl = document.createElement("span");
  latestEl.className = "story-time-latest";
  latestEl.textContent = fmtTime(latest);
  time.append(labelEl, latestEl);
  if (rangeLabel) {
    const rangeEl = document.createElement("span");
    rangeEl.className = "story-time-range";
    rangeEl.textContent = rangeLabel;
    rangeEl.title = "最早来源到最新来源的时间差，不是距离现在多久。";
    time.appendChild(rangeEl);
  }

  const body = document.createElement("div");
  body.className = "story-body";

  const meta = document.createElement("div");
  meta.className = "story-meta";
  const rankEl = document.createElement("span");
  rankEl.className = "story-rank";
  rankEl.textContent = `#${rank}`;
  meta.appendChild(rankEl);
  if (story.importance_label) {
    const imp = document.createElement("span");
    imp.className = `story-importance ${storyImportanceTone(story.importance_label)}`;
    imp.textContent = story.importance_label;
    meta.appendChild(imp);
  }
  const sourceCount = storySourceCount(story);
  const countEl = document.createElement("span");
  countEl.className = "story-count";
  countEl.textContent = `${sourceCount} 个来源`;
  meta.appendChild(countEl);
  const displayScore = storySortScore(story);
  if (displayScore > 0) {
    const scoreEl = document.createElement("strong");
    scoreEl.className = `story-score ${state.boleView === "hot" ? "heat" : ""}`.trim();
    scoreEl.title = state.boleView === "hot"
      ? "热度分 = 多源强度 × 时间衰减"
      : "编辑重要性分";
    scoreEl.innerHTML = `<span>${displayScore}</span><small>${state.boleView === "hot" ? "热度" : "分"}</small>`;
    meta.appendChild(scoreEl);
  }
  body.appendChild(meta);

  const sources = Array.isArray(story.sources) ? story.sources : [];
  if (sources.length) {
    const sourcesEl = document.createElement("div");
    sourcesEl.className = "story-sources";
    sources.slice(0, 6).forEach((src) => {
      const kind = sourceKind(src.site_id);
      const label = src.source || src.source_name || "来源";
      const tag = sourceChip(label, kind.tone, "story-source-chip source-chip");
      sourcesEl.appendChild(tag);
    });
    if (sources.length > 6) {
      const more = document.createElement("span");
      more.className = "story-source-more";
      more.textContent = `+${sources.length - 6}`;
      sourcesEl.appendChild(more);
    }
    body.appendChild(sourcesEl);
  }

  const title = document.createElement("div");
  title.className = "story-title";
  const primaryTitle = storyPrimaryTitleText(story);
  const enTitle = storyPrimaryEnText(story);
  if (enTitle && enTitle !== primaryTitle) {
    const zh = document.createElement("span");
    zh.className = "story-title-zh";
    zh.textContent = primaryTitle;
    const sub = document.createElement("span");
    sub.className = "story-title-en";
    sub.textContent = enTitle;
    title.append(zh, sub);
  } else {
    title.textContent = primaryTitle;
  }
  body.appendChild(title);

  link.append(time, body);
  return link;
}
function storyHotness(story) {
  const sources = storySourceCount(story);
  if (sources < 2) return 0;
  const latest = storyTimeMs(story, "latest_at") || storyTimeMs(story, "earliest_at");
  const ageHours = latest ? Math.max(0, (Date.now() - latest) / 3600000) : 24;
  return (sources - 1) * Math.exp(-ageHours / HOT_DECAY_HOURS);
}
function storyHotScore(story) {
  const raw = storyHotness(story);
  if (raw <= 0) return 0;
  return Math.max(1, Math.min(100, Math.round(raw * HOT_SCORE_SCALE)));
}
function storySortScore(story) {
  return state.boleView === "hot" ? storyHotScore(story) : storyScore(story);
}
function renderBoleBrief(stories) {
  bolePicksListEl.innerHTML = "";
  bolePicksListEl.className = "bole-board";

  const hot = hotStories(stories);
  const hotAvailable = hot.length >= 2;
  // 宁缺毋滥: the hot view only exists when there is real multi-source heat.
  if (boleViewToggleEl) boleViewToggleEl.hidden = !hotAvailable;
  if (!hotAvailable) state.boleView = "timeline";
  if (boleHotBtnEl) boleHotBtnEl.classList.toggle("active", state.boleView === "hot");
  if (boleTimelineBtnEl) boleTimelineBtnEl.classList.toggle("active", state.boleView !== "hot");

  let sorted;
  let metaLabel;
  if (state.boleView === "hot") {
    sorted = hot;
    metaLabel = `当前热点 · ${fmtNumber(sorted.length)} 簇 · 按热度分排序`;
  } else {
    sorted = [...stories].sort((a, b) => {
      const aLatest = storyTimeMs(a, "latest_at") || storyTimeMs(a, "earliest_at");
      const bLatest = storyTimeMs(b, "latest_at") || storyTimeMs(b, "earliest_at");
      if (aLatest !== bLatest) return bLatest - aLatest;
      return storyScore(b) - storyScore(a);
    });
    const topScore = Math.max(...sorted.map((s) => storyScore(s)));
    metaLabel = topScore > 0
      ? `故事时间线 · ${fmtNumber(sorted.length)} 条 · 最高 ${topScore} 分`
      : `故事时间线 · ${fmtNumber(sorted.length)} 条`;
  }

  const list = document.createElement("div");
  list.className = "bole-compact-list bole-timeline";
  const defaultLimit = state.boleView === "hot" ? BOLE_HOT_LIMIT : BOLE_TIMELINE_LIMIT;
  const visibleStories = state.boleExpanded ? sorted : sorted.slice(0, defaultLimit);
  visibleStories.forEach((story, index) => {
    list.appendChild(buildStoryCard(story, index + 1));
  });
  bolePicksListEl.appendChild(list);

  if (sorted.length > defaultLimit) {
    const moreBtn = document.createElement("button");
    moreBtn.type = "button";
    moreBtn.className = "bole-more-btn";
    moreBtn.textContent = state.boleExpanded
      ? "收起"
      : (state.boleView === "hot" ? "展开全部热点" : "展开完整时间线");
    moreBtn.addEventListener("click", () => {
      state.boleExpanded = !state.boleExpanded;
      renderBolePicks();
    });
    bolePicksListEl.appendChild(moreBtn);
  }

  const generatedAt = state.dailyBrief && state.dailyBrief.generated_at;
  bolePicksMetaEl.textContent = generatedAt ? `${metaLabel} · ${fmtTime(generatedAt)}` : metaLabel;
  document.dispatchEvent(new CustomEvent("aiRadar:briefRendered"));
}
function renderBoleFallback(picks) {
  bolePicksListEl.innerHTML = "";
  bolePicksListEl.className = "bole-board";

  const note = document.createElement("div");
  note.className = "bole-fallback-note";
  note.textContent = "故事合并数据暂未生成，先展示伯乐候选信号。";
  bolePicksListEl.appendChild(note);

  if (!picks.length) {
    const empty = document.createElement("div");
    empty.className = "bole-empty";
    empty.textContent = "当前数据里没有可展示的评分字段。";
    bolePicksListEl.appendChild(empty);
    return;
  }

  const timelinePicks = [...picks].sort((a, b) => {
    const byTime = timelineMs(b.item) - timelineMs(a.item);
    if (byTime !== 0) return byTime;
    return b.score - a.score || a.index - b.index;
  });
  const list = document.createElement("div");
  list.className = "bole-compact-list";
  const visiblePicks = state.boleExpanded ? timelinePicks : timelinePicks.slice(0, BOLE_TIMELINE_LIMIT);
  visiblePicks.forEach((row, index) => {
    list.appendChild(buildBoleTimelineRow(row, index + 1));
  });
  bolePicksListEl.appendChild(list);
  if (timelinePicks.length > BOLE_TIMELINE_LIMIT) {
    const moreBtn = document.createElement("button");
    moreBtn.type = "button";
    moreBtn.className = "bole-more-btn";
    moreBtn.textContent = state.boleExpanded ? "收起" : "展开完整时间线";
    moreBtn.addEventListener("click", () => {
      state.boleExpanded = !state.boleExpanded;
      renderBolePicks();
    });
    bolePicksListEl.appendChild(moreBtn);
  }
  document.dispatchEvent(new CustomEvent("aiRadar:briefRendered"));
}
function storyMatchesFilteredItems(story, filteredItems) {
  if (
    state.activeSection === "creator" &&
    !state.siteFilter &&
    !state.authorFilter &&
    !state.sourceTypeFilter &&
    !state.signalLevelFilter &&
    !state.query.trim()
  ) return true;
  const urls = new Set(filteredItems.map((item) => item.url).filter(Boolean));
  const ids = new Set(filteredItems.map((item) => item.id).filter(Boolean));
  const storyRefs = [
    story.primary_item,
    ...(Array.isArray(story.sources) ? story.sources : []),
    ...(Array.isArray(story.items) ? story.items : []),
  ].filter(Boolean);
  return storyRefs.some((ref) => (ref.url && urls.has(ref.url)) || (ref.id && ids.has(ref.id)));
}
function briefStories() {
  return Array.isArray(state.dailyBrief?.items) ? state.dailyBrief.items : [];
}
function mergedStories() {
  return Array.isArray(state.storiesMerged?.stories) ? state.storiesMerged.stories : [];
}
function storyStableKey(story) {
  if (!story) return "";
  return story.story_id || story.primary_url || story.url || story.primary_item?.url || story.title || "";
}
function uniqueStories(stories, excludeKeys = new Set(), excludeIdentityKeys = new Set()) {
  const seen = new Set(excludeKeys);
  return stories.filter((story) => {
    const key = storyStableKey(story);
    if (key && seen.has(key)) return false;
    if (storyHasAnyKey(story, excludeIdentityKeys)) return false;
    if (key) seen.add(key);
    return true;
  });
}
function currentStoryPools(filteredItems) {
  if (isSubscriptionSection(state.activeSection)) return { brief: [], merged: [], followup: [] };
  const brief = briefStories().filter((story) => storyMatchesFilteredItems(story, filteredItems));
  const merged = mergedStories().filter((story) => storyMatchesFilteredItems(story, filteredItems));
  const briefKeys = new Set(brief.map(storyStableKey).filter(Boolean));
  const briefIdentityKeys = new Set();
  brief.forEach((story) => storyIdentityKeys(story).forEach((key) => briefIdentityKeys.add(key)));
  return {
    brief,
    merged,
    followup: uniqueStories(merged, briefKeys, briefIdentityKeys),
  };
}
function storyRowsForPool(stories) {
  const source = Array.isArray(stories) ? stories : [];
  const pool = state.boleView === "hot"
    ? hotStories(source).slice(0, BOLE_HOT_LIMIT)
    : latestStories(source).slice(0, BOLE_TIMELINE_LIMIT);
  return pool.map(storyToBoleRow);
}
function storyCandidateCounts(stories) {
  const source = Array.isArray(stories) ? stories : [];
  const hotTotal = hotStories(source).length;
  const timelineTotal = source.length;
  return {
    hot: Math.min(BOLE_HOT_LIMIT, hotTotal),
    timeline: Math.min(BOLE_TIMELINE_LIMIT, timelineTotal),
    hotTotal,
    timelineTotal,
  };
}
function renderStoryViewPanel(stories, excludedRows = []) {
  const panel = document.createElement("div");
  panel.className = "bole-story-panel";

  const hot = hotStories(stories);
  let baseSorted;
  let metaLabel;
  if (state.boleView === "hot") {
    baseSorted = hot;
    metaLabel = hot.length
      ? `当前热点 · ${fmtNumber(hot.length)} 簇 · 按热度分排序`
      : "当前热点 · 暂无多源聚簇";
  } else {
    baseSorted = [...stories].sort((a, b) => {
      const aLatest = storyTimeMs(a, "latest_at") || storyTimeMs(a, "earliest_at");
      const bLatest = storyTimeMs(b, "latest_at") || storyTimeMs(b, "earliest_at");
      if (aLatest !== bLatest) return bLatest - aLatest;
      return storyScore(b) - storyScore(a);
    });
    metaLabel = `故事时间线 · ${fmtNumber(baseSorted.length)} 条 · 最新优先`;
  }

  const excludeKeys = excludedStoryKeySet(excludedRows);
  const sorted = excludeKeys.size
    ? baseSorted.filter((story) => !storyHasAnyKey(story, excludeKeys))
    : baseSorted;
  const skippedCount = baseSorted.length - sorted.length;
  const rankOffset = skippedCount > 0 ? excludedRows.length : 0;
  if (skippedCount > 0) {
    metaLabel = state.boleView === "hot"
      ? `当前热点 · ${fmtNumber(baseSorted.length)} 簇 · 续看 #${rankOffset + 1} 起`
      : `故事时间线 · ${fmtNumber(baseSorted.length)} 条 · Top3 后续`;
  }

  if (boleViewToggleEl) {
    boleViewToggleEl.hidden = false;
    if (boleHotBtnEl) boleHotBtnEl.classList.toggle("active", state.boleView === "hot");
    if (boleTimelineBtnEl) boleTimelineBtnEl.classList.toggle("active", state.boleView !== "hot");
  }

  const heading = document.createElement("div");
  heading.className = "bole-story-panel-head";
  heading.textContent = metaLabel;
  panel.appendChild(heading);

  if (!sorted.length) {
    const empty = document.createElement("div");
    empty.className = "bole-empty";
    empty.textContent = skippedCount > 0
      ? "Top3 已覆盖当前筛选下的故事，可切换筛选或时间线继续查看。"
      : state.boleView === "hot"
      ? "当前筛选下没有多源热点，可切换到时间线查看最新故事。"
      : "当前筛选下没有可展示的故事时间线。";
    panel.appendChild(empty);
    return panel;
  }

  const list = document.createElement("div");
  list.className = "bole-compact-list bole-timeline";
  const defaultLimit = state.boleView === "hot" ? BOLE_HOT_LIMIT : BOLE_TIMELINE_LIMIT;
  const visibleStories = state.boleExpanded ? sorted : sorted.slice(0, defaultLimit);
  visibleStories.forEach((story, index) => {
    list.appendChild(buildStoryCard(story, rankOffset + index + 1));
  });
  panel.appendChild(list);

  if (sorted.length > defaultLimit) {
    const moreBtn = document.createElement("button");
    moreBtn.type = "button";
    moreBtn.className = "bole-more-btn";
    moreBtn.textContent = state.boleExpanded
      ? "收起"
      : (skippedCount > 0
        ? (state.boleView === "hot" ? "展开后续热点" : "展开后续时间线")
        : (state.boleView === "hot" ? "展开全部热点" : "展开完整时间线"));
    moreBtn.addEventListener("click", () => {
      state.boleExpanded = !state.boleExpanded;
      renderBolePicks();
    });
    panel.appendChild(moreBtn);
  }

  return panel;
}
function storyToBoleRow(story, index) {
  const enrichStoryItem = (entry) => ({
    ...entry,
    site_name: entry.site_name || entry.source_name || story.source_name || "",
  });
  const item = enrichStoryItem(story.primary_item || story);
  const sourceItems = [
    item,
    ...(Array.isArray(story.sources) ? story.sources.map(enrichStoryItem) : []),
  ].filter(Boolean);
  const sourceSignals = Array.from(new Set(sourceItems.map(sourceSignal)));
  return {
    item,
    index,
    story,
    rows: sourceItems.map((sourceItem) => ({ item: sourceItem })),
    sourceSignals,
    sourceCount: storySourceCount(story),
    mergedCount: Math.max(1, Number(story.duplicate_count) || sourceItems.length),
    score: storySortScore(story),
  };
}
function rankedBriefRows(stories) {
  const sorted = [...stories].sort((a, b) => {
    const aLatest = storyTimeMs(a, "latest_at") || storyTimeMs(a, "earliest_at");
    const bLatest = storyTimeMs(b, "latest_at") || storyTimeMs(b, "earliest_at");
    if (state.boleView === "hot") {
      const byHeat = storyHotScore(b) - storyHotScore(a);
      if (byHeat !== 0) return byHeat;
      const byScore = storyScore(b) - storyScore(a);
      if (byScore !== 0) return byScore;
      return bLatest - aLatest;
    }
    const byScore = storyScore(b) - storyScore(a);
    if (byScore !== 0) return byScore;
    return bLatest - aLatest;
  });
  return sorted.map(storyToBoleRow);
}
function rankedFallbackRows(items) {
  const rows = rankedClustersForItems(items);
  return state.boleView === "hot"
    ? rows.sort((a, b) => b.sourceCount - a.sourceCount || b.score - a.score || timelineMs(b.item) - timelineMs(a.item))
    : rows.sort((a, b) => timelineMs(b.item) - timelineMs(a.item) || b.score - a.score);
}
function buildBoleFollowupPanel(rows, topCount, usesStories) {
  const remaining = rows.slice(topCount);
  if (!remaining.length) return null;

  const panel = document.createElement("div");
  panel.className = "bole-story-panel";
  const heading = document.createElement("div");
  heading.className = "bole-story-panel-head";
  const viewLabel = state.boleView === "hot" ? "当前热点" : "故事时间线";
  heading.textContent = `${viewLabel} · ${fmtNumber(rows.length)} 条${usesStories ? "故事" : "候选"} · Top${topCount} 后续`;
  panel.appendChild(heading);

  const list = document.createElement("div");
  list.className = "bole-compact-list bole-timeline";
  const followupLimit = 2;
  const visibleRows = state.boleExpanded ? remaining : remaining.slice(0, followupLimit);
  visibleRows.forEach((row, index) => {
    const rank = topCount + index + 1;
    list.appendChild(row.story
      ? buildStoryCard(row.story, rank)
      : buildBoleTimelineRow(row, rank));
  });
  panel.appendChild(list);

  if (remaining.length > followupLimit) {
    const moreBtn = document.createElement("button");
    moreBtn.type = "button";
    moreBtn.className = "bole-more-btn";
    moreBtn.textContent = state.boleExpanded
      ? "收起后续"
      : `展开后续 ${fmtNumber(remaining.length - followupLimit)} 条`;
    moreBtn.addEventListener("click", () => {
      state.boleExpanded = !state.boleExpanded;
      renderBolePicks();
    });
    panel.appendChild(moreBtn);
  }
  return panel;
}
function renderBolePicks() {
  if (!bolePicksListEl || !bolePicksMetaEl) return;
  bolePicksListEl.innerHTML = "";
  bolePicksListEl.className = "top-stories-grid";
  if (boleViewToggleEl) boleViewToggleEl.hidden = true;
  if (bolePicksWrapEl) bolePicksWrapEl.hidden = false;

  const section = SECTION_BY_ID[state.activeSection] || SECTION_BY_ID.creator;
  const filtered = getFilteredItems();
  const storyPools = currentStoryPools(filtered);
  const availableStoryPool = storyPools.brief.length
    ? [...storyPools.brief, ...storyPools.followup]
    : storyPools.merged;
  const usesStories = availableStoryPool.length > 0;
  const candidateCounts = storyCandidateCounts(availableStoryPool);
  const hotAvailable = usesStories && candidateCounts.hot >= 2;
  if (usesStories && !hotAvailable && state.boleView === "hot") {
    state.boleView = "timeline";
  }
  const defaultLimit = state.boleView === "hot" ? BOLE_HOT_LIMIT : BOLE_TIMELINE_LIMIT;
  const rows = usesStories
    ? storyRowsForPool(availableStoryPool)
    : rankedFallbackRows(filtered).slice(0, defaultLimit);
  const top = rows.slice(0, 3);
  const remainingCount = Math.max(0, rows.length - top.length);
  if (topStoriesTitleEl) topStoriesTitleEl.textContent = `${section.label}重点信号`;
  const storyMeta = usesStories
    ? `展示池：热点 ${fmtNumber(candidateCounts.hot)}/${fmtNumber(candidateCounts.hotTotal)} · 时间线 ${fmtNumber(candidateCounts.timeline)}/${fmtNumber(candidateCounts.timelineTotal)}`
    : `展示池：${fmtNumber(rows.length)} 条`;
  bolePicksMetaEl.textContent = storyMeta;
  if (boleViewToggleEl) {
    boleViewToggleEl.hidden = usesStories ? !hotAvailable : true;
    if (boleHotBtnEl) boleHotBtnEl.classList.toggle("active", state.boleView === "hot");
    if (boleTimelineBtnEl) boleTimelineBtnEl.classList.toggle("active", state.boleView === "timeline");
    if (boleHotBtnEl) boleHotBtnEl.textContent = `当前热点 ${fmtNumber(candidateCounts.hot)}`;
    if (boleTimelineBtnEl) boleTimelineBtnEl.textContent = `时间线 ${fmtNumber(candidateCounts.timeline)}`;
  }

  if (!top.length) {
    const empty = document.createElement("div");
    empty.className = "bole-empty";
    empty.textContent = "当前栏目和筛选条件下没有可展示的 Top 3。";
    bolePicksListEl.appendChild(empty);
  } else {
    top.forEach((row, index) => {
      bolePicksListEl.appendChild(buildTopStoryCard(row, index + 1));
    });
  }

  const followup = buildBoleFollowupPanel(rows, top.length, usesStories);
  if (followup) {
    bolePicksListEl.appendChild(followup);
  }
  document.dispatchEvent(new CustomEvent("aiRadar:briefRendered"));
}
function rankedClustersForItems(items) {
  const rows = [...items]
    .map((item, index) => ({
      item,
      index,
      score: isSubscriptionSection(state.activeSection)
        ? creatorHotScore(item)
        : (scorePercent(item) || Math.round(itemPriorityScore(item))),
    }))
    .filter((row) => row.item && (row.score > 0 || row.item.title))
    .sort((a, b) => itemPriorityScore(b.item) - itemPriorityScore(a.item) || timelineMs(b.item) - timelineMs(a.item));

  return clusterBoleEvents(rows).sort((a, b) => {
    const byHeadlineScore = headlineClusterScore(b) - headlineClusterScore(a);
    if (byHeadlineScore !== 0) return byHeadlineScore;
    return timelineMs(b.item) - timelineMs(a.item) || a.index - b.index;
  });
}
function headlineClusterScore(cluster) {
  const base = itemPriorityScore(cluster.item);
  const sourceBoost = Math.min(18, Math.max(0, cluster.sourceCount - 1) * 9);
  const mergeBoost = Math.min(8, Math.max(0, cluster.mergedCount - 1) * 4);
  return Math.min(100, Math.round(base + sourceBoost + mergeBoost));
}
function itemTagLabels(item, row = null) {
  const tags = [];
  const sections = itemSections(item);
  tags.push(sectionBadgeLabel(state.activeSection));
  if (row && (row.sourceCount > 1 || row.mergedCount > 1)) tags.push("多源验证");
  if (item.site_id === "official_ai") tags.push("官方");
  if (item.site_id === "aihot") tags.push("AI HOT");
  if (sections.has("models")) tags.push("模型发布");
  if (sections.has("devtools")) tags.push("开发者");
  if (sections.has("hn")) tags.push("社区热议");
  if (sections.has("research")) tags.push("研究");
  if (sections.has("creator")) tags.push("我的订阅");
  if (sections.has("community")) tags.push("社区");
  return Array.from(new Set(tags)).slice(0, 3);
}
function itemSourceRefs(item, row = null) {
  const refs = [];
  const seen = new Set();
  const add = (label, tone) => {
    const clean = String(label || "").trim();
    if (!clean) return;
    const key = `${tone}:${clean}`;
    if (seen.has(key)) return;
    seen.add(key);
    refs.push({ label: clean, tone });
  };

  if (row && Array.isArray(row.sourceSignals) && row.sourceSignals.length) {
    row.sourceSignals.forEach((signal) => add(signal, sourceSignalTone(signal)));
  } else if (row && Array.isArray(row.rows) && row.rows.length) {
    row.rows.forEach((entry) => {
      const sourceItem = entry.item || {};
      const kind = sourceKind(sourceItem.site_id);
      add(sourceItem.source || sourceItem.site_name || kind.label, kind.tone);
    });
  } else {
    const kind = sourceKind(item.site_id);
    add(item.source || item.site_name || kind.label, kind.tone);
  }

  return refs.length ? refs : [{ label: "来源", tone: "default" }];
}
function priorityGrade(score) {
  if (score >= 92) return "A+";
  if (score >= 82) return "A";
  if (score >= 70) return "B";
  return "C";
}
function rowSourceCount(row) {
  const item = row.item || {};
  const refs = itemSourceRefs(item, row);
  const storyCount = row.story ? storySourceCount(row.story) : 0;
  return Math.max(1, refs.length, Number(row.sourceCount || 0), Number(row.mergedCount || 0), storyCount);
}
function signalSummaryText(row) {
  const item = row.item || {};
  const story = row.story || {};
  const label = story.importance_label || labelText(item);
  const sourceCount = rowSourceCount(row);
  const multi = row.sourceCount > 1 || row.mergedCount > 1;
  if (multi && label) return `${label}信号，已被 ${fmtNumber(sourceCount)} 个来源验证，适合优先判断是否继续深挖。`;
  const reason = reasonText(item);
  if (reason && !reason.startsWith("来源与标题")) return reason.replace(/^命中方向：/, "核心方向：");
  return `${label}方向的新近更新，已进入 24 小时 AI 强相关池。`;
}
function whyImportantText(row) {
  const item = row.item || {};
  const story = row.story || {};
  const sections = itemSections(item);
  const reasons = Array.isArray(story.reasons) ? story.reasons : [];
  if (reasons.includes("official_source") && reasons.includes("multi_source")) {
    return "一手来源和聚合来源同时出现，说明它既有事实起点，也正在被外部信息流放大。";
  }
  if (sections.has("models")) {
    return "模型能力或训练/推理方式变化会影响后续产品路线、开发者选型和评测基准。";
  }
  if (sections.has("devtools")) {
    return "开发者工具和基础设施变化通常会很快传导到团队工作流、成本和可实现能力。";
  }
  if (sections.has("industry")) {
    return "公司、监管、芯片或资本动态会改变 AI 生态的资源分配和落地节奏。";
  }
  if (sections.has("research")) {
    return "研究信号可能还没产品化，但会提示下一轮模型、数据或方法的技术方向。";
  }
  if (sections.has("community") || sections.has("hn")) {
    return "社区集中讨论代表开发者和早期用户正在形成共识，适合作为趋势验证入口。";
  }
  return "它在当前 24 小时窗口里同时具备相关度、新鲜度和来源权重，值得先读原文确认。";
}
function impactLabels(item) {
  const sections = itemSections(item);
  const labels = [];
  if (sections.has("devtools")) labels.push("开发者");
  if (sections.has("products")) labels.push("产品");
  if (sections.has("industry")) labels.push("企业 / 投资");
  if (sections.has("research")) labels.push("研究");
  if (sections.has("models")) labels.push("模型团队");
  if (sections.has("community") || sections.has("hn")) labels.push("社区");
  return labels.slice(0, 3).length ? labels.slice(0, 3) : ["AI 观察者"];
}
function buildTopStoryCard(row, rank) {
  const item = row.item;
  const link = document.createElement("a");
  link.className = `top-story-card ${rank === 1 ? "lead" : "secondary"}`;
  link.href = item.url || "#";
  link.target = "_blank";
  link.rel = "noopener noreferrer";

  const rankEl = document.createElement("span");
  rankEl.className = "top-rank";
  rankEl.textContent = `#${rank}`;

  const meta = document.createElement("div");
  meta.className = "intel-meta";
  const time = document.createElement("time");
  // Brief stories keep their timeline on the story object rather than repeating
  // it on primary_item. Fall back to that aggregate time so Top 3 never shows
  // "时间未知" when the story itself has a verified latest/earliest timestamp.
  const storyTimeline = row.story?.latest_at || row.story?.earliest_at || "";
  time.textContent = fmtTime(timelineIso(item) || storyTimeline);
  const primarySource = itemSourceRefs(item, row)[0];
  const score = document.createElement("strong");
  const displayScore = row.story
    ? Math.max(row.score || 0, storyScore(row.story))
    : Math.max(row.score || 0, headlineClusterScore(row));
  score.className = `intel-score ${scoreTone(displayScore)}`;
  score.textContent = `优先级 ${priorityGrade(displayScore)}`;
  const sourceCount = document.createElement("span");
  sourceCount.className = "source-count";
  sourceCount.textContent = `${fmtNumber(rowSourceCount(row))} 个来源`;
  meta.append(rankEl, sourceChip(primarySource.label, primarySource.tone, "source-chip intel-source"), sourceCount, score, time);

  const title = document.createElement("div");
  title.className = "top-story-title";
  title.textContent = itemTitleText(item);

  const summary = document.createElement("p");
  summary.className = "top-story-summary";
  summary.textContent = signalSummaryText(row);

  const why = document.createElement("div");
  why.className = "top-story-why";
  const whyLabel = document.createElement("span");
  whyLabel.textContent = "为什么重要";
  const whyText = document.createElement("p");
  whyText.textContent = whyImportantText(row);
  why.append(whyLabel, whyText);

  const tags = document.createElement("div");
  tags.className = "intel-tags";
  itemTagLabels(item, row).forEach((label) => {
    tags.appendChild(itemTagChip(label));
  });

  const impact = document.createElement("div");
  impact.className = "impact-row";
  impactLabels(item).forEach((label) => {
    const chip = document.createElement("span");
    chip.textContent = label;
    impact.appendChild(chip);
  });

  link.append(meta, title, summary, why, tags, impact);
  return link;
}
function buildIntelCard(item, rank) {
  const card = document.createElement("article");
  card.className = "intel-card";

  const meta = document.createElement("div");
  meta.className = "intel-card-meta";
  const rankEl = document.createElement("span");
  rankEl.className = "intel-card-rank";
  rankEl.textContent = `#${rank}`;
  const time = document.createElement("time");
  time.textContent = fmtTime(timelineIso(item));
  const score = scorePercent(item);
  const scoreEl = document.createElement("strong");
  scoreEl.className = `intel-score ${scoreTone(score)}`;
  scoreEl.textContent = score ? `AI ${score}分` : "AI观察";
  meta.append(rankEl, time, scoreEl);

  const title = document.createElement("a");
  title.className = "intel-title";
  title.href = item.url || "#";
  title.target = "_blank";
  title.rel = "noopener noreferrer";
  title.textContent = itemTitleText(item);

  const reason = document.createElement("p");
  reason.className = "intel-reason";
  reason.textContent = reasonText(item);

  const tags = document.createElement("div");
  tags.className = "intel-tags";
  itemTagLabels(item).forEach((label) => {
    tags.appendChild(itemTagChip(label));
  });

  const sources = document.createElement("div");
  sources.className = "intel-card-sources";
  const refs = itemSourceRefs(item);
  const count = document.createElement("strong");
  count.textContent = `${fmtNumber(refs.length)} 个来源`;
  sources.appendChild(count);
  refs.slice(0, 3).forEach((ref) => {
    sources.appendChild(sourceChip(ref.label, ref.tone, "source-chip"));
  });

  card.append(meta, title, reason, tags, sources);
  return card;
}
function feedSummaryText(item) {
  const signals = Array.isArray(item.ai_signals) ? item.ai_signals.filter(Boolean).slice(0, 2) : [];
  if (signals.length) return `相关线索：${signals.join(" / ")}。`;
  const reason = reasonText(item);
  if (reason && !reason.startsWith("来源与标题")) return reason.replace(/^命中方向：/, "相关线索：");
  return `${labelText(item)} · AI 相关度 ${scorePercent(item) || "待评估"}。`;
}
function timelineItemDate(item) {
  const date = new Date(timelineIso(item));
  return Number.isNaN(date.getTime()) ? null : date;
}
function timelineDayKey(item) {
  const date = timelineItemDate(item);
  if (!date) return "unknown";
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}
function timelineClockText(date) {
  return new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).format(date);
}
function timelineDateText(date) {
  return `${date.getMonth() + 1}月${date.getDate()}日`;
}
function timelineWeekdayText(date) {
  return ["星期日", "星期一", "星期二", "星期三", "星期四", "星期五", "星期六"][date.getDay()];
}
function renderItemNode(item, context = {}) {
  const node = itemTpl.content.firstElementChild.cloneNode(true);
  const platformKey = itemPlatformSection(item) || "rss";
  node.classList.add(`platform-${platformKey}`);
  if (item.id) node.dataset.itemId = String(item.id);

  const avatarEl = node.querySelector(".card-avatar");
  const avatarText = String(item.source || item.site_name || sourceDisplayName(item) || "源").trim();
  if (avatarEl) avatarEl.textContent = Array.from(avatarText)[0] || "源";

  const metaRow = node.querySelector(".meta-row");
  const siteEl = node.querySelector(".site");
  siteEl.textContent = item.source || item.site_name;
  if (context.source && context.source === item.source) {
    siteEl.hidden = true;
  }
  const kind = sourceKind(item.site_id);
  const categoryEl = node.querySelector(".category");
  categoryEl.textContent = kind.label;
  categoryEl.classList.add(`kind-${kind.tone}`);
  const score = scorePercent(item);
  const creatorScore = creatorHotScore(item);
  const tagEl = document.createElement("span");
  tagEl.className = `ai-tag tone-${itemLabelTone(item)}`;
  tagEl.textContent = creatorScore && itemSections(item).has("creator")
    ? `订阅热度 · ${creatorScore}分`
    : `${labelText(item)} · ${score || "?"}分`;
  categoryEl.insertAdjacentElement("afterend", tagEl);

  const sourceEl = node.querySelector(".source");
  const sourceLabel = sourceSignal(item);
  setSourceBadge(sourceEl, sourceLabel, sourceSignalTone(sourceLabel), item.source ? `分区: ${item.source}` : "");
  if (context.source && context.source === item.source) {
    sourceEl.hidden = true;
  }

  const primaryLabel = labelText(item);
  itemTagLabels(item)
    .filter((label) => label !== primaryLabel)
    .slice(0, 3)
    .forEach((label) => {
      metaRow.insertBefore(itemTagChip(label), sourceEl);
    });

  const timeEl = node.querySelector(".time");
  const timeline = timelineIso(item);
  const timelineDate = timelineItemDate(item);
  if (timelineDate) {
    timeEl.textContent = fmtTime(timeline);
    timeEl.setAttribute("datetime", timeline);
  } else {
    timeEl.textContent = "时间未知";
    timeEl.removeAttribute("datetime");
  }

  const titleEl = node.querySelector(".title");
  const zh = (item.title_zh || "").trim();
  const en = (item.title_en || "").trim();
  titleEl.textContent = "";
  if (zh && en && zh !== en) {
    const primary = document.createElement("span");
    primary.textContent = zh;
    const sub = document.createElement("span");
    sub.className = "title-sub";
    sub.textContent = en;
    titleEl.appendChild(primary);
    titleEl.appendChild(sub);
  } else {
    titleEl.textContent = item.title || zh || en;
  }
  titleEl.href = item.url;
  const summaryEl = node.querySelector(".news-summary");
  if (summaryEl) summaryEl.textContent = feedSummaryText(item);
  if (shouldRenderReadToggle(item, context)) {
    node.appendChild(buildReadToggleButton(item));
  }
  return node;
}
function shouldRenderReadToggle(item, context = {}) {
  return context.readToggleEligible === true || isSubscriptionItem(item);
}
function buildReadToggleButton(item) {
  const wrap = document.createElement("div");
  wrap.className = "item-actions";
  const btn = document.createElement("button");
  btn.type = "button";
  const read = isItemRead(item);
  btn.className = `read-toggle-btn${read ? " is-read" : ""}`;
  btn.textContent = read ? "恢复" : "已阅";
  btn.title = read ? "恢复到我的订阅" : "标记已阅，从看板中移出";
  btn.addEventListener("click", () => toggleItemRead(item));
  wrap.appendChild(btn);
  return wrap;
}
function buildSourceGroupNode(source, items, rawCount = items.length) {
  const section = document.createElement("section");
  section.className = "source-group";
  const header = document.createElement("header");
  header.className = "source-group-head";
  const title = document.createElement("h3");
  title.textContent = source;
  const count = document.createElement("span");
  count.className = "group-summary";
  count.textContent = subgroupSummary(items, rawCount);
  const listEl = document.createElement("div");
  listEl.className = "source-group-list";
  header.append(title, count);
  section.append(header, listEl);

  let expanded = false;
  if (items.length > SOURCE_ITEM_INITIAL_LIMIT) {
    const moreBtn = document.createElement("button");
    moreBtn.type = "button";
    moreBtn.className = "group-more-btn";
    const renderItems = () => {
      listEl.innerHTML = "";
      const visibleItems = expanded ? items : items.slice(0, SOURCE_ITEM_INITIAL_LIMIT);
      visibleItems.forEach((item) => listEl.appendChild(renderItemNode(item, { source })));
      moreBtn.textContent = expanded
        ? `收起，仅看前 ${SOURCE_ITEM_INITIAL_LIMIT} 条`
        : `展开剩余 ${fmtNumber(items.length - SOURCE_ITEM_INITIAL_LIMIT)} 条`;
    };
    moreBtn.addEventListener("click", () => {
      expanded = !expanded;
      renderItems();
    });
    renderItems();
    section.append(moreBtn);
  } else {
    items.forEach((item) => listEl.appendChild(renderItemNode(item, { source })));
  }
  return section;
}
function displayDedupeKey(item) {
  const title = normalizedEventText(itemTitleText(item));
  // Short social-post titles such as "AI小狗" still identify the same visible
  // post within one creator subgroup; URL query strings often only carry a
  // rotating access token and must not defeat that deduplication.
  if (title) return `title:${title}`;
  try {
    const url = new URL(item.url || "");
    return `url:${url.origin}${url.pathname}`;
  } catch {
    return `url:${item.url || item.id || "untitled"}`;
  }
}
function dedupeSubgroupItems(items) {
  const seen = new Set();
  return sortItemsForList(items).filter((item) => {
    const key = displayDedupeKey(item);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}
function subgroupSortValue(items) {
  if (!items.length) return 0;
  if (state.listSort === "time") return Math.max(...items.map(timelineMs));
  if (state.listSort === "ai") return Math.max(...items.map(scorePercent));
  if (state.listSort === "source") return items.length;
  const leading = [...items]
    .sort((a, b) => itemPriorityScore(b) - itemPriorityScore(a))
    .slice(0, 3);
  return Math.round(leading.reduce((sum, item) => sum + itemPriorityScore(item), 0) / leading.length);
}
function subgroupSummary(items, rawCount = items.length) {
  const count = `${fmtNumber(items.length)} 条`;
  const merged = rawCount - items.length;
  let ranking = "";
  if (state.listSort === "priority") ranking = `综合 ${subgroupSortValue(items)}`;
  if (state.listSort === "time") ranking = `时间 ${fmtTime(timelineIso(items[0]))}`;
  if (state.listSort === "ai") ranking = `最高 AI ${subgroupSortValue(items)}分`;
  const mergedLabel = merged > 0 ? `合并 ${fmtNumber(merged)} 条重复` : "";
  return [count, ranking, mergedLabel].filter(Boolean).join(" · ");
}
function sourceGroupEntries(items) {
  const groupMap = new Map();
  items.forEach((item) => {
    const key = item.source || "未分区";
    if (!groupMap.has(key)) {
      groupMap.set(key, []);
    }
    groupMap.get(key).push(item);
  });

  return Array.from(groupMap.entries())
    .map(([source, rawItems]) => ({
      source,
      rawCount: rawItems.length,
      items: dedupeSubgroupItems(rawItems),
    }))
    .filter((group) => group.items.length)
    .sort((a, b) => {
      const byScore = subgroupSortValue(b.items) - subgroupSortValue(a.items);
      if (byScore !== 0) return byScore;
      const byCount = b.items.length - a.items.length;
      if (byCount !== 0) return byCount;
      return a.source.localeCompare(b.source, "zh-CN");
    });
}
// Mobile-safe async rendering: avoid blocking the main thread on large lists.
// We chunk site-groups and yield between each chunk so the browser can paint
// and respond to touch events while the list is being built.
let _renderListToken = 0;

function buildSiteGroupNode(site) {
  const siteSection = document.createElement("section");
  siteSection.className = "site-group";
  const header = document.createElement("header");
  header.className = "site-group-head";
  const title = document.createElement("h3");
  title.textContent = site.siteName;
  const count = document.createElement("span");
  count.className = "group-summary";
  count.textContent = subgroupSummary(site.items, site.rawCount);
  const siteListEl = document.createElement("div");
  siteListEl.className = "site-group-list";
  header.append(title, count);
  siteSection.append(header, siteListEl);

  const sourceGroups = site.sourceGroups;
  let expanded = false;
  let moreBtn = null;
  const renderSourceGroups = () => {
    siteListEl.innerHTML = "";
    if (moreBtn) moreBtn.remove();
    const visibleGroups = expanded
      ? sourceGroups
      : sourceGroups.slice(0, SITE_SOURCE_GROUP_INITIAL_LIMIT);
    const frag = document.createDocumentFragment();
    visibleGroups.forEach((group) => {
      frag.appendChild(buildSourceGroupNode(group.source, group.items, group.rawCount));
    });
    siteListEl.appendChild(frag);
    if (sourceGroups.length > SITE_SOURCE_GROUP_INITIAL_LIMIT) {
      const hiddenCount = sourceGroups.length - SITE_SOURCE_GROUP_INITIAL_LIMIT;
      moreBtn = addLoadMoreButton(
        siteSection,
        expanded
          ? `收起，仅看前 ${SITE_SOURCE_GROUP_INITIAL_LIMIT} 个分区`
          : `展开其余 ${fmtNumber(hiddenCount)} 个分区`,
        () => {
          expanded = !expanded;
          renderSourceGroups();
        },
      );
    }
  };
  renderSourceGroups();
  return siteSection;
}
function renderLoadingNotice(label, count) {
  const loading = document.createElement("div");
  loading.className = "list-loading";
  loading.textContent = `正在整理 ${label} · ${fmtNumber(count)} 条`;
  newsListEl.appendChild(loading);
}
function currentFilterLabel(filtered) {
  if (state.authorFilter) return `${listTitleText()} · X 博主 ${state.authorFilter}`;
  if (state.siteFilter) {
    const item = filtered[0];
    const stat = currentSiteStats().find((s) => s.site_id === state.siteFilter);
    return `${listTitleText()} · ${sourceDisplayName(item || stat || state.siteFilter)}`;
  }
  return listTitleText();
}
function groupedSites(items) {
  const siteMap = new Map();
  items.forEach((item) => {
    if (!siteMap.has(item.site_id)) {
      siteMap.set(item.site_id, { siteName: sourceDisplayName(item), rawItems: [] });
    }
    siteMap.get(item.site_id).rawItems.push(item);
  });

  return Array.from(siteMap.entries())
    .map(([siteId, site]) => {
      const sourceGroups = sourceGroupEntries(site.rawItems);
      return [siteId, {
        siteName: site.siteName,
        rawCount: site.rawItems.length,
        sourceGroups,
        items: sourceGroups.flatMap((group) => group.items),
      }];
    })
    .filter(([, site]) => site.items.length)
    .sort((a, b) => {
      const byScore = subgroupSortValue(b[1].items) - subgroupSortValue(a[1].items);
      if (byScore !== 0) return byScore;
      const byCount = b[1].items.length - a[1].items.length;
      if (byCount !== 0) return byCount;
      return a[1].siteName.localeCompare(b[1].siteName, "zh-CN");
    });
}
function addLoadMoreButton(parent, label, onClick) {
  const moreBtn = document.createElement("button");
  moreBtn.type = "button";
  moreBtn.className = "list-more-btn";
  moreBtn.textContent = label;
  moreBtn.addEventListener("click", onClick);
  parent.appendChild(moreBtn);
  return moreBtn;
}
function buildTimelineRow(item) {
  const row = document.createElement("div");
  const platformKey = itemPlatformSection(item) || "rss";
  row.className = `timeline-row platform-${platformKey}`;

  const time = document.createElement("time");
  time.className = "timeline-time";
  const timeline = timelineIso(item);
  const date = timelineItemDate(item);
  if (date) {
    time.textContent = timelineClockText(date);
    time.setAttribute("datetime", timeline);
  } else {
    time.textContent = "--:--";
  }

  const rail = document.createElement("span");
  rail.className = "timeline-rail";
  rail.setAttribute("aria-hidden", "true");
  const dot = document.createElement("span");
  dot.className = "timeline-dot";
  rail.appendChild(dot);

  row.append(time, rail, renderItemNode(item, { readToggleEligible: true }));
  return row;
}
function buildTimelineDaySection(key, items) {
  const section = document.createElement("section");
  section.className = "timeline-day";
  const headingId = `timeline-day-${key}`;
  section.setAttribute("aria-labelledby", headingId);

  const header = document.createElement("header");
  header.className = "timeline-day-head";
  const title = document.createElement("h3");
  title.className = "timeline-date";
  title.id = headingId;
  const meta = document.createElement("span");
  meta.className = "timeline-day-meta";
  const date = key === "unknown" ? null : timelineItemDate(items[0]);
  if (date) {
    title.textContent = timelineDateText(date);
    meta.textContent = `${timelineWeekdayText(date)} · ${fmtNumber(items.length)} 条`;
  } else {
    title.textContent = "日期未知";
    meta.textContent = `时间字段无效 · ${fmtNumber(items.length)} 条`;
  }
  header.append(title, meta);

  const rows = document.createElement("div");
  rows.className = "timeline-day-items";
  items.forEach((item) => rows.appendChild(buildTimelineRow(item)));
  section.append(header, rows);
  return section;
}
function renderFlatTimeline(items) {
  const pageSize = 80;
  const shown = state.siteGroupsExpanded ? items.length : Math.min(pageSize, items.length);
  const visibleItems = items.slice(0, shown);
  const frag = document.createDocumentFragment();
  if (state.listSort === "time") {
    const groups = new Map();
    visibleItems.forEach((item) => {
      const key = timelineDayKey(item);
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(item);
    });
    groups.forEach((groupItems, key) => {
      frag.appendChild(buildTimelineDaySection(key, groupItems));
    });
  } else {
    visibleItems.forEach((item) => {
      frag.appendChild(renderItemNode(item, { readToggleEligible: true }));
    });
  }
  newsListEl.appendChild(frag);

  if (items.length > pageSize) {
    addLoadMoreButton(
      newsListEl,
      state.siteGroupsExpanded
        ? `收起，仅看前 ${fmtNumber(pageSize)} 条`
        : `继续看剩余 ${fmtNumber(items.length - pageSize)} 条`,
      () => {
        state.siteGroupsExpanded = !state.siteGroupsExpanded;
        renderList();
      },
    );
  }
  document.dispatchEvent(new CustomEvent("aiRadar:listRendered"));
}
function renderSiteGroups(items) {
  const groups = groupedSites(items);
  const visibleGroups = state.siteGroupsExpanded
    ? groups
    : groups.slice(0, SITE_GROUP_INITIAL_LIMIT);
  visibleGroups.forEach(([, site]) => {
    newsListEl.appendChild(buildSiteGroupNode(site));
  });

  if (groups.length > SITE_GROUP_INITIAL_LIMIT) {
    const hiddenCount = groups.length - SITE_GROUP_INITIAL_LIMIT;
    addLoadMoreButton(
      newsListEl,
      state.siteGroupsExpanded
        ? `收起，仅看前 ${SITE_GROUP_INITIAL_LIMIT} 个来源`
        : `展开其余 ${fmtNumber(hiddenCount)} 个来源`,
      () => {
        state.siteGroupsExpanded = !state.siteGroupsExpanded;
        renderList();
      },
    );
  }
  document.dispatchEvent(new CustomEvent("aiRadar:listRendered"));
}
function renderList() {
  const filtered = getFilteredItems();
  renderListSortTools();
  newsListEl.classList.remove("timeline-mode", "flat-mode", "group-mode");
  if (isSubscriptionSection(state.activeSection)) {
    newsListEl.classList.add(state.listSort === "time" ? "timeline-mode" : "flat-mode");
  } else {
    newsListEl.classList.add("group-mode");
  }
  resultCountEl.textContent = `${fmtNumber(filtered.length)} 条`;
  renderSectionSummary(filtered);

  newsListEl.innerHTML = "";
  _renderListToken += 1;           // invalidate any in-flight render
  const token = _renderListToken;

  if (!filtered.length) {
    const empty = document.createElement("div");
    empty.className = "empty";
    empty.textContent = "当前筛选条件下没有结果。";
    newsListEl.appendChild(empty);
    return;
  }

  renderLoadingNotice(currentFilterLabel(filtered), filtered.length);
  requestAnimationFrame(() => {
    if (token !== _renderListToken) return;   // stale render, abort
    const sorted = sortItemsForList(filtered);
    newsListEl.innerHTML = "";
    if (isSubscriptionSection(state.activeSection)) {
      renderFlatTimeline(sorted);
    } else {
      renderSiteGroups(sorted);
    }
  });
}
function rerenderCurrentView() {
  state.boleExpanded = false;
  state.siteGroupsExpanded = false;
  renderSectionTabs();
  renderTimeRangeControl();
  renderModeSwitch();
  renderSiteFilters();
  renderBolePicks();
  if (state.waytoagiData) renderWaytoagi(state.waytoagiData);
  renderList();
}

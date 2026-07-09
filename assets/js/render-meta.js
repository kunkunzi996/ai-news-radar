function setStats() {
  statsEl.innerHTML = "";
  const items = visibleItemList(state.itemsAi || []);
  const highCount = items.filter((item) => isHighPriorityItem(item)).length;
  const curatedCount = briefStories().length || Math.min(20, mergedStories().filter((story) => storyScore(story) >= 75).length);
  const status = state.sourceStatus;
  const visibleSites = visibleSourceStatusSites(status);
  const totalSites = visibleSites.length;
  const okSites = visibleSites.filter((site) => site.ok).length;
  const health = totalSites ? `${fmtNumber(okSites)}/${fmtNumber(totalSites)}正常` : "加载中";
  const cards = [
    ["AI", `${fmtNumber(items.length)}条`],
    ["高优", `${fmtNumber(highCount)}条`],
    ["精选", `${fmtNumber(curatedCount)}条`],
    ["源", health],
  ];
  statsEl.setAttribute(
    "aria-label",
    `${windowLabel()}：AI 信号 ${fmtNumber(items.length)} 条，高优先级 ${fmtNumber(highCount)} 条，精选 ${fmtNumber(curatedCount)} 条，源状态 ${totalSites ? `${fmtNumber(okSites)}/${fmtNumber(totalSites)} 源正常` : "加载中"}`,
  );

  const prefix = document.createElement("div");
  prefix.className = "stat-prefix";
  prefix.textContent = `${windowLabel()}：`;
  statsEl.appendChild(prefix);

  cards.forEach(([k, v]) => {
    const node = document.createElement("div");
    node.className = "stat";
    node.innerHTML = `<div class="k">${k}</div><div class="v">${v}</div>`;
    statsEl.appendChild(node);
  });
  renderStickySummary();
  renderSourceStatusPill();
}
function failedSourceCount(status = state.sourceStatus) {
  const failedSites = visibleFailedSites(status).length;
  const rss = status?.rss_opml || {};
  const failedFeeds = visibleFeedList(rss.failed_feeds).length;
  return failedSites + failedFeeds;
}
function renderSourceStatusPill(errorMessage = "") {
  if (!sourceStatusPillEl) return;
  const status = state.sourceStatus;
  sourceStatusPillEl.className = "source-status-pill";
  if (!status) {
    sourceStatusPillEl.textContent = errorMessage || "源状态加载中";
    if (errorMessage) sourceStatusPillEl.classList.add("bad");
    return;
  }
  const visibleSites = visibleSourceStatusSites(status);
  const totalSites = visibleSites.length;
  const okSites = visibleSites.filter((site) => site.ok).length;
  const failed = failedSourceCount(status);
  sourceStatusPillEl.textContent = failed
    ? `${fmtNumber(okSites)}/${fmtNumber(totalSites)} 源正常 · 失败 ${fmtNumber(failed)}`
    : `${fmtNumber(okSites)}/${fmtNumber(totalSites)} 源正常`;
  if (failed) sourceStatusPillEl.classList.add("warn");
}
function renderDataSourcePill() {
  if (!dataSourcePillEl) return;
  dataSourcePillEl.className = "data-source-pill";
  if (state.dataSourceMode === "remote") {
    dataSourcePillEl.classList.add("remote");
    dataSourcePillEl.textContent = state.dataSourceFallback ? "远程失败 · 本地回退" : "远程数据";
    dataSourcePillEl.title = state.dataSourceFallback
      ? `${state.dataSourceError || "远程数据读取失败"}；远程地址：${state.dataBaseUrl}`
      : `当前读取远程数据：${state.dataBaseUrl}`;
    if (state.dataSourceFallback) dataSourcePillEl.classList.add("warn");
    return;
  }
  const staticPage = !canUseLocalBackend();
  dataSourcePillEl.textContent = state.dataSourceError ? "本地数据 · 地址无效" : (staticPage ? "静态数据" : "本地数据");
  dataSourcePillEl.title = state.dataSourceError || (staticPage ? "当前读取同源 data/*.json" : "当前读取本机 data/*.json");
  if (state.dataSourceError) dataSourcePillEl.classList.add("warn");
}
function renderStickySummary() {
  if (!stickySummaryTextEl) return;
  const filteredCount = getFilteredItems().length;
  const section = SECTION_BY_ID[state.activeSection] || SECTION_BY_ID.creator;
  const query = state.query.trim();
  const site = state.siteFilter
    ? (currentSiteStats().find((row) => row.site_id === state.siteFilter)?.site_name || state.siteFilter)
    : "";
  const sourceType = sourceTypeSelectEl?.selectedOptions?.[0]?.textContent || "";
  const signalLevel = signalLevelSelectEl?.selectedOptions?.[0]?.textContent || "";
  const filters = [
    section.label,
    site,
    state.sourceTypeFilter ? sourceType : "",
    state.signalLevelFilter ? signalLevel : "",
    query ? `搜索“${query}”` : "",
  ].filter(Boolean);
  const mode = state.mode === "all" ? "全量" : "AI强相关";
  stickySummaryTextEl.textContent = `${fmtNumber(filteredCount)} 条 · ${mode}${filters.length ? ` · ${filters.join(" · ")}` : ""}`;
}
function sourceKind(siteId) {
  return SOURCE_KINDS[siteId] || { label: "来源", tone: "default" };
}
function sourceDisplayName(source) {
  const sourceObj = typeof source === "object" && source ? source : {};
  const siteId = String(sourceObj.site_id || sourceObj.siteId || "").toLowerCase();
  const rawName = String(
    sourceObj.site_name ||
    sourceObj.siteName ||
    sourceObj.name ||
    (typeof source === "string" ? source : "") ||
    siteId ||
    "",
  ).trim();
  const hay = `${siteId} ${rawName} ${sourceObj.source || ""} ${sourceObj.url || ""}`.toLowerCase();
  if (siteId === "wewe_rss" || siteId === "maobidao_wudaolu_backup" || hay.includes("wewe") || hay.includes("mp.weixin") || hay.includes("公众号")) return "微信公众号";
  if (siteId === "opmlrss" || hay.includes("opmlrss") || hay.includes("youtube") || hay.includes("youtu.be")) return "YouTube";
  if (siteId === "github_foundation_sunshine_releases" || hay.includes("github_foundation") || hay.includes("github foundation sunshine")) return "GitHub";
  if (siteId === "mediacrawler_xhs" || siteId === "tikhub_xiaohongshu" || hay.includes("xiaohongshu") || hay.includes("小红书")) return "小红书";
  if (siteId === "mediacrawler_douyin" || siteId === "tikhub_douyin" || hay.includes("douyin") || hay.includes("抖音")) return "抖音";
  if (siteId === "bilibili_dynamic" || hay.includes("bilibili") || hay.includes("b站")) return "B站";
  return rawName || siteId || "来源";
}
function sourceSignalTone(signal) {
  const text = String(signal || "").toLowerCase();
  if (text.includes("官方") || text.includes("official")) return "official";
  if (text.includes("ai hot") || text.includes("精选")) return "hot";
  if (text.includes("我的订阅") || text.includes("订阅") || text.includes("自媒体") || text.includes("tikhub") || text.includes("douyin") || text.includes("xiaohongshu") || text.includes("bilibili") || text.includes("youtube") || text.includes("youtu.be") || text.includes("抖音") || text.includes("小红书") || text.includes("b站") || text.includes("油管")) return "creator";
  if (text.includes("builders") || text.includes("github") || text.includes("x")) return "builders";
  if (text.includes("aihub") || text.includes("aibase") || text.includes("媒体")) return "aihub";
  if (text.includes("hn") || text.includes("hacker") || text.includes("聚合")) return "aggregate";
  if (text.includes("opml") || text.includes("日报")) return "newsletter";
  return "default";
}
function sourceChip(label, tone = "default", className = "source-chip") {
  const chip = document.createElement("span");
  chip.className = `${className} kind-${tone}`.trim();
  const dot = document.createElement("span");
  dot.className = "source-dot";
  dot.setAttribute("aria-hidden", "true");
  const text = document.createElement("span");
  text.className = "source-chip-label";
  text.textContent = label || "来源";
  chip.append(dot, text);
  return chip;
}
function appendSourceChip(parent, label, tone = "default", className = "source-chip") {
  parent.appendChild(sourceChip(label, tone, className));
}
function siteRows() {
  return visibleSourceStatusSites(state.sourceStatus);
}
function siteRow(siteId) {
  return siteRows().find((site) => site.site_id === siteId) || null;
}
function aiSiteStat(siteId) {
  const stats = Array.isArray(state.statsAi) && state.statsAi.length
    ? state.statsAi
    : computeSiteStats(state.itemsAi || []);
  return stats.find((site) => site.site_id === siteId) || null;
}
function siteAiPoolCount(siteId) {
  return Number(aiSiteStat(siteId)?.count || 0);
}
function siteRawPoolCount(siteId) {
  const stat = aiSiteStat(siteId);
  return Number(stat?.raw_count ?? stat?.count ?? 0);
}
function sourcePoolMeta(aiCount, rawCount, fallback) {
  if (rawCount && rawCount !== aiCount) return `AI强相关 · 原始 ${fmtNumber(rawCount)} 条`;
  return fallback;
}
function paidSourceLabel(status, poolCount, activeLabel, idleLabel) {
  const connected = Boolean(status?.enabled);
  const liveCount = Number(status?.item_count || 0);
  const displayCount = liveCount || Number(poolCount || 0);
  if (connected) {
    if (displayCount) return `${activeLabel} ${fmtNumber(displayCount)}条`;
    return `${activeLabel} ${status?.skipped ? "待窗口" : "已连接暂无匹配"}`;
  }
  if (displayCount) return `${activeLabel} ${fmtNumber(displayCount)}条`;
  return idleLabel;
}
function renderCoverageCard(label, value, meta, tone = "") {
  const node = document.createElement("div");
  node.className = `coverage-card ${tone}`.trim();
  const labelEl = document.createElement("span");
  labelEl.className = "coverage-label";
  labelEl.textContent = label;
  const valueEl = document.createElement("strong");
  valueEl.textContent = value;
  const metaEl = document.createElement("span");
  metaEl.className = "coverage-meta";
  metaEl.textContent = meta;
  node.append(labelEl, valueEl, metaEl);
  return node;
}
function renderCoverageStrip(errorMessage = "") {
  if (!coverageStripEl) return;
  coverageStripEl.innerHTML = "";

  const rows = siteRows();
  const failedSites = visibleFailedSites(state.sourceStatus);
  const rss = state.sourceStatus?.rss_opml || {};
  const agentmail = state.sourceStatus?.agentmail || {};
  const xApi = state.sourceStatus?.x_api || {};
  const socialdata = state.sourceStatus?.socialdata || {};
  const allCount = Number(state.sourceStatus?.items_before_topic_filter || state.totalAllMode || state.itemsAll.length || 0);
  const coverageCount = Number(state.sourceStatus?.fetched_raw_items || state.totalRaw || allCount || 0);
  const officialCount = Number(siteRow("official_ai")?.item_count || 0);
  const newsletterCount = Number(siteRow("aibreakfast")?.item_count || 0);
  const curatedMediaCount = Number(siteRow("curated_media")?.item_count || 0);
  const buildersCount = Number(siteRow("followbuilders")?.item_count || 0);
  const creatorCount = visibleItemList(state.creatorItemsAi).length || (siteAiPoolCount("tikhub_douyin") + siteAiPoolCount("tikhub_xiaohongshu") + siteAiPoolCount("mediacrawler_douyin") + siteAiPoolCount("mediacrawler_xhs") + siteAiPoolCount("github_foundation_sunshine_releases"));
  const creatorRawCount = visibleItemList(state.creatorItemsAll).length || (siteRawPoolCount("tikhub_douyin") + siteRawPoolCount("tikhub_xiaohongshu") + siteRawPoolCount("mediacrawler_douyin") + siteRawPoolCount("mediacrawler_xhs") + siteRawPoolCount("github_foundation_sunshine_releases"));
  const socialdataPoolCount = siteAiPoolCount("socialdata_x");
  const xApiPoolCount = siteAiPoolCount("xapi");
  const xPoolCount = socialdataPoolCount + xApiPoolCount;
  const mailCount = Number(agentmail.item_count || 0);
  const totalSites = rows.length;
  const okSites = rows.filter((site) => site.ok).length;
  const opmlValue = rss.enabled ? `${fmtNumber(rss.ok_feeds || 0)}/${fmtNumber(rss.effective_feed_total || 0)}` : "OPML";
  const opmlMeta = rss.enabled ? "RSS示例/自定义订阅已接入" : "可用OPML批量接入RSS";
  const socialdataLabel = paidSourceLabel(socialdata, socialdataPoolCount, "SocialData", "");
  const xApiLabel = paidSourceLabel(xApi, xApiPoolCount, "X API", "");
  const xSourceLabel = socialdataLabel || xApiLabel || "X待配置";
  const mailLabel = agentmail.enabled ? `Mail ${fmtNumber(mailCount)}` : "Mail待配置";
  const advancedValue = xPoolCount || mailCount
    ? `${xPoolCount ? `X ${fmtNumber(xPoolCount)}` : "X"} / ${mailCount ? `Mail ${fmtNumber(mailCount)}` : "Mail"}`
    : "X / Mail";
  const advancedMeta = socialdata.enabled || xApi.enabled || agentmail.enabled || xPoolCount
    ? `额度保护 · ${xSourceLabel} / ${mailLabel}`
    : "X API 与 AgentMail 默认关闭";

  const creatorOnly = state.sourceScope === "tested_creator_sources" || state.sourceScope === "bilibili_only";
  const coverageMeta = creatorOnly
    ? `B站 / 抖音 / 小红书原始信号 · ${fmtNumber(allCount)} 条入池`
    : (allCount ? `全网抓取原始信号 · ${fmtNumber(allCount)} 条入池` : "全网抓取原始信号");
  const creatorMeta = creatorOnly
    ? sourcePoolMeta(creatorCount, creatorRawCount, "B站 / YouTube / 抖音 / 小红书 / GitHub")
    : sourcePoolMeta(creatorCount, creatorRawCount, "TikHub / MediaCrawler / YouTube / B站 / GitHub");

  const cards = [
    ["源健康", totalSites ? `${fmtNumber(okSites)}/${fmtNumber(totalSites)}` : "加载中", failedSites.length ? `${fmtNumber(failedSites.length)} 个失败源` : (errorMessage || "内置源正常"), failedSites.length ? "warn" : "ok"],
    ["今日覆盖池", `${fmtNumber(coverageCount)} 条`, coverageMeta, "signal"],
    ["AI强相关", `${fmtNumber(visibleItemList(state.itemsAi).length)} 条`, "24小时强相关信号", "signal"],
    ["官方/日报源池", `${fmtNumber(officialCount + newsletterCount)} 条`, "官方节点 + AI Breakfast", "official"],
    ["精选媒体源池", `${fmtNumber(curatedMediaCount)} 条`, "The Decoder / TC / Verge / MTP 等", "signal"],
    ["Builders/X源池", `${fmtNumber(buildersCount)} 条`, "Follow Builders公开feed", "builders"],
    ["我的订阅", `${fmtNumber(creatorCount)} 条`, creatorMeta, "creator"],
    ["RSS/OPML扩展", opmlValue, opmlMeta, "private"],
    ["高级源", advancedValue, advancedMeta, "private"],
  ];

  cards.forEach(([label, value, meta, tone]) => {
    coverageStripEl.appendChild(renderCoverageCard(label, value, meta, tone));
  });
}
function renderAdvancedSummary() {
  if (!advancedSummaryEl) return;
  const status = state.sourceStatus;
  const filteredCount = getFilteredItems().length;
  if (!status) {
    advancedSummaryEl.textContent = `${fmtNumber(filteredCount)} 条结果`;
    return;
  }
  const sites = visibleSourceStatusSites(status);
  const totalSites = sites.length;
  const okSites = sites.filter((site) => site.ok).length;
  const failed = failedSourceCount(status);
  advancedSummaryEl.textContent = `${fmtNumber(filteredCount)} 条结果 · ${fmtNumber(okSites)}/${fmtNumber(totalSites)} 源正常${failed ? ` · 失败 ${fmtNumber(failed)}` : ""}`;
}
function computeSiteStats(items) {
  const m = new Map();
  visibleItemList(items).forEach((item) => {
    if (!m.has(item.site_id)) {
      m.set(item.site_id, { site_id: item.site_id, site_name: sourceDisplayName(item), count: 0, raw_count: 0 });
    }
    const row = m.get(item.site_id);
    row.count += 1;
    row.raw_count += 1;
  });
  return Array.from(m.values()).sort((a, b) => b.count - a.count || a.site_name.localeCompare(b.site_name, "zh-CN"));
}
function currentSiteStats() {
  if (isSubscriptionSection(state.activeSection)) {
    return computeSiteStats(sectionItems(modeItems(), state.activeSection));
  }
  if (state.mode === "ai") return visibleSiteStats(state.statsAi || []);
  return computeSiteStats(state.allDedup ? (state.itemsAll || []) : (state.itemsAllRaw || []));
}
function creatorHotScore(item) {
  return normalizedPercent(item?.creator_hot_score);
}
function highPriorityScore(item) {
  if (itemSections(item).has("creator") && creatorHotScore(item)) return creatorHotScore(item);
  return scorePercent(item);
}
function isHighPriorityItem(item) {
  return highPriorityScore(item) >= 75 || itemPriorityScore(item) >= 82 || item.site_id === "official_ai" || item.site_id === "aihot";
}
function isCuratedItem(item) {
  return item.site_id === "official_ai" || item.site_id === "aihot" || item.source_tier === "official" || item.source_tier === "curated";
}
function itemSourceType(item) {
  const siteId = item.site_id || "";
  const tier = item.source_tier || "";
  if (siteId === "official_ai" || tier === "official") return "official";
  if (siteId === "curated_media" || siteId === "aibreakfast" || siteId === "aihot") return "media";
  if (isSubscriptionItem(item)) return "creator";
  if (siteId === "opmlrss" || tier === "user_opml") return "rss";
  if (siteId === "waytoagi" || siteId === "followbuilders" || siteId === "hackernews" || siteId === "zeli" || siteId === "aibase") return "community";
  if (siteId === "socialdata_x" || siteId === "xapi" || siteId === "agentmail") return "advanced";
  return "aggregate";
}
function sectionStats(sectionId) {
  const items = sectionItems(modeItems(), sectionId);
  const highCount = items.filter((item) => isHighPriorityItem(item)).length;
  const sourceSet = new Set(items.map((item) => item.source || item.site_name || item.site_id).filter(Boolean));
  return { items, count: items.length, highCount, sourceCount: sourceSet.size };
}
function setActiveSection(sectionId) {
  state.activeSection = SECTION_BY_ID[sectionId] ? sectionId : "creator";
  state.boleExpanded = false;
}
function renderSectionTabs() {
  if (!sectionTabsEl) return;
  sectionTabsEl.innerHTML = "";
  visibleSections().forEach((section) => {
    const stats = sectionStats(section.id);
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = `section-tab ${state.activeSection === section.id ? "active" : ""}`;
    btn.setAttribute("role", "tab");
    btn.setAttribute("aria-selected", state.activeSection === section.id ? "true" : "false");
    btn.dataset.section = section.id;
    btn.innerHTML = `<span>${section.label}</span><strong>${fmtNumber(stats.count)}</strong>`;
    btn.addEventListener("click", () => {
      setActiveSection(section.id);
      renderSectionTabs();
      renderModeSwitch();
      renderSiteFilters();
      renderBolePicks();
      if (state.waytoagiData) renderWaytoagi(state.waytoagiData);
      renderList();
    });
    sectionTabsEl.appendChild(btn);
  });
  renderSectionFilterSelect();
}
function renderSectionFilterSelect() {
  if (!sectionSelectEl) return;
  if (!sectionSelectEl.options.length) {
    visibleSections().forEach((section) => {
      const option = document.createElement("option");
      option.value = section.id;
      option.textContent = section.label;
      sectionSelectEl.appendChild(option);
    });
  }
  sectionSelectEl.value = state.activeSection;
}
function renderSectionSummary(filteredItems = null) {
  if (!sectionSummaryEl) return;
  const section = SECTION_BY_ID[state.activeSection] || SECTION_BY_ID.creator;
  const items = filteredItems || getFilteredItems();
  const highCount = items.filter((item) => isHighPriorityItem(item)).length;
  const sources = new Set(items.map((item) => item.source || item.site_name || item.site_id).filter(Boolean));
  const modeText = state.mode === "all" ? (state.allDedup ? "全量去重" : "全量原始") : "AI强相关";
  const sortText = {
    time: "时间优先",
    priority: "综合优先",
    ai: "高分优先",
    source: "来源优先",
  }[state.listSort] || "时间优先";
  const windowText = isSubscriptionSection(state.activeSection) ? `${creatorWindowLabel()} · ${sortText}` : windowLabel();
  sectionSummaryEl.textContent = `${windowText} · ${fmtNumber(items.length)} 条 ${section.label} 信号 · ${fmtNumber(highCount)} 条高优先级 · ${fmtNumber(sources.size)} 个来源 · ${modeText}`;
  renderStickySummary();
}
function siteRatioText(siteStats) {
  const count = Number(siteStats.count || 0);
  const raw = Number(siteStats.raw_count ?? siteStats.count ?? 0);
  if (!raw) {
    const scanned = Number(siteRow(siteStats.site_id)?.item_count || 0);
    if (!count && scanned) return `24h 0 · 已扫 ${fmtNumber(scanned)}`;
    if (!count) return "已扫 0";
    return `${fmtNumber(count)} 条`;
  }
  if (raw === count) return `${fmtNumber(count)} 条`;
  return `${fmtNumber(count)}/${fmtNumber(raw)} · ${Math.round((count / raw) * 100)}%AI`;
}
function renderSiteFilters() {
  const stats = currentSiteStats();

  siteSelectEl.innerHTML = '<option value="">全部站点</option>';
  stats.forEach((s) => {
    const opt = document.createElement("option");
    opt.value = s.site_id;
    opt.textContent = `${s.site_name} (${siteRatioText(s)})`;
    siteSelectEl.appendChild(opt);
  });
  siteSelectEl.value = state.siteFilter;

  sitePillsEl.innerHTML = "";
  const allPill = document.createElement("button");
  allPill.className = `pill ${state.siteFilter === "" ? "active" : ""}`;
  allPill.textContent = "全部";
  allPill.onclick = () => {
    state.siteFilter = "";
    renderSiteFilters();
    renderBolePicks();
    renderList();
  };
  sitePillsEl.appendChild(allPill);

  if (state.authorFilter) {
    const authorPill = document.createElement("button");
    authorPill.type = "button";
    authorPill.className = "pill active author-filter-pill";
    authorPill.textContent = `X 博主 ${state.authorFilter} ×`;
    authorPill.title = "清除博主筛选";
    authorPill.onclick = () => {
      state.authorFilter = "";
      state.siteFilter = "";
      state.siteGroupsExpanded = false;
      renderSiteFilters();
      renderBolePicks();
      renderList();
    };
    sitePillsEl.appendChild(authorPill);
  }

  stats.forEach((s) => {
    const btn = document.createElement("button");
    btn.className = `pill ${state.siteFilter === s.site_id ? "active" : ""}`;
    btn.textContent = `${s.site_name} ${siteRatioText(s)}`;
    btn.onclick = () => {
      state.siteFilter = s.site_id;
      if (s.site_id !== "socialdata_x") state.authorFilter = "";
      renderSiteFilters();
      renderBolePicks();
      renderList();
    };
    sitePillsEl.appendChild(btn);
  });
}
function renderModeSwitch() {
  modeAiBtnEl.classList.toggle("active", state.mode === "ai");
  modeAllBtnEl.classList.toggle("active", state.mode === "all");
  if (allDedupeWrapEl) allDedupeWrapEl.classList.toggle("show", state.mode === "all");
  if (allDedupeToggleEl) allDedupeToggleEl.checked = state.allDedup;
  if (allDedupeLabelEl) allDedupeLabelEl.textContent = state.allDedup ? "去重开" : "去重关";
  if (state.mode === "ai") {
    modeHintEl.textContent = `AI强相关 · ${fmtNumber(state.totalAi)} 条`;
  } else {
    const allCount = state.allDedup
      ? (state.totalAllMode || state.itemsAll.length)
      : (state.totalRaw || state.itemsAllRaw.length);
    modeHintEl.textContent = `全量 · ${state.allDedup ? "去重开" : "去重关"} · ${fmtNumber(allCount)} 条`;
  }
  if (listTitleEl) {
    listTitleEl.textContent = listTitleText();
  }
  renderAdvancedSummary();
  renderSectionSummary();
}
function renderTimeRangeControl() {
  if (!timeRangeSelectEl) return;
  timeRangeSelectEl.value = state.timeRangeFilter;
}
function listTitleText() {
  const section = SECTION_BY_ID[state.activeSection] || SECTION_BY_ID.creator;
  const pool = state.mode === "all"
    ? (state.allDedup ? "情报流 · 全量去重" : "情报流 · 全量原始")
    : "情报流";
  return `${section.label} · ${pool}`;
}
function renderListSortTools() {
  if (!listSortToolsEl) return;
  const validSort = LIST_SORT_DEFS.some((item) => item.id === state.listSort);
  if (!validSort) state.listSort = "priority";
  listSortToolsEl.querySelectorAll("[data-sort]").forEach((button) => {
    const active = button.dataset.sort === state.listSort;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", active ? "true" : "false");
  });
}
function itemSourceSortKey(item) {
  return [
    sourceSignal(item),
    item.site_name || item.site_id || "",
    item.source || "",
  ].join(" ").trim() || "来源";
}
function sortItemsForList(items) {
  const sorted = [...items];
  if (state.listSort === "time") {
    return sorted.sort((a, b) => timelineMs(b) - timelineMs(a) || itemPriorityScore(b) - itemPriorityScore(a));
  }
  if (state.listSort === "ai") {
    return sorted.sort((a, b) => scorePercent(b) - scorePercent(a) || itemPriorityScore(b) - itemPriorityScore(a) || timelineMs(b) - timelineMs(a));
  }
  if (state.listSort === "source") {
    const counts = new Map();
    sorted.forEach((item) => {
      const key = itemSourceSortKey(item);
      counts.set(key, (counts.get(key) || 0) + 1);
    });
    return sorted.sort((a, b) => {
      const aKey = itemSourceSortKey(a);
      const bKey = itemSourceSortKey(b);
      const byCount = (counts.get(bKey) || 0) - (counts.get(aKey) || 0);
      if (byCount !== 0) return byCount;
      const bySource = aKey.localeCompare(bKey, "zh-CN");
      if (bySource !== 0) return bySource;
      return itemPriorityScore(b) - itemPriorityScore(a) || timelineMs(b) - timelineMs(a);
    });
  }
  return sorted.sort((a, b) => itemPriorityScore(b) - itemPriorityScore(a) || timelineMs(b) - timelineMs(a));
}
function effectiveAllItems() {
  return state.allDedup ? state.itemsAll : state.itemsAllRaw;
}
function modeItems() {
  return state.mode === "all" ? effectiveAllItems() : state.itemsAi;
}
function getFilteredItems() {
  const q = state.query.trim().toLowerCase();
  const preliminary = sectionItems().filter((item) => {
    if (state.siteFilter && item.site_id !== state.siteFilter) return false;
    if (state.authorFilter && (item.site_id !== "socialdata_x" || item.source !== state.authorFilter)) return false;
    if (state.sourceTypeFilter && itemSourceType(item) !== state.sourceTypeFilter) return false;
    if (!q) return true;
    const hay = `${item.title || ""} ${item.title_zh || ""} ${item.title_en || ""} ${item.site_name || ""} ${item.source || ""}`.toLowerCase();
    return hay.includes(q);
  });
  const multiKeys = multiSourceEventKeys(preliminary);
  return preliminary.filter((item) => itemMatchesSignalLevel(item, multiKeys));
}
function itemTitleText(item) {
  return (item.title_zh || item.title || item.title_en || "未命名更新").trim();
}
function scorePercent(item) {
  const score = Number(item.ai_score ?? item.score ?? 0);
  if (!Number.isFinite(score) || score <= 0) return 0;
  return Math.round(score <= 1 ? score * 100 : score);
}
function normalizedPercent(value) {
  const score = Number(value);
  if (!Number.isFinite(score) || score <= 0) return 0;
  return Math.max(0, Math.min(100, Math.round(score <= 1 ? score * 100 : score)));
}
function scoreTone(score) {
  if (score >= 90) return "hot";
  if (score >= 75) return "strong";
  return "watch";
}
function itemLabelTone(item) {
  const label = item.ai_label || "";
  if (item.site_id === "official_ai") return "official";
  if (item.site_id === "aihot" || label === "curated_hotlist") return "hot";
  if (itemSections(item).has("creator")) return "creator";
  if (label === "model_release") return "models";
  if (label === "developer_tool" || label === "developer_tooling" || label === "infrastructure" || label === "infra_compute") return "devtools";
  if (label === "research_paper") return "research";
  if (label === "industry_business") return "industry";
  if (label === "ai_product_update" || label === "agent_workflow" || label === "robotics") return "products";
  if (itemSections(item).has("community")) return "community";
  return "default";
}
function itemTagTone(label) {
  const text = String(label || "");
  if (text.includes("多源")) return "strong";
  if (text.includes("官方")) return "official";
  if (text.includes("精选") || text.includes("热点")) return "hot";
  if (text.includes("HN")) return "aggregate";
  if (text.includes("模型")) return "models";
  if (text.includes("开发")) return "devtools";
  if (text.includes("研究")) return "research";
  if (text.includes("订阅") || text.includes("自媒体")) return "creator";
  if (text.includes("社区")) return "community";
  if (text.includes("产品")) return "products";
  if (text.includes("行业")) return "industry";
  return "default";
}
function itemTagChip(label) {
  const tag = document.createElement("span");
  tag.className = `signal-tag tone-${itemTagTone(label)}`;
  tag.textContent = label;
  return tag;
}
function setSourceBadge(el, label, tone = "default", title = "") {
  el.className = `source source-chip kind-${tone}`;
  el.innerHTML = "";
  if (title) el.title = title;
  const dot = document.createElement("span");
  dot.className = "source-dot";
  dot.setAttribute("aria-hidden", "true");
  const text = document.createElement("span");
  text.className = "source-chip-label";
  text.textContent = label || "来源";
  el.append(dot, text);
}
function sourceTierPercent(item) {
  if (item.site_id === "official_ai") return 100;
  if (item.site_id === "aihot") return 90;
  const rank = Number(item.source_tier_rank);
  if (!Number.isFinite(rank)) return 38;
  return Math.max(28, Math.min(86, 86 - rank * 9));
}
function editorialPercent(item) {
  const aihotScore = normalizedPercent(item.aihot_score);
  if (aihotScore) return aihotScore;
  if (item.site_id === "official_ai") return 90;
  if (item.site_id === "aihot") return 78;
  const internal = scorePercent(item);
  return internal ? Math.max(45, Math.round(internal * 0.72)) : 36;
}
function freshnessPercent(item, halfLifeHours = 48) {
  const ageMs = Date.now() - timelineMs(item);
  if (!Number.isFinite(ageMs) || ageMs < 0) return 100;
  const ageHours = ageMs / 3600000;
  return Math.max(0, Math.min(100, Math.round(100 * Math.pow(0.5, ageHours / halfLifeHours))));
}
function itemPriorityScore(item) {
  const creatorScore = creatorHotScore(item);
  if (creatorScore && itemSections(item).has("creator")) return creatorScore;
  const internal = scorePercent(item);
  const editorial = editorialPercent(item);
  const source = sourceTierPercent(item);
  const freshness = freshnessPercent(item);
  const signal = Array.isArray(item.ai_signals) ? Math.min(100, item.ai_signals.length * 18) : 0;
  return Math.round((editorial * 0.3) + (source * 0.22) + (internal * 0.2) + (freshness * 0.18) + (signal * 0.1));
}
function labelText(item) {
  const labels = {
    ai_general: "AI信号",
    model_release: "模型发布",
    agent_workflow: "Agent工作流",
    ai_product_update: "产品更新",
    developer_tooling: "开发工具",
    developer_tool: "开发工具",
    infrastructure: "基础设施",
    infra_compute: "基础设施",
    industry_business: "行业动态",
    research_paper: "研究论文",
    robotics: "机器人",
    curated_hotlist: "热点",
    ai_tech: "技术趋势",
  };
  return labels[item.ai_label] || item.ai_label || "精选信号";
}
function itemHaystack(item) {
  return [
    item.title,
    item.title_zh,
    item.title_en,
    item.title_original,
    item.source,
    item.site_name,
    item.site_id,
    item.ai_label,
    ...(Array.isArray(item.ai_signals) ? item.ai_signals : []),
  ].filter(Boolean).join(" ").toLowerCase();
}
function matchesAny(text, patterns) {
  return patterns.some((pattern) => pattern.test(text));
}
function reasonText(item) {
  const creatorScore = creatorHotScore(item);
  if (creatorScore && itemSections(item).has("creator")) {
    const metrics = item.creator_metrics || {};
    const parts = [
      `赞 ${fmtNumber(metrics.likes)}`,
      `藏 ${fmtNumber(metrics.collects)}`,
      `评 ${fmtNumber(metrics.comments)}`,
      `转 ${fmtNumber(metrics.shares)}`,
    ];
    if (Number(item.creator_freshness_bonus || 0) > 0) parts.push("24h 加分");
    return `订阅互动：${parts.join(" · ")}`;
  }
  const signals = Array.isArray(item.ai_signals) ? item.ai_signals.filter(Boolean).slice(0, 3) : [];
  if (signals.length) return `命中方向：${signals.join(" / ")}`;
  if (item.ai_relevance_reason) return String(item.ai_relevance_reason).replaceAll("_", " ");
  return "来源与标题信号通过筛选";
}
function timelineIso(item) {
  const published = item.published_at || "";
  const seen = item.first_seen_at || "";
  const generated = state.generatedAt || "";
  if (published && generated) {
    const publishedMs = new Date(published).getTime();
    const generatedMs = new Date(generated).getTime();
    if (Number.isFinite(publishedMs) && Number.isFinite(generatedMs) && publishedMs > generatedMs + 10 * 60 * 1000) {
      return seen || published;
    }
  }
  return published || seen;
}
function timelineMs(item) {
  const d = new Date(timelineIso(item));
  return Number.isNaN(d.getTime()) ? 0 : d.getTime();
}
function normalizedEventText(text) {
  return String(text || "")
    .toLowerCase()
    .replace(/https?:\/\/\S+/g, "")
    .replace(/[\s\u3000]+/g, "")
    .replace(/[，。、“”‘’：:；;！!？?（）()\[\]【】《》<>·.,/\\|_-]/g, "");
}
function eventKey(item) {
  const raw = itemTitleText(item);
  const bracket = raw.match(/《([^》]{4,40})》/);
  if (bracket) return `book:${normalizedEventText(bracket[1]).slice(0, 36)}`;

  const normalized = normalizedEventText(raw);
  const model = normalized.match(/(bitcpmcann|deepseekv\d+(?:pro)?|grokv\d+(?:medium)?|gemini\d+(?:\.\d+)?(?:flash|pro)?|gpt\d+(?:\.\d+)?|llama\d+)/);
  if (model) return `entity:${model[1]}`;

  return `title:${normalized.slice(0, 34)}`;
}
function itemIdentityKeys(item) {
  const keys = new Set();
  if (!item) return keys;
  const url = item.url || item.primary_url;
  if (url) keys.add(`url:${url}`);
  if (item.id) keys.add(`id:${item.id}`);
  if (item.bilibili_dynamic_id) keys.add(`bilibili_dynamic:${item.bilibili_dynamic_id}`);
  if (item.bilibili_opus_id) keys.add(`bilibili_opus:${item.bilibili_opus_id}`);
  const title = item.title_zh || item.title || item.title_en || item.title_original;
  if (title) {
    keys.add(`event:${eventKey({ ...item, title, title_zh: item.title_zh || title })}`);
    keys.add(`title:${normalizedEventText(title).slice(0, 34)}`);
  }
  return keys;
}
function storyIdentityKeys(story) {
  const keys = new Set();
  if (!story) return keys;
  const refs = [
    { id: story.story_id, title: story.title, url: story.primary_url || story.url },
    story.primary_item,
    ...(Array.isArray(story.sources) ? story.sources : []),
    ...(Array.isArray(story.items) ? story.items : []),
  ].filter(Boolean);
  refs.forEach((ref) => {
    itemIdentityKeys(ref).forEach((key) => keys.add(key));
  });
  return keys;
}
function headlineRowIdentityKeys(row) {
  const keys = new Set();
  if (!row) return keys;
  const refs = [
    row.item,
    ...(Array.isArray(row.rows) ? row.rows.map((entry) => entry.item).filter(Boolean) : []),
  ].filter(Boolean);
  refs.forEach((ref) => {
    itemIdentityKeys(ref).forEach((key) => keys.add(key));
  });
  return keys;
}
function excludedStoryKeySet(rows) {
  const keys = new Set();
  rows.forEach((row) => {
    headlineRowIdentityKeys(row).forEach((key) => keys.add(key));
  });
  return keys;
}
function storyHasAnyKey(story, keys) {
  if (!keys || !keys.size) return false;
  for (const key of storyIdentityKeys(story)) {
    if (keys.has(key)) return true;
  }
  return false;
}
function sourceSignal(item) {
  const site = item.site_name || "";
  const source = item.source || "";
  const hay = `${site} ${source}`.toLowerCase();
  if (site === "AI HOT") return "AI HOT精选";
  if (hay.includes("hackernews") || hay.includes("hacker news")) return "HN热议";
  if (item.site_id === "github_foundation_sunshine_releases") return "GitHub版本订阅";
  if (item.site_id === "maobidao_wudaolu_backup") return "公众号订阅";
  if (item.site_id === "wewe_rss") return "公众号订阅";
  if (source.includes("GitHub · Trending Today") || hay.includes("github")) return "GitHub趋势";
  if (site === "Official AI Updates") return "官方更新";
  if (site === "Follow Builders") return "Builders";
  if (site === "Bilibili Dynamic" || hay.includes("bilibili")) return "B站订阅";
  if (site === "TikHub Douyin" || hay.includes("tikhub douyin") || hay.includes("mediacrawler douyin")) return "抖音订阅";
  if (site === "TikHub Xiaohongshu" || hay.includes("tikhub xiaohongshu")) return "小红书订阅";
  if (site === "MediaCrawler Xiaohongshu" || hay.includes("mediacrawler xhs") || hay.includes("mediacrawler xiaohongshu")) return "小红书订阅";
  if (hay.includes("youtube") || hay.includes("youtu.be")) return "YouTube订阅";
  if (site === "AIbase") return "AIbase";
  if (site === "OPML RSS") return "OPML";
  return site || "来源";
}
function sourcePriority(item) {
  const signal = sourceSignal(item);
  if (signal === "官方更新") return 100;
  if (signal === "AI HOT精选") return 90;
  if (signal === "AIbase") return 82;
  if (signal === "Builders") return 74;
  if (signal.includes("订阅") || signal === "抖音自媒体" || signal === "小红书自媒体") return 70;
  if (signal === "OPML") return 68;
  if (signal === "HN热议" || signal === "GitHub趋势") return 62;
  return 50;
}

state.readItemIds = loadReadItemIds();
initDataSource();
renderDataSourcePill();
renderReadFilterTools();

async function loadNewsData() {
  return fetchDataJson("latest-24h.json", "latest-24h.json", { cache: "reload" });
}
async function loadAllModeData() {
  if (state.allDataLoaded) return;
  if (!state.allDataPromise) {
    state.allDataPromise = fetchDataJson(state.allDataUrl, "latest-24h-all.json", { cache: "reload" })
      .then((payload) => {
        state.itemsAllRaw = payload.items_all_raw || payload.items_all || state.itemsAi;
        state.itemsAll = payload.items_all || state.itemsAi;
        if (Array.isArray(payload.creator_items_all) && payload.creator_items_all.length) {
          state.creatorItemsAll = payload.creator_items_all;
        }
        state.creatorWindowDays = Number(payload.creator_window_days || state.creatorWindowDays || 7);
        state.creatorTimeScope = payload.creator_time_scope || state.creatorTimeScope;
        state.totalRaw = payload.total_items_raw || state.itemsAllRaw.length;
        state.totalAllMode = payload.total_items_all_mode || state.itemsAll.length;
        state.timeScope = payload.time_scope || state.timeScope;
        state.sourceScope = payload.source_scope || state.sourceScope;
        if (payload.retention && typeof payload.retention === "object") {
          state.retention = payload.retention;
        }
        state.allDataLoaded = true;
        if (typeof renderTimeRangeControl === "function") renderTimeRangeControl();
        if (typeof renderRetentionCheckLine === "function") renderRetentionCheckLine();
      })
      .catch((err) => {
        state.allDataPromise = null;
        throw err;
      });
  }
  return state.allDataPromise;
}
function currentViewUsesCreatorPool() {
  const sectionId = state.activeSection;
  return sectionId === "creator" || sectionId === "read" || isSubscriptionSection(sectionId);
}
function applyAllModeUnavailable() {
  state.allDataLoaded = false;
  if (state.timeRangeFilter === "all" || state.mode === "all") {
    if (!Array.isArray(state.creatorItemsHour) || !state.creatorItemsHour.length) {
      state.creatorItemsHour = Array.isArray(state.creatorItemsAi) ? state.creatorItemsAi.slice() : [];
    }
    state.creatorItemsAll = [];
    state.creatorItemsAi = [];
  }
  if (typeof renderList === "function" && newsListEl) renderList();
}

function restoreHourPoolIfNeeded() {
  if (state.timeRangeFilter === "all" || state.mode === "all") return;
  if (Array.isArray(state.creatorItemsHour) && state.creatorItemsHour.length) {
    state.creatorItemsAi = state.creatorItemsHour.slice();
  }
}

function afterAllModeDataArrived() {
  if (Array.isArray(state.creatorItemsHour) && state.creatorItemsHour.length) {
    state.creatorItemsAi = state.creatorItemsHour.slice();
  }
  if (window.RadarSync && typeof window.RadarSync.markArchiveListFresh === "function") {
    window.RadarSync.markArchiveListFresh();
  }
  renderSectionTabs();
  renderTimeRangeControl();
  renderModeSwitch();
  renderCoverageStrip();
  renderSiteFilters();
  if (resultCountEl) {
    resultCountEl.textContent = `${fmtNumber(getFilteredItems().length)} 条`;
  }
  const needsListRebuild = Boolean(state.query)
    || !newsListEl.querySelector(".news-card")
    || !currentViewUsesCreatorPool();
  if (needsListRebuild) {
    renderBolePicks();
    renderList();
  }
}
async function loadWaytoagiData() {
  return fetchDataJson("waytoagi-7d.json", "waytoagi-7d.json");
}
async function loadSourceStatusData() {
  return fetchDataJson("source-status.json", "source-status.json");
}
async function loadDailyBriefData() {
  return fetchDataJson("daily-brief.json", "daily-brief.json");
}
async function loadStoriesData() {
  return fetchDataJson(state.storiesDataUrl, "stories-merged.json");
}
async function init() {
  const [newsResult, waytoagiResult, statusResult, briefResult, storiesResult] = await Promise.allSettled([
    loadNewsData(),
    loadWaytoagiData(),
    loadSourceStatusData(),
    loadDailyBriefData(),
    loadStoriesData(),
  ]);

  if (briefResult.status === "fulfilled") {
    state.dailyBrief = briefResult.value;
  } else {
    state.dailyBrief = null;
  }

  if (storiesResult.status === "fulfilled") {
    state.storiesMerged = storiesResult.value;
  } else {
    state.storiesMerged = null;
  }

  if (newsResult.status === "fulfilled") {
    const payload = newsResult.value;
    if (window.RadarSync && typeof window.RadarSync.markArchiveListUsable === "function") {
      window.RadarSync.markArchiveListUsable();
    }
    const loadedStoriesDataUrl = state.storiesDataUrl;
    state.itemsAi = payload.items_ai || payload.items || [];
    state.itemsAllRaw = payload.items_all_raw || payload.items_all || [];
    state.itemsAll = payload.items_all || [];
    state.creatorItemsHour = payload.creator_items_ai || [];
    state.creatorItemsAi = payload.creator_items_ai || [];
    const hasAllModePayload = Boolean(payload.items_all || payload.items_all_raw);
    if (hasAllModePayload) {
      state.creatorItemsAll = payload.creator_items_all || state.creatorItemsAi;
    } else {
      state.creatorItemsAll = [];
    }
    state.creatorWindowDays = Number(payload.creator_window_days || 7);
    state.creatorTimeScope = payload.creator_time_scope || "rolling_window";
    state.statsAi = payload.site_stats || [];
    state.totalAi = payload.total_items || state.itemsAi.length;
    state.totalRaw = payload.total_items_raw || state.itemsAllRaw.length;
    state.totalAllMode = payload.total_items_all_mode || state.itemsAll.length;
    state.timeScope = payload.time_scope || "rolling_window";
    state.sourceScope = payload.source_scope || "all_sources";
    state.allDataUrl = payload.all_mode_data_url || state.allDataUrl;
    state.storiesDataUrl = payload.stories_data_url || state.storiesDataUrl;
    const wantsAllModeData = state.mode === "all" || state.timeRangeFilter === "all" || state.sourceScope === "bilibili_only" || state.sourceScope === "tested_creator_sources";
    if (wantsAllModeData) {
      state.mode = "all";
      state.activeSection = "creator";
    }
    if (state.storiesDataUrl !== loadedStoriesDataUrl) {
      try {
        state.storiesMerged = await loadStoriesData();
      } catch {
        state.storiesMerged = null;
      }
    }
    state.allDataLoaded = Boolean(payload.items_all || payload.items_all_raw);
    state.generatedAt = payload.generated_at;
    if (payload.retention && typeof payload.retention === "object") {
      state.retention = payload.retention;
    }

    if (wantsAllModeData && !Boolean(payload.items_all || payload.items_all_raw)) {
      applyAllModeUnavailable();
    }

    setStats();
    renderSectionTabs();
    renderTimeRangeControl();
    if (typeof renderRetentionCheckLine === "function") renderRetentionCheckLine();
    renderModeSwitch();
    renderListSortTools();
    renderCoverageStrip();
    renderSiteFilters();
    renderBolePicks();
    renderList();
    updatedAtEl.textContent = fmtTime(state.generatedAt);

    if (wantsAllModeData && !state.allDataLoaded) {
      loadAllModeData().then(afterAllModeDataArrived).catch(() => {
        applyAllModeUnavailable();
        if (window.RadarSync && typeof window.RadarSync.markArchiveListStale === "function") {
          window.RadarSync.markArchiveListStale();
        }
      });
    }
  } else {
    updatedAtEl.textContent = "新闻数据加载失败";
    newsListEl.innerHTML = `<div class="empty">${newsResult.reason.message}</div>`;
    renderCoverageStrip(newsResult.reason.message);
    if (window.RadarSync && typeof window.RadarSync.markArchiveListStale === "function") {
      window.RadarSync.markArchiveListStale();
    }
  }

  if (statusResult.status === "fulfilled") {
    state.sourceStatus = statusResult.value;
    renderSourceHealth();
    renderCoverageStrip();
  } else {
    renderSourceHealth(statusResult.reason.message);
    renderCoverageStrip(statusResult.reason.message);
  }

  if (waytoagiResult.status === "fulfilled") {
    state.waytoagiData = waytoagiResult.value;
    renderWaytoagi(state.waytoagiData);
  } else {
    if (waytoagiWrapEl) waytoagiWrapEl.hidden = true;
    waytoagiUpdatedAtEl.textContent = "加载失败";
    waytoagiListEl.innerHTML = `<div class="waytoagi-error">${waytoagiResult.reason.message}</div>`;
  }

  renderDataSourcePill();
  renderSourceConfig();
  renderOnlineSourceConfig();
  renderLocalOpsStatus({ source_status: state.sourceStatus || {} });
  if (canUseLocalBackend()) {
    loadSourceConfigFromLocalServer();
    loadOnlineSourceConfigFromServer(true);
    loadLocalStatusFromServer(false);
    loadYoutubeSubscriptions({ silent: true });
  } else {
    setSourceConfigStatus(localBackendUnavailableMessage(), "warn");
    loadOnlineSourceConfigFromServer(true);
    setLocalOpsStatus("公网静态页", "warn");
  }
  document.dispatchEvent(new CustomEvent("aiRadar:ready"));
}

let queryApplyTimer = null;
let queryComposing = false;
const QUERY_APPLY_DELAY_MS = 250;

function applyQueryView() {
  queryApplyTimer = null;
  if (window.RadarSync) window.RadarSync.saveViewField("query", state.query);
  renderBolePicks();
  renderList();
}

function scheduleQueryApply() {
  if (queryApplyTimer) clearTimeout(queryApplyTimer);
  queryApplyTimer = setTimeout(applyQueryView, QUERY_APPLY_DELAY_MS);
}

function onSearchQueryInput(value) {
  state.query = value;
  if (window.RadarSync && typeof window.RadarSync.noteQueryEdit === "function") {
    window.RadarSync.noteQueryEdit();
  }
  scheduleQueryApply();
}

searchInputEl.addEventListener("compositionstart", () => {
  queryComposing = true;
});
searchInputEl.addEventListener("compositionend", (e) => {
  queryComposing = false;
  onSearchQueryInput(e.target.value);
});
searchInputEl.addEventListener("input", (e) => {
  if (queryComposing) {
    state.query = e.target.value;
    if (window.RadarSync && typeof window.RadarSync.noteQueryEdit === "function") {
      window.RadarSync.noteQueryEdit();
    }
    return;
  }
  onSearchQueryInput(e.target.value);
});
searchInputEl.addEventListener("blur", () => {
  if (!queryApplyTimer) return;
  clearTimeout(queryApplyTimer);
  applyQueryView();
});

siteSelectEl.addEventListener("change", (e) => {
  state.siteFilter = e.target.value;
  if (window.RadarSync) window.RadarSync.saveViewField("siteFilter", state.siteFilter);
  if (state.siteFilter !== "socialdata_x") state.authorFilter = "";
  state.siteGroupsExpanded = false;
  renderSiteFilters();
  renderBolePicks();
  renderList();
});

if (timeRangeSelectEl) {
  timeRangeSelectEl.addEventListener("change", async (e) => {
    state.timeRangeFilter = e.target.value === "all" ? "all" : "24h";
    if (window.RadarSync) window.RadarSync.saveViewField("timeRangeFilter", state.timeRangeFilter);
    if (state.timeRangeFilter === "all") {
      try {
        await loadAllModeData();
      } catch (_err) {
        applyAllModeUnavailable();
        if (window.RadarSync && typeof window.RadarSync.markArchiveListStale === "function") {
          window.RadarSync.markArchiveListStale();
        }
        if (typeof renderTimeRangeControl === "function") renderTimeRangeControl();
        rerenderCurrentView();
        return;
      }
    } else {
      restoreHourPoolIfNeeded();
    }
    rerenderCurrentView();
  });
}

if (sectionSelectEl) {
  sectionSelectEl.addEventListener("change", (e) => {
    setActiveSection(e.target.value || "hot");
    if (window.RadarSync) window.RadarSync.saveViewField("activeSection", state.activeSection);
    rerenderCurrentView();
  });
}

if (sourceTypeSelectEl) {
  sourceTypeSelectEl.addEventListener("change", (e) => {
    state.sourceTypeFilter = e.target.value;
    state.siteFilter = "";
    state.authorFilter = "";
    if (window.RadarSync) {
      window.RadarSync.saveViewPatch({
        sourceTypeFilter: state.sourceTypeFilter,
        siteFilter: state.siteFilter,
      });
    }
    rerenderCurrentView();
  });
}

if (signalLevelSelectEl) {
  signalLevelSelectEl.addEventListener("change", (e) => {
    state.signalLevelFilter = e.target.value;
    if (window.RadarSync) window.RadarSync.saveViewField("signalLevelFilter", state.signalLevelFilter);
    rerenderCurrentView();
  });
}

modeAiBtnEl.addEventListener("click", () => {
  state.mode = "ai";
  if (window.RadarSync) window.RadarSync.saveViewField("mode", state.mode);
  rerenderCurrentView();
});

modeAllBtnEl.addEventListener("click", async () => {
  state.mode = "all";
  if (window.RadarSync) window.RadarSync.saveViewField("mode", state.mode);
  renderModeSwitch();
  newsListEl.innerHTML = "";
  const loading = document.createElement("div");
  loading.className = "empty";
  loading.textContent = "正在加载全量更新...";
  newsListEl.appendChild(loading);
  try {
    await loadAllModeData();
    rerenderCurrentView();
  } catch (err) {
    newsListEl.innerHTML = "";
    const failed = document.createElement("div");
    failed.className = "empty";
    failed.textContent = err.message;
    newsListEl.appendChild(failed);
  }
});

if (allDedupeToggleEl) {
  allDedupeToggleEl.addEventListener("change", (e) => {
    state.allDedup = Boolean(e.target.checked);
    if (window.RadarSync) window.RadarSync.saveViewField("allDedup", state.allDedup);
    rerenderCurrentView();
  });
}

if (listSortToolsEl) {
  listSortToolsEl.addEventListener("click", (event) => {
    const target = event.target;
    const button = target instanceof Element ? target.closest("[data-sort]") : null;
    if (!button || !listSortToolsEl.contains(button)) return;
    const nextSort = button.dataset.sort;
    if (!LIST_SORT_DEFS.some((item) => item.id === nextSort) || nextSort === state.listSort) return;
    state.listSort = nextSort;
    if (window.RadarSync) window.RadarSync.saveViewField("listSort", state.listSort);
    renderListSortTools();
    renderList();
  });
}

if (readFilterToolsEl) {
  readFilterToolsEl.addEventListener("click", (event) => {
    const target = event.target;
    const button = target instanceof Element ? target.closest("[data-read-filter]") : null;
    if (!button || !readFilterToolsEl.contains(button)) return;
    const nextFilter = button.dataset.readFilter;
    if (!["all", "unread", "read"].includes(nextFilter) || nextFilter === state.readFilter) return;
    state.readFilter = nextFilter;
    if (window.RadarSync) window.RadarSync.saveViewField("readFilter", state.readFilter);
    renderReadFilterTools();
    renderList();
  });
}

document.addEventListener("click", (event) => {
  const target = event.target;
  const anchor = target instanceof Element ? target.closest(".app-main a[href][target=\"_blank\"]") : null;
  if (!anchor) return;
  if (document.body.classList.contains("omnia-app-mode")) event.preventDefault();
  if (window.WorkbenchBridge) window.WorkbenchBridge.openExternal(anchor.href);
}, true);

if (waytoagiTodayBtnEl) {
  waytoagiTodayBtnEl.addEventListener("click", () => {
    state.waytoagiMode = "today";
    if (state.waytoagiData) renderWaytoagi(state.waytoagiData);
  });
}

if (waytoagi7dBtnEl) {
  waytoagi7dBtnEl.addEventListener("click", () => {
    state.waytoagiMode = "7d";
    if (state.waytoagiData) renderWaytoagi(state.waytoagiData);
  });
}

if (boleHotBtnEl) {
  boleHotBtnEl.addEventListener("click", () => {
    state.boleView = "hot";
    state.boleExpanded = false;
    renderBolePicks();
  });
}

if (boleTimelineBtnEl) {
  boleTimelineBtnEl.addEventListener("click", () => {
    state.boleView = "timeline";
    state.boleExpanded = false;
    renderBolePicks();
  });
}

if (sourceConfigFormEl) {
  sourceConfigFormEl.addEventListener("submit", (event) => {
    event.preventDefault();
    saveSourceConfigForCollection().catch(() => {});
  });
  sourceConfigFormEl.addEventListener("input", syncSourceConfigFormDraft);
  sourceConfigFormEl.addEventListener("change", syncSourceConfigFormDraft);
}

if (onlineSourceFormEl) {
  onlineSourceFormEl.addEventListener("submit", (event) => {
    event.preventDefault();
    if (!saveOnlineSourceFormToState()) return;
    saveOnlineSourceConfigToServer().catch(() => {});
  });
}

if (onlineSourceFiltersEl) {
  onlineSourceFiltersEl.addEventListener("click", (event) => {
    const button = event.target.closest("[data-source-filter]");
    if (!button) return;
    state.onlineSourceFilter = button.getAttribute("data-source-filter") || "all";
    renderOnlineSourceConfig();
  });
}

if (onlineSourceTypeEl) {
  onlineSourceTypeEl.addEventListener("change", renderOnlineSourceFormHints);
}

if (onlineSourceClearBtnEl) {
  onlineSourceClearBtnEl.addEventListener("click", clearOnlineSourceForm);
}

if (onlineSourceSyncBtnEl) {
  onlineSourceSyncBtnEl.addEventListener("click", () => {
    syncOnlineSourceConfigToServer().catch(() => {});
  });
}

if (orphanPurgeReloadBtnEl) {
  orphanPurgeReloadBtnEl.addEventListener("click", () => {
    loadOrphanPurgePreview().catch(() => {});
  });
}

if (orphanPurgeDeleteBtnEl) {
  orphanPurgeDeleteBtnEl.addEventListener("click", () => {
    deleteSelectedOrphanHistory().catch(() => {});
  });
}

if (orphanPurgeSelectAllEl) {
  orphanPurgeSelectAllEl.addEventListener("change", toggleOrphanPurgeSelectAll);
}

if (subscriptionMemberFormEl) {
  subscriptionMemberFormEl.addEventListener("submit", async (event) => {
    event.preventDefault();
    const ok = upsertSubscriptionMember({
      name: subscriptionMemberNameEl.value,
      locator: subscriptionMemberLocatorEl.value,
      htmlUrl: subscriptionMemberHomeUrlEl?.value || "",
    });
    if (!ok) return;
    try {
      await saveSubscriptionMembers();
    } catch (err) {
      setSubscriptionManagerStatus(`保存订阅失败：${err.message}`, "bad");
    }
  });
}

if (subscriptionMemberClearBtnEl) {
  subscriptionMemberClearBtnEl.addEventListener("click", clearSubscriptionMemberForm);
}

if (sourceConfigAddBtnEl) {
  sourceConfigAddBtnEl.addEventListener("click", addSourceConfigRecord);
}

if (sourceConfigDeleteBtnEl) {
  sourceConfigDeleteBtnEl.addEventListener("click", deleteSourceConfigRecord);
}

if (sourceConfigResetBtnEl) {
  sourceConfigResetBtnEl.addEventListener("click", resetSourceConfigDraft);
}

if (sourceCollectionScopeSelectEl) {
  try {
    const savedScope = window.localStorage.getItem(COLLECTION_SCOPE_STORAGE_KEY);
    sourceCollectionScopeSelectEl.value = savedScope === "all" ? "all" : "24h";
  } catch {
    sourceCollectionScopeSelectEl.value = "24h";
  }
  sourceCollectionScopeSelectEl.addEventListener("change", selectedCollectionScope);
}

if (oneClickCollectBtnEl) {
  oneClickCollectBtnEl.addEventListener("click", runOneClickCollect);
}

if (sourceConfigRefreshBtnEl) {
  sourceConfigRefreshBtnEl.addEventListener("click", refreshNewsDataFromLocalServer);
}

if (sourceConfigCheckBtnEl) {
  sourceConfigCheckBtnEl.addEventListener("click", () => {
    setLocalOpsStatus("检查中", "warn");
    loadLocalStatusFromServer(true);
  });
}

if (localServerRestartBtnEl) {
  localServerRestartBtnEl.addEventListener("click", restartLocalServerFromPage);
}

init();

state.readItemIds = loadReadItemIds();
initDataSource();
renderDataSourcePill();

async function loadNewsData() {
  return fetchDataJson("latest-24h.json", "latest-24h.json");
}
async function loadAllModeData() {
  if (state.allDataLoaded) return;
  if (!state.allDataPromise) {
    state.allDataPromise = fetchDataJson(state.allDataUrl, "latest-24h-all.json")
      .then((payload) => {
        state.itemsAllRaw = payload.items_all_raw || payload.items_all || state.itemsAi;
        state.itemsAll = payload.items_all || state.itemsAi;
        state.creatorItemsAll = payload.creator_items_all || state.creatorItemsAll;
        state.creatorWindowDays = Number(payload.creator_window_days || state.creatorWindowDays || 7);
        state.creatorTimeScope = payload.creator_time_scope || state.creatorTimeScope;
        state.totalRaw = payload.total_items_raw || state.itemsAllRaw.length;
        state.totalAllMode = payload.total_items_all_mode || state.itemsAll.length;
        state.timeScope = payload.time_scope || state.timeScope;
        state.sourceScope = payload.source_scope || state.sourceScope;
        state.allDataLoaded = true;
      })
      .catch((err) => {
        state.allDataPromise = null;
        throw err;
      });
  }
  return state.allDataPromise;
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
    const loadedStoriesDataUrl = state.storiesDataUrl;
    state.itemsAi = payload.items_ai || payload.items || [];
    state.itemsAllRaw = payload.items_all_raw || payload.items_all || [];
    state.itemsAll = payload.items_all || [];
    state.creatorItemsAi = payload.creator_items_ai || [];
    state.creatorItemsAll = payload.creator_items_all || state.creatorItemsAi;
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
    if (state.mode === "all" || state.timeRangeFilter === "all" || state.sourceScope === "bilibili_only" || state.sourceScope === "tested_creator_sources") {
      state.mode = "all";
      state.activeSection = "creator";
      try {
        await loadAllModeData();
      } catch {
        state.mode = "ai";
      }
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

    setStats();
    renderSectionTabs();
    renderTimeRangeControl();
    renderModeSwitch();
    renderListSortTools();
    renderCoverageStrip();
    renderSiteFilters();
    renderBolePicks();
    renderList();
    updatedAtEl.textContent = fmtTime(state.generatedAt);
  } else {
    updatedAtEl.textContent = "新闻数据加载失败";
    newsListEl.innerHTML = `<div class="empty">${newsResult.reason.message}</div>`;
    renderCoverageStrip(newsResult.reason.message);
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
  renderLocalOpsStatus({ source_status: state.sourceStatus || {} });
  if (canUseLocalBackend()) {
    loadSourceConfigFromLocalServer();
    loadLocalStatusFromServer(false);
    loadYoutubeSubscriptions({ silent: true });
  } else {
    setSourceConfigStatus(localBackendUnavailableMessage(), "warn");
    setLocalOpsStatus("公网静态页", "warn");
  }
  document.dispatchEvent(new CustomEvent("aiRadar:ready"));
}

searchInputEl.addEventListener("input", (e) => {
  state.query = e.target.value;
  renderBolePicks();
  renderList();
});

siteSelectEl.addEventListener("change", (e) => {
  state.siteFilter = e.target.value;
  if (state.siteFilter !== "socialdata_x") state.authorFilter = "";
  state.siteGroupsExpanded = false;
  renderSiteFilters();
  renderBolePicks();
  renderList();
});

if (timeRangeSelectEl) {
  timeRangeSelectEl.addEventListener("change", async (e) => {
    state.timeRangeFilter = e.target.value === "all" ? "all" : "24h";
    if (state.timeRangeFilter === "all") {
      try {
        await loadAllModeData();
      } catch (err) {
        state.timeRangeFilter = "24h";
        renderTimeRangeControl();
        newsListEl.innerHTML = "";
        const failed = document.createElement("div");
        failed.className = "empty";
        failed.textContent = err.message;
        newsListEl.appendChild(failed);
        return;
      }
    }
    rerenderCurrentView();
  });
}

if (sectionSelectEl) {
  sectionSelectEl.addEventListener("change", (e) => {
    setActiveSection(e.target.value || "hot");
    rerenderCurrentView();
  });
}

if (sourceTypeSelectEl) {
  sourceTypeSelectEl.addEventListener("change", (e) => {
    state.sourceTypeFilter = e.target.value;
    state.siteFilter = "";
    state.authorFilter = "";
    rerenderCurrentView();
  });
}

if (signalLevelSelectEl) {
  signalLevelSelectEl.addEventListener("change", (e) => {
    state.signalLevelFilter = e.target.value;
    rerenderCurrentView();
  });
}

modeAiBtnEl.addEventListener("click", () => {
  state.mode = "ai";
  rerenderCurrentView();
});

modeAllBtnEl.addEventListener("click", async () => {
  state.mode = "all";
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
    renderListSortTools();
    renderList();
  });
}

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

if (subscriptionMemberSyncBtnEl) {
  subscriptionMemberSyncBtnEl.addEventListener("click", () => {
    syncWeweRssSubscriptions().catch(() => {});
  });
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

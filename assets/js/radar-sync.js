// AI 雷达多端同步适配器：只处理同步状态与页面状态，不负责具体传输。
(function () {
  const VIEW_FIELDS = new Set([
    "activeSection",
    "query",
    "listSort",
    "timeRangeFilter",
    "sourceTypeFilter",
    "signalLevelFilter",
    "siteFilter",
    "mode",
    "allDedup",
    "readFilter",
  ]);
  const VALID_SORTS = new Set(["priority", "time", "ai", "source"]);
  const VALID_READ_FILTERS = new Set(["all", "unread", "read"]);
  const VALID_SOURCE_TYPES = new Set(["", "official", "media", "community", "rss", "aggregate", "creator", "advanced"]);
  const VALID_SIGNAL_LEVELS = new Set(["", "high", "curated", "multi"]);
  const MAX_READ_STATUS_BATCH_SIZE = 24;
  const MAX_BRIDGE_MESSAGE_LENGTH = 65536;
  const MAX_REQUEST_ID_PLACEHOLDER = "x".repeat(120);
  const LEGACY_READ_MIGRATION_STORAGE_KEY = "ai-news-radar-read-migration-v1";
  let protocolV1 = false;
  let syncAvailable = false;
  let readOnly = true;
  let dataReady = false;
  let queuedState = null;
  let authoritativeReadState = false;
  let viewRevision = 0;
  let serverReadKeys = new Set();
  let legacyReadMigration = { version: 1, status: "complete", migrationId: "" };
  let queuedViewPatch = null;
  let viewSaveInFlight = false;
  let sourceConfigLoadStarted = false;

  function setStatus(text, tone = "") {
    if (!radarSyncStatusEl) return;
    radarSyncStatusEl.hidden = !text;
    radarSyncStatusEl.textContent = text;
    radarSyncStatusEl.classList.toggle("warn", tone === "warn");
  }

  function enterSyncUnavailable() {
    syncAvailable = false;
    readOnly = true;
    authoritativeReadState = false;
    queuedViewPatch = null;
    setStatus("同步暂停", "warn");
    if (dataReady && typeof rerenderCurrentView === "function") rerenderCurrentView();
  }

  function normalizedUrl(value) {
    try {
      const url = new URL(String(value || ""));
      if (!/^https?:$/.test(url.protocol)) return "";
      url.hash = "";
      return url.toString();
    } catch {
      return "";
    }
  }

  function stableReadKey(item) {
    const url = normalizedUrl(item?.url || item?.primary_url);
    if (url) return url;
    const siteId = String(item?.site_id || "").trim();
    const itemId = String(item?.id || item?.bilibili_dynamic_id || item?.bilibili_opus_id || "").trim();
    return siteId && itemId ? `source:${siteId}:${itemId}` : "";
  }

  function allLoadedItems() {
    const pools = [state.itemsAi, state.itemsAll, state.itemsAllRaw, state.creatorItemsAi, state.creatorItemsAll];
    const unique = new Map();
    pools.flat().forEach((item) => {
      const key = stableReadKey(item);
      if (key && !unique.has(key)) unique.set(key, item);
    });
    return Array.from(unique.values());
  }

  function normalizeView(view) {
    const source = view && typeof view === "object" ? view : {};
    const activeSection = SECTION_BY_ID[source.activeSection] ? source.activeSection : state.activeSection;
    return {
      activeSection,
      query: typeof source.query === "string" ? source.query.slice(0, 200) : state.query,
      listSort: source.listSort === "signal"
        ? "priority"
        : (VALID_SORTS.has(source.listSort) ? source.listSort : state.listSort),
      timeRangeFilter: source.timeRangeFilter === "24h" ? "24h" : "all",
      sourceTypeFilter: VALID_SOURCE_TYPES.has(source.sourceTypeFilter) ? source.sourceTypeFilter : "",
      signalLevelFilter: VALID_SIGNAL_LEVELS.has(source.signalLevelFilter) ? source.signalLevelFilter : "",
      siteFilter: typeof source.siteFilter === "string" ? source.siteFilter.slice(0, 120) : "",
      mode: source.mode === "ai" ? "ai" : "all",
      allDedup: typeof source.allDedup === "boolean" ? source.allDedup : true,
      readFilter: VALID_READ_FILTERS.has(source.readFilter) ? source.readFilter : "unread",
    };
  }

  function replaceServerReads(keys) {
    serverReadKeys = new Set((Array.isArray(keys) ? keys : []).map(String).filter(Boolean));
    allLoadedItems().forEach((item) => {
      const trackingKeys = readTrackingKeys(item);
      trackingKeys.forEach((key) => state.readItemIds.delete(key));
      if (serverReadKeys.has(stableReadKey(item))) {
        trackingKeys.forEach((key) => state.readItemIds.add(key));
      }
    });
    persistReadItemIds();
  }

  function normalizeLegacyReadMigration(value) {
    if (!value || typeof value !== "object" || Number(value.version) !== 1) {
      return { version: 1, status: "complete", migrationId: "" };
    }
    const status = ["open", "claimed", "complete"].includes(value.status) ? value.status : "complete";
    const migrationId = typeof value.migrationId === "string" ? value.migrationId.slice(0, 120) : "";
    return { version: 1, status, migrationId };
  }

  function localMigrationId(allowCreate) {
    try {
      const existing = String(window.localStorage.getItem(LEGACY_READ_MIGRATION_STORAGE_KEY) || "").trim();
      if (existing) return existing.slice(0, 120);
      if (!allowCreate) return "";
      const generated = `migration-${typeof crypto?.randomUUID === "function" ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(16).slice(2)}`}`;
      window.localStorage.setItem(LEGACY_READ_MIGRATION_STORAGE_KEY, generated);
      return window.localStorage.getItem(LEGACY_READ_MIGRATION_STORAGE_KEY) === generated ? generated : "";
    } catch {
      return "";
    }
  }

  function migrationEnvelopeLength(migrationId, keys, complete) {
    return JSON.stringify({
      version: 1,
      type: "radar-read-migration",
      requestId: MAX_REQUEST_ID_PLACEHOLDER,
      payload: { migrationId, keys, complete },
    }).length;
  }

  function migrationBatches(migrationId, keys) {
    const batches = [];
    let batch = [];
    keys.forEach((key) => {
      const candidate = [...batch, key];
      if (candidate.length > MAX_READ_STATUS_BATCH_SIZE
        || migrationEnvelopeLength(migrationId, candidate, false) > MAX_BRIDGE_MESSAGE_LENGTH) {
        if (batch.length) batches.push(batch);
        batch = [key];
        return;
      }
      batch = candidate;
    });
    if (batch.length) batches.push(batch);
    return batches;
  }

  async function migrateLegacyReads(keys) {
    if (!window.WorkbenchBridge.connected()) return false;
    if (!["open", "claimed"].includes(legacyReadMigration.status)) return false;
    const candidates = Array.isArray(keys) ? keys.filter(Boolean) : [];
    if (!candidates.length) return false;
    const existingId = localMigrationId(false);
    if (legacyReadMigration.status === "claimed" && existingId !== legacyReadMigration.migrationId) return false;
    const migrationId = existingId || localMigrationId(true);
    if (!migrationId) return false;
    try {
      for (const batch of migrationBatches(migrationId, candidates)) {
        const result = await window.WorkbenchBridge.request("radar-read-migration", {
          migrationId,
          keys: batch,
          complete: false,
        });
        legacyReadMigration = normalizeLegacyReadMigration(result.legacyReadMigration);
      }
      const completed = await window.WorkbenchBridge.request("radar-read-migration", {
        migrationId,
        keys: [],
        complete: true,
      });
      legacyReadMigration = normalizeLegacyReadMigration(completed.legacyReadMigration);
      return legacyReadMigration.status === "complete";
    } catch (error) {
      if (Number(error?.status) === 409 || Number(error?.statusCode) === 409) return false;
      throw error;
    }
  }

  function readStatusEnvelopeLength(keys) {
    return JSON.stringify({
      version: 1,
      type: "radar-read-status",
      requestId: MAX_REQUEST_ID_PLACEHOLDER,
      payload: { keys },
    }).length;
  }

  function readStatusBatches(keys) {
    const batches = [];
    let batch = [];
    keys.forEach((key) => {
      const candidate = [...batch, key];
      if (candidate.length > MAX_READ_STATUS_BATCH_SIZE
        || readStatusEnvelopeLength(candidate) > MAX_BRIDGE_MESSAGE_LENGTH) {
        if (batch.length) batches.push(batch);
        batch = [key];
        return;
      }
      batch = candidate;
    });
    if (batch.length) batches.push(batch);
    return batches;
  }

  async function loadReadStatus({ render = true } = {}) {
    if (!dataReady || !canSync()) return;
    const legacyCandidates = allLoadedItems().filter((item) => isItemRead(item)).map(stableReadKey).filter(Boolean);
    const keys = allLoadedItems().map(stableReadKey).filter(Boolean);
    const matched = [];
    for (const batch of readStatusBatches(keys)) {
      if (readStatusEnvelopeLength(batch) > MAX_BRIDGE_MESSAGE_LENGTH) continue;
      const result = await window.WorkbenchBridge.request("radar-read-status", { keys: batch });
      if (Array.isArray(result.readKeys)) matched.push(...result.readKeys);
    }
    replaceServerReads(matched);
    authoritativeReadState = true;
    if (render) rerenderCurrentView();
    if (await migrateLegacyReads(legacyCandidates)) {
      const refreshed = [];
      for (const batch of readStatusBatches(keys)) {
        const result = await window.WorkbenchBridge.request("radar-read-status", { keys: batch });
        if (Array.isArray(result.readKeys)) refreshed.push(...result.readKeys);
      }
      replaceServerReads(refreshed);
      if (render) rerenderCurrentView();
    }
  }

  async function applyState(snapshot, { render = true } = {}) {
    if (!snapshot || typeof snapshot !== "object") return;
    if (!dataReady) {
      queuedState = snapshot;
      return;
    }
    const view = normalizeView(snapshot.view);
    legacyReadMigration = normalizeLegacyReadMigration(snapshot.legacyReadMigration);
    viewRevision = Number.isInteger(snapshot.viewRevision) ? snapshot.viewRevision : 0;
    Object.assign(state, view);
    const hasInlineReadKeys = Array.isArray(snapshot.readKeys);
    if (hasInlineReadKeys) {
      replaceServerReads(snapshot.readKeys);
      authoritativeReadState = true;
    }
    searchInputEl.value = state.query;
    sourceTypeSelectEl.value = state.sourceTypeFilter;
    signalLevelSelectEl.value = state.signalLevelFilter;
    if ((state.mode === "all" || state.timeRangeFilter === "all") && typeof loadAllModeData === "function") {
      try {
        await loadAllModeData();
      } catch {
        setStatus("同步暂停", "warn");
      }
    }
    if (render) rerenderCurrentView();
    if (!hasInlineReadKeys) await loadReadStatus({ render });
  }

  function canSync() {
    return protocolV1 && syncAvailable && !readOnly && window.WorkbenchBridge.connected();
  }

  function loadSourceConfigFromHost() {
    if (sourceConfigLoadStarted || !window.WorkbenchBridge.readerOnlyRequested()) return;
    sourceConfigLoadStarted = true;
    window.WorkbenchBridge.request("radar-source-config-read")
      .then((result) => {
        if (typeof window.applyBridgedOnlineSourceConfig === "function") {
          window.applyBridgedOnlineSourceConfig(result.config);
        }
      })
      .catch(() => {
        sourceConfigLoadStarted = false;
      });
  }

  function handleHostMessage(message) {
    if (!message || typeof message !== "object") return;
    if (message.type === "workbench-hello") {
      protocolV1 = Number(message.version) === 1;
      if (!protocolV1) return;
      syncAvailable = message.syncAvailable === true;
      readOnly = message.readOnly === true;
      authoritativeReadState = false;
      setStatus(canSync() ? "已同步" : "同步暂停", canSync() ? "" : "warn");
      applyState(message.state).catch(enterSyncUnavailable);
      loadSourceConfigFromHost();
      return;
    }
    if (message.type === "radar-read-migration-result") {
      legacyReadMigration = normalizeLegacyReadMigration(message.legacyReadMigration);
      const isConflict = Number(message.status) === 409 || Number(message.statusCode) === 409;
      if (message.state && typeof message.state === "object") {
        const snapshot = message.state;
        requestAnimationFrame(() => requestAnimationFrame(() => {
          authoritativeReadState = true;
          applyState(snapshot, { render: false }).catch(enterSyncUnavailable);
        }));
      }
      if (!message.ok && !isConflict) {
        enterSyncUnavailable();
      } else {
        setStatus("已同步");
      }
      return;
    }
    if (message.type !== "radar-state-result") return;
    if (message.ok === false) {
      if (Number(message.status) === 409 || Number(message.statusCode) === 409) {
        setStatus("其他设备已更新，请重新操作", "warn");
      } else {
        enterSyncUnavailable();
      }
    } else {
      setStatus("已同步");
    }
    if (message.state && typeof message.state === "object") {
      authoritativeReadState = true;
      applyState(message.state).catch(enterSyncUnavailable);
    }
  }

  async function flushViewPatch() {
    if (viewSaveInFlight || !queuedViewPatch || !canSync()) return;
    viewSaveInFlight = true;
    while (queuedViewPatch && canSync()) {
      const patch = queuedViewPatch;
      queuedViewPatch = null;
      try {
        await window.WorkbenchBridge.request("radar-view-patch", {
          baseRevision: viewRevision,
          patch,
        });
      } catch {
        // 409 或桥失败时服从宿主回传状态，不自动重放旧操作。
        queuedViewPatch = null;
        break;
      }
    }
    viewSaveInFlight = false;
  }

  function saveViewPatch(patch) {
    if (!patch || typeof patch !== "object" || !canSync()) return false;
    const fields = Object.keys(patch);
    if (!fields.length || fields.some((field) => !VIEW_FIELDS.has(field))) return false;
    queuedViewPatch = { ...(queuedViewPatch || {}), ...patch };
    flushViewPatch();
    return true;
  }

  function saveViewField(field, value) {
    return saveViewPatch({ [field]: value });
  }

  function markRead(item) {
    if (!canSync()) return false;
    const key = stableReadKey(item);
    if (!key) return false;
    serverReadKeys.add(key);
    window.WorkbenchBridge.request("radar-read", { keys: [key] }).catch(() => {});
    return true;
  }

  function canWriteCollections() {
    if (!window.WorkbenchBridge.connected()) return false;
    return protocolV1 ? canSync() : true;
  }

  document.addEventListener("aiRadar:ready", () => {
    dataReady = true;
    if (queuedState) {
      const snapshot = queuedState;
      queuedState = null;
      applyState(snapshot).catch(enterSyncUnavailable);
    } else {
      loadReadStatus().catch(enterSyncUnavailable);
    }
  });

  window.RadarSync = {
    saveViewField,
    saveViewPatch,
    markRead,
    monotonicReads() {
      return protocolV1 && authoritativeReadState && window.WorkbenchBridge.connected();
    },
    canWriteCollections,
  };

  window.WorkbenchBridge.setMessageHandler(handleHostMessage);
  window.WorkbenchBridge.setWriteFailureHandler(() => enterSyncUnavailable());
  if (window.WorkbenchBridge.appRequested() && !window.WorkbenchBridge.connected()) {
    setStatus("正在连接同步…", "warn");
    setTimeout(() => {
      if (!window.WorkbenchBridge.connected()) setStatus("同步暂停", "warn");
    }, 3000);
  }
})();

const ONLINE_SOURCE_TYPE_DEFS = {
  bilibili_dynamic: {
    label: "B站 UP",
    nameLabel: "UP 主名称",
    locatorLabel: "B站 UID",
    locatorPlaceholder: "例如：316183842",
    channel: "B站动态",
  },
  github_release: {
    label: "GitHub Release",
    nameLabel: "显示名称",
    locatorLabel: "owner/repo 或仓库 URL",
    locatorPlaceholder: "例如：AlkaidLab/foundation-sunshine",
    channel: "GitHub Release",
  },
  rss: {
    label: "RSS/YouTube",
    nameLabel: "Feed 标题",
    locatorLabel: "RSS/Atom/YouTube feed URL",
    locatorPlaceholder: "例如：https://www.youtube.com/feeds/videos.xml?channel_id=UC...",
    channel: "RSS/YouTube",
  },
};

function onlineSourceTypeDef(type = onlineSourceTypeEl?.value) {
  return ONLINE_SOURCE_TYPE_DEFS[type] || ONLINE_SOURCE_TYPE_DEFS.rss;
}

function onlineSourceTypeLabel(type) {
  return onlineSourceTypeDef(type).label;
}

function onlineSourceFormActionLabel() {
  return "保存配置";
}

function setOnlineSourceStatus(message, tone = "") {
  if (!onlineSourceStatusEl) return;
  onlineSourceStatusEl.textContent = message || "";
  onlineSourceStatusEl.className = `online-source-status${tone ? ` ${tone}` : ""}`;
}

function setOnlineSourceButton(button, label, disabled = false) {
  if (!button) return;
  button.textContent = label;
  button.disabled = Boolean(disabled);
}

function restoreOnlineSourceButton(button, label, delay = 1200) {
  if (!button) return;
  window.setTimeout(() => {
    button.textContent = label;
    button.disabled = false;
  }, delay);
}

function onlineSourceDraftId(type, locator, name) {
  const base = normalizeSourceConfigToken(locator || name || "online_source");
  return `draft_${type}_${base}`.slice(0, 90);
}

function normalizeOnlineSourceRecord(source, index = 0) {
  const type = String(source?.type || "rss").trim() || "rss";
  const def = onlineSourceTypeDef(type);
  const name = String(source?.name || source?.target || "").trim() || `线上信源 ${index + 1}`;
  const locator = String(source?.locator || source?.url || "").trim();
  return {
    id: String(source?.id || onlineSourceDraftId(type, locator, name)).trim(),
    name,
    type,
    enabled: source?.enabled !== false,
    channel: String(source?.channel || def.channel || def.label).trim(),
    target: String(source?.target || name).trim(),
    locator,
    env: "",
    notes: String(source?.notes || "").trim(),
  };
}

function normalizeOnlineSourceConfig(payload = {}) {
  const sources = Array.isArray(payload.sources) ? payload.sources : [];
  return {
    ...payload,
    sources: sources
      .filter((source) => source && typeof source === "object")
      .filter((source) => String(source.id || "") !== "online_opmlrss" && String(source.type || "") !== "opmlrss")
      .map(normalizeOnlineSourceRecord),
  };
}

function onlineSourcePayload() {
  return {
    version: "1.0",
    sources: (state.onlineSourceConfig?.sources || []).map((source) => ({
      id: source.id,
      name: source.name,
      type: source.type,
      enabled: source.enabled !== false,
      channel: source.channel,
      target: source.target || source.name,
      locator: source.locator,
      env: "",
      notes: source.notes || "",
    })),
  };
}

function markOnlineSourceDirty(message = "未保存") {
  state.onlineSourceDirty = true;
  setOnlineSourceStatus(message, "warn");
}

function renderOnlineSourceFormHints() {
  if (!onlineSourceTypeEl) return;
  const def = onlineSourceTypeDef();
  if (onlineSourceNameLabelEl) onlineSourceNameLabelEl.textContent = def.nameLabel;
  if (onlineSourceLocatorLabelEl) onlineSourceLocatorLabelEl.textContent = def.locatorLabel;
  if (onlineSourceLocatorEl) onlineSourceLocatorEl.placeholder = def.locatorPlaceholder;
  if (onlineSourceSaveBtnEl) {
    onlineSourceSaveBtnEl.textContent = onlineSourceFormActionLabel();
  }
}

function clearOnlineSourceForm() {
  if (onlineSourceFormEl) delete onlineSourceFormEl.dataset.sourceId;
  if (onlineSourceTypeEl) onlineSourceTypeEl.value = "bilibili_dynamic";
  if (onlineSourceNameEl) onlineSourceNameEl.value = "";
  if (onlineSourceLocatorEl) onlineSourceLocatorEl.value = "";
  if (onlineSourceNotesEl) onlineSourceNotesEl.value = "";
  if (onlineSourceEnabledEl) onlineSourceEnabledEl.checked = true;
  renderOnlineSourceFormHints();
}

function onlineSourceFormRecord() {
  const type = onlineSourceTypeEl?.value || "rss";
  const def = onlineSourceTypeDef(type);
  const name = String(onlineSourceNameEl?.value || "").trim();
  const locator = String(onlineSourceLocatorEl?.value || "").trim();
  const existingId = onlineSourceFormEl?.dataset?.sourceId || "";
  return {
    id: existingId || onlineSourceDraftId(type, locator, name),
    name,
    type,
    enabled: onlineSourceEnabledEl?.checked !== false,
    channel: def.channel,
    target: name,
    locator,
    env: "",
    notes: String(onlineSourceNotesEl?.value || "").trim(),
  };
}

function saveOnlineSourceFormToState() {
  const record = onlineSourceFormRecord();
  if (!record.name || !record.locator) {
    setOnlineSourceStatus("名称和关键字段都要填写", "bad");
    return false;
  }
  if (!state.onlineSourceConfig) state.onlineSourceConfig = { sources: [] };
  const sources = state.onlineSourceConfig.sources || [];
  const index = sources.findIndex((source) => source.id === record.id);
  if (index >= 0) {
    sources[index] = record;
  } else {
    sources.push(record);
  }
  state.onlineSourceConfig.sources = sources;
  state.onlineSourceSelectedId = record.id;
  clearOnlineSourceForm();
  renderOnlineSourceConfig();
  markOnlineSourceDirty("未保存：点“保存配置”只写公开配置，点“同步到线上”会提交并推送");
  return true;
}

function syncOnlineSourceFormIfFilled() {
  const hasAnyValue = [onlineSourceNameEl?.value, onlineSourceLocatorEl?.value, onlineSourceNotesEl?.value]
    .some((value) => String(value || "").trim());
  if (!hasAnyValue) return true;
  return saveOnlineSourceFormToState();
}

function editOnlineSourceRecord(record) {
  if (!record) return;
  if (onlineSourceFormEl) onlineSourceFormEl.dataset.sourceId = record.id;
  if (onlineSourceTypeEl) onlineSourceTypeEl.value = record.type || "rss";
  if (onlineSourceNameEl) onlineSourceNameEl.value = record.name || "";
  if (onlineSourceLocatorEl) onlineSourceLocatorEl.value = record.locator || "";
  if (onlineSourceNotesEl) onlineSourceNotesEl.value = record.notes || "";
  if (onlineSourceEnabledEl) onlineSourceEnabledEl.checked = record.enabled !== false;
  renderOnlineSourceFormHints();
  setOnlineSourceStatus(`正在编辑：${record.name}`, "warn");
}

function removeOnlineSourceRecord(recordId) {
  state.onlineSourceConfig.sources = (state.onlineSourceConfig?.sources || []).filter((source) => source.id !== recordId);
  clearOnlineSourceForm();
  renderOnlineSourceConfig();
  markOnlineSourceDirty("未保存：已从线上信源草稿删除");
}

function toggleOnlineSourceRecord(recordId, enabled) {
  const source = (state.onlineSourceConfig?.sources || []).find((item) => item.id === recordId);
  if (!source) return;
  source.enabled = Boolean(enabled);
  renderOnlineSourceConfig();
  markOnlineSourceDirty("未保存：启用状态已变更");
}

function renderOnlineSourceList() {
  if (!onlineSourceListEl) return;
  onlineSourceListEl.innerHTML = "";
  const isLocal = canUseLocalBackend();
  const sources = state.onlineSourceConfig?.sources || [];
  const visibleSources = isLocal ? sources : sources.filter((source) => source.enabled !== false);
  if (!visibleSources.length) {
    const empty = document.createElement("div");
    empty.className = "online-source-empty";
    empty.textContent = isLocal ? "当前还没有线上公开信源。" : "当前线上没有启用的公开信源。";
    onlineSourceListEl.appendChild(empty);
    return;
  }
  visibleSources.forEach((source) => {
    const card = document.createElement("article");
    card.className = `online-source-card${source.enabled === false ? " disabled" : ""}`;
    const main = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = source.name;
    const meta = document.createElement("span");
    meta.textContent = `${onlineSourceTypeLabel(source.type)} · ${source.locator}`;
    main.append(title, meta);

    card.appendChild(main);
    if (isLocal) {
      const actions = document.createElement("div");
      actions.className = "online-source-actions";
      const toggleLabel = document.createElement("label");
      toggleLabel.className = "online-source-toggle";
      const toggle = document.createElement("input");
      toggle.type = "checkbox";
      toggle.checked = source.enabled !== false;
      toggle.addEventListener("change", () => toggleOnlineSourceRecord(source.id, toggle.checked));
      const toggleText = document.createElement("span");
      toggleText.textContent = "启用";
      toggleLabel.append(toggle, toggleText);

      const editBtn = document.createElement("button");
      editBtn.type = "button";
      editBtn.className = "tool-btn";
      editBtn.textContent = "编辑";
      editBtn.addEventListener("click", () => editOnlineSourceRecord(source));

      const deleteBtn = document.createElement("button");
      deleteBtn.type = "button";
      deleteBtn.className = "tool-btn danger";
      deleteBtn.textContent = "删除";
      deleteBtn.addEventListener("click", () => removeOnlineSourceRecord(source.id));

      actions.append(toggleLabel, editBtn, deleteBtn);
      card.appendChild(actions);
    }
    onlineSourceListEl.appendChild(card);
  });
}

function renderOnlineSourceConfig() {
  if (!onlineSourceFormEl && !onlineSourceListEl) return;
  if (!state.onlineSourceConfig) state.onlineSourceConfig = { sources: [] };
  const isLocal = canUseLocalBackend();
  [
    onlineSourceTypeEl,
    onlineSourceNameEl,
    onlineSourceLocatorEl,
    onlineSourceNotesEl,
    onlineSourceEnabledEl,
    onlineSourceSaveBtnEl,
    onlineSourceClearBtnEl,
    onlineSourceSyncBtnEl,
  ].forEach((node) => {
    if (node) node.disabled = !isLocal;
  });
  if (onlineSourceFormEl) onlineSourceFormEl.hidden = !isLocal;
  renderOnlineSourceFormHints();
  renderOnlineSourceList();
  if (!isLocal) {
    const enabledCount = (state.onlineSourceConfig?.sources || []).filter((source) => source.enabled !== false).length;
    const message = enabledCount
      ? `线上实际追踪 ${fmtNumber(enabledCount)} 个公开信源；修改请在本机打开 127.0.0.1:8080。`
      : "公网静态页不能直接修改线上配置；请在本机打开 127.0.0.1:8080 使用本地控制台同步。";
    setOnlineSourceStatus(message, enabledCount ? "ok" : "warn");
  }
}

async function loadOnlineSourceConfigFromServer(silent = false) {
  if (!onlineSourceListEl) {
    renderOnlineSourceConfig();
    return null;
  }
  const isLocal = canUseLocalBackend();
  const configUrl = isLocal ? "./api/online-source-config" : "./config/online-sources.json";
  try {
    const res = await fetch(configUrl, {
      headers: { Accept: "application/json" },
      cache: "no-store",
    });
    const payload = await res.json().catch(() => ({}));
    if (!res.ok || payload.ok === false) throw new Error(payload.error || `HTTP ${res.status}`);
    state.onlineSourceConfig = normalizeOnlineSourceConfig(payload);
    state.onlineSourceDirty = false;
    renderOnlineSourceConfig();
    if (!silent) {
      const sourceCount = payload.source_count || state.onlineSourceConfig.sources.length;
      const prefix = isLocal ? "已读取" : "已同步线上实际追踪源";
      setOnlineSourceStatus(`${prefix} ${payload.path || "config/online-sources.json"}，共 ${fmtNumber(sourceCount)} 个线上信源`, "ok");
    }
    return payload;
  } catch (err) {
    setOnlineSourceStatus(`线上信源读取失败：${err.message}`, "bad");
    renderOnlineSourceConfig();
    return null;
  }
}

async function saveOnlineSourceConfigToServer() {
  if (!canUseLocalBackend()) {
    setOnlineSourceStatus(localBackendUnavailableMessage(), "warn");
    return null;
  }
  if (!syncOnlineSourceFormIfFilled()) return null;
  setOnlineSourceButton(onlineSourceSaveBtnEl, "保存中...", true);
  setOnlineSourceStatus("正在写入公开线上配置...", "warn");
  try {
    const res = await fetch("./api/online-source-config", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(onlineSourcePayload()),
    });
    const payload = await res.json().catch(() => ({}));
    if (!res.ok || payload.ok === false) throw new Error(payload.error || `HTTP ${res.status}`);
    state.onlineSourceConfig = normalizeOnlineSourceConfig(payload);
    state.onlineSourceDirty = false;
    renderOnlineSourceConfig();
    setOnlineSourceStatus(`已写入本地线上配置：${fmtNumber(payload.source_count || 0)} 个信源`, "ok");
    setOnlineSourceButton(onlineSourceSaveBtnEl, "已保存", true);
    restoreOnlineSourceButton(onlineSourceSaveBtnEl, onlineSourceFormActionLabel());
    return payload;
  } catch (err) {
    setOnlineSourceStatus(`保存失败：${err.message}`, "bad");
    setOnlineSourceButton(onlineSourceSaveBtnEl, "保存失败", true);
    restoreOnlineSourceButton(onlineSourceSaveBtnEl, onlineSourceFormActionLabel());
    return null;
  }
}

function onlineSyncErrorMessage(message) {
  if (String(message || "").includes("unrelated_files_already_staged")) {
    return "已有无关文件处于 staged 状态。请先取消暂存这些文件，再同步线上信源。";
  }
  return message || "unknown error";
}

async function syncOnlineSourceConfigToServer() {
  if (!canUseLocalBackend()) {
    setOnlineSourceStatus(localBackendUnavailableMessage(), "warn");
    return null;
  }
  if (!syncOnlineSourceFormIfFilled()) return null;
  setOnlineSourceButton(onlineSourceSyncBtnEl, "同步中...", true);
  setOnlineSourceStatus("正在提交并推送线上信源配置...", "warn");
  try {
    const res = await fetch("./api/sync-online-source-config", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(onlineSourcePayload()),
    });
    const payload = await res.json().catch(() => ({}));
    if (!res.ok || payload.ok === false) throw new Error(payload.error || `HTTP ${res.status}`);
    state.onlineSourceConfig = normalizeOnlineSourceConfig(payload);
    state.onlineSourceDirty = false;
    renderOnlineSourceConfig();
    if (payload.no_changes) {
      setOnlineSourceStatus("线上配置没有变化，不需要提交。", "ok");
      setOnlineSourceButton(onlineSourceSyncBtnEl, "无变化", true);
    } else if (payload.pushed) {
      setOnlineSourceStatus(`已推送，等待 GitHub Actions 刷新（commit ${payload.commit || ""}）`, "ok");
      setOnlineSourceButton(onlineSourceSyncBtnEl, "已推送", true);
    } else {
      setOnlineSourceStatus(`已提交 ${payload.commit || ""}，但未推送。`, "warn");
      setOnlineSourceButton(onlineSourceSyncBtnEl, "已提交", true);
    }
    restoreOnlineSourceButton(onlineSourceSyncBtnEl, "同步到线上", 1800);
    return payload;
  } catch (err) {
    setOnlineSourceStatus(`推送失败：${onlineSyncErrorMessage(err.message)}`, "bad");
    setOnlineSourceButton(onlineSourceSyncBtnEl, "推送失败", true);
    restoreOnlineSourceButton(onlineSourceSyncBtnEl, "同步到线上");
    return null;
  }
}

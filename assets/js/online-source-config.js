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
  mediacrawler_jsonl: {
    label: "抖音博主",
    nameLabel: "博主名称",
    locatorLabel: "抖音主页链接",
    locatorPlaceholder: "例如：https://www.douyin.com/user/MS4wLjABAAAA...",
    channel: "抖音订阅",
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

function canWriteOnlineSourceConfig() {
  return canUseLocalBackend() && state.onlineSourceConfigLoaded === true;
}

function requireLoadedOnlineSourceConfig() {
  if (canWriteOnlineSourceConfig()) return true;
  setOnlineSourceStatus("线上配置尚未加载成功，请先重新加载，避免覆盖线上信源", "bad");
  renderOnlineSourceConfig();
  return false;
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
    button.disabled = !canWriteOnlineSourceConfig();
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
  if (!requireLoadedOnlineSourceConfig()) return false;
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
  const sources = state.onlineSourceConfig?.sources || [];
  const target = sources.find((source) => source.id === recordId);
  const label = String(target?.name || target?.target || recordId || "该信源");
  const confirmed = window.confirm(
    `确定删除「${label}」吗？\n\n该源已采集的历史内容会在下次采集时一并清除。`
  );
  if (!confirmed) return;
  state.onlineSourceConfig.sources = sources.filter((source) => source.id !== recordId);
  clearOnlineSourceForm();
  renderOnlineSourceConfig();
  markOnlineSourceDirty("未保存：已从线上信源草稿删除");
}

function toggleOnlineSourceRecord(recordId, enabled) {
  const source = (state.onlineSourceConfig?.sources || []).find((item) => item.id === recordId);
  if (!source) return;
  const nextEnabled = Boolean(enabled);
  if (!nextEnabled && source.enabled !== false) {
    const label = String(source.name || source.target || recordId || "该信源");
    const confirmed = window.confirm(
      `停用「${label}」后，该源已采集的历史内容会在下次采集时一并清除。\n\n确定停用吗？`
    );
    if (!confirmed) {
      renderOnlineSourceConfig();
      return;
    }
  }
  source.enabled = nextEnabled;
  renderOnlineSourceConfig();
  markOnlineSourceDirty("未保存：启用状态已变更");
}

function renderOnlineSourceList() {
  if (!onlineSourceListEl) return;
  onlineSourceListEl.innerHTML = "";
  const isLocal = canUseLocalBackend();
  const canEdit = canWriteOnlineSourceConfig();
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
    if (canEdit) {
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
  const canWrite = canWriteOnlineSourceConfig();
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
    if (node) node.disabled = !canWrite;
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
  } else if (!state.onlineSourceConfigLoaded) {
    setOnlineSourceStatus("线上配置尚未加载成功，请先重新加载，避免覆盖线上信源", "bad");
  }
  renderGithubStarPanel();
}

async function loadOnlineSourceConfigFromServer(silent = false) {
  if (!onlineSourceListEl) {
    renderOnlineSourceConfig();
    return null;
  }
  const isLocal = canUseLocalBackend();
  const configUrl = isLocal ? "./api/online-source-config" : "./config/online-sources.json";
  state.onlineSourceConfigLoaded = false;
  renderOnlineSourceConfig();
  try {
    const res = await fetch(configUrl, {
      headers: { Accept: "application/json" },
      cache: "no-store",
    });
    const payload = await res.json().catch(() => ({}));
    if (!res.ok || payload.ok === false) throw new Error(payload.error || `HTTP ${res.status}`);
    const configPayload = payload.config && typeof payload.config === "object"
      ? { ...payload.config, sources: Array.isArray(payload.sources) ? payload.sources : payload.config.sources }
      : payload;
    state.onlineSourceConfig = normalizeOnlineSourceConfig(configPayload);
    state.onlineSourceConfigLoaded = true;
    state.onlineSourceDirty = false;
    state.githubStarEtag = String(res.headers.get("ETag") || payload.etag || state.githubStarEtag || "");
    state.githubStarConfigDigest = String(payload.base_config_digest || state.githubStarConfigDigest || "");
    state.githubStarRecovery = payload.recovery || null;
    renderOnlineSourceConfig();
    const sourceCount = payload.source_count || state.onlineSourceConfig.sources.length;
    const prefix = isLocal ? "已读取" : "已同步线上实际追踪源";
    setOnlineSourceStatus(`${prefix} ${payload.path || "config/online-sources.json"}，共 ${fmtNumber(sourceCount)} 个线上信源`, "ok");
    return payload;
  } catch (err) {
    state.onlineSourceConfigLoaded = false;
    setOnlineSourceStatus(`线上信源读取失败：${err.message}。线上配置尚未加载成功，请先重新加载，避免覆盖线上信源`, "bad");
    renderOnlineSourceConfig();
    return null;
  }
}

async function saveOnlineSourceConfigToServer() {
  if (!canUseLocalBackend()) {
    setOnlineSourceStatus(localBackendUnavailableMessage(), "warn");
    return null;
  }
  if (!requireLoadedOnlineSourceConfig()) return null;
  if (!syncOnlineSourceFormIfFilled()) return null;
  setOnlineSourceButton(onlineSourceSaveBtnEl, "保存中...", true);
  setOnlineSourceStatus("正在写入公开线上配置...", "warn");
  try {
    const res = await fetch("./api/online-source-config", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
        ...(state.githubStarEtag ? { "If-Match": state.githubStarEtag } : {}),
      },
      body: JSON.stringify(onlineSourcePayload()),
    });
    const payload = await res.json().catch(() => ({}));
    if (!res.ok || payload.ok === false) throw new Error(payload.error || `HTTP ${res.status}`);
    state.onlineSourceConfig = normalizeOnlineSourceConfig(onlineConfigFromResponse(payload));
    state.githubStarEtag = String(res.headers.get("ETag") || payload.etag || state.githubStarEtag || "");
    state.githubStarConfigDigest = String(payload.base_config_digest || state.githubStarConfigDigest || "");
    state.onlineSourceDirty = false;
    renderOnlineSourceConfig();
    setOnlineSourceStatus(
      `已写入本地线上配置：${fmtNumber(payload.source_count || 0)} 个信源${purgedItemsNote(payload.purged_items)}`,
      "ok",
    );
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
  const code = String(message || "");
  if (code.includes("unrelated_files_already_staged")) {
    return "已有无关文件处于 staged 状态。请先取消暂存这些文件，再同步线上信源。";
  }
  if (code.includes("online_sources_preflight_failed") || code.includes("online_sources_config_stale")) {
    return "远端线上配置已变化。请先更新本地工作区并重新读取线上信源，不能强制覆盖。";
  }
  return code || "unknown error";
}

async function syncOnlineSourceConfigToServer() {
  if (!canUseLocalBackend()) {
    setOnlineSourceStatus(localBackendUnavailableMessage(), "warn");
    return null;
  }
  if (!requireLoadedOnlineSourceConfig()) return null;
  if (!syncOnlineSourceFormIfFilled()) return null;
  if (state.onlineSourceDirty) {
    setOnlineSourceStatus("当前配置尚未保存，请先点“保存配置”，再同步到线上。", "warn");
    return null;
  }
  setOnlineSourceButton(onlineSourceSyncBtnEl, "同步中...", true);
  setOnlineSourceStatus("正在提交并推送线上信源配置...", "warn");
  try {
    const res = await fetch("./api/sync-online-source-config", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
        ...(state.githubStarEtag ? { "If-Match": state.githubStarEtag } : {}),
      },
      body: JSON.stringify({}),
    });
    const payload = await res.json().catch(() => ({}));
    if (!res.ok || payload.ok === false) throw new Error(payload.error || `HTTP ${res.status}`);
    state.onlineSourceConfig = normalizeOnlineSourceConfig(onlineConfigFromResponse(payload));
    state.githubStarEtag = String(res.headers.get("ETag") || payload.etag || state.githubStarEtag || "");
    state.githubStarConfigDigest = String(payload.base_config_digest || state.githubStarConfigDigest || "");
    state.onlineSourceDirty = false;
    renderOnlineSourceConfig();
    const purgedNote = purgedItemsNote(payload.purged_items);
    if (payload.no_changes) {
      setOnlineSourceStatus(`线上配置没有变化，不需要提交。${purgedNote}`, "ok");
      setOnlineSourceButton(onlineSourceSyncBtnEl, "无变化", true);
    } else if (payload.pushed) {
      setOnlineSourceStatus(`已推送，等待 GitHub Actions 刷新（commit ${payload.commit || ""}）${purgedNote}`, "ok");
      setOnlineSourceButton(onlineSourceSyncBtnEl, "已推送", true);
    } else {
      setOnlineSourceStatus(`已提交 ${payload.commit || ""}，但未推送。${purgedNote}`, "warn");
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

// ---- 清理已退订信源的历史（预览 + 全选 + 手动删）----
// state.orphanPurgeList 缓存后端预览结果；每项形如 {site_id, site_name, source, count}。

function setOrphanPurgeStatus(message, tone = "") {
  if (!orphanPurgeStatusEl) return;
  orphanPurgeStatusEl.textContent = message || "";
  orphanPurgeStatusEl.className = `online-source-status${tone ? ` ${tone}` : ""}`;
}

function orphanPurgeKey(entry) {
  return `${entry.site_id} ${entry.source}`;
}

function renderOrphanPurgeList() {
  if (!orphanPurgeListEl) return;
  const entries = state.orphanPurgeList || [];
  const controls = orphanPurgeControlsEl;
  orphanPurgeListEl.innerHTML = "";
  if (!entries.length) {
    if (controls) controls.hidden = true;
    const empty = document.createElement("div");
    empty.className = "online-source-empty";
    empty.textContent = "没有需要清理的历史——所有历史条目都还对应着配置里的信源。";
    orphanPurgeListEl.appendChild(empty);
    return;
  }
  if (controls) controls.hidden = false;
  const checked = state.orphanPurgeChecked || new Set();
  entries.forEach((entry) => {
    const key = orphanPurgeKey(entry);
    const card = document.createElement("article");
    card.className = "online-source-card";
    const label = document.createElement("label");
    label.className = "online-source-enabled";
    const box = document.createElement("input");
    box.type = "checkbox";
    box.checked = checked.has(key);
    box.addEventListener("change", () => {
      if (box.checked) checked.add(key);
      else checked.delete(key);
      syncOrphanPurgeSelectAllState();
    });
    const text = document.createElement("span");
    text.textContent = `${entry.source}（${onlineSourceTypeLabelForSite(entry.site_id, entry.site_name)} · ${fmtNumber(entry.count)} 条）`;
    label.append(box, text);
    card.appendChild(label);
    orphanPurgeListEl.appendChild(card);
  });
  syncOrphanPurgeSelectAllState();
}

function onlineSourceTypeLabelForSite(siteId, siteName) {
  // 预览项没有 config type，只有运行时 site_id；给个可读的通道名，取不到就退回 site_name。
  if (siteId === "github_foundation_sunshine_releases") return "GitHub Release";
  if (siteId === "bilibili_dynamic") return "B站动态";
  if (siteId === "mediacrawler_douyin") return "抖音";
  if (siteId === "mediacrawler_xhs") return "小红书";
  if (String(siteId || "").startsWith("we_mp_rss") || String(siteId || "").startsWith("wewe_rss")) return "微信公众号";
  return String(siteName || siteId || "来源");
}

function syncOrphanPurgeSelectAllState() {
  if (!orphanPurgeSelectAllEl) return;
  const entries = state.orphanPurgeList || [];
  const checked = state.orphanPurgeChecked || new Set();
  const allChecked = entries.length > 0 && entries.every((entry) => checked.has(orphanPurgeKey(entry)));
  orphanPurgeSelectAllEl.checked = allChecked;
}

async function loadOrphanPurgePreview() {
  if (!orphanPurgeListEl) return;
  if (!canUseLocalBackend()) {
    setOrphanPurgeStatus("清理历史只在本机（127.0.0.1:8080）可用。", "warn");
    return;
  }
  setOnlineSourceButton(orphanPurgeReloadBtnEl, "扫描中...", true);
  setOrphanPurgeStatus("正在扫描历史条目...", "warn");
  try {
    const res = await fetch("./api/archive/orphans", {
      headers: { Accept: "application/json" },
      cache: "no-store",
    });
    const payload = await res.json().catch(() => ({}));
    if (!res.ok || payload.ok === false) throw new Error(payload.error || `HTTP ${res.status}`);
    const orphans = Array.isArray(payload.orphans) ? payload.orphans : [];
    state.orphanPurgeList = orphans;
    // 默认全选：安全在于删除前的二次确认，而非默认不选。
    state.orphanPurgeChecked = new Set(orphans.map((entry) => orphanPurgeKey(entry)));
    renderOrphanPurgeList();
    const total = orphans.reduce((sum, entry) => sum + (Number(entry.count) || 0), 0);
    if (!orphans.length) {
      setOrphanPurgeStatus("没有需要清理的历史。", "ok");
    } else {
      setOrphanPurgeStatus(`发现 ${fmtNumber(orphans.length)} 个已退订信源、共 ${fmtNumber(total)} 条历史。默认全选，删除前请核对。`, "warn");
    }
  } catch (err) {
    setOrphanPurgeStatus(`扫描失败：${err.message}`, "bad");
  } finally {
    restoreOnlineSourceButton(orphanPurgeReloadBtnEl, "扫描");
  }
}

async function deleteSelectedOrphanHistory() {
  if (!canUseLocalBackend()) {
    setOrphanPurgeStatus("清理历史只在本机（127.0.0.1:8080）可用。", "warn");
    return;
  }
  const entries = state.orphanPurgeList || [];
  const checked = state.orphanPurgeChecked || new Set();
  const selected = entries.filter((entry) => checked.has(orphanPurgeKey(entry)));
  if (!selected.length) {
    setOrphanPurgeStatus("没有勾选任何信源。", "warn");
    return;
  }
  const total = selected.reduce((sum, entry) => sum + (Number(entry.count) || 0), 0);
  const names = selected.map((entry) => `· ${entry.source}（${fmtNumber(entry.count)} 条）`).join("\n");
  const confirmed = window.confirm(
    `将永久删除以下 ${selected.length} 个已退订信源、共 ${total} 条历史：\n\n${names}\n\n删除前会自动备份 archive.json。确定删除吗？`,
  );
  if (!confirmed) return;
  const pairs = selected.map((entry) => [entry.site_id, entry.source]);
  setOnlineSourceButton(orphanPurgeDeleteBtnEl, "删除中...", true);
  setOrphanPurgeStatus("正在删除并重写数据文件...", "warn");
  try {
    const res = await fetch("./api/archive/purge-selected", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ pairs }),
    });
    const payload = await res.json().catch(() => ({}));
    if (!res.ok || payload.ok === false) throw new Error(payload.error || `HTTP ${res.status}`);
    const removed = payload.removed && typeof payload.removed === "object" ? payload.removed : {};
    const removedNote = Object.entries(removed)
      .filter(([, count]) => Number(count) > 0)
      .map(([file, count]) => `${file}: ${fmtNumber(count)}`)
      .join("，") || "无改动";
    setOrphanPurgeStatus(`已删除。${removedNote}。备份：${payload.backup || "无"}。点“读取结果”刷新页面。`, "ok");
    setOnlineSourceButton(orphanPurgeDeleteBtnEl, "已删除", true);
    restoreOnlineSourceButton(orphanPurgeDeleteBtnEl, "删除选中的历史");
    await loadOrphanPurgePreview();
  } catch (err) {
    setOrphanPurgeStatus(`删除失败：${err.message}`, "bad");
    setOnlineSourceButton(orphanPurgeDeleteBtnEl, "删除失败", true);
    restoreOnlineSourceButton(orphanPurgeDeleteBtnEl, "删除选中的历史");
  }
}

function toggleOrphanPurgeSelectAll() {
  const entries = state.orphanPurgeList || [];
  const checked = state.orphanPurgeChecked || new Set();
  const selectAll = orphanPurgeSelectAllEl ? orphanPurgeSelectAllEl.checked : true;
  if (selectAll) entries.forEach((entry) => checked.add(orphanPurgeKey(entry)));
  else checked.clear();
  state.orphanPurgeChecked = checked;
  renderOrphanPurgeList();
}

// ---- GitHub 星标安全同步 ----
function githubStarBinding() {
  const binding = state.onlineSourceConfig?.github_star_sync;
  return binding && typeof binding === "object" ? binding : null;
}

function onlineConfigFromResponse(payload = {}) {
  if (payload.config && typeof payload.config === "object") {
    return { ...payload.config, sources: Array.isArray(payload.sources) ? payload.sources : payload.config.sources };
  }
  return payload;
}

function githubStarErrorText(code) {
  const messages = {
    github_username_invalid: "GitHub 用户名格式不正确。",
    github_user_not_found: "没有找到这个 GitHub 用户名，请检查拼写。",
    github_star_limit_exceeded: "公开星标超过 50 个，本次已中止。",
    github_star_capacity_exceeded: "线上信源总数超过安全上限，本次已中止。",
    github_star_preview_stale: "配置已变化，这份预览已过期，请重新预览。",
    github_star_account_mismatch: "账号身份已变化，请重新加载配置。",
    github_upstream_rate_limited: "GitHub 当前限流，请稍后重试。",
    github_upstream_forbidden: "GitHub 拒绝了请求，请检查公开访问权限。",
    github_upstream_timeout: "GitHub 请求超时，请稍后重试。",
    online_sources_busy: "当前已有同步操作，请稍后再试。",
    online_sources_config_stale: "配置已变化，请重新加载后再操作。",
  };
  return messages[code] || code || "操作失败，请查看本地服务状态。";
}

function setGithubStarStatus(message, tone = "") {
  state.githubStarStatus = { message: String(message || ""), tone: String(tone || "") };
  renderGithubStarStatus();
}

function renderGithubStarStatus() {
  if (!githubStarStatusEl) return;
  if (state.githubStarStatus) {
    githubStarStatusEl.textContent = state.githubStarStatus.message;
    githubStarStatusEl.className = `online-source-status${state.githubStarStatus.tone ? ` ${state.githubStarStatus.tone}` : ""}`;
    return;
  }
  const binding = githubStarBinding();
  const local = canUseLocalBackend();
  githubStarStatusEl.textContent = !local
    ? "GitHub 星标同步只在本机控制台可用。"
    : binding
      ? `已绑定 ${binding.account_login || binding.account_id}`
      : "未绑定 GitHub 账号";
  githubStarStatusEl.className = `online-source-status ${local && binding ? "ok" : local ? "" : "warn"}`.trim();
}

function githubStarSetResponseState(payload, response = null) {
  if (!payload || typeof payload !== "object") return;
  if (payload.config && typeof payload.config === "object") {
    state.onlineSourceConfig = normalizeOnlineSourceConfig(onlineConfigFromResponse(payload));
    state.onlineSourceConfigLoaded = true;
  }
  state.githubStarConfigDigest = String(payload.base_config_digest || state.githubStarConfigDigest || "");
  state.githubStarEtag = String(payload.etag || response?.headers?.get("ETag") || state.githubStarEtag || "");
  if (Object.prototype.hasOwnProperty.call(payload, "recovery")) {
    state.githubStarRecovery = payload.recovery || null;
  }
}

async function githubStarRequest(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      Accept: "application/json",
      ...(options.headers || {}),
    },
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok || payload.ok === false) {
    const error = new Error(githubStarErrorText(payload.error || `HTTP ${response.status}`));
    error.code = payload.error || `HTTP ${response.status}`;
    error.payload = payload;
    error.status = response.status;
    throw error;
  }
  githubStarSetResponseState(payload, response);
  return payload;
}

function githubStarSetOutcome(outcome, payload = {}) {
  if (!githubStarOutcomeEl) return;
  const labels = {
    no_change: "无变化",
    pushed: "已推送",
    saved_not_committed: "已保存，待提交",
    committed_not_pushed: "已提交，待推送",
  };
  const label = labels[outcome] || "";
  const detail = payload.recovery_pending ? " · 本机恢复待处理" : "";
  githubStarOutcomeEl.textContent = label ? `${label}${detail}` : "";
  githubStarOutcomeEl.className = `github-star-outcome${outcome === "pushed" || outcome === "no_change" ? " ok" : outcome ? " warn" : ""}`;
}

function githubStarSummaryText(summary = {}) {
  const labels = [
    ["added", "新增"],
    ["adopted", "收编"],
    ["renamed", "改名"],
    ["re_enabled", "恢复"],
    ["disabled", "停用"],
    ["skipped_manual_disabled", "跳过"],
  ];
  const parts = [];
  labels.forEach(([key, label]) => {
    const list = Array.isArray(summary[key]) ? summary[key] : [];
    if (!list.length) return;
    const names = list.slice(0, 4).map((entry) => String(entry.full_name || entry.name || entry.repo || entry.id || "")).filter(Boolean);
    parts.push(`${label} ${fmtNumber(list.length)}${names.length ? `：${names.join("、")}` : ""}`);
  });
  return parts.length ? parts.join("；") : "没有配置变化";
}

function renderGithubStarCollectionStatus() {
  if (!githubStarCollectionStatusEl) return;
  const site = (state.sourceStatus?.sites || []).find((item) => item?.site_id === "github_foundation_sunshine_releases");
  if (!site) {
    githubStarCollectionStatusEl.hidden = true;
    return;
  }
  const children = Array.isArray(site.repos || site.children) ? (site.repos || site.children) : [];
  const failed = Number(site.failed_count || 0);
  const deferred = Number(site.deferred_count || 0);
  const skipped = Number(site.expected_skip_count || site.daily_coalesced || 0);
  const succeeded = Number(site.succeeded_count || 0);
  const tone = site.partial ? "warn" : (site.ok ? "ok" : "bad");
  githubStarCollectionStatusEl.hidden = false;
  githubStarCollectionStatusEl.className = `github-star-collection-status ${tone}`;
  const childNote = children.length ? `；已展开 ${fmtNumber(children.length)} 个仓库状态` : "";
  githubStarCollectionStatusEl.textContent = `GitHub 采集：成功 ${fmtNumber(succeeded)}，正常跳过 ${fmtNumber(skipped)}，失败 ${fmtNumber(failed)}，延后 ${fmtNumber(deferred)}${childNote}`;
}

function renderGithubStarRecovery() {
  if (!githubStarRecoveryEl) return;
  const recovery = state.githubStarRecovery;
  if (!recovery) {
    githubStarRecoveryEl.hidden = true;
    return;
  }
  const actions = new Set(Array.isArray(recovery.allowed_actions) ? recovery.allowed_actions : []);
  githubStarRecoveryEl.hidden = false;
  githubStarRecoveryTextEl.textContent = `${recovery.phase || "未知阶段"} · ${recovery.outcome || "待核对"} · 可恢复`;
  githubStarRetryBtnEl.hidden = !actions.has("retry_push");
  githubStarRollbackBtnEl.hidden = !actions.has("rollback");
}

function renderGithubStarPanel() {
  if (!githubStarSyncPanelEl) return;
  const binding = githubStarBinding();
  const local = canUseLocalBackend();
  renderGithubStarStatus();
  githubStarBindingFormEl.hidden = !local;
  if (githubStarUsernameEl) {
    githubStarUsernameEl.readOnly = Boolean(binding);
    if (binding) githubStarUsernameEl.value = String(binding.account_login || "");
  }
  githubStarBoundAccountEl.hidden = !binding;
  githubStarBoundAccountEl.textContent = binding ? `当前账号：${binding.account_login || binding.account_id}（数字 ID ${binding.account_id}）` : "";
  githubStarUnbindBtnEl.hidden = !binding || !local;
  githubStarPreviewEl.hidden = !state.githubStarPreview;
  if (state.githubStarPreview) {
    const preview = state.githubStarPreview;
    githubStarPreviewSummaryEl.textContent = `${preview.account?.login || "账号"}：公开星标 ${fmtNumber(preview.starred_count || 0)} 个${preview.private_skipped_count ? `，另有 ${fmtNumber(preview.private_skipped_count)} 个非公开仓库已跳过` : ""}。${githubStarSummaryText(preview.summary)}`;
    githubStarApplyBtnEl.disabled = Boolean(preview.requires_confirmation) && !githubStarConfirmEl?.checked;
  }
  renderGithubStarRecovery();
  renderGithubStarCollectionStatus();
}

async function previewGithubStarSync() {
  const binding = githubStarBinding();
  const username = String(githubStarUsernameEl?.value || "").trim();
  if (!binding && !username) {
    setGithubStarStatus("请填写 GitHub 用户名。", "bad");
    return;
  }
  state.githubStarPreview = null;
  if (githubStarConfirmEl) githubStarConfirmEl.checked = false;
  if (githubStarApplyBtnEl) githubStarApplyBtnEl.disabled = true;
  githubStarPreviewBtnEl.disabled = true;
  setGithubStarStatus("正在读取公开星标...", "warn");
  try {
    const payload = await githubStarRequest("./api/github-stars/preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(binding ? {} : { username }),
    });
    state.githubStarPreview = payload;
    state.githubStarConfigDigest = String(payload.base_config_digest || state.githubStarConfigDigest || "");
    setGithubStarStatus("预览已生成，请确认后同步。", "warn");
    renderGithubStarPanel();
  } catch (err) {
    state.githubStarPreview = null;
    setGithubStarStatus(err.message, "bad");
    renderGithubStarPanel();
  } finally {
    githubStarPreviewBtnEl.disabled = false;
  }
}

async function applyGithubStarSync() {
  const preview = state.githubStarPreview;
  if (!preview || (preview.requires_confirmation && !githubStarConfirmEl?.checked)) {
    setGithubStarStatus("请先勾选确认，再同步。", "warn");
    return;
  }
  githubStarApplyBtnEl.disabled = true;
  setGithubStarStatus("正在安全写入并核对 Git...", "warn");
  try {
    const payload = await githubStarRequest("./api/github-stars/apply", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ account_id: Number(preview.account?.id), preview_hash: preview.preview_hash }),
    });
    state.githubStarPreview = null;
    githubStarSetOutcome(payload.outcome, payload);
    setGithubStarStatus(payload.partial ? "同步未完全结束，请按恢复提示处理。" : "同步完成。", payload.partial ? "warn" : "ok");
    renderGithubStarPanel();
  } catch (err) {
    githubStarSetOutcome("", {});
    setGithubStarStatus(err.message, err.code === "github_star_preview_stale" ? "warn" : "bad");
    if (err.code === "github_star_preview_stale") state.githubStarPreview = null;
    renderGithubStarPanel();
  } finally {
    githubStarApplyBtnEl.disabled = !state.githubStarPreview || (state.githubStarPreview.requires_confirmation && !githubStarConfirmEl?.checked);
  }
}

async function recoverGithubStarOperation(action) {
  const recovery = state.githubStarRecovery;
  if (!recovery?.operation_id || !recovery?.manifest_digest) return;
  if (action === "rollback" && !window.confirm("确认撤销这次未完成的 GitHub 星标同步吗？")) return;
  const button = action === "retry_push" ? githubStarRetryBtnEl : githubStarRollbackBtnEl;
  button.disabled = true;
  try {
    const payload = await githubStarRequest("./api/online-source-config/recovery", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action, operation_id: recovery.operation_id, manifest_digest: recovery.manifest_digest, confirmed: action === "rollback" }),
    });
    state.githubStarRecovery = payload.recovery || null;
    githubStarSetOutcome(payload.outcome, payload);
    setGithubStarStatus(payload.recovery_pending ? "恢复仍待处理。" : "恢复完成。", payload.recovery_pending ? "warn" : "ok");
    renderGithubStarPanel();
  } catch (err) {
    setGithubStarStatus(err.message, "bad");
  } finally {
    button.disabled = false;
  }
}

async function unbindGithubStarSync() {
  const binding = githubStarBinding();
  if (!binding || !window.confirm(`确认解绑 GitHub 账号 ${binding.account_login || binding.account_id} 吗？`)) return;
  githubStarUnbindBtnEl.disabled = true;
  try {
    const payload = await githubStarRequest("./api/github-stars/unbind", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...(state.githubStarEtag ? { "If-Match": state.githubStarEtag } : {}) },
      body: JSON.stringify({ account_id: Number(binding.account_id), confirmed: true }),
    });
    state.githubStarPreview = null;
    githubStarSetOutcome(payload.outcome, payload);
    setGithubStarStatus("已解绑，托管源已保留为普通配置。", "ok");
    renderOnlineSourceConfig();
    renderGithubStarPanel();
  } catch (err) {
    setGithubStarStatus(err.message, "bad");
  } finally {
    githubStarUnbindBtnEl.disabled = false;
  }
}

if (githubStarBindingFormEl) githubStarBindingFormEl.addEventListener("submit", (event) => { event.preventDefault(); previewGithubStarSync().catch(() => {}); });
if (githubStarConfirmEl) githubStarConfirmEl.addEventListener("change", () => { githubStarApplyBtnEl.disabled = !state.githubStarPreview || (state.githubStarPreview.requires_confirmation && !githubStarConfirmEl.checked); });
if (githubStarApplyBtnEl) githubStarApplyBtnEl.addEventListener("click", () => { applyGithubStarSync().catch(() => {}); });
if (githubStarPreviewCancelBtnEl) githubStarPreviewCancelBtnEl.addEventListener("click", () => { state.githubStarPreview = null; renderGithubStarPanel(); });
if (githubStarRetryBtnEl) githubStarRetryBtnEl.addEventListener("click", () => { recoverGithubStarOperation("retry_push").catch(() => {}); });
if (githubStarRollbackBtnEl) githubStarRollbackBtnEl.addEventListener("click", () => { recoverGithubStarOperation("rollback").catch(() => {}); });
if (githubStarUnbindBtnEl) githubStarUnbindBtnEl.addEventListener("click", () => { unbindGithubStarSync().catch(() => {}); });

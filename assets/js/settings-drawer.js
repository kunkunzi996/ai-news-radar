const settingsDrawerEl = document.getElementById("settingsDrawer");
const settingsOpenBtnEl = document.getElementById("settingsOpenBtn");
const settingsCloseBtnEl = document.getElementById("settingsCloseBtn");
const settingsTabLocalEl = document.getElementById("settingsTabLocal");
const remoteAdminFormEl = document.getElementById("remoteAdminForm");
const remoteAdminBaseInputEl = document.getElementById("remoteAdminBaseInput");
const remoteAdminTokenInputEl = document.getElementById("remoteAdminTokenInput");
const remoteAdminConnectBtnEl = document.getElementById("remoteAdminConnectBtn");
const remoteAdminDisconnectBtnEl = document.getElementById("remoteAdminDisconnectBtn");
const remoteAdminStatusEl = document.getElementById("remoteAdminStatus");

function setRemoteAdminStatus(message, tone = "") {
  if (!remoteAdminStatusEl) return;
  remoteAdminStatusEl.textContent = message || "";
  remoteAdminStatusEl.className = tone || "";
}

function pruneStatusLabel(status) {
  if (status === "completed") return "已按保留期裁过";
  if (status === "failed") return "裁剪失败，列表应仍是裁前";
  if (status === "skipped_grace") return "宽限中，尚未按 14 天裁";
  return "尚未裁";
}

function renderRetentionCheckLine() {
  const lineEl = document.getElementById("retentionCheckLine");
  if (!lineEl) return;
  const retention = state.retention && typeof state.retention === "object" ? state.retention : null;
  const generated = state.generatedAt ? fmtTime(state.generatedAt) : "未知";
  if (!retention) {
    lineEl.textContent = `保留规则：这份数据还没有保留字段（更新 ${generated}）`;
    return;
  }
  const phase = isRetentionGraceActive() ? "宽限中" : "宽限已结束";
  const cut = pruneStatusLabel(retention.last_prune_status);
  const when = retention.grace_ends_at || retention.effective_at || "";
  const whenBit = when ? ` · ${when}` : "";
  lineEl.textContent = `保留规则已生效 · ${phase} · ${cut} · 本页数据 ${generated}${whenBit}`;
}

function syncRemoteAdminForm() {
  if (isReaderOnlyMode()) return;
  if (!remoteAdminFormEl) return;
  const base = getAdminApiBase();
  const token = getAdminToken();
  if (remoteAdminBaseInputEl && document.activeElement !== remoteAdminBaseInputEl) {
    remoteAdminBaseInputEl.value = base;
  }
  if (remoteAdminTokenInputEl && document.activeElement !== remoteAdminTokenInputEl) {
    remoteAdminTokenInputEl.value = token;
  }
  if (base && token) {
    setRemoteAdminStatus(`已连接：${base}（令牌已保存在本浏览器）`, "ok");
  } else {
    setRemoteAdminStatus("未配置远程后台；当前为纯阅读模式。", "");
  }
}

async function connectRemoteAdmin(event) {
  if (event) event.preventDefault();
  if (isReaderOnlyMode()) return;
  if (!remoteAdminBaseInputEl || !remoteAdminTokenInputEl) return;
  const base = normalizeAdminApiBase(remoteAdminBaseInputEl.value);
  const token = String(remoteAdminTokenInputEl.value || "").trim();
  if (!base) {
    setRemoteAdminStatus("API 地址无效，需形如 https://radar.example.com", "bad");
    return;
  }
  if (!token) {
    setRemoteAdminStatus("请输入管理令牌。", "bad");
    return;
  }
  if (remoteAdminConnectBtnEl) remoteAdminConnectBtnEl.disabled = true;
  setRemoteAdminStatus("正在测试连接...", "warn");
  try {
    const res = await fetch(`${base}/api/local-status`, {
      headers: { Accept: "application/json", "X-Admin-Token": token },
      cache: "no-store",
      redirect: "manual",
    });
    const payload = await res.json().catch(() => ({}));
    if (res.status === 401) {
      setRemoteAdminStatus("后台要求管理令牌：请确认地址指向管理后台。", "bad");
      return;
    }
    if (res.status === 403) {
      setRemoteAdminStatus("令牌不正确，未保存。", "bad");
      return;
    }
    if (res.status === 429) {
      setRemoteAdminStatus("失败次数过多，后台已临时锁定，请稍后再试。", "bad");
      return;
    }
    if (!res.ok || payload.ok === false) {
      throw new Error(payload.error || `HTTP ${res.status}`);
    }
    setAdminConnection(base, token);
    if (window.WorkbenchBridge && window.WorkbenchBridge.saveConfigToWorkbench) {
      window.WorkbenchBridge.saveConfigToWorkbench({ adminApiBase: base, adminToken: token });
    }
    setRemoteAdminStatus("连接成功，正在刷新页面启用管理面板...", "ok");
    window.setTimeout(() => window.location.reload(), 600);
  } catch (err) {
    setRemoteAdminStatus(`连接失败：${err && err.message ? err.message : err}`, "bad");
  } finally {
    if (remoteAdminConnectBtnEl) remoteAdminConnectBtnEl.disabled = false;
  }
}

function disconnectRemoteAdmin() {
  if (isReaderOnlyMode()) return;
  clearAdminConnection();
  if (window.WorkbenchBridge && window.WorkbenchBridge.saveConfigToWorkbench) {
    window.WorkbenchBridge.saveConfigToWorkbench({ adminApiBase: "", adminToken: "" });
  }
  if (remoteAdminBaseInputEl) remoteAdminBaseInputEl.value = "";
  if (remoteAdminTokenInputEl) remoteAdminTokenInputEl.value = "";
  setRemoteAdminStatus("已断开，正在刷新页面回到纯阅读模式...", "warn");
  window.setTimeout(() => window.location.reload(), 400);
}

function settingsTabButtons() {
  if (!settingsDrawerEl) return [];
  return Array.from(settingsDrawerEl.querySelectorAll("[data-settings-tab]"));
}

function setActiveSettingsTab(tabId) {
  if (!settingsDrawerEl) return;
  settingsTabButtons().forEach((btn) => {
    const active = btn.dataset.settingsTab === tabId;
    btn.classList.toggle("active", active);
    btn.setAttribute("aria-selected", active ? "true" : "false");
  });
  settingsDrawerEl.querySelectorAll("[data-settings-pane]").forEach((pane) => {
    pane.hidden = pane.dataset.settingsPane !== tabId;
  });
}

// 公网静态页没有本地后台，「本机采集」整块无意义，直接隐藏该 tab。
function syncSettingsTabAvailability() {
  if (!settingsTabLocalEl) return;
  settingsTabLocalEl.hidden = !canUseLocalBackend();
}

const FOCUSABLE_SELECTOR = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  "summary",
  "[tabindex]:not([tabindex='-1'])",
].join(",");

// 抽屉声明了 aria-modal，背景必须真正不可达：inert 让背景对鼠标、Tab
// 和读屏软件同时失效。下面的 Tab 循环是 inert 不被支持时的兜底。
function setBackgroundInert(inert) {
  if (!settingsDrawerEl || !settingsDrawerEl.parentElement) return;
  Array.from(settingsDrawerEl.parentElement.children).forEach((node) => {
    if (node === settingsDrawerEl) return;
    if (inert) node.setAttribute("inert", "");
    else node.removeAttribute("inert");
  });
}

// 折叠 <details> 里的内容按不到，但 offsetParent 和 getClientRects 都可能显示它
// “可见”。若把它们算进来，last 会落在一个实际按不到的按钮上，Tab 就从真正的
// 末尾漏到 body。故显式排除未展开 details 的内容（summary 本身除外）。
function isFocusableInDrawer(node) {
  if (node === document.activeElement) return true;
  if (node.getClientRects().length === 0) return false;
  // 逐层上溯：只要任一祖先 details 未展开，且 node 不是那一层的 summary，就按不到。
  // 只查最近一层不够——「高级信源配置」的 summary 会藏在外层折叠的「本机私有配置」里。
  let child = node;
  let parent = node.parentElement;
  while (parent && settingsDrawerEl.contains(parent)) {
    if (parent.tagName === "DETAILS" && !parent.open && child.tagName !== "SUMMARY") return false;
    child = parent;
    parent = parent.parentElement;
  }
  return true;
}

function visibleFocusablesInDrawer() {
  if (!settingsDrawerEl) return [];
  return Array.from(settingsDrawerEl.querySelectorAll(FOCUSABLE_SELECTOR)).filter(isFocusableInDrawer);
}

function trapSettingsTab(event) {
  const focusables = visibleFocusablesInDrawer();
  if (!focusables.length) return;
  const first = focusables[0];
  const last = focusables[focusables.length - 1];
  const active = document.activeElement;

  if (!settingsDrawerEl.contains(active)) {
    event.preventDefault();
    first.focus();
    return;
  }
  if (event.shiftKey && active === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && active === last) {
    event.preventDefault();
    first.focus();
  }
}

let settingsLastFocusedEl = null;

function openSettingsDrawer() {
  if (isReaderOnlyMode()) return;
  if (!settingsDrawerEl) return;
  settingsLastFocusedEl = document.activeElement;
  syncSettingsTabAvailability();
  syncRemoteAdminForm();
  renderRetentionCheckLine();
  settingsDrawerEl.hidden = false;
  document.body.classList.add("settings-drawer-open");
  setBackgroundInert(true);
  if (settingsCloseBtnEl) settingsCloseBtnEl.focus();
}

function closeSettingsDrawer() {
  if (!settingsDrawerEl) return;
  setBackgroundInert(false);
  settingsDrawerEl.hidden = true;
  document.body.classList.remove("settings-drawer-open");
  const restoreTarget = settingsLastFocusedEl && document.contains(settingsLastFocusedEl)
    ? settingsLastFocusedEl
    : settingsOpenBtnEl;
  if (restoreTarget) restoreTarget.focus();
  settingsLastFocusedEl = null;
}

if (settingsOpenBtnEl) settingsOpenBtnEl.addEventListener("click", openSettingsDrawer);
if (settingsCloseBtnEl) settingsCloseBtnEl.addEventListener("click", closeSettingsDrawer);
if (remoteAdminFormEl) remoteAdminFormEl.addEventListener("submit", connectRemoteAdmin);
if (remoteAdminDisconnectBtnEl) remoteAdminDisconnectBtnEl.addEventListener("click", disconnectRemoteAdmin);

if (settingsDrawerEl) {
  // 点遮罩（抽屉容器本身，而非内部面板）关闭
  settingsDrawerEl.addEventListener("click", (event) => {
    if (event.target === settingsDrawerEl) closeSettingsDrawer();
  });
  settingsTabButtons().forEach((btn) => {
    btn.addEventListener("click", () => setActiveSettingsTab(btn.dataset.settingsTab));
  });
  syncSettingsTabAvailability();
  setActiveSettingsTab("sources");
}

document.addEventListener("keydown", (event) => {
  if (!settingsDrawerEl || settingsDrawerEl.hidden) return;
  if (event.key === "Escape") {
    closeSettingsDrawer();
    return;
  }
  if (event.key === "Tab") trapSettingsTab(event);
});

const settingsDrawerEl = document.getElementById("settingsDrawer");
const settingsOpenBtnEl = document.getElementById("settingsOpenBtn");
const settingsCloseBtnEl = document.getElementById("settingsCloseBtn");
const settingsTabLocalEl = document.getElementById("settingsTabLocal");

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
  if (!settingsDrawerEl) return;
  settingsLastFocusedEl = document.activeElement;
  syncSettingsTabAvailability();
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

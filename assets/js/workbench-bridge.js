// ============================================
// 工作台收藏桥：仅当本页被昆昆子工作台以 iframe 嵌入并完成握手后生效。
// 协议（postMessage）：
//   工作台 → 雷达：{ type: "workbench-hello", radarConfig?: { adminApiBase, adminToken } }
//   雷达 → 工作台：{ type: "radar-ready" }
//   雷达 → 工作台：{ type: "radar-collect", requestId, payload: { title, url, summary, source, publishedAt } }
//   工作台 → 雷达：{ type: "radar-collect-result", requestId, ok, alreadyExists?, error? }
//   雷达 → 工作台：{ type: "radar-save-config", config: { adminApiBase, adminToken } }
// 独立打开（非 iframe / 父页面不在白名单）时本文件不做任何事，页面行为与原来完全一致。
// 注意：NUC 私有部署上线后，若工作台地址变化，需同步扩充 PARENT_ORIGINS。
// ============================================
(function () {
  const PARENT_ORIGINS = new Set([
    "http://127.0.0.1:8765",
    "http://localhost:8765",
    "https://app.wanyouomnia.cn",
  ]);
  const REQUEST_TIMEOUT_MS = 10000;

  let parentWin = null;
  let parentOrigin = "";
  let requestSeq = 0;
  const pending = new Map(); // requestId -> { resolve, reject, timer }
  const collectedUrls = new Set(); // 本次会话内已收藏的链接，防重复点击

  function connected() {
    return !!parentWin;
  }

  function collect(payload) {
    if (!parentWin) return Promise.reject(new Error("未连接工作台"));
    const requestId = `req-${Date.now()}-${++requestSeq}`;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        pending.delete(requestId);
        reject(new Error("工作台响应超时"));
      }, REQUEST_TIMEOUT_MS);
      pending.set(requestId, { resolve, reject, timer });
      parentWin.postMessage({ type: "radar-collect", requestId, payload }, parentOrigin);
    });
  }

  // 工作台配置不能依赖 iframe 的第三方 localStorage；通过 URL 重载让 utils.js
  // 在页面启动阶段读到配置，避免首轮线上信源请求走到 404 的静态兜底路径。
  function applyBridgedConfig(radarConfig) {
    if (!radarConfig || typeof radarConfig !== "object") return false;
    const base = typeof radarConfig.adminApiBase === "string" ? radarConfig.adminApiBase.trim() : "";
    const token = typeof radarConfig.adminToken === "string" ? radarConfig.adminToken.trim() : "";
    if (!base || !token) return false;
    const normalizedBase = typeof normalizeAdminApiBase === "function"
      ? normalizeAdminApiBase(base)
      : base;
    const currentBase = typeof getAdminApiBase === "function" ? getAdminApiBase() : "";
    const currentToken = typeof getAdminToken === "function" ? getAdminToken() : "";
    if (normalizedBase && currentBase === normalizedBase && currentToken === token) {
      return false;
    }
    try {
      const url = new URL(window.location.href);
      url.searchParams.set("adminBase", base);
      url.searchParams.set("adminToken", token);
      window.location.replace(url.toString());
      return true;
    } catch {
      return false;
    }
  }

  function saveConfigToWorkbench(config) {
    if (!parentWin || !parentOrigin) return;
    try {
      parentWin.postMessage({ type: "radar-save-config", config }, parentOrigin);
    } catch {}
  }

  window.addEventListener("message", (event) => {
    const data = event.data;
    if (!data || typeof data !== "object") return;
    if (data.type === "workbench-hello") {
      // 三重校验：来源域名在白名单、本页确实被嵌入、消息确实来自父窗口
      if (!PARENT_ORIGINS.has(event.origin)) return;
      if (window === window.parent || event.source !== window.parent) return;
      parentWin = event.source;
      parentOrigin = event.origin;
      if (data.radarConfig && applyBridgedConfig(data.radarConfig)) {
        return;
      }
      parentWin.postMessage({ type: "radar-ready" }, parentOrigin);
      try {
        if (typeof rerenderCurrentView === "function") rerenderCurrentView();
      } catch {
        // 数据尚未加载完成时接到握手，等 boot 正常渲染即可
      }
      return;
    }
    if (data.type === "radar-collect-result") {
      // 回执必须同时来自已握手的父窗口和已锁定的父页面 origin。
      // 只校验 origin 不够：同一白名单 origin 下的其它窗口也可能发消息。
      if (!parentWin || !parentOrigin) return;
      if (event.source !== parentWin || event.origin !== parentOrigin) return;
      if (typeof data.requestId !== "string") return;
      const entry = pending.get(data.requestId);
      if (!entry) return;
      pending.delete(data.requestId);
      clearTimeout(entry.timer);
      if (data.ok) entry.resolve(data);
      else entry.reject(new Error(data.error || "收藏失败"));
    }
  });

  window.WorkbenchBridge = {
    connected,
    collect,
    saveConfigToWorkbench,
    markCollected(url) {
      if (url) collectedUrls.add(url);
    },
    isCollected(url) {
      return collectedUrls.has(url);
    },
  };
})();

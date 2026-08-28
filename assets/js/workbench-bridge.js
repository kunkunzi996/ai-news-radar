// ============================================
// 工作台桥：同时支持白名单 iframe 与鸿蒙 OmniaRadarHost 原生代理。
// 所有双向消息统一使用协议 v1 envelope：{ version, type, requestId, ... }。
// 内容页只接收状态、操作结果与脱敏信源配置；管理地址和 Token 永不进入本页。
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
  const BRIDGE_VERSION = 1;
  const MAX_BRIDGE_MESSAGE_LENGTH = 65536;
  const MAX_REQUEST_ID_LENGTH = 120;
  const NATIVE_HANDSHAKE_INTERVAL_MS = 250;
  const NATIVE_HANDSHAKE_WINDOW_MS = 3000;
  const IFRAME_HANDSHAKE_INTERVAL_MS = 250;
  const IFRAME_HANDSHAKE_WINDOW_MS = 3000;
  const PAGE_MESSAGE_TYPES = new Set([
    "radar-ready",
    "radar-read",
    "radar-read-expire",
    "radar-read-status",
    "radar-read-migration",
    "radar-view-patch",
    "radar-collect",
    "radar-open-external",
    "radar-source-config-read",
    "radar-exploration-seen",
    "radar-exploration-ask",
    "radar-archive-status",
  ]);
  const HOST_MESSAGE_TYPES = new Set([
    "workbench-hello",
    "radar-collect-result",
    "radar-state-result",
    "radar-read-status-result",
    "radar-read-migration-result",
    "radar-source-config-result",
    "radar-exploration-state",
    "radar-exploration-ask-result",
  ]);
  const EXPECTED_RESULT_TYPES = new Map([
    ["radar-collect", "radar-collect-result"],
    ["radar-source-config-read", "radar-source-config-result"],
    ["radar-read", "radar-state-result"],
    ["radar-read-expire", "radar-state-result"],
    ["radar-view-patch", "radar-state-result"],
    ["radar-read-status", "radar-read-status-result"],
    ["radar-read-migration", "radar-read-migration-result"],
    ["radar-exploration-ask", "radar-exploration-ask-result"],
  ]);
  const SYNC_WRITE_TYPES = new Set(["radar-collect", "radar-read", "radar-read-expire", "radar-view-patch"]);
  const HOST_MESSAGE_FIELDS = new Map([
    ["workbench-hello", new Set(["version", "type", "requestId", "state", "syncAvailable", "readOnly"])],
    ["radar-collect-result", new Set(["version", "type", "requestId", "ok", "alreadyExists", "error", "declined"])],
    ["radar-state-result", new Set([
      "version", "type", "requestId", "ok", "state", "syncAvailable", "readOnly",
      "status", "statusCode", "code", "error",
    ])],
    ["radar-read-status-result", new Set([
      "version", "type", "requestId", "ok", "readKeys", "status", "code", "error",
    ])],
    ["radar-read-migration-result", new Set([
      "version", "type", "requestId", "ok", "state", "legacyReadMigration", "status", "code", "error",
    ])],
    ["radar-source-config-result", new Set(["version", "type", "requestId", "ok", "config", "error"])],
    ["radar-exploration-state", new Set(["version", "type", "requestId", "items", "date", "generated"])],
    ["radar-exploration-ask-result", new Set(["version", "type", "requestId", "ok", "error", "text"])],
  ]);

  let parentWin = null;
  let parentOrigin = "";
  let transport = "";
  let nativeProxy = null;
  let nativeHandshakeTimer = null;
  let nativeHandshakeDeadline = 0;
  let nativeHandshakeRequestId = "";
  let iframeHandshakeTimer = null;
  let iframeHandshakeDeadline = 0;
  let iframeHandshakeRequestId = "";
  let requestSeq = 0;
  const pending = new Map(); // requestId -> { expectedResultType, resolve, reject, timer }
  const collectedUrls = new Set(); // 本次会话内已收藏的链接，防重复点击
  const queuedHostMessages = [];
  const queuedNativeExternalMessages = [];
  const extraHostListeners = [];
  let hostMessageHandler = null;
  let writeFailureHandler = null;
  let lastExternalOpenFailure = null;
  const searchParams = new URLSearchParams(window.location.search);
  const appRequested = searchParams.get("omniaApp") === "1";
  const readerOnlyRequested = searchParams.get("readerOnly") === "1";
  if (isReaderOnlyMode()) document.body.classList.add("radar-reader-only-mode");
  if (appRequested) document.body.classList.add("omnia-app-mode");

  function resolveNativeProxy() {
    if (!appRequested || transport === "iframe") return null;
    const candidate = window.OmniaRadarHost;
    nativeProxy = candidate && typeof candidate.postMessage === "function" ? candidate : null;
    return nativeProxy;
  }

  function stopNativeHandshake() {
    if (nativeHandshakeTimer !== null) clearInterval(nativeHandshakeTimer);
    nativeHandshakeTimer = null;
    nativeHandshakeDeadline = 0;
    nativeHandshakeRequestId = "";
  }

  function stopIframeHandshake() {
    if (iframeHandshakeTimer !== null) clearInterval(iframeHandshakeTimer);
    iframeHandshakeTimer = null;
    iframeHandshakeDeadline = 0;
    iframeHandshakeRequestId = "";
  }

  function connected() {
    return transport === "iframe" ? !!parentWin : transport === "native";
  }

  function nextRequestId() {
    return `req-${Date.now()}-${++requestSeq}`;
  }

  function validRequestId(value) {
    return typeof value === "string" && value.length >= 1 && value.length <= MAX_REQUEST_ID_LENGTH;
  }

  function isPlainObject(value) {
    if (!value || typeof value !== "object" || Array.isArray(value)) return false;
    const prototype = Object.getPrototypeOf(value);
    return prototype === Object.prototype || prototype === null;
  }

  function createPageEnvelope(type, requestId, payload) {
    if (!PAGE_MESSAGE_TYPES.has(type) || !validRequestId(requestId)) return null;
    const message = payload === undefined
      ? { version: BRIDGE_VERSION, type, requestId }
      : { version: BRIDGE_VERSION, type, requestId, payload };
    try {
      return JSON.stringify(message).length <= MAX_BRIDGE_MESSAGE_LENGTH ? message : null;
    } catch {
      return null;
    }
  }

  function parseHostEnvelope(value) {
    if (!isPlainObject(value)) return null;
    let serialized = "";
    try { serialized = JSON.stringify(value); } catch { return null; }
    if (!serialized || serialized.length > MAX_BRIDGE_MESSAGE_LENGTH) return null;
    if (value.version !== BRIDGE_VERSION || !HOST_MESSAGE_TYPES.has(value.type)) return null;
    if (!validRequestId(value.requestId)) return null;
    const allowedFields = HOST_MESSAGE_FIELDS.get(value.type);
    if (!allowedFields) return null;
    if (Object.keys(value).some((key) => !allowedFields.has(key))) return null;
    if (value.type === "workbench-hello") {
      if (typeof value.syncAvailable !== "boolean" || typeof value.readOnly !== "boolean") return null;
      if (value.state !== undefined && value.state !== null && !isPlainObject(value.state)) return null;
      return value;
    }
    if (value.type === "radar-exploration-state") {
      return Array.isArray(value.items)
        && typeof value.date === "string"
        && typeof value.generated === "boolean"
        ? value
        : null;
    }
    if (typeof value.ok !== "boolean") return null;
    if (value.state !== undefined && value.state !== null && !isPlainObject(value.state)) return null;
    if (value.config !== undefined && !isPlainObject(value.config)) return null;
    if (value.readKeys !== undefined
      && (!Array.isArray(value.readKeys) || value.readKeys.some((key) => typeof key !== "string"))) return null;
    if (value.legacyReadMigration !== undefined && !isPlainObject(value.legacyReadMigration)) return null;
    if (value.syncAvailable !== undefined && typeof value.syncAvailable !== "boolean") return null;
    if (value.readOnly !== undefined && typeof value.readOnly !== "boolean") return null;
    if (value.alreadyExists !== undefined && typeof value.alreadyExists !== "boolean") return null;
    if (value.declined !== undefined && typeof value.declined !== "boolean") return null;
    if (value.type === "radar-collect-result" && value.ok && value.declined === true) return null;
    if (value.status !== undefined && typeof value.status !== "number") return null;
    if (value.statusCode !== undefined && typeof value.statusCode !== "number") return null;
    if (value.code !== undefined && typeof value.code !== "string") return null;
    if (value.error !== undefined && typeof value.error !== "string") return null;
    if (value.text !== undefined && typeof value.text !== "string") return null;
    return value;
  }

  function sendRaw(message, allowNativeCandidate = false) {
    if (transport === "iframe" && parentWin && parentOrigin) {
      parentWin.postMessage(message, parentOrigin);
      return true;
    }
    if (transport === "native" || allowNativeCandidate) {
      const proxy = resolveNativeProxy();
      if (!proxy) return false;
      try {
        proxy.postMessage(JSON.stringify(message));
        return true;
      } catch {
        nativeProxy = null;
      }
    }
    return false;
  }

  function flushQueuedNativeExternalMessages() {
    if (transport !== "native") return false;
    while (queuedNativeExternalMessages.length) {
      if (!sendRaw(queuedNativeExternalMessages[0])) return false;
      queuedNativeExternalMessages.shift();
    }
    lastExternalOpenFailure = null;
    return true;
  }

  function failQueuedNativeExternalMessages(error) {
    const failed = queuedNativeExternalMessages.splice(0);
    if (!failed.length) return;
    const url = failed[0] && failed[0].payload && typeof failed[0].payload.url === "string"
      ? failed[0].payload.url
      : "";
    lastExternalOpenFailure = { url, error: String(error || "原生宿主不可用") };
  }

  function iframeParentOrigins() {
    const origins = [];
    const add = (value) => {
      if (PARENT_ORIGINS.has(value) && !origins.includes(value)) origins.push(value);
    };
    try {
      if (document.referrer) add(new URL(document.referrer).origin);
    } catch {}
    try {
      const ancestors = window.location.ancestorOrigins;
      if (ancestors) {
        for (let i = 0; i < ancestors.length; i += 1) add(ancestors[i]);
      }
    } catch {}
    if (origins.length || window === window.parent) return origins;
    // 工作台 HTML 使用 Referrer-Policy: no-referrer 时，iframe 读不到 referrer。
    // 只向白名单 origin 发送；真正的父页才会收到。
    return Array.from(PARENT_ORIGINS);
  }

  function attemptIframeHandshake() {
    if (transport || Date.now() >= iframeHandshakeDeadline) {
      stopIframeHandshake();
      return;
    }
    if (window === window.parent) return;
    parentWin = window.parent;
    const message = createPageEnvelope("radar-ready", iframeHandshakeRequestId);
    if (!message) return;
    const origins = iframeParentOrigins();
    if (!origins.length) return;
    origins.forEach((origin) => {
      parentWin.postMessage(message, origin);
    });
  }

  function startIframeHandshake() {
    if (window === window.parent || iframeHandshakeTimer !== null) return;
    iframeHandshakeRequestId = nextRequestId();
    iframeHandshakeDeadline = Date.now() + IFRAME_HANDSHAKE_WINDOW_MS;
    attemptIframeHandshake();
    if (!transport && iframeHandshakeDeadline) {
      iframeHandshakeTimer = setInterval(attemptIframeHandshake, IFRAME_HANDSHAKE_INTERVAL_MS);
    }
  }

  function attemptNativeHandshake() {
    if (!appRequested || transport || Date.now() >= nativeHandshakeDeadline) {
      if (appRequested && !transport && nativeHandshakeDeadline && Date.now() >= nativeHandshakeDeadline) {
        failQueuedNativeExternalMessages("原生宿主不可用");
      }
      stopNativeHandshake();
      return;
    }
    const message = createPageEnvelope("radar-ready", nativeHandshakeRequestId);
    if (message) sendRaw(message, true);
  }

  function startNativeHandshake() {
    if (!appRequested || nativeHandshakeTimer !== null) return;
    nativeHandshakeRequestId = nextRequestId();
    nativeHandshakeDeadline = Date.now() + NATIVE_HANDSHAKE_WINDOW_MS;
    attemptNativeHandshake();
    if (!transport && nativeHandshakeDeadline) {
      nativeHandshakeTimer = setInterval(attemptNativeHandshake, NATIVE_HANDSHAKE_INTERVAL_MS);
    }
  }

  function notify(type, payload = {}) {
    const requestId = nextRequestId();
    const message = createPageEnvelope(type, requestId, payload);
    if (!message) return "";
    return sendRaw(message) ? requestId : "";
  }

  function request(type, payload) {
    if (!connected()) {
      const error = new Error("未连接工作台");
      reportWriteFailure(type, error);
      return Promise.reject(error);
    }
    const expectedResultType = EXPECTED_RESULT_TYPES.get(type);
    if (!expectedResultType) return Promise.reject(new Error("不支持的工作台请求"));
    const requestId = nextRequestId();
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        pending.delete(requestId);
        const error = new Error("工作台响应超时");
        reportWriteFailure(type, error);
        reject(error);
      }, REQUEST_TIMEOUT_MS);
      pending.set(requestId, { requestType: type, expectedResultType, resolve, reject, timer });
      const message = createPageEnvelope(type, requestId, payload);
      if (!message || !sendRaw(message)) {
        pending.delete(requestId);
        clearTimeout(timer);
        const error = new Error("未连接工作台");
        reportWriteFailure(type, error);
        reject(error);
      }
    });
  }

  function collect(payload) {
    return request("radar-collect", payload);
  }

  function emitHostMessage(data) {
    if (hostMessageHandler) hostMessageHandler(data);
    else queuedHostMessages.push(data);
    for (const listener of extraHostListeners) listener(data);
  }

  function setMessageHandler(handler) {
    hostMessageHandler = typeof handler === "function" ? handler : null;
    if (!hostMessageHandler) return;
    while (queuedHostMessages.length) hostMessageHandler(queuedHostMessages.shift());
  }

  function addHostMessageListener(handler) {
    if (typeof handler !== "function" || extraHostListeners.includes(handler)) return;
    extraHostListeners.push(handler);
  }

  function setWriteFailureHandler(handler) {
    writeFailureHandler = typeof handler === "function" ? handler : null;
  }

  function reportWriteFailure(type, error) {
    if (!SYNC_WRITE_TYPES.has(type)) return;
    if (Number(error?.status) === 409 || Number(error?.statusCode) === 409) return;
    if (writeFailureHandler) writeFailureHandler({ type, error });
  }

  function settleRequest(data) {
    if (typeof data.requestId !== "string") return false;
    const entry = pending.get(data.requestId);
    if (!entry || data.type !== entry.expectedResultType) return false;
    pending.delete(data.requestId);
    clearTimeout(entry.timer);
    if (data.ok) entry.resolve(data);
    else {
      const declined = data.declined === true
        || (data.type === "radar-collect-result" && data.error === "用户未确认");
      const error = new Error(data.error || (data.type === "radar-collect-result" ? "收藏失败" : "工作台操作失败"));
      Object.assign(error, {
        status: data.status,
        statusCode: data.statusCode,
        code: data.code,
        state: data.state,
        legacyReadMigration: data.legacyReadMigration,
        declined,
      });
      if (!declined) reportWriteFailure(entry.requestType, error);
      entry.reject(error);
    }
    return true;
  }

  function acceptHostMessage(data, sourceTransport) {
    if (data.type === "workbench-hello") {
      const currentHandshakeRequestId = sourceTransport === "iframe"
        ? iframeHandshakeRequestId
        : nativeHandshakeRequestId;
      if (transport || !currentHandshakeRequestId || data.requestId !== currentHandshakeRequestId) return false;
      stopNativeHandshake();
      stopIframeHandshake();
      transport = sourceTransport;
      if (sourceTransport === "native") flushQueuedNativeExternalMessages();
      else queuedNativeExternalMessages.length = 0;
      emitHostMessage(data);
      try {
        if (typeof rerenderCurrentView === "function") rerenderCurrentView();
      } catch {
        // 数据尚未加载完成时接到握手，等 boot 正常渲染即可。
      }
      return true;
    }
    if (data.type === "radar-exploration-state") {
      emitHostMessage(data);
      return true;
    }
    if (!connected()) return false;
    const entry = pending.get(data.requestId);
    if (!entry || data.type !== entry.expectedResultType) return false;
    const settled = settleRequest(data);
    if (data.type === "radar-collect-result" || data.type === "radar-source-config-result") {
      return settled;
    }
    if (!settled) return false;
    emitHostMessage(data);
    return true;
  }

  window.addEventListener("message", (event) => {
    const data = parseHostEnvelope(event.data);
    if (!data) return;
    if (data.type === "workbench-hello") {
      // 三重校验：来源域名在白名单、本页确实被嵌入、消息确实来自父窗口
      if (!PARENT_ORIGINS.has(event.origin)) return;
      if (window === window.parent || event.source !== window.parent) return;
      parentWin = event.source;
      parentOrigin = event.origin;
      acceptHostMessage(data, "iframe");
      return;
    }
    // 回执必须同时来自已握手的父窗口和已锁定的父页面 origin。
    if (transport !== "iframe" || !parentWin || !parentOrigin) return;
    if (event.source !== parentWin || event.origin !== parentOrigin) return;
    acceptHostMessage(data, "iframe");
  });

  function receiveHostMessage(json) {
    if (!resolveNativeProxy() || transport === "iframe") return false;
    let data = json;
    if (typeof json === "string") {
      try {
        data = JSON.parse(json);
      } catch {
        return false;
      }
    }
    data = parseHostEnvelope(data);
    if (!data) return false;
    if (!transport && data.type !== "workbench-hello") return false;
    return acceptHostMessage(data, "native");
  }

  function openExternal(url) {
    let normalized = "";
    try {
      const parsed = new URL(url, window.location.href);
      if (!/^https?:$/.test(parsed.protocol)) return false;
      normalized = parsed.toString();
    } catch {
      return false;
    }
    const requestId = nextRequestId();
    const message = createPageEnvelope("radar-open-external", requestId, { url: normalized });
    if (!message) return false;
    if (sendRaw(message)) {
      lastExternalOpenFailure = null;
      return true;
    }
    if (!appRequested || transport || !nativeHandshakeDeadline || Date.now() >= nativeHandshakeDeadline) {
      lastExternalOpenFailure = { url: normalized, error: "原生宿主不可用" };
      return false;
    }
    queuedNativeExternalMessages.push(message);
    return true;
  }

  window.WorkbenchBridge = {
    connected,
    collect,
    notify,
    request,
    openExternal,
    lastExternalOpenError() {
      return lastExternalOpenFailure;
    },
    receiveHostMessage,
    setMessageHandler,
    addHostMessageListener,
    setWriteFailureHandler,
    appRequested() {
      return appRequested;
    },
    readerOnlyRequested() {
      return readerOnlyRequested;
    },
    markCollected(url) {
      if (url) collectedUrls.add(url);
    },
    isCollected(url) {
      return collectedUrls.has(url);
    },
  };

  window.addEventListener("pagehide", () => {
    stopNativeHandshake();
    stopIframeHandshake();
    queuedNativeExternalMessages.length = 0;
  }, { once: true });
  startIframeHandshake();
  startNativeHandshake();
})();

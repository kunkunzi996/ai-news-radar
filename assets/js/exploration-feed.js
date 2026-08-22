(function () {
  const MAX_STRIPS = 3;
  let batchItems = [];
  let drawerEl = null;
  let collectPending = false;

  function canShowExploration() {
    if (typeof state !== "object" || !state) return false;
    if (state.activeSection !== "creator") return false;
    if (String(state.query || "").trim()) return false;
    if (state.sourceTypeFilter) return false;
    if (state.siteFilter) return false;
    return Array.isArray(batchItems) && batchItems.length > 0;
  }

  function placeAfter(ordinaryCount, exploreCount) {
    const maxK = Math.min(exploreCount, ordinaryCount, MAX_STRIPS);
    if (!maxK) return [];
    const slots = [];
    for (let i = 0; i < maxK; i += 1) {
      const pos = Math.min(ordinaryCount, i * 2 + 1);
      if (!slots.includes(pos)) slots.push(pos);
    }
    return slots;
  }

  function markItemSeen(id) {
    const item = batchItems.find((entry) => entry.id === id);
    if (item) item.seen = true;
    if (window.WorkbenchBridge && typeof window.WorkbenchBridge.notify === "function") {
      window.WorkbenchBridge.notify("radar-exploration-seen", { id });
    }
  }

  function buildStrip(item) {
    const article = document.createElement("article");
    article.className = "explore-signal";
    article.setAttribute("data-exploration", "1");
    if (item.seen) article.classList.add("is-seen");

    const badge = document.createElement("span");
    badge.className = "explore-signal-badge";
    badge.textContent = item.domain ? `探索信号 · ${item.domain}` : "探索信号";

    const body = document.createElement("div");
    const title = document.createElement("h3");
    title.textContent = item.title || "";
    const why = document.createElement("p");
    why.className = "explore-signal-why";
    why.textContent = item.why || "";
    body.append(title, why);

    const action = document.createElement("button");
    action.type = "button";
    action.className = "explore-signal-action";
    action.textContent = "值得深挖";
    action.addEventListener("click", () => openDrawer(item));

    article.append(badge, body, action);
    return article;
  }

  function ensureDrawer() {
    if (drawerEl) return drawerEl;
    drawerEl = document.createElement("div");
    drawerEl.className = "explore-drawer-root";
    drawerEl.hidden = true;
    drawerEl.innerHTML = [
      '<div class="explore-drawer-mask" data-explore-close="1"></div>',
      '<div class="explore-drawer" role="dialog" aria-modal="true" aria-label="探索信号详情">',
      '  <header class="explore-drawer-head">',
      '    <strong></strong>',
      '    <button type="button" class="explore-drawer-close" data-explore-close="1" aria-label="关闭">×</button>',
      '  </header>',
      '  <div class="explore-drawer-body">',
      '    <section><h4>发生了什么</h4><p data-block="what"></p></section>',
      '    <section><h4>证据靠不靠谱</h4><p data-block="evidence"></p></section>',
      '    <section><h4>为什么与你有关</h4><p data-block="why"></p></section>',
      '    <section><h4>接下来盯什么</h4><p data-block="next"></p></section>',
      '    <p class="explore-ask-status" hidden></p>',
      '  </div>',
      '  <footer class="explore-drawer-foot">',
      '    <button type="button" class="explore-collect-btn">存进收藏库</button>',
      '    <button type="button" class="explore-ask-btn">问 AI</button>',
      '  </footer>',
      '</div>',
    ].join("");
    document.body.appendChild(drawerEl);
    drawerEl.addEventListener("click", (event) => {
      if (event.target && event.target.getAttribute("data-explore-close") === "1") closeDrawer();
    });
    return drawerEl;
  }

  function setAskStatus(text) {
    const status = ensureDrawer().querySelector(".explore-ask-status");
    if (!text) {
      status.hidden = true;
      status.textContent = "";
      return;
    }
    status.hidden = false;
    status.textContent = text;
  }

  function openDrawer(item) {
    const root = ensureDrawer();
    root.hidden = false;
    root.dataset.itemId = item.id || "";
    root.querySelector(".explore-drawer-head strong").textContent = item.title || "探索信号";
    root.querySelector('[data-block="what"]').textContent = item.what || "";
    root.querySelector('[data-block="evidence"]').textContent = item.evidence || "";
    root.querySelector('[data-block="why"]').textContent = item.why || "";
    root.querySelector('[data-block="next"]').textContent = item.next || "";
    const collectBtn = root.querySelector(".explore-collect-btn");
    collectBtn.textContent = "存进收藏库";
    collectBtn.disabled = false;
    collectPending = false;
    setAskStatus("");
    markItemSeen(item.id);
    applyExplorationFeed();
  }

  function closeDrawer() {
    if (drawerEl) drawerEl.hidden = true;
  }

  function currentDrawerItem() {
    const id = drawerEl && drawerEl.dataset.itemId;
    return batchItems.find((entry) => entry.id === id) || null;
  }

  async function collectCurrent() {
    const item = currentDrawerItem();
    const button = ensureDrawer().querySelector(".explore-collect-btn");
    if (!item || collectPending || !window.WorkbenchBridge || typeof window.WorkbenchBridge.collect !== "function") return;
    collectPending = true;
    try {
      const result = await window.WorkbenchBridge.collect({
        title: item.title,
        url: item.url,
        summary: item.why || "",
        source: item.source || "探索信号",
      });
      if (result && result.ok) button.textContent = "已在收藏库";
    } catch {
      button.textContent = "存进收藏库";
    } finally {
      collectPending = false;
    }
  }

  async function askCurrent() {
    const item = currentDrawerItem();
    if (!item || !window.WorkbenchBridge) return;
    setAskStatus("");
    const payload = { id: item.id, message: "这篇接下来该盯什么？" };
    try {
      if (typeof window.WorkbenchBridge.request === "function") {
        const result = await window.WorkbenchBridge.request("radar-exploration-ask", payload);
        if (!result || result.ok === false) {
          setAskStatus((result && result.error) || "问 AI 失败");
          return;
        }
        const answer = typeof result.text === "string" ? result.text.trim() : "";
        setAskStatus(answer || result.error || "");
      } else if (typeof window.WorkbenchBridge.notify === "function") {
        window.WorkbenchBridge.notify("radar-exploration-ask", payload);
      }
    } catch (error) {
      setAskStatus((error && error.message) || "问 AI 失败");
    }
  }

  function bindDrawerActions() {
    const root = ensureDrawer();
    root.querySelector(".explore-collect-btn").addEventListener("click", () => {
      collectCurrent();
    });
    root.querySelector(".explore-ask-btn").addEventListener("click", () => {
      askCurrent();
    });
  }

  function clearStrips() {
    if (!newsListEl) return;
    newsListEl.querySelectorAll(".explore-signal").forEach((node) => node.remove());
  }

  function applyExplorationFeed() {
    if (!newsListEl) return;
    clearStrips();
    if (!canShowExploration()) return;
    const cards = Array.from(newsListEl.querySelectorAll(".news-card"));
    if (!cards.length) return;
    const slots = placeAfter(cards.length, batchItems.length);
    const planned = [];
    slots.forEach((pos, index) => {
      if (batchItems[index] && cards[pos - 1]) planned.push({ pos, item: batchItems[index] });
    });
    planned.sort((left, right) => right.pos - left.pos);
    planned.forEach(({ pos, item }) => {
      const card = cards[pos - 1];
      const anchor = card.closest(".timeline-row") || card;
      const parent = anchor.parentNode;
      if (!parent) return;
      parent.insertBefore(buildStrip(item), anchor.nextSibling);
    });
  }

  function storeBatch(message) {
    const items = Array.isArray(message && message.items) ? message.items : [];
    batchItems = items.slice(0, MAX_STRIPS).filter((item) => item && item.title).map((item) => ({
      ...item,
      next: item.next || "",
    }));
  }

  function handleHostExploration(data) {
    if (!data || typeof data !== "object") return;
    if (data.type === "radar-exploration-state") {
      if (!window.WorkbenchBridge || !window.WorkbenchBridge.connected()) return;
      storeBatch(data);
      applyExplorationFeed();
      return;
    }
    if (data.type !== "radar-exploration-ask-result") return;
    if (data.ok === false) {
      setAskStatus(data.error || "问 AI 失败");
      return;
    }
    const answer = typeof data.text === "string" ? data.text.trim() : "";
    if (answer) setAskStatus(answer);
  }

  window.addEventListener("message", (event) => {
    handleHostExploration(event.data);
  });
  if (window.WorkbenchBridge && typeof window.WorkbenchBridge.addHostMessageListener === "function") {
    window.WorkbenchBridge.addHostMessageListener(handleHostExploration);
  }

  document.addEventListener("aiRadar:listRendered", () => {
    applyExplorationFeed();
  });

  if (typeof renderList === "function") {
    const originalRenderList = renderList;
    renderList = function explorationAwareRenderList() {
      originalRenderList.apply(this, arguments);
      requestAnimationFrame(applyExplorationFeed);
    };
  }

  bindDrawerActions();

  window.ExplorationFeed = {
    apply: applyExplorationFeed,
  };
})();

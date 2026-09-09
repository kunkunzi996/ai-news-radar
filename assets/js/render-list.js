function feedSummaryText(item) {
  const signals = Array.isArray(item.ai_signals) ? item.ai_signals.filter(Boolean).slice(0, 2) : [];
  if (signals.length) return `相关线索：${signals.join(" / ")}。`;
  const reason = reasonText(item);
  if (reason.startsWith("订阅互动")) return reason;
  const source = item.source || item.site_name || sourceDisplayName(item);
  return source ? `${source} 的更新` : "";
}
function timelineItemDate(item) {
  const date = new Date(timelineIso(item));
  return Number.isNaN(date.getTime()) ? null : date;
}
function timelineDayKey(item) {
  const date = timelineItemDate(item);
  if (!date) return "unknown";
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}
function timelineClockText(date) {
  return new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).format(date);
}
function timelineDateText(date) {
  return `${date.getMonth() + 1}月${date.getDate()}日`;
}
function timelineWeekdayText(date) {
  return ["星期日", "星期一", "星期二", "星期三", "星期四", "星期五", "星期六"][date.getDay()];
}
function renderItemNode(item, context = {}) {
  const node = itemTpl.content.firstElementChild.cloneNode(true);
  const platformKey = itemPlatformSection(item) || "rss";
  node.classList.add(`platform-${platformKey}`);
  if (item.id) node.dataset.itemId = String(item.id);

  const avatarEl = node.querySelector(".card-avatar");
  const avatarText = String(item.source || item.site_name || sourceDisplayName(item) || "源").trim();
  if (avatarEl) avatarEl.textContent = Array.from(avatarText)[0] || "源";

  const siteEl = node.querySelector(".site");
  siteEl.textContent = item.source || item.site_name;
  if (context.source && context.source === item.source) {
    siteEl.hidden = true;
  }
  const kind = sourceKind(item.site_id);
  const categoryEl = node.querySelector(".category");
  categoryEl.textContent = kind.label;
  categoryEl.classList.add(`kind-${kind.tone}`);

  const sourceEl = node.querySelector(".source");
  if (sourceEl) sourceEl.hidden = true;

  const timeEl = node.querySelector(".time");
  const timeline = timelineIso(item);
  const timelineDate = timelineItemDate(item);
  if (timelineDate) {
    timeEl.textContent = fmtTime(timeline);
    timeEl.setAttribute("datetime", timeline);
  } else {
    timeEl.textContent = "时间未知";
    timeEl.removeAttribute("datetime");
  }

  const titleEl = node.querySelector(".title");
  const zh = (item.title_zh || "").trim();
  const en = (item.title_en || "").trim();
  titleEl.textContent = "";
  if (zh && en && zh !== en) {
    const primary = document.createElement("span");
    primary.textContent = zh;
    const sub = document.createElement("span");
    sub.className = "title-sub";
    sub.textContent = en;
    titleEl.appendChild(primary);
    titleEl.appendChild(sub);
  } else {
    titleEl.textContent = item.title || zh || en;
  }
  titleEl.href = item.url;
  const summaryEl = node.querySelector(".news-summary");
  if (summaryEl) summaryEl.textContent = feedSummaryText(item);
  const actions = buildItemActions(item, context);
  if (actions) node.appendChild(actions);
  return node;
}
function shouldRenderReadToggle(item, context = {}) {
  return context.readToggleEligible === true || isSubscriptionItem(item);
}
function buildReadToggleButton(item) {
  const btn = document.createElement("button");
  btn.type = "button";
  const read = isItemRead(item);
  btn.className = `read-toggle-btn${read ? " is-read" : ""}`;
  const monotonic = Boolean(window.RadarSync && window.RadarSync.monotonicReads());
  btn.textContent = read && !monotonic ? "恢复" : "已阅";
  btn.title = read
    ? (monotonic ? "已阅状态已同步，不能恢复为未阅" : "恢复到我的订阅")
    : "标记已阅，从看板中移出";
  btn.disabled = read && monotonic;
  btn.addEventListener("click", () => toggleItemRead(item, { node: btn.closest(".news-card") }));
  return btn;
}
function buildCollectButton(item) {
  const btn = document.createElement("button");
  btn.type = "button";
  const collected = window.WorkbenchBridge.isCollected(item.url);
  const idleTitle = "收藏到工作台收藏库，并标记已阅";
  btn.className = `collect-btn${collected ? " is-collected" : ""}`;
  btn.textContent = collected ? "已收藏" : "收藏";
  btn.title = collected ? "已收藏到工作台收藏库" : idleTitle;
  btn.disabled = false;
  if (!collected && window.RadarSync && !window.RadarSync.canWriteCollections()) {
    btn.textContent = "同步暂停";
    btn.title = "同步暂不可用，当前仍可阅读和打开原文";
    btn.disabled = true;
    return btn;
  }
  btn.addEventListener("click", async () => {
    if (window.WorkbenchBridge.isCollected(item.url)) {
      btn.textContent = "已在收藏库";
      btn.title = "该内容已在工作台收藏库，不会重复收藏";
      btn.classList.add("is-collected");
      return;
    }
    if (window.RadarSync && !window.RadarSync.canWriteCollections()) {
      btn.textContent = "同步暂停";
      btn.title = "同步暂不可用，当前仍可阅读和打开原文";
      btn.disabled = true;
      return;
    }
    btn.disabled = true;
    btn.textContent = "收藏中…";
    try {
      await window.WorkbenchBridge.collect({
        title: itemTitleText(item) || item.title || "",
        url: item.url || "",
        summary: feedSummaryText(item),
        source: item.source || item.site_name || "",
        publishedAt: item.published_at || "",
      });
      window.WorkbenchBridge.markCollected(item.url);
      btn.textContent = "已收藏";
      btn.title = "已收藏到工作台收藏库";
      btn.classList.add("is-collected");
      btn.disabled = false;
      // 收藏做成才顺手标已阅；只动这一张卡，按钮状态由 isCollected 记住
      if (!isItemRead(item) && workbenchReadKey(item)) {
        toggleItemRead(item, { node: btn.closest(".news-card") });
      }
    } catch (err) {
      btn.textContent = "收藏失败";
      btn.title = String((err && err.message) || err);
      setTimeout(() => {
        btn.disabled = false;
        btn.textContent = "收藏";
        btn.title = idleTitle;
      }, 3000);
    }
  });
  return btn;
}
function buildItemActions(item, context = {}) {
  const bridgeOn = !!(window.WorkbenchBridge && window.WorkbenchBridge.connected());
  const showRead = shouldRenderReadToggle(item, context);
  if (!bridgeOn && !showRead) return null;
  const wrap = document.createElement("div");
  wrap.className = "item-actions";
  if (bridgeOn && item.url) wrap.appendChild(buildCollectButton(item));
  if (showRead) wrap.appendChild(buildReadToggleButton(item));
  return wrap;
}
function buildSourceGroupNode(source, items, rawCount = items.length) {
  const section = document.createElement("section");
  section.className = "source-group";
  const header = document.createElement("header");
  header.className = "source-group-head";
  const title = document.createElement("h3");
  title.textContent = source;
  const count = document.createElement("span");
  count.className = "group-summary";
  count.textContent = subgroupSummary(items, rawCount);
  const listEl = document.createElement("div");
  listEl.className = "source-group-list";
  header.append(title, count);
  section.append(header, listEl);

  let expanded = false;
  if (items.length > SOURCE_ITEM_INITIAL_LIMIT) {
    const moreBtn = document.createElement("button");
    moreBtn.type = "button";
    moreBtn.className = "group-more-btn";
    const renderItems = () => {
      listEl.innerHTML = "";
      const visibleItems = expanded ? items : items.slice(0, SOURCE_ITEM_INITIAL_LIMIT);
      visibleItems.forEach((item) => listEl.appendChild(renderItemNode(item, { source })));
      moreBtn.textContent = expanded
        ? `收起，仅看前 ${SOURCE_ITEM_INITIAL_LIMIT} 条`
        : `展开剩余 ${fmtNumber(items.length - SOURCE_ITEM_INITIAL_LIMIT)} 条`;
    };
    moreBtn.addEventListener("click", () => {
      expanded = !expanded;
      renderItems();
    });
    renderItems();
    section.append(moreBtn);
  } else {
    items.forEach((item) => listEl.appendChild(renderItemNode(item, { source })));
  }
  return section;
}
function displayDedupeKey(item) {
  const title = normalizedEventText(itemTitleText(item));
  // Short social-post titles such as "AI小狗" still identify the same visible
  // post within one creator subgroup; URL query strings often only carry a
  // rotating access token and must not defeat that deduplication.
  if (title) return `title:${title}`;
  try {
    const url = new URL(item.url || "");
    return `url:${url.origin}${url.pathname}`;
  } catch {
    return `url:${item.url || item.id || "untitled"}`;
  }
}
function dedupeSubgroupItems(items) {
  const seen = new Set();
  return sortItemsForList(items).filter((item) => {
    const key = displayDedupeKey(item);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}
function subgroupSortValue(items) {
  if (!items.length) return 0;
  if (state.listSort === "time") return Math.max(...items.map(timelineMs));
  if (state.listSort === "ai") return Math.max(...items.map(scorePercent));
  if (state.listSort === "source") return items.length;
  const leading = [...items]
    .sort((a, b) => itemPriorityScore(b) - itemPriorityScore(a))
    .slice(0, 3);
  return Math.round(leading.reduce((sum, item) => sum + itemPriorityScore(item), 0) / leading.length);
}
function subgroupSummary(items, rawCount = items.length) {
  const count = `${fmtNumber(items.length)} 条`;
  const merged = rawCount - items.length;
  let ranking = "";
  if (state.listSort === "priority") ranking = `综合 ${subgroupSortValue(items)}`;
  if (state.listSort === "time") ranking = `时间 ${fmtTime(timelineIso(items[0]))}`;
  if (state.listSort === "ai") ranking = `最高 AI ${subgroupSortValue(items)}分`;
  const mergedLabel = merged > 0 ? `合并 ${fmtNumber(merged)} 条重复` : "";
  return [count, ranking, mergedLabel].filter(Boolean).join(" · ");
}
function sourceGroupEntries(items) {
  const groupMap = new Map();
  items.forEach((item) => {
    const key = item.source || "未分区";
    if (!groupMap.has(key)) {
      groupMap.set(key, []);
    }
    groupMap.get(key).push(item);
  });

  return Array.from(groupMap.entries())
    .map(([source, rawItems]) => ({
      source,
      rawCount: rawItems.length,
      items: dedupeSubgroupItems(rawItems),
    }))
    .filter((group) => group.items.length)
    .sort((a, b) => {
      const byScore = subgroupSortValue(b.items) - subgroupSortValue(a.items);
      if (byScore !== 0) return byScore;
      const byCount = b.items.length - a.items.length;
      if (byCount !== 0) return byCount;
      return a.source.localeCompare(b.source, "zh-CN");
    });
}
// Mobile-safe async rendering: avoid blocking the main thread on large lists.
// We chunk site-groups and yield between each chunk so the browser can paint
// and respond to touch events while the list is being built.
let _renderListToken = 0;
let _listStayFollowOuter = 0;
let _listStayFollowInner = 0;

function buildSiteGroupNode(site) {
  const siteSection = document.createElement("section");
  siteSection.className = "site-group";
  const header = document.createElement("header");
  header.className = "site-group-head";
  const title = document.createElement("h3");
  title.textContent = site.siteName;
  const count = document.createElement("span");
  count.className = "group-summary";
  count.textContent = subgroupSummary(site.items, site.rawCount);
  const siteListEl = document.createElement("div");
  siteListEl.className = "site-group-list";
  header.append(title, count);
  siteSection.append(header, siteListEl);

  const sourceGroups = site.sourceGroups;
  let expanded = false;
  let moreBtn = null;
  const renderSourceGroups = () => {
    siteListEl.innerHTML = "";
    if (moreBtn) moreBtn.remove();
    const visibleGroups = expanded
      ? sourceGroups
      : sourceGroups.slice(0, SITE_SOURCE_GROUP_INITIAL_LIMIT);
    const frag = document.createDocumentFragment();
    visibleGroups.forEach((group) => {
      frag.appendChild(buildSourceGroupNode(group.source, group.items, group.rawCount));
    });
    siteListEl.appendChild(frag);
    if (sourceGroups.length > SITE_SOURCE_GROUP_INITIAL_LIMIT) {
      const hiddenCount = sourceGroups.length - SITE_SOURCE_GROUP_INITIAL_LIMIT;
      moreBtn = addLoadMoreButton(
        siteSection,
        expanded
          ? `收起，仅看前 ${SITE_SOURCE_GROUP_INITIAL_LIMIT} 个分区`
          : `展开其余 ${fmtNumber(hiddenCount)} 个分区`,
        () => {
          expanded = !expanded;
          renderSourceGroups();
        },
      );
    }
  };
  renderSourceGroups();
  return siteSection;
}
function renderLoadingNotice(label, count) {
  const loading = document.createElement("div");
  loading.className = "list-loading";
  loading.textContent = `正在整理 ${label} · ${fmtNumber(count)} 条`;
  newsListEl.appendChild(loading);
}
function currentFilterLabel(filtered) {
  if (state.authorFilter) return `${listTitleText()} · X 博主 ${state.authorFilter}`;
  if (state.siteFilter) {
    const item = filtered[0];
    const stat = currentSiteStats().find((s) => s.site_id === state.siteFilter);
    return `${listTitleText()} · ${sourceDisplayName(item || stat || state.siteFilter)}`;
  }
  return listTitleText();
}
function groupedSites(items) {
  const siteMap = new Map();
  items.forEach((item) => {
    if (!siteMap.has(item.site_id)) {
      siteMap.set(item.site_id, { siteName: sourceDisplayName(item), rawItems: [] });
    }
    siteMap.get(item.site_id).rawItems.push(item);
  });

  return Array.from(siteMap.entries())
    .map(([siteId, site]) => {
      const sourceGroups = sourceGroupEntries(site.rawItems);
      return [siteId, {
        siteName: site.siteName,
        rawCount: site.rawItems.length,
        sourceGroups,
        items: sourceGroups.flatMap((group) => group.items),
      }];
    })
    .filter(([, site]) => site.items.length)
    .sort((a, b) => {
      const byScore = subgroupSortValue(b[1].items) - subgroupSortValue(a[1].items);
      if (byScore !== 0) return byScore;
      const byCount = b[1].items.length - a[1].items.length;
      if (byCount !== 0) return byCount;
      return a[1].siteName.localeCompare(b[1].siteName, "zh-CN");
    });
}
function addLoadMoreButton(parent, label, onClick) {
  const moreBtn = document.createElement("button");
  moreBtn.type = "button";
  moreBtn.className = "list-more-btn";
  moreBtn.textContent = label;
  moreBtn.addEventListener("click", onClick);
  parent.appendChild(moreBtn);
  return moreBtn;
}
function buildTimelineRow(item) {
  const row = document.createElement("div");
  const platformKey = itemPlatformSection(item) || "rss";
  row.className = `timeline-row platform-${platformKey}`;

  const time = document.createElement("time");
  time.className = "timeline-time";
  const timeline = timelineIso(item);
  const date = timelineItemDate(item);
  if (date) {
    time.textContent = timelineClockText(date);
    time.setAttribute("datetime", timeline);
  } else {
    time.textContent = "--:--";
  }

  const rail = document.createElement("span");
  rail.className = "timeline-rail";
  rail.setAttribute("aria-hidden", "true");
  const dot = document.createElement("span");
  dot.className = "timeline-dot";
  rail.appendChild(dot);

  row.append(time, rail, renderItemNode(item, { readToggleEligible: true }));
  return row;
}
function buildTimelineDaySection(key, items) {
  const section = document.createElement("section");
  section.className = "timeline-day";
  const headingId = `timeline-day-${key}`;
  section.setAttribute("aria-labelledby", headingId);

  const header = document.createElement("header");
  header.className = "timeline-day-head";
  const title = document.createElement("h3");
  title.className = "timeline-date";
  title.id = headingId;
  const meta = document.createElement("span");
  meta.className = "timeline-day-meta";
  const date = key === "unknown" ? null : timelineItemDate(items[0]);
  if (date) {
    title.textContent = timelineDateText(date);
    meta.textContent = `${timelineWeekdayText(date)} · ${fmtNumber(items.length)} 条`;
  } else {
    title.textContent = "日期未知";
    meta.textContent = `时间字段无效 · ${fmtNumber(items.length)} 条`;
  }
  header.append(title, meta);

  const rows = document.createElement("div");
  rows.className = "timeline-day-items";
  items.forEach((item) => rows.appendChild(buildTimelineRow(item)));
  section.append(header, rows);
  return section;
}
function listMoreButton() {
  return newsListEl.querySelector(":scope > .list-more-btn");
}
function flatTimelinePagerLabel(total, pageSize) {
  return state.siteGroupsExpanded
    ? `收起，仅看前 ${fmtNumber(pageSize)} 条`
    : `继续看剩余 ${fmtNumber(total - pageSize)} 条`;
}
function findTimelineDaySection(key) {
  const heading = newsListEl.querySelector(`#${CSS.escape(`timeline-day-${key}`)}`);
  return heading ? heading.closest(".timeline-day") : null;
}
function updateTimelineDayMeta(section) {
  const meta = section.querySelector(".timeline-day-meta");
  if (!meta) return;
  const count = section.querySelectorAll(".timeline-row").length;
  const prefix = String(meta.textContent || "").split(" · ")[0] || "";
  meta.textContent = `${prefix} · ${fmtNumber(count)} 条`;
}
function insertBeforeListPager(node) {
  const moreBtn = listMoreButton();
  if (moreBtn) newsListEl.insertBefore(node, moreBtn);
  else newsListEl.appendChild(node);
}
function appendFlatTimelineRemainder(items, pageSize) {
  const remainder = items.slice(pageSize);
  if (!remainder.length) return;
  if (state.listSort === "time") {
    const groups = new Map();
    remainder.forEach((item) => {
      const key = timelineDayKey(item);
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(item);
    });
    groups.forEach((groupItems, key) => {
      const existing = findTimelineDaySection(key);
      if (existing) {
        const rows = existing.querySelector(".timeline-day-items");
        groupItems.forEach((item) => rows.appendChild(buildTimelineRow(item)));
        updateTimelineDayMeta(existing);
        return;
      }
      insertBeforeListPager(buildTimelineDaySection(key, groupItems));
    });
    return;
  }
  const frag = document.createDocumentFragment();
  remainder.forEach((item) => {
    frag.appendChild(renderItemNode(item, { readToggleEligible: true }));
  });
  insertBeforeListPager(frag);
}
function collapseFlatTimeline(pageSize) {
  if (state.listSort === "time") {
    const rows = Array.from(newsListEl.querySelectorAll(".timeline-row"));
    rows.slice(pageSize).forEach((row) => row.remove());
    newsListEl.querySelectorAll(".timeline-day").forEach((day) => {
      if (!day.querySelector(".timeline-row")) day.remove();
      else updateTimelineDayMeta(day);
    });
    return;
  }
  const cards = Array.from(newsListEl.querySelectorAll(":scope > .news-card"));
  cards.slice(pageSize).forEach((card) => card.remove());
}
function renderFlatTimeline(items) {
  const pageSize = TIMELINE_PAGE_SIZE;
  const shown = state.siteGroupsExpanded ? items.length : Math.min(pageSize, items.length);
  const visibleItems = items.slice(0, shown);
  const frag = document.createDocumentFragment();
  if (state.listSort === "time") {
    const groups = new Map();
    visibleItems.forEach((item) => {
      const key = timelineDayKey(item);
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(item);
    });
    groups.forEach((groupItems, key) => {
      frag.appendChild(buildTimelineDaySection(key, groupItems));
    });
  } else {
    visibleItems.forEach((item) => {
      frag.appendChild(renderItemNode(item, { readToggleEligible: true }));
    });
  }
  newsListEl.appendChild(frag);

  if (items.length > pageSize) {
    const moreBtn = addLoadMoreButton(
      newsListEl,
      flatTimelinePagerLabel(items.length, pageSize),
      () => {
        if (state.siteGroupsExpanded) {
          collapseFlatTimeline(pageSize);
          state.siteGroupsExpanded = false;
        } else {
          appendFlatTimelineRemainder(items, pageSize);
          state.siteGroupsExpanded = true;
        }
        moreBtn.textContent = flatTimelinePagerLabel(items.length, pageSize);
      },
    );
  }
  document.dispatchEvent(new CustomEvent("aiRadar:listRendered"));
}
function renderSiteGroups(items) {
  const groups = groupedSites(items);
  const visibleGroups = state.siteGroupsExpanded
    ? groups
    : groups.slice(0, SITE_GROUP_INITIAL_LIMIT);
  visibleGroups.forEach(([, site]) => {
    newsListEl.appendChild(buildSiteGroupNode(site));
  });

  if (groups.length > SITE_GROUP_INITIAL_LIMIT) {
    const hiddenCount = groups.length - SITE_GROUP_INITIAL_LIMIT;
    addLoadMoreButton(
      newsListEl,
      state.siteGroupsExpanded
        ? `收起，仅看前 ${SITE_GROUP_INITIAL_LIMIT} 个来源`
        : `展开其余 ${fmtNumber(hiddenCount)} 个来源`,
      () => {
        state.siteGroupsExpanded = !state.siteGroupsExpanded;
        renderList();
      },
    );
  }
  document.dispatchEvent(new CustomEvent("aiRadar:listRendered"));
}
function usesFlatTimelineLayout(sectionId) {
  return Boolean(SECTION_BY_ID[sectionId]);
}
function ensureListStaySpacer(slotTop) {
  if (!newsListEl) return;
  let spacer = newsListEl.querySelector("[data-list-stay-spacer='1']");
  if (!spacer) {
    spacer = document.createElement("div");
    spacer.dataset.listStaySpacer = "1";
    spacer.setAttribute("aria-hidden", "true");
    newsListEl.appendChild(spacer);
  }
  const scrolling = document.scrollingElement || document.documentElement;
  const viewport = scrolling.clientHeight || window.innerHeight || 0;
  const safeSlot = Number.isFinite(slotTop) ? Math.max(0, slotTop) : 0;
  spacer.style.height = `${Math.max(0, viewport - safeSlot)}px`;
}

function currentListStayScrollY() {
  const scrolling = document.scrollingElement || document.documentElement;
  return Number((scrolling && scrolling.scrollTop) || window.scrollY || 0);
}

function consumeListStayRestore(followUp) {
  const stay = state.pendingListStay;
  if (!stay) return;
  const slotTop = Number(stay.slotTop);
  const anchorId = stay.anchorId ? String(stay.anchorId) : "";
  if (!anchorId || !Number.isFinite(slotTop) || !newsListEl) {
    state.pendingListStay = null;
    return;
  }
  if (anchorId.includes("\"") || anchorId.includes("\\")) {
    state.pendingListStay = null;
    return;
  }
  const anchor = newsListEl.querySelector(`.news-card[data-item-id="${anchorId}"]`);
  if (!anchor) return;
  state.pendingListStay = null;
  // 两帧后再校正是为了排版落稳。人已经开始滚了，位移就不是排版偏移，不能再拽回去。
  if (followUp) {
    const expected = Number(state.listStayRestoreScrollY);
    if (Number.isFinite(expected) && Math.abs(currentListStayScrollY() - expected) >= 1) return;
  }
  const scrolling = document.scrollingElement || document.documentElement;
  newsListEl.style.overflowAnchor = "none";
  if (scrolling) scrolling.style.overflowAnchor = "none";
  if (document.body) document.body.style.overflowAnchor = "none";
  ensureListStaySpacer(slotTop);
  const delta = anchor.getBoundingClientRect().top - slotTop;
  if (Math.abs(delta) >= 1) window.scrollBy(0, delta);
  if (followUp) return;
  if (_listStayFollowOuter) cancelAnimationFrame(_listStayFollowOuter);
  if (_listStayFollowInner) cancelAnimationFrame(_listStayFollowInner);
  const expectedY = currentListStayScrollY();
  state.listStayRestoreScrollY = expectedY;
  const followStay = { anchorId, slotTop };
  _listStayFollowOuter = requestAnimationFrame(() => {
    _listStayFollowOuter = 0;
    _listStayFollowInner = requestAnimationFrame(() => {
      _listStayFollowInner = 0;
      if (Math.abs(currentListStayScrollY() - expectedY) >= 1) return;
      state.pendingListStay = followStay;
      consumeListStayRestore(true);
    });
  });
}

function renderList() {
  newsListEl.style.overflowAnchor = "none";
  const filtered = getFilteredItems();
  renderListSortTools();
  newsListEl.classList.remove("timeline-mode", "flat-mode", "group-mode");
  if (usesFlatTimelineLayout(state.activeSection)) {
    newsListEl.classList.add(state.listSort === "time" ? "timeline-mode" : "flat-mode");
  } else {
    newsListEl.classList.add("group-mode");
  }
  resultCountEl.textContent = `${fmtNumber(filtered.length)} 条`;
  renderSectionSummary(filtered);

  newsListEl.innerHTML = "";
  _renderListToken += 1;           // invalidate any in-flight render
  const token = _renderListToken;

  if (!filtered.length) {
    const empty = document.createElement("div");
    empty.className = "empty";
    empty.textContent = "当前筛选条件下没有结果。";
    newsListEl.appendChild(empty);
    consumeListStayRestore();
    return;
  }

  renderLoadingNotice(currentFilterLabel(filtered), filtered.length);
  requestAnimationFrame(() => {
    if (token !== _renderListToken) return;   // stale render, abort
    const sorted = sortItemsForList(filtered);
    newsListEl.innerHTML = "";
    if (usesFlatTimelineLayout(state.activeSection)) {
      renderFlatTimeline(sorted);
    } else {
      renderSiteGroups(sorted);
    }
    consumeListStayRestore();
  });
}
function rerenderCurrentView() {
  state.siteGroupsExpanded = false;
  renderSectionTabs();
  renderTimeRangeControl();
  renderModeSwitch();
  renderReadFilterTools();
  renderListSortTools();
  renderSiteFilters();
  renderList();
}

function waytoagiViews(waytoagi) {
  const updates7d = Array.isArray(waytoagi?.updates_7d) ? waytoagi.updates_7d : [];
  const latestDate = waytoagi?.latest_date || (updates7d.length ? updates7d[0].date : null);
  const updatesToday = Array.isArray(waytoagi?.updates_today) && waytoagi.updates_today.length
    ? waytoagi.updates_today
    : (latestDate ? updates7d.filter((u) => u.date === latestDate) : []);
  return { updates7d, updatesToday, latestDate };
}
function renderWaytoagi(waytoagi) {
  if (waytoagiWrapEl) {
    waytoagiWrapEl.hidden = true;
  }
  return;
  const { updates7d, updatesToday, latestDate } = waytoagiViews(waytoagi);
  if (waytoagiTodayBtnEl) waytoagiTodayBtnEl.classList.toggle("active", state.waytoagiMode === "today");
  if (waytoagi7dBtnEl) waytoagi7dBtnEl.classList.toggle("active", state.waytoagiMode === "7d");
  waytoagiUpdatedAtEl.textContent = `更新时间：${fmtTime(waytoagi.generated_at)}`;

  waytoagiMetaEl.innerHTML = "";
  const rootLink = document.createElement("a");
  rootLink.href = waytoagi.root_url || "#";
  rootLink.target = "_blank";
  rootLink.rel = "noopener noreferrer";
  rootLink.textContent = "主页面";
  const historyLink = document.createElement("a");
  historyLink.href = waytoagi.history_url || "#";
  historyLink.target = "_blank";
  historyLink.rel = "noopener noreferrer";
  historyLink.textContent = "历史更新页";
  const todayCount = document.createElement("span");
  todayCount.textContent = `最近更新日(${latestDate || "--"})：${fmtNumber(waytoagi.count_today || updatesToday.length)} 条`;
  const weekCount = document.createElement("span");
  weekCount.textContent = `近 7 日：${fmtNumber(waytoagi.count_7d || updates7d.length)} 条`;
  [rootLink, "·", historyLink, "·", todayCount, "·", weekCount].forEach((part) => {
    if (typeof part === "string") {
      const sep = document.createElement("span");
      sep.textContent = part;
      waytoagiMetaEl.appendChild(sep);
    } else {
      waytoagiMetaEl.appendChild(part);
    }
  });

  waytoagiListEl.innerHTML = "";
  if (waytoagi.has_error) {
    const div = document.createElement("div");
    div.className = "waytoagi-error";
    div.textContent = waytoagi.error || "WaytoAGI 数据加载失败";
    waytoagiListEl.appendChild(div);
    return;
  }

  const updates = state.waytoagiMode === "today" ? updatesToday : updates7d;
  if (!updates.length) {
    const div = document.createElement("div");
    div.className = "waytoagi-empty";
    div.textContent = state.waytoagiMode === "today"
      ? "最近更新日没有更新，可切换到近7日查看。"
      : (waytoagi.warning || "近 7 日没有更新");
    waytoagiListEl.appendChild(div);
    return;
  }

  updates.forEach((u) => {
    const row = document.createElement("a");
    row.className = "waytoagi-item";
    row.href = u.url || "#";
    row.target = "_blank";
    row.rel = "noopener noreferrer";
    const dateEl = document.createElement("span");
    dateEl.className = "d";
    dateEl.textContent = fmtDate(u.date);
    const titleEl = document.createElement("span");
    titleEl.className = "t";
    titleEl.textContent = u.title;
    row.append(dateEl, titleEl);
    waytoagiListEl.appendChild(row);
  });
}
function renderMetric(label, value, tone = "", options = {}) {
  const interactive = typeof options.onClick === "function";
  const node = document.createElement(interactive ? "button" : "div");
  node.className = `health-metric ${interactive ? "health-metric-button" : ""} ${tone}`.trim();
  if (interactive) {
    node.type = "button";
    node.title = options.title || "查看详情";
    node.setAttribute("aria-expanded", String(Boolean(options.expanded)));
    node.addEventListener("click", options.onClick);
  }
  const labelEl = document.createElement("span");
  labelEl.className = "health-label";
  labelEl.textContent = label;
  const valueEl = document.createElement("strong");
  valueEl.textContent = value;
  node.append(labelEl, valueEl);
  return node;
}
function socialdataAuthors() {
  return Array.from(new Set(
    state.itemsAi
      .filter((item) => item.site_id === "socialdata_x")
      .map((item) => String(item.source || "").trim())
      .filter(Boolean),
  )).sort((a, b) => a.localeCompare(b, "en"));
}
function selectSocialdataAuthor(author) {
  state.authorFilter = author;
  state.siteFilter = "socialdata_x";
  state.activeSection = "creator";
  state.boleExpanded = false;
  state.siteGroupsExpanded = false;
  state.xAuthorsExpanded = false;
  renderSectionTabs();
  renderModeSwitch();
  renderSiteFilters();
  renderBolePicks();
  renderList();
  renderSourceHealth();
  document.querySelector(".list-wrap")?.scrollIntoView({ behavior: "smooth", block: "start" });
}
function renderSocialdataAuthorList(authors, itemCount) {
  const panel = document.createElement("section");
  panel.className = "health-author-list";
  const heading = document.createElement("div");
  heading.className = "health-author-list-title";
  heading.textContent = "本轮 X 扫到的博主";
  const meta = document.createElement("div");
  meta.className = "health-author-list-meta";
  meta.textContent = `${fmtNumber(authors.length)} 位博主 · ${fmtNumber(itemCount)} 条入池内容`;
  const list = document.createElement("div");
  list.className = "health-author-list-items";
  authors.forEach((author) => {
    const item = document.createElement("button");
    item.type = "button";
    item.textContent = author;
    item.title = `查看 ${author} 的 X 内容`;
    item.addEventListener("click", () => selectSocialdataAuthor(author));
    list.appendChild(item);
  });
  panel.append(heading, meta, list);
  return panel;
}
function renderIssueList(title, items) {
  const wrap = document.createElement("div");
  wrap.className = "health-issue";
  const titleEl = document.createElement("div");
  titleEl.className = "health-issue-title";
  titleEl.textContent = title;
  const list = document.createElement("ul");
  items.slice(0, 6).forEach((item) => {
    const li = document.createElement("li");
    li.textContent = typeof item === "string" ? item : JSON.stringify(item);
    list.appendChild(li);
  });
  if (items.length > 6) {
    const li = document.createElement("li");
    li.textContent = `另有 ${fmtNumber(items.length - 6)} 项`;
    list.appendChild(li);
  }
  wrap.append(titleEl, list);
  return wrap;
}
function renderSourceHealthSummaryNode(status, errorMessage = "") {
  const node = document.createElement("div");
  node.className = "source-health-summary";
  if (!status) {
    node.classList.add(errorMessage ? "bad" : "warn");
    node.innerHTML = `<strong>${errorMessage ? "源状态异常" : "源状态未生成"}</strong><span>${errorMessage || "等待 source-status.json"}</span>`;
    return node;
  }
  const sites = visibleSourceStatusSites(status);
  const okSites = sites.filter((site) => site.ok).length;
  const partialSites = sites.filter((site) => site.partial).length;
  const failed = failedSourceCount(status);
  const fetched = Number(status.fetched_raw_items || state.totalRaw || status.items_before_topic_filter || 0);
  node.classList.toggle("warn", failed > 0 || partialSites > 0);
  node.innerHTML = `<strong>${fmtNumber(okSites)}/${fmtNumber(sites.length)} 源正常</strong><span>今日采集 ${fmtNumber(fetched)} 条 · 部分完成 ${fmtNumber(partialSites)} · 失败 ${fmtNumber(failed)}</span>`;
  return node;
}
function renderSourceStatusTable(status) {
  if (!sourceStatusTableEl) return;
  sourceStatusTableEl.innerHTML = "";
  const visibleSites = visibleSourceStatusSites(status);
  if (!status || !visibleSites.length) return;

  const rows = visibleSites
    .map((site) => {
      const ai = aiSiteStat(site.site_id);
      const aiCount = Number(ai?.count || 0);
      const rawCount = Number(ai?.raw_count ?? site.item_count ?? 0);
      const scanned = Number(site.item_count || rawCount || 0);
      const ratioBase = rawCount || scanned;
      const ratio = ratioBase ? Math.round((aiCount / ratioBase) * 100) : 0;
      return { ...site, displayName: sourceDisplayName(site), aiCount, rawCount: ratioBase, ratio };
    })
    .sort((a, b) => b.aiCount - a.aiCount || b.rawCount - a.rawCount || String(a.displayName).localeCompare(String(b.displayName), "zh-CN"))
    .slice(0, 12);

  const table = document.createElement("div");
  table.className = "source-table";
  const header = document.createElement("div");
  header.className = "source-table-row source-table-head";
  header.innerHTML = "<span>来源</span><span>AI / 原始</span><span>AI占比</span><span>状态</span>";
  table.appendChild(header);
  rows.forEach((site) => {
    const row = document.createElement("div");
    row.className = "source-table-row";
    const statusText = site.partial ? "部分完成" : (site.ok ? "正常" : "异常");
    const statusTone = site.partial ? "warn" : (site.ok ? "ok" : "bad");
    row.innerHTML = `
      <span>${site.displayName}</span>
      <span>${fmtNumber(site.aiCount)} / ${fmtNumber(site.rawCount)}</span>
      <span>${fmtNumber(site.ratio)}%</span>
      <span class="${statusTone}">${statusText}</span>
    `;
    table.appendChild(row);
  });
  sourceStatusTableEl.appendChild(table);
}
function renderSourceHealth(errorMessage = "") {
  if (!sourceHealthEl) return;
  sourceHealthEl.innerHTML = "";
  if (sourceHealthDetailsEl) sourceHealthDetailsEl.innerHTML = "";
  if (sourceStatusTableEl) sourceStatusTableEl.innerHTML = "";

  const status = state.sourceStatus;
  if (!status) {
    sourceHealthEl.appendChild(renderSourceHealthSummaryNode(null, errorMessage));
    renderSourceStatusPill(errorMessage);
    renderAdvancedSummary();
    setStats();
    return;
  }

  const sites = visibleSourceStatusSites(status);
  const failedSites = visibleFailedSites(status);
  const zeroSites = visibleZeroSites(status);
  const rss = status.rss_opml || {};
  const agentmail = status.agentmail || {};
  const xApi = status.x_api || {};
  const socialdata = status.socialdata || {};
  const emptyAdvanced = Array.isArray(status.empty_advanced_sources) ? status.empty_advanced_sources : [];
  const failedFeeds = visibleFeedList(rss.failed_feeds);
  const skippedFeeds = visibleFeedList(rss.skipped_feeds);
  const replacedFeeds = visibleFeedList(rss.replaced_feeds);
  // Paid sources run on a protected interval. A skipped refresh can still have
  // usable records from the last successful run in today's data pool, so don't
  // hide them behind a misleading "待窗口" status.
  const socialdataLiveCount = Number(socialdata.item_count || 0);
  const socialdataPoolCount = siteAiPoolCount("socialdata_x");
  const socialdataDisplayCount = socialdataLiveCount || socialdataPoolCount;
  const xApiLiveCount = Number(xApi.item_count || 0);
  const xApiPoolCount = siteAiPoolCount("xapi");
  const xApiDisplayCount = xApiLiveCount || xApiPoolCount;
  const xDisplayCount = socialdataDisplayCount + xApiDisplayCount;
  const xAuthors = socialdataAuthors();

  const xMetricValue = xDisplayCount
    ? `已入池 ${fmtNumber(xDisplayCount)}条`
    : socialdata.enabled
    ? (socialdataDisplayCount
      ? "成功"
      : (socialdata.skipped ? "待窗口" : "已连接，暂无匹配"))
    : (xApi.enabled
      ? (xApiDisplayCount
        ? "成功"
        : (xApi.skipped ? "待窗口" : "已连接，暂无匹配"))
      : "未启用");
  const xMetricTone = socialdata.error || xApi.error ? "bad" : (xDisplayCount ? "ok" : (emptyAdvanced.length ? "warn" : ""));

  const metricGrid = document.createElement("div");
  metricGrid.className = "health-grid";
  metricGrid.append(
    renderMetric("内置源", `${fmtNumber(sites.filter((site) => site.ok).length)}/${fmtNumber(sites.length)}`, failedSites.length ? "warn" : "ok"),
    renderMetric("RSS", rss.enabled ? `${fmtNumber(rss.ok_feeds || 0)}/${fmtNumber(rss.effective_feed_total || 0)}` : "未启用"),
    renderMetric("X数据源", xMetricValue, xMetricTone, xAuthors.length ? {
      expanded: state.xAuthorsExpanded,
      title: "查看本轮扫描到的 X 博主",
      onClick: () => {
        state.xAuthorsExpanded = !state.xAuthorsExpanded;
        renderSourceHealth();
      },
    } : {}),
    renderMetric("AgentMail", agentmail.enabled ? `${fmtNumber(agentmail.item_count || 0)}封` : "未启用", agentmail.error ? "bad" : ""),
    renderMetric("失败源", fmtNumber(failedSites.length + failedFeeds.length), failedSites.length || failedFeeds.length ? "bad" : "ok"),
    renderMetric("替换/跳过", `${fmtNumber(replacedFeeds.length)}/${fmtNumber(skippedFeeds.length)}`)
  );
  sourceHealthEl.appendChild(renderSourceHealthSummaryNode(status, errorMessage));
  const detailTarget = sourceHealthDetailsEl || sourceHealthEl;
  detailTarget.appendChild(metricGrid);
  if (state.xAuthorsExpanded && xAuthors.length) {
    detailTarget.appendChild(renderSocialdataAuthorList(xAuthors, socialdataDisplayCount));
  }

  const issues = document.createElement("div");
  issues.className = "health-issues";
  if (failedSites.length) issues.appendChild(renderIssueList("失败站点", failedSites));
  if (zeroSites.length) issues.appendChild(renderIssueList("零结果站点", zeroSites));
  if (emptyAdvanced.length) {
    issues.appendChild(renderIssueList("高级源暂无匹配", emptyAdvanced.map((item) => `${item.site_name || item.site_id} · 已连接，暂无匹配结果`)));
  }
  if (failedFeeds.length) issues.appendChild(renderIssueList("失败 RSS", failedFeeds));
  if (skippedFeeds.length) {
    issues.appendChild(renderIssueList("跳过 RSS", skippedFeeds.map((item) => `${item.feed_url} · ${item.reason || "skipped"}`)));
  }

  if (issues.childElementCount) {
    detailTarget.appendChild(issues);
  } else {
    const ok = document.createElement("div");
    ok.className = "health-ok";
    ok.textContent = "详细源状态正常";
    detailTarget.appendChild(ok);
  }
  renderSourceStatusTable(status);
  renderSourceStatusPill(errorMessage);
  renderAdvancedSummary();
  setStats();
}

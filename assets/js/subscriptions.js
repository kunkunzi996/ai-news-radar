function hiddenWeChatText(value) {
  const text = String(value || "").toLowerCase();
  return Boolean(text) && (
    text.includes("wewe") ||
    text.includes("wechat") ||
    text.includes("mp.weixin") ||
    text.includes("公众号") ||
    text.includes("猫笔刀") ||
    text.includes("maobidao")
  );
}
function isHiddenPlatformId(platformId) {
  return HIDDEN_PLATFORM_IDS.has(String(platformId || "").toLowerCase());
}
function isHiddenSourceId(siteId) {
  return HIDDEN_SOURCE_IDS.has(String(siteId || "").toLowerCase());
}
function isHiddenStatusSite(site) {
  return isHiddenSourceId(site?.site_id) || hiddenWeChatText(`${site?.site_name || ""} ${site?.error || ""}`);
}
function isHiddenSourceConfig(source) {
  const runtimeIds = sourceConfigRuntimeIds(source);
  if (Array.from(runtimeIds).some(isHiddenSourceId)) return true;
  return isHiddenPlatformId(sourceConfigPlatformKey(source)) || hiddenWeChatText(`${source?.id || ""} ${source?.type || ""} ${source?.channel || ""} ${source?.target || ""} ${source?.locator || ""}`);
}
function withHiddenSourcePaused(source) {
  if (!source || !isHiddenSourceConfig(source)) return source;
  return { ...source, enabled: false };
}
function isHiddenItem(item) {
  return isHiddenSourceId(item?.site_id) || isHiddenPlatformId(itemPlatformSection(item));
}
function visibleSections() {
  return SECTION_DEFS.filter((section) => !isHiddenPlatformId(section.id));
}
function visibleSubscriptionPlatforms() {
  return SUBSCRIPTION_PLATFORMS.filter((platform) => !isHiddenPlatformId(platform.id));
}
function visibleSourceConfigFilters() {
  return SOURCE_CONFIG_FILTERS.filter((filter) => !isHiddenPlatformId(filter.id));
}
function visibleSourceConfigSources(sources = []) {
  return (Array.isArray(sources) ? sources : []).filter((source) => !isHiddenSourceConfig(source));
}
function visibleSourceStatusSites(status = state.sourceStatus) {
  return (Array.isArray(status?.sites) ? status.sites : []).filter((site) => !isHiddenStatusSite(site));
}
function visibleFailedSites(status = state.sourceStatus) {
  return (Array.isArray(status?.failed_sites) ? status.failed_sites : []).filter((item) => !isHiddenSourceId(item) && !hiddenWeChatText(item));
}
function visibleZeroSites(status = state.sourceStatus) {
  return (Array.isArray(status?.zero_item_sites) ? status.zero_item_sites : []).filter((item) => !isHiddenSourceId(item) && !hiddenWeChatText(item));
}
function visibleIssueList(issues = []) {
  return (Array.isArray(issues) ? issues : []).filter((issue) => {
    const sourceId = String(issue?.source_id || "");
    const text = `${issue?.id || ""} ${issue?.title || ""} ${(issue?.details || []).join(" ")}`;
    return !isHiddenSourceId(sourceId) && !hiddenWeChatText(text);
  });
}
function visibleFeedList(items = []) {
  return (Array.isArray(items) ? items : []).filter((item) => !hiddenWeChatText(typeof item === "string" ? item : JSON.stringify(item || {})));
}
function visibleItemList(items = []) {
  return (Array.isArray(items) ? items : []).filter((item) => !isHiddenItem(item));
}
function visibleSiteStats(stats = []) {
  return (Array.isArray(stats) ? stats : []).filter((site) => !isHiddenStatusSite(site));
}
function setSubscriptionManagerStatus(message, tone = "") {
  if (!subscriptionManagerStatusEl) return;
  subscriptionManagerStatusEl.textContent = message || "";
  subscriptionManagerStatusEl.className = tone || "";
}
function subscriptionPlatformDef(platformId = state.subscriptionPlatform) {
  const platforms = visibleSubscriptionPlatforms();
  return platforms.find((item) => item.id === platformId) || platforms[0] || SUBSCRIPTION_PLATFORMS[0];
}
function youtubeFeedUrl(channelId) {
  const clean = String(channelId || "").trim();
  return clean ? `https://www.youtube.com/feeds/videos.xml?channel_id=${clean}` : "";
}
function youtubeChannelIdFromFeedUrl(url) {
  try {
    const parsed = new URL(String(url || "").trim());
    return parsed.searchParams.get("channel_id") || "";
  } catch {
    return "";
  }
}
function normalizeSourceConfigToken(value) {
  const base = String(value || "subscription")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9\u4e00-\u9fa5]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 48);
  return base || "subscription";
}
function sourceRecordMatchesPlatform(source, platform) {
  if (!source || !platform) return false;
  const runtimeIds = sourceConfigRuntimeIds(source);
  if (platform.runtimeId && !runtimeIds.has(platform.runtimeId)) return false;
  if (platform.type && String(source.type || "") !== platform.type) return false;
  if (platform.channel) {
    const hay = `${source.id || ""} ${source.channel || ""} ${source.target || ""} ${source.locator || ""}`.toLowerCase();
    const channel = platform.channel.toLowerCase();
    if (channel.includes("抖音") && !(hay.includes("douyin") || hay.includes("抖音"))) return false;
    if (channel.includes("小红书") && !(hay.includes("xhs") || hay.includes("xiaohongshu") || hay.includes("小红书"))) return false;
    if (channel.includes("公众号") && !(hay.includes("wewe") || hay.includes("wechat") || hay.includes("公众号"))) return false;
    if (channel.includes("github") && !(hay.includes("github") || hay.includes("release"))) return false;
  }
  return true;
}
function subscriptionSourceRecordId(platform, locator, name) {
  const key = normalizeSourceConfigToken(
    platform.id === "github"
      ? githubRepoSlug(locator) || name
      : locator || name
  );
  const raw = `${platform.idPrefix || platform.id}_${key}`;
  return raw.slice(0, 72);
}
function githubRepoSlug(value) {
  const raw = String(value || "").trim();
  if (!raw) return "";
  const apiMatch = raw.match(/github\.com\/repos\/([^/]+\/[^/]+)\/releases/i);
  if (apiMatch) return apiMatch[1];
  const webMatch = raw.match(/github\.com\/([^/]+\/[^/#?]+)/i);
  if (webMatch) return webMatch[1];
  const repoMatch = raw.match(/^([^/\s]+\/[^/\s]+)$/);
  return repoMatch ? repoMatch[1] : "";
}
function githubReleaseApiUrl(value) {
  const raw = String(value || "").trim();
  if (!raw) return "";
  if (/^https:\/\/api\.github\.com\/repos\/[^/]+\/[^/]+\/releases/i.test(raw)) return raw;
  const slug = githubRepoSlug(raw);
  return slug ? `https://api.github.com/repos/${slug}/releases` : raw;
}
function ensureSourceConfigForSubscriptions() {
  if (!state.sourceConfig) state.sourceConfig = loadSourceConfigDraft();
  if (!Array.isArray(state.sourceConfig.sources)) state.sourceConfig.sources = [];
  return state.sourceConfig.sources;
}
function bilibiliSourceRecord() {
  let sources = ensureSourceConfigForSubscriptions();
  let record = sources.find((source) => source.id === "bilibili_dynamic_sources" || source.type === "bilibili_dynamic");
  if (!record) {
    record = {
      id: "bilibili_dynamic_sources",
      name: "B站动态",
      type: "bilibili_dynamic",
      enabled: true,
      channel: "B站动态",
      target: "",
      locator: "",
      env: "BILIBILI_DYNAMIC_UIDS / BILIBILI_DYNAMIC_SOURCE_NAMES",
      notes: "同一渠道统一维护；UID 和名称用英文逗号分隔，可继续追加 UP 主。",
    };
    sources = [...sources, record];
    state.sourceConfig.sources = sources;
  }
  return record;
}
function bilibiliSubscriptionMembers() {
  const record = bilibiliSourceRecord();
  const names = splitSourceConfigList(record.target);
  const locators = splitSourceConfigList(record.locator);
  return locators.map((locator, index) => ({
    id: locator,
    name: names[index] || `Bilibili ${locator}`,
    locator,
  }));
}
function setBilibiliSubscriptionMembers(members) {
  const clean = [];
  const seen = new Set();
  members.forEach((member) => {
    const locator = String(member.locator || "").trim();
    const name = String(member.name || "").trim();
    if (!locator || seen.has(locator)) return;
    seen.add(locator);
    clean.push({ name: name || `Bilibili ${locator}`, locator });
  });
  const record = bilibiliSourceRecord();
  record.target = clean.map((member) => member.name).join(",");
  record.locator = clean.map((member) => member.locator).join(",");
  record.enabled = true;
  record.name = "B站动态";
  record.type = "bilibili_dynamic";
  record.channel = "B站动态";
  record.env = "BILIBILI_DYNAMIC_UIDS / BILIBILI_DYNAMIC_SOURCE_NAMES";
  record.notes = "同一渠道统一维护；可在订阅成员面板里新增或删除 UP 主。";
  state.sourceConfigSelectedId = record.id;
  saveSourceConfigDraft("B站订阅成员已更新，点“保存订阅”后写入采集配置");
  renderSourceConfig();
}
function youtubeSubscriptionMembers() {
  return (state.youtubeSubscriptions || []).map((item) => ({
    id: item.channel_id || youtubeChannelIdFromFeedUrl(item.xml_url),
    name: item.title || item.channel_id || "YouTube 频道",
    locator: item.channel_id || youtubeChannelIdFromFeedUrl(item.xml_url),
    htmlUrl: item.html_url || "",
    xmlUrl: item.xml_url || youtubeFeedUrl(item.channel_id),
  })).filter((item) => item.locator);
}
function sourceRecordSubscriptionMembers(platform) {
  const sources = ensureSourceConfigForSubscriptions();
  return sources
    .filter((source) => sourceRecordMatchesPlatform(source, platform))
    .map((source) => ({
      id: source.locator || source.id,
      sourceId: source.id,
      name: source.target || source.name || source.id,
      locator: source.locator || "",
      type: source.type || platform.type || "rss",
      channel: source.channel || platform.channel || "",
    }))
    .filter((item) => item.locator);
}
function sourceRecordForSubscriptionMember(platform, member) {
  const locator = platform.id === "github"
    ? githubReleaseApiUrl(member.locator)
    : String(member.locator || "").trim();
  const name = String(member.name || "").trim();
  return {
    id: member.sourceId || subscriptionSourceRecordId(platform, locator, name),
    name,
    type: platform.type || "rss",
    enabled: true,
    channel: platform.channel || platform.label,
    target: name,
    locator,
    env: platform.env || "",
    notes: platform.notes || "",
  };
}
function setSourceRecordSubscriptionMembers(platform, members) {
  const sources = ensureSourceConfigForSubscriptions();
  const matched = sources.filter((source) => sourceRecordMatchesPlatform(source, platform));
  const keep = sources.filter((source) => !sourceRecordMatchesPlatform(source, platform));
  const seen = new Set();
  const next = [];
  members.forEach((member) => {
    const locator = String(member.locator || "").trim();
    const name = String(member.name || "").trim();
    if (!locator || !name || seen.has(locator)) return;
    seen.add(locator);
    next.push(sourceRecordForSubscriptionMember(platform, { ...member, name, locator }));
  });
  const seedIds = new Set(sourceConfigSeedSources().map((source) => source.id));
  const nextSeedIds = new Set(next.filter((source) => seedIds.has(source.id)).map((source) => source.id));
  const deleted = new Set(state.sourceConfig.deleted_source_ids || []);
  matched.forEach((source) => {
    if (!seedIds.has(source.id)) return;
    if (nextSeedIds.has(source.id)) {
      deleted.delete(source.id);
    } else {
      deleted.add(source.id);
    }
  });
  state.sourceConfig.deleted_source_ids = Array.from(deleted);
  state.sourceConfig.sources = [...keep, ...next];
  if (next.length) state.sourceConfigSelectedId = next[next.length - 1].id;
  saveSourceConfigDraft(`${platform.label}订阅成员已更新，点“保存成员”后写入采集配置`);
  renderSourceConfig();
}
function currentSubscriptionMembers() {
  const platform = subscriptionPlatformDef();
  if (platform.storage === "youtube") return youtubeSubscriptionMembers();
  if (platform.storage === "bilibili") return bilibiliSubscriptionMembers();
  return sourceRecordSubscriptionMembers(platform);
}
function renderSubscriptionPlatformTabs() {
  if (!subscriptionPlatformTabsEl) return;
  subscriptionPlatformTabsEl.innerHTML = "";
  if (isHiddenPlatformId(state.subscriptionPlatform)) {
    state.subscriptionPlatform = subscriptionPlatformDef()?.id || "bilibili";
  }
  visibleSubscriptionPlatforms().forEach((platform) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "subscription-platform-tab";
    button.dataset.platform = platform.id;
    if (state.subscriptionPlatform === platform.id) button.classList.add("active");
    button.textContent = platform.label;
    button.addEventListener("click", () => {
      state.subscriptionPlatform = platform.id;
      clearSubscriptionMemberForm();
      renderSubscriptionManager();
      if (platform.id === "youtube") {
        loadYoutubeSubscriptions().catch(() => {});
      }
    });
    subscriptionPlatformTabsEl.appendChild(button);
  });
}
function renderSubscriptionMembers() {
  if (!subscriptionMembersEl) return;
  subscriptionMembersEl.innerHTML = "";
  const members = currentSubscriptionMembers();
  if (!members.length) {
    const empty = document.createElement("div");
    empty.className = "subscription-empty";
    empty.textContent = "当前渠道还没有订阅成员。";
    subscriptionMembersEl.appendChild(empty);
    return;
  }
  members.forEach((member) => {
    const card = document.createElement("article");
    card.className = "subscription-member";
    const main = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = member.name;
    const meta = document.createElement("span");
    meta.textContent = member.locator;
    main.append(title, meta);
    const actions = document.createElement("div");
    actions.className = "subscription-member-card-actions";
    const editBtn = document.createElement("button");
    editBtn.type = "button";
    editBtn.className = "tool-btn";
    editBtn.textContent = "编辑";
    editBtn.addEventListener("click", () => {
      subscriptionMemberNameEl.value = member.name || "";
      subscriptionMemberLocatorEl.value = member.locator || "";
      if (subscriptionMemberHomeUrlEl) subscriptionMemberHomeUrlEl.value = member.htmlUrl || "";
      if (member.sourceId && subscriptionMemberFormEl) subscriptionMemberFormEl.dataset.sourceId = member.sourceId;
      subscriptionMemberSubmitBtnEl.textContent = "保存成员";
    });
    const removeBtn = document.createElement("button");
    removeBtn.type = "button";
    removeBtn.className = "tool-btn danger";
    removeBtn.textContent = "删除";
    removeBtn.addEventListener("click", () => {
      removeSubscriptionMember(member.locator).catch((err) => {
        setSubscriptionManagerStatus(`删除失败：${err.message}`, "bad");
      });
    });
    actions.append(editBtn, removeBtn);
    card.append(main, actions);
    subscriptionMembersEl.appendChild(card);
  });
}
function renderSubscriptionMemberFormHints() {
  const platform = subscriptionPlatformDef();
  if (subscriptionNameLabelEl) subscriptionNameLabelEl.textContent = platform.nameLabel;
  if (subscriptionLocatorLabelEl) subscriptionLocatorLabelEl.textContent = platform.locatorLabel;
  if (subscriptionMemberLocatorEl) subscriptionMemberLocatorEl.placeholder = platform.locatorPlaceholder;
  if (subscriptionMemberSyncBtnEl) {
    const showSync = platform.id === "wechat";
    subscriptionMemberSyncBtnEl.hidden = !showSync;
    subscriptionMemberSyncBtnEl.style.display = showSync ? "" : "none";
  }
  if (subscriptionHomeUrlWrapEl) {
    const showHomeUrl = Boolean(platform.homeUrl);
    subscriptionHomeUrlWrapEl.hidden = !showHomeUrl;
    subscriptionHomeUrlWrapEl.style.display = showHomeUrl ? "" : "none";
  }
}
function renderSubscriptionManager() {
  if (!subscriptionMemberFormEl) return;
  renderSubscriptionPlatformTabs();
  renderSubscriptionMemberFormHints();
  renderSubscriptionMembers();
}
function clearSubscriptionMemberForm() {
  if (subscriptionMemberNameEl) subscriptionMemberNameEl.value = "";
  if (subscriptionMemberLocatorEl) subscriptionMemberLocatorEl.value = "";
  if (subscriptionMemberHomeUrlEl) subscriptionMemberHomeUrlEl.value = "";
  if (subscriptionMemberFormEl) delete subscriptionMemberFormEl.dataset.sourceId;
  if (subscriptionMemberSubmitBtnEl) subscriptionMemberSubmitBtnEl.textContent = "新增成员";
}
async function loadYoutubeSubscriptions(options = {}) {
  const silent = Boolean(options.silent);
  if (!canUseLocalBackend()) return;
  try {
    const res = await fetch("./api/subscriptions/youtube", { headers: { Accept: "application/json" }, cache: "no-store" });
    const payload = await res.json().catch(() => ({}));
    if (!res.ok || payload.ok === false) throw new Error(payload.error || `HTTP ${res.status}`);
    state.youtubeSubscriptions = Array.isArray(payload.subscriptions) ? payload.subscriptions : [];
    if (!silent) renderSubscriptionManager();
    renderLocalOpsStatus(state.localOpsStatus);
  } catch (err) {
    if (!silent) setSubscriptionManagerStatus(`油管订阅读取失败：${err.message}`, "bad");
  }
}
async function saveYoutubeSubscriptions() {
  if (!canUseLocalBackend()) throw new Error(localBackendUnavailableMessage());
  const subscriptions = youtubeSubscriptionMembers().map((member) => ({
    title: member.name,
    channel_id: member.locator,
    xml_url: youtubeFeedUrl(member.locator),
    html_url: member.htmlUrl || "",
  }));
  const res = await fetch("./api/subscriptions/youtube", {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ subscriptions }),
  });
  const payload = await res.json().catch(() => ({}));
  if (!res.ok || payload.ok === false) throw new Error(payload.error || `HTTP ${res.status}`);
  state.youtubeSubscriptions = Array.isArray(payload.subscriptions) ? payload.subscriptions : subscriptions;
  return payload;
}
async function syncWeweRssSubscriptions() {
  const platform = subscriptionPlatformDef();
  if (platform.id !== "wechat") return;
  if (!canUseLocalBackend()) {
    setSubscriptionManagerStatus(localBackendUnavailableMessage(), "warn");
    return;
  }
  setSourceConfigButton(subscriptionMemberSyncBtnEl, "同步中...", true);
  setSubscriptionManagerStatus("正在读取 WeWe RSS 已订阅公众号...", "warn");
  try {
    const res = await fetch("./api/wewe-rss/feeds", { headers: { Accept: "application/json" }, cache: "no-store" });
    const payload = await res.json().catch(() => ({}));
    if (!res.ok || payload.ok === false) throw new Error(payload.error || `HTTP ${res.status}`);
    const feeds = Array.isArray(payload.feeds) ? payload.feeds : [];
    if (!feeds.length) {
      setSubscriptionManagerStatus("WeWe RSS 里还没有公众号；先去后台添加公众号，再回来同步。", "warn");
      return;
    }
    const existingByLocator = new Map(sourceRecordSubscriptionMembers(platform).map((member) => [member.locator, member]));
    const members = feeds.map((feed) => {
      const locator = String(feed.id || "").trim();
      const existing = existingByLocator.get(locator);
      return {
        name: String(feed.name || locator).trim(),
        locator,
        sourceId: existing?.sourceId || "",
      };
    }).filter((member) => member.name && member.locator);
    setSourceRecordSubscriptionMembers(platform, members);
    clearSubscriptionMemberForm();
    renderSubscriptionManager();
    setSubscriptionManagerStatus(`已从 WeWe RSS 同步 ${fmtNumber(members.length)} 个公众号，正在写入本地配置...`, "warn");
    await writeSourceConfigToLocalServer({
      button: subscriptionMemberSyncBtnEl,
      successLabel: "已同步",
      idleLabel: "同步 WeWe RSS",
      syncForm: false,
    });
    setSubscriptionManagerStatus(`已同步并保存 ${fmtNumber(members.length)} 个公众号，点“读取结果”后出现在看板。`, "ok");
  } catch (err) {
    setSubscriptionManagerStatus(`同步 WeWe RSS 失败：${err.message}`, "bad");
  } finally {
    restoreSourceConfigButton(subscriptionMemberSyncBtnEl, "同步 WeWe RSS");
  }
}
async function saveSubscriptionMembers() {
  const platform = subscriptionPlatformDef();
  if (platform.storage === "youtube") {
    await saveYoutubeSubscriptions();
    setSubscriptionManagerStatus("油管订阅已写入 feeds/follow.opml，点“读取结果”后生效", "ok");
    renderSubscriptionManager();
    return;
  }
  await writeSourceConfigToLocalServer({
    button: subscriptionMemberSubmitBtnEl,
    successLabel: "已保存",
    idleLabel: "新增成员",
    syncForm: false,
  });
  setSubscriptionManagerStatus(`${platform.label}订阅已写入 sources.config.json；抖音/小红书先点启动采集，再点读取结果`, "ok");
}
function upsertSubscriptionMember(member) {
  const platform = subscriptionPlatformDef();
  const locator = String(member.locator || "").trim();
  const name = String(member.name || "").trim();
  if (!locator || !name) {
    setSubscriptionManagerStatus("名称和账号 ID 都要填写", "bad");
    return false;
  }
  const sourceId = subscriptionMemberFormEl?.dataset?.sourceId || "";
  if (platform.storage === "youtube") {
    const existing = youtubeSubscriptionMembers().filter((item) => item.locator !== locator);
    state.youtubeSubscriptions = [
      ...existing.map((item) => ({
        title: item.name,
        channel_id: item.locator,
        xml_url: youtubeFeedUrl(item.locator),
        html_url: item.htmlUrl || "",
      })),
      {
        title: name,
        channel_id: locator,
        xml_url: youtubeFeedUrl(locator),
        html_url: String(member.htmlUrl || "").trim(),
      },
    ];
  } else if (platform.storage === "bilibili") {
    const existing = bilibiliSubscriptionMembers().filter((item) => item.locator !== locator);
    setBilibiliSubscriptionMembers([...existing, { name, locator }]);
  } else {
    const existing = sourceRecordSubscriptionMembers(platform)
      .filter((item) => item.locator !== locator && item.sourceId !== sourceId);
    setSourceRecordSubscriptionMembers(platform, [...existing, { name, locator, sourceId }]);
  }
  clearSubscriptionMemberForm();
  renderSubscriptionManager();
  setSubscriptionManagerStatus("成员已更新，点“保存成员”写入本地配置", "warn");
  return true;
}
async function removeSubscriptionMember(locator) {
  const platform = subscriptionPlatformDef();
  const cleanLocator = String(locator || "").trim();
  if (!cleanLocator) return;
  if (platform.storage === "youtube") {
    state.youtubeSubscriptions = youtubeSubscriptionMembers()
      .filter((item) => item.locator !== cleanLocator)
      .map((item) => ({
        title: item.name,
        channel_id: item.locator,
        xml_url: youtubeFeedUrl(item.locator),
        html_url: item.htmlUrl || "",
      }));
  } else if (platform.storage === "bilibili") {
    setBilibiliSubscriptionMembers(bilibiliSubscriptionMembers().filter((item) => item.locator !== cleanLocator));
  } else {
    setSourceRecordSubscriptionMembers(
      platform,
      sourceRecordSubscriptionMembers(platform).filter((item) => item.locator !== cleanLocator),
    );
  }
  clearSubscriptionMemberForm();
  renderSubscriptionManager();
  await saveSubscriptionMembers();
  setSubscriptionManagerStatus("成员已删除并保存，点“读取结果”后生效", "ok");
}
function isSubscriptionSection(sectionId) {
  if (isHiddenPlatformId(sectionId)) return false;
  return sectionId === "creator" || sectionId === "read" || ["douyin", "xiaohongshu", "bilibili", "youtube", "github"].includes(sectionId);
}
function itemPlatformSection(item) {
  const siteId = String(item?.site_id || "").toLowerCase();
  const urlHay = [item?.url, item?.primary_url].filter(Boolean).join(" ").toLowerCase();
  const hay = [
    item?.site_name,
    item?.source,
    item?.url,
    item?.primary_url,
    item?.title,
    item?.title_zh,
    item?.title_en,
  ].filter(Boolean).join(" ").toLowerCase();
  if (siteId === "bilibili_dynamic" || hay.includes("bilibili") || hay.includes("b站")) return "bilibili";
  if (siteId === "mediacrawler_douyin" || siteId === "tikhub_douyin" || hay.includes("douyin") || hay.includes("抖音")) return "douyin";
  if (siteId === "mediacrawler_xhs" || siteId === "tikhub_xiaohongshu" || hay.includes("xiaohongshu") || hay.includes("小红书")) return "xiaohongshu";
  if (
    siteId === "wewe_rss" ||
    siteId === "maobidao_wudaolu_backup" ||
    hay.includes("mp.weixin.qq.com") ||
    hay.includes("wewe") ||
    hay.includes("公众号") ||
    hay.includes("猫笔刀") ||
    hay.includes("maobidao")
  ) return "wechat";
  if (hay.includes("youtube") || hay.includes("youtu.be") || hay.includes("油管")) return "youtube";
  if (siteId.includes("github") || urlHay.includes("github.com")) return "github";
  return "";
}
function subscriptionModeItems() {
  const seeded = state.creatorItemsAll.length ? state.creatorItemsAll : state.creatorItemsAi;
  const candidates = modeItems();
  const out = [];
  const seen = new Set();
  const add = (item) => {
    if (!item) return;
    if (isHiddenItem(item)) return;
    const key = itemIdentityKey(item);
    if (seen.has(key)) return;
    seen.add(key);
    out.push(item);
  };
  (Array.isArray(seeded) ? seeded : []).forEach(add);
  (Array.isArray(candidates) ? candidates : []).filter(isSubscriptionItem).forEach(add);
  return out;
}
function itemSections(item) {
  const hay = itemHaystack(item);
  const contentHay = [
    item.title,
    item.title_zh,
    item.title_en,
    item.title_original,
    item.source,
    item.site_name,
    item.site_id,
    ...(Array.isArray(item.ai_signals) ? item.ai_signals : []),
  ].filter(Boolean).join(" ").toLowerCase();
  const sections = new Set();
  const label = item.ai_label || "";
  const source = `${item.source || ""} ${item.site_name || ""}`.toLowerCase();
  const hasExplicitModelTerm = matchesAny(contentHay, [
    /gpt[-\s]?\d|claude|gemini|grok|llama|qwen|deepseek|mistral|kimi\s?k\d|glm|gemma|模型|model|weights|权重|多模态|视频生成|diffusion|sora|seedance|llm|大模型/,
  ]);
  const looksLikeToolOrProduct = matchesAny(hay, [
    /skill|copilot|codex|cli|api|sdk|dashboard|workflow|tool|工具|助手|应用|插件|工作流|支付宝|浏览器|搜索/,
  ]);

  if (
    hasExplicitModelTerm ||
    (label === "model_release" && !looksLikeToolOrProduct)
  ) sections.add("models");

  if (
    label === "ai_product_update" ||
    label === "agent_workflow" ||
    label === "robotics" ||
    matchesAny(hay, [
      /app|product|agent|workflow|siri|copilot|chatgpt|perplexity|runway|suno|支付宝|产品|应用|智能体|机器人|浏览器|搜索|助手|生成工具|办公|教育/,
    ])
  ) sections.add("products");

  if (
    label === "developer_tool" ||
    label === "developer_tooling" ||
    label === "infra_compute" ||
    matchesAny(hay, [
      /github|cursor|codex|copilot|openrouter|api|sdk|mcp|cli|framework|inference|推理|开发者|开源|代码|编程|算力|芯片|nvidia|cloud|部署|benchmarking|token/,
    ])
  ) sections.add("devtools");

  if (
    item.site_id === "hackernews" ||
    item.site_id === "zeli" ||
    source.includes("hacker news") ||
    source.includes("hackernews") ||
    source.includes("hn algolia")
  ) sections.add("hn");

  if (
    label === "industry_business" ||
    matchesAny(hay, [
      /funding|raised|ipo|acquire|acquisition|lawsuit|regulation|policy|white house|pentagon|nvidia|salesforce|meta|microsoft|融资|收购|上市|监管|政策|裁员|估值|债券|芯片|公司|行业|政府|五角大楼|白宫/,
    ])
  ) sections.add("industry");

  if (
    label === "research_paper" ||
    matchesAny(hay, [
      /paper|arxiv|research|benchmark|eval|dataset|lmsys|rdi|berkeley|huggingface daily papers|论文|研究|基准|评测|数据集|训练|k-means|speculative decoding/,
    ])
  ) sections.add("research");

  if (isSubscriptionItem(item)) {
    sections.add("creator");
    const platformSection = itemPlatformSection(item);
    if (platformSection) sections.add(platformSection);
  }

  if (
    item.site_id === "waytoagi" ||
    item.site_id === "followbuilders" ||
    item.site_id === "aibase" ||
    source.includes("it之家") ||
    source.includes("36氪") ||
    source.includes("掘金") ||
    source.includes("readhub") ||
    source.includes("aibase") ||
    source.includes("公众号") ||
    source.includes("宝玉") ||
    source.includes("小互") ||
    source.includes("ayi") ||
    matchesAny(hay, [
      /waytoagi|社区|公众号|阿里|通义|千问|智谱|kimi|月之暗面|minimax|字节|火山|百度|腾讯|华为|蚂蚁|讯飞|国内|中文|开源中国|少数派|虎嗅/,
    ])
  ) sections.add("community");

  if (!sections.size) sections.add("industry");
  return sections;
}
function itemMatchesSection(item, sectionId) {
  return itemSections(item).has(sectionId);
}
function sectionBadgeLabel(sectionId) {
  return SECTION_BY_ID[sectionId]?.short || "栏目";
}
function readTrackingKey(item) {
  const keys = strongReadIdentityKeys(item);
  return keys.size ? Array.from(keys)[0] : readTitleFallbackKey(item);
}
function strongReadIdentityKeys(item) {
  const keys = new Set();
  if (!item) return keys;
  const url = item.url || item.primary_url;
  if (url) keys.add(`url:${url}`);
  if (item.id) keys.add(`id:${item.id}`);
  if (item.bilibili_dynamic_id) keys.add(`bilibili_dynamic:${item.bilibili_dynamic_id}`);
  if (item.bilibili_opus_id) keys.add(`bilibili_opus:${item.bilibili_opus_id}`);
  return keys;
}
function readTitleFallbackKey(item) {
  const title = item?.title_zh || item?.title || item?.title_en || item?.title_original;
  const normalized = normalizedEventText(title);
  if (!normalized || normalized.length < 8) return "";
  if (["分享动态", "转发动态", "动态", "直播回放"].includes(normalized)) return "";
  return `title:${normalized.slice(0, 34)}`;
}
function readTrackingKeys(item) {
  const keys = strongReadIdentityKeys(item);
  const primary = readTrackingKey(item);
  if (primary) keys.add(primary);
  return keys;
}
function loadReadItemIds() {
  try {
    const raw = window.localStorage.getItem(READ_ITEMS_STORAGE_KEY);
    const arr = raw ? JSON.parse(raw) : [];
    return new Set(Array.isArray(arr) ? arr : []);
  } catch {
    return new Set();
  }
}
function persistReadItemIds() {
  try {
    window.localStorage.setItem(READ_ITEMS_STORAGE_KEY, JSON.stringify(Array.from(state.readItemIds)));
  } catch {
    // localStorage 不可用时，只影响跨刷新保留；当前页面操作仍可继续。
  }
}
function isItemRead(item) {
  for (const key of readTrackingKeys(item)) {
    if (state.readItemIds.has(key)) return true;
  }
  return false;
}
function toggleItemRead(item) {
  const keys = readTrackingKeys(item);
  if (!keys.size) return;
  if (isItemRead(item)) {
    keys.forEach((key) => state.readItemIds.delete(key));
  } else {
    keys.forEach((key) => state.readItemIds.add(key));
  }
  persistReadItemIds();
  rerenderCurrentView();
}
function isSubscriptionItem(item) {
  if (isHiddenItem(item)) return false;
  const siteId = String(item?.site_id || "").toLowerCase();
  const hay = `${item?.site_name || ""} ${item?.source || ""} ${item?.url || ""}`.toLowerCase();
  const isPersonalRss = siteId === "opmlrss" || siteId.startsWith("opmlrss:");
  const isTrackedPlatformUrl =
    hay.includes("bilibili") ||
    hay.includes("youtube") ||
    hay.includes("youtu.be") ||
    hay.includes("douyin") ||
    hay.includes("xiaohongshu") ||
    hay.includes("maobidao") ||
    hay.includes("mp.weixin.qq.com") ||
    hay.includes("wewe") ||
    hay.includes("b站") ||
    hay.includes("油管") ||
    hay.includes("抖音") ||
    hay.includes("小红书") ||
    hay.includes("公众号") ||
    hay.includes("猫笔刀");
  return SUBSCRIPTION_SITE_IDS.has(siteId) || (isPersonalRss && isTrackedPlatformUrl);
}

function sourceConfigSeedSources() {
  return [
    {
      id: "official_ai_sources",
      name: "官方一手源包",
      type: "official_ai",
      enabled: false,
      channel: "官方一手源",
      target: "OpenAI / Anthropic / Google / Hugging Face / GitHub",
      locator: "scripts/update_news.py --source-scope all_sources",
      env: "",
      notes: "项目内置官方 RSS/Atom/API/Page 源；当前默认输出不启用，需要 all_sources 才会抓。",
    },
    {
      id: "curated_ai_media_sources",
      name: "精选AI媒体包",
      type: "curated_media",
      enabled: false,
      channel: "精选媒体",
      target: "The Decoder / TechCrunch / The Verge / MarkTechPost / VentureBeat / AI News / Claude Code",
      locator: "scripts/update_news.py --source-scope all_sources",
      env: "",
      notes: "项目自带英文 AI 媒体源；当前默认输出不启用，避免默认看板噪音过多。",
    },
    {
      id: "aihot",
      name: "AI HOT",
      type: "aihot",
      enabled: false,
      channel: "AI站点",
      target: "AI HOT",
      locator: "https://ai-bot.cn/daily-ai-news/",
      env: "",
      notes: "内置中文 AI 资讯站点源；默认停用，可作为全源模式补充。",
    },
    {
      id: "aibreakfast",
      name: "AI Breakfast",
      type: "aibreakfast",
      enabled: false,
      channel: "日报",
      target: "AI Breakfast",
      locator: "RSS / Newsletter",
      env: "",
      notes: "内置英文 AI 日报源；默认停用。",
    },
    {
      id: "aihubtoday",
      name: "AIHubToday",
      type: "aihubtoday",
      enabled: false,
      channel: "AI站点",
      target: "AIHubToday",
      locator: "AIHubToday",
      env: "",
      notes: "内置 AI 站点源；默认停用。",
    },
    {
      id: "aibase",
      name: "AIbase",
      type: "aibase",
      enabled: false,
      channel: "AI站点",
      target: "AIbase",
      locator: "AIbase",
      env: "",
      notes: "内置中文 AI 站点源；默认停用。",
    },
    {
      id: "bestblogs",
      name: "BestBlogs",
      type: "bestblogs",
      enabled: false,
      channel: "博客",
      target: "BestBlogs",
      locator: "BestBlogs",
      env: "",
      notes: "内置博客聚合源；默认停用。",
    },
    {
      id: "followbuilders",
      name: "Follow Builders",
      type: "followbuilders",
      enabled: false,
      channel: "Builders/X",
      target: "Follow Builders",
      locator: "RSS / curated list",
      env: "",
      notes: "内置 Builders 相关信号源；默认停用。",
    },
    {
      id: "waytoagi",
      name: "WaytoAGI",
      type: "waytoagi",
      enabled: false,
      channel: "中文社区",
      target: "WaytoAGI",
      locator: "data/waytoagi-7d.json",
      env: "",
      notes: "社区信号源；页面已有专门区块，配置目录里也展示出来。",
    },
    {
      id: "hackernews",
      name: "Hacker News",
      type: "hackernews",
      enabled: false,
      channel: "HN热议",
      target: "Hacker News AI stories",
      locator: "HN API",
      env: "",
      notes: "内置 HN AI 关键词源；当前默认输出不启用。",
    },
    {
      id: "techurls",
      name: "TechURLs",
      type: "techurls",
      enabled: false,
      channel: "聚合",
      target: "TechURLs",
      locator: "TechURLs",
      env: "",
      notes: "内置技术聚合源；默认停用。",
    },
    {
      id: "buzzing",
      name: "Buzzing",
      type: "buzzing",
      enabled: false,
      channel: "聚合",
      target: "Buzzing",
      locator: "Buzzing",
      env: "",
      notes: "内置聚合源；默认停用。",
    },
    {
      id: "iris",
      name: "Iris",
      type: "iris",
      enabled: false,
      channel: "聚合",
      target: "Iris",
      locator: "Iris",
      env: "",
      notes: "内置聚合源；默认停用。",
    },
    {
      id: "tophub",
      name: "TopHub",
      type: "tophub",
      enabled: false,
      channel: "聚合",
      target: "TopHub AI / tech topics",
      locator: "TopHub",
      env: "",
      notes: "内置热榜聚合源；不会再被误归类为我的订阅。",
    },
    {
      id: "zeli",
      name: "Zeli",
      type: "zeli",
      enabled: false,
      channel: "聚合",
      target: "Zeli",
      locator: "Zeli",
      env: "",
      notes: "内置聚合源；默认停用。",
    },
    {
      id: "newsnow",
      name: "NewsNow",
      type: "newsnow",
      enabled: false,
      channel: "聚合",
      target: "NewsNow",
      locator: "NewsNow",
      env: "",
      notes: "内置聚合源；默认停用。",
    },
    {
      id: "opmlrss",
      name: "OPML/RSS 订阅包",
      type: "opmlrss",
      enabled: false,
      channel: "RSS/OPML",
      target: "feeds/follow.opml",
      locator: "feeds/follow.opml",
      env: "",
      notes: "本地 OPML/RSS 订阅入口；默认输出曾收窄，需后续接入配置后再按需启用。",
    },
    {
      id: "xapi",
      name: "X API",
      type: "xapi",
      enabled: false,
      channel: "高级 API",
      target: "X / Twitter",
      locator: "X API",
      env: "X_BEARER_TOKEN",
      notes: "高级源，需要外部凭证；不要把 token 写进仓库或导出的公开文件。",
    },
    {
      id: "socialdata_x",
      name: "SocialData X 搜索",
      type: "socialdata_x",
      enabled: false,
      channel: "高级 API",
      target: "X / Twitter 搜索",
      locator: "SocialData API",
      env: "SOCIALDATA_API_KEY",
      notes: "高级源，需要外部凭证；默认停用。",
    },
    {
      id: "tikhub_social_sources",
      name: "TikHub 抖音/小红书",
      type: "tikhub_douyin",
      enabled: false,
      channel: "高级 API",
      target: "抖音 / 小红书",
      locator: "TikHub API",
      env: "TIKHUB_API_KEY",
      notes: "高级平台源，需要外部服务和凭证；当前本机优先用 MediaCrawler JSONL 桥。",
    },
    {
      id: "agentmail",
      name: "AgentMail",
      type: "rss",
      enabled: false,
      channel: "邮件/RSS",
      target: "AgentMail",
      locator: "AgentMail",
      env: "AGENTMAIL_*",
      notes: "高级邮件源；默认停用。",
    },
    {
      id: "bilibili_dynamic_sources",
      name: "B站动态",
      type: "bilibili_dynamic",
      enabled: true,
      channel: "B站动态",
      target: "Koji杨远骋at十字路口,技术爬爬虾",
      locator: "505301413,316183842",
      env: "BILIBILI_DYNAMIC_UIDS / BILIBILI_DYNAMIC_SOURCE_NAMES",
      notes: "同一渠道统一维护；UID 和名称用英文逗号分隔，可继续追加 UP 主。",
    },
    {
      id: "mediacrawler_douyin_simon",
      name: "Simon林",
      type: "mediacrawler_jsonl",
      enabled: false,
      channel: "抖音",
      target: "Simon林",
      locator: "E:\\AI-news-reader\\MediaCrawler-local-test\\output\\douyin\\jsonl\\creator_contents_2026-07-01.jsonl",
      env: "MEDIACRAWLER_DOUYIN_ENABLED / MEDIACRAWLER_DOUYIN_JSONL / MEDIACRAWLER_DOUYIN_SOURCE_NAME",
      notes: "Radar 只读本地 JSONL，不启动 MediaCrawler 或 Chrome。",
    },
    {
      id: "mediacrawler_xhs_chenbaoyi",
      name: "陈抱一",
      type: "mediacrawler_jsonl",
      enabled: false,
      channel: "小红书",
      target: "陈抱一",
      locator: "E:\\AI-news-reader\\MediaCrawler-local-test\\output\\xhs\\jsonl\\creator_contents_2026-07-01.jsonl",
      env: "MEDIACRAWLER_XHS_ENABLED / MEDIACRAWLER_XHS_JSONL / MEDIACRAWLER_XHS_SOURCE_NAME",
      notes: "Radar 只读本地 JSONL，不保存 xsec_token 或浏览器 profile。",
    },
    {
      id: "github_foundation_sunshine",
      name: "AlkaidLab/foundation-sunshine",
      type: "github_release",
      enabled: true,
      channel: "GitHub Release",
      target: "AlkaidLab/foundation-sunshine",
      locator: "https://api.github.com/repos/AlkaidLab/foundation-sunshine/releases",
      env: "",
      notes: "只追踪 release，不追踪普通 commit。",
    },
  ];
}
function freshSourceConfig() {
  return {
    version: "1.0",
    catalog_version: SOURCE_CONFIG_CATALOG_VERSION,
    mode: "refresh-script-config",
    how_to_apply: "保存为项目根目录 sources.config.json 后运行 scripts/update_news.py；也可用 --source-config 指定路径。",
    updated_at: new Date().toISOString(),
    deleted_source_ids: [],
    sources: sourceConfigSeedSources(),
  };
}
function normalizeSourceConfig(payload) {
  const rawSources = Array.isArray(payload?.sources) ? payload.sources : [];
  const updatedAt = String(payload?.updated_at || "").trim();
  const sources = rawSources
    .filter((source) => source && typeof source === "object")
    .filter((source) => !RETIRED_SOURCE_CONFIG_IDS.has(String(source.id || "").trim()))
    .map((source, index) => ({
      id: String(source.id || `source_${index + 1}`).trim() || `source_${index + 1}`,
      name: String(source.name || source.title || "").trim() || `未命名信源 ${index + 1}`,
      type: String(source.type || "rss").trim() || "rss",
      enabled: source.enabled !== false,
      channel: String(source.channel || source.category || "").trim(),
      target: String(source.target || source.account || source.repo || "").trim(),
      locator: String(source.locator || source.url || source.feed_url || source.path || "").trim(),
      env: String(source.env || source.env_vars || "").trim(),
      notes: String(source.notes || source.description || "").trim(),
    }))
    .map(withHiddenSourcePaused);
  return {
    version: String(payload?.version || "1.0"),
    catalog_version: String(payload?.catalog_version || ""),
    mode: "refresh-script-config",
    how_to_apply: String(payload?.how_to_apply || "保存为项目根目录 sources.config.json 后运行 scripts/update_news.py；也可用 --source-config 指定路径。"),
    updated_at: Number.isFinite(Date.parse(updatedAt)) ? updatedAt : new Date().toISOString(),
    deleted_source_ids: Array.isArray(payload?.deleted_source_ids)
      ? Array.from(new Set(payload.deleted_source_ids.map((id) => String(id || "").trim()).filter(Boolean)))
      : [],
    sources,
  };
}
function sourceConfigUpdatedMs(config) {
  const ms = Date.parse(config?.updated_at || "");
  return Number.isFinite(ms) ? ms : 0;
}
function splitSourceConfigList(value) {
  return String(value || "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}
function uniqueSourceConfigList(values) {
  return Array.from(new Set(values.filter(Boolean)));
}
function consolidateBilibiliSourceRecords(config) {
  const sources = Array.isArray(config.sources) ? config.sources : [];
  const bilibiliRecords = sources.filter((source) => (
    source.type === "bilibili_dynamic" ||
    source.id === "bilibili_dynamic_sources" ||
    source.id.startsWith("bilibili_")
  ));
  if (bilibiliRecords.length <= 1 && bilibiliRecords[0]?.id === "bilibili_dynamic_sources") {
    return { config, changed: false };
  }
  if (!bilibiliRecords.length) return { config, changed: false };

  const locators = uniqueSourceConfigList(bilibiliRecords.flatMap((source) => splitSourceConfigList(source.locator)));
  const targets = uniqueSourceConfigList(bilibiliRecords.flatMap((source) => (
    splitSourceConfigList(source.target).length
      ? splitSourceConfigList(source.target)
      : splitSourceConfigList(source.name)
  )));
  const firstIndex = sources.findIndex((source) => bilibiliRecords.some((record) => record.id === source.id));
  const merged = {
    id: "bilibili_dynamic_sources",
    name: "B站动态",
    type: "bilibili_dynamic",
    enabled: bilibiliRecords.some((source) => source.enabled !== false),
    channel: "B站动态",
    target: targets.join(","),
    locator: locators.join(","),
    env: "BILIBILI_DYNAMIC_UIDS / BILIBILI_DYNAMIC_SOURCE_NAMES",
    notes: "同一渠道统一维护；UID 和名称用英文逗号分隔，可继续追加 UP 主。",
  };
  const withoutBilibili = sources.filter((source) => !bilibiliRecords.some((record) => record.id === source.id));
  withoutBilibili.splice(Math.max(0, firstIndex), 0, merged);
  return {
    config: {
      ...config,
      sources: withoutBilibili,
    },
    changed: true,
  };
}
function mergeSourceConfigWithSeed(config) {
  const inputUpdatedAt = String(config?.updated_at || "").trim();
  const hasInputUpdatedAt = Number.isFinite(Date.parse(inputUpdatedAt));
  const normalizedBase = normalizeSourceConfig(config);
  const { config: normalized, changed: consolidated } = consolidateBilibiliSourceRecords(normalizedBase);
  const seedSources = sourceConfigSeedSources();
  const seedIds = new Set(seedSources.map((source) => source.id));
  const hadDeletedIds = Array.isArray(config?.deleted_source_ids);
  const deletedSeedIds = new Set(normalized.deleted_source_ids.filter((id) => seedIds.has(id)));
  const existingById = new Map(normalized.sources.map((source) => [source.id, source]));
  if (!hadDeletedIds && normalized.catalog_version === SOURCE_CONFIG_CATALOG_VERSION) {
    seedSources.forEach((seed) => {
      if (!existingById.has(seed.id)) deletedSeedIds.add(seed.id);
    });
  }
  const seedOrdered = seedSources
    .filter((seed) => existingById.has(seed.id) || !deletedSeedIds.has(seed.id))
    .map((seed) => existingById.get(seed.id) || seed);
  const customSources = normalized.sources.filter((source) => !seedIds.has(source.id));
  const mergedSources = [...seedOrdered, ...customSources];
  const changed =
    consolidated ||
    normalized.catalog_version !== SOURCE_CONFIG_CATALOG_VERSION ||
    normalized.deleted_source_ids.length !== deletedSeedIds.size ||
    mergedSources.length !== normalized.sources.length ||
    mergedSources.some((source, index) => source.id !== normalized.sources[index]?.id);
  normalized.deleted_source_ids = Array.from(deletedSeedIds);
  normalized.catalog_version = SOURCE_CONFIG_CATALOG_VERSION;
  normalized.sources = mergedSources;
  if (changed && !hasInputUpdatedAt) normalized.updated_at = new Date().toISOString();
  return { config: normalized, changed };
}
function loadSourceConfigDraft() {
  try {
    const raw = window.localStorage.getItem(SOURCE_CONFIG_STORAGE_KEY);
    if (raw) {
      const { config, changed } = mergeSourceConfigWithSeed(JSON.parse(raw));
      if (changed) {
        window.localStorage.setItem(SOURCE_CONFIG_STORAGE_KEY, JSON.stringify(config, null, 2));
      }
      return config;
    }
  } catch {
    // Fall back to the built-in current-source draft.
  }
  return freshSourceConfig();
}
function saveSourceConfigDraft(message = "高级配置草稿已保存") {
  if (!state.sourceConfig) return;
  state.sourceConfig.sources = (state.sourceConfig.sources || []).map(withHiddenSourcePaused);
  state.sourceConfig.updated_at = new Date().toISOString();
  window.localStorage.setItem(SOURCE_CONFIG_STORAGE_KEY, JSON.stringify(state.sourceConfig, null, 2));
  setSourceConfigStatus(message, "ok");
}
function setSourceConfigStatus(message, tone = "") {
  if (!sourceConfigStatusEl) return;
  sourceConfigStatusEl.textContent = message || "";
  sourceConfigStatusEl.className = `source-config-status${tone ? ` ${tone}` : ""}`;
}
function sourceConfigJsonText() {
  return JSON.stringify(state.sourceConfig || freshSourceConfig(), null, 2);
}
function syncSourceConfigJson() {
  return sourceConfigJsonText();
}
function sourceConfigRuntimeIds(source) {
  const rawId = String(source?.id || "").toLowerCase();
  const type = String(source?.type || "").toLowerCase();
  const channel = String(source?.channel || "").toLowerCase();
  const target = String(source?.target || "").toLowerCase();
  const locator = String(source?.locator || "").toLowerCase();
  const hay = `${rawId} ${type} ${channel} ${target} ${locator}`;
  const ids = new Set();
  if (rawId === "aihot" || type === "aihot") ids.add("aihot");
  if (rawId.includes("github_foundation_sunshine") || type === "github_release") ids.add("github_foundation_sunshine_releases");
  if (rawId.includes("maobidao_wudaolu")) ids.add("maobidao_wudaolu_backup");
  if (type === "wewe_rss" || rawId.startsWith("wewe_rss") || hay.includes("wewe_rss") || hay.includes("wewe rss")) ids.add("wewe_rss");
  if (type === "bilibili_dynamic" || hay.includes("bilibili") || hay.includes("b站")) ids.add("bilibili_dynamic");
  if (type === "mediacrawler_jsonl" && (hay.includes("xhs") || hay.includes("xiaohongshu") || hay.includes("小红书"))) ids.add("mediacrawler_xhs");
  if (type === "mediacrawler_jsonl" && (hay.includes("douyin") || hay.includes("抖音"))) ids.add("mediacrawler_douyin");
  if (rawId === "opmlrss" || hay.includes("follow.opml") || channel.includes("opml")) ids.add("opmlrss");
  if (type === "xapi") ids.add("xapi");
  if (type === "socialdata_x") ids.add("socialdata_x");
  if (type === "tikhub_douyin") ids.add("tikhub_douyin");
  return ids;
}
function localOpsIssues() {
  const issues = state.localOpsStatus?.source_status?.maintenance_issues;
  return visibleIssueList(issues);
}
function issueSeverityForSource(source) {
  const runtimeIds = sourceConfigRuntimeIds(source);
  const matched = localOpsIssues().filter((issue) => runtimeIds.has(String(issue.source_id || "")) || String(issue.id || "").includes(String(source?.id || "")));
  if (matched.some((issue) => issue.severity === "bad")) return "bad";
  if (matched.length) return "warn";
  return "";
}
function sourceConfigPlatformKey(source) {
  const hay = `${source?.id || ""} ${source?.type || ""} ${source?.channel || ""} ${source?.target || ""} ${source?.locator || ""}`.toLowerCase();
  if (hay.includes("公众号") || hay.includes("wewe") || hay.includes("wechat")) return "wechat";
  if (hay.includes("小红书") || hay.includes("xhs") || hay.includes("xiaohongshu")) return "xhs";
  if (hay.includes("抖音") || hay.includes("douyin")) return "douyin";
  if (hay.includes("b站") || hay.includes("bilibili")) return "bilibili";
  if (hay.includes("github")) return "github";
  if (hay.includes("rss") || hay.includes("opml") || String(source?.type || "") === "rss") return "rss";
  return "other";
}
function sourceConfigMatchesFilter(source) {
  if (isHiddenSourceConfig(source)) return false;
  const filter = state.sourceConfigFilter || "all";
  if (filter === "all") return true;
  if (filter === "enabled") return source.enabled !== false;
  if (filter === "attention") return Boolean(issueSeverityForSource(source));
  return sourceConfigPlatformKey(source) === filter;
}
function selectSourceConfigByRuntimeId(runtimeId) {
  const sources = visibleSourceConfigSources(state.sourceConfig?.sources || []);
  const source = sources.find((item) => sourceConfigRuntimeIds(item).has(runtimeId));
  if (!source) return false;
  state.sourceConfigFilter = "all";
  state.sourceConfigSelectedId = source.id;
  renderSourceConfig();
  sourceConfigFormEl?.scrollIntoView({ behavior: "smooth", block: "center" });
  setSourceConfigStatus(`已定位到 ${source.name}`, "ok");
  return true;
}
async function loadSourceConfigFromLocalServer() {
  if (!sourceConfigFormEl) return;
  if (!canUseLocalBackend()) {
    setSourceConfigStatus(localBackendUnavailableMessage(), "warn");
    return;
  }
  try {
    const draftConfig = loadSourceConfigDraft();
    const res = await fetch("./api/source-config", {
      headers: { Accept: "application/json" },
      cache: "no-store",
    });
    if (res.status === 404) return;
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const payload = await res.json();
    if (!payload?.config) return;
    const { config } = mergeSourceConfigWithSeed(payload.config);
    if (sourceConfigUpdatedMs(draftConfig) > sourceConfigUpdatedMs(config)) {
      state.sourceConfig = draftConfig;
      state.sourceConfigSelectedId = draftConfig.sources[0]?.id || "";
      setSourceConfigStatus("已保留较新的浏览器高级配置；点“保存高级配置”后同步到采集配置", "warn");
      renderSourceConfig();
      return;
    }
    state.sourceConfig = config;
    state.sourceConfigSelectedId = config.sources[0]?.id || "";
    saveSourceConfigDraft("已读取 sources.config.json");
    renderSourceConfig();
  } catch {
    // The plain static server has no local write API; keep using localStorage.
  }
}
async function writeSourceConfigToLocalServer(options = {}) {
  const button = options.button || null;
  const successLabel = options.successLabel || "已保存";
  const idleLabel = options.idleLabel || "保存高级配置";
  const syncForm = options.syncForm !== false;
  if (syncForm && !saveSourceConfigFormToState("高级配置草稿已保存", false)) {
    setSourceConfigButton(button, "保存失败", false);
    restoreSourceConfigButton(button, idleLabel);
    throw new Error("source config form is invalid");
  }
  if (!state.sourceConfig) state.sourceConfig = loadSourceConfigDraft();
  state.sourceConfig.updated_at = new Date().toISOString();
  syncSourceConfigJson();
  if (!canUseLocalBackend()) {
    throw new Error(localBackendUnavailableMessage());
  }
  setSourceConfigButton(button, "保存中...", true);
  setSourceConfigStatus("正在同步当前高级信源配置...", "warn");
  try {
    const res = await fetch("./api/source-config", {
      method: "POST",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
      },
      body: sourceConfigJsonText(),
    });
    const payload = await res.json().catch(() => ({}));
    if (!res.ok || payload.ok === false) {
      throw new Error(payload.error || `HTTP ${res.status}`);
    }
    const purgedTotal = Object.values(payload.purged_items || {}).reduce((sum, value) => {
      const n = Number(value);
      return sum + (Number.isFinite(n) ? n : 0);
    }, 0);
    const purgedNote = purgedTotal > 0 ? `；已清理 ${purgedTotal} 条已删除信源的历史数据` : "";
    saveSourceConfigDraft(`已同步 ${payload.path || "sources.config.json"}，共 ${payload.source_count || 0} 个信源${purgedNote}`);
    renderSourceConfig();
    setSourceConfigButton(button, successLabel, true);
    restoreSourceConfigButton(button, idleLabel);
    return payload;
  } catch (err) {
    setSourceConfigButton(button, "保存失败", true);
    restoreSourceConfigButton(button, idleLabel);
    setSourceConfigStatus(`保存失败：请用 scripts/local_server.py 启动本地后台（${err.message}）`, "bad");
    throw err;
  }
}
async function saveSourceConfigForCollection(message = "已保存，后续采集会按当前信源执行") {
  if (!saveSourceConfigFormToState(message, false)) return;
  try {
    await writeSourceConfigToLocalServer({
      button: sourceConfigSaveBtnEl,
      successLabel: "已保存",
      idleLabel: "保存高级配置",
      syncForm: false,
    });
    setSourceConfigStatus(message, "ok");
  } catch {
    setSourceConfigStatus("已保存到浏览器草稿；本地后台不可用时不会同步到采集配置", "warn");
  }
}
function selectedSourceConfig() {
  const sources = visibleSourceConfigSources(state.sourceConfig?.sources || []);
  return sources.find((source) => source.id === state.sourceConfigSelectedId) || sources[0] || null;
}
function fillSourceConfigForm(source) {
  if (!sourceConfigFormEl) return;
  const item = source || {
    id: "",
    name: "",
    type: "rss",
    enabled: true,
    channel: "",
    target: "",
    locator: "",
    env: "",
    notes: "",
  };
  sourceConfigIdEl.value = item.id || "";
  sourceConfigNameEl.value = item.name || "";
  sourceConfigTypeEl.value = item.type || "rss";
  sourceConfigChannelEl.value = item.channel || "";
  sourceConfigTargetEl.value = item.target || "";
  sourceConfigLocatorEl.value = item.locator || "";
  sourceConfigEnvEl.value = item.env || "";
  sourceConfigNotesEl.value = item.notes || "";
  sourceConfigEnabledEl.checked = item.enabled !== false;
}
function renderSourceConfigList() {
  if (!sourceConfigListEl || !state.sourceConfig) return;
  sourceConfigListEl.innerHTML = "";
  const sources = visibleSourceConfigSources(state.sourceConfig.sources || []).filter(sourceConfigMatchesFilter);
  if (!sources.length) {
    const empty = document.createElement("div");
    empty.className = "source-config-empty";
    empty.textContent = state.sourceConfigFilter === "attention" ? "当前没有需要维护的信源" : "暂无信源";
    sourceConfigListEl.appendChild(empty);
    return;
  }
  sources.forEach((source) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "source-config-source";
    if (source.id === state.sourceConfigSelectedId) button.classList.add("active");
    const severity = issueSeverityForSource(source);
    if (severity) button.classList.add(severity === "bad" ? "bad" : "warn");
    const title = document.createElement("strong");
    title.textContent = source.name;
    const meta = document.createElement("span");
    const statusText = severity ? (severity === "bad" ? "需处理" : "需关注") : (source.enabled === false ? "停用" : "启用");
    meta.textContent = [source.channel || source.type, statusText].filter(Boolean).join(" · ");
    button.append(title, meta);
    button.addEventListener("click", () => {
      state.sourceConfigSelectedId = source.id;
      fillSourceConfigForm(source);
      renderSourceConfigList();
    });
    sourceConfigListEl.appendChild(button);
  });
}
function renderSourceConfigSummary() {
  if (!sourceConfigSummaryEl || !state.sourceConfig) return;
  const sources = visibleSourceConfigSources(state.sourceConfig.sources || []);
  const total = sources.length;
  const enabled = sources.filter((source) => source.enabled !== false).length;
  const attention = sources.filter((source) => issueSeverityForSource(source)).length;
  sourceConfigSummaryEl.textContent = attention
    ? `${fmtNumber(enabled)}/${fmtNumber(total)} 启用 · ${fmtNumber(attention)} 需维护`
    : `${fmtNumber(enabled)}/${fmtNumber(total)} 启用`;
}
function renderSourceConfigFilters() {
  if (!sourceConfigFiltersEl || !state.sourceConfig) return;
  sourceConfigFiltersEl.innerHTML = "";
  const sources = visibleSourceConfigSources(state.sourceConfig.sources || []);
  visibleSourceConfigFilters().forEach((filter) => {
    const count = sources.filter((source) => {
      if (filter.id === "all") return true;
      if (filter.id === "enabled") return source.enabled !== false;
      if (filter.id === "attention") return Boolean(issueSeverityForSource(source));
      return sourceConfigPlatformKey(source) === filter.id;
    }).length;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "source-config-filter";
    if ((state.sourceConfigFilter || "all") === filter.id) button.classList.add("active");
    button.textContent = `${filter.label} ${fmtNumber(count)}`;
    button.addEventListener("click", () => {
      state.sourceConfigFilter = filter.id;
      renderSourceConfig();
    });
    sourceConfigFiltersEl.appendChild(button);
  });
}
function renderSourceConfig() {
  if (!sourceConfigFormEl) return;
  if (!state.sourceConfig) state.sourceConfig = loadSourceConfigDraft();
  if (isHiddenPlatformId(state.sourceConfigFilter)) state.sourceConfigFilter = "all";
  const sources = visibleSourceConfigSources(state.sourceConfig.sources || []);
  if (!state.sourceConfigSelectedId || !sources.some((source) => source.id === state.sourceConfigSelectedId)) {
    state.sourceConfigSelectedId = sources[0]?.id || "";
  }
  renderSourceConfigSummary();
  renderSourceConfigFilters();
  renderSourceConfigList();
  fillSourceConfigForm(selectedSourceConfig());
  syncSourceConfigJson();
  renderSubscriptionManager();
}
function sourceConfigIdFromName(name) {
  const base = String(name || "source")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9\u4e00-\u9fa5]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 48) || "source";
  const existing = new Set((state.sourceConfig?.sources || []).map((source) => source.id));
  let out = base;
  let i = 2;
  while (existing.has(out)) {
    out = `${base}_${i}`;
    i += 1;
  }
  return out;
}
function formSourceConfigRecord() {
  const name = sourceConfigNameEl.value.trim();
  const id = sourceConfigIdEl.value.trim() || sourceConfigIdFromName(name);
  return {
    id,
    name,
    type: sourceConfigTypeEl.value || "rss",
    enabled: Boolean(sourceConfigEnabledEl.checked),
    channel: sourceConfigChannelEl.value.trim(),
    target: sourceConfigTargetEl.value.trim(),
    locator: sourceConfigLocatorEl.value.trim(),
    env: sourceConfigEnvEl.value.trim(),
    notes: sourceConfigNotesEl.value.trim(),
  };
}
function upsertSourceConfigRecord(record) {
  saveSourceConfigRecordToState(record, "高级配置草稿已保存", true);
}
function saveSourceConfigFormToState(message = "高级配置草稿已保存", shouldRender = true) {
  if (!sourceConfigFormEl) return true;
  return saveSourceConfigRecordToState(formSourceConfigRecord(), message, shouldRender);
}
function saveSourceConfigRecordToState(record, message = "高级配置草稿已保存", shouldRender = true) {
  const safeRecord = withHiddenSourcePaused(record);
  if (!record.name) {
    setSourceConfigStatus("名称不能为空", "bad");
    return false;
  }
  if (!state.sourceConfig) state.sourceConfig = freshSourceConfig();
  const sources = state.sourceConfig.sources || [];
  const index = sources.findIndex((source) => source.id === safeRecord.id);
  if (index >= 0) {
    sources[index] = safeRecord;
  } else {
    sources.push(safeRecord);
  }
  state.sourceConfig.sources = sources;
  state.sourceConfigSelectedId = safeRecord.id;
  saveSourceConfigDraft(message);
  if (shouldRender) {
    renderSourceConfig();
  } else {
    syncSourceConfigJson();
  }
  return true;
}
function syncSourceConfigFormDraft() {
  if (!sourceConfigFormEl || !state.sourceConfigSelectedId) return;
  const record = withHiddenSourcePaused(formSourceConfigRecord());
  if (!record.name) return;
  if (!state.sourceConfig) state.sourceConfig = freshSourceConfig();
  const sources = state.sourceConfig.sources || [];
  const index = sources.findIndex((source) => source.id === record.id);
  if (index >= 0) {
    sources[index] = record;
  } else {
    sources.push(record);
  }
  state.sourceConfig.sources = sources.map(withHiddenSourcePaused);
  state.sourceConfigSelectedId = record.id;
  state.sourceConfig.updated_at = new Date().toISOString();
  window.localStorage.setItem(SOURCE_CONFIG_STORAGE_KEY, JSON.stringify(state.sourceConfig, null, 2));
  renderSourceConfigSummary();
  renderSourceConfigList();
  syncSourceConfigJson();
  setSourceConfigStatus("高级配置草稿已更新，点“保存高级配置”或“读取结果”后生效", "warn");
}
function addSourceConfigRecord() {
  if (!state.sourceConfig) state.sourceConfig = freshSourceConfig();
  const id = sourceConfigIdFromName("new_source");
  const record = {
    id,
    name: "新信源",
    type: "rss",
    enabled: true,
    channel: "RSS",
    target: "",
    locator: "",
    env: "",
    notes: "",
  };
  state.sourceConfig.sources.push(record);
  state.sourceConfigSelectedId = id;
  saveSourceConfigDraft("已新增高级信源配置草稿");
  renderSourceConfig();
}
function deleteSourceConfigRecord() {
  if (!state.sourceConfigSelectedId || !state.sourceConfig) return;
  const seedIds = new Set(sourceConfigSeedSources().map((source) => source.id));
  if (seedIds.has(state.sourceConfigSelectedId)) {
    const deleted = new Set(state.sourceConfig.deleted_source_ids || []);
    deleted.add(state.sourceConfigSelectedId);
    state.sourceConfig.deleted_source_ids = Array.from(deleted);
  }
  state.sourceConfig.sources = (state.sourceConfig.sources || []).filter((source) => source.id !== state.sourceConfigSelectedId);
  state.sourceConfigSelectedId = state.sourceConfig.sources[0]?.id || "";
  saveSourceConfigDraft("已从高级配置删除；点“保存高级配置”后采集会按当前配置执行");
  renderSourceConfig();
}
function resetSourceConfigDraft() {
  state.sourceConfig = freshSourceConfig();
  state.sourceConfigSelectedId = state.sourceConfig.sources[0]?.id || "";
  saveSourceConfigDraft("已恢复为当前默认高级配置草稿");
  renderSourceConfig();
}

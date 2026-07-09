const state = {
  itemsAi: [],
  itemsAll: [],
  itemsAllRaw: [],
  creatorItemsAi: [],
  creatorItemsAll: [],
  creatorWindowDays: 7,
  creatorTimeScope: "rolling_window",
  statsAi: [],
  totalAi: 0,
  totalRaw: 0,
  totalAllMode: 0,
  timeScope: "rolling_window",
  timeRangeFilter: "all",
  sourceScope: "all_sources",
  allDedup: true,
  allDataLoaded: false,
  allDataUrl: "data/latest-24h-all.json",
  allDataPromise: null,
  siteFilter: "",
  authorFilter: "",
  query: "",
  mode: "all",
  waytoagiMode: "today",
  waytoagiData: null,
  sourceStatus: null,
  generatedAt: null,
  dataBaseUrl: "",
  dataSourceMode: "local",
  dataSourceFallback: false,
  dataSourceError: "",
  dailyBrief: null,
  storiesMerged: null,
  storiesDataUrl: "data/stories-merged.json",
  activeSection: "creator",
  boleView: "timeline",
  boleExpanded: false,
  listSort: "time",
  sourceTypeFilter: "",
  signalLevelFilter: "",
  siteGroupsExpanded: false,
  xAuthorsExpanded: false,
  sourceConfig: null,
  sourceConfigSelectedId: "",
  sourceConfigFilter: "all",
  onlineSourceConfig: { sources: [] },
  onlineSourceSelectedId: "",
  onlineSourceDirty: false,
  subscriptionPlatform: "bilibili",
  youtubeSubscriptions: [],
  localOpsStatus: null,
  localOpsPollTimer: null,
  refreshProgressPollTimer: null,
  refreshProgress: null,
  collectionProgressActive: false,
  oneClickActive: false,
  readItemIds: new Set(),
};

const statsEl = document.getElementById("stats");
const siteSelectEl = document.getElementById("siteSelect");
const sitePillsEl = document.getElementById("sitePills");
const newsListEl = document.getElementById("newsList");
const updatedAtEl = document.getElementById("updatedAt");
const dataSourcePillEl = document.getElementById("dataSourcePill");
const sourceStatusPillEl = document.getElementById("sourceStatusPill");
const stickySummaryTextEl = document.getElementById("stickySummaryText");
const searchInputEl = document.getElementById("searchInput");
const resultCountEl = document.getElementById("resultCount");
const listTitleEl = document.getElementById("listTitle");
const itemTpl = document.getElementById("itemTpl");
const modeAiBtnEl = document.getElementById("modeAiBtn");
const modeAllBtnEl = document.getElementById("modeAllBtn");
const timeRangeSelectEl = document.getElementById("timeRangeSelect");
const modeHintEl = document.getElementById("modeHint");
const allDedupeWrapEl = document.getElementById("allDedupeWrap");
const allDedupeToggleEl = document.getElementById("allDedupeToggle");
const allDedupeLabelEl = document.getElementById("allDedupeLabel");
const advancedSummaryEl = document.getElementById("advancedSummary");
const sourceHealthEl = document.getElementById("sourceHealth");
const sourceHealthDetailsEl = document.getElementById("sourceHealthDetails");
const sourceStatusTableEl = document.getElementById("sourceStatusTable");
const sectionSelectEl = document.getElementById("sectionSelect");
const sourceTypeSelectEl = document.getElementById("sourceTypeSelect");
const signalLevelSelectEl = document.getElementById("signalLevelSelect");

const waytoagiWrapEl = document.querySelector(".waytoagi-wrap");
const waytoagiUpdatedAtEl = document.getElementById("waytoagiUpdatedAt");
const waytoagiMetaEl = document.getElementById("waytoagiMeta");
const waytoagiListEl = document.getElementById("waytoagiList");
const waytoagiTodayBtnEl = document.getElementById("waytoagiTodayBtn");
const waytoagi7dBtnEl = document.getElementById("waytoagi7dBtn");
const coverageStripEl = document.getElementById("coverageStrip");
const bolePicksListEl = document.getElementById("bolePicksList");
const bolePicksMetaEl = document.getElementById("bolePicksMeta");
const bolePicksWrapEl = document.getElementById("bolePicksWrap");
const boleViewToggleEl = document.getElementById("boleViewToggle");
const boleHotBtnEl = document.getElementById("boleHotBtn");
const boleTimelineBtnEl = document.getElementById("boleTimelineBtn");
const sectionTabsEl = document.getElementById("sectionTabs");
const sectionSummaryEl = document.getElementById("sectionSummary");
const topStoriesTitleEl = document.getElementById("topStoriesTitle");
const listSortToolsEl = document.getElementById("listSortTools");
const sourceConfigSummaryEl = document.getElementById("sourceConfigSummary");
const sourceConfigFiltersEl = document.getElementById("sourceConfigFilters");
const sourceConfigListEl = document.getElementById("sourceConfigList");
const sourceConfigFormEl = document.getElementById("sourceConfigForm");
const sourceConfigIdEl = document.getElementById("sourceConfigId");
const sourceConfigNameEl = document.getElementById("sourceConfigName");
const sourceConfigTypeEl = document.getElementById("sourceConfigType");
const sourceConfigChannelEl = document.getElementById("sourceConfigChannel");
const sourceConfigTargetEl = document.getElementById("sourceConfigTarget");
const sourceConfigLocatorEl = document.getElementById("sourceConfigLocator");
const sourceConfigEnvEl = document.getElementById("sourceConfigEnv");
const sourceConfigNotesEl = document.getElementById("sourceConfigNotes");
const sourceConfigEnabledEl = document.getElementById("sourceConfigEnabled");
const sourceConfigSaveBtnEl = document.getElementById("sourceConfigSaveBtn");
const sourceConfigAddBtnEl = document.getElementById("sourceConfigAddBtn");
const sourceConfigDeleteBtnEl = document.getElementById("sourceConfigDeleteBtn");
const sourceConfigResetBtnEl = document.getElementById("sourceConfigResetBtn");
const oneClickCollectBtnEl = document.getElementById("oneClickCollectBtn");
const sourceConfigRefreshBtnEl = document.getElementById("sourceConfigRefreshBtn");
const sourceConfigCheckBtnEl = document.getElementById("sourceConfigCheckBtn");
const localServerRestartBtnEl = document.getElementById("localServerRestartBtn");
const sourceCollectionScopeSelectEl = document.getElementById("sourceCollectionScopeSelect");
const sourceConfigStatusEl = document.getElementById("sourceConfigStatus");
const localOpsStatusEl = document.getElementById("localOpsStatus");
const localOpsProgressEl = document.getElementById("localOpsProgress");
const localOpsSummaryEl = document.getElementById("localOpsSummary");
const localOpsCollectorsEl = document.getElementById("localOpsCollectors");
const localOpsIssuesEl = document.getElementById("localOpsIssues");
const onlineSourceStatusEl = document.getElementById("onlineSourceStatus");
const onlineSourceListEl = document.getElementById("onlineSourceList");
const onlineSourceFormEl = document.getElementById("onlineSourceForm");
const onlineSourceTypeEl = document.getElementById("onlineSourceType");
const onlineSourceNameLabelEl = document.getElementById("onlineSourceNameLabel");
const onlineSourceLocatorLabelEl = document.getElementById("onlineSourceLocatorLabel");
const onlineSourceNameEl = document.getElementById("onlineSourceName");
const onlineSourceLocatorEl = document.getElementById("onlineSourceLocator");
const onlineSourceNotesEl = document.getElementById("onlineSourceNotes");
const onlineSourceEnabledEl = document.getElementById("onlineSourceEnabled");
const onlineSourceSaveBtnEl = document.getElementById("onlineSourceSaveBtn");
const onlineSourceClearBtnEl = document.getElementById("onlineSourceClearBtn");
const onlineSourceSyncBtnEl = document.getElementById("onlineSourceSyncBtn");
const subscriptionManagerStatusEl = document.getElementById("subscriptionManagerStatus");
const subscriptionPlatformTabsEl = document.getElementById("subscriptionPlatformTabs");
const subscriptionMembersEl = document.getElementById("subscriptionMembers");
const subscriptionMemberFormEl = document.getElementById("subscriptionMemberForm");
const subscriptionMemberNameEl = document.getElementById("subscriptionMemberName");
const subscriptionMemberLocatorEl = document.getElementById("subscriptionMemberLocator");
const subscriptionMemberHomeUrlEl = document.getElementById("subscriptionMemberHomeUrl");
const subscriptionHomeUrlWrapEl = document.getElementById("subscriptionHomeUrlWrap");
const subscriptionNameLabelEl = document.getElementById("subscriptionNameLabel");
const subscriptionLocatorLabelEl = document.getElementById("subscriptionLocatorLabel");
const subscriptionMemberSubmitBtnEl = document.getElementById("subscriptionMemberSubmitBtn");
const subscriptionMemberClearBtnEl = document.getElementById("subscriptionMemberClearBtn");
const subscriptionMemberSyncBtnEl = document.getElementById("subscriptionMemberSyncBtn");

const SOURCE_KINDS = {
  official_ai: { label: "官方", tone: "official" },
  curated_media: { label: "精选媒体", tone: "aihub" },
  aihot: { label: "AI HOT", tone: "hot" },
  aibreakfast: { label: "日报", tone: "newsletter" },
  followbuilders: { label: "Builders/X", tone: "builders" },
  xapi: { label: "X API", tone: "builders" },
  socialdata_x: { label: "X 搜索", tone: "builders" },
  tikhub_douyin: { label: "抖音", tone: "creator" },
  tikhub_xiaohongshu: { label: "小红书", tone: "creator" },
  bilibili_dynamic: { label: "B站", tone: "creator" },
  mediacrawler_douyin: { label: "抖音博主", tone: "creator" },
  mediacrawler_xhs: { label: "小红书博主", tone: "creator" },
  github_foundation_sunshine_releases: { label: "GitHub版本", tone: "creator" },
  maobidao_wudaolu_backup: { label: "公众号", tone: "creator" },
  wewe_rss: { label: "公众号", tone: "creator" },
  techurls: { label: "聚合", tone: "aggregate" },
  buzzing: { label: "聚合", tone: "aggregate" },
  iris: { label: "聚合", tone: "aggregate" },
  bestblogs: { label: "博客", tone: "blogs" },
  tophub: { label: "聚合", tone: "aggregate" },
  zeli: { label: "聚合", tone: "aggregate" },
  hackernews: { label: "HN", tone: "aggregate" },
  aihubtoday: { label: "AI站点", tone: "aihub" },
  aibase: { label: "AI站点", tone: "aihub" },
  waytoagi: { label: "社区", tone: "builders" },
  newsnow: { label: "聚合", tone: "aggregate" },
  opmlrss: { label: "OPML", tone: "newsletter" },
};

const SUBSCRIPTION_SITE_IDS = new Set([
  "tikhub_douyin",
  "tikhub_xiaohongshu",
  "bilibili_dynamic",
  "mediacrawler_douyin",
  "mediacrawler_xhs",
  "github_foundation_sunshine_releases",
]);

const HIDDEN_PLATFORM_IDS = new Set(["wechat"]);
const HIDDEN_SOURCE_IDS = new Set(["wewe_rss", "maobidao_wudaolu_backup"]);

const SECTION_DEFS = [
  { id: "creator", label: "我的订阅", short: "订阅", description: "B站、小红书、YouTube、抖音和 GitHub 项目的更新" },
  { id: "douyin", label: "抖音", short: "抖音", description: "抖音创作者与短视频信号" },
  { id: "xiaohongshu", label: "小红书", short: "小红书", description: "小红书博主、笔记和搜索信号" },
  { id: "wechat", label: "微信公众号", short: "公众号", description: "微信公众号订阅和 WeWe RSS 信号" },
  { id: "bilibili", label: "B站", short: "B站", description: "B站动态、视频和账号订阅" },
  { id: "youtube", label: "油管", short: "油管", description: "YouTube 频道订阅和视频更新" },
  { id: "read", label: "已阅", short: "已阅", description: "已标记已阅的订阅内容，可随时恢复" },
];

const SECTION_BY_ID = Object.fromEntries(SECTION_DEFS
  .filter((section) => !HIDDEN_PLATFORM_IDS.has(section.id))
  .map((section) => [section.id, section]));

const LIST_SORT_DEFS = [
  { id: "priority", label: "综合" },
  { id: "time", label: "时间" },
  { id: "ai", label: "高分" },
  { id: "source", label: "来源" },
];

const SOURCE_CONFIG_STORAGE_KEY = "ai-news-radar-source-config-v1";
const DATA_BASE_STORAGE_KEY = "ai-news-radar-data-base-v1";
const COLLECTION_SCOPE_STORAGE_KEY = "ai-news-radar-collection-scope-v1";
const READ_ITEMS_STORAGE_KEY = "ai-news-radar-read-items-v1";
const SOURCE_CONFIG_CATALOG_VERSION = "2026-07-09-retire-wechat-sources";
const RETIRED_SOURCE_CONFIG_IDS = new Set(["wewe_rss_maobidao", "maobidao_wudaolu_backup"]);

const SOURCE_CONFIG_FILTERS = [
  { id: "all", label: "全部" },
  { id: "enabled", label: "启用" },
  { id: "attention", label: "需维护" },
  { id: "wechat", label: "公众号" },
  { id: "xhs", label: "小红书" },
  { id: "douyin", label: "抖音" },
  { id: "bilibili", label: "B站" },
  { id: "rss", label: "RSS" },
  { id: "github", label: "GitHub" },
];

const SUBSCRIPTION_PLATFORMS = [
  {
    id: "bilibili",
    label: "B站",
    nameLabel: "UP主名称",
    locatorLabel: "B站 UID",
    locatorPlaceholder: "例如：316183842",
    homeUrl: false,
    storage: "bilibili",
    runtimeId: "bilibili_dynamic",
  },
  {
    id: "youtube",
    label: "油管",
    nameLabel: "频道名称",
    locatorLabel: "YouTube channel_id",
    locatorPlaceholder: "例如：UCxxxxxxxxxxxxxxxxxxxxxx",
    homeUrl: true,
    storage: "youtube",
    runtimeId: "opmlrss",
  },
  {
    id: "douyin",
    label: "抖音",
    nameLabel: "创作者名称",
    locatorLabel: "抖音主页链接",
    locatorPlaceholder: "例如：https://www.douyin.com/user/MS4wLjABAAAA...",
    homeUrl: false,
    storage: "source-records",
    runtimeId: "mediacrawler_douyin",
    type: "mediacrawler_jsonl",
    channel: "抖音",
    idPrefix: "mediacrawler_douyin",
    env: "MEDIACRAWLER_DOUYIN_ENABLED / MEDIACRAWLER_DOUYIN_JSONLS / MEDIACRAWLER_DOUYIN_SOURCE_NAMES",
    notes: "填创作者主页链接即可；Radar 会自动读取本地 MediaCrawler 最新 JSONL，不读取 cookie 或浏览器 profile。",
  },
  {
    id: "xiaohongshu",
    label: "小红书",
    nameLabel: "博主名称",
    locatorLabel: "小红书主页链接",
    locatorPlaceholder: "例如：https://www.xiaohongshu.com/user/profile/5e4027000000000001005eb8",
    homeUrl: false,
    storage: "source-records",
    runtimeId: "mediacrawler_xhs",
    type: "mediacrawler_jsonl",
    channel: "小红书",
    idPrefix: "mediacrawler_xhs",
    env: "MEDIACRAWLER_XHS_ENABLED / MEDIACRAWLER_XHS_JSONLS / MEDIACRAWLER_XHS_SOURCE_NAMES",
    notes: "填博主主页链接即可；Radar 会自动读取本地 MediaCrawler 最新 JSONL，不保存登录态。",
  },
  {
    id: "wechat",
    label: "微信公众号",
    nameLabel: "公众号名称",
    locatorLabel: "WeWe RSS feed_id",
    locatorPlaceholder: "例如：MP_WXS_3198966508",
    homeUrl: false,
    storage: "source-records",
    runtimeId: "wewe_rss",
    type: "wewe_rss",
    channel: "微信公众号",
    idPrefix: "wewe_rss",
    env: "WEWE_RSS_ENABLED / WEWE_RSS_FEEDS",
    notes: "本地 WeWe RSS sidecar 的公众号 feed；Radar 只读 JSON Feed，不读取数据库或登录态。",
  },
  {
    id: "github",
    label: "GitHub",
    nameLabel: "仓库名称",
    locatorLabel: "仓库或 Releases API",
    locatorPlaceholder: "例如：AlkaidLab/foundation-sunshine",
    homeUrl: false,
    storage: "source-records",
    runtimeId: "github_foundation_sunshine_releases",
    type: "github_release",
    channel: "GitHub Release",
    idPrefix: "github_release",
    env: "",
    notes: "只追踪 GitHub Releases，不追踪普通 commit。",
  },
];


// 渲染限额常量（原 app.js 4182-4184、4976-4984 行，拆分时曾遗漏，验收补回）
const HOT_DECAY_HOURS = 12;
const HOT_SCORE_SCALE = 60;
const SOURCE_ITEM_INITIAL_LIMIT = 3;
const SITE_GROUP_INITIAL_LIMIT = 4;
const SITE_GROUP_LOAD_STEP = 4;
const SITE_SOURCE_GROUP_INITIAL_LIMIT = 4;
const SITE_SOURCE_GROUP_LOAD_STEP = 4;
const SOURCE_GROUP_INITIAL_LIMIT = 8;
const SOURCE_GROUP_LOAD_STEP = 8;
const BOLE_HOT_LIMIT = 10;
const BOLE_TIMELINE_LIMIT = 20;

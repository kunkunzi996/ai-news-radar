const { test, expect } = require("@playwright/test");

const GENERATED_AT = "2026-08-27T12:00:00+08:00";
const HOUR_ONLY_TITLE = "仅24小时条目甲";

function makeItem(id, title) {
  return {
    id,
    site_id: "bilibili_dynamic",
    site_name: "B站",
    source: "测试作者",
    title,
    title_zh: title,
    url: `https://www.bilibili.com/video/${id}`,
    published_at: "2026-08-27T11:00:00+08:00",
    first_seen_at: "2026-08-27T11:00:00+08:00",
    ai_score: 0.5,
    creator_hot_score: 40,
    ai_label: "ai_general",
    ai_signals: ["fixture"],
    source_tier: "creator",
    source_tier_rank: 3,
  };
}

const HOUR_ITEM = makeItem("hour-only-1", HOUR_ONLY_TITLE);
const SLIM_PAYLOAD = {
  generated_at: GENERATED_AT,
  time_scope: "rolling_window",
  source_scope: "all_sources",
  creator_window_days: 7,
  creator_time_scope: "rolling_window",
  total_items: 1,
  creator_items_ai: [HOUR_ITEM],
  creator_items_all: [HOUR_ITEM],
  items: [],
  all_mode_data_url: "data/latest-24h-all.json",
  stories_data_url: "data/stories-merged.json",
};
const ALL_PAYLOAD = {
  generated_at: GENERATED_AT,
  creator_items_all: [HOUR_ITEM],
  items_all: [HOUR_ITEM],
  items_all_raw: [HOUR_ITEM],
};
const SOURCE_STATUS = {
  generated_at: GENERATED_AT,
  sites: [{ site_id: "bilibili_dynamic", site_name: "B站", ok: true, item_count: 1 }],
  failed_sites: [],
  rss_opml: { enabled: false, failed_feeds: [] },
};
const HELLO_STATE = {
  version: 1,
  view: {
    activeSection: "creator",
    query: "",
    listSort: "ai",
    timeRangeFilter: "all",
    sourceTypeFilter: "",
    signalLevelFilter: "",
    siteFilter: "",
    mode: "all",
    allDedup: false,
    readFilter: "all",
  },
  viewRevision: 1,
  updatedAt: GENERATED_AT,
};

function jsonResponse(body) {
  return { status: 200, contentType: "application/json", body: JSON.stringify(body) };
}

async function installWorkbenchHello(page, initialState = HELLO_STATE) {
  await page.addInitScript(({ initialState }) => {
    window.__hostWrites = [];
    window.__hostMessages = [];
    window.OmniaRadarHost = {
      postMessage(json) {
        const message = JSON.parse(json);
        window.__hostWrites.push(message.type);
        window.__hostMessages.push(message);
        if (message.type === "radar-ready") {
          setTimeout(() => window.WorkbenchBridge.receiveHostMessage(JSON.stringify({
            version: 1,
            type: "workbench-hello",
            requestId: message.requestId,
            state: initialState,
            syncAvailable: true,
            readOnly: false,
          })), 0);
          return;
        }
        if (message.type === "radar-read-status") {
          setTimeout(() => window.WorkbenchBridge.receiveHostMessage(JSON.stringify({
            version: 1,
            type: "radar-read-status-result",
            requestId: message.requestId,
            ok: true,
            readKeys: [],
          })), 0);
          return;
        }
        if (message.type === "radar-read" || message.type === "radar-view-patch") {
          setTimeout(() => window.WorkbenchBridge.receiveHostMessage(JSON.stringify({
            version: 1,
            type: "radar-state-result",
            requestId: message.requestId,
            ok: true,
            status: 200,
          })), 0);
        }
      },
    };
  }, { initialState });
}

function fixtureJson() {
  return {
    "/data/source-status.json": SOURCE_STATUS,
    "/data/waytoagi-7d.json": { generated_at: GENERATED_AT, items: [] },
    "/data/daily-brief.json": { generated_at: GENERATED_AT, items: [] },
    "/data/stories-merged.json": { generated_at: GENERATED_AT, stories: [] },
    "/api/source-config": {
      ok: true,
      path: "sources.config.json",
      config: { version: "1.0", updated_at: GENERATED_AT, deleted_source_ids: [], sources: [] },
    },
    "/api/online-source-config": { ok: true, source_count: 0, sources: [] },
    "/api/local-status": {
      ok: true,
      source_status: SOURCE_STATUS,
      source_config: { enabled_sources: [] },
      collectors: {},
      refresh_running: false,
    },
    "/api/subscriptions/youtube": { ok: true, subscriptions: [] },
    "/config/online-sources.json": { version: "1.0", sources: [] },
  };
}

async function installArchiveStatusFixture(page, failPath = "") {
  await page.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    if (route.request().isNavigationRequest() && url.pathname === "/") {
      const response = await route.fetch();
      const html = (await response.text()).replace(
        /\s*<script src="https:\/\/cdn\.jsdelivr\.net\/npm\/gsap@3\.13\.0\/dist\/gsap\.min\.js"[^>]*><\/script>/,
        "",
      );
      await route.fulfill({ response, body: html });
      return;
    }
    if (url.pathname === failPath) {
      await route.fulfill({ status: 500, contentType: "application/json", body: "{\"ok\":false}" });
      return;
    }
    const staticJson = Object.assign({
      "/data/latest-24h.json": SLIM_PAYLOAD,
      "/data/latest-24h-all.json": ALL_PAYLOAD,
    }, fixtureJson());
    if (Object.prototype.hasOwnProperty.call(staticJson, url.pathname)) {
      await route.fulfill(jsonResponse(staticJson[url.pathname]));
      return;
    }
    await route.continue();
  });
}

async function latestArchiveStatusPayload(page) {
  return page.evaluate(() => window.__hostMessages
    .filter((message) => message.type === "radar-archive-status")
    .at(-1)?.payload || null);
}

test("P5-ARCHIVE：近两周没拿全时列表未更新且不暂停写入", async ({ page }) => {
  await installWorkbenchHello(page);

  await page.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    if (route.request().isNavigationRequest() && url.pathname === "/") {
      const response = await route.fetch();
      const html = (await response.text()).replace(
        /\s*<script src="https:\/\/cdn\.jsdelivr\.net\/npm\/gsap@3\.13\.0\/dist\/gsap\.min\.js"[^>]*><\/script>/,
        "",
      );
      await route.fulfill({ response, body: html });
      return;
    }
    if (url.pathname === "/data/latest-24h-all.json") {
      await route.fulfill({ status: 500, contentType: "application/json", body: "{\"ok\":false}" });
      return;
    }
    const staticJson = {
      "/data/latest-24h.json": SLIM_PAYLOAD,
      "/data/source-status.json": SOURCE_STATUS,
      "/data/waytoagi-7d.json": { generated_at: GENERATED_AT, items: [] },
      "/data/daily-brief.json": { generated_at: GENERATED_AT, items: [] },
      "/data/stories-merged.json": { generated_at: GENERATED_AT, stories: [] },
      "/api/source-config": {
        ok: true,
        path: "sources.config.json",
        config: { version: "1.0", updated_at: GENERATED_AT, deleted_source_ids: [], sources: [] },
      },
      "/api/online-source-config": { ok: true, source_count: 0, sources: [] },
      "/api/local-status": {
        ok: true,
        source_status: SOURCE_STATUS,
        source_config: { enabled_sources: [] },
        collectors: {},
        refresh_running: false,
      },
      "/api/subscriptions/youtube": { ok: true, subscriptions: [] },
      "/config/online-sources.json": { version: "1.0", sources: [] },
    };
    if (Object.prototype.hasOwnProperty.call(staticJson, url.pathname)) {
      await route.fulfill(jsonResponse(staticJson[url.pathname]));
      return;
    }
    await route.continue();
  });

  await page.goto("/?omniaApp=1");
  await expect(page.locator("#radarSyncStatus")).toHaveText("列表未更新");
  await expect(page.locator("#newsList")).not.toContainText(HOUR_ONLY_TITLE);
  await expect.poll(() => page.evaluate(() => window.RadarSync && window.RadarSync.canWriteCollections())).toBe(true);
  await expect(page.locator("#radarSyncStatus")).not.toHaveText("同步暂停");
});

test("P5-ARCHIVE：订阅归档整包失败时列表未更新且不暂停写入", async ({ page }) => {
  const hourHello = {
    version: 1,
    view: {
      activeSection: "creator",
      query: "",
      listSort: "ai",
      timeRangeFilter: "24h",
      sourceTypeFilter: "",
      signalLevelFilter: "",
      siteFilter: "",
      mode: "ai",
      allDedup: false,
      readFilter: "all",
    },
    viewRevision: 1,
    updatedAt: GENERATED_AT,
  };
  await installWorkbenchHello(page, hourHello);

  await page.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    if (route.request().isNavigationRequest() && url.pathname === "/") {
      const response = await route.fetch();
      const html = (await response.text()).replace(
        /\s*<script src="https:\/\/cdn\.jsdelivr\.net\/npm\/gsap@3\.13\.0\/dist\/gsap\.min\.js"[^>]*><\/script>/,
        "",
      );
      await route.fulfill({ response, body: html });
      return;
    }
    if (url.pathname === "/data/latest-24h.json") {
      await route.fulfill({ status: 500, contentType: "application/json", body: "{\"ok\":false}" });
      return;
    }
    const staticJson = Object.assign({
      "/data/latest-24h-all.json": {
        generated_at: GENERATED_AT,
        creator_items_all: [HOUR_ITEM],
        items_all: [HOUR_ITEM],
        items_all_raw: [HOUR_ITEM],
      },
    }, fixtureJson());
    if (Object.prototype.hasOwnProperty.call(staticJson, url.pathname)) {
      await route.fulfill(jsonResponse(staticJson[url.pathname]));
      return;
    }
    await route.continue();
  });

  await page.goto("/?omniaApp=1");
  await expect(page.locator("#radarSyncStatus")).toHaveText("列表未更新");
  await expect.poll(() => page.evaluate(() => window.RadarSync && window.RadarSync.canWriteCollections())).toBe(true);
  await expect(page.locator("#radarSyncStatus")).not.toHaveText("同步暂停");
  await expect(page.locator("#radarSyncStatus")).not.toHaveText("已同步");
});

test("TEST-033：App 有基础列表时归档失败上报 hasUsableList=true", async ({ page }) => {
  await installWorkbenchHello(page);
  await installArchiveStatusFixture(page, "/data/latest-24h-all.json");

  await page.goto("/?omniaApp=1");
  await expect(page.locator("#radarSyncStatus")).toHaveText("列表未更新");
  await expect.poll(() => latestArchiveStatusPayload(page)).toEqual({
    stale: true,
    hasUsableList: true,
  });
});

test("TEST-033：App 无基础列表时上报 hasUsableList=false", async ({ page }) => {
  await installWorkbenchHello(page, {
    ...HELLO_STATE,
    view: {
      ...HELLO_STATE.view,
      timeRangeFilter: "24h",
      mode: "ai",
    },
  });
  await installArchiveStatusFixture(page, "/data/latest-24h.json");

  await page.goto("/?omniaApp=1");
  await expect(page.locator("#radarSyncStatus")).toHaveText("列表未更新");
  await expect.poll(() => latestArchiveStatusPayload(page)).toEqual({
    stale: true,
    hasUsableList: false,
  });
});

test("TEST-033：桌面模式归档状态载荷仍只有 stale", async ({ page }) => {
  await installArchiveStatusFixture(page);
  await page.goto("/");

  const payload = await page.evaluate(() => {
    const archivePayloads = [];
    const originalNotify = window.WorkbenchBridge.notify;
    window.WorkbenchBridge.notify = (type, nextPayload) => {
      if (type === "radar-archive-status") archivePayloads.push(nextPayload);
      return originalNotify.call(window.WorkbenchBridge, type, nextPayload);
    };
    window.RadarSync.markArchiveListStale();
    return archivePayloads.at(-1) || null;
  });

  expect(payload).toEqual({ stale: true });
});

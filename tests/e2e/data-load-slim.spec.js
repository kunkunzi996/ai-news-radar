const { test, expect } = require("@playwright/test");

const GENERATED_AT = "2026-08-27T12:00:00+08:00";

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

const CREATOR_ITEMS = [
  makeItem("slim-1", "首屏条目一"),
  makeItem("slim-2", "首屏条目二"),
  makeItem("slim-3", "首屏条目三"),
];

const SLIM_PAYLOAD = {
  generated_at: GENERATED_AT,
  time_scope: "rolling_window",
  source_scope: "all_sources",
  creator_window_days: 7,
  creator_time_scope: "rolling_window",
  total_items: 0,
  creator_items_ai: CREATOR_ITEMS,
  creator_items_all: CREATOR_ITEMS,
  items: [],
  all_mode_data_url: "data/latest-24h-all.json",
  stories_data_url: "data/stories-merged.json",
};

const ALL_PAYLOAD = {
  generated_at: GENERATED_AT,
  time_scope: "rolling_window",
  source_scope: "all_sources",
  creator_window_days: 7,
  creator_time_scope: "rolling_window",
  creator_items_all: [makeItem("all-1", "全量补条目")],
  items_all: [makeItem("all-1", "全量补条目")],
  items_all_raw: [makeItem("all-1", "全量补条目")],
};

const HOUR_VIEW = {
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
};

const SOURCE_STATUS = {
  generated_at: GENERATED_AT,
  sites: [{ site_id: "bilibili_dynamic", site_name: "B站", ok: true, item_count: 3 }],
  failed_sites: [],
  rss_opml: { enabled: false, failed_feeds: [] },
};

function jsonResponse(body) {
  return { status: 200, contentType: "application/json", body: JSON.stringify(body) };
}

async function installSlimFixture(page, { delayAll, helloView } = {}) {
  let releaseAllData = () => {};
  const allDataGate = delayAll
    ? new Promise((resolve) => {
      releaseAllData = resolve;
    })
    : Promise.resolve();
  let allDataRequested = false;
  const dataUrls = [];
  page.on("request", (request) => {
    const url = request.url();
    if (url.includes("/data/")) dataUrls.push(url);
  });
  if (helloView) {
    await page.addInitScript(({ view }) => {
      window.OmniaRadarHost = {
        postMessage(json) {
          const message = JSON.parse(json);
          if (message.type === "radar-ready") {
            setTimeout(() => window.WorkbenchBridge.receiveHostMessage(JSON.stringify({
              version: 1,
              type: "workbench-hello",
              requestId: message.requestId,
              state: { version: 1, view, viewRevision: 1, updatedAt: "2026-08-27T12:00:00+08:00" },
              syncAvailable: true,
              readOnly: false,
            })), 0);
          }
          if (message.type === "radar-read-status") {
            setTimeout(() => window.WorkbenchBridge.receiveHostMessage(JSON.stringify({
              version: 1,
              type: "radar-read-status-result",
              requestId: message.requestId,
              ok: true,
              readKeys: [],
            })), 0);
          }
        },
      };
    }, { view: helloView });
  }
  await page.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    if (route.request().isNavigationRequest() && (url.pathname === "/" || url.pathname === "")) {
      const response = await route.fetch();
      const html = (await response.text()).replace(
        /\s*<script src="https:\/\/cdn\.jsdelivr\.net\/npm\/gsap@3\.13\.0\/dist\/gsap\.min\.js"[^>]*><\/script>/,
        "",
      );
      await route.fulfill({ response, body: html });
      return;
    }
    if (url.pathname === "/data/latest-24h-all.json") {
      allDataRequested = true;
      await allDataGate;
      await route.fulfill(jsonResponse(ALL_PAYLOAD));
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
  return { releaseAllData, getAllDataRequested: () => allDataRequested, getDataUrls: () => dataUrls };
}

test("首屏不阻塞 latest-24h-all.json，且数据请求不带 t= 缓存穿透", async ({ page }) => {
  const fixture = await installSlimFixture(page, { delayAll: true });
  await page.goto("/");
  await expect.poll(() => fixture.getAllDataRequested()).toBeTruthy();
  await expect(page.locator("#newsList")).not.toContainText("首屏条目一");
  await expect(page.locator("#newsList .news-card")).toHaveCount(0);

  fixture.releaseAllData();
  await expect(page.locator("#newsList")).toContainText("全量补条目");
  const queried = fixture.getDataUrls().filter((url) => new URL(url).searchParams.has("t"));
  expect(queried).toEqual([]);
});

test("24 小时筛选不等 latest-24h-all.json 也能出卡，且数据请求不带 t=", async ({ page }) => {
  const fixture = await installSlimFixture(page, { delayAll: true, helloView: HOUR_VIEW });
  await page.goto("/?omniaApp=1");
  await expect(page.locator("#newsList .news-card")).toHaveCount(3);
  await expect(page.locator("#newsList")).toContainText("首屏条目一");
  expect(fixture.getAllDataRequested()).toBeTruthy();
  const queried = fixture.getDataUrls().filter((url) => new URL(url).searchParams.has("t"));
  expect(queried).toEqual([]);
  fixture.releaseAllData();
});

test("P5-ARCHIVE：订阅归档请求强制再验证且不带 t=", async ({ page }) => {
  await page.addInitScript(() => {
    window.__subscriptionFetches = [];
    const originalFetch = window.fetch.bind(window);
    window.fetch = (input, init) => {
      const url = typeof input === "string"
        ? input
        : (input && input.url) ? input.url : String(input);
      window.__subscriptionFetches.push({
        url,
        cache: init && typeof init.cache === "string" ? init.cache : "",
      });
      return originalFetch(input, init);
    };
  });

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
    const staticJson = {
      "/data/latest-24h.json": SLIM_PAYLOAD,
      "/data/latest-24h-all.json": ALL_PAYLOAD,
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

  await page.goto("/");
  await expect(page.locator("#newsList .news-card").first()).toBeVisible();
  await page.waitForFunction(() => {
    const rows = window.__subscriptionFetches || [];
    const hasSlim = rows.some((row) => /latest-24h\.json(?:\?|$)/.test(row.url) && !row.url.includes("latest-24h-all.json"));
    const hasAll = rows.some((row) => row.url.includes("latest-24h-all.json"));
    return hasSlim && hasAll;
  });

  const records = await page.evaluate(() => window.__subscriptionFetches || []);
  const slim = records.filter((row) => /latest-24h\.json(?:\?|$)/.test(row.url) && !row.url.includes("latest-24h-all.json"));
  const all = records.filter((row) => row.url.includes("latest-24h-all.json"));
  expect(slim.length, "必须请求 latest-24h.json").toBeGreaterThan(0);
  expect(all.length, "必须请求 latest-24h-all.json").toBeGreaterThan(0);

  for (const row of slim.concat(all)) {
    const parsed = new URL(row.url, "http://127.0.0.1");
    expect(parsed.searchParams.has("t"), `${row.url} 不得带 t=`).toBeFalsy();
    expect(row.cache, `${row.url} 必须 cache reload`).toBe("reload");
  }
});

const http = require("node:http");
const { test, expect } = require("@playwright/test");

let PARENT_ORIGIN = "";
let WRONG_ORIGIN_PARENT = "";
const GENERATED_AT = "2026-07-17T12:00:00+08:00";
const COLLECT_IDLE_TITLE = "收藏到工作台收藏库，并标记已阅";
const FIRST_ITEM = {
  id: "workbench-bridge-first",
  site_id: "bilibili_dynamic",
  site_name: "B站",
  source: "桥接测试作者甲",
  title: "工作台收藏桥测试标题甲",
  url: "https://www.bilibili.com/video/workbench-bridge-first",
  published_at: "2026-07-17T09:30:00+08:00",
  first_seen_at: "2026-07-17T09:30:00+08:00",
  ai_score: 0.8,
  ai_label: "ai_general",
  ai_signals: ["收藏桥验证甲"],
  source_tier: "creator",
  source_tier_rank: 3,
};
const SECOND_ITEM = {
  ...FIRST_ITEM,
  id: "workbench-bridge-second",
  source: "桥接测试作者乙",
  title: "工作台收藏桥测试标题乙",
  url: "https://www.bilibili.com/video/workbench-bridge-second",
  published_at: "2026-07-17T09:20:00+08:00",
  first_seen_at: "2026-07-17T09:20:00+08:00",
  ai_signals: ["收藏桥验证乙"],
};
const FIXTURE_ITEMS = [FIRST_ITEM, SECOND_ITEM];
const SYNC_STATE = {
  version: 1,
  readKeys: [FIRST_ITEM.url],
  view: {
    activeSection: "bilibili",
    query: "工作台收藏桥",
    listSort: "ai",
    timeRangeFilter: "24h",
    sourceTypeFilter: "creator",
    signalLevelFilter: "high",
    siteFilter: "bilibili_dynamic",
    mode: "ai",
    allDedup: false,
    readFilter: "read",
  },
  viewRevision: 7,
  updatedAt: "2026-07-17T12:30:00+08:00",
};
const NEWS_PAYLOAD = {
  generated_at: GENERATED_AT,
  time_scope: "all_time",
  source_scope: "tested_creator_sources",
  creator_window_days: 180,
  creator_time_scope: "all_time",
  total_items: FIXTURE_ITEMS.length,
  total_items_raw: FIXTURE_ITEMS.length,
  total_items_all_mode: FIXTURE_ITEMS.length,
  items: FIXTURE_ITEMS,
  items_ai: FIXTURE_ITEMS,
  items_all: FIXTURE_ITEMS,
  items_all_raw: FIXTURE_ITEMS,
  creator_items_ai: FIXTURE_ITEMS,
  creator_items_all: FIXTURE_ITEMS,
};
const SOURCE_STATUS = {
  generated_at: GENERATED_AT,
  sites: [{ site_id: "bilibili_dynamic", site_name: "B站", ok: true, item_count: 2 }],
  failed_sites: [],
  rss_opml: { enabled: false, failed_feeds: [] },
};

let radarOrigin = "";
let parentServer;
let wrongOriginServer;
let workbenchRadarConfig = null;
let workbenchRadarState = null;
let workbenchReaderOnly = false;
let workbenchReadKeys = [];
let workbenchReadStatusFailure = false;
let workbenchMigrationConflict = null;
let workbenchWriteFailure = null;
let workbenchRequestTimeoutMs = 0;
let workbenchNoReferrer = false;

function jsonResponse(body) {
  return { status: 200, contentType: "application/json", body: JSON.stringify(body) };
}

function collectErrors(page) {
  const errors = [];
  page.on("pageerror", (error) => errors.push(`pageerror: ${error}`));
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(`console: ${message.text()}`);
  });
  return errors;
}

async function installRadarFixture(page, fixtureItems = FIXTURE_ITEMS) {
  const newsPayload = {
    ...NEWS_PAYLOAD,
    total_items: fixtureItems.length,
    total_items_raw: fixtureItems.length,
    total_items_all_mode: fixtureItems.length,
    items: fixtureItems,
    items_ai: fixtureItems,
    items_all: fixtureItems,
    items_all_raw: fixtureItems,
    creator_items_ai: fixtureItems,
    creator_items_all: fixtureItems,
  };
  const responses = new Map([
    ["/data/latest-24h.json", newsPayload],
    ["/data/latest-24h-all.json", newsPayload],
    ["/data/source-status.json", SOURCE_STATUS],
    ["/data/waytoagi-7d.json", { generated_at: GENERATED_AT, items: [] }],
    ["/data/daily-brief.json", { generated_at: GENERATED_AT, items: [] }],
    ["/data/stories-merged.json", { generated_at: GENERATED_AT, stories: [] }],
    ["/api/source-config", {
      ok: true,
      path: "sources.config.json",
      config: { version: "1.0", updated_at: GENERATED_AT, deleted_source_ids: [], sources: [] },
    }],
    ["/api/online-source-config", { ok: true, source_count: 0, sources: [] }],
    ["/api/local-status", {
      ok: true,
      source_status: SOURCE_STATUS,
      source_config: { enabled_sources: [] },
      collectors: {},
      refresh_running: false,
    }],
    ["/api/subscriptions/youtube", { ok: true, subscriptions: [] }],
    ["/config/online-sources.json", { version: "1.0", sources: [] }],
  ]);

  await page.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    if (url.origin === radarOrigin && route.request().isNavigationRequest() && url.pathname === "/") {
      const response = await route.fetch();
      const html = (await response.text()).replace(
        /\s*<script src="https:\/\/cdn\.jsdelivr\.net\/npm\/gsap@3\.13\.0\/dist\/gsap\.min\.js"[^>]*><\/script>/,
        "",
      );
      await route.fulfill({ response, body: html });
      return;
    }
    if (url.origin === radarOrigin && url.pathname === "/assets/js/workbench-bridge.js") {
      const response = await route.fetch();
      const bridgeSource = await response.text();
      let dynamicBridgeSource = bridgeSource.replace(
        '"http://127.0.0.1:8765"',
        JSON.stringify(PARENT_ORIGIN),
      );
      if (dynamicBridgeSource === bridgeSource) {
        throw new Error("测试无法注入动态工作台父源，请检查桥接白名单测试锚点。");
      }
      if (workbenchRequestTimeoutMs) {
        dynamicBridgeSource = dynamicBridgeSource.replace(
          "const REQUEST_TIMEOUT_MS = 10000;",
          `const REQUEST_TIMEOUT_MS = ${workbenchRequestTimeoutMs};`,
        );
        if (!dynamicBridgeSource.includes(`const REQUEST_TIMEOUT_MS = ${workbenchRequestTimeoutMs};`)) {
          throw new Error("测试无法缩短桥请求超时，请检查测试锚点。");
        }
      }
      await route.fulfill({ response, body: dynamicBridgeSource });
      return;
    }
    if (url.origin === radarOrigin && responses.has(url.pathname)) {
      await route.fulfill(jsonResponse(responses.get(url.pathname)));
      return;
    }
    await route.continue();
  });
}

function sendHtml(response, html) {
  response.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
  response.end(html);
}

function workbenchHtml(radarUrl, radarConfig = null, radarState = null) {
  const injectedRadarConfig = JSON.stringify(radarConfig);
  const injectedRadarState = JSON.stringify(radarState);
  return `<!doctype html>
<html lang="zh-CN">
  <head>${workbenchNoReferrer ? '<meta name="referrer" content="no-referrer">' : ""}</head>
  <body>
    <iframe id="radar" title="真实雷达"></iframe>
    <iframe id="spoof" title="同源伪造页" src="/spoof"></iframe>
    <script>
      const radarOrigin = ${JSON.stringify(new URL(radarUrl).origin)};
      const workbenchRadarConfig = ${injectedRadarConfig};
      const workbenchRadarState = ${injectedRadarState};
      const workbenchWriteFailure = ${JSON.stringify(workbenchWriteFailure)};
      const radar = document.getElementById("radar");
      const events = [];
      const messages = [];
      const migrationResponses = [];
      const requests = new Map();
      const knownReadKeys = new Set(${JSON.stringify(workbenchReadKeys)});
      let migrationStatus = workbenchRadarState?.legacyReadMigration?.status || "complete";
      let claimedMigrationId = workbenchRadarState?.legacyReadMigration?.migrationId || "";
      const radarUrl = new URL(${JSON.stringify(radarUrl)});
      if (${JSON.stringify(workbenchReaderOnly)}) radarUrl.searchParams.set("readerOnly", "1");
      radar.src = radarUrl.toString();

      function handleWriteFailure(event, data) {
        if (workbenchWriteFailure?.type !== data.type) return false;
        if (workbenchWriteFailure.mode === "timeout") return true;
        const result = data.type === "radar-collect"
          ? {
            version: 1,
            type: "radar-collect-result",
            requestId: data.requestId,
            ok: false,
            error: "工作台收藏接口返回 503",
          }
          : {
            version: 1,
            type: "radar-state-result",
            requestId: data.requestId,
            ok: false,
            status: 503,
            code: "fixture_write_unavailable",
            error: "工作台写入不可用",
          };
        event.source.postMessage(result, event.origin);
        return true;
      }

      window.addEventListener("message", (event) => {
        if (event.origin !== radarOrigin || event.source !== radar.contentWindow) return;
        const data = event.data;
        if (!data || typeof data !== "object") return;
        messages.push(data);
        events.push({ type: data.type, requestId: data.requestId || "", origin: event.origin });
        if (data.type === "radar-collect") {
          requests.set(data.requestId, { source: event.source, origin: event.origin, requestId: data.requestId, payload: data.payload });
          if (handleWriteFailure(event, data)) return;
        }
        if (data.type === "radar-view-patch" || data.type === "radar-read") {
          if (handleWriteFailure(event, data)) return;
        }
        if (data.type === "radar-source-config-read") {
          event.source.postMessage({
            version: 1,
            type: "radar-source-config-result",
            requestId: data.requestId,
            ok: true,
            config: {
              version: "1.0",
              sources: [{ id: "host-relay-source", name: "宿主代读信源", type: "rss", locator: "https://example.com/feed.xml" }],
            },
          }, event.origin);
        }
        if (data.type === "radar-read-status") {
          event.source.postMessage({
            version: 1,
            type: "radar-read-status-result",
            requestId: data.requestId,
            ok: ${JSON.stringify(!workbenchReadStatusFailure)},
            ...(${JSON.stringify(workbenchReadStatusFailure)}
              ? { status: 503, code: "read_status_unavailable", error: "权威已阅状态不可用" }
              : {
                readKeys: Array.isArray(data.payload?.keys)
                  ? data.payload.keys.filter((key) => knownReadKeys.has(key))
                  : [],
              }),
          }, event.origin);
        }
        if (data.type === "radar-read-migration") {
          if (${JSON.stringify(workbenchMigrationConflict)}) {
            const conflict = ${JSON.stringify(workbenchMigrationConflict)};
            const response = {
              version: 1,
              type: "radar-read-migration-result",
              requestId: data.requestId,
              ok: false,
              status: 409,
              code: conflict.code,
              error: conflict.error,
              state: conflict.state,
              legacyReadMigration: conflict.state.legacyReadMigration,
            };
            migrationResponses.push(response);
            event.source.postMessage(response, event.origin);
            return;
          }
          const migrationId = String(data.payload?.migrationId || "");
          let ok = false;
          if (migrationStatus === "open" && migrationId) {
            migrationStatus = "claimed";
            claimedMigrationId = migrationId;
          }
          if (migrationStatus === "claimed" && migrationId === claimedMigrationId) {
            ok = true;
            for (const key of Array.isArray(data.payload?.keys) ? data.payload.keys : []) knownReadKeys.add(key);
            if (data.payload?.complete === true) migrationStatus = "complete";
          }
          event.source.postMessage({
            version: 1,
            type: "radar-read-migration-result",
            requestId: data.requestId,
            ok,
            legacyReadMigration: { version: 1, status: migrationStatus, migrationId: claimedMigrationId },
            ...(!ok ? { error: "迁移不可用" } : {}),
          }, event.origin);
        }
      });

      window.__workbench = {
        hello(requestId = "") {
          const send = () => {
            const ready = messages.filter((message) => message.type === "radar-ready").at(-1);
            const correlatedRequestId = requestId || ready?.requestId || "";
            if (!correlatedRequestId) {
              setTimeout(send, 10);
              return;
            }
            radar.contentWindow.postMessage({
              version: 1,
              type: "workbench-hello",
              requestId: correlatedRequestId,
              syncAvailable: true,
              readOnly: false,
              ...(workbenchRadarState ? {
                state: workbenchRadarState,
              } : {}),
              ...(!${JSON.stringify(workbenchReaderOnly)} && workbenchRadarConfig ? { radarConfig: workbenchRadarConfig } : {}),
            }, radarOrigin);
          };
          send();
        },
        sendToRadar(message) {
          radar.contentWindow.postMessage(message, radarOrigin);
        },
        events() {
          return events.slice();
        },
        currentReadyId() {
          return messages.filter((message) => message.type === "radar-ready").at(-1)?.requestId || "";
        },
        latestMessage(type) {
          return messages.filter((message) => message.type === type).at(-1) || null;
        },
        readStatusRequests() {
          return messages.filter((message) => message.type === "radar-read-status");
        },
        migrationRequests() {
          return messages.filter((message) => message.type === "radar-read-migration");
        },
        migrationResponses() {
          return migrationResponses.slice();
        },
        latestRequest() {
          const requestsInOrder = Array.from(requests.values());
          const request = requestsInOrder[requestsInOrder.length - 1];
          return request && { requestId: request.requestId, payload: request.payload, origin: request.origin };
        },
        reply(requestId, result) {
          const request = requests.get(requestId);
          if (!request) throw new Error("未找到收藏请求");
          request.source.postMessage({ version: 1, type: "radar-collect-result", requestId, ...result }, request.origin);
        },
      };
    </script>
  </body>
</html>`;
}

function spoofHtml() {
  return `<!doctype html>
<html lang="zh-CN">
  <body>
    <script>
      window.sendSpoofToRadar = (message, targetOrigin) => {
        parent.document.getElementById("radar").contentWindow.postMessage(message, targetOrigin);
      };
    </script>
  </body>
</html>`;
}

function wrongOriginHtml(radarUrl) {
  return `<!doctype html>
<html lang="zh-CN">
  <body>
    <iframe id="radar" title="错误来源父页中的真实雷达"></iframe>
    <script>
      const radar = document.getElementById("radar");
      const radarOrigin = ${JSON.stringify(new URL(radarUrl).origin)};
      radar.src = ${JSON.stringify(radarUrl)};
      window.__originSpoofHello = () => radar.contentWindow.postMessage({ type: "workbench-hello" }, radarOrigin);
    </script>
  </body>
</html>`;
}

function startServer(handler) {
  return new Promise((resolve, reject) => {
    const server = http.createServer(handler);
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => resolve(server));
  });
}

function serverOrigin(server) {
  const address = server.address();
  if (!address || typeof address === "string") throw new Error("动态测试端口未成功分配");
  return `http://127.0.0.1:${address.port}`;
}

function closeServer(server) {
  return new Promise((resolve, reject) => {
    if (!server) return resolve();
    server.close((error) => (error ? reject(error) : resolve()));
  });
}

async function openWorkbench(page) {
  const errors = collectErrors(page);
  await installRadarFixture(page);
  await page.goto(PARENT_ORIGIN);
  const radar = page.frameLocator("#radar");
  await expect(radar.locator("#newsList .news-card")).toHaveCount(2);
  await expect.poll(() => page.evaluate(() => window.__workbench.events().some((event) => event.type === "radar-ready"))).toBe(true);
  await page.evaluate(() => window.__workbench.hello());
  await expect(radar.locator(".collect-btn")).toHaveCount(2);
  return { errors, radar };
}

async function latestRequest(page) {
  await expect.poll(() => page.evaluate(() => Boolean(window.__workbench.latestRequest()))).toBe(true);
  return page.evaluate(() => window.__workbench.latestRequest());
}

test.describe("工作台收藏桥", () => {
  test.beforeAll(async ({ browser }, testInfo) => {
    void browser;
    const baseURL = testInfo.project.use.baseURL;
    radarOrigin = new URL(baseURL).origin;
    parentServer = await startServer((request, response) => {
      if (request.url === "/spoof") return sendHtml(response, spoofHtml());
      return sendHtml(response, workbenchHtml(baseURL, workbenchRadarConfig, workbenchRadarState));
    });
    PARENT_ORIGIN = serverOrigin(parentServer);
    wrongOriginServer = await startServer((_request, response) => (
      sendHtml(response, wrongOriginHtml(baseURL))
    ));
    WRONG_ORIGIN_PARENT = serverOrigin(wrongOriginServer);
  });

  test.afterAll(async () => {
    await closeServer(wrongOriginServer);
    await closeServer(parentServer);
  });

  test("父页禁止 referrer 时仍能向白名单父源发起握手并应用已阅", async ({ page }) => {
    workbenchNoReferrer = true;
    workbenchRadarState = SYNC_STATE;
    const errors = collectErrors(page);
    await installRadarFixture(page);
    await page.goto(PARENT_ORIGIN);
    const radar = page.frameLocator("#radar");
    await expect(radar.locator("#newsList .news-card")).toHaveCount(2);
    await expect.poll(() => page.evaluate(() => window.__workbench.events().some((event) => event.type === "radar-ready"))).toBe(true);
    await page.evaluate(() => window.__workbench.hello());
    await expect.poll(() => radar.locator("body").evaluate(() => window.WorkbenchBridge.connected())).toBe(true);
    await expect(radar.locator(".section-tab.active")).toContainText("B站");
    expect(errors).toEqual([]);
    workbenchNoReferrer = false;
    workbenchRadarState = null;
  });

  test("独立打开时没有收藏痕迹和控制台错误", async ({ page }) => {
    const errors = collectErrors(page);
    await installRadarFixture(page);
    await page.goto("/");
    await expect(page.locator("#newsList .news-card")).toHaveCount(2);
    expect(await page.evaluate(() => window.WorkbenchBridge.connected())).toBe(false);
    await expect(page.locator(".collect-btn")).toHaveCount(0);
    expect(errors).toEqual([]);
  });

  test("握手分别拒绝错误来源和错误窗口，仅接受真实父窗口", async ({ page }) => {
    const errors = collectErrors(page);
    await installRadarFixture(page);

    await page.goto(WRONG_ORIGIN_PARENT);
    const wrongOriginRadar = page.frameLocator("#radar");
    await expect(wrongOriginRadar.locator("#newsList .news-card")).toHaveCount(2);
    await page.evaluate(() => window.__originSpoofHello());
    await expect.poll(() => wrongOriginRadar.locator("body").evaluate(() => window.WorkbenchBridge.connected())).toBe(false);
    await expect(wrongOriginRadar.locator(".collect-btn")).toHaveCount(0);

    await page.goto(PARENT_ORIGIN);
    const radar = page.frameLocator("#radar");
    await expect(radar.locator("#newsList .news-card")).toHaveCount(2);
    await page.frameLocator("#spoof").locator("body").evaluate((_, targetOrigin) => {
      window.sendSpoofToRadar({ type: "workbench-hello" }, targetOrigin);
    }, radarOrigin);
    await expect.poll(() => radar.locator("body").evaluate(() => window.WorkbenchBridge.connected())).toBe(false);
    await expect(radar.locator(".collect-btn")).toHaveCount(0);

    await expect.poll(() => page.evaluate(() => window.__workbench.events().some((event) => event.type === "radar-ready"))).toBe(true);
    await page.evaluate(() => window.__workbench.hello());
    await expect.poll(() => radar.locator("body").evaluate(() => window.WorkbenchBridge.connected())).toBe(true);
    await expect(radar.locator(".collect-btn")).toHaveCount(2);
    expect(errors).toEqual([]);
  });

  test("真实收藏回执只接受已握手父窗口，并完成收藏和已阅", async ({ page }) => {
    const { errors, radar } = await openWorkbench(page);
    const card = radar.locator(`#newsList .news-card[data-item-id="${FIRST_ITEM.id}"]`);
    const collectButton = card.locator(".collect-btn");

    await collectButton.click();
    await expect(collectButton).toHaveText("收藏中…");
    const request = await latestRequest(page);
    expect(request.payload).toEqual({
      title: FIRST_ITEM.title,
      url: FIRST_ITEM.url,
      summary: "相关线索：收藏桥验证甲。",
      source: FIRST_ITEM.source,
      publishedAt: FIRST_ITEM.published_at,
    });

    await page.frameLocator("#spoof").locator("body").evaluate((_, { requestId, targetOrigin }) => {
      window.sendSpoofToRadar({ type: "radar-collect-result", requestId, ok: true }, targetOrigin);
    }, { requestId: request.requestId, targetOrigin: radarOrigin });
    await expect(collectButton).toHaveText("收藏中…");

    await page.evaluate(({ requestId }) => window.__workbench.reply(requestId, { ok: true }), { requestId: request.requestId });
    await expect.poll(() => radar.locator("body").evaluate((_, url) => window.WorkbenchBridge.isCollected(url), FIRST_ITEM.url)).toBe(true);
    await expect.poll(() => radar.locator("body").evaluate((_, url) => (
      JSON.parse(window.localStorage.getItem("ai-news-radar-read-items-v1") || "[]").includes(`url:${url}`)
    ), FIRST_ITEM.url)).toBe(true);
    await expect(card).toHaveCount(0);
    expect(errors).toEqual([]);
  });

  test("P6-UA-04：收藏后移出我的订阅且重复收藏明确提示", async ({ page }) => {
    workbenchRadarState = {
      ...SYNC_STATE,
      readKeys: [],
      view: {
        ...SYNC_STATE.view,
        activeSection: "creator",
        query: "",
        listSort: "priority",
        timeRangeFilter: "all",
        sourceTypeFilter: "",
        signalLevelFilter: "",
        siteFilter: "",
        mode: "all",
        allDedup: true,
        readFilter: "all",
      },
    };
    const collectRequestCount = () => page.evaluate(() => (
      window.__workbench.events().filter((event) => event.type === "radar-collect").length
    ));

    try {
      const { errors, radar } = await openWorkbench(page);
      await expect.poll(() => radar.locator("body").evaluate(() => ({
        activeSection: state.activeSection,
        readFilter: state.readFilter,
      }))).toEqual({ activeSection: "creator", readFilter: "all" });
      const subscriptionCard = radar.locator(`#newsList .news-card[data-item-id="${FIRST_ITEM.id}"]`);
      await expect(subscriptionCard).toHaveCount(1);
      await subscriptionCard.locator(".collect-btn").click();
      const request = await latestRequest(page);
      expect(await collectRequestCount()).toBe(1);

      await page.evaluate(({ requestId }) => window.__workbench.reply(requestId, { ok: true }), {
        requestId: request.requestId,
      });
      await expect.poll(() => radar.locator("body").evaluate((_, url) => (
        window.WorkbenchBridge.isCollected(url)
      ), FIRST_ITEM.url)).toBe(true);
      await radar.locator("body").evaluate(() => new Promise((resolve) => {
        requestAnimationFrame(() => requestAnimationFrame(resolve));
      }));
      await expect.poll(() => radar.locator("#newsList").evaluate((list) => ({
        loading: Boolean(list.querySelector(".list-loading")),
        settled: Boolean(list.querySelector(".news-card, .empty")),
      }))).toEqual({ loading: false, settled: true });
      await expect.soft(subscriptionCard).toHaveCount(0);

      await radar.locator('#sectionTabs [data-section="read"]').click();
      const readCard = radar.locator(`#newsList .news-card[data-item-id="${FIRST_ITEM.id}"]`);
      const repeatedCollectButton = readCard.locator(".collect-btn");
      await expect(readCard).toHaveCount(1);
      await expect.soft(repeatedCollectButton).toBeEnabled();
      await repeatedCollectButton.evaluate((button) => button.click());
      await expect.soft(repeatedCollectButton).toHaveText("已在收藏库");
      expect(await collectRequestCount()).toBe(1);
      expect(errors).toEqual([]);
    } finally {
      workbenchRadarState = null;
    }
  });

  test("P5-SYNC：既有收藏失败回归兼容适配", async ({ page, context }) => {
    test.setTimeout(45000);
    const { errors, radar } = await openWorkbench(page);
    const firstCard = radar.locator(`#newsList .news-card[data-item-id="${FIRST_ITEM.id}"]`);
    const firstCollectButton = firstCard.locator(".collect-btn");

    await firstCollectButton.click();
    const rejectedRequest = await latestRequest(page);
    await page.evaluate(({ requestId }) => window.__workbench.reply(requestId, {
      ok: false,
      error: "工作台拒绝收藏",
    }), { requestId: rejectedRequest.requestId });
    await expect(firstCollectButton).toHaveText("同步暂停");
    await expect(firstCollectButton).toHaveAttribute("title", "同步暂不可用，当前仍可阅读和打开原文");
    await expect(firstCollectButton).toBeDisabled();

    const secondCard = radar.locator(`#newsList .news-card[data-item-id="${SECOND_ITEM.id}"]`);
    await expect(secondCard.locator(".collect-btn")).toBeDisabled();
    await secondCard.locator(".read-toggle-btn").click();
    await expect(secondCard).toHaveCount(0);
    await radar.locator('#sectionTabs [data-section="read"]').click();
    const readSecondCard = radar.locator(`#newsList .news-card[data-item-id="${SECOND_ITEM.id}"]`);
    await expect(readSecondCard.locator(".read-toggle-btn")).toHaveText("恢复");
    await readSecondCard.locator(".read-toggle-btn").click();
    await radar.locator('#sectionTabs [data-section="creator"]').click();
    await expect(secondCard.locator(".collect-btn")).toBeDisabled();

    const timeoutPage = await context.newPage();
    const { errors: timeoutErrors, radar: timeoutRadar } = await openWorkbench(timeoutPage);
    const timeoutCollectButton = timeoutRadar
      .locator(`#newsList .news-card[data-item-id="${FIRST_ITEM.id}"]`)
      .locator(".collect-btn");
    await timeoutCollectButton.click();
    await latestRequest(timeoutPage);
    await expect(timeoutCollectButton).toHaveText("收藏中…");
    await expect(timeoutCollectButton).toHaveText("同步暂停", { timeout: 12000 });
    await expect(timeoutCollectButton).toHaveAttribute("title", "同步暂不可用，当前仍可阅读和打开原文");
    await expect(timeoutCollectButton).toBeDisabled();
    expect(timeoutErrors).toEqual([]);
    await timeoutPage.close();
    expect(errors).toEqual([]);
  });

  test("嵌入式雷达凭据归宿主且仍能读取脱敏信源", async ({ page }) => {
    const secretToken = "fixture-admin-token-must-stay-in-host";
    workbenchRadarConfig = { adminApiBase: radarOrigin, adminToken: secretToken };
    workbenchReaderOnly = true;
    const errors = collectErrors(page);
    try {
      await page.addInitScript(() => {
        window.localStorage.setItem("radarAdminApiBase", "https://stale-admin.example.test");
        window.localStorage.setItem("radarAdminToken", "stale-token-must-not-be-read");
      });
      await installRadarFixture(page);
      let staticFallbackRequests = 0;
      await page.route("**/config/online-sources.json", async (route) => {
        staticFallbackRequests += 1;
        await route.fulfill({ status: 500, contentType: "application/json", body: "{}" });
      });

      await page.goto(PARENT_ORIGIN);
      const radar = page.frameLocator("#radar");
      await expect(radar.locator("#newsList .news-card")).toHaveCount(2);
      await page.evaluate(() => window.__workbench.hello());
      await expect.poll(() => page.evaluate(() => window.__workbench.events()
        .some((event) => event.type === "radar-source-config-read"))).toBe(true);
      await expect(radar.locator("#onlineSourceStatus")).toContainText("已读取");
      expect(staticFallbackRequests).toBeGreaterThanOrEqual(0);
      const contentBoundary = await radar.locator("body").evaluate(() => ({
        search: window.location.search,
        base: getAdminApiBase(),
        token: getAdminToken(),
        loaded: state.onlineSourceConfigLoaded,
        sourceName: state.onlineSourceConfig?.sources?.[0]?.name || "",
      }));
      expect(contentBoundary.search).toContain("readerOnly=1");
      expect(contentBoundary.search).not.toContain("adminBase");
      expect(contentBoundary.search).not.toContain("adminToken");
      expect(contentBoundary).toMatchObject({
        base: "",
        token: "",
        loaded: true,
        sourceName: "宿主代读信源",
      });
      const bridgeMessages = await page.evaluate(() => window.__workbench.events()
        .map((event) => window.__workbench.latestMessage(event.type)));
      expect(JSON.stringify(bridgeMessages)).not.toContain(secretToken);
      expect(errors).toEqual([]);
    } finally {
      workbenchRadarConfig = null;
      workbenchReaderOnly = false;
    }
  });

  test("TASK-12：嵌入式零凭据与 capability URL 边界", async ({ page }) => {
    workbenchReaderOnly = true;
    const errors = collectErrors(page);
    try {
      await page.addInitScript(() => {
        window.localStorage.setItem("radarAdminApiBase", "https://stale-admin.example.test");
        window.localStorage.setItem("radarAdminToken", "stale-token-must-not-be-read");
      });
      await installRadarFixture(page);
      await page.goto(PARENT_ORIGIN);
      const radar = page.frameLocator("#radar");
      await expect(radar.locator("#newsList .news-card")).toHaveCount(2);
      await page.evaluate(() => window.__workbench.hello());

      const restricted = await radar.locator("body").evaluate(async () => {
        const attemptedRequests = [];
        const originalFetch = window.fetch;
        window.fetch = (...args) => {
          attemptedRequests.push(String(args[0] || ""));
          return Promise.reject(new Error("受限模式不应发出管理请求"));
        };
        openSettingsDrawer();
        document.getElementById("remoteAdminBaseInput").value = "https://blocked-admin.example.test";
        document.getElementById("remoteAdminTokenInput").value = "blocked-token";
        await connectRemoteAdmin({ preventDefault() {} });
        const result = {
          drawerHidden: document.getElementById("settingsDrawer").hidden,
          settingsHidden: getComputedStyle(document.getElementById("settingsOpenBtn")).display === "none",
          attemptedRequests,
          base: getAdminApiBase(),
          token: getAdminToken(),
        };
        window.fetch = originalFetch;
        return result;
      });

      expect(restricted).toEqual({
        drawerHidden: true,
        settingsHidden: true,
        attemptedRequests: [],
        base: "",
        token: "",
      });
      expect(errors).toEqual([]);
    } finally {
      workbenchReaderOnly = false;
    }
  });

  test("P5-SECURITY：独立管理页 Token 只发往安全地址", async ({ page }) => {
    const errors = collectErrors(page);
    await installRadarFixture(page);
    await page.goto("/");
    await expect(page.locator("#newsList .news-card")).toHaveCount(2);

    const observed = await page.evaluate(async () => {
      const fakeToken = "fixture-security-token";
      const originalFetch = window.fetch;
      const originalSetTimeout = window.setTimeout;
      const acceptedBases = [
        ["HTTPS", "https://secure-admin.example.test"],
        ["localhost HTTP", "http://localhost:19090"],
        ["IPv4 回环 HTTP", "http://127.0.0.1:19090"],
        ["IPv6 回环 HTTP", "http://[::1]:19090"],
      ];
      const rejectedBases = [
        ["非回环明文 HTTP", "http://admin.example.test"],
        ["全接口明文 HTTP", "http://0.0.0.0:19090"],
        ["localhost 子域", "http://radar.localhost:19090"],
        ["HTTP 凭据段", "http://user:pass@localhost:19090"],
        ["HTTPS 凭据段", "https://user:pass@admin.example.test"],
      ];

      function requestSnapshot(input, init = {}) {
        const inputRequest = input instanceof Request ? input : null;
        const url = new URL(inputRequest ? inputRequest.url : String(input), window.location.href);
        const headers = new Headers(init.headers || inputRequest?.headers);
        return {
          url: url.href,
          redirect: init.redirect || inputRequest?.redirect || "follow",
          hasAdminToken: headers.has("X-Admin-Token"),
        };
      }

      function responseFor(requests, input, init = {}) {
        const snapshot = requestSnapshot(input, init);
        requests.push(snapshot);
        const url = new URL(snapshot.url);
        if (url.origin === "https://redirect-source.test") {
          if (snapshot.redirect !== "manual") {
            requests.push({
              url: "https://redirect-target.test/api/local-status",
              redirect: snapshot.redirect,
              hasAdminToken: snapshot.hasAdminToken,
            });
            return Promise.resolve(new Response(JSON.stringify({ ok: true }), {
              status: 200,
              headers: { "Content-Type": "application/json" },
            }));
          }
          return Promise.resolve(new Response(null, {
            status: 302,
            headers: { Location: "https://redirect-target.test/api/local-status" },
          }));
        }
        return Promise.resolve(new Response(JSON.stringify({ ok: true }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }));
      }

      async function inspectConnect(label, base) {
        clearAdminConnection();
        const requests = [];
        window.fetch = (input, init = {}) => responseFor(requests, input, init);
        document.getElementById("remoteAdminBaseInput").value = base;
        document.getElementById("remoteAdminTokenInput").value = fakeToken;
        await connectRemoteAdmin({ preventDefault() {} });
        const result = {
          label,
          requests,
          savedBase: getAdminApiBase(),
          hasSavedToken: Boolean(getAdminToken()),
        };
        clearAdminConnection();
        return result;
      }

      async function inspectApiFetch(label, base) {
        clearAdminConnection();
        window.localStorage.setItem("radarAdminApiBase", base);
        window.localStorage.setItem("radarAdminToken", fakeToken);
        const requests = [];
        window.fetch = (input, init = {}) => responseFor(requests, input, init);
        let responseOk = false;
        let rejected = false;
        try {
          const response = await apiFetch("/api/local-status");
          responseOk = response.ok;
        } catch {
          rejected = true;
        }
        const result = { label, requests, responseOk, rejected };
        clearAdminConnection();
        return result;
      }

      window.setTimeout = () => 0;
      try {
        const rejectedConnect = [];
        const acceptedConnect = [];
        const rejectedSend = [];
        const acceptedSend = [];
        for (const [label, base] of rejectedBases) {
          rejectedConnect.push(await inspectConnect(label, base));
          rejectedSend.push(await inspectApiFetch(label, base));
        }
        for (const [label, base] of acceptedBases) {
          acceptedConnect.push(await inspectConnect(label, base));
          acceptedSend.push(await inspectApiFetch(label, base));
        }
        const redirectConnect = await inspectConnect("重定向连接探针", "https://redirect-source.test");
        const redirectSend = await inspectApiFetch("重定向通用请求", "https://redirect-source.test");
        return {
          rejectedConnect,
          acceptedConnect,
          rejectedSend,
          acceptedSend,
          redirectConnect,
          redirectSend,
        };
      } finally {
        clearAdminConnection();
        window.fetch = originalFetch;
        window.setTimeout = originalSetTimeout;
      }
    });

    for (const check of observed.rejectedConnect) {
      expect(check.requests, `${check.label}：设置连接前必须拒绝`).toEqual([]);
      expect(check.savedBase, `${check.label}：不得保存管理地址`).toBe("");
      expect(check.hasSavedToken, `${check.label}：不得保存管理 Token`).toBe(false);
    }
    for (const check of observed.rejectedSend) {
      expect(check.requests, `${check.label}：发送前复核必须阻止请求`).toEqual([]);
      expect(check.rejected, `${check.label}：通用请求必须失败关闭`).toBe(true);
    }
    for (const check of [...observed.acceptedConnect, ...observed.acceptedSend]) {
      expect(check.requests, `${check.label}：合法地址只发送一次请求`).toHaveLength(1);
      expect(check.requests[0].hasAdminToken, `${check.label}：请求携带管理 Token`).toBe(true);
      expect(check.requests[0].redirect, `${check.label}：禁止自动跟随重定向`).toBe("manual");
    }
    for (const check of observed.acceptedConnect) {
      expect(check.savedBase, `${check.label}：合法地址可保存`).not.toBe("");
      expect(check.hasSavedToken, `${check.label}：合法 Token 可保存`).toBe(true);
    }
    for (const check of observed.acceptedSend) {
      expect(check.responseOk, `${check.label}：合法地址请求成功`).toBe(true);
      expect(check.rejected, `${check.label}：合法地址不得误拒绝`).toBe(false);
    }
    expect(observed.redirectConnect.requests, "连接探针重定向只能请求初始地址").toHaveLength(1);
    expect(observed.redirectConnect.requests[0].redirect).toBe("manual");
    expect(observed.redirectConnect.savedBase, "连接探针重定向不得保存地址").toBe("");
    expect(observed.redirectConnect.hasSavedToken, "连接探针重定向不得保存 Token").toBe(false);
    expect(observed.redirectSend.requests, "通用请求重定向只能请求初始地址").toHaveLength(1);
    expect(observed.redirectSend.requests[0].redirect).toBe("manual");
    expect(observed.redirectSend.responseOk, "通用请求重定向必须失败关闭").toBe(false);
    expect(errors).toEqual([]);
  });

  test("网页内容桥只接受完整协议 v1 envelope", async ({ page }) => {
    const errors = collectErrors(page);
    await installRadarFixture(page);
    await page.goto(PARENT_ORIGIN);
    const radar = page.frameLocator("#radar");
    await expect(radar.locator("#newsList .news-card")).toHaveCount(2);

    await page.evaluate(() => window.__workbench.sendToRadar({
      type: "workbench-hello",
      requestId: "missing-version",
    }));
    await expect.poll(() => radar.locator("body").evaluate(() => window.WorkbenchBridge.connected())).toBe(false);

    const currentReadyId = await page.evaluate(() => window.__workbench.currentReadyId());
    await page.evaluate((requestId) => window.__workbench.sendToRadar({
      version: 1,
      type: "workbench-hello",
      requestId,
      state: null,
      syncAvailable: true,
      readOnly: false,
    }), currentReadyId);
    await expect.poll(() => radar.locator("body").evaluate(() => window.WorkbenchBridge.connected())).toBe(true);

    const card = radar.locator(`#newsList .news-card[data-item-id="${FIRST_ITEM.id}"]`);
    await card.locator(".collect-btn").click();
    const request = await latestRequest(page);
    await page.evaluate(({ requestId }) => window.__workbench.sendToRadar({
      version: 2,
      type: "radar-collect-result",
      requestId,
      ok: true,
    }), { requestId: request.requestId });
    await page.waitForTimeout(250);
    expect(await radar.locator("body").evaluate((_, url) => window.WorkbenchBridge.isCollected(url), FIRST_ITEM.url)).toBe(false);

    await page.evaluate(({ requestId }) => window.__workbench.sendToRadar({
      version: 1,
      type: "radar-collect-result",
      requestId,
      ok: true,
    }), { requestId: request.requestId });
    await expect.poll(() => radar.locator("body").evaluate((_, url) => (
      window.WorkbenchBridge.isCollected(url)
    ), FIRST_ITEM.url)).toBe(true);
    expect(errors).toEqual([]);
  });

  test("TASK-13：严格握手与结果类型关联", async ({ page }) => {
    const errors = collectErrors(page);
    await installRadarFixture(page);
    await page.goto(PARENT_ORIGIN);
    const radar = page.frameLocator("#radar");
    await expect(radar.locator("#newsList .news-card")).toHaveCount(2);
    await expect.poll(() => page.evaluate(() => window.__workbench.currentReadyId())).not.toBe("");
    const currentReadyId = await page.evaluate(() => window.__workbench.currentReadyId());

    await page.evaluate(() => {
      window.__workbench.sendToRadar({
        version: 1,
        type: "unknown-result",
        requestId: "unknown-result-1",
        ok: true,
      });
      window.__workbench.sendToRadar({
        version: 1,
        type: "workbench-hello",
        requestId: "oversized-hello",
        syncAvailable: true,
        readOnly: false,
        error: "x".repeat(65_536),
      });
    });
    await page.evaluate((requestId) => window.__workbench.hello(`stale-${requestId}`), currentReadyId);
    await page.waitForTimeout(250);
    expect(await radar.locator("body").evaluate(() => window.WorkbenchBridge.connected())).toBe(false);

    await page.evaluate((requestId) => window.__workbench.hello(requestId), currentReadyId);
    await expect.poll(() => radar.locator("body").evaluate(() => window.WorkbenchBridge.connected())).toBe(true);

    await radar.locator("body").evaluate(() => {
      window.__task13Result = { settled: false, type: "" };
      window.WorkbenchBridge.request("radar-collect", {
        title: "类型关联测试",
        url: "https://example.com/task-13-result-type",
      }).then((result) => {
        window.__task13Result = { settled: true, type: result.type };
      }).catch(() => {
        window.__task13Result = { settled: true, type: "rejected" };
      });
    });
    const request = await latestRequest(page);
    await page.evaluate(({ requestId }) => window.__workbench.sendToRadar({
      version: 1,
      type: "radar-state-result",
      requestId,
      ok: true,
    }), { requestId: request.requestId });
    await page.waitForTimeout(250);
    expect(await radar.locator("body").evaluate(() => window.__task13Result.settled)).toBe(false);

    await page.evaluate(({ requestId }) => window.__workbench.sendToRadar({
      version: 1,
      type: "radar-collect-result",
      requestId,
      ok: true,
    }), { requestId: request.requestId });
    await expect.poll(() => radar.locator("body").evaluate(() => window.__task13Result)).toEqual({
      settled: true,
      type: "radar-collect-result",
    });
    expect(errors).toEqual([]);
  });

  test("P4-SPEC-B02：迟到状态回执不得修改当前页面", async ({ page }) => {
    const testState = {
      ...SYNC_STATE,
      view: { ...SYNC_STATE.view, readFilter: "all" },
    };
    workbenchRadarState = testState;
    try {
      const { errors, radar } = await openWorkbench(page);
      await expect(radar.locator("#searchInput")).toHaveValue(testState.view.query);

      await page.evaluate((stateSnapshot) => window.__workbench.sendToRadar({
        version: 1,
        type: "radar-state-result",
        requestId: "late-state-result-without-pending-request",
        ok: true,
        status: 200,
        state: {
          ...stateSnapshot,
          viewRevision: stateSnapshot.viewRevision + 1,
          view: { ...stateSnapshot.view, query: "迟到回执错误覆盖" },
        },
      }), testState);
      await page.waitForTimeout(250);

      await expect(radar.locator("#searchInput")).toHaveValue(testState.view.query);
      expect(errors).toEqual([]);
    } finally {
      workbenchRadarState = null;
    }
  });

  test("P4-SPEC-B03：网页已阅交集失败立即关闭收藏", async ({ page }) => {
    workbenchRadarState = {
      ...SYNC_STATE,
      readKeys: undefined,
      view: { ...SYNC_STATE.view, readFilter: "all" },
    };
    workbenchReadStatusFailure = true;
    try {
      const { errors, radar } = await openWorkbench(page);
      await expect(radar.locator(".collect-btn")).toHaveCount(2);
      await expect(radar.locator(".collect-btn").first()).toBeDisabled();
      await expect(radar.locator(".collect-btn").first()).toHaveText("同步暂停");
      expect(await radar.locator("body").evaluate(() => window.RadarSync.canWriteCollections())).toBe(false);
      expect(errors).toEqual([]);
    } finally {
      workbenchReadStatusFailure = false;
      workbenchRadarState = null;
    }
  });

  test("P4-SPEC-B03：原生已阅交集失败立即关闭收藏", async ({ page }) => {
    const nativeState = {
      ...SYNC_STATE,
      readKeys: undefined,
      view: { ...SYNC_STATE.view, readFilter: "all" },
    };
    await page.addInitScript(({ stateSnapshot }) => {
      window.OmniaRadarHost = {
        postMessage(json) {
          const message = JSON.parse(json);
          if (message.type === "radar-ready") {
            setTimeout(() => window.WorkbenchBridge.receiveHostMessage(JSON.stringify({
              version: 1,
              type: "workbench-hello",
              requestId: message.requestId,
              state: stateSnapshot,
              syncAvailable: true,
              readOnly: false,
            })), 0);
          }
          if (message.type === "radar-read-status") {
            setTimeout(() => window.WorkbenchBridge.receiveHostMessage(JSON.stringify({
              version: 1,
              type: "radar-read-status-result",
              requestId: message.requestId,
              ok: false,
              status: 503,
              code: "read_status_unavailable",
              error: "权威已阅状态不可用",
            })), 0);
          }
        },
      };
    }, { stateSnapshot: nativeState });

    const errors = collectErrors(page);
    await installRadarFixture(page);
    await page.goto("/?omniaApp=1");
    await expect(page.locator(".collect-btn")).toHaveCount(2);
    await expect(page.locator(".collect-btn").first()).toBeDisabled();
    await expect(page.locator(".collect-btn").first()).toHaveText("同步暂停");
    expect(await page.evaluate(() => window.RadarSync.canWriteCollections())).toBe(false);
    expect(errors).toEqual([]);
  });

  test("P5-SYNC：写入失败统一暂停同步并关闭收藏", async ({ page }) => {
    test.setTimeout(60_000);
    const errors = collectErrors(page);
    const stateSnapshot = {
      ...SYNC_STATE,
      readKeys: [],
      view: { ...SYNC_STATE.view, query: "", readFilter: "all" },
    };
    const writeTypes = ["radar-view-patch", "radar-read", "radar-collect"];
    const failureModes = ["transport", "timeout", "5xx"];
    workbenchRadarState = stateSnapshot;

    await page.addInitScript(({ initialState }) => {
      if (new URLSearchParams(window.location.search).get("omniaApp") !== "1") return;
      window.OmniaRadarHost = {
        postMessage(json) {
          const message = JSON.parse(json);
          if (message.type !== "radar-ready") return;
          setTimeout(() => window.WorkbenchBridge.receiveHostMessage(JSON.stringify({
            version: 1,
            type: "workbench-hello",
            requestId: message.requestId,
            state: initialState,
            syncAvailable: true,
            readOnly: false,
          })), 0);
        },
      };
    }, { initialState: stateSnapshot });

    await installRadarFixture(page);

    const openIframeCase = async (writeType, failureMode) => {
      workbenchWriteFailure = { type: writeType, mode: failureMode };
      workbenchRequestTimeoutMs = failureMode === "timeout" ? 150 : 0;
      await page.goto(PARENT_ORIGIN);
      const radar = page.frameLocator("#radar");
      await expect.poll(() => page.evaluate(() => window.__workbench.events()
        .some((event) => event.type === "radar-ready"))).toBe(true);
      await page.evaluate(() => window.__workbench.hello());
      await expect(radar.locator("#radarSyncStatus")).toHaveText("已同步");
      await expect(radar.locator("#newsList .news-card")).toHaveCount(2);
      await expect(radar.locator(".collect-btn")).toHaveCount(2);
      return radar;
    };

    const openTransportCase = async () => {
      workbenchWriteFailure = null;
      workbenchRequestTimeoutMs = 0;
      await page.goto("/?omniaApp=1");
      await expect(page.locator("#newsList .news-card")).toHaveCount(2);
      await expect(page.locator("#radarSyncStatus")).toHaveText("已同步");
      await expect(page.locator(".collect-btn")).toHaveCount(2);
      await page.evaluate(() => { window.OmniaRadarHost = null; });
      return page;
    };

    const triggerWrite = async (radar, writeType) => {
      if (writeType === "radar-view-patch") {
        await radar.locator('[data-read-filter="unread"]').click();
      } else if (writeType === "radar-read") {
        await radar.locator(".read-toggle-btn").first().click();
      } else {
        await radar.locator(".collect-btn").first().click();
      }
    };

    const expectFailureClosed = async (radar, label) => {
      await expect.soft(radar.locator("#radarSyncStatus"), `${label} 后应公开显示同步暂停`)
        .toHaveText("同步暂停", { timeout: 1_000 });
      await expect.soft.poll(
        () => radar.locator(".collect-btn").evaluateAll((buttons) => (
          buttons.length > 0 && buttons.every((button) => button.disabled)
        )),
        { message: `${label} 后所有收藏入口都应关闭`, timeout: 1_000 },
      ).toBe(true);
    };

    try {
      for (const failureMode of failureModes) {
        for (const writeType of writeTypes) {
          const radar = failureMode === "transport"
            ? await openTransportCase()
            : await openIframeCase(writeType, failureMode);
          await triggerWrite(radar, writeType);
          await expectFailureClosed(radar, `${writeType} ${failureMode}`);
        }
      }
      expect(errors).toEqual([]);
    } finally {
      workbenchWriteFailure = null;
      workbenchRequestTimeoutMs = 0;
      workbenchRadarState = null;
    }
  });

  test("协议 v1 通过网页 postMessage 恢复完整视图并上报视图与已阅变化", async ({ page }) => {
    workbenchRadarState = SYNC_STATE;
    const errors = collectErrors(page);
    try {
      await installRadarFixture(page);
      await page.goto(PARENT_ORIGIN);
      const radar = page.frameLocator("#radar");
      await expect(radar.locator("#newsList .news-card")).toHaveCount(2);
      await page.evaluate(() => window.__workbench.hello());
      await expect.poll(() => page.evaluate(() => window.__workbench.events()
        .some((event) => event.type === "radar-ready"))).toBe(true);

      await expect.poll(() => radar.locator("body").evaluate(() => ({
        activeSection: state.activeSection,
        query: state.query,
        listSort: state.listSort,
        timeRangeFilter: state.timeRangeFilter,
        sourceTypeFilter: state.sourceTypeFilter,
        signalLevelFilter: state.signalLevelFilter,
        siteFilter: state.siteFilter,
        mode: state.mode,
        allDedup: state.allDedup,
        readFilter: state.readFilter,
      }))).toEqual(SYNC_STATE.view);
      await expect(radar.locator('#sectionTabs [data-section="bilibili"]')).toHaveAttribute("aria-pressed", "true");
      await expect(radar.locator("#searchInput")).toHaveValue(SYNC_STATE.view.query);
      await expect(radar.locator('#listSortTools [data-sort="ai"]')).toHaveClass(/active/);
      await expect(radar.locator("#timeRangeSelect")).toHaveValue("24h");
      await expect(radar.locator("#sourceTypeSelect")).toHaveValue("creator");
      await expect(radar.locator("#signalLevelSelect")).toHaveValue("high");
      await expect(radar.locator("#siteSelect")).toHaveValue("bilibili_dynamic");
      await expect(radar.locator("#modeAiBtn")).toHaveClass(/active/);
      await expect(radar.locator("#allDedupeToggle")).not.toBeChecked();
      await expect(radar.locator('[data-read-filter="read"]')).toHaveClass(/active/);
      await expect(radar.locator(`#newsList .news-card[data-item-id="${FIRST_ITEM.id}"]`)).toHaveCount(1);
      await expect(radar.locator(`#newsList .news-card[data-item-id="${SECOND_ITEM.id}"]`)).toHaveCount(0);

      await radar.locator(`#newsList .news-card[data-item-id="${FIRST_ITEM.id}"] .title`).evaluate((node) => (
        node.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }))
      ));
      await expect.poll(() => page.evaluate(() => (
        window.__workbench.latestMessage("radar-open-external")?.payload?.url || ""
      ))).toBe(FIRST_ITEM.url);

      await radar.locator('[data-read-filter="unread"]').click();
      await expect.poll(() => page.evaluate(() => (
        window.__workbench.latestMessage("radar-view-patch")?.payload?.patch?.readFilter || ""
      ))).toBe("unread");
      const unreadCard = radar.locator(`#newsList .news-card[data-item-id="${SECOND_ITEM.id}"]`);
      await expect(unreadCard).toHaveCount(1);
      await unreadCard.locator(".read-toggle-btn").click();
      await expect.poll(() => page.evaluate(() => (
        window.__workbench.latestMessage("radar-read")?.payload?.keys || []
      ))).toEqual([SECOND_ITEM.url]);
      expect(errors).toEqual([]);
    } finally {
      workbenchRadarState = null;
    }
  });

  test("TASK-11：10,000 条滚动保留与按需已阅交集", async ({ page }) => {
    const fixtureItems = Array.from({ length: 30 }, (_, index) => ({
      ...FIRST_ITEM,
      id: `task-11-item-${index}`,
      title: `按需已阅交集 ${index}`,
      url: `https://example.com/task-11/${index}?padding=${"x".repeat(1900)}`,
      published_at: `2026-07-17T09:${String(59 - index).padStart(2, "0")}:00+08:00`,
      first_seen_at: `2026-07-17T09:${String(59 - index).padStart(2, "0")}:00+08:00`,
    }));
    workbenchRadarState = {
      version: 1,
      view: { ...SYNC_STATE.view, query: "", readFilter: "all" },
      viewRevision: SYNC_STATE.viewRevision,
      updatedAt: SYNC_STATE.updatedAt,
    };
    workbenchReadKeys = [fixtureItems[0].url, fixtureItems.at(-1).url];
    const errors = collectErrors(page);
    try {
      await installRadarFixture(page, fixtureItems);
      await page.goto(PARENT_ORIGIN);
      const radar = page.frameLocator("#radar");
      await expect(radar.locator("#newsList .news-card")).toHaveCount(30);
      await page.evaluate(() => window.__workbench.hello());
      await expect.poll(() => page.evaluate(() => window.__workbench.readStatusRequests().length)).toBe(2);

      const batches = await page.evaluate(() => window.__workbench.readStatusRequests());
      expect(batches.flatMap((message) => message.payload.keys)).toEqual(fixtureItems.map((item) => item.url));
      for (const message of batches) {
        expect(message.payload.keys.length).toBeLessThanOrEqual(24);
        expect(JSON.stringify(message).length).toBeLessThanOrEqual(65_536);
      }
      await expect(radar.locator(`#newsList .news-card[data-item-id="${fixtureItems[0].id}"] .read-toggle-btn`))
        .toHaveText("已阅");
      await expect(radar.locator(`#newsList .news-card[data-item-id="${fixtureItems.at(-1).id}"] .read-toggle-btn`))
        .toHaveText("已阅");
      await expect(radar.locator(`#newsList .news-card[data-item-id="${fixtureItems[0].id}"] .read-toggle-btn`))
        .toBeDisabled();
      await expect(radar.locator(`#newsList .news-card[data-item-id="${fixtureItems.at(-1).id}"] .read-toggle-btn`))
        .toBeDisabled();
      expect(errors).toEqual([]);
    } finally {
      workbenchRadarState = null;
      workbenchReadKeys = [];
    }
  });

  test("TASK-14：一次性旧已阅迁移与服务端权威恢复", async ({ page }) => {
    workbenchRadarState = {
      version: 1,
      view: { ...SYNC_STATE.view, query: "", readFilter: "all" },
      viewRevision: SYNC_STATE.viewRevision,
      updatedAt: SYNC_STATE.updatedAt,
      legacyReadMigration: { version: 1, status: "open", migrationId: "" },
    };
    workbenchReadKeys = [];
    const errors = collectErrors(page);
    try {
      await page.addInitScript(({ readStorageKey, readKey }) => {
        window.localStorage.setItem(readStorageKey, JSON.stringify([readKey]));
      }, { readStorageKey: "ai-news-radar-read-items-v1", readKey: `url:${FIRST_ITEM.url}` });
      await installRadarFixture(page);
      await page.goto(PARENT_ORIGIN);
      let radar = page.frameLocator("#radar");
      await page.evaluate(() => window.__workbench.hello());
      await expect(radar.locator("#newsList .news-card")).toHaveCount(2);
      await expect.poll(() => page.evaluate(() => window.__workbench.migrationRequests().length)).toBeGreaterThan(0);
      const migrationRequests = await page.evaluate(() => window.__workbench.migrationRequests());
      expect(migrationRequests.at(-1).payload.complete).toBe(true);
      expect(migrationRequests.flatMap((message) => message.payload.keys)).toContain(FIRST_ITEM.url);
      expect(await page.evaluate(() => window.__workbench.latestMessage("radar-read"))).toBeNull();

      workbenchRadarState = {
        ...workbenchRadarState,
        legacyReadMigration: { version: 1, status: "complete", migrationId: "task-14-complete" },
      };
      workbenchReadKeys = [];
      await page.reload();
      radar = page.frameLocator("#radar");
      await page.evaluate(() => window.__workbench.hello());
      await expect(radar.locator("#newsList .news-card")).toHaveCount(2);
      await expect(radar.locator(`#newsList .news-card[data-item-id="${FIRST_ITEM.id}"] .read-toggle-btn`))
        .toHaveText("已阅");
      await expect(radar.locator(`#newsList .news-card[data-item-id="${FIRST_ITEM.id}"] .read-toggle-btn`))
        .toBeEnabled();
      expect(await page.evaluate(() => window.__workbench.latestMessage("radar-read"))).toBeNull();
      expect(errors).toEqual([]);
    } finally {
      workbenchRadarState = null;
      workbenchReadKeys = [];
    }
  });

  test("P5-MIGRATION：空候选不认领且 409 仲裁不暂停同步", async ({ page }) => {
    test.setTimeout(60_000);
    const errors = collectErrors(page);
    const openState = {
      version: 1,
      view: { ...SYNC_STATE.view, query: "", readFilter: "all" },
      viewRevision: SYNC_STATE.viewRevision,
      updatedAt: SYNC_STATE.updatedAt,
      legacyReadMigration: { version: 1, status: "open", migrationId: "" },
    };
    workbenchRadarState = openState;
    workbenchReadKeys = [];
    workbenchMigrationConflict = null;
    try {
      await installRadarFixture(page);
      await page.goto(PARENT_ORIGIN);
      let radar = page.frameLocator("#radar");
      await page.evaluate(() => window.__workbench.hello());
      await expect(radar.locator("#newsList .news-card")).toHaveCount(2);
      await expect.poll(() => page.evaluate(() => window.__workbench.readStatusRequests().length)).toBeGreaterThan(0);
      await expect.soft.poll(() => page.evaluate(() => window.__workbench.migrationRequests().length)).toBe(0);

      await page.addInitScript(({ readStorageKey, migrationStorageKey, readKey }) => {
        window.localStorage.setItem(readStorageKey, JSON.stringify([readKey]));
        window.localStorage.setItem(migrationStorageKey, "task-04a-browser");
      }, {
        readStorageKey: "ai-news-radar-read-items-v1",
        migrationStorageKey: "ai-news-radar-read-migration-v1",
        readKey: `url:${FIRST_ITEM.url}`,
      });

      for (const conflict of [
        {
          code: "read_migration_claimed",
          error: "旧已阅迁移已被其他浏览器认领",
          state: {
            ...openState,
            view: { ...openState.view, query: "仲裁已认领" },
            legacyReadMigration: { version: 1, status: "claimed", migrationId: "other-browser" },
          },
        },
        {
          code: "read_migration_complete",
          error: "旧已阅迁移已经永久关闭",
          state: {
            ...openState,
            view: { ...openState.view, query: "仲裁已完成" },
            legacyReadMigration: { version: 1, status: "complete", migrationId: "completed-browser" },
          },
        },
      ]) {
        workbenchMigrationConflict = conflict;
        await page.goto(PARENT_ORIGIN);
        radar = page.frameLocator("#radar");
        await page.evaluate(() => window.__workbench.hello());
        await expect(radar.locator("#newsList .news-card")).toHaveCount(2);
        await expect.poll(() => page.evaluate(() => window.__workbench.migrationRequests().length)).toBeGreaterThan(0);
        await expect.poll(() => page.evaluate(() => window.__workbench.migrationResponses().length)).toBe(1);

        const response = await page.evaluate(() => window.__workbench.migrationResponses()[0]);
        expect(response).toMatchObject({
          ok: false,
          status: 409,
          code: conflict.code,
          state: conflict.state,
        });
        await page.waitForTimeout(11_000);
        await expect.soft(radar.locator("#searchInput")).toHaveValue(conflict.state.view.query, { timeout: 1_000 });
        await expect.soft(radar.locator("#radarSyncStatus")).toHaveText("已同步", { timeout: 1_000 });
        await expect.soft(radar.locator(".collect-btn").first()).toBeEnabled({ timeout: 1_000 });
        expect.soft(await radar.locator("body").evaluate(() => window.RadarSync.canWriteCollections())).toBe(true);
      }

      expect(errors).toEqual([]);
    } finally {
      workbenchRadarState = null;
      workbenchReadKeys = [];
      workbenchMigrationConflict = null;
    }
  });

  test("omniaApp 只接受 OmniaRadarHost 原生代理并把收藏与外链交给宿主", async ({ page }) => {
    const errors = collectErrors(page);
    await page.setViewportSize({ width: 400, height: 900 });
    await page.addInitScript(({ stateSnapshot }) => {
      const messages = [];
      const hello = {
        version: 1,
        type: "workbench-hello",
        requestId: "native-hello-1",
        state: stateSnapshot,
        syncAvailable: true,
        readOnly: false,
      };
      window.__nativeHost = {
        messages,
        latest(type) {
          return messages.filter((message) => message.type === type).at(-1) || null;
        },
        reply(message) {
          window.WorkbenchBridge.receiveHostMessage(JSON.stringify(message));
        },
      };
      window.OmniaRadarHost = {
        postMessage(json) {
          if (typeof json !== "string") throw new Error("原生代理只接受 JSON 字符串");
          const message = JSON.parse(json);
          messages.push(message);
          if (message.type === "radar-ready") {
            hello.requestId = message.requestId;
            setTimeout(() => window.WorkbenchBridge.receiveHostMessage(JSON.stringify(hello)), 0);
          }
        },
      };
    }, { stateSnapshot: { ...SYNC_STATE, readKeys: [], view: { ...SYNC_STATE.view, query: "", readFilter: "all" } } });
    await installRadarFixture(page);
    await page.goto("/?omniaApp=1");
    await expect(page.locator("#newsList .news-card")).toHaveCount(2);
    await expect.poll(() => page.evaluate(() => window.WorkbenchBridge.connected())).toBe(true);
    await expect(page.locator("body")).toHaveClass(/omnia-app-mode/);
    await expect(page.locator("#settingsOpenBtn")).toBeHidden();
    await expect(page.locator(".hero-links a")).toBeHidden();
    await expect(page.locator("#settingsDrawer")).toBeHidden();

    const firstTitle = page.locator(`#newsList .news-card[data-item-id="${FIRST_ITEM.id}"] .title`);
    await firstTitle.evaluate((node) => (
      node.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }))
    ));
    await expect.poll(() => page.evaluate(() => window.__nativeHost.latest("radar-open-external")?.payload?.url || ""))
      .toBe(FIRST_ITEM.url);

    const secondCard = page.locator(`#newsList .news-card[data-item-id="${SECOND_ITEM.id}"]`);
    await secondCard.locator(".collect-btn").click();
    await expect.poll(() => page.evaluate(() => window.__nativeHost.latest("radar-collect")))
      .not.toBeNull();
    const nativeCollect = await page.evaluate(() => window.__nativeHost.latest("radar-collect"));
    expect(nativeCollect.payload.url).toBe(SECOND_ITEM.url);
    await page.evaluate(({ requestId }) => window.__nativeHost.reply({
      version: 1,
      type: "radar-collect-result",
      requestId,
      ok: true,
    }), { requestId: nativeCollect.requestId });
    await expect.poll(() => page.evaluate((url) => window.WorkbenchBridge.isCollected(url), SECOND_ITEM.url)).toBe(true);
    const width = await page.evaluate(() => ({
      scroll: document.documentElement.scrollWidth,
      client: document.documentElement.clientWidth,
    }));
    expect(width.scroll).toBeLessThanOrEqual(width.client + 1);
    expect(errors).toEqual([]);
  });

  test("omniaApp 延迟出现原生代理仍完成首屏握手", async ({ page }) => {
    test.setTimeout(10000);
    const errors = collectErrors(page);
    await page.setViewportSize({ width: 400, height: 900 });

    // 先让页面脚本在没有原生代理的真实启动条件下完成初始化，再注入延迟出现的代理。
    await installRadarFixture(page);
    await page.goto("/?omniaApp=1");
    await expect(page.locator("#newsList .news-card")).toHaveCount(2);
    expect(await page.evaluate(() => window.WorkbenchBridge.connected())).toBe(false);

    await page.evaluate(({ stateSnapshot }) => {
      const messages = [];
      const hello = {
        version: 1,
        type: "workbench-hello",
        requestId: "late-native-hello-1",
        state: stateSnapshot,
        syncAvailable: true,
        readOnly: false,
      };
      window.__lateNativeHost = {
        messages,
        latest(type) {
          return messages.filter((message) => message.type === type).at(-1) || null;
        },
      };
      window.OmniaRadarHost = {
        postMessage(json) {
          if (typeof json !== "string") throw new Error("原生代理只接受 JSON 字符串");
          const message = JSON.parse(json);
          messages.push(message);
          if (message.type === "radar-ready") {
            hello.requestId = message.requestId;
            setTimeout(() => window.WorkbenchBridge.receiveHostMessage(JSON.stringify(hello)), 0);
          }
        },
      };
    }, {
      stateSnapshot: {
        ...SYNC_STATE,
        readKeys: [],
        view: { ...SYNC_STATE.view, query: "", readFilter: "all" },
      },
    });

    await expect.poll(
      () => page.evaluate(() => window.__lateNativeHost.latest("radar-ready")),
      { timeout: 2000, intervals: [50, 100, 250] },
    ).not.toBeNull();
    await expect.poll(
      () => page.evaluate(() => window.WorkbenchBridge.connected()),
      { timeout: 1000, intervals: [50, 100, 250] },
    ).toBe(true);
    await expect(page.locator("body")).toHaveClass(/omnia-app-mode/);
    expect(errors).toEqual([]);
  });

  test("P5-APP：未握手点击原文仍交给原生宿主", async ({ page }) => {
    test.setTimeout(10000);
    const errors = collectErrors(page);
    await page.setViewportSize({ width: 400, height: 900 });
    await installRadarFixture(page);

    await page.goto("/?omniaApp=1");
    await expect(page.locator("#newsList .news-card")).toHaveCount(2);
    expect(await page.evaluate(() => window.WorkbenchBridge.connected())).toBe(false);
    const pageUrlBeforeClick = page.url();

    const firstTitle = page.locator(`#newsList .news-card[data-item-id="${FIRST_ITEM.id}"] .title`);
    await firstTitle.evaluate((node) => (
      node.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }))
    ));
    expect(page.url()).toBe(pageUrlBeforeClick);

    await page.evaluate(({ stateSnapshot }) => {
      const messages = [];
      const hello = {
        version: 1,
        type: "workbench-hello",
        requestId: "late-external-hello-1",
        state: stateSnapshot,
        syncAvailable: true,
        readOnly: false,
      };
      window.__lateExternalHost = {
        messages,
        latest(type) {
          return messages.filter((message) => message.type === type).at(-1) || null;
        },
      };
      window.OmniaRadarHost = {
        postMessage(json) {
          if (typeof json !== "string") throw new Error("原生代理只接受 JSON 字符串");
          const message = JSON.parse(json);
          messages.push(message);
          if (message.type === "radar-ready") {
            hello.requestId = message.requestId;
            setTimeout(() => window.WorkbenchBridge.receiveHostMessage(JSON.stringify(hello)), 0);
          }
        },
      };
    }, {
      stateSnapshot: {
        ...SYNC_STATE,
        readKeys: [],
        view: { ...SYNC_STATE.view, query: "", readFilter: "all" },
      },
    });

    await expect.poll(
      () => page.evaluate(() => window.WorkbenchBridge.connected()),
      { timeout: 2000, intervals: [50, 100, 250] },
    ).toBe(true);
    await expect.poll(
      () => page.evaluate(() => window.__lateExternalHost.latest("radar-open-external")?.payload?.url || ""),
      { timeout: 2000, intervals: [50, 100, 250] },
    ).toBe(FIRST_ITEM.url);
    expect(page.url()).toBe(pageUrlBeforeClick);
    expect(errors).toEqual([]);
  });

  test("P5-APP：宿主永久不可用时原文明确失败并留在当前页", async ({ page }) => {
    test.setTimeout(15000);
    const errors = collectErrors(page);
    await page.setViewportSize({ width: 400, height: 900 });
    await installRadarFixture(page);

    await page.goto("/?omniaApp=1");
    await expect(page.locator("#newsList .news-card")).toHaveCount(2);
    expect(await page.evaluate(() => window.WorkbenchBridge.connected())).toBe(false);
    const pageUrlBeforeClick = page.url();

    const firstTitle = page.locator(`#newsList .news-card[data-item-id="${FIRST_ITEM.id}"] .title`);
    await firstTitle.evaluate((node) => (
      node.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }))
    ));
    expect(page.url()).toBe(pageUrlBeforeClick);

    await expect.poll(
      () => page.evaluate(() => {
        const bridge = window.WorkbenchBridge;
        if (!bridge || typeof bridge.lastExternalOpenError !== "function") return null;
        const report = bridge.lastExternalOpenError();
        if (!report || typeof report !== "object") return null;
        return {
          url: report.url || "",
          error: typeof report.error === "string" ? report.error : "",
          connected: bridge.connected(),
        };
      }),
      { timeout: 4000, intervals: [100, 250, 500] },
    ).toEqual({
      url: FIRST_ITEM.url,
      error: expect.stringMatching(/\S/),
      connected: false,
    });

    await expect(page.locator("#radarSyncStatus")).toHaveText("同步暂停");
    expect(page.url()).toBe(pageUrlBeforeClick);
    expect(await page.evaluate(() => window.OmniaRadarHost)).toBeUndefined();
    expect(errors).toEqual([]);
  });

  test("omniaApp 未握手时首屏仍隐藏所有管理入口并保持阅读", async ({ page }) => {
    const errors = collectErrors(page);
    await page.setViewportSize({ width: 400, height: 900 });
    await installRadarFixture(page);

    await page.goto("/?omniaApp=1");

    await expect(page.locator("#newsList .news-card")).toHaveCount(2);
    expect(await page.evaluate(() => window.WorkbenchBridge.connected())).toBe(false);
    await expect(page.locator("body")).toHaveClass(/omnia-app-mode/);
    await expect(page.locator("#settingsOpenBtn")).toBeHidden();
    await expect(page.locator(".hero-links a")).toBeHidden();
    await expect(page.locator("#settingsDrawer")).toBeHidden();
    expect(errors).toEqual([]);
  });

  test("连续视图操作保持单路在途并把等待值合并为最后一次", async ({ page }) => {
    const initialState = {
      ...SYNC_STATE,
      readKeys: [],
      view: { ...SYNC_STATE.view, query: "初始查询", readFilter: "all" },
    };
    await page.addInitScript(({ stateSnapshot }) => {
      const messages = [];
      const hello = {
        version: 1,
        type: "workbench-hello",
        requestId: "native-hello-queue",
        state: stateSnapshot,
        syncAvailable: true,
        readOnly: false,
      };
      window.__nativeHost = {
        messages,
        viewPatches() {
          return messages.filter((message) => message.type === "radar-view-patch");
        },
        reply(message) {
          window.WorkbenchBridge.receiveHostMessage(JSON.stringify(message));
        },
      };
      window.OmniaRadarHost = {
        postMessage(json) {
          const message = JSON.parse(json);
          messages.push(message);
          if (message.type === "radar-ready") {
            hello.requestId = message.requestId;
            setTimeout(() => window.WorkbenchBridge.receiveHostMessage(JSON.stringify(hello)), 0);
          }
        },
      };
    }, { stateSnapshot: initialState });

    await installRadarFixture(page);
    await page.goto("/?omniaApp=1");
    await expect(page.locator("#searchInput")).toHaveValue("初始查询");
    await page.evaluate(() => {
      window.RadarSync.saveViewField("query", "第一个值");
      window.RadarSync.saveViewField("query", "第二个值");
      window.RadarSync.saveViewField("query", "最后一个值");
    });

    await expect.poll(() => page.evaluate(() => window.__nativeHost.viewPatches().length)).toBe(1);
    const first = await page.evaluate(() => window.__nativeHost.viewPatches()[0]);
    expect(first.payload).toEqual({ baseRevision: 7, patch: { query: "第一个值" } });

    await page.evaluate(({ requestId, stateSnapshot }) => window.__nativeHost.reply({
      version: 1,
      type: "radar-state-result",
      requestId,
      ok: true,
      status: 200,
      state: {
        ...stateSnapshot,
        viewRevision: 8,
        view: { ...stateSnapshot.view, query: "第一个值" },
      },
    }), { requestId: first.requestId, stateSnapshot: initialState });

    await expect.poll(() => page.evaluate(() => window.__nativeHost.viewPatches().length)).toBe(2);
    const second = await page.evaluate(() => window.__nativeHost.viewPatches()[1]);
    expect(second.payload).toEqual({ baseRevision: 8, patch: { query: "最后一个值" } });
  });

  test("TEST-018：自己点已阅或收藏后下一条顶到原位", async ({ page }) => {
    const fixtureItems = Array.from({ length: 16 }, (_, index) => ({
      ...FIRST_ITEM,
      id: `stay-018-${index}`,
      title: `停留位置夹具 ${index}`,
      url: `https://www.bilibili.com/video/stay-018-${index}`,
      source: `停留作者 ${index}`,
      published_at: `2026-07-17T09:${String(59 - index).padStart(2, "0")}:00+08:00`,
      first_seen_at: `2026-07-17T09:${String(59 - index).padStart(2, "0")}:00+08:00`,
    }));
    workbenchRadarState = {
      version: 1,
      view: {
        ...SYNC_STATE.view,
        activeSection: "creator",
        query: "",
        listSort: "time",
        readFilter: "unread",
        timeRangeFilter: "all",
        sourceTypeFilter: "",
        signalLevelFilter: "",
        siteFilter: "",
        mode: "all",
      },
      viewRevision: SYNC_STATE.viewRevision,
      updatedAt: SYNC_STATE.updatedAt,
    };
    workbenchReadKeys = [];
    const errors = collectErrors(page);

    async function waitListSettled(radar) {
      await radar.locator("body").evaluate(() => new Promise((resolve) => {
        requestAnimationFrame(() => requestAnimationFrame(resolve));
      }));
      await expect.poll(() => radar.locator("#newsList").evaluate((list) => ({
        loading: Boolean(list.querySelector(".list-loading")),
        settled: Boolean(list.querySelector(".news-card, .empty")),
      }))).toEqual({ loading: false, settled: true });
    }

    async function cardViewport(radar, itemId) {
      return radar.locator(`#newsList .news-card[data-item-id="${itemId}"]`).evaluate((node) => ({
        id: node.getAttribute("data-item-id"),
        top: node.getBoundingClientRect().top,
        scrollY: window.scrollY || document.documentElement.scrollTop || 0,
      }));
    }

    try {
      await installRadarFixture(page, fixtureItems);
      await page.goto(PARENT_ORIGIN);
      await page.locator("#radar").evaluate((frame) => {
        frame.style.width = "390px";
        frame.style.height = "640px";
        frame.style.border = "0";
      });
      const radar = page.frameLocator("#radar");
      await expect(radar.locator("#newsList .news-card")).toHaveCount(16);
      await page.evaluate(() => window.__workbench.hello());
      await expect.poll(() => radar.locator("body").evaluate(() => window.WorkbenchBridge.connected())).toBe(true);
      await expect.poll(() => radar.locator("body").evaluate(() => state.readFilter)).toBe("unread");
      await waitListSettled(radar);

      const mid = fixtureItems[8];
      const nextAfterMid = fixtureItems[9];
      const midCard = radar.locator(`#newsList .news-card[data-item-id="${mid.id}"]`);
      await midCard.scrollIntoViewIfNeeded();
      const beforeRead = await cardViewport(radar, mid.id);
      expect(beforeRead.scrollY).toBeGreaterThan(80);
      await midCard.locator(".read-toggle-btn").click();
      await waitListSettled(radar);
      await expect(midCard).toHaveCount(0);
      const afterRead = await cardViewport(radar, nextAfterMid.id);
      expect(afterRead.scrollY).toBeGreaterThan(80);
      expect(Math.abs(afterRead.top - beforeRead.top)).toBeLessThanOrEqual(64);

      const collectTarget = fixtureItems[6];
      const nextAfterCollect = fixtureItems[7];
      const collectCard = radar.locator(`#newsList .news-card[data-item-id="${collectTarget.id}"]`);
      await collectCard.scrollIntoViewIfNeeded();
      const beforeCollect = await cardViewport(radar, collectTarget.id);
      expect(beforeCollect.scrollY).toBeGreaterThan(80);
      await collectCard.locator(".collect-btn").click();
      const collectRequest = await latestRequest(page);
      await page.evaluate(({ requestId }) => window.__workbench.reply(requestId, { ok: true }), {
        requestId: collectRequest.requestId,
      });
      await expect.poll(() => radar.locator("body").evaluate((_, url) => (
        window.WorkbenchBridge.isCollected(url)
      ), collectTarget.url)).toBe(true);
      await waitListSettled(radar);
      await expect(collectCard).toHaveCount(0);
      const afterCollect = await cardViewport(radar, nextAfterCollect.id);
      expect(afterCollect.scrollY).toBeGreaterThan(80);
      expect(Math.abs(afterCollect.top - beforeCollect.top)).toBeLessThanOrEqual(64);

      const last = fixtureItems[15];
      const lastCard = radar.locator(`#newsList .news-card[data-item-id="${last.id}"]`);
      await lastCard.scrollIntoViewIfNeeded();
      const beforeLast = await cardViewport(radar, last.id);
      expect(beforeLast.scrollY).toBeGreaterThan(80);
      await lastCard.locator(".read-toggle-btn").click();
      await waitListSettled(radar);
      await expect(lastCard).toHaveCount(0);
      const afterLastScrollY = await radar.locator("body").evaluate(() => (
        window.scrollY || document.documentElement.scrollTop || 0
      ));
      expect(afterLastScrollY).toBeGreaterThan(80);
      expect(errors).toEqual([]);
    } finally {
      workbenchRadarState = null;
      workbenchReadKeys = [];
    }
  });

  test("TEST-019：自己点出去的已阅回声再画仍留在原位", async ({ page }) => {
    const fixtureItems = Array.from({ length: 16 }, (_, index) => ({
      ...FIRST_ITEM,
      id: `stay-019-${index}`,
      title: `回声停留夹具 ${index}`,
      url: `https://www.bilibili.com/video/stay-019-${index}`,
      source: `回声作者 ${index}`,
      published_at: `2026-07-17T09:${String(59 - index).padStart(2, "0")}:00+08:00`,
      first_seen_at: `2026-07-17T09:${String(59 - index).padStart(2, "0")}:00+08:00`,
    }));
    const echoView = {
      ...SYNC_STATE.view,
      activeSection: "creator",
      query: "",
      listSort: "time",
      readFilter: "unread",
      timeRangeFilter: "all",
      sourceTypeFilter: "",
      signalLevelFilter: "",
      siteFilter: "",
      mode: "all",
    };
    workbenchRadarState = {
      version: 1,
      view: echoView,
      viewRevision: SYNC_STATE.viewRevision,
      updatedAt: SYNC_STATE.updatedAt,
    };
    workbenchReadKeys = [];
    const errors = collectErrors(page);

    async function waitListSettled(radar) {
      await radar.locator("body").evaluate(() => new Promise((resolve) => {
        requestAnimationFrame(() => requestAnimationFrame(resolve));
      }));
      await expect.poll(() => radar.locator("#newsList").evaluate((list) => ({
        loading: Boolean(list.querySelector(".list-loading")),
        settled: Boolean(list.querySelector(".news-card, .empty")),
      }))).toEqual({ loading: false, settled: true });
    }

    async function cardViewport(radar, itemId) {
      return radar.locator(`#newsList .news-card[data-item-id="${itemId}"]`).evaluate((node) => ({
        id: node.getAttribute("data-item-id"),
        top: node.getBoundingClientRect().top,
        scrollY: window.scrollY || document.documentElement.scrollTop || 0,
      }));
    }

    try {
      await installRadarFixture(page, fixtureItems);
      await page.goto(PARENT_ORIGIN);
      await page.locator("#radar").evaluate((frame) => {
        frame.style.width = "390px";
        frame.style.height = "640px";
        frame.style.border = "0";
      });
      const radar = page.frameLocator("#radar");
      await expect(radar.locator("#newsList .news-card")).toHaveCount(16);
      await page.evaluate(() => window.__workbench.hello());
      await expect.poll(() => radar.locator("body").evaluate(() => window.WorkbenchBridge.connected())).toBe(true);
      await expect.poll(() => radar.locator("body").evaluate(() => state.readFilter)).toBe("unread");
      await waitListSettled(radar);

      const mid = fixtureItems[8];
      const nextAfterMid = fixtureItems[9];
      const midCard = radar.locator(`#newsList .news-card[data-item-id="${mid.id}"]`);
      await midCard.scrollIntoViewIfNeeded();
      const beforeRead = await cardViewport(radar, mid.id);
      expect(beforeRead.scrollY).toBeGreaterThan(80);
      await midCard.locator(".read-toggle-btn").click();
      await waitListSettled(radar);
      await expect(midCard).toHaveCount(0);
      const afterRead = await cardViewport(radar, nextAfterMid.id);
      expect(afterRead.scrollY).toBeGreaterThan(80);
      expect(Math.abs(afterRead.top - beforeRead.top)).toBeLessThanOrEqual(64);

      const readRequestId = await page.evaluate(() => (
        window.__workbench.latestMessage("radar-read")?.requestId || "echo-stay-019"
      ));
      await page.evaluate(({ requestId, viewSnapshot, readKey }) => {
        window.__workbench.sendToRadar({
          version: 1,
          type: "radar-state-result",
          requestId,
          ok: true,
          status: 200,
          state: {
            version: 1,
            view: viewSnapshot,
            viewRevision: 8,
            readKeys: [readKey],
            updatedAt: "2026-07-17T12:31:00+08:00",
          },
        });
      }, { requestId: readRequestId, viewSnapshot: echoView, readKey: mid.url });
      await waitListSettled(radar);
      await expect(midCard).toHaveCount(0);
      const afterEcho = await cardViewport(radar, nextAfterMid.id);
      expect(afterEcho.scrollY).toBeGreaterThan(80);
      expect(Math.abs(afterEcho.top - afterRead.top)).toBeLessThanOrEqual(64);
      expect(errors).toEqual([]);
    } finally {
      workbenchRadarState = null;
      workbenchReadKeys = [];
    }
  });
});

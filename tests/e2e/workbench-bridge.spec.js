const http = require("node:http");
const { test, expect } = require("@playwright/test");

const PARENT_PORT = 8765;
const PARENT_ORIGIN = `http://127.0.0.1:${PARENT_PORT}`;
const WRONG_ORIGIN_PORT = 8766;
const WRONG_ORIGIN_PARENT = `http://127.0.0.1:${WRONG_ORIGIN_PORT}`;
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

async function installRadarFixture(page) {
  const responses = new Map([
    ["/data/latest-24h.json", NEWS_PAYLOAD],
    ["/data/latest-24h-all.json", NEWS_PAYLOAD],
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

function workbenchHtml(radarUrl) {
  return `<!doctype html>
<html lang="zh-CN">
  <body>
    <iframe id="radar" title="真实雷达"></iframe>
    <iframe id="spoof" title="同源伪造页" src="/spoof"></iframe>
    <script>
      const radarOrigin = ${JSON.stringify(new URL(radarUrl).origin)};
      const radar = document.getElementById("radar");
      const events = [];
      const requests = new Map();
      radar.src = ${JSON.stringify(radarUrl)};

      window.addEventListener("message", (event) => {
        if (event.origin !== radarOrigin || event.source !== radar.contentWindow) return;
        const data = event.data;
        if (!data || typeof data !== "object") return;
        events.push({ type: data.type, requestId: data.requestId || "", origin: event.origin });
        if (data.type === "radar-collect") {
          requests.set(data.requestId, { source: event.source, origin: event.origin, requestId: data.requestId, payload: data.payload });
        }
      });

      window.__workbench = {
        hello() {
          radar.contentWindow.postMessage({ type: "workbench-hello" }, radarOrigin);
        },
        events() {
          return events.slice();
        },
        latestRequest() {
          const requestsInOrder = Array.from(requests.values());
          const request = requestsInOrder[requestsInOrder.length - 1];
          return request && { requestId: request.requestId, payload: request.payload, origin: request.origin };
        },
        reply(requestId, result) {
          const request = requests.get(requestId);
          if (!request) throw new Error("未找到收藏请求");
          request.source.postMessage({ type: "radar-collect-result", requestId, ...result }, request.origin);
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

function startServer(port, handler, portDescription) {
  return new Promise((resolve, reject) => {
    const server = http.createServer(handler);
    const onError = (error) => {
      if (error.code === "EADDRINUSE") {
        reject(new Error(`${portDescription} 已被占用，请先关闭占用该端口的工作台或测试服务。`));
        return;
      }
      reject(error);
    };
    server.once("error", onError);
    server.listen(port, "127.0.0.1", () => {
      server.off("error", onError);
      resolve(server);
    });
  });
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
  await page.evaluate(() => window.__workbench.hello());
  await expect.poll(() => page.evaluate(() => window.__workbench.events().some((event) => event.type === "radar-ready"))).toBe(true);
  await expect(radar.locator(".collect-btn")).toHaveCount(2);
  return { errors, radar };
}

async function latestRequest(page) {
  await expect.poll(() => page.evaluate(() => Boolean(window.__workbench.latestRequest()))).toBe(true);
  return page.evaluate(() => window.__workbench.latestRequest());
}

test.describe("工作台收藏桥", () => {
  test.describe.configure({ mode: "serial" });

  test.beforeAll(async ({ browser }, testInfo) => {
    void browser;
    const baseURL = testInfo.project.use.baseURL;
    radarOrigin = new URL(baseURL).origin;
    parentServer = await startServer(PARENT_PORT, (request, response) => {
      if (request.url === "/spoof") return sendHtml(response, spoofHtml());
      return sendHtml(response, workbenchHtml(baseURL));
    }, "8765 端口（真实工作台）");
    wrongOriginServer = await startServer(WRONG_ORIGIN_PORT, (_request, response) => (
      sendHtml(response, wrongOriginHtml(baseURL))
    ), "8766 端口（错误来源测试页）");
  });

  test.afterAll(async () => {
    await closeServer(wrongOriginServer);
    await closeServer(parentServer);
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

    await page.evaluate(() => window.__workbench.hello());
    await expect.poll(() => page.evaluate(() => window.__workbench.events().some((event) => event.type === "radar-ready"))).toBe(true);
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

  test("失败和超时都会恢复按钮，其他卡片和已阅功能仍可用", async ({ page }) => {
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
    await expect(firstCollectButton).toHaveText("收藏失败");
    await expect(firstCollectButton).toHaveAttribute("title", "工作台拒绝收藏");
    await expect(firstCollectButton).toBeDisabled();
    await expect(firstCollectButton).toBeEnabled({ timeout: 5000 });
    await expect(firstCollectButton).toHaveText("收藏");
    await expect(firstCollectButton).toHaveAttribute("title", COLLECT_IDLE_TITLE);

    const secondCard = radar.locator(`#newsList .news-card[data-item-id="${SECOND_ITEM.id}"]`);
    await expect(secondCard.locator(".collect-btn")).toBeEnabled();
    await secondCard.locator(".read-toggle-btn").click();
    await expect(secondCard).toHaveCount(0);
    await radar.locator('#sectionTabs [data-section="read"]').click();
    const readSecondCard = radar.locator(`#newsList .news-card[data-item-id="${SECOND_ITEM.id}"]`);
    await expect(readSecondCard.locator(".read-toggle-btn")).toHaveText("恢复");
    await readSecondCard.locator(".read-toggle-btn").click();
    await radar.locator('#sectionTabs [data-section="creator"]').click();
    await expect(secondCard.locator(".collect-btn")).toBeEnabled();

    await firstCollectButton.click();
    await latestRequest(page);
    await expect(firstCollectButton).toHaveText("收藏中…");
    await expect(firstCollectButton).toHaveText("收藏失败", { timeout: 12000 });
    await expect(firstCollectButton).toHaveAttribute("title", "工作台响应超时");
    await expect(firstCollectButton).toBeDisabled();
    await expect(firstCollectButton).toBeEnabled({ timeout: 5000 });
    await expect(firstCollectButton).toHaveText("收藏");
    await expect(firstCollectButton).toHaveAttribute("title", COLLECT_IDLE_TITLE);
    expect(errors).toEqual([]);
  });
});

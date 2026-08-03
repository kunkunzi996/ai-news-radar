const { test, expect } = require("@playwright/test");

async function installWindowOpenRecorder(page) {
  await page.addInitScript(() => {
    window.__openedWindows = [];
    window.open = (url) => {
      const popup = {
        location: { href: String(url) },
        closed: false,
        opener: window,
        close() {
          this.closed = true;
        },
      };
      window.__openedWindows.push(popup);
      return popup;
    };
  });
}

async function openLocalCollectionSettings(page) {
  await page.locator("#settingsOpenBtn").click();
  await page.locator('[data-settings-tab="local"]').click();
  await expect(page.locator("#weMpRssStartBtn")).toBeVisible();
}

async function openedWindows(page) {
  return page.evaluate(() => window.__openedWindows.map((popup) => ({
    href: popup.location.href,
    closed: popup.closed,
    openerIsNull: popup.opener === null,
  })));
}

test("iframe 存储不可用时，URL 配置仍能读取线上信源", async ({ page, baseURL }) => {
  const errors = [];
  page.on("pageerror", (error) => errors.push(`pageerror: ${error}`));
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(`console: ${message.text()}`);
  });

  await page.addInitScript(() => {
    const originalGetItem = Storage.prototype.getItem;
    Storage.prototype.getItem = function blockedAdminStorage(key) {
      if (key === "radarAdminApiBase" || key === "radarAdminToken") {
        throw new Error("iframe storage blocked");
      }
      return originalGetItem.call(this, key);
    };
  });

  const authHeaders = [];
  let staticFallbackRequests = 0;
  await page.route("**/api/online-source-config", async (route) => {
    authHeaders.push(route.request().headers()["x-admin-token"] || "");
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ ok: true, source_count: 0, sources: [] }),
    });
  });
  await page.route("**/config/online-sources.json", async (route) => {
    staticFallbackRequests += 1;
    await route.fulfill({ status: 500, contentType: "application/json", body: "{}" });
  });

  const adminToken = "fixture-admin-token";
  const url = new URL("/", baseURL);
  url.searchParams.set("adminBase", baseURL);
  url.searchParams.set("adminToken", adminToken);
  await page.goto(url.toString());

  await expect(page.locator("#onlineSourceStatus")).toContainText("已读取");
  expect(authHeaders).toContain(adminToken);
  expect(staticFallbackRequests).toBe(0);
  expect(await page.evaluate(() => ({
    base: getAdminApiBase(),
    token: getAdminToken(),
    loaded: state.onlineSourceConfigLoaded,
  }))).toEqual({ base: baseURL, token: adminToken, loaded: true });
  expect(errors).toEqual([]);
});

test("远程模式启动微信采集只打开公网后台", async ({ page, baseURL, context }) => {
  const requests = [];
  await context.route("https://wechat.wanyouomnia.cn/**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "text/html",
      body: "<!doctype html><title>wechat-admin-fixture</title>",
    });
  });
  await page.route("**/api/maintenance-action", async (route) => {
    requests.push({
      body: route.request().postDataJSON(),
      token: route.request().headers()["x-admin-token"] || "",
    });
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        ok: true,
        already_running: true,
        url: "http://127.0.0.1:8001",
        local_url: "http://127.0.0.1:8001",
        public_url: "https://wechat.wanyouomnia.cn",
      }),
    });
  });

  const adminToken = "fixture-admin-token";
  const url = new URL("/", baseURL);
  url.searchParams.set("adminBase", baseURL);
  url.searchParams.set("adminToken", adminToken);
  await page.goto(url.toString());
  await openLocalCollectionSettings(page);
  const popupPromise = page.waitForEvent("popup");
  await page.locator("#weMpRssStartBtn").click();
  const popup = await popupPromise;

  await expect.poll(() => popup.url()).toBe("https://wechat.wanyouomnia.cn/");
  await expect(popup).toHaveTitle("wechat-admin-fixture");
  expect(requests).toEqual([{
    body: { action_id: "start_we_mp_rss_sidecar" },
    token: adminToken,
  }]);
});

test("远程模式缺少公网地址时关闭空白窗口且绝不回退本机", async ({ page, baseURL }) => {
  await installWindowOpenRecorder(page);
  await page.route("**/api/maintenance-action", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        ok: true,
        url: "http://127.0.0.1:8001",
        local_url: "http://127.0.0.1:8001",
        public_url: "",
      }),
    });
  });

  const url = new URL("/", baseURL);
  url.searchParams.set("adminBase", baseURL);
  url.searchParams.set("adminToken", "fixture-admin-token");
  await page.goto(url.toString());
  await openLocalCollectionSettings(page);
  await page.locator("#weMpRssStartBtn").click();

  await expect(page.locator("#sourceConfigStatus")).toContainText(
    "微信后台公网地址未配置，请先在 NUC 配置安全访问入口。",
  );
  await expect.poll(() => openedWindows(page)).toEqual([{
    href: "about:blank",
    closed: true,
    openerIsNull: true,
  }]);
});

test("本机模式优先打开本地地址并兼容旧响应", async ({ page }) => {
  await installWindowOpenRecorder(page);
  let requestCount = 0;
  await page.route("**/api/maintenance-action", async (route) => {
    requestCount += 1;
    const payload = requestCount === 1
      ? {
          ok: true,
          local_url: "http://127.0.0.1:8011",
          url: "http://127.0.0.1:8022",
          public_url: "https://wechat.wanyouomnia.cn",
        }
      : {
          ok: true,
          url: "http://127.0.0.1:8033",
        };
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(payload),
    });
  });

  await page.goto("/");
  await openLocalCollectionSettings(page);
  const startButton = page.locator("#weMpRssStartBtn");
  await startButton.click();
  await expect.poll(() => openedWindows(page)).toEqual([{
    href: "http://127.0.0.1:8011",
    closed: false,
    openerIsNull: true,
  }]);

  await expect(startButton).toBeEnabled();
  await startButton.click();
  await expect.poll(() => openedWindows(page)).toEqual([
    { href: "http://127.0.0.1:8011", closed: false, openerIsNull: true },
    { href: "http://127.0.0.1:8033", closed: false, openerIsNull: true },
  ]);
});

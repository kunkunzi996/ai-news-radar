const { test, expect } = require("@playwright/test");

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

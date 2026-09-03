const { test, expect } = require("@playwright/test");

const emptyConfig = {
  ok: true,
  config: { version: "1.0", sources: [] },
  base_config_digest: "d".repeat(64),
  etag: '"d'.concat("d".repeat(63), '"'),
  recovery: null,
};

const crawlerConfig = {
  ...emptyConfig,
  config: {
    version: "1.0",
    sources: [
      {
        id: "online_bilibili_crawler",
        name: "技术爬爬虾",
        type: "bilibili_dynamic",
        enabled: true,
        locator: "316183842",
      },
    ],
  },
};

function collectErrors(page, errors) {
  page.on("pageerror", (err) => errors.push(`pageerror: ${err}`));
  page.on("console", (msg) => {
    if (msg.type() === "error") errors.push(`console: ${msg.text()}`);
  });
}

async function mockOnlineConfig(page, config) {
  await page.route("**/api/online-source-config", async (route) => {
    if (route.request().method() === "GET") {
      await route.fulfill({
        status: 200,
        headers: { ETag: config.etag },
        json: config,
      });
      return;
    }
    await route.fallback();
  });
}

async function openSourcesSettings(page) {
  const configLoaded = page.waitForResponse("**/api/online-source-config");
  await page.goto("/");
  await configLoaded;
  await page.locator("#settingsOpenBtn").click();
  await page.locator('[data-settings-tab="sources"]').click();
}

test("TEST-041：设置页是一张表，没有订阅成员和保存并同步", async ({ page }) => {
  await mockOnlineConfig(page, emptyConfig);
  await openSourcesSettings(page);
  const pane = page.locator('[data-settings-pane="sources"]');
  const drawer = page.locator("#settingsDrawer");
  await expect(pane.getByRole("button", { name: "全部" })).toBeVisible();
  await expect(pane.getByRole("button", { name: "B站" })).toBeVisible();
  await expect(pane.getByRole("button", { name: "油管" })).toBeVisible();
  await expect(pane.getByRole("button", { name: "抖音" })).toBeVisible();
  await expect(pane.getByRole("button", { name: "GitHub" })).toBeVisible();
  await expect(drawer.getByText("订阅成员")).toHaveCount(0);
  await expect(drawer.getByRole("button", { name: "保存并同步" })).toHaveCount(0);
  await expect(drawer).not.toContainText("保存并同步");
  const typeLabels = await page.locator("#onlineSourceType option").allTextContents();
  expect(typeLabels.join(" ")).not.toMatch(/小红书|微信/);
});

test("TEST-041：空名单显示还没有人", async ({ page }) => {
  await mockOnlineConfig(page, emptyConfig);
  await openSourcesSettings(page);
  await expect(page.locator("#onlineSourceList")).toContainText("还没有人");
});

test("TEST-041：只读模式没有设置按钮", async ({ page }) => {
  await mockOnlineConfig(page, emptyConfig);
  await page.goto("/?readerOnly=1");
  await expect(page.locator("#settingsOpenBtn")).toBeHidden();
});

test("TEST-042：填名称定位后点加入会发 save-and-sync", async ({ page }) => {
  const errors = [];
  const posts = [];
  collectErrors(page, errors);
  await mockOnlineConfig(page, emptyConfig);
  await page.route("**/api/save-and-sync-online-source-config", async (route) => {
    posts.push({
      body: route.request().postDataJSON(),
      etag: route.request().headers()["if-match"],
    });
    const body = route.request().postDataJSON() || {};
    await route.fulfill({
      status: 200,
      headers: { ETag: emptyConfig.etag },
      json: {
        ok: true,
        outcome: "pushed",
        pushed: true,
        commit: "test-commit",
        config: { version: "1.0", sources: body.sources || [] },
        etag: emptyConfig.etag,
        base_config_digest: emptyConfig.base_config_digest,
      },
    });
  });
  await openSourcesSettings(page);
  await page.locator("#onlineSourceName").fill("测试UP");
  await page.locator("#onlineSourceLocator").fill("123456");
  await expect(page.getByRole("button", { name: "加入" })).toBeVisible();
  await page.getByRole("button", { name: "加入" }).click();
  await expect.poll(() => posts.length).toBe(1);
  expect(posts[0].etag).toBe(emptyConfig.etag);
  expect(JSON.stringify(posts[0].body.sources || [])).toContain("测试UP");
  await expect(page.locator("#onlineSourceList")).toContainText("测试UP");
  await expect(page.locator("#onlineSourceList")).toContainText("待采集");
  expect(errors.filter((message) => !message.includes("status of 409"))).toEqual([]);
});

test("TEST-042：空字段点加入不发 POST", async ({ page }) => {
  const posts = [];
  await mockOnlineConfig(page, emptyConfig);
  await page.route("**/api/save-and-sync-online-source-config", async (route) => {
    posts.push(true);
    await route.fulfill({ status: 200, json: emptyConfig });
  });
  await openSourcesSettings(page);
  await expect(page.getByRole("button", { name: "加入" })).toBeVisible();
  await page.getByRole("button", { name: "加入" }).click();
  await expect(page.locator("#onlineSourceStatus")).toContainText("名称和关键字段");
  expect(posts).toEqual([]);
  await expect(page.locator("#onlineSourceList")).not.toContainText("测试UP");
});

test("TEST-042：保存 409 后面单回到操作前", async ({ page }) => {
  await mockOnlineConfig(page, emptyConfig);
  await page.route("**/api/save-and-sync-online-source-config", async (route) => {
    await route.fulfill({
      status: 409,
      json: { ok: false, error: "online_sources_preflight_failed" },
    });
  });
  await openSourcesSettings(page);
  await page.locator("#onlineSourceName").fill("不会留下");
  await page.locator("#onlineSourceLocator").fill("999");
  await expect(page.getByRole("button", { name: "加入" })).toBeVisible();
  await page.getByRole("button", { name: "加入" }).click();
  await expect(page.locator("#onlineSourceStatus")).toContainText("失败");
  await expect(page.locator("#onlineSourceList")).not.toContainText("不会留下");
  await expect(page.locator("#onlineSourceList")).toContainText("还没有人");
});

test("TEST-042：删除确认后 POST 不含该 id", async ({ page }) => {
  const posts = [];
  await mockOnlineConfig(page, crawlerConfig);
  await page.route("**/api/save-and-sync-online-source-config", async (route) => {
    posts.push(route.request().postDataJSON());
    await route.fulfill({
      status: 200,
      json: {
        ok: true,
        outcome: "pushed",
        pushed: true,
        config: { version: "1.0", sources: [] },
        etag: crawlerConfig.etag,
      },
    });
  });
  page.once("dialog", (dialog) => dialog.accept());
  await openSourcesSettings(page);
  await page.locator("#onlineSourceList").getByRole("button", { name: "删除" }).click();
  await expect.poll(() => posts.length).toBe(1);
  const ids = (posts[0].sources || []).map((source) => source.id);
  expect(ids).not.toContain("online_bilibili_crawler");
});

test("TEST-043：停用确认后行仍在且 POST enabled 为 false", async ({ page }) => {
  const posts = [];
  const dialogs = [];
  await mockOnlineConfig(page, crawlerConfig);
  await page.route("**/api/save-and-sync-online-source-config", async (route) => {
    const body = route.request().postDataJSON() || {};
    posts.push(body);
    await route.fulfill({
      status: 200,
      json: {
        ok: true,
        outcome: "pushed",
        pushed: true,
        config: { version: "1.0", sources: body.sources || [] },
        etag: crawlerConfig.etag,
      },
    });
  });
  page.once("dialog", (dialog) => {
    dialogs.push(dialog.message());
    dialog.accept();
  });
  await openSourcesSettings(page);
  await page.locator("#onlineSourceList").getByRole("checkbox").uncheck();
  await expect.poll(() => posts.length).toBe(1);
  expect(dialogs.join("")).toContain("下次采集");
  await expect(page.locator("#onlineSourceList")).toContainText("技术爬爬虾");
  await expect(page.locator("#onlineSourceList").getByRole("checkbox")).not.toBeChecked();
  const saved = (posts[0].sources || []).find((source) => source.id === "online_bilibili_crawler");
  expect(saved).toBeTruthy();
  expect(saved.enabled).toBe(false);
});

test("TEST-043：删除点取消不发 POST 且行仍在", async ({ page }) => {
  const posts = [];
  await mockOnlineConfig(page, crawlerConfig);
  await page.route("**/api/save-and-sync-online-source-config", async (route) => {
    posts.push(route.request().postDataJSON());
    await route.fulfill({ status: 200, json: crawlerConfig });
  });
  page.once("dialog", (dialog) => dialog.dismiss());
  await openSourcesSettings(page);
  await page.locator("#onlineSourceList").getByRole("button", { name: "删除" }).click();
  await expect(page.locator("#onlineSourceList")).toContainText("技术爬爬虾");
  expect(posts).toEqual([]);
});

test("TEST-043：删除确认后行消失", async ({ page }) => {
  await mockOnlineConfig(page, crawlerConfig);
  await page.route("**/api/save-and-sync-online-source-config", async (route) => {
    await route.fulfill({
      status: 200,
      json: {
        ok: true,
        outcome: "pushed",
        pushed: true,
        config: { version: "1.0", sources: [] },
        etag: crawlerConfig.etag,
      },
    });
  });
  page.once("dialog", (dialog) => {
    expect(dialog.message()).toContain("下次采集");
    dialog.accept();
  });
  await openSourcesSettings(page);
  await page.locator("#onlineSourceList").getByRole("button", { name: "删除" }).click();
  await expect(page.locator("#onlineSourceList")).not.toContainText("技术爬爬虾");
});


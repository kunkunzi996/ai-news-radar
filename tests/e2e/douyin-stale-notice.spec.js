const { test, expect } = require("@playwright/test");

const NOW = "2026-10-02T12:00:00Z";
const GENERATED_AT = "2026-10-02T11:30:00Z";

function statusWithCollectionAt(collectionGeneratedAt) {
  const site = {
    site_id: "mediacrawler_douyin",
    site_name: "抖音",
    ok: true,
    partial: false,
    item_count: 1,
  };
  if (collectionGeneratedAt) site.collection_generated_at = collectionGeneratedAt;
  return {
    generated_at: GENERATED_AT,
    sites: [site],
    failed_sites: [],
    rss_opml: { enabled: false, failed_feeds: [] },
  };
}

function jsonResponse(body) {
  return { status: 200, contentType: "application/json", body: JSON.stringify(body) };
}

async function openWithStatus(page, status) {
  await page.clock.install({ time: new Date(NOW) });
  await page.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    if (path === "/data/source-status.json") {
      await route.fulfill(jsonResponse(status));
      return;
    }
    if (path === "/api/local-status") {
      await route.fulfill(jsonResponse({
        ok: true,
        source_status: status,
        source_config: { enabled_sources: [] },
        collectors: {},
        refresh_running: false,
      }));
      return;
    }
    await route.continue();
  });
  await page.goto("/");
  await expect(page.locator("#sourceStatusPill")).toContainText("正常");
}

test("抖音超过两天没采成功时，订阅页直接写出停了几天", async ({ page }) => {
  await openWithStatus(page, statusWithCollectionAt("2026-09-29T12:00:00Z"));
  await expect(page.locator("#douyinStaleNotice")).toHaveText("抖音已经3天没采到新内容");
  await expect(page.locator("#douyinStaleNotice")).toBeInViewport();
  await expect(page.locator("#settingsOpenBtn")).toBeInViewport();
});

test("不满两天时不显示停更提醒", async ({ page }) => {
  await openWithStatus(page, statusWithCollectionAt("2026-09-30T13:00:00Z"));
  await expect(page.locator("#douyinStaleNotice")).toBeHidden();
});

test("没有采集时间时不编造停更提醒", async ({ page }) => {
  await openWithStatus(page, statusWithCollectionAt(""));
  await expect(page.locator("#douyinStaleNotice")).toBeHidden();
});

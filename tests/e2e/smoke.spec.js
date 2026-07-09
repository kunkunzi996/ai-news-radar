const { test, expect } = require("@playwright/test");

function collectErrors(page, errors) {
  page.on("pageerror", (err) => errors.push(`pageerror: ${err}`));
  page.on("console", (msg) => {
    if (msg.type() === "error") errors.push(`console: ${msg.text()}`);
  });
}

test("home page loads without runtime errors", async ({ page }) => {
  const errors = [];
  collectErrors(page, errors);
  await page.goto("/");
  await expect(page.locator("#sectionTabs")).toBeVisible();
  await expect(page.locator("#newsList")).toBeAttached();
  await page.waitForTimeout(1500);
  expect(errors).toEqual([]);
});

test("tabs and time range filter do not throw", async ({ page }) => {
  const errors = [];
  collectErrors(page, errors);
  await page.goto("/");
  const tabs = page.locator("#sectionTabs button");
  const count = await tabs.count();
  for (let i = 0; i < Math.min(count, 3); i += 1) {
    await tabs.nth(i).click();
    await page.waitForTimeout(300);
  }
  await page.locator("details.advanced-panel > summary").first().click();
  await page.locator("#timeRangeSelect").selectOption("24h");
  await page.waitForTimeout(500);
  expect(errors).toEqual([]);
});

test("remote data base query loads data files", async ({ page }) => {
  const errors = [];
  collectErrors(page, errors);
  await page.goto("/?dataBase=http://127.0.0.1:8080/data/");
  await expect(page.locator("#dataSourcePill")).toContainText("远程数据");
  await expect(page.locator("#sectionTabs")).toBeVisible();
  await page.waitForTimeout(1000);
  expect(errors).toEqual([]);
});

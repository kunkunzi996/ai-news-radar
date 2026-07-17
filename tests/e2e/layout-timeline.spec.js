const { test, expect } = require("@playwright/test");

const GENERATED_AT = "2026-07-15T12:00:00+08:00";

function makeItem(index, overrides = {}) {
  const publishedAt = new Date(Date.parse(GENERATED_AT) - (index + 1) * 10 * 60 * 1000).toISOString();
  return {
    id: `fixture-${index + 1}`,
    site_id: "bilibili_dynamic",
    site_name: "B站",
    source: `测试作者 ${String((index % 8) + 1).padStart(2, "0")}`,
    title: `固定测试内容 ${String(index + 1).padStart(2, "0")}`,
    title_zh: "",
    title_en: "",
    url: `https://www.bilibili.com/video/fixture-${index + 1}`,
    published_at: publishedAt,
    first_seen_at: publishedAt,
    ai_score: 0.4 + (index % 5) * 0.05,
    creator_hot_score: 35 + (index % 10),
    ai_label: "ai_general",
    ai_signals: ["fixture"],
    source_tier: "creator",
    source_tier_rank: 3,
    ...overrides,
  };
}

const REGULAR_ITEMS = Array.from({ length: 76 }, (_, index) => makeItem(index));
REGULAR_ITEMS.slice(10, 30).forEach((item) => {
  item.source = "批量来源";
});
REGULAR_ITEMS[0] = makeItem(0, {
  id: "sort-time",
  title: "时间排序首条",
  published_at: "2026-07-15T11:59:00+08:00",
  first_seen_at: "2026-07-15T11:59:00+08:00",
});
REGULAR_ITEMS[1] = makeItem(1, {
  id: "sort-priority",
  source: "综合排序作者",
  title: "综合排序首条",
  published_at: "2026-07-15T10:00:00+08:00",
  first_seen_at: "2026-07-15T10:00:00+08:00",
  creator_hot_score: 100,
});
REGULAR_ITEMS[2] = makeItem(2, {
  id: "sort-ai",
  source: "高分排序作者",
  title: "高分排序首条",
  published_at: "2026-07-15T09:50:00+08:00",
  first_seen_at: "2026-07-15T09:50:00+08:00",
  ai_score: 1,
});
REGULAR_ITEMS[3] = makeItem(3, {
  id: "read-target",
  title: "唯一检索词 KUNKUN-TIMELINE",
  published_at: "2026-07-15T09:40:00+08:00",
  first_seen_at: "2026-07-15T09:40:00+08:00",
});
REGULAR_ITEMS[4] = makeItem(4, {
  id: "midnight",
  title: "午夜时间格式",
  published_at: "2026-07-15T00:05:00+08:00",
  first_seen_at: "2026-07-15T00:05:00+08:00",
});
REGULAR_ITEMS[5] = makeItem(5, {
  id: "long-layout",
  source: "这是一个用于验证窄屏不会溢出的非常非常长的作者名称",
  title: "NO_BREAK_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
});
REGULAR_ITEMS[6] = makeItem(6, {
  id: "xss-text",
  title: '<img src=x onerror="window.__fixtureXss=true">只应显示为文本',
});
REGULAR_ITEMS[10] = makeItem(10, {
  id: "source-leader",
  source: "批量来源",
  title: "来源排序首条",
  creator_hot_score: 99,
});

const PLATFORM_FIXTURES = [
  [68, { id: "douyin-alpha", site_id: "mediacrawler_douyin", site_name: "抖音", source: "抖音甲", url: "https://www.douyin.com/video/fixture-alpha" }],
  [69, { id: "douyin-beta", site_id: "mediacrawler_douyin", site_name: "抖音", source: "抖音乙", url: "https://www.douyin.com/video/fixture-beta" }],
  [70, { id: "xhs-alpha", site_id: "mediacrawler_xhs", site_name: "小红书", source: "小红书甲", url: "https://www.xiaohongshu.com/explore/fixture-alpha" }],
  [71, { id: "xhs-beta", site_id: "mediacrawler_xhs", site_name: "小红书", source: "小红书乙", url: "https://www.xiaohongshu.com/explore/fixture-beta" }],
  [72, { id: "youtube-alpha", site_id: "opmlrss", site_name: "YouTube", source: "YouTube 甲", url: "https://www.youtube.com/watch?v=fixture-alpha" }],
  [73, { id: "youtube-beta", site_id: "opmlrss", site_name: "YouTube", source: "YouTube 乙", url: "https://www.youtube.com/watch?v=fixture-beta" }],
  [74, { id: "github-alpha", site_id: "github_foundation_sunshine_releases", site_name: "GitHub Release", source: "项目甲", url: "https://github.com/example/alpha/releases/tag/v1" }],
  [75, { id: "github-beta", site_id: "github_foundation_sunshine_releases", site_name: "GitHub Release", source: "项目乙", url: "https://github.com/example/beta/releases/tag/v1" }],
];
PLATFORM_FIXTURES.forEach(([index, overrides]) => {
  REGULAR_ITEMS[index] = makeItem(index, overrides);
});

const SPECIAL_ITEMS = [
  makeItem(76, {
    id: "future-fallback",
    source: "未来时间作者",
    title: "未来发布时间回退",
    published_at: "2026-07-16T09:00:00+08:00",
    first_seen_at: "2026-07-15T11:55:00+08:00",
  }),
  makeItem(77, {
    id: "broken-published",
    source: "损坏时间作者",
    title: "损坏发布时间回退",
    published_at: "not-a-date",
    first_seen_at: "2026-07-14T08:30:00+08:00",
  }),
  makeItem(78, {
    id: "wechat-alpha",
    site_id: "we_mp_rss_jsonl",
    site_name: "WeRSS 公众号",
    source: "甲号",
    title: "甲号固定文章",
    url: "https://mp.weixin.qq.com/s/fixture-alpha",
    published_at: "2026-07-15T08:00:00+08:00",
    first_seen_at: "2026-07-15T08:00:00+08:00",
  }),
  makeItem(79, {
    id: "wechat-beta",
    site_id: "we_mp_rss_jsonl",
    site_name: "WeRSS 公众号",
    source: "乙号",
    title: "乙号固定文章",
    url: "https://mp.weixin.qq.com/s/fixture-beta",
    published_at: "2026-07-14T07:00:00+08:00",
    first_seen_at: "2026-07-14T07:00:00+08:00",
  }),
  makeItem(80, {
    id: "double-bad",
    source: "未知时间作者",
    title: "双坏时间进入未知日期",
    published_at: "broken-published",
    first_seen_at: "broken-seen",
  }),
];

const TIMELINE_ITEMS = [...REGULAR_ITEMS, ...SPECIAL_ITEMS];
const NEWS_PAYLOAD = {
  generated_at: GENERATED_AT,
  time_scope: "all_time",
  source_scope: "tested_creator_sources",
  creator_window_days: 180,
  creator_time_scope: "all_time",
  total_items: TIMELINE_ITEMS.length,
  total_items_raw: TIMELINE_ITEMS.length,
  total_items_all_mode: TIMELINE_ITEMS.length,
  items: TIMELINE_ITEMS,
  items_ai: TIMELINE_ITEMS,
  items_all: TIMELINE_ITEMS,
  items_all_raw: TIMELINE_ITEMS,
  creator_items_ai: TIMELINE_ITEMS,
  creator_items_all: TIMELINE_ITEMS,
};
const SOURCE_STATUS = {
  generated_at: GENERATED_AT,
  sites: [
    { site_id: "bilibili_dynamic", site_name: "B站", ok: true, item_count: 71 },
    { site_id: "mediacrawler_douyin", site_name: "抖音", ok: true, item_count: 2 },
    { site_id: "mediacrawler_xhs", site_name: "小红书", ok: true, item_count: 2 },
    { site_id: "we_mp_rss_jsonl", site_name: "微信公众号", ok: true, item_count: 2 },
    { site_id: "opmlrss", site_name: "YouTube", ok: true, item_count: 2 },
    { site_id: "github_foundation_sunshine_releases", site_name: "GitHub Release", ok: true, item_count: 2 },
  ],
  failed_sites: [],
  rss_opml: { enabled: false, failed_feeds: [] },
};

function jsonResponse(body) {
  return { status: 200, contentType: "application/json", body: JSON.stringify(body) };
}

async function installFixtureRoutes(page) {
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
    if (route.request().isNavigationRequest() && url.pathname === "/") {
      const response = await route.fetch();
      const html = (await response.text()).replace(
        /\s*<script src="https:\/\/cdn\.jsdelivr\.net\/npm\/gsap@3\.13\.0\/dist\/gsap\.min\.js"[^>]*><\/script>/,
        "",
      );
      await route.fulfill({ response, body: html });
      return;
    }
    if (responses.has(url.pathname)) {
      await route.fulfill(jsonResponse(responses.get(url.pathname)));
      return;
    }
    await route.continue();
  });
}

function collectErrors(page) {
  const errors = [];
  page.on("pageerror", (error) => errors.push(`pageerror: ${error}`));
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(`console: ${message.text()}`);
  });
  return errors;
}

async function openFixture(page) {
  await installFixtureRoutes(page);
  await page.goto("/");
  await expect(page.locator("#resultCount")).toHaveText("81 条");
  await expect(page.locator("#newsList .news-card")).toHaveCount(80);
}

async function waitForListRender(page) {
  await expect(page.locator("#newsList .list-loading")).toHaveCount(0);
  await expect(page.locator("#newsList .news-card")).not.toHaveCount(0);
}

async function openSection(page, sectionId) {
  await page.locator(`#sectionTabs [data-section="${sectionId}"]`).click();
  await waitForListRender(page);
}

function listModeClasses(page) {
  return page.locator("#newsList").evaluate((node) => (
    ["timeline-mode", "flat-mode", "group-mode"].filter((className) => node.classList.contains(className))
  ));
}

test("语义骨架、栏目 ARIA 和设置抽屉兄弟关系", async ({ page }) => {
  const errors = collectErrors(page);
  await openFixture(page);

  await expect(page.locator("main")).toHaveCount(1);
  await expect(page.locator(".shell.app-layout > .app-sidebar")).toHaveCount(1);
  await expect(page.locator(".shell.app-layout > main.app-main")).toHaveCount(1);
  await expect(page.locator(".shell.app-layout > #settingsDrawer")).toHaveCount(1);

  const duplicateIds = await page.locator("[id]").evaluateAll((nodes) => {
    const counts = new Map();
    nodes.forEach((node) => counts.set(node.id, (counts.get(node.id) || 0) + 1));
    return Array.from(counts.entries()).filter(([, count]) => count > 1);
  });
  expect(duplicateIds).toEqual([]);

  await expect(page.locator("#sectionTabs")).not.toHaveAttribute("role", "tablist");
  await expect(page.locator("#sectionTabs [role=tab]")).toHaveCount(0);
  const creatorButton = page.locator('#sectionTabs [data-section="creator"]');
  const bilibiliButton = page.locator('#sectionTabs [data-section="bilibili"]');
  await expect(creatorButton).toHaveAttribute("aria-pressed", "true");
  await expect(creatorButton).toHaveClass(/active/);
  await expect(creatorButton.locator("strong")).toHaveText("81");
  await expect(bilibiliButton).toHaveAttribute("aria-pressed", "false");
  await bilibiliButton.click();
  await expect(bilibiliButton).toHaveAttribute("aria-pressed", "true");
  await expect(bilibiliButton).toHaveClass(/active/);
  await expect(creatorButton).toHaveAttribute("aria-pressed", "false");
  await expect(creatorButton).not.toHaveClass(/active/);

  await page.locator("#settingsOpenBtn").click();
  await expect(page.locator(".app-sidebar")).toHaveAttribute("inert", "");
  await expect(page.locator(".app-main")).toHaveAttribute("inert", "");
  await page.locator("#settingsCloseBtn").click();
  await expect(page.locator(".app-sidebar")).not.toHaveAttribute("inert", "");
  await expect(page.locator(".app-main")).not.toHaveAttribute("inert", "");
  expect(errors).toEqual([]);
});

test("统一时间口径、真实日期分组和 80 条分页", async ({ page }) => {
  const errors = collectErrors(page);
  await openFixture(page);

  const timelineValues = await page.evaluate(() => ({
    future: timelineIso({
      published_at: "2026-07-16T09:00:00+08:00",
      first_seen_at: "2026-07-15T11:55:00+08:00",
    }),
    broken: timelineIso({
      published_at: "not-a-date",
      first_seen_at: "2026-07-14T08:30:00+08:00",
    }),
    doubleBad: timelineIso({ published_at: "broken-published", first_seen_at: "broken-seen" }),
    singaporeDay: timelineDayKey({ published_at: "2026-07-14T16:30:00Z" }),
    unknownDay: timelineDayKey({ published_at: "broken-published", first_seen_at: "broken-seen" }),
  }));
  expect(timelineValues).toEqual({
    future: "2026-07-15T11:55:00+08:00",
    broken: "2026-07-14T08:30:00+08:00",
    doubleBad: "",
    singaporeDay: "2026-07-15",
    unknownDay: "unknown",
  });

  await expect(page.locator("#newsList")).toHaveClass(/timeline-mode/);
  expect(await page.locator(".timeline-day").count()).toBeGreaterThan(1);
  const groupCounts = await page.locator(".timeline-day").evaluateAll((sections) => sections.map((section) => {
    const text = section.querySelector(".timeline-day-meta")?.textContent || "";
    const declared = Number((text.match(/(\d+)\s*条/) || [])[1]);
    return { declared, actual: section.querySelectorAll(".timeline-row .news-card").length };
  }));
  expect(groupCounts.every(({ declared, actual }) => declared === actual)).toBe(true);
  const groupSemantics = await page.locator(".timeline-day").evaluateAll((sections) => sections.map((section) => {
    const labelledBy = section.getAttribute("aria-labelledby");
    const heading = labelledBy ? section.querySelector(`#${CSS.escape(labelledBy)}`) : null;
    return { tag: section.tagName, headingTag: heading?.tagName || "", headingInside: Boolean(heading) };
  }));
  expect(groupSemantics.every(({ tag, headingTag, headingInside }) => (
    tag === "SECTION" && headingTag === "H3" && headingInside
  ))).toBe(true);

  const futureRow = page.locator('.timeline-row:has(.news-card[data-item-id="future-fallback"])');
  await expect(futureRow.locator(".timeline-time")).toHaveAttribute("datetime", "2026-07-15T11:55:00+08:00");
  await expect(futureRow.locator(".news-card .time")).toHaveAttribute("datetime", "2026-07-15T11:55:00+08:00");
  const brokenRow = page.locator('.timeline-row:has(.news-card[data-item-id="broken-published"])');
  await expect(brokenRow.locator(".timeline-time")).toHaveAttribute("datetime", "2026-07-14T08:30:00+08:00");
  await expect(brokenRow.locator(".news-card .time")).toHaveAttribute("datetime", "2026-07-14T08:30:00+08:00");
  await expect(page.locator('.timeline-row:has(.news-card[data-item-id="midnight"]) .timeline-time')).toHaveText("00:05");
  expect(await page.evaluate(() => Boolean(window.__fixtureXss))).toBe(false);
  await expect(page.locator('.news-card[data-item-id="xss-text"] .title img')).toHaveCount(0);
  await expect(page.locator(".timeline-date", { hasText: "日期未知" })).toHaveCount(0);

  await page.getByRole("button", { name: "继续看剩余 1 条" }).click();
  await expect(page.locator("#newsList .news-card")).toHaveCount(81);
  await expect(page.locator(".timeline-date", { hasText: "日期未知" })).toHaveCount(1);
  const unknownRow = page.locator('.timeline-row:has(.news-card[data-item-id="double-bad"])');
  await expect(unknownRow.locator(".timeline-time")).toHaveText("--:--");
  await expect(unknownRow.locator(".timeline-time")).not.toHaveAttribute("datetime", /.+/);
  await expect(unknownRow.locator(".news-card .time")).toHaveText("时间未知");
  await expect(unknownRow.locator(".news-card .time")).not.toHaveAttribute("datetime", /.+/);
  await expect(page.locator(".timeline-day").last().locator(".timeline-date")).toHaveText("日期未知");
  await page.getByRole("button", { name: "收起，仅看前 80 条" }).click();
  await expect(page.locator("#newsList .news-card")).toHaveCount(80);
  expect(errors).toEqual([]);
});

test("四种排序只在时间排序显示日期轴", async ({ page }) => {
  const errors = collectErrors(page);
  await openFixture(page);

  const firstCardId = () => page.locator("#newsList .news-card").first().getAttribute("data-item-id");
  const modeClasses = () => page.locator("#newsList").evaluate((node) => (
    ["timeline-mode", "flat-mode", "group-mode"].filter((className) => node.classList.contains(className))
  ));
  expect(await firstCardId()).toBe("sort-time");
  expect(await modeClasses()).toEqual(["timeline-mode"]);
  await expect(page.locator(".timeline-day")).not.toHaveCount(0);

  const cases = [
    ["priority", "sort-priority"],
    ["ai", "sort-ai"],
    ["source", "source-leader"],
  ];
  for (const [sort, expectedId] of cases) {
    await page.locator(`#listSortTools [data-sort="${sort}"]`).click();
    expect(await modeClasses()).toEqual(["flat-mode"]);
    await expect(page.locator(".timeline-day")).toHaveCount(0);
    await expect(page.locator("#newsList .news-card").first()).toHaveAttribute("data-item-id", expectedId);
    expect(await page.locator("#newsList .news-card").first().locator(".time").evaluate((node) => (
      getComputedStyle(node).display
    ))).not.toBe("none");
  }
  await page.locator('#listSortTools [data-sort="time"]').click();
  expect(await modeClasses()).toEqual(["timeline-mode"]);
  await expect(page.locator(".timeline-day")).not.toHaveCount(0);
  await expect(page.locator("#newsList .news-card").first().locator(".time"))
    .toHaveAttribute("datetime", "2026-07-15T11:59:00+08:00");
  expect(errors).toEqual([]);
});

test("微信公众号只切换平铺布局，业务栏目口径保持不变", async ({ page }) => {
  const errors = collectErrors(page);
  await openFixture(page);

  expect(await page.evaluate(() => ({
    layout: usesFlatTimelineLayout("wechat"),
    subscriptionBusinessMode: isSubscriptionSection("wechat"),
  }))).toEqual({ layout: true, subscriptionBusinessMode: false });

  await openSection(page, "wechat");
  expect(await listModeClasses(page)).toEqual(["timeline-mode"]);
  await expect(page.locator("#resultCount")).toHaveText("2 条");
  await expect(page.locator("#newsList .source-group")).toHaveCount(0);
  await expect(page.locator("#newsList .site-group")).toHaveCount(0);
  const days = page.locator("#newsList .timeline-day");
  await expect(days).toHaveCount(2);
  await expect(days.nth(0).locator(".timeline-date")).toHaveText("7月15日");
  await expect(days.nth(0).locator(".timeline-day-meta")).toContainText("星期三");
  await expect(days.nth(1).locator(".timeline-date")).toHaveText("7月14日");
  await expect(days.nth(1).locator(".timeline-day-meta")).toContainText("星期二");
  const cardIds = await page.locator("#newsList .news-card").evaluateAll((nodes) => (
    nodes.map((node) => node.dataset.itemId)
  ));
  expect(cardIds).toEqual(["wechat-alpha", "wechat-beta"]);
  await expect(page.locator('script[src*="render-list.js?v=workbench-bridge-0717a"]')).toHaveCount(1);

  await page.locator('#listSortTools [data-sort="source"]').click();
  await waitForListRender(page);
  expect(await listModeClasses(page)).toEqual(["flat-mode"]);
  await expect(page.locator("#newsList .timeline-day")).toHaveCount(0);
  await expect(page.locator("#newsList .news-card")).toHaveCount(2);
  await expect(page.locator("#newsList .source-group")).toHaveCount(0);
  await page.locator('#listSortTools [data-sort="time"]').click();
  await waitForListRender(page);
  expect(await listModeClasses(page)).toEqual(["timeline-mode"]);
  await expect(page.locator("#newsList .timeline-day")).toHaveCount(2);
  expect(errors).toEqual([]);
});

test("所有平台 tab 都完成真实时间流渲染", async ({ page }) => {
  const errors = collectErrors(page);
  await openFixture(page);

  await page.locator('#newsList .news-card[data-item-id="read-target"] .read-toggle-btn').click();
  await waitForListRender(page);
  await expect(page.locator('#newsList .news-card[data-item-id="read-target"]')).toHaveCount(0);

  const sectionIds = await page.locator("#sectionTabs [data-section]").evaluateAll((nodes) => (
    nodes.map((node) => node.dataset.section)
  ));
  const expectedSectionIds = [
    "creator",
    "douyin",
    "xiaohongshu",
    "wechat",
    "bilibili",
    "youtube",
    "github",
    "read",
  ];
  expect(sectionIds).toEqual(expectedSectionIds);

  for (const sectionId of expectedSectionIds) {
    await openSection(page, sectionId);
    expect(await listModeClasses(page), `tab ${sectionId} 默认必须是时间轴`).toEqual(["timeline-mode"]);
    await expect(page.locator("#newsList .news-card")).not.toHaveCount(0);
    await expect(page.locator("#newsList .timeline-day")).not.toHaveCount(0);
    await expect(page.locator("#newsList .source-group")).toHaveCount(0);
    await expect(page.locator("#newsList .site-group")).toHaveCount(0);
    const timeValues = await page.locator("#newsList .news-card .time[datetime]").evaluateAll((nodes) => (
      nodes.map((node) => Date.parse(node.getAttribute("datetime")))
    ));
    expect(
      timeValues.every((value, index) => index === 0 || timeValues[index - 1] >= value),
      `tab ${sectionId} 的卡片必须按时间非递增排列`,
    ).toBe(true);
  }
  expect(errors).toEqual([]);
});

test("微信公众号平铺模式下已阅和恢复保持可用", async ({ page }) => {
  const errors = collectErrors(page);
  await openFixture(page);
  await openSection(page, "wechat");

  const alpha = page.locator('#newsList .news-card[data-item-id="wechat-alpha"]');
  await alpha.locator(".read-toggle-btn").click();
  await waitForListRender(page);
  await expect(alpha).toHaveCount(0);
  await expect(page.locator("#resultCount")).toHaveText("1 条");

  await openSection(page, "read");
  const readAlpha = page.locator('#newsList .news-card[data-item-id="wechat-alpha"]');
  await expect(readAlpha).toHaveCount(1);
  await expect(readAlpha.locator(".read-toggle-btn")).toHaveText("恢复");
  await readAlpha.locator(".read-toggle-btn").click();
  await expect(page.locator("#resultCount")).toHaveText("0 条");
  await expect(page.locator("#newsList > .empty")).toHaveCount(1);

  await openSection(page, "wechat");
  const restoredIds = await page.locator("#newsList .news-card").evaluateAll((nodes) => (
    nodes.map((node) => node.dataset.itemId)
  ));
  expect(restoredIds).toEqual(["wechat-alpha", "wechat-beta"]);
  expect(errors).toEqual([]);
});

test("搜索、已阅和恢复流程保持可用", async ({ page }) => {
  const errors = collectErrors(page);
  await openFixture(page);

  const search = page.locator("#searchInput");
  await search.fill("KUNKUN-TIMELINE");
  await expect(page.locator("#resultCount")).toHaveText("1 条");
  await expect(page.locator('#newsList .news-card[data-item-id="read-target"]')).toHaveCount(1);
  await page.locator('#newsList .news-card[data-item-id="read-target"] .read-toggle-btn').click();
  await expect(page.locator("#resultCount")).toHaveText("0 条");

  await page.locator('#sectionTabs [data-section="read"]').click();
  await expect(page.locator('#newsList .news-card[data-item-id="read-target"]')).toHaveCount(1);
  await expect(page.locator('#newsList .news-card[data-item-id="read-target"] .read-toggle-btn')).toHaveText("恢复");
  await page.locator('#newsList .news-card[data-item-id="read-target"] .read-toggle-btn').click();
  await expect(page.locator('#newsList .news-card[data-item-id="read-target"]')).toHaveCount(0);

  await search.fill("");
  await page.locator('#sectionTabs [data-section="creator"]').click();
  await expect(page.locator("#resultCount")).toHaveText("81 条");
  await expect(page.locator('#newsList .news-card[data-item-id="read-target"]')).toHaveCount(1);
  const storedReadKeys = await page.evaluate(() => JSON.parse(localStorage.getItem("ai-news-radar-read-items-v1") || "[]"));
  expect(storedReadKeys).toEqual([]);
  expect(errors).toEqual([]);
});

test("设置抽屉完整焦点循环、Esc 关闭和焦点恢复", async ({ page }) => {
  const errors = collectErrors(page);
  await openFixture(page);

  await page.locator("#settingsOpenBtn").focus();
  await page.locator("#settingsOpenBtn").click();
  await expect(page.locator("#settingsDrawer")).toBeVisible();
  for (let index = 0; index < 20; index += 1) {
    await page.keyboard.press("Tab");
    expect(await page.evaluate(() => document.querySelector("#settingsDrawer").contains(document.activeElement))).toBe(true);
  }
  for (let index = 0; index < 10; index += 1) {
    await page.keyboard.press("Shift+Tab");
    expect(await page.evaluate(() => document.querySelector("#settingsDrawer").contains(document.activeElement))).toBe(true);
  }
  await page.keyboard.press("Escape");
  await expect(page.locator("#settingsDrawer")).toBeHidden();
  await expect(page.locator(".app-sidebar")).not.toHaveAttribute("inert", "");
  await expect(page.locator(".app-main")).not.toHaveAttribute("inert", "");
  expect(await page.evaluate(() => document.activeElement?.id)).toBe("settingsOpenBtn");
  expect(errors).toEqual([]);
});

test("卡片 DOM 顺序、装饰头像和连续日期轨道", async ({ page }) => {
  const errors = collectErrors(page);
  await openFixture(page);

  const card = page.locator("#newsList .news-card").first();
  expect(await card.evaluate((node) => Array.from(node.children).slice(0, 3).map((child) => child.className))).toEqual([
    "meta-row",
    "title",
    "news-summary",
  ]);
  await expect(card.locator(".card-avatar")).toHaveAttribute("aria-hidden", "true");
  await expect(card.locator(".card-avatar")).not.toHaveText("");
  const visualContract = await card.evaluate((node) => {
    const cardStyle = getComputedStyle(node);
    const avatarStyle = getComputedStyle(node.querySelector(".card-avatar"));
    const cardTimeStyle = getComputedStyle(node.querySelector(".time"));
    const rowsStyle = getComputedStyle(document.querySelector(".timeline-day-items"), "::before");
    return {
      borderLeft: parseFloat(cardStyle.borderLeftWidth),
      avatarWidth: parseFloat(avatarStyle.width),
      cardTimeDisplay: cardTimeStyle.display,
      childOrders: Array.from(node.children).slice(0, 3).map((child) => getComputedStyle(child).order),
      railContent: rowsStyle.content,
      railWidth: parseFloat(rowsStyle.width),
      railHeight: parseFloat(rowsStyle.height),
    };
  });
  expect(visualContract.borderLeft).toBeGreaterThanOrEqual(3);
  expect(visualContract.avatarWidth).toBeGreaterThanOrEqual(24);
  expect(visualContract.cardTimeDisplay).toBe("none");
  expect(visualContract.childOrders).toEqual(["0", "0", "0"]);
  expect(visualContract.railContent).not.toBe("none");
  expect(visualContract.railWidth).toBeGreaterThanOrEqual(1);
  expect(visualContract.railHeight).toBeGreaterThan(100);
  expect(errors).toEqual([]);
});

test("item 文本字段不会被 innerHTML 解析", async ({ page }) => {
  const errors = collectErrors(page);
  await openFixture(page);

  const result = await page.evaluate(() => {
    const injectedText = '<img alt="fixture-field-injection">';
    const item = {
      id: "inner-html-guard",
      site_id: "bilibili_dynamic",
      site_name: injectedText,
      source: injectedText,
      title: "字段安全回归",
      url: "https://example.com/fixture",
      published_at: "2026-07-15T08:00:00+08:00",
      first_seen_at: "2026-07-15T08:00:00+08:00",
      ai_signals: [],
    };
    const host = document.createElement("div");
    host.append(
      buildBoleLead({ item, score: 42 }),
      buildBoleTimelineRow({ item, score: 42, sourceSignals: [] }, 1),
    );
    document.body.appendChild(host);
    const snapshot = {
      imageCount: host.querySelectorAll('img[alt="fixture-field-injection"]').length,
      footText: host.querySelector(".bole-lead-foot")?.textContent || "",
      metaText: host.querySelector(".bole-row-meta")?.textContent || "",
    };
    host.remove();
    return snapshot;
  });

  expect(result.imageCount).toBe(0);
  expect(result.footText).toContain('<img alt="fixture-field-injection">');
  expect(result.metaText).toContain('<img alt="fixture-field-injection">');
  expect(errors).toEqual([]);
});

const VIEWPORTS = [
  { width: 1440, height: 1000, desktop: true },
  { width: 1024, height: 900, desktop: true },
  { width: 768, height: 1024, desktop: false },
  { width: 400, height: 900, desktop: false },
];

for (const viewport of VIEWPORTS) {
  test(`响应式 ${viewport.width}x${viewport.height} 无横向溢出`, async ({ page }, testInfo) => {
    const errors = collectErrors(page);
    // Freeze the existing GSAP entrance sequence so full-page evidence never
    // captures the first 30 cards halfway through their staggered animation.
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    await openFixture(page);

    const metrics = await page.evaluate(() => {
      const sidebar = document.querySelector(".app-sidebar");
      const main = document.querySelector(".app-main");
      const tabs = document.querySelector("#sectionTabs");
      const firstCard = document.querySelector("#newsList .news-card");
      const longCard = document.querySelector('[data-item-id="long-layout"]');
      const sidebarRect = sidebar.getBoundingClientRect();
      const mainRect = main.getBoundingClientRect();
      const longRect = longCard.getBoundingClientRect();
      return {
        scrollWidth: document.documentElement.scrollWidth,
        clientWidth: document.documentElement.clientWidth,
        sidebarPosition: getComputedStyle(sidebar).position,
        tabsDirection: getComputedStyle(tabs).flexDirection,
        sidebarLeft: sidebarRect.left,
        sidebarRight: sidebarRect.right,
        mainLeft: mainRect.left,
        mainTop: mainRect.top,
        sidebarBottom: sidebarRect.bottom,
        firstCardTop: firstCard.getBoundingClientRect().top,
        longWithinViewport: longRect.left >= -1 && longRect.right <= document.documentElement.clientWidth + 1,
      };
    });
    expect(metrics.scrollWidth).toBeLessThanOrEqual(metrics.clientWidth + 1);
    expect(metrics.longWithinViewport).toBe(true);
    expect(metrics.firstCardTop).toBeLessThan(viewport.height);
    if (viewport.desktop) {
      expect(metrics.sidebarPosition).toBe("sticky");
      expect(metrics.sidebarRight).toBeLessThanOrEqual(metrics.mainLeft + 1);
      expect(metrics.tabsDirection).toBe("column");
    } else {
      expect(metrics.sidebarPosition).toBe("static");
      expect(metrics.mainTop).toBeGreaterThanOrEqual(metrics.sidebarBottom - 1);
      expect(metrics.tabsDirection).toBe("row");
    }

    const screenshotPath = testInfo.outputPath(`viewport-${viewport.width}x${viewport.height}.png`);
    await page.screenshot({ path: screenshotPath });
    expect(errors).toEqual([]);
  });
}

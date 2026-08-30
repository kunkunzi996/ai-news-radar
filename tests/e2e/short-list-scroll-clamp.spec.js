const { test, expect } = require("@playwright/test");

const GENERATED_AT = "2026-07-15T12:00:00+08:00";

function makeItem(index) {
  const publishedAt = new Date(Date.parse(GENERATED_AT) - (index + 1) * 24 * 60 * 60 * 1000).toISOString();
  return {
    id: `short-${index + 1}`,
    site_id: "bilibili_dynamic",
    site_name: "B站",
    source: `短列表作者 ${index + 1}`,
    title: `短列表第 ${index + 1} 条`,
    title_zh: "",
    title_en: "",
    url: `https://www.bilibili.com/video/short-${index + 1}`,
    published_at: publishedAt,
    first_seen_at: publishedAt,
    ai_score: 0.5,
    creator_hot_score: 40,
    ai_label: "ai_general",
    ai_signals: ["fixture"],
    source_tier: "creator",
    source_tier_rank: 3,
  };
}

const ITEMS = Array.from({ length: 8 }, (_, index) => makeItem(index));
const NEWS_PAYLOAD = {
  generated_at: GENERATED_AT,
  time_scope: "all_time",
  source_scope: "tested_creator_sources",
  creator_window_days: 180,
  creator_time_scope: "all_time",
  total_items: ITEMS.length,
  total_items_raw: ITEMS.length,
  total_items_all_mode: ITEMS.length,
  items: ITEMS,
  items_ai: ITEMS,
  items_all: ITEMS,
  items_all_raw: ITEMS,
  creator_items_ai: ITEMS,
  creator_items_all: ITEMS,
};
const SOURCE_STATUS = {
  generated_at: GENERATED_AT,
  sites: [{ site_id: "bilibili_dynamic", site_name: "B站", ok: true, item_count: 8 }],
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

async function openShortBilibili(page) {
  await page.setViewportSize({ width: 1280, height: 720 });
  await installFixtureRoutes(page);
  await page.goto("/?readerOnly=1");
  await expect(page.locator("#newsList .news-card")).toHaveCount(8);
  await page.addStyleTag({ content: ".news-card{min-height:280px;}" });
  await page.locator('#sectionTabs [data-section="bilibili"]').click();
  await expect(page.locator("#newsList .list-loading")).toHaveCount(0);
  await expect(page.locator("#newsList .news-card")).toHaveCount(8);
}

async function scrollToEnd(page) {
  return page.evaluate(() => {
    const scrolling = document.scrollingElement || document.documentElement;
    const maxScroll = Math.max(0, scrolling.scrollHeight - scrolling.clientHeight);
    scrolling.scrollTop = maxScroll;
    return {
      scrollY: scrolling.scrollTop,
      maxScroll,
      scrollHeight: scrolling.scrollHeight,
      clientHeight: scrolling.clientHeight,
      lastTop: document.querySelector("#newsList .news-card:last-of-type")?.getBoundingClientRect().top || 0,
      firstTop: document.querySelector("#newsList .news-card")?.getBoundingClientRect().top || 0,
      spacerHeight: document.querySelector("[data-list-stay-spacer='1']")?.getBoundingClientRect().height || 0,
    };
  });
}

async function waitFrames(page, count = 3) {
  await page.evaluate((frames) => new Promise((resolve) => {
    const step = (left) => {
      if (left <= 0) return resolve();
      requestAnimationFrame(() => step(left - 1));
    };
    step(frames);
  }), count);
}

test("H1 只滚动到底、不重画：短列表不应自己弹回顶部", async ({ page }) => {
  await openShortBilibili(page);
  const before = await scrollToEnd(page);
  expect(before.maxScroll).toBeGreaterThan(200);
  expect(before.scrollY).toBeGreaterThan(200);
  await page.waitForTimeout(400);
  await waitFrames(page);
  const later = await page.evaluate(() => {
    const scrolling = document.scrollingElement || document.documentElement;
    return scrolling.scrollTop;
  });
  expect(later).toBeGreaterThan(before.scrollY - 8);
});

test("H2 同步清空当下：innerHTML 变空时滚动会被钳到接近 0", async ({ page }) => {
  await openShortBilibili(page);
  const before = await scrollToEnd(page);
  expect(before.scrollY).toBeGreaterThan(200);

  const emptied = await page.evaluate(() => {
    const scrolling = document.scrollingElement || document.documentElement;
    const y0 = scrolling.scrollTop;
    const h0 = scrolling.scrollHeight;
    newsListEl.innerHTML = "";
    return {
      y0,
      y1: scrolling.scrollTop,
      h0,
      h1: scrolling.scrollHeight,
      clientHeight: scrolling.clientHeight,
    };
  });

  expect(emptied.h1).toBeLessThan(emptied.h0);
  expect(emptied.y1).toBeLessThan(24);
});

test("H3 产品重画尾路径应尽量保住当前视口，而不是弹回顶部", async ({ page }) => {
  await openShortBilibili(page);
  const before = await scrollToEnd(page);
  expect(before.scrollY).toBeGreaterThan(200);

  const after = await page.evaluate(async () => {
    const cardsBefore = Array.from(document.querySelectorAll("#newsList .news-card")).map((card) => ({
      id: card.dataset.itemId,
      top: card.getBoundingClientRect().top,
    }));
    requestListStayRestore();
    const pending = state.pendingListStay ? { ...state.pendingListStay } : null;
    rerenderCurrentView();
    await new Promise((resolve) => {
      requestAnimationFrame(() => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    });
    const cards = Array.from(document.querySelectorAll("#newsList .news-card"));
    const last = cards[cards.length - 1];
    const first = cards[0];
    const scrolling = document.scrollingElement || document.documentElement;
    return {
      scrollY: scrolling.scrollTop,
      pending,
      firstId: first?.dataset.itemId || "",
      firstTop: first?.getBoundingClientRect().top || 0,
      lastId: last?.dataset.itemId || "",
      lastTop: last ? last.getBoundingClientRect().top : 0,
      visibleIds: cardsBefore.filter((card) => card.top >= 0 && card.top < window.innerHeight).map((card) => card.id),
    };
  });

  expect(after.lastId).toBe("short-8");
  expect(after.scrollY, JSON.stringify(after)).toBeGreaterThan(before.scrollY - 80);
});

test("H4 无参恢复必须忽略过期 lastListStay，保住底部", async ({ page }) => {
  await openShortBilibili(page);
  const before = await scrollToEnd(page);
  expect(before.scrollY).toBeGreaterThan(200);

  const after = await page.evaluate(async () => {
    const first = document.querySelector("#newsList .news-card");
    const cards = () => Array.from(document.querySelectorAll("#newsList .news-card"));
    state.lastListStay = { anchorId: first.dataset.itemId, slotTop: 180 };
    state.pendingListStay = null;
    requestListStayRestore();
    rerenderCurrentView();
    await new Promise((resolve) => {
      requestAnimationFrame(() => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    });
    const scrolling = document.scrollingElement || document.documentElement;
    const list = cards();
    const last = list[list.length - 1];
    return {
      scrollY: scrolling.scrollTop,
      firstTop: list[0]?.getBoundingClientRect().top || 0,
      lastId: last?.dataset.itemId || "",
      lastTop: last ? last.getBoundingClientRect().top : 0,
    };
  });

  expect(after.lastId).toBe("short-8");
  expect(after.scrollY).toBeGreaterThan(before.scrollY - 80);
  expect(after.lastTop).toBeLessThan(900);
});

test("H5 先点已阅再拉到底：不额外重画时不应自己弹回", async ({ page }) => {
  await openShortBilibili(page);
  await page.locator("#newsList .news-card .read-toggle-btn").nth(0).click();
  await page.locator("#newsList .news-card .read-toggle-btn").nth(0).click();
  await expect(page.locator("#newsList .news-card")).toHaveCount(6);
  const before = await scrollToEnd(page);
  expect(before.scrollY).toBeGreaterThan(80);
  await page.waitForTimeout(400);
  await waitFrames(page);
  const later = await page.evaluate(() => ({
    scrollY: (document.scrollingElement || document.documentElement).scrollTop,
    lastListStay: state.lastListStay,
    spacerHeight: document.querySelector("[data-list-stay-spacer='1']")?.getBoundingClientRect().height || 0,
  }));
  expect(later.scrollY).toBeGreaterThan(before.scrollY - 8);
  expect(later.lastListStay && later.lastListStay.anchorId).toBeTruthy();
});

test("H6 已阅留下锚点后整表重画仍保住当前底部", async ({ page }) => {
  await openShortBilibili(page);
  await page.locator("#newsList .news-card .read-toggle-btn").nth(0).click();
  await page.locator("#newsList .news-card .read-toggle-btn").nth(0).click();
  await expect(page.locator("#newsList .news-card")).toHaveCount(6);
  const before = await scrollToEnd(page);
  expect(before.scrollY).toBeGreaterThan(80);

  const after = await page.evaluate(async () => {
    const stay = state.lastListStay ? { ...state.lastListStay } : null;
    requestListStayRestore();
    rerenderCurrentView();
    await new Promise((resolve) => {
      requestAnimationFrame(() => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    });
    const scrolling = document.scrollingElement || document.documentElement;
    const cards = Array.from(document.querySelectorAll("#newsList .news-card"));
    const last = cards[cards.length - 1];
    return {
      stay,
      scrollY: scrolling.scrollTop,
      lastId: last?.dataset.itemId || "",
      lastTop: last ? last.getBoundingClientRect().top : 0,
    };
  });

  expect(after.stay && after.stay.anchorId).toBeTruthy();
  expect(after.scrollY).toBeGreaterThan(before.scrollY - 80);
  expect(after.lastTop).toBeLessThan(900);
});

test("H7 工作台 iframe 里只滚到底，不重画也不应弹回", async ({ page, baseURL }) => {
  await installFixtureRoutes(page);
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.setContent(`<!doctype html><iframe id="radar" src="${baseURL}/?readerOnly=1" style="width:1100px;height:620px;border:0"></iframe>`);
  const radar = page.frameLocator("#radar");
  await expect(radar.locator("#newsList .news-card")).toHaveCount(8);
  await radar.locator("body").evaluate(() => {
    const style = document.createElement("style");
    style.textContent = ".news-card{min-height:280px;}";
    document.head.appendChild(style);
  });
  await radar.locator('#sectionTabs [data-section="bilibili"]').click();
  await expect(radar.locator("#newsList .list-loading")).toHaveCount(0);
  await expect(radar.locator("#newsList .news-card")).toHaveCount(8);

  const before = await radar.locator("body").evaluate(() => {
    const scrolling = document.scrollingElement || document.documentElement;
    scrolling.scrollTop = Math.max(0, scrolling.scrollHeight - scrolling.clientHeight);
    return {
      scrollY: scrolling.scrollTop,
      maxScroll: Math.max(0, scrolling.scrollHeight - scrolling.clientHeight),
    };
  });
  expect(before.maxScroll).toBeGreaterThan(200);
  expect(before.scrollY).toBeGreaterThan(200);
  await page.waitForTimeout(400);
  const later = await radar.locator("body").evaluate(() => (
    document.scrollingElement || document.documentElement
  ).scrollTop);
  expect(later).toBeGreaterThan(before.scrollY - 8);
});


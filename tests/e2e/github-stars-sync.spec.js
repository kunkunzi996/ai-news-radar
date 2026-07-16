const { test, expect } = require("@playwright/test");

function collectErrors(page, errors) {
  page.on("pageerror", (err) => errors.push(`pageerror: ${err}`));
  page.on("console", (msg) => {
    if (msg.type() === "error") errors.push(`console: ${msg.text()}`);
  });
}

const account = { id: 12345678, login: "example-user" };
const baseConfig = {
  ok: true,
  config: { version: "1.0", sources: [] },
  base_config_digest: "d".repeat(64),
  etag: '"d'.concat("d".repeat(63), '"'),
  recovery: null,
};

function previewPayload() {
  return {
    ok: true,
    account,
    starred_count: 1,
    private_skipped_count: 0,
    summary: {
      added: [{ id: 987654321, full_name: "owner/public-repo" }],
      disabled: [],
      re_enabled: [],
      adopted: [],
      renamed: [],
      skipped_manual_disabled: [],
    },
    requires_confirmation: true,
    preview_hash: "p".repeat(64),
    base_config_digest: baseConfig.base_config_digest,
  };
}

test("GitHub 星标首次绑定、确认、Apply 与四种 outcome 可展示", async ({ page }) => {
  const errors = [];
  collectErrors(page, errors);
  let applyCount = 0;
  await page.route("**/api/online-source-config", async (route) => {
    await route.fulfill({ status: 200, headers: { ETag: baseConfig.etag }, json: baseConfig });
  });
  await page.route("**/api/github-stars/preview", async (route) => {
    await route.fulfill({ status: 200, json: previewPayload() });
  });
  await page.route("**/api/github-stars/apply", async (route) => {
    applyCount += 1;
    const outcomes = ["no_change", "pushed", "saved_not_committed", "committed_not_pushed"];
    const outcome = outcomes[Math.min(applyCount - 1, outcomes.length - 1)];
    await route.fulfill({
      status: 200,
      headers: { ETag: baseConfig.etag },
      json: {
        ok: true,
        outcome,
        config: baseConfig.config,
        base_config_digest: baseConfig.base_config_digest,
        etag: baseConfig.etag,
        config_changed: outcome !== "no_change",
        commit: outcome === "no_change" ? null : `commit-${applyCount}`,
        pushed: outcome === "pushed",
        partial: outcome !== "no_change" && outcome !== "pushed",
        recovery_pending: false,
        summary: previewPayload().summary,
      },
    });
  });

  const configLoaded = page.waitForResponse("**/api/online-source-config");
  await page.goto("/");
  await configLoaded;
  await page.locator("#settingsOpenBtn").click();
  await expect(page.locator("#onlineSourceStatus")).toContainText("已读取");
  await expect(page.locator("#githubStarSyncPanel")).toBeVisible();
  await page.locator("#githubStarUsername").fill("example-user");
  await page.locator("#githubStarPreviewBtn").click();
  await expect(page.locator("#githubStarPreview")).toBeVisible();
  await expect(page.locator("#githubStarPreviewSummary")).toContainText("owner/public-repo");
  await page.locator("#githubStarConfirm").check();
  await page.locator("#githubStarApplyBtn").click();
  await expect(page.locator("#githubStarOutcome")).toContainText("无变化");
  for (const expected of ["已推送", "已保存，待提交", "已提交，待推送"]) {
    await page.locator("#githubStarUsername").fill("example-user");
    await page.locator("#githubStarPreviewBtn").click();
    await page.locator("#githubStarConfirm").check();
    await expect(page.locator("#githubStarConfirm")).toBeChecked();
    await expect(page.locator("#githubStarApplyBtn")).toBeEnabled();
    await page.locator("#githubStarApplyBtn").click();
    await expect(page.locator("#githubStarOutcome")).toContainText(expected);
  }
  expect(errors).toEqual([]);
});

test("GitHub 星标 stale、Recovery、解绑和 partial/deferred 状态可见", async ({ page }) => {
  const errors = [];
  collectErrors(page, errors);
  page.on("dialog", (dialog) => dialog.accept());
  const config = {
    ...baseConfig,
    config: {
      ...baseConfig.config,
      github_star_sync: { version: 1, account_id: account.id, account_login: account.login },
      sources: [{ id: "online_github_repo_987654321", name: "owner/public-repo", type: "github_release", enabled: true }],
    },
    recovery: {
      operation_id: "op-1",
      manifest_digest: "m".repeat(64),
      operation_kind: "apply",
      phase: "committed",
      outcome: "committed_not_pushed",
      recovery_pending: false,
      allowed_actions: ["retry_push", "rollback"],
    },
  };
  await page.route("**/api/online-source-config", async (route) => {
    await route.fulfill({ status: 200, headers: { ETag: config.etag }, json: config });
  });
  await page.route("**/api/github-stars/preview", async (route) => {
    await route.fulfill({ status: 200, json: { ok: false, error: "github_star_preview_stale" } });
  });
  await page.route("**/api/github-stars/unbind", async (route) => {
    await route.fulfill({ status: 200, headers: { ETag: config.etag }, json: { ok: true, outcome: "pushed", config: baseConfig.config, etag: config.etag, base_config_digest: config.base_config_digest } });
  });
  await page.route("**/api/online-source-config/recovery", async (route) => {
    await route.fulfill({ status: 200, headers: { ETag: config.etag }, json: { ok: true, outcome: "pushed", recovery_pending: false, config: config.config, etag: config.etag, base_config_digest: config.base_config_digest } });
  });
  await page.route("**/api/local-status", async (route) => {
    await route.fulfill({
      status: 200,
      json: {
        ok: true,
        source_status: {
          sites: [{
            site_id: "github_foundation_sunshine_releases",
            site_name: "GitHub Release",
            ok: false,
            partial: true,
            eligible_count: 3,
            attempted_count: 2,
            succeeded_count: 1,
            expected_skip_count: 0,
            failed_count: 1,
            deferred_count: 1,
            repos: [{ repo: "owner/public-repo", skip_reason: "skipped_due_to_budget" }],
          }],
        },
      },
    });
  });

  const configLoaded = page.waitForResponse("**/api/online-source-config");
  await page.goto("/");
  await configLoaded;
  await page.locator("#settingsOpenBtn").click();
  await expect(page.locator("#onlineSourceStatus")).toContainText("已读取");
  await expect(page.locator("#githubStarBoundAccount")).toContainText("example-user");
  await expect(page.locator("#githubStarRecovery")).toContainText("可恢复");
  await expect(page.locator("#githubStarCollectionStatus")).toContainText("延后 1");
  await page.locator("#githubStarRetryBtn").click();
  await page.locator("#githubStarUnbindBtn").click();
  await page.locator("#githubStarUsername").fill("example-user");
  await page.locator("#githubStarPreviewBtn").click();
  await expect(page.locator("#githubStarStatus")).toContainText("过期");
  expect(errors).toEqual([]);
});

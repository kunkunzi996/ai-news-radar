const { defineConfig } = require("@playwright/test");

module.exports = defineConfig({
  testDir: "tests/e2e",
  timeout: 30000,
  use: { baseURL: "http://127.0.0.1:8080" },
  webServer: {
    command: ".\\.venv\\Scripts\\python.exe scripts\\local_server.py",
    url: "http://127.0.0.1:8080/api/local-status",
    reuseExistingServer: true,
    timeout: 30000,
  },
});

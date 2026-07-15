const { defineConfig } = require("@playwright/test");

// A clean worktree intentionally has no private sources.config.json. Keep the
// real local server, but make its read-only E2E surface deterministic and
// remove the optional CDN motion script from test HTML only.
const testServerCode = [
  "import re",
  "from pathlib import Path",
  "import scripts.local_server as m",
  "original_get = m.LocalRadarHandler.do_GET",
  "source_fixture = {'ok': True, 'path': 'sources.config.json', 'config': {'version': '1.0', 'updated_at': '', 'deleted_source_ids': [], 'sources': []}}",
  "html = Path('index.html').read_text(encoding='utf-8')",
  "html = re.sub(r'\\s*<script[^>]+cdn[.]jsdelivr[.]net/npm/gsap@3[.]13[.]0/dist/gsap[.]min[.]js[^>]*></script>', '', html)",
  "index_body = html.encode('utf-8')",
  "serve_index = lambda self: (self.send_response(m.HTTPStatus.OK), self.send_header('Content-Type', 'text/html; charset=utf-8'), self.send_header('Content-Length', str(len(index_body))), self.end_headers(), self.wfile.write(index_body))",
  "m.LocalRadarHandler.do_GET = lambda self: m.json_response(self, m.HTTPStatus.OK, source_fixture) if self.path.split('?', 1)[0] == '/api/source-config' else serve_index(self) if self.path.split('?', 1)[0] in ('/', '/index.html') else original_get(self)",
  "raise SystemExit(m.main())",
].join("; ");

module.exports = defineConfig({
  testDir: "tests/e2e",
  timeout: 30000,
  use: {
    baseURL: "http://127.0.0.1:8080",
    timezoneId: "Asia/Singapore",
  },
  webServer: {
    command: `.\\.venv\\Scripts\\python.exe -c "${testServerCode}"`,
    url: "http://127.0.0.1:8080/api/local-status",
    reuseExistingServer: false,
    timeout: 30000,
  },
});

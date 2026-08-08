# 远程管理后台（token 公开模式）的禁区（详细契约）

> 本文是 `CLAUDE.md`「远程管理后台（token 公开模式）的禁区」的展开。
> **两条安全底线仍在 `CLAUDE.md` 正文**（白名单只许收缩、无令牌禁止绑定非回环）；
> 本文装五条逐条契约——只有改 `scripts/radar/server/` 下的公开模式逻辑时才需要逐条对照。

2026-07-29 起，local_server 支持「公开模式」：设置 `RADAR_ADMIN_TOKEN` 后经 Cloudflare 隧道
暴露到公网，公网 Pages 页面配置「远程后台」即可直接管理订阅源（实施计划见
`计划/2026-07-29-订阅源管理合并入公网页面实施计划.md`）。改动这块时：

1. **静态白名单只许收缩、不许扩张。** 公开模式下只服务 `/`、`/index.html`、`/assets/*`、
   `/data/*`、`/site.webmanifest`、`/favicon.ico`、`/bilibili-account-preview.html` 和 `/api/*`；
   `sources.config.json`、`feeds/follow.opml`、`local-secrets/`、`data/pending-purge.json`、
   `.git/`、`node_modules/`、日志、`计划/`、`.venv*` **永远禁止进入白名单**。想新增可公开文件，
   先确认它在公开仓库里本来就可见。白名单判定必须先 `unquote` 再 `normpath`，
   防 `/assets/%2e%2e/...` 编码穿越（测试里有用例，别删）。
2. **令牌校验必须恒定时间比较**（`hmac.compare_digest`）；禁止把令牌写进日志、响应体、
   截图或错误消息；失败限速状态只允许在内存，不能落盘。
3. **未设 `RADAR_ADMIN_TOKEN` 时一切行为必须与历史逐字一致**（回环本地控制台），由
   `DefaultModeServerRegressionTests` 守住；改公开模式逻辑时不许顺手改默认路径。
4. **CORS 只许精确反射 `RADAR_TRUSTED_ORIGINS` 里的 Origin**，禁止 `*` 或子串/后缀匹配；
   同源回环页面不需要 CORS 头，不同端口的回环跨源也必须显式配置才反射。
5. **绑定非回环地址且无令牌必须拒绝启动**——origin 检查只是 CSRF 防线，挡不住局域网里的
   curl，公网/局域网暴露必须以令牌为前提。

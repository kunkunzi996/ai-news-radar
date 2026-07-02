# 本地生成数据和临时文件策略

这份说明只管一件事：把“本地刷新出来的数据”“私人运行文件”“可以删的临时文件”分清楚。
目标是：本地页面还能正常验收，但不要把私人数据、平台临时参数、登录态误提交到 Git。

## 保留本地，不要盲目提交

| 路径 | 为什么保留本地 | 提交规则 |
|---|---|---|
| `data/*.json` | 本地网页直接读取这些文件，所以它们对预览和验收有用。 | 这些是 Git 已追踪的生成快照。生成链路已会清理小红书 `xsec_token` / `xsec_source` 等临时参数；旧的本地脏数据仍需重新生成后才会变干净。提交前还要审查 diff。 |
| `sources.config.json` | 本地信源配置面板的个人启用/停用选择。 | 已加入忽略，只留本地。 |
| `feeds/follow.opml` | 私人 OPML/RSS 订阅清单。 | 已加入忽略，只留本地。 |
| `E:\AI-news-reader\MediaCrawler-local-test\output\**\*.jsonl` | MediaCrawler 导出的爬虫结果，主项目只读取它。 | 保留在主仓库外，不要复制进主仓库。 |
| `E:\AI-news-reader\MediaCrawler-local-test\chrome-profile` | MediaCrawler 用到的浏览器登录态。 | 永远不要提交，也不要复制进主仓库。 |

## 已加入忽略的本地临时文件

这些只是本地预览或日志文件，现在已经加入 `.gitignore`：

- `bilibili-account-preview.html`
- `server.err.log`
- `server.out.log`

它们可以继续留在磁盘上，方便排查问题。以后如果不需要了，也必须先让用户确认，
再一次删除一个明确路径的文件。

## 删除前必须确认

不要批量删除文件或目录。确实要清理时，先问用户，再每条命令只删一个明确路径，例如：

```powershell
Remove-Item "E:\AI-news-reader\ai-news-radar-run\server.out.log"
```

不要用宽泛清理命令，比如“删除全部日志”“清空整个 `data` 目录”“删除 MediaCrawler 工作区”
或“重置 Git 工作区”。

## 下一步选择

下次继续开发前，从这几个方向里选一个就行：

1. 当前 `data/*.json` 继续保留本地，不提交。
2. 重新生成 `data/*.json`，检查不再包含 `xsec_token` / `xsec_source` 后，再决定是否提交。
3. 明确确认某个临时文件要删，然后一次删一个。

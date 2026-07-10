# 抖音订阅全自动：云电脑 + 私有桥接仓库方案

Date: 2026-07-10
Scope: 把抖音博主订阅接入公网自动刷新（GitHub Actions），采集端跑在 24 小时在线的云 Windows 上。

## 一句话架构

```
云电脑 (Windows 常开, Chrome 已扫码登录抖音)
  └─ 计划任务每天 2~4 次跑 deploy/cloud-pc/collect-douyin-and-push.ps1
       ├─ 读主仓库 config/online-sources.json 里启用的抖音博主
       ├─ MediaCrawler 抓取 → creator_contents_*.jsonl
       └─ 复制进私有桥接仓库并 git push
            ↓
GitHub Actions（现有 update-news.yml，每 30 分钟）
  ├─ 克隆桥接仓库（vars.DOUYIN_BRIDGE_REPO + secrets.DOUYIN_BRIDGE_TOKEN）
  ├─ MEDIACRAWLER_LOCAL_DIR 指向克隆目录
  └─ update_news.py 读 JSONL → 抖音内容进 data/*.json → 页面展示
```

为什么不让 Actions 直接爬抖音：MediaCrawler 需要真实 Chrome + 扫码登录态，
GitHub 的机房容器给不了；抖音对无登录态的服务器 IP 风控极严。
云电脑提供"真浏览器 + 可远程扫码 + 常在线"，是采集端的最小可行环境。

## 第一步：买云电脑

要求：Windows 系统、能装 Chrome、24 小时在线、能访问抖音（选中国大陆区域）。

- 推荐：阿里云/腾讯云 **Windows 轻量应用服务器**（2C4G 起步即可）。
- 云桌面类产品（无影等）也可以，但注意"闲置自动关机/休眠"策略必须关掉。
- 计划任务要用"仅当用户登录时运行"（Chrome 非 headless），所以云电脑需要
  设置自动登录、不注销；断开 RDP 连接（不要注销）会话仍保持。

## 第二步：装环境（云电脑上）

1. 安装 [Git](https://git-scm.com/)、[Python 3.11+](https://www.python.org/)、Chrome。
2. 克隆三个仓库（示例放 `D:\ai-news\`）：

```powershell
mkdir D:\ai-news; cd D:\ai-news
git clone https://github.com/<你的用户名>/ai-news-radar.git        # 主仓库
git clone https://github.com/NanmiCoder/MediaCrawler.git            # 采集器
git clone https://github.com/<你的用户名>/douyin-bridge.git         # 私有桥接仓库（见第三步）
```

3. 给 MediaCrawler 建 venv 并装依赖：

```powershell
cd D:\ai-news\MediaCrawler
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
```

## 第三步：建私有桥接仓库

1. GitHub 上新建 **私有** 仓库，例如 `douyin-bridge`（空仓库即可，加个 README 方便克隆）。
2. 创建两枚 Fine-grained PAT（Settings → Developer settings → Fine-grained tokens），
   都只授权 `douyin-bridge` 这一个仓库：
   - **云电脑用**：Contents 权限 Read and write（用于 push JSONL）。
   - **Actions 用**：Contents 权限 Read-only（用于克隆）。
3. 云电脑上给桥接仓库配好推送凭证（克隆时带 PAT 或用 Git Credential Manager 登录一次）。

桥接仓库内容由脚本自动维护，固定布局：

```
output/douyin/jsonl/creator_contents_latest.jsonl   # 每次采集覆盖
manifest.json                                        # 采集时间、行数等元信息
```

## 第四步：首次手动采集（扫码登录）

云电脑上手动跑一次，弹出的 Chrome 里用手机抖音 App 扫码登录：

```powershell
cd D:\ai-news\ai-news-radar
powershell -ExecutionPolicy Bypass -File deploy\cloud-pc\collect-douyin-and-push.ps1 `
  -CrawlerRoot D:\ai-news\MediaCrawler -BridgeRoot D:\ai-news\douyin-bridge
```

说明：

- 登录态保存在 `<CrawlerRoot>\chrome-profile`，之后无人值守运行不再需要扫码。
- 博主列表自动读主仓库 `config/online-sources.json` 里 `type=mediacrawler_jsonl`
  且 `enabled=true` 的条目——如果还没启用（见第六步），可先用
  `-CreatorIds "<sec_uid1>,<sec_uid2>"` 手动指定验证链路。
- 成功标志：控制台输出"完成：N 行 JSONL 已推送"，桥接仓库出现新 commit。

## 第五步：注册计划任务（每天 3 次示例）

```powershell
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
  -Argument "-ExecutionPolicy Bypass -File D:\ai-news\ai-news-radar\deploy\cloud-pc\collect-douyin-and-push.ps1 -CrawlerRoot D:\ai-news\MediaCrawler -BridgeRoot D:\ai-news\douyin-bridge"
$triggers = @("08:10", "13:10", "20:10") | ForEach-Object { New-ScheduledTaskTrigger -Daily -At $_ }
Register-ScheduledTask -TaskName "DouyinCollectAndPush" -Action $action -Trigger $triggers `
  -Settings (New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 1))
```

注意任务属性里保持默认的 **"只在用户登录时运行"**（Run only when user is logged on），
否则 Chrome 起不来。

频率建议每天 2~4 次即可，**不要**跟着 Actions 每 30 分钟跑——采集频率越高，
抖音风控风险越大；内容进页面的实时性由 Actions 端每 30 分钟的读取保证。

## 第六步：接通 GitHub Actions

主仓库 Settings → Secrets and variables → Actions：

1. Variables 新增 `DOUYIN_BRIDGE_REPO`，值如 `你的用户名/douyin-bridge`。
2. Secrets 新增 `DOUYIN_BRIDGE_TOKEN`，值为第三步的 Read-only PAT。
3. 本地打开控制台（127.0.0.1:8080）→ 线上信源面板，把 4 个抖音博主的
   "启用"打开 → 点"同步到线上"。（或直接把 `config/online-sources.json`
   里抖音条目的 `enabled` 改为 `true` 后提交推送。）

未配置这两个变量时，workflow 会跳过抖音步骤，其余信源完全不受影响。

## 验收清单

1. 云电脑手动跑脚本 → 桥接仓库有新 commit，`manifest.json` 的 `generated_at` 是刚才。
2. Actions 手动触发一次 `Update AI News Snapshot` → 日志里 `Fetch Douyin bridge JSONL`
   步骤显示 `bridge jsonl found`。
3. 跑完后 `data/source-status.json` 的 `mediacrawler_douyin` 段：`ok=true`、
   `item_count>0`、`subscriptions` 里每个博主 `ok=true`。
4. 公网页面出现抖音内容（"我的订阅"分类），来源名为博主昵称。
5. 等一次计划任务自动运行，确认无人值守链路成立。

## 日常运维与故障排查

| 现象 | 原因与处理 |
| --- | --- |
| source-status 里 `mediacrawler_douyin_jsonl_not_found` | 桥接仓库没有 JSONL 或 Actions 未配置 bridge 变量；查云电脑计划任务是否正常跑 |
| 采集到 0 条 / MediaCrawler 报登录失效 | 抖音 session 过期，远程桌面进云电脑手动跑一次脚本重新扫码 |
| 桥接仓库 push 失败 | PAT 过期（Fine-grained 最长一年），重新生成并更新凭证 |
| 新增/删除抖音博主 | 本地控制台线上信源面板改 → 同步到线上；云电脑下次运行自动 `git pull` 拿到新列表 |
| 采集频繁被风控 | 降低计划任务频率、调小 `-MaxNotes`；不要在多平台同时高频采集 |

## 安全边界

- 抖音登录态只存在云电脑的 `chrome-profile` 里，**不进任何仓库**。
- 桥接仓库必须是私有仓库；里面只有公开可见的作品元数据 JSONL，不含 cookie。
- PAT 只授权桥接仓库单库、最小权限；Actions 用的那枚是只读。
- 主仓库（公开）不出现任何 token/cookie/私有路径。

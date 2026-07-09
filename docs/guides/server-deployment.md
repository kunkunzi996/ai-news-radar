# Server Deployment Guide

这份手册用于把 AI News Radar 部署到自己的 Linux 服务器上自动跑。

推荐架构很简单：

1. `systemd timer` 每 30 分钟运行一次 `scripts/update_news.py`。
2. 脚本把最新数据写进 `data/*.json`。
3. `nginx` 只对外提供 `index.html`、`assets/` 和 `data/*.json`。

大白话解释：服务器后台定时“更新报纸”，Nginx 只负责“把报纸摆出来”。不要把 `scripts/local_server.py` 直接暴露到公网，因为它有写配置和启动本地维护动作的接口。

## 适用前提

- 服务器系统：Ubuntu 22.04 / 24.04 或类似 Linux。
- Python：3.11 或更新版本。
- 对外访问：Nginx。
- 项目目录：本文默认 `/opt/ai-news-radar`。
- 运行用户：本文默认 `ai-news-radar`。

如果你用宝塔、1Panel、Docker 或非 Ubuntu 系统，仍可参考命令含义，但路径和服务管理方式要按实际面板调整。

## 文件说明

本仓库提供 4 个模板：

- `deploy/systemd/ai-news-radar-refresh.service`：单次刷新任务。
- `deploy/systemd/ai-news-radar-refresh.timer`：每 30 分钟触发刷新。
- `deploy/nginx/ai-news-radar.conf`：Nginx 静态站点模板。
- `deploy/env/ai-news-radar.env.example`：环境变量示例，真实文件放到 `/etc/ai-news-radar.env`。

## 第一次部署

以下命令以 root 或 sudo 用户执行。

```bash
sudo apt update
sudo apt install -y git python3 python3-venv nginx
sudo useradd --system --create-home --shell /usr/sbin/nologin ai-news-radar
sudo mkdir -p /opt
sudo git clone https://github.com/LearnPrompt/ai-news-radar.git /opt/ai-news-radar
sudo chown -R ai-news-radar:ai-news-radar /opt/ai-news-radar
cd /opt/ai-news-radar
```

如果你部署的是自己的 fork，把 `git clone` 里的仓库地址换成你的仓库。

安装 Python 依赖：

```bash
sudo -u ai-news-radar python3 -m venv .venv
sudo -u ai-news-radar .venv/bin/python -m pip install --upgrade pip
sudo -u ai-news-radar .venv/bin/pip install -r requirements.txt
```

准备环境变量文件：

```bash
sudo install -m 600 -o root -g root deploy/env/ai-news-radar.env.example /etc/ai-news-radar.env
sudo nano /etc/ai-news-radar.env
```

没有私有源时可以先不改；有 cookie、API key、私有 OPML 时，只写进 `/etc/ai-news-radar.env` 或 `/etc/ai-news-radar/`，不要写进仓库。

先手动跑一次刷新：

```bash
sudo -u ai-news-radar /opt/ai-news-radar/.venv/bin/python /opt/ai-news-radar/scripts/update_news.py \
  --output-dir /opt/ai-news-radar/data \
  --window-hours 24 \
  --archive-days 3650 \
  --collect-window-hours 24 \
  --all-time
```

这一步先验证公开默认源能不能跑通。后面安装 `systemd` 服务后，服务会通过 `/etc/ai-news-radar.env` 自动读取私有环境变量。

成功后检查：

```bash
ls -lh /opt/ai-news-radar/data/latest-24h.json
python3 -m json.tool /opt/ai-news-radar/data/source-status.json >/dev/null
```

## 开启自动刷新

```bash
sudo cp deploy/systemd/ai-news-radar-refresh.service /etc/systemd/system/
sudo cp deploy/systemd/ai-news-radar-refresh.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ai-news-radar-refresh.timer
```

查看是否启动：

```bash
systemctl list-timers ai-news-radar-refresh.timer
sudo systemctl status ai-news-radar-refresh.service
sudo journalctl -u ai-news-radar-refresh.service -n 80 --no-pager
```

想立刻刷新一次：

```bash
sudo systemctl start ai-news-radar-refresh.service
```

## 配置 Nginx

复制模板：

```bash
sudo cp deploy/nginx/ai-news-radar.conf /etc/nginx/sites-available/ai-news-radar.conf
sudo nano /etc/nginx/sites-available/ai-news-radar.conf
```

把 `server_name example.com;` 改成你的域名。如果项目目录不是 `/opt/ai-news-radar`，同步修改 `root`。

启用站点：

```bash
sudo ln -s /etc/nginx/sites-available/ai-news-radar.conf /etc/nginx/sites-enabled/ai-news-radar.conf
sudo nginx -t
sudo systemctl reload nginx
```

如果需要 HTTPS，推荐用 Certbot：

```bash
sudo certbot --nginx -d your-domain.example
```

## 日常更新代码

```bash
cd /opt/ai-news-radar
sudo -u ai-news-radar git pull --ff-only
sudo -u ai-news-radar .venv/bin/pip install -r requirements.txt
sudo systemctl restart ai-news-radar-refresh.timer
sudo systemctl start ai-news-radar-refresh.service
```

如果 `git pull` 提示本地有改动，先不要硬重置。服务器上通常只应该改 `/etc/ai-news-radar.env` 和私有数据文件，仓库目录内的改动要先确认来源。

## 回滚方式

如果新版本刷新失败：

```bash
cd /opt/ai-news-radar
git log --oneline -5
sudo -u ai-news-radar git checkout <上一个可用提交>
sudo systemctl start ai-news-radar-refresh.service
```

如果只是 Nginx 配错了：

```bash
sudo nginx -t
sudo journalctl -u nginx -n 80 --no-pager
```

## 安全边界

- 不要把 `scripts/local_server.py` 绑定到公网地址。
- 不要提交 `/etc/ai-news-radar.env`、cookie、token、私有 OPML、`sources.config.json`、`local-secrets/`。
- Nginx 模板只允许访问网页、静态资源和 `data/*.json`，不会公开 `scripts/`、`docs/`、`deploy/`、`feeds/` 等目录。
- 付费 API 源默认关闭；打开前先确认成本上限。

## 验收清单

部署完成后按这几步验收：

1. 打开你的域名，页面能正常加载。
2. 浏览器访问 `/data/latest-24h.json`，能看到 JSON。
3. 运行 `systemctl list-timers ai-news-radar-refresh.timer`，能看到下一次触发时间。
4. 运行 `journalctl -u ai-news-radar-refresh.service -n 80 --no-pager`，没有 Python 报错。
5. 等一次自动刷新后，页面右上角更新时间发生变化。

# 六级词汇复习系统

面向天津大学用户的多账户 CET-6 词汇学习网站。支持邮箱验证、词典查词、
拼写建议、SM-2 间隔复习、Agent 批量导入、学习统计和个人 JSON 数据备份。

## 本地启动

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# 编辑 .env，填写 SECRET_KEY、邮箱密码和词典 API Key
set -a
source .env
set +a
python app.py
```

开发服务器监听 `0.0.0.0:6657`，SQLite 数据库默认位于
`data/vocab.db`。生产环境请使用下方的 Gunicorn 与 systemd 方案。

## 环境变量

| 变量 | 必需 | 说明 |
| --- | --- | --- |
| `SECRET_KEY` | 是 | Session 和签名令牌密钥，生产环境必须使用随机长字符串 |
| `DATABASE` | 建议 | SQLite 数据库路径，默认 `data/vocab.db` |
| `ECDICT_DATABASE` | 是 | 完整 ECDICT 数据库路径，默认 `data/ecdict.db` |
| `MATERIALS_DIR` | 建议 | 资料广场 PDF 目录，默认 `data/materials` |
| `ADMIN_EMAILS` | 建议 | 管理员邮箱白名单，多个邮箱用英文逗号分隔；管理员可动态扫描资料目录 |
| `SMTP_HOST` | 是 | SMTP 服务器地址 |
| `SMTP_PORT` | 是 | SMTP 端口，STARTTLS 通常使用 `587` |
| `SMTP_USERNAME` | 视服务而定 | SMTP 用户名 |
| `SMTP_PASSWORD` | 视服务而定 | SMTP 密码或授权码 |
| `SMTP_SECURITY` | 建议 | `ssl`、`starttls` 或 `plain`；天大邮箱云服务器部署建议 `ssl` |
| `SMTP_USE_TLS` | 兼容项 | 未设置 `SMTP_SECURITY` 时，`1` 使用 STARTTLS，`0` 使用普通 SMTP |
| `MAIL_FROM` | 是 | 验证和重置邮件的发件人地址 |
| `TRUST_PROXY` | 反向代理时 | 通过 Nginx 部署时设为 `1`，使外部链接使用正确域名和 HTTPS |
| `ONLINE_DICTIONARY_ENABLED` | 否 | `1` 启用在线兜底，`0` 仅使用本地数据，推荐 `0` |
| `DICTIONARY_CACHE_DATABASE` | 建议 | 在线词典缓存路径，默认 `data/dictionary-cache.db` |
| `DICTIONARY_API_TIMEOUT` | 否 | 单次在线词典请求超时秒数，默认 `8` |
| `MYMEMORY_EMAIL` | 否 | 提交给 MyMemory 的联系邮箱，可提高免费额度；不设置则不发送 |
| `MERRIAM_WEBSTER_API_KEY` | 否 | 在线兜底使用的 Learner's Dictionary API Key |

邮件服务未配置或发送失败时，注册账户仍会保留，用户可以稍后重新发送。

`.env.example` 只包含占位值，可以提交；实际 `.env` 已被 Git 忽略，禁止提交。
项目根目录 `.env` 使用普通的 `KEY=value` 格式，启动前通过
`set -a; source .env; set +a` 导出给应用进程。

## 服务器快速验收

在正式配置 systemd 前，可以临时验证服务器环境：

```bash
cd /home/ubuntu/Vocab
cp .env.example .env
nano .env
chmod 600 .env
set -a
source .env
set +a
venv/bin/python3 app.py
```

浏览器访问 `http://服务器IP:6657`。这只适合短期验收；Flask 开发服务器不应
长期直接暴露到公网。验收完成后应使用下方的 Gunicorn、systemd、Nginx 和
HTTPS 部署方案。

## 持久化部署

以下示例适用于 Ubuntu/Debian，使用 Gunicorn、systemd 和 Nginx。
代码放在 `/opt/vocab`，用户数据放在 `/var/lib/vocab`。升级代码时不会覆盖
SQLite 数据库和 ECDICT。

### 1. 安装代码与依赖

```bash
sudo apt update
sudo apt install -y git python3-venv nginx sqlite3
sudo useradd --system --home /opt/vocab --shell /usr/sbin/nologin vocab
sudo git clone https://github.com/Luchutong/Vocab.git /opt/vocab
sudo python3 -m venv /opt/vocab/venv
sudo /opt/vocab/venv/bin/pip install -r /opt/vocab/requirements.txt
sudo install -d -o vocab -g vocab -m 750 /var/lib/vocab /var/lib/vocab/materials
sudo chown -R vocab:vocab /opt/vocab
```

安装完整 ECDICT：

```bash
sudo -u vocab ECDICT_DATABASE=/var/lib/vocab/ecdict.db \
  /opt/vocab/venv/bin/flask --app /opt/vocab/app.py download-dictionary
```

官方 SQLite 压缩包约 217 MB，解压后的数据库约 851 MB，安装时建议至少预留
1.2 GB 可用空间。词典文件不进入 Git，应保存在 `/var/lib/vocab` 等持久化目录。
应用仍有小型高频词后备库，但生产环境应确认完整词典安装成功：

```bash
sqlite3 /var/lib/vocab/ecdict.db \
  "SELECT COUNT(*) FROM stardict;"

# 或使用应用自带诊断命令
sudo -u vocab ECDICT_DATABASE=/var/lib/vocab/ecdict.db \
  /opt/vocab/venv/bin/flask --app /opt/vocab/app.py dictionary-status
```

### 2. 配置密钥和邮件

生成密钥：

```bash
python3 -c 'import secrets; print(secrets.token_hex(32))'
```

创建 `/etc/vocab.env`：

```ini
SECRET_KEY=替换为上一步生成的随机字符串
DATABASE=/var/lib/vocab/vocab.db
ECDICT_DATABASE=/var/lib/vocab/ecdict.db
DICTIONARY_CACHE_DATABASE=/var/lib/vocab/dictionary-cache.db
MATERIALS_DIR=/var/lib/vocab/materials
ONLINE_DICTIONARY_ENABLED=0
DICTIONARY_API_TIMEOUT=8
MERRIAM_WEBSTER_API_KEY=
SMTP_HOST=smtp.tju.edu.cn
SMTP_PORT=465
SMTP_USERNAME=你的邮箱@tju.edu.cn
SMTP_PASSWORD=password-or-app-token
SMTP_SECURITY=ssl
MAIL_FROM=你的邮箱@tju.edu.cn
TRUST_PROXY=1
```

保护配置文件：

```bash
sudo chown root:vocab /etc/vocab.env
sudo chmod 640 /etc/vocab.env
```

不要将 `/etc/vocab.env`、数据库或 SMTP 密码提交到 Git。

天大邮箱支持 `25 + STARTTLS` 和 `465 + SSL`。许多云厂商默认封锁出站
25 端口，因此服务器部署优先使用：

```ini
SMTP_HOST=smtp.tju.edu.cn
SMTP_PORT=465
SMTP_SECURITY=ssl
```

若邮件仍然失败，在服务器执行以下无密码诊断：

```bash
getent ahosts smtp.tju.edu.cn
timeout 8 bash -c '</dev/tcp/smtp.tju.edu.cn/465' && echo 端口可达
sudo systemctl show vocab --property=EnvironmentFiles
sudo journalctl -u vocab -n 100 --no-pager
```

修改 `/etc/vocab.env` 后必须执行 `sudo systemctl restart vocab`。注意 systemd
的 `EnvironmentFile` 使用 `KEY=value`，不要写 shell 的 `export KEY=value`。

### 3. 配置 systemd 常驻和开机自启

创建 `/etc/systemd/system/vocab.service`：

```ini
[Unit]
Description=CET-6 Vocab Builder
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=vocab
Group=vocab
WorkingDirectory=/opt/vocab
EnvironmentFile=/etc/vocab.env
ExecStart=/opt/vocab/venv/bin/gunicorn \
  --workers 2 \
  --threads 4 \
  --timeout 60 \
  --bind 127.0.0.1:6657 \
  --access-logfile - \
  --error-logfile - \
  app:app
Restart=always
RestartSec=5
PrivateTmp=true
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
```

启动并检查服务：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now vocab
sudo systemctl status vocab
sudo journalctl -u vocab -f
```

`Restart=always` 会在进程异常退出后自动重启，`enable` 会在服务器重启后自动启动。

### 4. 配置 Nginx

创建 `/etc/nginx/sites-available/vocab`：

```nginx
server {
    listen 80;
    server_name vocab.example.com;

    location / {
        proxy_pass http://127.0.0.1:6657;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 90;
    }
}
```

启用配置：

```bash
sudo ln -s /etc/nginx/sites-available/vocab /etc/nginx/sites-enabled/vocab
sudo nginx -t
sudo systemctl reload nginx
```

公网部署应使用 Certbot 或其他方式启用 HTTPS。邮箱验证链接会依据请求的
域名和协议生成，因此生产环境必须通过正式域名访问。

### 5. 本地词典

完整 [ECDICT](https://github.com/skywind3000/ECDICT) 是默认主词典。系统按以下
顺序查询：

1. ECDICT 精确词条。
2. 通过 ECDICT `exchange` 字段还原原形后查询。
3. 内置高频词后备库。
4. 可选在线 API 兜底。

本地释义会去除纯英文行、重复项和词性前缀，并限制卡片长度。拼写建议优先从
完整 ECDICT 词表生成。正常查词不访问网络、不消耗 API 配额，SQLite 精确查询
通常为毫秒级。

测验中的变形词只读取 ECDICT `exchange` 字段，并同时验证目标词条确实存在。
系统按原词的主要词性过滤候选，例如形容词 `quick` 只会测试 `quicker` 和
`quickest`，不会测试罕见名词复数 `quicks`。检查答案后会逐项展示变形类型。

如需在线兜底，将 `ONLINE_DICTIONARY_ENABLED=1` 并配置
`MERRIAM_WEBSTER_API_KEY`。Key 只能放在服务端环境文件中，不得写入前端、
源码或 Git。在线服务受第三方额度和使用条款约束。

### 6. 资料广场

“资料广场”读取 `MATERIALS_DIR` 中的文本型 PDF。应用启动时会递归扫描
`*.pdf`；配置 `ADMIN_EMAILS` 后，管理员也可以在资料广场点击
“重新扫描资料目录”动态入库，无需重启网站。扫描过程使用 PyMuPDF 提取整卷文本，
并按文件内容 SHA-256 去重写入
`materials` 表。扫描版 PDF 或无法提取足够英文文本的文件会被跳过并记录日志，
不会影响网站启动。

资料广场按目录生成分类夹。直接放在 `MATERIALS_DIR` 根目录下的 PDF 会归入
“真题”；放入子目录的 PDF 会以子目录名作为分类，例如
`/var/lib/vocab/materials/听力原文/*.pdf` 会显示在“听力原文”分类中。

本仓库不提交资料 PDF。部署时将资料单独上传到服务器：

```bash
sudo install -d -o vocab -g vocab -m 750 /var/lib/vocab/materials
sudo install -d -o vocab -g vocab -m 750 /var/lib/vocab/materials/听力原文
sudo cp 2025年12月英语六级真题*.pdf /var/lib/vocab/materials/
sudo cp 听力原文*.pdf /var/lib/vocab/materials/听力原文/
sudo chown vocab:vocab /var/lib/vocab/materials/*.pdf
sudo chown -R vocab:vocab /var/lib/vocab/materials/听力原文
```

确保 `.env` 中包含管理员邮箱：

```bash
ADMIN_EMAILS=luchutong@tju.edu.cn
```

随后用该邮箱登录，进入“资料广场”，点击“重新扫描资料目录”即可解析新 PDF。
如果尚未配置管理员邮箱，也可以重启服务触发启动扫描。

登录后进入“资料广场”，选择资料阅读。阅读页会按 PDF 原版面渲染页面图片，
并在英文单词坐标上叠加透明点击层；点击后显示释义浮层，并可将单词加入当天正式
测验。v1 不提供用户上传入口，后续优质资料上传会作为独立审核流程扩展。

### 7. 数据持久化和自动备份

需要持久化的文件：

- `/var/lib/vocab/vocab.db`：用户、单词、复习进度和设置。
- `/var/lib/vocab/dictionary-cache.db`：已查询词条的小型在线缓存。
- `/var/lib/vocab/ecdict.db`：完整 ECDICT，可重新下载，但保留可减少部署时间。
- `/var/lib/vocab/materials/`：资料广场 PDF，需单独上传，不进入 Git。
- `/etc/vocab.env`：密钥和邮件配置，应单独安全备份。

SQLite 在线备份请使用 SQLite 的备份命令，不要在服务运行时直接复制数据库：

```bash
sudo install -d -m 750 /var/backups/vocab
sudo sqlite3 /var/lib/vocab/vocab.db \
  ".backup '/var/backups/vocab/vocab-$(date +%F-%H%M%S).db'"
```

可在 root 的 crontab 中每日执行并保留最近 30 天：

```cron
15 3 * * * sqlite3 /var/lib/vocab/vocab.db ".backup '/var/backups/vocab/vocab-$(date +\%F-\%H\%M\%S).db'" && find /var/backups/vocab -type f -name 'vocab-*.db' -mtime +30 -delete
```

恢复前先停止服务，并保留当前数据库副本：

```bash
sudo systemctl stop vocab
sudo cp /var/lib/vocab/vocab.db /var/lib/vocab/vocab.db.before-restore
sudo cp /var/backups/vocab/选定的备份文件.db /var/lib/vocab/vocab.db
sudo chown vocab:vocab /var/lib/vocab/vocab.db
sudo systemctl start vocab
```

用户也可以在“词库管理”页面下载自己的完整 JSON 学习数据备份。

### 8. Agent 导入接口

用户可在“词库管理”进入“Agent 接口”，创建个人 Token。Token 明文只显示一次，
数据库仅保存 SHA-256 摘要；不用时应立即在页面撤销。调用必须使用 HTTPS：

```bash
curl https://你的域名/api/agent/import \
  -H "Authorization: Bearer vocab_替换为页面生成的Token" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: $(cat /proc/sys/kernel/random/uuid)" \
  --data '{"words":["abandon","dense","elapse"]}'
```

接口规则：

- `words` 必须是数组，单次最多 100 个，批内重复项只处理一次。
- 所有词条由服务端 ECDICT 校验，Agent 不能自行提交或伪造释义。
- 查询失败的项目会出现在 `failed` 中，不影响其他有效项目导入。
- 新词和已有词都会记录一次 `quality=3`、来源为 `agent_import` 的复习，并进入
  当天正式测验。
- 可传 `Idempotency-Key`。同一用户以相同 Key 重试时返回第一次结果，不重复写入。
- Token 仅能访问所属用户的词库，已撤销或未验证账户会返回 `401`。

生产环境建议在 Nginx 的 `http` 块声明限流区：

```nginx
limit_req_zone $binary_remote_addr zone=vocab_agent:10m rate=10r/m;
```

并在站点的 `server` 块中为接口单独添加：

```nginx
location = /api/agent/import {
    limit_req zone=vocab_agent burst=5 nodelay;
    proxy_pass http://127.0.0.1:6657;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

无需下载仓库、安装虚拟环境或配置 MCP。将 curl 命令中的 Token 和 `words`
数组交给 Agent 执行即可。不要把 Token 写进仓库、聊天提示词或公开配置；服务器
地址应使用正式 HTTPS 域名，不建议通过公网明文 HTTP 传输 Bearer Token。

### 9. 后续升级

```bash
sudo systemctl stop vocab
sudo -u vocab git -C /opt/vocab pull --ff-only
sudo -u vocab /opt/vocab/venv/bin/pip install -r /opt/vocab/requirements.txt
sudo systemctl start vocab
sudo systemctl status vocab
```

代码升级不会删除 `/var/lib/vocab` 中的持久化数据。升级前仍建议先执行一次
SQLite 在线备份。

## 测试

```bash
pytest -q
```

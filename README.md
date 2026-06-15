# 六级词汇复习系统

面向天津大学用户的多账户 CET-6 词汇学习网站。支持邮箱验证、词典查词、
拼写建议、SM-2 间隔复习、学习统计和个人 JSON 数据备份。

## 本地启动

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
export SECRET_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')"
python app.py
```

开发服务器监听 `0.0.0.0:6657`，SQLite 数据库默认位于
`data/vocab.db`。生产环境请使用下方的 Gunicorn 与 systemd 方案。

## 环境变量

| 变量 | 必需 | 说明 |
| --- | --- | --- |
| `SECRET_KEY` | 是 | Session 和签名令牌密钥，生产环境必须使用随机长字符串 |
| `DATABASE` | 建议 | SQLite 数据库路径，默认 `data/vocab.db` |
| `ECDICT_DATABASE` | 建议 | 完整 ECDICT 数据库路径，默认 `data/ecdict.db` |
| `SMTP_HOST` | 是 | SMTP 服务器地址 |
| `SMTP_PORT` | 是 | SMTP 端口，STARTTLS 通常使用 `587` |
| `SMTP_USERNAME` | 视服务而定 | SMTP 用户名 |
| `SMTP_PASSWORD` | 视服务而定 | SMTP 密码或授权码 |
| `SMTP_SECURITY` | 建议 | `ssl`、`starttls` 或 `plain`；天大邮箱云服务器部署建议 `ssl` |
| `SMTP_USE_TLS` | 兼容项 | 未设置 `SMTP_SECURITY` 时，`1` 使用 STARTTLS，`0` 使用普通 SMTP |
| `MAIL_FROM` | 是 | 验证和重置邮件的发件人地址 |
| `TRUST_PROXY` | 反向代理时 | 通过 Nginx 部署时设为 `1`，使外部链接使用正确域名和 HTTPS |
| `ONLINE_DICTIONARY_ENABLED` | 否 | `1` 启用在线词典，`0` 仅使用本地数据，默认 `1` |
| `DICTIONARY_CACHE_DATABASE` | 建议 | 在线词典缓存路径，默认 `data/dictionary-cache.db` |
| `DICTIONARY_API_TIMEOUT` | 否 | 单次在线词典请求超时秒数，默认 `8` |
| `MYMEMORY_EMAIL` | 否 | 提交给 MyMemory 的联系邮箱，可提高免费额度；不设置则不发送 |
| `MERRIAM_WEBSTER_API_KEY` | 建议 | Merriam-Webster Learner's Dictionary API Key，首选查词来源 |

邮件服务未配置或发送失败时，注册账户仍会保留，用户可以稍后重新发送。

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
sudo install -d -o vocab -g vocab -m 750 /var/lib/vocab
sudo chown -R vocab:vocab /opt/vocab
```

如需完整 ECDICT，可执行：

```bash
sudo -u vocab ECDICT_DATABASE=/var/lib/vocab/ecdict.db \
  /opt/vocab/venv/bin/flask --app /opt/vocab/app.py download-dictionary
```

应用自带离线高频词后备库，因此完整词典下载失败不会阻止服务启动。

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
ONLINE_DICTIONARY_ENABLED=1
DICTIONARY_API_TIMEOUT=8
MERRIAM_WEBSTER_API_KEY=替换为你的Learner词典API密钥
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

### 5. 在线词典与轻量部署

默认无需下载完整 ECDICT。配置 `MERRIAM_WEBSTER_API_KEY` 后，系统按以下
顺序查询：

1. Merriam-Webster 查询缓存。
2. Merriam-Webster Learner's Dictionary 校验拼写并获取音标、词性和学习者释义。
3. MyMemory 将释义转换为中文。
4. API 暂时故障时退回旧缓存、可选 ECDICT 和内置高频词库。
5. 未配置 Key 时使用 DictionaryAPI.dev 和 Datamuse 免费接口。

拼写错误时优先采用 Merriam-Webster 原生候选词，且不会为同一次输入重复请求。
成功查询会写入 `dictionary-cache.db`，同一单词以后直接使用缓存。Key 只能放在
服务端 `.env` 或 `/etc/vocab.env` 中，不得写入前端、源码或 Git。

Merriam-Webster API 受其订阅额度和使用条款约束。降级服务受第三方可用性和
免费额度约束。项目文档对
[Merriam-Webster](https://www.dictionaryapi.com/products/api-learners-dictionary)、
[DictionaryAPI.dev](https://dictionaryapi.dev/)、
[MyMemory](https://mymemory.translated.net/doc/spec.php) 和
[Datamuse](https://www.datamuse.com/api/) 表示感谢。若不希望服务器访问第三方
服务，将 `ONLINE_DICTIONARY_ENABLED=0`，并安装完整 ECDICT。

### 6. 数据持久化和自动备份

需要持久化的文件：

- `/var/lib/vocab/vocab.db`：用户、单词、复习进度和设置。
- `/var/lib/vocab/dictionary-cache.db`：已查询词条的小型在线缓存。
- `/var/lib/vocab/ecdict.db`：完整 ECDICT，可重新下载，但保留可减少部署时间。
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

### 7. 后续升级

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

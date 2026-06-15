# 六级词汇复习系统

面向天津大学用户的多账户 CET-6 词汇学习网站。支持词典查词、
拼写建议、SM-2 间隔复习、学习统计和个人 JSON 数据备份。

## 启动

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
export SECRET_KEY="请替换为随机长字符串"
python app.py
```

服务监听 `0.0.0.0:6657`，SQLite 数据库默认位于 `data/vocab.db`。

## 邮件配置

注册验证和密码找回需要以下环境变量：

```bash
export SMTP_HOST="smtp.example.com"
export SMTP_PORT="587"
export SMTP_USERNAME="username"
export SMTP_PASSWORD="password"
export SMTP_USE_TLS="1"
export MAIL_FROM="vocab@example.com"
```

邮件服务未配置或发送失败时，注册账户仍会保留，用户可以稍后重新发送。

## ECDICT

应用自带离线高频词后备库。若需要完整 ECDICT，将发行包中的
`stardict.db` 放置为 `data/ecdict.db`，或在 Python 中调用
`dict_query.download_ecdict()` 下载。也可以运行：

```bash
flask --app app download-dictionary
```

## 测试

```bash
pytest -q
```

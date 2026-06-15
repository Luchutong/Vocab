import json
import os
import random
import re
import secrets
import smtplib
import ssl
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from functools import wraps
from io import BytesIO

from flask import (
    Flask,
    abort,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash

from dict_query import download_ecdict, lookup, suggestions
from models import (
    get_db,
    get_setting,
    init_user_settings,
    register_app,
    set_setting,
)
from spaced_repetition import SM2Calculator, reviewed_at_iso
from variations import get_variations


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
EMAIL_RE = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@tju\.edu\.cn$")
WORD_RE = re.compile(r"^[A-Za-z]+(?:[-'][A-Za-z]+)*$")


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev-change-this-secret"),
        DATABASE=os.environ.get(
            "DATABASE", os.path.join(BASE_DIR, "data", "vocab.db")
        ),
        SMTP_HOST=os.environ.get("SMTP_HOST", ""),
        SMTP_PORT=int(os.environ.get("SMTP_PORT", "587")),
        SMTP_USERNAME=os.environ.get("SMTP_USERNAME", ""),
        SMTP_PASSWORD=os.environ.get("SMTP_PASSWORD", ""),
        SMTP_USE_TLS=os.environ.get("SMTP_USE_TLS", "1") != "0",
        SMTP_SECURITY=os.environ.get("SMTP_SECURITY", "").strip().lower(),
        MAIL_FROM=os.environ.get("MAIL_FROM", ""),
        TRUST_PROXY=os.environ.get("TRUST_PROXY", "0") == "1",
    )
    if test_config:
        app.config.update(test_config)
    if app.config["TRUST_PROXY"]:
        app.wsgi_app = ProxyFix(
            app.wsgi_app, x_for=1, x_proto=1, x_host=1
        )

    register_app(app)
    register_routes(app)
    return app


def _app():
    from flask import current_app

    return current_app


def make_token(data, salt):
    return URLSafeTimedSerializer(_app().secret_key).dumps(data, salt=salt)


def read_token(token, salt, max_age):
    return URLSafeTimedSerializer(_app().secret_key).loads(
        token, salt=salt, max_age=max_age
    )


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            flash("请先登录后继续。", "warning")
            return redirect(url_for("login", next=request.path))
        if not g.user["is_verified"]:
            flash("请先完成邮箱验证。", "warning")
            return redirect(url_for("verify_notice"))
        return view(*args, **kwargs)

    return wrapped


def send_email(recipient, subject, body):
    app = _app()
    host = app.config["SMTP_HOST"]
    sender = app.config["MAIL_FROM"] or app.config["SMTP_USERNAME"]
    if not host or not sender:
        raise RuntimeError("邮件服务尚未配置")

    message = EmailMessage()
    message["From"] = sender
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)

    security = app.config["SMTP_SECURITY"]
    if not security:
        security = "starttls" if app.config["SMTP_USE_TLS"] else "plain"
    if security not in {"ssl", "starttls", "plain"}:
        raise RuntimeError("SMTP_SECURITY 必须是 ssl、starttls 或 plain")

    if security == "ssl":
        smtp_client = smtplib.SMTP_SSL(
            host,
            app.config["SMTP_PORT"],
            timeout=15,
            context=ssl.create_default_context(),
        )
    else:
        smtp_client = smtplib.SMTP(
            host, app.config["SMTP_PORT"], timeout=15
        )

    with smtp_client as smtp:
        smtp.ehlo()
        if security == "starttls":
            smtp.starttls(context=ssl.create_default_context())
            smtp.ehlo()
        if app.config["SMTP_USERNAME"]:
            smtp.login(
                app.config["SMTP_USERNAME"], app.config["SMTP_PASSWORD"]
            )
        smtp.send_message(message)


def send_verification(user):
    token = make_token(
        {"user_id": user["id"], "email": user["email"]}, "verify-email"
    )
    link = url_for("verify_email", token=token, _external=True)
    send_email(
        user["email"],
        "验证你的六级词汇系统账户",
        f"请在 24 小时内打开以下链接完成邮箱验证：\n\n{link}\n\n"
        "如果这不是你的操作，请忽略本邮件。",
    )


def record_review(user_id, word, quality, source="quiz", today=None):
    today = today or date.today()
    new_ef, interval, next_review, repetitions = SM2Calculator.calculate(
        quality,
        word["ease_factor"],
        word["interval"],
        word["repetitions"],
        today,
    )
    lapses = word["lapses"] + (1 if quality < 3 else 0)
    db = get_db()
    db.execute(
        """
        UPDATE words
        SET ease_factor=?, interval=?, repetitions=?, next_review=?, lapses=?
        WHERE id=? AND user_id=?
        """,
        (
            new_ef,
            interval,
            repetitions,
            next_review.isoformat(),
            lapses,
            word["id"],
            user_id,
        ),
    )
    db.execute(
        """
        INSERT INTO review_log(
            user_id, word_id, quality, ease_factor, interval, repetitions,
            next_review, reviewed_at, source
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            word["id"],
            quality,
            new_ef,
            interval,
            repetitions,
            next_review.isoformat(),
            reviewed_at_iso(),
            source,
        ),
    )
    set_setting(user_id, "last_review_date", today.isoformat())
    return {
        "ease_factor": new_ef,
        "interval": interval,
        "repetitions": repetitions,
        "next_review": next_review.isoformat(),
    }


def normalize_answer(text):
    return re.sub(r"[\s，。；、,;.!！？:：()（）]+", "", (text or "").lower())


def answer_is_correct(answer, meaning):
    normalized = normalize_answer(answer)
    if not normalized:
        return False
    parts = re.split(r"[\n；;，,、/]+", meaning or "")
    candidates = [normalize_answer(part) for part in parts if part.strip()]
    return any(
        normalized == item
        or (len(normalized) >= 2 and normalized in item)
        or (len(item) >= 2 and item in normalized)
        for item in candidates
    )


def rebalance_backlog(user_id):
    last_value = get_setting(user_id, "last_review_date", date.today().isoformat())
    try:
        last_date = date.fromisoformat(last_value)
    except ValueError:
        last_date = date.today()
    interrupted = (date.today() - last_date).days
    if interrupted <= 1:
        return None

    db = get_db()
    rows = db.execute(
        """
        SELECT * FROM words
        WHERE user_id=? AND next_review < ?
        """,
        (user_id, date.today().isoformat()),
    ).fetchall()
    if not rows:
        return None

    cap = max(1, int(get_setting(user_id, "daily_cap", "30")))
    ordered = sorted(
        rows,
        key=lambda row: SM2Calculator.risk_score(
            row["ease_factor"], row["lapses"], row["next_review"]
        ),
        reverse=True,
    )
    distribution = SM2Calculator.spread_backlog(len(ordered), cap)
    cursor = 0
    for day, count in distribution.items():
        for row in ordered[cursor : cursor + count]:
            db.execute(
                "UPDATE words SET next_review=? WHERE id=? AND user_id=?",
                (day, row["id"], user_id),
            )
        cursor += count
    db.commit()
    return {
        "days_interrupted": interrupted,
        "count": len(rows),
        "days": len(distribution),
    }


def register_routes(app):
    @app.cli.command("download-dictionary")
    def download_dictionary_command():
        """Download and install the full ECDICT database."""
        path = download_ecdict()
        print(f"ECDICT 已安装到：{path}")

    @app.before_request
    def load_user():
        user_id = session.get("user_id")
        g.user = (
            get_db()
            .execute(
                "SELECT id, email, is_verified, created_at FROM users WHERE id=?",
                (user_id,),
            )
            .fetchone()
            if user_id
            else None
        )
        if user_id and g.user is None:
            session.clear()

    @app.context_processor
    def inject_globals():
        return {"current_user": g.user, "today": date.today()}

    @app.route("/register", methods=("GET", "POST"))
    def register():
        if g.user and g.user["is_verified"]:
            return redirect(url_for("dashboard"))
        if request.method == "POST":
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "")
            confirm = request.form.get("confirm_password", "")
            error = None
            if not EMAIL_RE.fullmatch(email):
                error = "仅支持使用 @tju.edu.cn 邮箱注册。"
            elif len(password) < 8:
                error = "密码长度至少为 8 位。"
            elif password != confirm:
                error = "两次输入的密码不一致。"

            db = get_db()
            if error is None:
                try:
                    cursor = db.execute(
                        """
                        INSERT INTO users(email, password_hash, created_at)
                        VALUES (?, ?, ?)
                        """,
                        (
                            email,
                            generate_password_hash(password),
                            datetime.now().astimezone().isoformat(
                                timespec="seconds"
                            ),
                        ),
                    )
                    init_user_settings(cursor.lastrowid)
                    db.commit()
                except Exception as exc:
                    db.rollback()
                    if "UNIQUE" in str(exc):
                        error = "该邮箱已注册，请直接登录。"
                    else:
                        app.logger.exception("注册失败")
                        error = "注册失败，请稍后重试。"

            if error:
                flash(error, "error")
            else:
                user = db.execute(
                    "SELECT * FROM users WHERE email=?", (email,)
                ).fetchone()
                session.clear()
                session["user_id"] = user["id"]
                try:
                    send_verification(user)
                    flash("注册成功，验证邮件已发送，请检查邮箱。", "success")
                except Exception:
                    app.logger.exception("验证邮件发送失败")
                    flash(
                        "账户已创建，但验证邮件发送失败。请稍后点击重新发送。",
                        "warning",
                    )
                return redirect(url_for("verify_notice"))
        return render_template("register.html")

    @app.route("/login", methods=("GET", "POST"))
    def login():
        if g.user and g.user["is_verified"]:
            return redirect(url_for("dashboard"))
        if request.method == "POST":
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "")
            user = get_db().execute(
                "SELECT * FROM users WHERE email=?", (email,)
            ).fetchone()
            if user is None or not check_password_hash(
                user["password_hash"], password
            ):
                flash("邮箱或密码错误。", "error")
            else:
                session.clear()
                session["user_id"] = user["id"]
                if not user["is_verified"]:
                    flash("请先完成邮箱验证。", "warning")
                    return redirect(url_for("verify_notice"))
                next_url = request.args.get("next", "")
                if not next_url.startswith("/"):
                    next_url = url_for("dashboard")
                return redirect(next_url)
        return render_template("login.html")

    @app.route("/logout", methods=("POST",))
    def logout():
        session.clear()
        flash("你已安全退出。", "success")
        return redirect(url_for("login"))

    @app.route("/verify")
    def verify_notice():
        if g.user is None:
            return redirect(url_for("login"))
        if g.user["is_verified"]:
            return redirect(url_for("dashboard"))
        return render_template("verify_notice.html")

    @app.route("/verify/<token>")
    def verify_email(token):
        try:
            data = read_token(token, "verify-email", 24 * 3600)
        except SignatureExpired:
            flash("验证链接已过期，请重新发送。", "error")
            return redirect(url_for("verify_notice"))
        except BadSignature:
            abort(400, description="无效的验证链接")
        db = get_db()
        user = db.execute(
            "SELECT * FROM users WHERE id=? AND email=?",
            (data.get("user_id"), data.get("email")),
        ).fetchone()
        if user is None:
            abort(400, description="验证账户不存在")
        db.execute("UPDATE users SET is_verified=1 WHERE id=?", (user["id"],))
        db.commit()
        session.clear()
        session["user_id"] = user["id"]
        flash("邮箱验证成功，欢迎开始学习。", "success")
        return redirect(url_for("dashboard"))

    @app.route("/verify/resend", methods=("POST",))
    def resend_verification():
        if g.user is None:
            return redirect(url_for("login"))
        if g.user["is_verified"]:
            return redirect(url_for("dashboard"))
        user = get_db().execute(
            "SELECT * FROM users WHERE id=?", (g.user["id"],)
        ).fetchone()
        try:
            send_verification(user)
            flash("新的验证邮件已发送。", "success")
        except Exception:
            app.logger.exception("重发验证邮件失败")
            flash("邮件发送失败，请稍后重试。", "error")
        return redirect(url_for("verify_notice"))

    @app.route("/forgot-password", methods=("GET", "POST"))
    def forgot_password():
        if request.method == "POST":
            email = request.form.get("email", "").strip().lower()
            user = get_db().execute(
                "SELECT * FROM users WHERE email=?", (email,)
            ).fetchone()
            if user:
                token = make_token(
                    {"user_id": user["id"], "email": user["email"]},
                    "reset-password",
                )
                link = url_for("reset_password", token=token, _external=True)
                try:
                    send_email(
                        user["email"],
                        "重置你的六级词汇系统密码",
                        f"请在 1 小时内打开以下链接设置新密码：\n\n{link}",
                    )
                except Exception:
                    app.logger.exception("重置邮件发送失败")
            flash(
                "如果该邮箱已注册，密码重置邮件将很快发送。",
                "success",
            )
            return redirect(url_for("login"))
        return render_template("forgot_password.html")

    @app.route("/reset-password/<token>", methods=("GET", "POST"))
    def reset_password(token):
        try:
            data = read_token(token, "reset-password", 3600)
        except SignatureExpired:
            flash("密码重置链接已过期，请重新申请。", "error")
            return redirect(url_for("forgot_password"))
        except BadSignature:
            abort(400, description="无效的密码重置链接")
        user = get_db().execute(
            "SELECT * FROM users WHERE id=? AND email=?",
            (data.get("user_id"), data.get("email")),
        ).fetchone()
        if user is None:
            abort(400, description="账户不存在")
        if request.method == "POST":
            password = request.form.get("password", "")
            confirm = request.form.get("confirm_password", "")
            if len(password) < 8:
                flash("密码长度至少为 8 位。", "error")
            elif password != confirm:
                flash("两次输入的密码不一致。", "error")
            else:
                db = get_db()
                db.execute(
                    "UPDATE users SET password_hash=? WHERE id=?",
                    (generate_password_hash(password), user["id"]),
                )
                db.commit()
                flash("密码已重置，请使用新密码登录。", "success")
                return redirect(url_for("login"))
        return render_template("reset_password.html", token=token)

    @app.route("/")
    @login_required
    def dashboard():
        notice = rebalance_backlog(g.user["id"])
        db = get_db()
        today_value = date.today().isoformat()
        daily_cap = max(1, int(get_setting(g.user["id"], "daily_cap", "30")))
        reviewed_today = db.execute(
            """
            SELECT COUNT(*) FROM review_log
            WHERE user_id=? AND substr(reviewed_at, 1, 10)=?
            """,
            (g.user["id"], today_value),
        ).fetchone()[0]
        raw_due = db.execute(
            "SELECT COUNT(*) FROM words WHERE user_id=? AND next_review<=?",
            (g.user["id"], today_value),
        ).fetchone()[0]
        stats = {
            "due": min(raw_due, max(0, daily_cap - reviewed_today)),
            "reviewed": reviewed_today,
            "new": db.execute(
                "SELECT COUNT(*) FROM words WHERE user_id=? AND date_added=?",
                (g.user["id"], today_value),
            ).fetchone()[0],
            "total": db.execute(
                "SELECT COUNT(*) FROM words WHERE user_id=?", (g.user["id"],)
            ).fetchone()[0],
        }
        progress = db.execute(
            """
            SELECT
              SUM(CASE WHEN ease_factor>2.3 AND interval>21 THEN 1 ELSE 0 END),
              SUM(CASE WHEN repetitions=0 THEN 1 ELSE 0 END),
              COUNT(*)
            FROM words WHERE user_id=?
            """,
            (g.user["id"],),
        ).fetchone()
        mastered = progress[0] or 0
        new_count = progress[1] or 0
        learning = max(0, (progress[2] or 0) - mastered - new_count)

        heatmap = []
        forecast = []
        for offset in range(6, -1, -1):
            day = date.today() - timedelta(days=offset)
            count = db.execute(
                """
                SELECT COUNT(*) FROM review_log
                WHERE user_id=? AND substr(reviewed_at, 1, 10)=?
                """,
                (g.user["id"], day.isoformat()),
            ).fetchone()[0]
            heatmap.append({"date": day, "count": count})
        for offset in range(7):
            day = date.today() + timedelta(days=offset)
            count = db.execute(
                "SELECT COUNT(*) FROM words WHERE user_id=? AND next_review=?",
                (g.user["id"], day.isoformat()),
            ).fetchone()[0]
            forecast.append({"date": day, "count": count})
        return render_template(
            "dashboard.html",
            stats=stats,
            progress={
                "mastered": mastered,
                "learning": learning,
                "new": new_count,
                "total": progress[2] or 0,
            },
            heatmap=heatmap,
            forecast=forecast,
            daily_cap=daily_cap,
            backlog_notice=notice,
        )

    @app.route("/settings/daily-cap", methods=("POST",))
    @login_required
    def update_daily_cap():
        try:
            daily_cap = int(request.form.get("daily_cap", ""))
            if daily_cap < 1 or daily_cap > 500:
                raise ValueError
        except ValueError:
            flash("每日复习上限必须是 1 到 500 之间的整数。", "error")
        else:
            set_setting(g.user["id"], "daily_cap", daily_cap)
            get_db().commit()
            flash("每日复习上限已更新。", "success")
        return redirect(url_for("dashboard"))

    @app.route("/import")
    @login_required
    def import_words():
        rows = get_db().execute(
            """
            SELECT word, meaning, phonetic, pos FROM words
            WHERE user_id=? AND date_added=?
            ORDER BY id DESC
            """,
            (g.user["id"], date.today().isoformat()),
        ).fetchall()
        return render_template("import_words.html", imported=rows)

    @app.route("/api/import/lookup", methods=("POST",))
    @login_required
    def api_import_lookup():
        payload = request.get_json(silent=True) or {}
        word = payload.get("word", "").strip().lower()
        if not WORD_RE.fullmatch(word):
            return jsonify(
                ok=False,
                error="请输入有效英文单词，只能包含字母、连字符或撇号。",
            ), 400
        result = lookup(word)
        if result is None:
            return jsonify(
                ok=False,
                error="词典中未找到该单词，请检查拼写。",
                suggestions=suggestions(word),
            ), 404
        nonce = secrets.token_urlsafe(18)
        session["import_nonce"] = nonce
        token = make_token(
            {"word": word, **result, "nonce": nonce, "user_id": g.user["id"]},
            "import-word",
        )
        existing = get_db().execute(
            "SELECT id FROM words WHERE user_id=? AND word=?",
            (g.user["id"], word),
        ).fetchone()
        return jsonify(
            ok=True,
            word=word,
            **result,
            token=token,
            existing=bool(existing),
        )

    @app.route("/api/import/confirm", methods=("POST",))
    @login_required
    def api_import_confirm():
        payload = request.get_json(silent=True) or {}
        token = payload.get("token", "")
        try:
            data = read_token(token, "import-word", 10 * 60)
        except SignatureExpired:
            return jsonify(ok=False, error="查询结果已过期，请重新查询。"), 400
        except BadSignature:
            return jsonify(ok=False, error="无效的导入请求。"), 400
        nonce = session.pop("import_nonce", None)
        if (
            not nonce
            or nonce != data.get("nonce")
            or data.get("user_id") != g.user["id"]
        ):
            return jsonify(ok=False, error="该查询结果已使用或不属于你。"), 400

        db = get_db()
        word = db.execute(
            "SELECT * FROM words WHERE user_id=? AND word=?",
            (g.user["id"], data["word"]),
        ).fetchone()
        created = word is None
        if created:
            cursor = db.execute(
                """
                INSERT INTO words(
                    user_id, word, meaning, phonetic, pos, date_added,
                    next_review
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    g.user["id"],
                    data["word"],
                    data["definition"],
                    data.get("phonetic", ""),
                    data.get("pos", ""),
                    date.today().isoformat(),
                    date.today().isoformat(),
                ),
            )
            word = db.execute(
                "SELECT * FROM words WHERE id=?", (cursor.lastrowid,)
            ).fetchone()
        review = record_review(g.user["id"], word, 3, source="import")
        db.commit()
        return jsonify(
            ok=True,
            created=created,
            word=data["word"],
            definition=data["definition"],
            phonetic=data.get("phonetic", ""),
            pos=data.get("pos", ""),
            next_review=review["next_review"],
            message=(
                "单词已导入，并记录为今日复习。"
                if created
                else "该单词已在词库中，已记录为今日复习。"
            ),
        )

    @app.route("/words")
    @login_required
    def word_list():
        rows = get_db().execute(
            """
            SELECT * FROM words WHERE user_id=?
            ORDER BY date_added DESC, word COLLATE NOCASE
            """,
            (g.user["id"],),
        ).fetchall()
        groups = {}
        for row in rows:
            groups.setdefault(row["date_added"], []).append(row)
        return render_template("word_list.html", groups=groups)

    @app.route("/words/<int:word_id>/delete", methods=("POST",))
    @login_required
    def delete_word(word_id):
        db = get_db()
        cursor = db.execute(
            "DELETE FROM words WHERE id=? AND user_id=?",
            (word_id, g.user["id"]),
        )
        db.commit()
        flash("单词已删除。" if cursor.rowcount else "未找到该单词。", "success")
        return redirect(url_for("word_list"))

    def get_due_word(user_id):
        cap = max(1, int(get_setting(user_id, "daily_cap", "30")))
        reviewed_today = get_db().execute(
            """
            SELECT COUNT(*) FROM review_log
            WHERE user_id=? AND substr(reviewed_at, 1, 10)=?
            """,
            (user_id, date.today().isoformat()),
        ).fetchone()[0]
        if reviewed_today >= cap:
            return None, cap
        return get_db().execute(
            """
            SELECT * FROM words
            WHERE user_id=? AND next_review<=?
            ORDER BY ((1.0/ease_factor) * (1+lapses) *
                     MAX(1, julianday(?) - julianday(next_review))) DESC,
                     next_review, id
            LIMIT 1 OFFSET 0
            """,
            (user_id, date.today().isoformat(), date.today().isoformat()),
        ).fetchone(), cap

    @app.route("/quiz")
    @login_required
    def quiz():
        db = get_db()
        raw_due_count = db.execute(
            "SELECT COUNT(*) FROM words WHERE user_id=? AND next_review<=?",
            (g.user["id"], date.today().isoformat()),
        ).fetchone()[0]
        reviewed_today = db.execute(
            """
            SELECT COUNT(*) FROM review_log
            WHERE user_id=? AND substr(reviewed_at, 1, 10)=?
            """,
            (g.user["id"], date.today().isoformat()),
        ).fetchone()[0]
        word, cap = get_due_word(g.user["id"])
        question = None
        if word:
            forms = get_variations(word["word"], word["pos"])
            display = (
                random.choice(forms[1:])
                if len(forms) > 1 and random.random() < 0.3
                else word["word"]
            )
            question = {"id": word["id"], "display": display}
        return render_template(
            "quiz.html",
            due_count=min(raw_due_count, max(0, cap - reviewed_today)),
            question=question,
        )

    @app.route("/api/quiz/check", methods=("POST",))
    @login_required
    def api_quiz_check():
        payload = request.get_json(silent=True) or {}
        try:
            word_id = int(payload.get("word_id"))
        except (TypeError, ValueError):
            return jsonify(error="无效的单词编号。"), 400
        word = get_db().execute(
            "SELECT * FROM words WHERE id=? AND user_id=?",
            (word_id, g.user["id"]),
        ).fetchone()
        if word is None:
            return jsonify(error="单词不存在或不属于你。"), 404
        return jsonify(
            correct=answer_is_correct(payload.get("answer", ""), word["meaning"]),
            correct_answer=word["meaning"],
            variations=get_variations(word["word"], word["pos"]),
        )

    @app.route("/quiz", methods=("POST",))
    @login_required
    def submit_quiz():
        payload = request.get_json(silent=True) or {}
        try:
            word_id = int(payload.get("word_id"))
            quality = int(payload.get("quality"))
        except (TypeError, ValueError):
            return jsonify(error="提交参数无效。"), 400
        if quality not in (0, 2, 3, 5):
            return jsonify(error="请选择有效的记忆评分。"), 400
        db = get_db()
        word = db.execute(
            "SELECT * FROM words WHERE id=? AND user_id=?",
            (word_id, g.user["id"]),
        ).fetchone()
        if word is None:
            return jsonify(error="单词不存在或不属于你。"), 404
        review = record_review(g.user["id"], word, quality)
        db.commit()
        next_word, _cap = get_due_word(g.user["id"])
        if next_word is None:
            return jsonify(done=True, review=review)
        forms = get_variations(next_word["word"], next_word["pos"])
        display = (
            random.choice(forms[1:])
            if len(forms) > 1 and random.random() < 0.3
            else next_word["word"]
        )
        return jsonify(
            done=False,
            review=review,
            next_word={"id": next_word["id"], "display": display},
        )

    @app.route("/export")
    @login_required
    def export_data():
        db = get_db()
        db.execute("BEGIN")
        try:
            words = [
                dict(row)
                for row in db.execute(
                    """
                    SELECT id, word, meaning, phonetic, pos, example, date_added,
                           ease_factor, interval, repetitions, next_review,
                           lapses
                    FROM words WHERE user_id=? ORDER BY id
                    """,
                    (g.user["id"],),
                ).fetchall()
            ]
            logs = [
                dict(row)
                for row in db.execute(
                    """
                    SELECT id, word_id, quality, ease_factor, interval,
                           repetitions, next_review, reviewed_at, source
                    FROM review_log WHERE user_id=? ORDER BY id
                    """,
                    (g.user["id"],),
                ).fetchall()
            ]
            settings = {
                row["key"]: row["value"]
                for row in db.execute(
                    "SELECT key, value FROM user_settings WHERE user_id=?",
                    (g.user["id"],),
                ).fetchall()
            }
            db.commit()
        except Exception:
            db.rollback()
            raise

        exported_at = datetime.now().astimezone()
        payload = {
            "format_version": 1,
            "exported_at": exported_at.isoformat(timespec="seconds"),
            "account_email": g.user["email"],
            "words": words,
            "review_log": logs,
            "settings": settings,
        }
        content = json.dumps(
            payload, ensure_ascii=False, indent=2
        ).encode("utf-8")
        filename = exported_at.strftime("vocab-backup-%Y%m%d-%H%M%S.json")
        response = send_file(
            BytesIO(content),
            mimetype="application/json; charset=utf-8",
            as_attachment=True,
            download_name=filename,
        )
        response.headers["Cache-Control"] = "no-store, max-age=0"
        response.headers["Pragma"] = "no-cache"
        return response

    @app.errorhandler(400)
    @app.errorhandler(404)
    @app.errorhandler(500)
    def error_page(error):
        code = getattr(error, "code", 500)
        if code == 500:
            message = "服务器暂时无法处理请求，请稍后重试。"
        else:
            message = getattr(error, "description", "请求无法完成。")
        return render_template("error.html", code=code, message=message), code


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=6657)

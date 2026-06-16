import json
import hashlib
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

from answer_matching import check_answer
from dict_query import download_ecdict, ecdict_status, lookup, suggestions
from material_library import (
    material_contains_word,
    sync_materials_from_directory,
    tokenize_material_text,
)
from models import (
    get_db,
    get_setting,
    init_user_settings,
    register_app,
    set_setting,
)
from spaced_repetition import SM2Calculator, reviewed_at_iso
from variations import get_variation_details


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
EMAIL_RE = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@tju\.edu\.cn$")
WORD_RE = re.compile(r"^[A-Za-z]+(?:[-'][A-Za-z]+)*$")
IDEMPOTENCY_KEY_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
AGENT_IMPORT_LIMIT = 100
AGENT_IMPORT_MAX_BODY = 64 * 1024


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev-change-this-secret"),
        DATABASE=os.environ.get(
            "DATABASE", os.path.join(BASE_DIR, "data", "vocab.db")
        ),
        MATERIALS_DIR=os.environ.get(
            "MATERIALS_DIR", os.path.join(BASE_DIR, "data", "materials")
        ),
        MATERIALS_AUTO_IMPORT=os.environ.get("MATERIALS_AUTO_IMPORT", "1")
        != "0",
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
    if app.config["MATERIALS_AUTO_IMPORT"]:
        with app.app_context():
            sync_materials_from_directory(app.config["MATERIALS_DIR"])
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


def hash_agent_token(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def agent_token_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        authorization = request.headers.get("Authorization", "")
        scheme, separator, token = authorization.partition(" ")
        if (
            not separator
            or scheme.lower() != "bearer"
            or not token.strip()
        ):
            return jsonify(
                ok=False,
                error="请使用 Authorization: Bearer <token> 进行认证。",
            ), 401
        row = get_db().execute(
            """
            SELECT t.id AS token_id, u.id, u.email, u.is_verified
            FROM agent_tokens AS t
            JOIN users AS u ON u.id=t.user_id
            WHERE t.token_hash=? AND t.revoked_at IS NULL
            """,
            (hash_agent_token(token.strip()),),
        ).fetchone()
        if row is None or not row["is_verified"]:
            return jsonify(ok=False, error="Agent Token 无效或已撤销。"), 401
        g.agent_user = row
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


def import_word_for_user(user_id, word_text, dictionary_entry, source):
    db = get_db()
    word = db.execute(
        "SELECT * FROM words WHERE user_id=? AND word=?",
        (user_id, word_text),
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
                user_id,
                word_text,
                dictionary_entry["definition"],
                dictionary_entry.get("phonetic", ""),
                dictionary_entry.get("pos", ""),
                date.today().isoformat(),
                date.today().isoformat(),
            ),
        )
        word = db.execute(
            "SELECT * FROM words WHERE id=?", (cursor.lastrowid,)
        ).fetchone()
    review = record_review(user_id, word, 3, source=source)
    return {
        "created": created,
        "word": word_text,
        "definition": dictionary_entry["definition"],
        "phonetic": dictionary_entry.get("phonetic", ""),
        "pos": dictionary_entry.get("pos", ""),
        "next_review": review["next_review"],
    }


def build_quiz_question(word):
    details = get_variation_details(word["word"], word["pos"])
    if details and random.random() < 0.3:
        selected = random.choice(details)
        return {
            "id": word["id"],
            "display": selected["form"],
            "form_type": selected["type"],
        }
    return {
        "id": word["id"],
        "display": word["word"],
        "form_type": "原形",
    }


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

    @app.cli.command("dictionary-status")
    def dictionary_status_command():
        """Show the local ECDICT installation status."""
        status = ecdict_status()
        print(f"路径：{status['path']}")
        print(f"存在：{'是' if status['exists'] else '否'}")
        print(f"大小：{status['size']} 字节")
        print(f"词条：{status['entries']}")

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

    def quiz_reviews_today(user_id):
        return get_db().execute(
            """
            SELECT COUNT(*) FROM review_log
            WHERE user_id=? AND source='quiz'
              AND substr(reviewed_at, 1, 10)=?
            """,
            (user_id, date.today().isoformat()),
        ).fetchone()[0]

    def due_words_count(user_id):
        today_value = date.today().isoformat()
        return get_db().execute(
            """
            SELECT COUNT(*) FROM words AS w
            WHERE w.user_id=? AND (
                w.next_review<=?
                OR (
                    (
                        w.date_added=?
                        OR EXISTS (
                            SELECT 1 FROM review_log AS imported
                            WHERE imported.user_id=w.user_id
                              AND imported.word_id=w.id
                              AND imported.source IN (
                                  'import', 'agent_import', 'material_import'
                              )
                              AND substr(imported.reviewed_at, 1, 10)=?
                        )
                    )
                    AND NOT EXISTS (
                        SELECT 1 FROM review_log AS r
                        WHERE r.user_id=w.user_id
                          AND r.word_id=w.id
                          AND r.source='quiz'
                          AND substr(r.reviewed_at, 1, 10)=?
                    )
                )
            )
            """,
            (
                user_id,
                today_value,
                today_value,
                today_value,
                today_value,
            ),
        ).fetchone()[0]

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
        quiz_reviewed = quiz_reviews_today(g.user["id"])
        raw_due = due_words_count(g.user["id"])
        stats = {
            "due": min(raw_due, max(0, daily_cap - quiz_reviewed)),
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

    @app.route("/materials")
    @login_required
    def material_square():
        rows = get_db().execute(
            """
            SELECT id, title, file_name, page_count, word_count, updated_at
            FROM materials
            WHERE is_published=1
            ORDER BY updated_at DESC, id DESC
            """
        ).fetchall()
        return render_template("materials.html", materials=rows)

    @app.route("/materials/<int:material_id>")
    @login_required
    def material_reader(material_id):
        material = get_db().execute(
            "SELECT * FROM materials WHERE id=? AND is_published=1",
            (material_id,),
        ).fetchone()
        if material is None:
            abort(404, description="资料不存在或尚未发布。")
        paragraphs = tokenize_material_text(material["content"])
        return render_template(
            "material_reader.html",
            material=material,
            paragraphs=paragraphs,
        )

    @app.route("/api/materials/<int:material_id>/lookup", methods=("POST",))
    @login_required
    def api_material_lookup(material_id):
        material = get_db().execute(
            "SELECT content FROM materials WHERE id=? AND is_published=1",
            (material_id,),
        ).fetchone()
        if material is None:
            return jsonify(ok=False, error="资料不存在或尚未发布。"), 404
        payload = request.get_json(silent=True) or {}
        word = payload.get("word", "").strip().lower()
        if not WORD_RE.fullmatch(word):
            return jsonify(ok=False, error="请选择有效英文单词。"), 400
        if not material_contains_word(material["content"], word):
            return jsonify(ok=False, error="该单词不在当前资料中。"), 400
        result = lookup(word)
        if result is None:
            return jsonify(
                ok=False,
                error="词典中未找到该单词，请检查拼写。",
                suggestions=suggestions(word),
            ), 404
        existing = get_db().execute(
            "SELECT id FROM words WHERE user_id=? AND word=?",
            (g.user["id"], word),
        ).fetchone()
        return jsonify(ok=True, word=word, **result, existing=bool(existing))

    @app.route("/api/materials/<int:material_id>/import", methods=("POST",))
    @login_required
    def api_material_import(material_id):
        material = get_db().execute(
            "SELECT content FROM materials WHERE id=? AND is_published=1",
            (material_id,),
        ).fetchone()
        if material is None:
            return jsonify(ok=False, error="资料不存在或尚未发布。"), 404
        payload = request.get_json(silent=True) or {}
        word = payload.get("word", "").strip().lower()
        if not WORD_RE.fullmatch(word):
            return jsonify(ok=False, error="请选择有效英文单词。"), 400
        if not material_contains_word(material["content"], word):
            return jsonify(ok=False, error="该单词不在当前资料中。"), 400
        result = lookup(word)
        if result is None:
            return jsonify(
                ok=False,
                error="词典中未找到该单词，请检查拼写。",
                suggestions=suggestions(word),
            ), 404
        imported = import_word_for_user(
            g.user["id"], word, result, source="material_import"
        )
        get_db().commit()
        return jsonify(
            ok=True,
            **imported,
            message=(
                "单词已从资料加入今日正式测验。"
                if imported["created"]
                else "该单词已在词库中，并已加入今日正式测验。"
            ),
        )

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

        imported = import_word_for_user(
            g.user["id"], data["word"], data, source="import"
        )
        get_db().commit()
        return jsonify(
            ok=True,
            **imported,
            message=(
                "单词已导入，并已加入今日正式测验。"
                if imported["created"]
                else "该单词已在词库中，并已加入今日正式测验。"
            ),
        )

    @app.route("/agent-access", methods=("GET", "POST"))
    @login_required
    def agent_access():
        new_token = None
        if request.method == "POST":
            name = request.form.get("name", "").strip()
            if not name:
                flash("请填写 Token 名称。", "error")
            elif len(name) > 50:
                flash("Token 名称不能超过 50 个字符。", "error")
            else:
                raw_token = "vocab_" + secrets.token_urlsafe(32)
                get_db().execute(
                    """
                    INSERT INTO agent_tokens(
                        user_id, name, token_hash, token_prefix, created_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        g.user["id"],
                        name,
                        hash_agent_token(raw_token),
                        raw_token[:14],
                        datetime.now().astimezone().isoformat(
                            timespec="seconds"
                        ),
                    ),
                )
                get_db().commit()
                new_token = raw_token
        tokens = get_db().execute(
            """
            SELECT id, name, token_prefix, created_at, last_used_at
            FROM agent_tokens
            WHERE user_id=? AND revoked_at IS NULL
            ORDER BY id DESC
            """,
            (g.user["id"],),
        ).fetchall()
        return render_template(
            "agent_access.html",
            tokens=tokens,
            new_token=new_token,
            api_base_url=request.url_root.rstrip("/"),
        )

    @app.route("/agent-access/<int:token_id>/revoke", methods=("POST",))
    @login_required
    def revoke_agent_token(token_id):
        cursor = get_db().execute(
            """
            UPDATE agent_tokens SET revoked_at=?
            WHERE id=? AND user_id=? AND revoked_at IS NULL
            """,
            (
                datetime.now().astimezone().isoformat(timespec="seconds"),
                token_id,
                g.user["id"],
            ),
        )
        get_db().commit()
        flash(
            "Agent Token 已撤销。" if cursor.rowcount else "未找到该 Token。",
            "success",
        )
        return redirect(url_for("agent_access"))

    @app.route("/api/agent/import", methods=("POST",))
    @agent_token_required
    def api_agent_import():
        if (
            request.content_length is not None
            and request.content_length > AGENT_IMPORT_MAX_BODY
        ):
            return jsonify(
                ok=False, error="请求体过大，最大允许 64 KiB。"
            ), 413
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify(ok=False, error="请求体必须是 JSON 对象。"), 400
        words = payload.get("words")
        if not isinstance(words, list) or not words:
            return jsonify(
                ok=False, error="words 必须是非空字符串数组。"
            ), 400
        if len(words) > AGENT_IMPORT_LIMIT:
            return jsonify(
                ok=False,
                error=f"单次最多导入 {AGENT_IMPORT_LIMIT} 个单词。",
            ), 400

        idempotency_key = request.headers.get(
            "Idempotency-Key", ""
        ).strip()
        if idempotency_key and not IDEMPOTENCY_KEY_RE.fullmatch(
            idempotency_key
        ):
            return jsonify(
                ok=False,
                error="Idempotency-Key 格式无效或超过 128 个字符。",
            ), 400
        db = get_db()
        if idempotency_key:
            previous = db.execute(
                """
                SELECT response_json FROM agent_import_requests
                WHERE user_id=? AND idempotency_key=?
                """,
                (g.agent_user["id"], idempotency_key),
            ).fetchone()
            if previous:
                response = jsonify(json.loads(previous["response_json"]))
                response.headers["Idempotency-Replayed"] = "true"
                return response

        normalized_words = []
        seen = set()
        failed = []
        for index, value in enumerate(words):
            if not isinstance(value, str):
                failed.append(
                    {
                        "input": value,
                        "index": index,
                        "error": "单词必须是字符串。",
                    }
                )
                continue
            word = value.strip().lower()
            if not WORD_RE.fullmatch(word):
                failed.append(
                    {
                        "input": value,
                        "index": index,
                        "error": "格式无效，只能包含字母、连字符或撇号。",
                    }
                )
                continue
            if word not in seen:
                normalized_words.append(word)
                seen.add(word)

        imported = []
        for word in normalized_words:
            result = lookup(word)
            if result is None:
                failed.append(
                    {
                        "input": word,
                        "error": "词典中未找到该单词。",
                        "suggestions": suggestions(word),
                    }
                )
                continue
            imported.append(
                import_word_for_user(
                    g.agent_user["id"],
                    word,
                    result,
                    source="agent_import",
                )
            )

        now = datetime.now().astimezone().isoformat(timespec="seconds")
        retention_boundary = (
            datetime.now().astimezone() - timedelta(days=7)
        ).isoformat(timespec="seconds")
        result_payload = {
            "ok": not failed,
            "imported_count": len(imported),
            "failed_count": len(failed),
            "imported": imported,
            "failed": failed,
            "message": (
                f"已将 {len(imported)} 个单词加入今日正式测验。"
                if imported
                else "没有单词被导入。"
            ),
        }
        if idempotency_key:
            db.execute(
                """
                INSERT INTO agent_import_requests(
                    user_id, idempotency_key, response_json, created_at
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    g.agent_user["id"],
                    idempotency_key,
                    json.dumps(result_payload, ensure_ascii=False),
                    now,
                ),
            )
        db.execute(
            "UPDATE agent_tokens SET last_used_at=? WHERE id=?",
            (now, g.agent_user["token_id"]),
        )
        db.execute(
            """
            DELETE FROM agent_import_requests
            WHERE user_id=? AND created_at<?
            """,
            (g.agent_user["id"], retention_boundary),
        )
        db.commit()
        return jsonify(result_payload)

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
        reviewed_today = quiz_reviews_today(user_id)
        if reviewed_today >= cap:
            return None, cap
        today_value = date.today().isoformat()
        return get_db().execute(
            """
            SELECT w.* FROM words AS w
            WHERE w.user_id=? AND (
                w.next_review<=?
                OR (
                    (
                        w.date_added=?
                        OR EXISTS (
                            SELECT 1 FROM review_log AS imported
                            WHERE imported.user_id=w.user_id
                              AND imported.word_id=w.id
                              AND imported.source IN (
                                  'import', 'agent_import', 'material_import'
                              )
                              AND substr(imported.reviewed_at, 1, 10)=?
                        )
                    )
                    AND NOT EXISTS (
                        SELECT 1 FROM review_log AS r
                        WHERE r.user_id=w.user_id
                          AND r.word_id=w.id
                          AND r.source='quiz'
                          AND substr(r.reviewed_at, 1, 10)=?
                    )
                )
            )
            ORDER BY
                CASE WHEN w.next_review<=? THEN 0 ELSE 1 END,
                ((1.0/w.ease_factor) * (1+w.lapses) *
                 MAX(1, julianday(?) - julianday(w.next_review))) DESC,
                w.next_review, w.id
            LIMIT 1 OFFSET 0
            """,
            (
                user_id,
                today_value,
                today_value,
                today_value,
                today_value,
                today_value,
                today_value,
            ),
        ).fetchone(), cap

    @app.route("/quiz")
    @login_required
    def quiz():
        raw_due_count = due_words_count(g.user["id"])
        reviewed_today = quiz_reviews_today(g.user["id"])
        word, cap = get_due_word(g.user["id"])
        question = build_quiz_question(word) if word else None
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
        variation_details = get_variation_details(
            word["word"], word["pos"]
        )
        answer_result = check_answer(
            payload.get("answer", ""), word["meaning"]
        )
        return jsonify(
            correct=answer_result["correct"],
            correct_answer=word["meaning"],
            match_type=answer_result["match_type"],
            matched_meaning=answer_result["matched_meaning"],
            base_word=word["word"],
            variations=variation_details,
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
        return jsonify(
            done=False,
            review=review,
            next_word=build_quiz_question(next_word),
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

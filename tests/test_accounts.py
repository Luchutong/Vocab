from app import make_token
from models import get_db


def test_registration_restricts_domain_and_hashes_password(
    app, client, monkeypatch
):
    response = client.post(
        "/register",
        data={
            "email": "student@example.com",
            "password": "password123",
            "confirm_password": "password123",
        },
    )
    assert "仅支持使用 @tju.edu.cn 邮箱注册".encode() in response.data

    monkeypatch.setattr("app.send_verification", lambda user: None)
    response = client.post(
        "/register",
        data={
            "email": "Student@TJU.EDU.CN",
            "password": "password123",
            "confirm_password": "password123",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "请验证你的邮箱".encode() in response.data
    with app.app_context():
        user = get_db().execute(
            "SELECT * FROM users WHERE email='student@tju.edu.cn'"
        ).fetchone()
        assert user is not None
        assert user["password_hash"] != "password123"
        assert user["is_verified"] == 0


def test_registration_survives_mail_failure(app, client, monkeypatch):
    def fail(_user):
        raise RuntimeError("SMTP unavailable")

    monkeypatch.setattr("app.send_verification", fail)
    response = client.post(
        "/register",
        data={
            "email": "mailfail@tju.edu.cn",
            "password": "password123",
            "confirm_password": "password123",
        },
        follow_redirects=True,
    )
    assert "账户已创建，但验证邮件发送失败".encode() in response.data
    with app.app_context():
        assert (
            get_db()
            .execute(
                "SELECT COUNT(*) FROM users WHERE email=?",
                ("mailfail@tju.edu.cn",),
            )
            .fetchone()[0]
            == 1
        )


def test_email_verification_and_unverified_access(app, client, make_user):
    user_id = make_user("verify@tju.edu.cn", verified=False)
    with client.session_transaction() as session:
        session["user_id"] = user_id
    assert client.get("/").status_code == 302

    with app.test_request_context():
        token = make_token(
            {"user_id": user_id, "email": "verify@tju.edu.cn"},
            "verify-email",
        )
    response = client.get(f"/verify/{token}", follow_redirects=True)
    assert "今天也稳稳向前".encode() in response.data
    with app.app_context():
        verified = get_db().execute(
            "SELECT is_verified FROM users WHERE id=?", (user_id,)
        ).fetchone()[0]
        assert verified == 1


def test_password_reset_changes_login_password(app, client, make_user):
    user_id = make_user("reset@tju.edu.cn")
    with app.test_request_context():
        token = make_token(
            {"user_id": user_id, "email": "reset@tju.edu.cn"},
            "reset-password",
        )
    response = client.post(
        f"/reset-password/{token}",
        data={
            "password": "newpassword123",
            "confirm_password": "newpassword123",
        },
        follow_redirects=True,
    )
    assert "密码已重置".encode() in response.data
    response = client.post(
        "/login",
        data={"email": "reset@tju.edu.cn", "password": "newpassword123"},
    )
    assert response.status_code == 302
    assert response.location == "/"

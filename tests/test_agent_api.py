import re
from datetime import date, timedelta

from app import hash_agent_token
from models import get_db
from tests.conftest import login_as


TOKEN_RE = re.compile(rb'id="new-agent-token">(vocab_[^<]+)</code>')


def create_agent_token(app, client, user_id, name="测试 Agent"):
    login_as(client, user_id)
    response = client.post("/agent-access", data={"name": name})
    assert response.status_code == 200
    match = TOKEN_RE.search(response.data)
    assert match
    token = match.group(1).decode()
    assert response.data.count(token.encode()) == 1
    with app.app_context():
        row = get_db().execute(
            "SELECT * FROM agent_tokens WHERE user_id=?", (user_id,)
        ).fetchone()
        assert row["token_hash"] == hash_agent_token(token)
        assert token not in tuple(row)
    return token


def test_agent_access_page_contains_complete_configuration_guide(
    client, make_user
):
    user_id = make_user("agent-docs@tju.edu.cn")
    login_as(client, user_id)
    response = client.get("/agent-access")
    assert response.status_code == 200
    for expected in (
        "创建个人 Token",
        "直接调用 HTTP API",
        "配置 stdio MCP",
        "验证配置",
        "常见问题",
        "requirements-mcp.txt",
        "VOCAB_API_URL=http://localhost",
        "VOCAB_API_TOKEN=vocab_替换为页面生成的Token",
        "import_words",
        "Idempotency-Key",
        "不要通过公网 HTTP 发送 Token",
    ):
        assert expected.encode() in response.data


def agent_headers(token, key=None):
    headers = {"Authorization": f"Bearer {token}"}
    if key:
        headers["Idempotency-Key"] = key
    return headers


def test_agent_import_requires_token_and_verified_account(
    app, client, make_user
):
    response = client.post(
        "/api/agent/import", json={"words": ["abandon"]}
    )
    assert response.status_code == 401

    user_id = make_user("unverified-agent@tju.edu.cn", verified=False)
    with app.app_context():
        get_db().execute(
            """
            INSERT INTO agent_tokens(
                user_id, name, token_hash, token_prefix, created_at
            ) VALUES (?, 'test', ?, 'vocab_test', ?)
            """,
            (
                user_id,
                hash_agent_token("vocab_unverified"),
                date.today().isoformat(),
            ),
        )
        get_db().commit()
    response = client.post(
        "/api/agent/import",
        json={"words": ["abandon"]},
        headers=agent_headers("vocab_unverified"),
    )
    assert response.status_code == 401


def test_agent_batch_import_isolated_validated_and_due_today(
    app, client, make_user, monkeypatch
):
    monkeypatch.setattr("dict_query.ONLINE_ENABLED", False)
    first_user = make_user("agent@tju.edu.cn")
    second_user = make_user("other-agent@tju.edu.cn")
    token = create_agent_token(app, client, first_user)

    response = client.post(
        "/api/agent/import",
        json={
            "words": [
                "abandon",
                "ability",
                "abandon",
                "abandn",
                "bad word!",
            ]
        },
        headers=agent_headers(token, "batch-1"),
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is False
    assert payload["imported_count"] == 2
    assert payload["failed_count"] == 2
    assert {item["word"] for item in payload["imported"]} == {
        "abandon",
        "ability",
    }

    with app.app_context():
        db = get_db()
        assert db.execute(
            "SELECT COUNT(*) FROM words WHERE user_id=?", (first_user,)
        ).fetchone()[0] == 2
        assert db.execute(
            "SELECT COUNT(*) FROM words WHERE user_id=?", (second_user,)
        ).fetchone()[0] == 0
        sources = db.execute(
            "SELECT source FROM review_log WHERE user_id=? ORDER BY id",
            (first_user,),
        ).fetchall()
        assert [row["source"] for row in sources] == [
            "agent_import",
            "agent_import",
        ]

    login_as(client, first_user)
    quiz_page = client.get("/quiz")
    assert 'id="due-count">2</strong>'.encode() in quiz_page.data


def test_agent_import_idempotency_and_revocation(
    app, client, make_user
):
    user_id = make_user("idempotent@tju.edu.cn")
    token = create_agent_token(app, client, user_id)
    headers = agent_headers(token, "same-request")
    first = client.post(
        "/api/agent/import",
        json={"words": ["abandon"]},
        headers=headers,
    )
    second = client.post(
        "/api/agent/import",
        json={"words": ["abandon"]},
        headers=headers,
    )
    assert first.status_code == second.status_code == 200
    assert second.headers["Idempotency-Replayed"] == "true"
    assert first.get_json() == second.get_json()
    with app.app_context():
        db = get_db()
        assert db.execute(
            "SELECT COUNT(*) FROM review_log WHERE user_id=?", (user_id,)
        ).fetchone()[0] == 1
        token_id = db.execute(
            "SELECT id FROM agent_tokens WHERE user_id=?", (user_id,)
        ).fetchone()[0]

    login_as(client, user_id)
    client.post(f"/agent-access/{token_id}/revoke")
    rejected = client.post(
        "/api/agent/import",
        json={"words": ["ability"]},
        headers=agent_headers(token),
    )
    assert rejected.status_code == 401


def test_reimported_old_word_is_available_in_same_day_quiz(
    app, client, make_user
):
    user_id = make_user("old-word@tju.edu.cn")
    with app.app_context():
        db = get_db()
        db.execute(
            """
            INSERT INTO words(
                user_id, word, meaning, date_added, next_review
            ) VALUES (?, 'abandon', '放弃', ?, ?)
            """,
            (
                user_id,
                (date.today() - timedelta(days=30)).isoformat(),
                (date.today() + timedelta(days=30)).isoformat(),
            ),
        )
        db.commit()
    token = create_agent_token(app, client, user_id)
    response = client.post(
        "/api/agent/import",
        json={"words": ["abandon"]},
        headers=agent_headers(token),
    )
    assert response.get_json()["imported"][0]["created"] is False

    login_as(client, user_id)
    quiz_page = client.get("/quiz")
    assert 'id="due-count">1</strong>'.encode() in quiz_page.data

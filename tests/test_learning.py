import json
from datetime import date, timedelta

from models import get_db
from tests.conftest import login_as


def test_import_flow_records_review_and_rejects_token_reuse(
    app, client, make_user
):
    user_id = make_user("learner@tju.edu.cn")
    login_as(client, user_id)

    lookup = client.post("/api/import/lookup", json={"word": "abandon"})
    assert lookup.status_code == 200
    result = lookup.get_json()
    assert result["definition"]
    assert result["existing"] is False

    confirmed = client.post(
        "/api/import/confirm", json={"token": result["token"]}
    )
    assert confirmed.status_code == 200
    assert confirmed.get_json()["created"] is True

    reused = client.post(
        "/api/import/confirm", json={"token": result["token"]}
    )
    assert reused.status_code == 400

    with app.app_context():
        db = get_db()
        word = db.execute(
            "SELECT * FROM words WHERE user_id=?", (user_id,)
        ).fetchone()
        assert word["repetitions"] == 1
        assert word["interval"] == 1
        assert word["next_review"] == (
            date.today() + timedelta(days=1)
        ).isoformat()
        log = db.execute(
            "SELECT * FROM review_log WHERE user_id=?", (user_id,)
        ).fetchone()
        assert log["quality"] == 3
        assert log["source"] == "import"


def test_existing_import_is_review_not_duplicate(app, client, make_user):
    user_id = make_user("repeat@tju.edu.cn")
    login_as(client, user_id)
    first = client.post(
        "/api/import/lookup", json={"word": "ability"}
    ).get_json()
    client.post("/api/import/confirm", json={"token": first["token"]})
    second = client.post(
        "/api/import/lookup", json={"word": "ability"}
    ).get_json()
    assert second["existing"] is True
    response = client.post(
        "/api/import/confirm", json={"token": second["token"]}
    )
    assert response.get_json()["created"] is False
    with app.app_context():
        db = get_db()
        assert (
            db.execute(
                "SELECT COUNT(*) FROM words WHERE user_id=?", (user_id,)
            ).fetchone()[0]
            == 1
        )
        assert (
            db.execute(
                "SELECT COUNT(*) FROM review_log WHERE user_id=?", (user_id,)
            ).fetchone()[0]
            == 2
        )


def test_spelling_failure_returns_suggestions(
    client, make_user, monkeypatch
):
    monkeypatch.setattr("dict_query.ONLINE_ENABLED", False)
    user_id = make_user("spelling@tju.edu.cn")
    login_as(client, user_id)
    response = client.post("/api/import/lookup", json={"word": "abandn"})
    assert response.status_code == 404
    payload = response.get_json()
    assert "abandon" in payload["suggestions"]
    assert client.post(
        "/api/import/lookup", json={"word": "bad word!"}
    ).status_code == 400


def test_user_isolation_for_word_access(app, client, make_user):
    first_user = make_user("first@tju.edu.cn")
    second_user = make_user("second@tju.edu.cn")
    with app.app_context():
        db = get_db()
        cursor = db.execute(
            """
            INSERT INTO words(
                user_id, word, meaning, date_added, next_review
            ) VALUES (?, 'private', '私有的', ?, ?)
            """,
            (first_user, date.today().isoformat(), date.today().isoformat()),
        )
        word_id = cursor.lastrowid
        db.commit()
    login_as(client, second_user)
    assert (
        client.post(
            "/api/quiz/check", json={"word_id": word_id, "answer": "私有的"}
        ).status_code
        == 404
    )
    client.post(f"/words/{word_id}/delete")
    with app.app_context():
        assert get_db().execute(
            "SELECT id FROM words WHERE id=?", (word_id,)
        ).fetchone()


def test_export_contains_only_current_user_and_no_secrets(
    app, client, make_user
):
    first_user = make_user("backup@tju.edu.cn")
    second_user = make_user("other@tju.edu.cn")
    with app.app_context():
        db = get_db()
        for user_id, word in (
            (first_user, "abandon"),
            (second_user, "secretword"),
        ):
            db.execute(
                """
                INSERT INTO words(
                    user_id, word, meaning, date_added, next_review
                ) VALUES (?, ?, '测试释义', ?, ?)
                """,
                (
                    user_id,
                    word,
                    date.today().isoformat(),
                    date.today().isoformat(),
                ),
            )
        db.commit()
    login_as(client, first_user)
    response = client.get("/export")
    assert response.status_code == 200
    assert response.headers["Content-Disposition"].startswith(
        "attachment; filename=vocab-backup-"
    )
    assert response.headers["Cache-Control"] == "no-store, max-age=0"
    payload = json.loads(response.data)
    assert payload["format_version"] == 1
    assert payload["account_email"] == "backup@tju.edu.cn"
    assert [word["word"] for word in payload["words"]] == ["abandon"]
    serialized = response.data.decode()
    assert "secretword" not in serialized
    assert "password_hash" not in serialized
    assert "test-secret" not in serialized


def test_export_requires_login(client):
    response = client.get("/export")
    assert response.status_code == 302
    assert "/login" in response.location

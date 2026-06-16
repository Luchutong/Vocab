import os
import sys

import pytest
from werkzeug.security import generate_password_hash


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app import create_app
from models import get_db, init_user_settings


@pytest.fixture
def app(tmp_path):
    application = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret",
            "DATABASE": str(tmp_path / "test.db"),
            "MATERIALS_AUTO_IMPORT": False,
            "SMTP_HOST": "",
        }
    )
    yield application


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def make_user(app):
    def factory(email, verified=True, password="password123"):
        with app.app_context():
            db = get_db()
            cursor = db.execute(
                """
                INSERT INTO users(email, password_hash, is_verified, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    email,
                    generate_password_hash(password),
                    int(verified),
                    "2026-06-15T10:00:00+08:00",
                ),
            )
            init_user_settings(cursor.lastrowid)
            db.commit()
            return cursor.lastrowid

    return factory


def login_as(client, user_id):
    with client.session_transaction() as session:
        session["user_id"] = user_id

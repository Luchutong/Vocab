import os
import sqlite3
from datetime import date

from flask import current_app, g


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    is_verified INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS words (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    word TEXT NOT NULL COLLATE NOCASE,
    meaning TEXT NOT NULL,
    phonetic TEXT DEFAULT '',
    pos TEXT DEFAULT '',
    example TEXT DEFAULT '',
    date_added TEXT NOT NULL,
    ease_factor REAL NOT NULL DEFAULT 2.5,
    interval INTEGER NOT NULL DEFAULT 0,
    repetitions INTEGER NOT NULL DEFAULT 0,
    next_review TEXT NOT NULL,
    lapses INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    UNIQUE (user_id, word)
);

CREATE TABLE IF NOT EXISTS review_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    word_id INTEGER NOT NULL,
    quality INTEGER NOT NULL CHECK (quality BETWEEN 0 AND 5),
    ease_factor REAL NOT NULL,
    interval INTEGER NOT NULL,
    repetitions INTEGER NOT NULL,
    next_review TEXT NOT NULL,
    reviewed_at TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'quiz',
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (word_id) REFERENCES words(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS user_settings (
    user_id INTEGER NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    PRIMARY KEY (user_id, key),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS agent_tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    token_prefix TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_used_at TEXT,
    revoked_at TEXT,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS agent_import_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    idempotency_key TEXT NOT NULL,
    response_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    UNIQUE (user_id, idempotency_key)
);

CREATE TABLE IF NOT EXISTS materials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL DEFAULT '真题',
    title TEXT NOT NULL,
    file_name TEXT NOT NULL UNIQUE,
    file_hash TEXT NOT NULL UNIQUE,
    page_count INTEGER NOT NULL DEFAULT 0,
    word_count INTEGER NOT NULL DEFAULT 0,
    content TEXT NOT NULL,
    is_published INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_words_due
ON words(user_id, next_review);

CREATE INDEX IF NOT EXISTS idx_review_user_time
ON review_log(user_id, reviewed_at);

CREATE INDEX IF NOT EXISTS idx_agent_tokens_user
ON agent_tokens(user_id, revoked_at);

CREATE INDEX IF NOT EXISTS idx_materials_published
ON materials(is_published, updated_at);

"""


def get_db():
    if "db" not in g:
        path = current_app.config["DATABASE"]
        os.makedirs(os.path.dirname(path), exist_ok=True)
        g.db = sqlite3.connect(path)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
        g.db.execute("PRAGMA journal_mode = WAL")
        g.db.execute("PRAGMA busy_timeout = 5000")
    return g.db


def close_db(_error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = get_db()
    db.executescript(SCHEMA)
    ensure_column(
        db,
        "materials",
        "category",
        "ALTER TABLE materials ADD COLUMN category TEXT NOT NULL DEFAULT '真题'",
    )
    db.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_materials_category
        ON materials(category, is_published, updated_at)
        """
    )
    db.commit()


def ensure_column(db, table, column, statement):
    columns = {
        row["name"]
        for row in db.execute(f"PRAGMA table_info({table})").fetchall()
    }
    if column not in columns:
        db.execute(statement)


def init_user_settings(user_id):
    db = get_db()
    db.executemany(
        "INSERT OR IGNORE INTO user_settings(user_id, key, value) VALUES (?, ?, ?)",
        [
            (user_id, "daily_cap", "30"),
            (user_id, "last_review_date", date.today().isoformat()),
        ],
    )


def get_setting(user_id, key, default=None):
    row = get_db().execute(
        "SELECT value FROM user_settings WHERE user_id=? AND key=?",
        (user_id, key),
    ).fetchone()
    return row["value"] if row else default


def set_setting(user_id, key, value):
    get_db().execute(
        """
        INSERT INTO user_settings(user_id, key, value) VALUES (?, ?, ?)
        ON CONFLICT(user_id, key) DO UPDATE SET value=excluded.value
        """,
        (user_id, key, str(value)),
    )


def register_app(app):
    app.teardown_appcontext(close_db)
    with app.app_context():
        init_db()

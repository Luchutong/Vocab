from datetime import date, timedelta

import fitz

from app import create_app
from material_library import sync_materials_from_directory
from models import get_db
from tests.conftest import login_as


def write_pdf(path, text):
    document = fitz.open()
    page = document.new_page()
    page.insert_textbox(fitz.Rect(72, 72, 520, 760), text, fontsize=12)
    document.save(path)
    document.close()


def test_materials_auto_import_from_pdf_and_updates(tmp_path):
    materials_dir = tmp_path / "materials"
    materials_dir.mkdir()
    pdf = materials_dir / "sample.pdf"
    write_pdf(
        pdf,
        "Abandon long-term goals only after careful analysis. "
        "Students practice reading and vocabulary every day. "
        "Teachers encourage learners to explore authentic materials "
        "and review unfamiliar words with patient attention.",
    )
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret",
            "DATABASE": str(tmp_path / "test.db"),
            "MATERIALS_DIR": str(materials_dir),
            "MATERIALS_AUTO_IMPORT": True,
            "SMTP_HOST": "",
        }
    )
    with app.app_context():
        db = get_db()
        rows = db.execute("SELECT * FROM materials").fetchall()
        assert len(rows) == 1
        assert rows[0]["title"] == "sample"
        assert rows[0]["page_count"] == 1
        assert rows[0]["word_count"] >= 10

        result = sync_materials_from_directory(str(materials_dir))
        assert result["unchanged"] == 1
        assert db.execute("SELECT COUNT(*) FROM materials").fetchone()[0] == 1

        pdf.unlink()
        write_pdf(
            pdf,
            "Abandon resilient students explore material reading. "
            "Vocabulary learning continues through repeated practice. "
            "Careful readers compare passages, record phrases, and "
            "return to important details after class.",
        )
        result = sync_materials_from_directory(str(materials_dir))
        assert result["updated"] == 1
        assert db.execute("SELECT COUNT(*) FROM materials").fetchone()[0] == 1
        content = db.execute("SELECT content FROM materials").fetchone()[0]
        assert "resilient" in content


def test_empty_material_square_and_auth(app, client, make_user):
    assert client.get("/materials").status_code == 302
    user_id = make_user("materials-empty@tju.edu.cn")
    login_as(client, user_id)
    response = client.get("/materials")
    assert response.status_code == 200
    assert "资料库暂时为空".encode() in response.data


def test_material_reader_uses_pdf_page_image_and_word_overlay(
    app, client, make_user, tmp_path
):
    materials_dir = tmp_path / "materials"
    materials_dir.mkdir()
    app.config["MATERIALS_DIR"] = str(materials_dir)
    write_pdf(
        materials_dir / "reader.pdf",
        "Students don't abandon long-term goals.",
    )
    user_id = make_user("reader@tju.edu.cn")
    with app.app_context():
        db = get_db()
        published = db.execute(
            """
            INSERT INTO materials(
                title, file_name, file_hash, page_count, word_count, content,
                is_published, created_at, updated_at
            ) VALUES (
                '阅读测试', 'reader.pdf', 'hash-reader', 1, 8,
                'Students don''t abandon long-term goals.',
                1, '2026-06-16T10:00:00+08:00',
                '2026-06-16T10:00:00+08:00'
            )
            """
        ).lastrowid
        unpublished = db.execute(
            """
            INSERT INTO materials(
                title, file_name, file_hash, page_count, word_count, content,
                is_published, created_at, updated_at
            ) VALUES (
                '未发布', 'hidden.pdf', 'hash-hidden', 1, 1,
                'hidden content', 0, '2026-06-16T10:00:00+08:00',
                '2026-06-16T10:00:00+08:00'
            )
            """
        ).lastrowid
        db.commit()
    login_as(client, user_id)
    response = client.get(f"/materials/{published}")
    assert response.status_code == 200
    assert f"/materials/{published}/pages/1.png".encode() in response.data
    assert b'class="pdf-word-hit"' in response.data
    assert 'data-word="students"'.encode() in response.data
    assert b"material-reader" not in response.data
    assert client.get(f"/materials/{unpublished}").status_code == 404

    image = client.get(f"/materials/{published}/pages/1.png")
    assert image.status_code == 200
    assert image.mimetype == "image/png"


def test_material_lookup_and_import_join_today_quiz(
    app, client, make_user
):
    user_id = make_user("material-import@tju.edu.cn")
    with app.app_context():
        db = get_db()
        material_id = db.execute(
            """
            INSERT INTO materials(
                title, file_name, file_hash, page_count, word_count, content,
                is_published, created_at, updated_at
            ) VALUES (
                '导入测试', 'import.pdf', 'hash-import', 1, 4,
                'Students abandon old habits.', 1,
                '2026-06-16T10:00:00+08:00',
                '2026-06-16T10:00:00+08:00'
            )
            """
        ).lastrowid
        db.commit()
    login_as(client, user_id)

    lookup = client.post(
        f"/api/materials/{material_id}/lookup", json={"word": "abandon"}
    )
    assert lookup.status_code == 200
    assert lookup.get_json()["definition"]

    imported = client.post(
        f"/api/materials/{material_id}/import", json={"word": "abandon"}
    )
    assert imported.status_code == 200
    assert imported.get_json()["created"] is True
    with app.app_context():
        db = get_db()
        log = db.execute(
            "SELECT source FROM review_log WHERE user_id=?", (user_id,)
        ).fetchone()
        assert log["source"] == "material_import"

    quiz_page = client.get("/quiz")
    assert 'id="due-count">1</strong>'.encode() in quiz_page.data


def test_material_reimport_existing_future_word_is_due_today(
    app, client, make_user
):
    user_id = make_user("material-existing@tju.edu.cn")
    with app.app_context():
        db = get_db()
        material_id = db.execute(
            """
            INSERT INTO materials(
                title, file_name, file_hash, page_count, word_count, content,
                is_published, created_at, updated_at
            ) VALUES (
                '复习测试', 'existing.pdf', 'hash-existing', 1, 4,
                'Students abandon old habits.', 1,
                '2026-06-16T10:00:00+08:00',
                '2026-06-16T10:00:00+08:00'
            )
            """
        ).lastrowid
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
    login_as(client, user_id)
    response = client.post(
        f"/api/materials/{material_id}/import", json={"word": "abandon"}
    )
    assert response.get_json()["created"] is False
    quiz_page = client.get("/quiz")
    assert 'id="due-count">1</strong>'.encode() in quiz_page.data


def test_material_lookup_rejects_word_outside_material(
    app, client, make_user
):
    user_id = make_user("material-scope@tju.edu.cn")
    with app.app_context():
        db = get_db()
        material_id = db.execute(
            """
            INSERT INTO materials(
                title, file_name, file_hash, page_count, word_count, content,
                is_published, created_at, updated_at
            ) VALUES (
                '范围测试', 'scope.pdf', 'hash-scope', 1, 2,
                'Only reading.', 1, '2026-06-16T10:00:00+08:00',
                '2026-06-16T10:00:00+08:00'
            )
            """
        ).lastrowid
        db.commit()
    login_as(client, user_id)
    response = client.post(
        f"/api/materials/{material_id}/lookup", json={"word": "abandon"}
    )
    assert response.status_code == 400
    assert "不在当前资料" in response.get_json()["error"]

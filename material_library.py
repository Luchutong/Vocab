import hashlib
import os
import re
from datetime import datetime
from io import BytesIO
from pathlib import Path

from flask import current_app

from models import get_db


WORD_TOKEN_RE = re.compile(r"[A-Za-z]+(?:[-'][A-Za-z]+)*")
MIN_EXTRACTED_WORDS = 20


def material_word_count(text):
    return len(WORD_TOKEN_RE.findall(text or ""))


def material_contains_word(text, word):
    target = (word or "").lower()
    return any(
        match.group(0).lower() == target
        for match in WORD_TOKEN_RE.finditer(text or "")
    )


def material_title_from_filename(path):
    return Path(path).stem.replace("_", " ").strip()


def tokenize_material_text(text):
    paragraphs = []
    for block in re.split(r"\n\s*\n+", text or ""):
        block = block.strip()
        if not block:
            continue
        tokens = []
        cursor = 0
        for match in WORD_TOKEN_RE.finditer(block):
            if match.start() > cursor:
                tokens.append(
                    {"type": "text", "value": block[cursor : match.start()]}
                )
            value = match.group(0)
            tokens.append(
                {
                    "type": "word",
                    "value": value,
                    "lookup": value.lower(),
                }
            )
            cursor = match.end()
        if cursor < len(block):
            tokens.append({"type": "text", "value": block[cursor:]})
        if tokens:
            paragraphs.append(tokens)
    return paragraphs


def material_pdf_path(directory, file_name):
    base = Path(directory).resolve()
    path = (base / file_name).resolve()
    if base not in path.parents and path != base:
        raise ValueError("资料文件路径无效。")
    return path


def material_page_layout(path):
    import fitz

    pages = []
    with fitz.open(path) as document:
        for index, page in enumerate(document):
            words = []
            for raw in page.get_text("words"):
                x0, y0, x1, y1, text = raw[:5]
                if text.lower().startswith(("http://", "https://", "www.")):
                    continue
                match = WORD_TOKEN_RE.search(text)
                if not match:
                    continue
                words.append(
                    {
                        "text": match.group(0),
                        "lookup": match.group(0).lower(),
                        "left": round(x0 / page.rect.width * 100, 4),
                        "top": round(y0 / page.rect.height * 100, 4),
                        "width": round((x1 - x0) / page.rect.width * 100, 4),
                        "height": round((y1 - y0) / page.rect.height * 100, 4),
                    }
                )
            pages.append(
                {
                    "number": index + 1,
                    "width": round(page.rect.width, 2),
                    "height": round(page.rect.height, 2),
                    "words": words,
                }
            )
    return pages


def render_material_page(path, page_number, zoom=1.8):
    import fitz

    with fitz.open(path) as document:
        if page_number < 1 or page_number > document.page_count:
            raise IndexError("页码不存在。")
        page = document[page_number - 1]
        pixmap = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        return BytesIO(pixmap.tobytes("png"))


def extract_pdf_text(path):
    import fitz

    with fitz.open(path) as document:
        pages = []
        for page in document:
            text = page.get_text("text").strip()
            if text:
                pages.append(text)
        content = "\n\n".join(pages)
        return content, document.page_count


def _file_hash(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def import_material_pdf(path):
    file_name = os.path.basename(path)
    file_hash = _file_hash(path)
    content, page_count = extract_pdf_text(path)
    word_count = material_word_count(content)
    if word_count < MIN_EXTRACTED_WORDS:
        raise ValueError("PDF 中可解析英文文本过少，可能是扫描版。")

    db = get_db()
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    duplicate = db.execute(
        "SELECT id, file_name FROM materials WHERE file_hash=?",
        (file_hash,),
    ).fetchone()
    if duplicate and duplicate["file_name"] != file_name:
        return "duplicate"

    existing = db.execute(
        "SELECT id, file_hash FROM materials WHERE file_name=?",
        (file_name,),
    ).fetchone()
    title = material_title_from_filename(path)
    if existing:
        if existing["file_hash"] == file_hash:
            return "unchanged"
        db.execute(
            """
            UPDATE materials
            SET title=?, file_hash=?, page_count=?, word_count=?, content=?,
                is_published=?, updated_at=?
            WHERE id=?
            """,
            (
                title,
                file_hash,
                page_count,
                word_count,
                content,
                1,
                now,
                existing["id"],
            ),
        )
        return "updated"

    db.execute(
        """
        INSERT INTO materials(
            title, file_name, file_hash, page_count, word_count, content,
            is_published, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            title,
            file_name,
            file_hash,
            page_count,
            word_count,
            content,
            1,
            now,
            now,
        ),
    )
    return "created"


def sync_materials_from_directory(directory):
    path = Path(directory)
    if not path.exists():
        return {"created": 0, "updated": 0, "unchanged": 0, "skipped": 0}

    result = {"created": 0, "updated": 0, "unchanged": 0, "skipped": 0}
    for pdf_path in sorted(path.glob("*.pdf")):
        try:
            status = import_material_pdf(str(pdf_path))
        except Exception:
            current_app.logger.exception("资料解析失败：%s", pdf_path)
            result["skipped"] += 1
        else:
            result[status] = result.get(status, 0) + 1
    get_db().commit()
    return result

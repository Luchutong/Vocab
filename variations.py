import os
import re
import sqlite3


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get(
    "ECDICT_DATABASE", os.path.join(BASE_DIR, "data", "ecdict.db")
)

FORM_LABELS = {
    "p": "过去式",
    "d": "过去分词",
    "i": "现在分词",
    "3": "第三人称单数",
    "s": "复数",
    "r": "比较级",
    "t": "最高级",
}

POS_FORM_CODES = {
    "verb": {"p", "d", "i", "3"},
    "noun": {"s"},
    "adjective": {"r", "t"},
}


def _pos_scores(pos, translation):
    scores = {"verb": 0, "noun": 0, "adjective": 0}
    aliases = {
        "v": "verb",
        "n": "noun",
        "j": "adjective",
        "a": "adjective",
    }
    for code, weight in re.findall(r"([a-z]+):(\d+)", pos or "", re.I):
        category = aliases.get(code.lower())
        if category:
            scores[category] = max(scores[category], int(weight))

    if not any(scores.values()):
        prefixes = re.findall(
            r"(?:^|[\r\n])\s*(v[ti]?|n|a|adj)\.",
            translation or "",
            re.I,
        )
        for prefix in prefixes:
            category = aliases.get(prefix.lower()[0])
            if category:
                scores[category] = max(scores[category], 1)
    return scores


def _dominant_categories(pos, translation):
    scores = _pos_scores(pos, translation)
    highest = max(scores.values())
    if highest <= 0:
        return set()
    # Minor senses should not produce surprise quiz forms.
    threshold = max(20, highest * 0.5)
    return {
        category
        for category, score in scores.items()
        if score >= threshold
    }


def _parse_exchange(exchange):
    parsed = []
    for item in (exchange or "").split("/"):
        if ":" not in item:
            continue
        code, value = item.split(":", 1)
        code = code.strip()
        value = value.strip().lower()
        if code in FORM_LABELS and value:
            parsed.append((code, value))
    return parsed


def get_variation_details(word, pos=""):
    word = (word or "").strip().lower()
    if not word or not os.path.exists(DB_PATH):
        return []

    try:
        with sqlite3.connect(DB_PATH) as db:
            db.row_factory = sqlite3.Row
            row = db.execute(
                """
                SELECT word, COALESCE(pos, '') AS pos,
                       COALESCE(translation, '') AS translation,
                       COALESCE(exchange, '') AS exchange
                FROM stardict WHERE word=? COLLATE NOCASE LIMIT 1
                """,
                (word,),
            ).fetchone()
            if not row:
                return []

            categories = _dominant_categories(
                row["pos"], row["translation"]
            )
            allowed_codes = set()
            for category in categories:
                allowed_codes.update(POS_FORM_CODES[category])

            details = []
            by_form = {}
            for code, form in _parse_exchange(row["exchange"]):
                if code not in allowed_codes or form == word:
                    continue
                exists = db.execute(
                    """
                    SELECT 1 FROM stardict
                    WHERE word=? COLLATE NOCASE LIMIT 1
                    """,
                    (form,),
                ).fetchone()
                if not exists:
                    continue
                if form in by_form:
                    item = by_form[form]
                    item["type"] += "/" + FORM_LABELS[code]
                    item["code"] += "/" + code
                    continue
                item = {
                    "form": form,
                    "type": FORM_LABELS[code],
                    "code": code,
                }
                by_form[form] = item
                details.append(item)
            return details
    except sqlite3.Error:
        return []


def get_variations(word, pos=""):
    return [word.strip().lower()] + [
        item["form"] for item in get_variation_details(word, pos)
    ]

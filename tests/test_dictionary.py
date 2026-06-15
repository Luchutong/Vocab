import sqlite3

import dict_query


def create_ecdict(path):
    with sqlite3.connect(path) as db:
        db.execute(
            """
            CREATE TABLE stardict (
                word TEXT,
                phonetic TEXT,
                translation TEXT,
                pos TEXT,
                tag TEXT,
                exchange TEXT,
                frq INTEGER
            )
            """
        )
        db.executemany(
            """
            INSERT INTO stardict(
                word, phonetic, translation, pos, tag, exchange, frq
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "elapse",
                    "i'læps",
                    "v. （时间）流逝\n过去\nTime to Elapse",
                    "v:100",
                    "cet6",
                    "p:elapsed/d:elapsed/i:elapsing/3:elapses",
                    9000,
                ),
                (
                    "elapsed",
                    "",
                    "",
                    "",
                    "",
                    "0:elapse/1:p",
                    18000,
                ),
                (
                    "abandon",
                    "ə'bændən",
                    "v. 放弃\n抛弃",
                    "v:100",
                    "cet4 cet6",
                    "",
                    3000,
                ),
            ],
        )
        db.commit()


def test_ecdict_is_primary_and_cleans_local_definition(
    monkeypatch, tmp_path
):
    db_path = tmp_path / "ecdict.db"
    create_ecdict(db_path)
    monkeypatch.setattr(dict_query, "DB_PATH", str(db_path))
    monkeypatch.setattr(
        dict_query, "CACHE_PATH", str(tmp_path / "dictionary-cache.db")
    )
    monkeypatch.setattr(dict_query, "MERRIAM_WEBSTER_API_KEY", "test-key")
    dict_query._cache_set(
        "elapse",
        {"definition": "错误在线释义", "phonetic": "bad", "pos": "noun"},
        "merriam-webster",
    )

    def should_not_run(_url):
        raise AssertionError("online API was called")

    monkeypatch.setattr(dict_query, "_request_json", should_not_run)
    assert dict_query.lookup("elapse") == {
        "definition": "（时间）流逝；过去",
        "phonetic": "i'læps",
        "pos": "v",
    }
    assert dict_query.lookup("elapsed") == {
        "definition": "（时间）流逝；过去",
        "phonetic": "i'læps",
        "pos": "v",
    }


def test_ecdict_provides_local_spelling_suggestions(
    monkeypatch, tmp_path
):
    db_path = tmp_path / "ecdict.db"
    create_ecdict(db_path)
    monkeypatch.setattr(dict_query, "DB_PATH", str(db_path))
    monkeypatch.setattr(dict_query, "ONLINE_ENABLED", False)
    assert dict_query.suggestions("abandn")[0] == "abandon"


def test_online_lookup_is_cached(monkeypatch, tmp_path):
    monkeypatch.setattr(
        dict_query, "CACHE_PATH", str(tmp_path / "dictionary-cache.db")
    )
    monkeypatch.setattr(dict_query, "DB_PATH", str(tmp_path / "missing.db"))
    monkeypatch.setattr(dict_query, "ONLINE_ENABLED", True)
    monkeypatch.setattr(dict_query, "MERRIAM_WEBSTER_API_KEY", "")
    calls = []

    def fake_request(url):
        calls.append(url)
        if "dictionaryapi" in url:
            return [
                {
                    "phonetics": [{"text": "/həˈləʊ/"}],
                    "meanings": [
                        {
                            "partOfSpeech": "interjection",
                            "definitions": [
                                {"definition": "A greeting."}
                            ],
                        }
                    ],
                }
            ]
        return {
            "responseData": {"translatedText": "你好"},
            "matches": [
                {"translation": "您好", "quality": "80"},
                {"translation": "bad result", "quality": "0"},
            ],
        }

    monkeypatch.setattr(dict_query, "_request_json", fake_request)
    result = dict_query.lookup("hello")
    assert result == {
        "definition": "你好；您好",
        "phonetic": "həˈləʊ",
        "pos": "interjection",
    }
    assert len(calls) == 2

    assert dict_query.lookup("hello") == result
    assert len(calls) == 2


def test_online_suggestions_and_local_fallback(monkeypatch, tmp_path):
    monkeypatch.setattr(dict_query, "ONLINE_ENABLED", True)
    monkeypatch.setattr(dict_query, "MERRIAM_WEBSTER_API_KEY", "")
    monkeypatch.setattr(dict_query, "DB_PATH", str(tmp_path / "missing.db"))
    monkeypatch.setattr(
        dict_query,
        "_request_json",
        lambda _url: [
            {"word": "abandon"},
            {"word": "abandoned"},
            {"word": "bad phrase"},
        ],
    )
    assert dict_query.suggestions("abandn", 3)[:2] == [
        "abandon",
        "abandoned",
    ]

    def fail(_url):
        raise OSError("offline")

    monkeypatch.setattr(dict_query, "_request_json", fail)
    assert "abandon" in dict_query.suggestions("abandn")


def test_merriam_webster_is_preferred_and_cached(monkeypatch, tmp_path):
    monkeypatch.setattr(
        dict_query, "CACHE_PATH", str(tmp_path / "dictionary-cache.db")
    )
    monkeypatch.setattr(dict_query, "DB_PATH", str(tmp_path / "missing.db"))
    monkeypatch.setattr(dict_query, "ONLINE_ENABLED", True)
    monkeypatch.setattr(dict_query, "MERRIAM_WEBSTER_API_KEY", "test-key")
    calls = []

    def fake_request(url):
        calls.append(url)
        if "mymemory" in url:
            if "to+ask+someone" in url:
                return {
                    "responseData": {
                        "translatedText": "要求某人付款|给设备充电"
                    },
                    "matches": [],
                }
            return {
                "responseData": {"translatedText": "收费；充电"},
                "matches": [],
            }
        assert "references/learners" in url
        assert "key=test-key" in url
        return [
            {
                "meta": {"id": "charge:1", "stems": ["charge", "charged"]},
                "fl": "verb",
                "hwi": {"prs": [{"ipa": "ˈtʃɑɚʤ"}]},
                "shortdef": ["to ask someone to pay", "to add electricity"],
            },
            {
                "meta": {"id": "charge:2", "stems": ["charge", "charges"]},
                "fl": "noun",
                "shortdef": ["an amount of money"],
            },
            {
                "meta": {"id": "charge account", "stems": ["charge account"]},
                "fl": "noun",
                "shortdef": ["an account for buying on credit"],
            },
        ]

    monkeypatch.setattr(dict_query, "_request_json", fake_request)
    result = dict_query.lookup("charge")
    assert result == {
        "definition": "收费；充电；要求某人付款；给设备充电",
        "phonetic": "ˈtʃɑɚʤ",
        "pos": "verb/noun",
    }
    assert len(calls) == 3
    assert dict_query.lookup("charge") == result
    assert len(calls) == 3


def test_merriam_webster_suggestions_avoid_second_request(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(
        dict_query, "CACHE_PATH", str(tmp_path / "dictionary-cache.db")
    )
    monkeypatch.setattr(dict_query, "DB_PATH", str(tmp_path / "missing.db"))
    monkeypatch.setattr(dict_query, "ONLINE_ENABLED", True)
    monkeypatch.setattr(dict_query, "MERRIAM_WEBSTER_API_KEY", "test-key")
    dict_query._MERRIAM_SUGGESTIONS.clear()
    calls = []

    def fake_request(url):
        calls.append(url)
        return ["abound in", "abandon", "abandoned", "bands"]

    monkeypatch.setattr(dict_query, "_request_json", fake_request)
    assert dict_query.lookup("abandn") is None
    assert dict_query.suggestions("abandn")[:2] == [
        "abandon",
        "abandoned",
    ]
    assert len(calls) == 1


def test_merriam_webster_failure_uses_existing_cache(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(
        dict_query, "CACHE_PATH", str(tmp_path / "dictionary-cache.db")
    )
    monkeypatch.setattr(dict_query, "ONLINE_ENABLED", True)
    monkeypatch.setattr(dict_query, "MERRIAM_WEBSTER_API_KEY", "test-key")
    monkeypatch.setattr(dict_query, "DB_PATH", str(tmp_path / "missing.db"))
    cached = {
        "definition": "原缓存",
        "phonetic": "test",
        "pos": "noun",
    }
    dict_query._cache_set("resilient", cached, "online")

    def fail(_url):
        raise OSError("offline")

    monkeypatch.setattr(dict_query, "_request_json", fail)
    assert dict_query.lookup("resilient") == cached

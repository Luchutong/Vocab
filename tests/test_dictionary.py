import dict_query


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


def test_online_suggestions_and_local_fallback(monkeypatch):
    monkeypatch.setattr(dict_query, "ONLINE_ENABLED", True)
    monkeypatch.setattr(dict_query, "MERRIAM_WEBSTER_API_KEY", "")
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

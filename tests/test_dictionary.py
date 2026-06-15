import dict_query


def test_online_lookup_is_cached(monkeypatch, tmp_path):
    monkeypatch.setattr(
        dict_query, "CACHE_PATH", str(tmp_path / "dictionary-cache.db")
    )
    monkeypatch.setattr(dict_query, "DB_PATH", str(tmp_path / "missing.db"))
    monkeypatch.setattr(dict_query, "ONLINE_ENABLED", True)
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

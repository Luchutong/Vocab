import sqlite3
from datetime import date

import pytest

from answer_matching import answer_is_correct, check_answer
from spaced_repetition import SM2Calculator
import variations
from variations import get_variation_details, get_variations


def test_sm2_success_and_failure_paths():
    first = SM2Calculator.calculate(3, 2.5, 0, 0, date(2026, 6, 15))
    assert first == (2.36, 1, date(2026, 6, 16), 1)

    second = SM2Calculator.calculate(5, first[0], 1, 1, date(2026, 6, 16))
    assert second[1:] == (3, date(2026, 6, 19), 2)

    failed = SM2Calculator.calculate(0, 1.4, 20, 8, date(2026, 6, 15))
    assert failed == (1.3, 1, date(2026, 6, 16), 0)


def test_sm2_rejects_invalid_quality_and_spreads_backlog():
    with pytest.raises(ValueError):
        SM2Calculator.calculate(6)
    allocation = SM2Calculator.spread_backlog(
        65, 30, start=date(2026, 6, 15)
    )
    assert sum(allocation.values()) == 65
    assert max(allocation.values()) <= 30
    assert len(allocation) == 3


def test_answer_matching_accepts_explicit_synonyms_without_fuzzy_guessing():
    result = check_answer("稠密的", "密集的；浓厚的")
    assert result == {
        "correct": True,
        "match_type": "synonym",
        "matched_meaning": "密集的",
    }
    assert answer_is_correct("密集", "密集的；浓厚的")
    assert not answer_is_correct("稀疏的", "密集的；浓厚的")
    assert not answer_is_correct("浓淡的", "密集的；浓厚的")


def test_variations_only_include_verified_dictionary_forms(
    monkeypatch, tmp_path
):
    db_path = tmp_path / "ecdict.db"
    with sqlite3.connect(db_path) as db:
        db.execute(
            """
            CREATE TABLE stardict (
                word TEXT, pos TEXT, translation TEXT, exchange TEXT
            )
            """
        )
        db.executemany(
            "INSERT INTO stardict VALUES (?, ?, ?, ?)",
            [
                (
                    "go",
                    "v:100",
                    "vi. 去",
                    "i:going/p:went/d:gone/3:goes/s:goes",
                ),
                ("going", "", "go的现在分词", "0:go/1:i"),
                ("went", "", "go的过去式", "0:go/1:p"),
                ("gone", "", "go的过去分词", "0:go/1:d"),
                ("goes", "", "go的第三人称单数", "0:go/1:3"),
                (
                    "quick",
                    "r:8/j:92",
                    "a. 快的\nadv. 快\nn. 要害",
                    "s:quicks/r:quicker/t:quickest",
                ),
                ("quicks", "", "quick的复数", "0:quick/1:s"),
                ("quicker", "", "quick的比较级", "0:quick/1:r"),
                ("quickest", "", "quick的最高级", "0:quick/1:t"),
                (
                    "happy",
                    "j:100",
                    "a. 快乐的",
                    "r:happier/t:happiest/s:missing-form",
                ),
                ("happier", "", "happy的比较级", "0:happy/1:r"),
                ("happiest", "", "happy的最高级", "0:happy/1:t"),
                ("child", "n:100", "n. 孩子", "s:children"),
                ("children", "", "child的复数", "0:child/1:s"),
                (
                    "create",
                    "v:100",
                    "vt. 创造",
                    "d:created/p:created/i:creating/3:creates",
                ),
                ("created", "", "create的过去式和过去分词", "0:create"),
                ("creating", "", "create的现在分词", "0:create"),
                ("creates", "", "create的第三人称单数", "0:create"),
            ],
        )
    monkeypatch.setattr(variations, "DB_PATH", str(db_path))

    assert {"go", "went", "gone", "going", "goes"} <= set(
        get_variations("go", "v")
    )
    assert get_variations("quick") == ["quick", "quicker", "quickest"]
    assert "quicks" not in get_variations("quick")
    assert get_variations("happy") == ["happy", "happier", "happiest"]
    assert "missing-form" not in get_variations("happy")
    assert "children" in get_variations("child", "n")
    assert get_variation_details("go") == [
        {"form": "going", "type": "现在分词", "code": "i"},
        {"form": "went", "type": "过去式", "code": "p"},
        {"form": "gone", "type": "过去分词", "code": "d"},
        {"form": "goes", "type": "第三人称单数", "code": "3"},
    ]
    assert get_variation_details("create")[0] == {
        "form": "created",
        "type": "过去分词/过去式",
        "code": "d/p",
    }

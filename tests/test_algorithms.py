from datetime import date

import pytest

from spaced_repetition import SM2Calculator
from variations import get_variations


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


def test_variations_include_regular_and_irregular_forms():
    assert {"go", "went", "gone", "going", "goes"} <= set(
        get_variations("go", "v")
    )
    assert {"happy", "happier", "happiest", "happiness"} <= set(
        get_variations("happy", "adj")
    )
    assert "children" in get_variations("child", "n")

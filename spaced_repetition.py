import math
from datetime import date, datetime, timedelta


class SM2Calculator:
    DEFAULT_EASE = 2.5
    MIN_EASE = 1.3

    @classmethod
    def calculate(
        cls,
        quality,
        prev_ef=DEFAULT_EASE,
        prev_interval=0,
        reps=0,
        today=None,
    ):
        if quality not in range(6):
            raise ValueError("评分必须在 0 到 5 之间")

        today = today or date.today()
        if isinstance(today, str):
            today = date.fromisoformat(today)

        old_ef = max(float(prev_ef), cls.MIN_EASE)
        new_ef = old_ef + (
            0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02)
        )
        new_ef = max(cls.MIN_EASE, round(new_ef, 4))

        if quality >= 3:
            if reps == 0:
                interval = 1
            elif reps == 1:
                interval = 3
            else:
                interval = max(1, round(prev_interval * old_ef))
            new_reps = reps + 1
        else:
            interval = 1
            new_reps = 0

        return new_ef, interval, today + timedelta(days=interval), new_reps

    @staticmethod
    def spread_backlog(overdue_count, daily_cap=30, start=None):
        if overdue_count <= 0:
            return {}
        if daily_cap <= 0:
            raise ValueError("每日上限必须大于 0")
        start = start or date.today()
        days = math.ceil(overdue_count / daily_cap)
        base, remainder = divmod(overdue_count, days)
        return {
            (start + timedelta(days=i)).isoformat(): base + (i < remainder)
            for i in range(days)
        }

    @staticmethod
    def risk_score(ease_factor, lapses, next_review, today=None):
        today = today or date.today()
        if isinstance(next_review, str):
            next_review = date.fromisoformat(next_review)
        overdue_days = max(0, (today - next_review).days)
        return (1 / max(float(ease_factor), 0.01)) * (1 + lapses) * overdue_days


def reviewed_at_iso(now=None):
    now = now or datetime.now().astimezone()
    return now.isoformat(timespec="seconds")

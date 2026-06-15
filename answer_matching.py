import re


MEANING_SEPARATOR_RE = re.compile(r"[\n；;，,、/]+")
IGNORED_CHARACTERS_RE = re.compile(r"[\s，。；、,;.!！？:：()（）]+")
TRAILING_PARTICLES = ("的", "地", "得")

# Keep this list conservative. Each group represents interchangeable Chinese
# senses, not merely words that look similar.
SYNONYM_GROUPS = (
    frozenset(("密集", "稠密", "浓密")),
    frozenset(("浓厚", "浓郁")),
)


def normalize_answer(text):
    return IGNORED_CHARACTERS_RE.sub("", (text or "").lower())


def meaning_core(text):
    normalized = normalize_answer(text)
    while len(normalized) > 1 and normalized.endswith(TRAILING_PARTICLES):
        normalized = normalized[:-1]
    return normalized


def split_meanings(meaning):
    return [
        part.strip()
        for part in MEANING_SEPARATOR_RE.split(meaning or "")
        if part.strip()
    ]


def _synonym_group(value):
    for group in SYNONYM_GROUPS:
        if value in group:
            return group
    return None


def check_answer(answer, meaning):
    answer_core = meaning_core(answer)
    if not answer_core:
        return {
            "correct": False,
            "match_type": "none",
            "matched_meaning": None,
        }

    candidates = split_meanings(meaning)
    for candidate in candidates:
        candidate_core = meaning_core(candidate)
        if answer_core == candidate_core:
            return {
                "correct": True,
                "match_type": "exact",
                "matched_meaning": candidate,
            }

    for candidate in candidates:
        candidate_core = meaning_core(candidate)
        if (
            min(len(answer_core), len(candidate_core)) >= 2
            and (
                answer_core in candidate_core
                or candidate_core in answer_core
            )
        ):
            return {
                "correct": True,
                "match_type": "contained",
                "matched_meaning": candidate,
            }

    answer_group = _synonym_group(answer_core)
    if answer_group:
        for candidate in candidates:
            if meaning_core(candidate) in answer_group:
                return {
                    "correct": True,
                    "match_type": "synonym",
                    "matched_meaning": candidate,
                }

    return {
        "correct": False,
        "match_type": "none",
        "matched_meaning": None,
    }


def answer_is_correct(answer, meaning):
    return check_answer(answer, meaning)["correct"]

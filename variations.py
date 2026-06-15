import re

try:
    from nltk.stem import WordNetLemmatizer
except ImportError:  # pragma: no cover
    WordNetLemmatizer = None


IRREGULAR_VERBS = {
    "be": ["was", "were", "been", "being", "is"],
    "go": ["went", "gone", "going", "goes"],
    "take": ["took", "taken", "taking", "takes"],
    "write": ["wrote", "written", "writing", "writes"],
    "do": ["did", "done", "doing", "does"],
    "have": ["had", "having", "has"],
    "make": ["made", "making", "makes"],
    "come": ["came", "coming", "comes"],
    "see": ["saw", "seen", "seeing", "sees"],
    "get": ["got", "gotten", "getting", "gets"],
}
IRREGULAR_ADJECTIVES = {
    "big": ["bigger", "biggest"],
    "good": ["better", "best"],
    "bad": ["worse", "worst"],
    "little": ["less", "least"],
    "many": ["more", "most"],
}
IRREGULAR_NOUNS = {
    "child": ["children"],
    "man": ["men"],
    "woman": ["women"],
    "foot": ["feet"],
    "tooth": ["teeth"],
    "mouse": ["mice"],
    "person": ["people"],
}
DERIVATIONS = {
    "beauty": ["beautiful", "beautifully"],
    "happy": ["happiness", "unhappy", "happily"],
    "create": ["creation", "creative", "creativity"],
    "decide": ["decision", "decisive"],
    "vary": ["variation", "various", "variety"],
    "analyse": ["analysis", "analytical"],
    "analyze": ["analysis", "analytical"],
}


def _double_final(word):
    return bool(
        re.search(r"[^aeiou][aeiou][^aeiouwxy]$", word)
        and len(word) <= 6
    )


def _verb_forms(word):
    if word in IRREGULAR_VERBS:
        return IRREGULAR_VERBS[word]
    if word.endswith("e"):
        past = word + "d"
        ing = word[:-1] + "ing"
    elif word.endswith("y") and word[-2:-1] not in "aeiou":
        past = word[:-1] + "ied"
        ing = word + "ing"
    elif _double_final(word):
        past = word + word[-1] + "ed"
        ing = word + word[-1] + "ing"
    else:
        past = word + "ed"
        ing = word + "ing"

    if re.search(r"(s|sh|ch|x|z|o)$", word):
        third = word + "es"
    elif word.endswith("y") and word[-2:-1] not in "aeiou":
        third = word[:-1] + "ies"
    else:
        third = word + "s"
    return [past, past, ing, third]


def _adjective_forms(word):
    if word in IRREGULAR_ADJECTIVES:
        return IRREGULAR_ADJECTIVES[word]
    if word.endswith("y"):
        return [word[:-1] + "ier", word[:-1] + "iest"]
    if word.endswith("e"):
        return [word + "r", word + "st"]
    if _double_final(word):
        return [word + word[-1] + "er", word + word[-1] + "est"]
    return [word + "er", word + "est"]


def _noun_forms(word):
    if word in IRREGULAR_NOUNS:
        return IRREGULAR_NOUNS[word]
    if re.search(r"(s|sh|ch|x|z)$", word):
        return [word + "es"]
    if word.endswith("y") and word[-2:-1] not in "aeiou":
        return [word[:-1] + "ies"]
    if word.endswith("f"):
        return [word[:-1] + "ves"]
    if word.endswith("fe"):
        return [word[:-2] + "ves"]
    return [word + "s"]


def get_variations(word, pos=""):
    word = word.strip().lower()
    if not word:
        return []
    forms = [word]
    pos_lower = (pos or "").lower()
    if pos_lower.startswith("v") or "动" in pos_lower:
        forms.extend(_verb_forms(word))
    if pos_lower.startswith("adj") or "形" in pos_lower:
        forms.extend(_adjective_forms(word))
    if pos_lower.startswith("n") or "名" in pos_lower:
        forms.extend(_noun_forms(word))
    forms.extend(DERIVATIONS.get(word, []))

    if WordNetLemmatizer:
        try:
            lemma = WordNetLemmatizer().lemmatize(word)
            forms.append(lemma)
        except LookupError:
            pass
    return list(dict.fromkeys(item for item in forms if item))

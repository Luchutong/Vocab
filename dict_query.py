import difflib
import json
import os
import re
import shutil
import sqlite3
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import zipfile


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.environ.get(
    "ECDICT_DATABASE", os.path.join(DATA_DIR, "ecdict.db")
)
CACHE_PATH = os.environ.get(
    "DICTIONARY_CACHE_DATABASE",
    os.path.join(DATA_DIR, "dictionary-cache.db"),
)
ARCHIVE_URL = (
    "https://github.com/skywind3000/ECDICT/releases/download/"
    "1.0.28/ecdict-sqlite-28.zip"
)
DICTIONARY_API_URL = os.environ.get(
    "DICTIONARY_API_URL",
    "https://api.dictionaryapi.dev/api/v2/entries/en/{word}",
)
TRANSLATION_API_URL = os.environ.get(
    "TRANSLATION_API_URL",
    "https://api.mymemory.translated.net/get",
)
DATAMUSE_API_URL = os.environ.get(
    "DATAMUSE_API_URL", "https://api.datamuse.com/sug"
)
MERRIAM_WEBSTER_API_URL = os.environ.get(
    "MERRIAM_WEBSTER_API_URL",
    "https://www.dictionaryapi.com/api/v3/references/learners/json/{word}",
)
MERRIAM_WEBSTER_API_KEY = os.environ.get(
    "MERRIAM_WEBSTER_API_KEY", ""
).strip()
ONLINE_ENABLED = os.environ.get("ONLINE_DICTIONARY_ENABLED", "0") != "0"
REQUEST_TIMEOUT = float(os.environ.get("DICTIONARY_API_TIMEOUT", "8"))
USER_AGENT = (
    "VocabBuilder/1.0 (+https://github.com/Luchutong/Vocab)"
)
_MERRIAM_SUGGESTIONS = {}
POS_ORDER = (
    "v",
    "n",
    "adj",
    "adv",
    "prep",
    "conj",
    "pron",
    "num",
    "art",
    "interj",
)

# This compact fallback keeps the application useful when the full ECDICT
# archive is unavailable. Common inflections are handled by variations.py.
_FALLBACK_ROWS = """
abandon|放弃；抛弃|əˈbændən|v
ability|能力；才能|əˈbɪləti|n
absorb|吸收；理解|əbˈzɔːb|v
abstract|抽象的；摘要|ˈæbstrækt|adj/n
academic|学术的；大学的|ˌækəˈdemɪk|adj
accelerate|加速；促进|əkˈseləreɪt|v
access|进入；使用权|ˈækses|n/v
accommodate|容纳；适应|əˈkɒmədeɪt|v
accompany|陪伴；伴随|əˈkʌmpəni|v
accumulate|积累；积聚|əˈkjuːmjəleɪt|v
accurate|准确的|ˈækjərət|adj
acknowledge|承认；确认|əkˈnɒlɪdʒ|v
acquire|获得；学到|əˈkwaɪə|v
adapt|适应；改编|əˈdæpt|v
adequate|足够的；合格的|ˈædɪkwət|adj
adjacent|邻近的|əˈdʒeɪsnt|adj
advocate|提倡；拥护者|ˈædvəkeɪt|v/n
allocate|分配|ˈæləkeɪt|v
alter|改变|ˈɔːltə|v
alternative|替代的；选择|ɔːlˈtɜːnətɪv|adj/n
ambiguous|模棱两可的|æmˈbɪɡjuəs|adj
analyse|分析|ˈænəlaɪz|v
anticipate|预期；期待|ænˈtɪsɪpeɪt|v
apparent|明显的；表面上的|əˈpærənt|adj
appeal|呼吁；吸引力|əˈpiːl|v/n
approach|接近；方法|əˈprəʊtʃ|v/n
appropriate|适当的|əˈprəʊpriət|adj
arbitrary|任意的；武断的|ˈɑːbɪtrəri|adj
aspect|方面|ˈæspekt|n
assess|评估|əˈses|v
assign|分配；指派|əˈsaɪn|v
assume|假定；承担|əˈsjuːm|v
attain|达到；获得|əˈteɪn|v
attribute|属性；归因于|ˈætrɪbjuːt|n/v
authentic|真实的；可信的|ɔːˈθentɪk|adj
aware|意识到的|əˈweə|adj
benefit|益处；受益|ˈbenɪfɪt|n/v
capacity|能力；容量|kəˈpæsəti|n
cease|停止|siːs|v
challenge|挑战|ˈtʃælɪndʒ|n/v
clarify|澄清|ˈklærəfaɪ|v
coherent|连贯的|kəʊˈhɪərənt|adj
collapse|倒塌；崩溃|kəˈlæps|v/n
compensate|补偿|ˈkɒmpenseɪt|v
compile|编译；汇编|kəmˈpaɪl|v
complement|补充；补足物|ˈkɒmplɪment|v/n
complex|复杂的；复合体|ˈkɒmpleks|adj/n
comprehensive|全面的|ˌkɒmprɪˈhensɪv|adj
concentrate|集中|ˈkɒnsntreɪt|v
concede|承认；让步|kənˈsiːd|v
conceive|构想；认为|kənˈsiːv|v
conclude|得出结论；结束|kənˈkluːd|v
concrete|具体的；混凝土|ˈkɒŋkriːt|adj/n
conduct|实施；行为|kənˈdʌkt|v/n
confirm|确认|kənˈfɜːm|v
conflict|冲突|ˈkɒnflɪkt|n/v
conform|符合；遵守|kənˈfɔːm|v
consent|同意|kənˈsent|n/v
consequence|后果|ˈkɒnsɪkwəns|n
considerable|相当大的|kənˈsɪdərəbl|adj
consistent|一致的|kənˈsɪstənt|adj
constitute|构成|ˈkɒnstɪtjuːt|v
constraint|限制；约束|kənˈstreɪnt|n
consult|咨询；查阅|kənˈsʌlt|v
consume|消耗；消费|kənˈsjuːm|v
contemporary|当代的；同时代的|kənˈtemprəri|adj
contradict|反驳；矛盾|ˌkɒntrəˈdɪkt|v
controversial|有争议的|ˌkɒntrəˈvɜːʃl|adj
conventional|传统的；常规的|kənˈvenʃənl|adj
convert|转变|kənˈvɜːt|v
cope|应付|kəʊp|v
crucial|关键的|ˈkruːʃl|adj
decline|下降；拒绝|dɪˈklaɪn|v/n
deduce|推断|dɪˈdjuːs|v
demonstrate|证明；展示|ˈdemənstreɪt|v
derive|获得；起源于|dɪˈraɪv|v
detect|发现；查明|dɪˈtekt|v
deteriorate|恶化|dɪˈtɪəriəreɪt|v
deviate|偏离|ˈdiːvieɪt|v
diminish|减少；削弱|dɪˈmɪnɪʃ|v
discriminate|区分；歧视|dɪˈskrɪmɪneɪt|v
distort|歪曲；扭曲|dɪˈstɔːt|v
diverse|多样的|daɪˈvɜːs|adj
domestic|国内的；家庭的|dəˈmestɪk|adj
elaborate|精心制作的；详述|ɪˈlæbərət|adj/v
eliminate|消除；淘汰|ɪˈlɪmɪneɪt|v
emerge|出现|ɪˈmɜːdʒ|v
emphasize|强调|ˈemfəsaɪz|v
empirical|以实验为依据的|ɪmˈpɪrɪkl|adj
encounter|遭遇|ɪnˈkaʊntə|v/n
enhance|提高；增强|ɪnˈhɑːns|v
ensure|确保|ɪnˈʃʊə|v
equivalent|相等的；等价物|ɪˈkwɪvələnt|adj/n
evaluate|评价|ɪˈvæljueɪt|v
evident|明显的|ˈevɪdənt|adj
exceed|超过|ɪkˈsiːd|v
exclude|排除|ɪkˈskluːd|v
explicit|明确的|ɪkˈsplɪsɪt|adj
facilitate|促进；使便利|fəˈsɪlɪteɪt|v
feasible|可行的|ˈfiːzəbl|adj
fluctuate|波动|ˈflʌktʃueɪt|v
fundamental|基本的；根本的|ˌfʌndəˈmentl|adj
generate|产生|ˈdʒenəreɪt|v
highlight|突出；亮点|ˈhaɪlaɪt|v/n
identify|识别；确认|aɪˈdentɪfaɪ|v
illustrate|说明；图解|ˈɪləstreɪt|v
implement|实施；工具|ˈɪmplɪment|v/n
imply|暗示|ɪmˈplaɪ|v
incentive|激励；动机|ɪnˈsentɪv|n
inevitable|不可避免的|ɪnˈevɪtəbl|adj
infer|推断|ɪnˈfɜː|v
inhibit|抑制；阻止|ɪnˈhɪbɪt|v
innovate|创新|ˈɪnəveɪt|v
integrate|整合；融入|ˈɪntɪɡreɪt|v
interpret|解释；口译|ɪnˈtɜːprɪt|v
intervene|干预|ˌɪntəˈviːn|v
intrinsic|内在的|ɪnˈtrɪnsɪk|adj
justify|证明合理|ˈdʒʌstɪfaɪ|v
maintain|维持；主张|meɪnˈteɪn|v
manipulate|操纵；处理|məˈnɪpjuleɪt|v
mature|成熟的|məˈtʃʊə|adj/v
modify|修改|ˈmɒdɪfaɪ|v
negotiate|谈判|nɪˈɡəʊʃieɪt|v
notion|概念；观念|ˈnəʊʃn|n
obtain|获得|əbˈteɪn|v
occur|发生|əˈkɜː|v
offset|抵消；补偿|ˈɒfset|v/n
perceive|察觉；理解|pəˈsiːv|v
persistent|坚持不懈的；持续的|pəˈsɪstənt|adj
perspective|观点；视角|pəˈspektɪv|n
phenomenon|现象|fəˈnɒmɪnən|n
preliminary|初步的|prɪˈlɪmɪnəri|adj
presume|假定|prɪˈzjuːm|v
prevail|盛行；获胜|prɪˈveɪl|v
prohibit|禁止|prəˈhɪbɪt|v
prominent|突出的；著名的|ˈprɒmɪnənt|adj
proportion|比例|prəˈpɔːʃn|n
pursue|追求；继续|pəˈsjuː|v
radical|根本的；激进的|ˈrædɪkl|adj
reinforce|加强；巩固|ˌriːɪnˈfɔːs|v
relevant|相关的|ˈreləvənt|adj
reluctant|不情愿的|rɪˈlʌktənt|adj
restrain|抑制；约束|rɪˈstreɪn|v
retain|保留|rɪˈteɪn|v
reveal|揭示|rɪˈviːl|v
revise|修订；复习|rɪˈvaɪz|v
significant|重要的；显著的|sɪɡˈnɪfɪkənt|adj
simulate|模拟|ˈsɪmjuleɪt|v
specify|明确说明|ˈspesɪfaɪ|v
subsequent|随后的|ˈsʌbsɪkwənt|adj
substitute|替代；替代品|ˈsʌbstɪtjuːt|v/n
sustain|维持；支撑|səˈsteɪn|v
tentative|暂定的；试探性的|ˈtentətɪv|adj
transform|转变|trænsˈfɔːm|v
transmit|传输；传播|trænzˈmɪt|v
undergo|经历|ˌʌndəˈɡəʊ|v
undertake|承担；着手|ˌʌndəˈteɪk|v
valid|有效的；合理的|ˈvælɪd|adj
vary|变化；不同|ˈveəri|v
verify|核实；验证|ˈverɪfaɪ|v
vital|至关重要的；有生命的|ˈvaɪtl|adj
""".strip()

FALLBACK = {}
for _line in _FALLBACK_ROWS.splitlines():
    _word, _definition, _phonetic, _pos = _line.split("|", 3)
    FALLBACK[_word] = {
        "definition": _definition,
        "phonetic": _phonetic,
        "pos": _pos,
    }


def _valid_word(word):
    return bool(re.fullmatch(r"[A-Za-z]+(?:[-'][A-Za-z]+)*", word))


def _clean_local_definition(text, max_items=6, max_length=220):
    items = []
    for raw in re.split(r"[\r\n]+", text or ""):
        value = re.sub(r"\s+", " ", raw).strip(" ;；,，")
        if not value:
            continue
        normalized = re.sub(r"^[a-z]{1,10}\.\s*", "", value, flags=re.I)
        normalized = re.sub(r"\s*[,，;；]\s*", "；", normalized)
        if (
            normalized
            and re.search(r"[\u3400-\u9fff]", normalized)
            and normalized not in items
        ):
            items.append(normalized)
        if len(items) >= max_items:
            break
    result = "；".join(items)
    if len(result) > max_length:
        result = result[:max_length].rsplit("；", 1)[0] or result[:max_length]
    return result


def _normalize_local_pos(pos, translation=""):
    found = []
    inferred = re.findall(
        r"(?:^|[\r\n])\s*(v[ti]?|n|a|adj|ad|adv|prep|conj|pron|num|art|interj)\.",
        translation or "",
        flags=re.I,
    )
    for item in inferred + re.split(r"[/,\s]+", pos or ""):
        key = item.split(":", 1)[0].strip().lower()
        aliases = {
            "a": "adj",
            "ad": "adv",
            "adjective": "adj",
            "d": "adv",
            "adverb": "adv",
            "vt": "v",
            "vi": "v",
            "verb": "v",
            "noun": "n",
        }
        key = aliases.get(key, key)
        if key in POS_ORDER and key not in found:
            found.append(key)
    return "/".join(sorted(found, key=POS_ORDER.index))


def _lemma_from_exchange(exchange):
    for item in (exchange or "").split("/"):
        if item.startswith("0:"):
            lemma = item[2:].strip().lower()
            if _valid_word(lemma):
                return lemma
    return None


def _ecdict_row(db, word):
    db.row_factory = sqlite3.Row
    return db.execute(
        """
        SELECT word, COALESCE(translation, '') AS translation,
               COALESCE(phonetic, '') AS phonetic,
               COALESCE(pos, '') AS pos,
               COALESCE(tag, '') AS tag,
               COALESCE(exchange, '') AS exchange
        FROM stardict WHERE word=? COLLATE NOCASE
        LIMIT 1
        """,
        (word,),
    ).fetchone()


def _ecdict_lookup(word):
    if not os.path.exists(DB_PATH):
        return None
    try:
        with sqlite3.connect(DB_PATH) as db:
            row = _ecdict_row(db, word)
            if row and not row["translation"]:
                lemma = _lemma_from_exchange(row["exchange"])
                if lemma and lemma != word:
                    row = _ecdict_row(db, lemma)
    except sqlite3.Error:
        return None
    if not row:
        return None
    definition = _clean_local_definition(row["translation"])
    if not definition:
        return None
    return {
        "definition": definition,
        "phonetic": row["phonetic"].strip().strip("/"),
        "pos": _normalize_local_pos(row["pos"], row["translation"]),
    }


def _request_json(url):
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        },
    )
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
        return json.load(response)


def _cache_connection():
    cache_dir = os.path.dirname(CACHE_PATH)
    if cache_dir:
        os.makedirs(cache_dir, exist_ok=True)
    db = sqlite3.connect(CACHE_PATH, timeout=5)
    db.execute("PRAGMA journal_mode = WAL")
    db.execute("PRAGMA busy_timeout = 5000")
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS dictionary_cache (
            word TEXT PRIMARY KEY COLLATE NOCASE,
            definition TEXT NOT NULL,
            phonetic TEXT NOT NULL DEFAULT '',
            pos TEXT NOT NULL DEFAULT '',
            source TEXT NOT NULL,
            cached_at INTEGER NOT NULL
        )
        """
    )
    return db


def _cache_get(word):
    try:
        with _cache_connection() as db:
            row = db.execute(
                """
                SELECT definition, phonetic, pos, source
                FROM dictionary_cache WHERE word=?
                """,
                (word,),
            ).fetchone()
    except sqlite3.Error:
        return None
    if not row:
        return None
    return {
        "definition": row[0],
        "phonetic": row[1],
        "pos": row[2],
        "_source": row[3],
    }


def _cache_set(word, result, source):
    try:
        with _cache_connection() as db:
            db.execute(
                """
                INSERT INTO dictionary_cache(
                    word, definition, phonetic, pos, source, cached_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(word) DO UPDATE SET
                    definition=excluded.definition,
                    phonetic=excluded.phonetic,
                    pos=excluded.pos,
                    source=excluded.source,
                    cached_at=excluded.cached_at
                """,
                (
                    word,
                    result["definition"],
                    result.get("phonetic", ""),
                    result.get("pos", ""),
                    source,
                    int(time.time()),
                ),
            )
    except sqlite3.Error:
        pass


def _clean_translation(text):
    text = "".join(
        char for char in text if unicodedata.category(char) != "Co"
    )
    text = re.sub(r"\s*[|｜]\s*", "；", text)
    text = re.sub(r"\s+", " ", text).strip(" ;；,，")
    return text


def _clean_merriam_definition(text):
    text = text.strip().lstrip("—- ").strip()
    text = text.split("—", 1)[0].strip()
    return text


def _translate_word(word, english_definitions, include_definitions=False):
    params = {
        "q": word,
        "langpair": "en|zh-CN",
    }
    contact = os.environ.get("MYMEMORY_EMAIL")
    if contact:
        params["de"] = contact
    data = _request_json(
        TRANSLATION_API_URL + "?" + urllib.parse.urlencode(params)
    )
    translations = []
    primary = _clean_translation(
        data.get("responseData", {}).get("translatedText", "")
    )
    if primary and primary.lower() != word:
        translations.append(primary)
    for match in data.get("matches", []):
        try:
            quality = int(match.get("quality", 0))
        except (TypeError, ValueError):
            quality = 0
        value = _clean_translation(match.get("translation", ""))
        if (
            quality >= 50
            and value
            and value.lower() != word
            and value not in translations
        ):
            translations.append(value)
        if len(translations) >= 3:
            break

    summary = " | ".join(english_definitions)[:450]
    if summary and (include_definitions or not translations):
        params["q"] = summary
        data = _request_json(
            TRANSLATION_API_URL + "?" + urllib.parse.urlencode(params)
        )
        detail = _clean_translation(
            data.get("responseData", {}).get("translatedText", "")
        )
        if detail and detail not in translations:
            translations.append(detail)
    return "；".join(translations)


def _merriam_webster_lookup(word):
    params = urllib.parse.urlencode({"key": MERRIAM_WEBSTER_API_KEY})
    url = MERRIAM_WEBSTER_API_URL.format(
        word=urllib.parse.quote(word, safe="")
    )
    entries = _request_json(url + "?" + params)
    if not isinstance(entries, list) or not entries:
        _MERRIAM_SUGGESTIONS[word] = []
        return None
    if isinstance(entries[0], str):
        _MERRIAM_SUGGESTIONS[word] = [
            item.lower()
            for item in entries
            if _valid_word(item) and item.lower() != word
        ]
        return None

    positions = []
    definitions = []
    phonetic = ""
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        stems = {
            stem.lower()
            for stem in entry.get("meta", {}).get("stems", [])
            if isinstance(stem, str)
        }
        shortdefs = [
            _clean_merriam_definition(definition)
            for definition in entry.get("shortdef", [])
            if isinstance(definition, str) and definition.strip()
        ]
        shortdefs = [definition for definition in shortdefs if definition]
        if word not in stems or not shortdefs:
            continue

        position = (entry.get("fl") or "").strip()
        if position and position not in positions:
            positions.append(position)
        if not phonetic:
            for pronunciation in entry.get("hwi", {}).get("prs", []) or []:
                value = (pronunciation.get("ipa") or "").strip().strip("/")
                if value:
                    phonetic = value
                    break
        for definition in shortdefs[:3]:
            if definition not in definitions:
                definitions.append(definition)
            if len(definitions) >= 5:
                break
        if len(definitions) >= 5 and len(positions) >= 2:
            break

    if not definitions:
        return None
    chinese = _translate_word(word, definitions, include_definitions=True)
    if not chinese:
        return None
    _MERRIAM_SUGGESTIONS.pop(word, None)
    return {
        "definition": chinese,
        "phonetic": phonetic,
        "pos": "/".join(positions[:4]),
    }


def _online_lookup(word):
    dictionary_url = DICTIONARY_API_URL.format(
        word=urllib.parse.quote(word, safe="")
    )
    entries = _request_json(dictionary_url)
    if not isinstance(entries, list) or not entries:
        return None
    entry = entries[0]

    phonetic = (entry.get("phonetic") or "").strip().strip("/")
    if not phonetic:
        for item in entry.get("phonetics", []):
            value = (item.get("text") or "").strip().strip("/")
            if value:
                phonetic = value
                break

    positions = []
    definitions = []
    for meaning in entry.get("meanings", []):
        position = (meaning.get("partOfSpeech") or "").strip()
        if position and position not in positions:
            positions.append(position)
        for definition in meaning.get("definitions", [])[:1]:
            text = (definition.get("definition") or "").strip()
            if text:
                definitions.append(text)
        if len(definitions) >= 4:
            break

    chinese = _translate_word(word, definitions)
    if not chinese:
        return None
    return {
        "definition": chinese,
        "phonetic": phonetic,
        "pos": "/".join(positions[:4]),
    }


def lookup(word):
    word = (word or "").strip().lower()
    if not _valid_word(word):
        return None

    local = _ecdict_lookup(word)
    if local:
        return local

    cached = _cache_get(word)
    if cached and (
        not (ONLINE_ENABLED and MERRIAM_WEBSTER_API_KEY)
        or cached["_source"] == "merriam-webster"
    ):
        cached.pop("_source", None)
        return cached

    if ONLINE_ENABLED and MERRIAM_WEBSTER_API_KEY:
        try:
            result = _merriam_webster_lookup(word)
        except (
            OSError,
            ValueError,
            KeyError,
            json.JSONDecodeError,
            urllib.error.HTTPError,
        ):
            result = None
        else:
            if result:
                _cache_set(word, result, "merriam-webster")
                return result
            if word in _MERRIAM_SUGGESTIONS:
                return None

    if cached:
        cached.pop("_source", None)
        return cached
    result = FALLBACK.get(word)
    if result:
        result = dict(result)
        _cache_set(word, result, "fallback")
        return result
    if ONLINE_ENABLED:
        try:
            result = _online_lookup(word)
        except (
            OSError,
            ValueError,
            KeyError,
            json.JSONDecodeError,
            urllib.error.HTTPError,
        ):
            result = None
        if result:
            _cache_set(word, result, "online")
            return result
    return None


def suggestions(word, limit=5):
    word = (word or "").strip().lower()
    candidates = set(FALLBACK)
    if os.path.exists(DB_PATH) and _valid_word(word):
        try:
            with sqlite3.connect(DB_PATH) as db:
                rows = db.execute(
                    """
                    SELECT word FROM stardict
                    WHERE word LIKE ? COLLATE NOCASE
                    ORDER BY COALESCE(frq, 999999), word
                    LIMIT 1000
                    """,
                    (word[: max(1, min(2, len(word)))] + "%",),
                ).fetchall()
            candidates.update(row[0].lower() for row in rows)
        except sqlite3.Error:
            pass
    local_matches = difflib.get_close_matches(
        word, candidates, n=limit, cutoff=0.65
    )
    merriam_matches = _MERRIAM_SUGGESTIONS.pop(word, [])
    matches = list(dict.fromkeys(local_matches + merriam_matches))
    if merriam_matches:
        return matches[:limit]
    if len(matches) >= limit:
        return matches[:limit]
    if ONLINE_ENABLED and _valid_word(word):
        try:
            query = urllib.parse.urlencode({"s": word, "max": limit * 2})
            rows = _request_json(DATAMUSE_API_URL + "?" + query)
            online_matches = [
                row["word"].lower()
                for row in rows
                if isinstance(row, dict)
                and _valid_word(row.get("word", ""))
                and row.get("word", "").lower() != word
            ]
            return list(dict.fromkeys(matches + online_matches))[:limit]
        except (
            OSError,
            ValueError,
            KeyError,
            json.JSONDecodeError,
            urllib.error.HTTPError,
        ):
            pass
    return matches


def download_ecdict(force=False):
    db_dir = os.path.dirname(DB_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)
    if os.path.exists(DB_PATH) and not force:
        return DB_PATH
    archive = os.path.join(DATA_DIR, "ecdict.zip")
    temporary = DB_PATH + ".tmp"
    try:
        if not zipfile.is_zipfile(archive):
            urllib.request.urlretrieve(ARCHIVE_URL, archive)
        with zipfile.ZipFile(archive) as zipped:
            member = next(
                name
                for name in zipped.namelist()
                if name.endswith("stardict.db")
            )
            with zipped.open(member) as source, open(temporary, "wb") as target:
                shutil.copyfileobj(source, target)
        with sqlite3.connect(temporary) as db:
            count = db.execute("SELECT COUNT(*) FROM stardict").fetchone()[0]
            if count < 100000:
                raise RuntimeError("ECDICT 数据库词条数量异常")
        os.replace(temporary, DB_PATH)
    finally:
        for path in (archive, temporary):
            if os.path.exists(path):
                os.remove(path)
    return DB_PATH


def ecdict_status():
    status = {
        "path": DB_PATH,
        "exists": os.path.exists(DB_PATH),
        "size": os.path.getsize(DB_PATH) if os.path.exists(DB_PATH) else 0,
        "entries": 0,
    }
    if status["exists"]:
        try:
            with sqlite3.connect(DB_PATH) as db:
                status["entries"] = db.execute(
                    "SELECT COUNT(*) FROM stardict"
                ).fetchone()[0]
        except sqlite3.Error:
            status["entries"] = -1
    return status

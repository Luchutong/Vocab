import difflib
import os
import re
import sqlite3
import urllib.request
import zipfile


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "ecdict.db")
ARCHIVE_URL = (
    "https://github.com/skywind3000/ECDICT/releases/download/"
    "1.0.28/ecdict-sqlite-28.zip"
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


def lookup(word):
    word = (word or "").strip().lower()
    if not _valid_word(word):
        return None
    if os.path.exists(DB_PATH):
        try:
            with sqlite3.connect(DB_PATH) as db:
                row = db.execute(
                    """
                    SELECT translation, COALESCE(phonetic, ''),
                           COALESCE(pos, '')
                    FROM stardict WHERE word=? COLLATE NOCASE
                    """,
                    (word,),
                ).fetchone()
            if row and row[0]:
                return {
                    "definition": row[0].strip(),
                    "phonetic": row[1].strip(),
                    "pos": row[2].strip(),
                }
        except sqlite3.Error:
            pass
    result = FALLBACK.get(word)
    return dict(result) if result else None


def suggestions(word, limit=5):
    word = (word or "").strip().lower()
    candidates = set(FALLBACK)
    if os.path.exists(DB_PATH) and _valid_word(word):
        try:
            with sqlite3.connect(DB_PATH) as db:
                rows = db.execute(
                    "SELECT word FROM stardict WHERE word LIKE ? LIMIT 500",
                    (word[:1] + "%",),
                ).fetchall()
            candidates.update(row[0].lower() for row in rows)
        except sqlite3.Error:
            pass
    return difflib.get_close_matches(word, candidates, n=limit, cutoff=0.65)


def download_ecdict(force=False):
    os.makedirs(DATA_DIR, exist_ok=True)
    if os.path.exists(DB_PATH) and not force:
        return DB_PATH
    archive = os.path.join(DATA_DIR, "ecdict.zip")
    urllib.request.urlretrieve(ARCHIVE_URL, archive)
    with zipfile.ZipFile(archive) as zipped:
        member = next(
            name for name in zipped.namelist() if name.endswith("stardict.db")
        )
        with zipped.open(member) as source, open(DB_PATH, "wb") as target:
            target.write(source.read())
    os.remove(archive)
    return DB_PATH

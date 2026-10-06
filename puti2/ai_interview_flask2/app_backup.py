import os
import json
import uuid
import random
import datetime
import re
import time
import urllib.error
import urllib.request

from flask import Flask, render_template, request, jsonify, url_for

app = Flask(__name__)

# Ollama runs locally and is free to use (https://ollama.com).
# Install it, run `ollama pull <model>` once, then `ollama serve` (it usually
# starts automatically after install). No API key needed.
OLLAMA_URL = os.environ.get("OLLAMA_URL")
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:7b")
MAX_FOLLOWUPS = 2  # safety cap enforced server-side too


class OllamaError(RuntimeError):
    pass


def ollama_chat(payload, timeout=180):
    url = (OLLAMA_URL or f'{OLLAMA_HOST.rstrip("/")}/api/chat').rstrip('/')
    if url.endswith('/api/chat/api/chat'):
        url = url[:-9]
    body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    ollama_request = urllib.request.Request(
        url,
        data=body,
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    try:
        with urllib.request.urlopen(ollama_request, timeout=timeout) as response:
            return json.loads(response.read().decode('utf-8'))
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as error:
        raise OllamaError(str(error)) from error

# 深掘り上限に達し、サーバー側で move_on を強制した際に使う締めの相槌。
# モデルが返した「続きの質問文」をそのまま読み上げると不自然になるための代替。
CLOSING_ACKNOWLEDGEMENTS = [
    "なるほど、よく分かりました。それでは次の質問に移りますね。",
    "ありがとうございます、詳しくお話しいただけました。次の質問に移ります。",
    "よく理解できました。それでは次に進みますね。",
]

UPLOAD_DIR = os.path.join(app.root_path, "static", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

# --- mock data: replace with a real DB / company-recommendation feature later ---
COMPANIES = [
    {
        "id": 1,
        "name": "㈱ニュー・オータニ",
        "questions": [
            "自己紹介をしてください",
            "学生時代に最も力を入れたことは何ですか",
            "当社を志望する理由を教えてください",
            "入社後にやりたい仕事は何ですか",
        ],
    },
    {
        "id": 2,
        "name": "エスアイエス・テクノサービス㈱",
        "questions": [
            "自己紹介をしてください",
            "チームで困難を乗り越えた経験はありますか",
            "当社の事業についてどう思いますか",
            "ITに興味を持ったきっかけを教えてください",
            "自分で課題を見つけて改善した経験を教えてください",
            "仕事で分からないことがあったとき、どのように解決しますか",
            "入社後に身につけたい技術や知識は何ですか",
            "お客様や社内の人と信頼関係を築くために大切なことは何ですか",
        ],
    },
    {
        "id": 3,
        "name": "TEPPANシステムインテグレーション株式会社",
        "questions": [
            "自己紹介をしてください",
            "学生時代に力を入れたことを教えてください",
            "IT業界を志望する理由を教えてください",
            "システム開発やプログラミングに興味を持ったきっかけは何ですか",
            "チームで一つの目標に向かって取り組んだ経験を教えてください",
            "困難な課題に直面したとき、どのように解決しましたか",
            "新しい知識や技術を学ぶときに工夫していることはありますか",
            "お客様の要望と技術的な制約が合わない場合、どう対応しますか",
            "当社でどのような仕事に挑戦したいですか",
            "入社後、周囲からどのような存在として頼られたいですか",
        ],
    },
    {
        "id": 4,
        "name": "共用ソリューションズ株式会社",
        "questions": [
            "自己紹介をしてください",
            "あなたの強みと、それが活かされた経験を教えてください",
            "学生時代に最も成長したと感じる経験は何ですか",
            "人と協力して課題を解決した経験を教えてください",
            "相手の要望を正確に理解するために意識していることは何ですか",
            "意見の異なる相手と協働した経験を教えてください",
            "失敗した経験と、そこから学んだことを教えてください",
            "社会や企業の課題を解決する仕事に興味を持った理由は何ですか",
            "当社のソリューションや事業にどのような印象を持っていますか",
            "入社後にお客様へどのような価値を提供したいですか",
        ],
    },
]

# In-memory log store. Swap for SQLite/Postgres etc. for real persistence.
LOGS = []


def build_rule_based_criteria(answer):
    text = (answer or '').strip()
    first_person = bool(re.search(r'(わたし|わたくし|私)', text))
    polite_endings = bool(re.search(r'(です|ます|でした|ました|ません|でしょう|ください)(?:[。！？!?]|$)', text))
    casual_endings = bool(re.search(r'(だよ|だね|じゃん|だろ|だったよ|するよ|したよ)[。！？!?]?\s*$', text))
    ng_words = ['やばい', 'まじで', 'めっちゃ', 'ウケる', 'ぶっちゃけ', 'とりま']
    honorific_words = ['おっしゃられる', 'ご覧になられる', '拝見させていただく']
    found_ng_words = [word for word in ng_words + honorific_words if word in text]
    if re.search(r'っす(?![ぁ-んァ-ヶ一-龯A-Za-z0-9])', text):
        found_ng_words.append('っす')
    if re.search(r'マジで|(?<![ぁ-んァ-ヶ一-龯A-Za-z0-9])マジ(?![ぁ-んァ-ヶ一-龯A-Za-z0-9])', text):
        found_ng_words.append('マジ')
    if re.search(r'超(?!える|過)[ぁ-んァ-ヶー]+', text):
        found_ng_words.append('超')
    filler_words = ['えっと', 'えーと', 'あのー', 'なんか', 'そのー', 'まあ', 'うーん']
    found_fillers = [word for word in filler_words if word in text]
    ending_habit = bool(re.search(r'(です|ます|だ|ね|よ)[ー〜～!！]+|[ー〜～]{2,}|[!！?？]{2,}', text))
    speech_habit = ending_habit
    speech_evidence = []
    if ending_habit:
        speech_evidence.append('語尾の強調・伸ばしとみられる表現があります。')
    if found_fillers:
        speech_evidence.append(f'（参考）フィラーを検出: {"、".join(found_fillers)}。判定には使っていません。')

    criteria = [
        {
            'id': 'first_person_ending', 'label': '一人称・文末', 'method': 'ルールベース',
            'status': 'good' if first_person and polite_endings and not casual_endings else 'needs_improvement',
            'score': 100 if first_person and polite_endings and not casual_endings else 0,
            'evidence': 'わたし/わたくし系の一人称とです・ます調を確認しました。' if first_person and polite_endings and not casual_endings else 'わたし/わたくし系の一人称、またはです・ます調の統一を確認できませんでした。',
            'feedback': '一人称は「私」「わたし」「わたくし」を使い、文末はです・ます調にそろえましょう',
        },
        {
            'id': 'inappropriate_words', 'label': '不適切な言葉', 'method': 'ルールベース（NGワード照合）',
            'status': 'good' if not found_ng_words else 'needs_improvement',
            'score': 100 if not found_ng_words else 0,
            'evidence': '不適切な登録語は見つかりませんでした。' if not found_ng_words else f'確認された語句: {"、".join(found_ng_words)}',
            'feedback': f'回答に「{"」「".join(found_ng_words)}」が含まれています。俗語・略語・つなぎ言葉は避け、正式な表現に言い換えましょう。' if found_ng_words else '面接に適した表現を維持できています。',
        },
        {
            'id': 'speech_habit', 'label': '言葉癖', 'method': 'ルールベース（語尾の強調・伸ばし。ブラウザ音声認識の精度に依存）',
            'status': 'needs_improvement' if speech_habit else 'good',
            'score': 0 if speech_habit else 100,
            'evidence': '、'.join(found_fillers) if found_fillers else ('語尾の強調・伸ばし' if ending_habit else '該当なし'),
            'feedback': 'フィラーを減らし、語尾を伸ばしたり強調したりせず、文末で一度区切って話しましょう。' if speech_habit else '落ち着いた語尾で話せています。',
        },
    ]
    if found_fillers:
        criteria.append({
            'id': 'filler_words', 'label': '話し言葉・口癖', 'method': 'ルールベース',
            'status': 'needs_improvement', 'score': 0,
            'evidence': '、'.join(found_fillers),
            'feedback': f'「{"」「".join(found_fillers)}」は話し言葉や口癖にあたるため、面接では削除してから本題を話しましょう。',
            'example': f'「{"」「".join(found_fillers)}」を削り、「〇〇について説明します」と本題から話し始めましょう。',
            'missing': [],
        })
    if any(word in text for word in ('特にない', '普通', 'なんとなく')):
        self_devaluing = next(
            word for word in ('特にない', '普通', 'なんとなく') if word in text
        )
        criteria.append({
            'id': 'self_devaluing', 'label': '自己評価を下げる表現', 'method': 'ルールベース',
            'status': 'needs_improvement', 'score': 0,
            'evidence': self_devaluing,
            'feedback': f'「{self_devaluing}」と自分の経験の価値を下げず、授業・アルバイト・ゲームなどから、続けた理由や工夫を一つ説明しましょう。',
            'example': f'「{self_devaluing}」を「〇〇を続けた理由は、〇〇です」に言い換えましょう。',
            'missing': [],
        })
    return criteria


def build_llm_fallback_criteria(followup_count):
    return [
        {
            'id': 'deep_followup', 'label': '深掘り対応', 'method': 'LLM',
            'status': 'not_applicable' if not followup_count else 'unavailable',
            'score': None,
            'evidence': 'メイン質問への回答のため、深掘り対応は未評価です。' if not followup_count else 'LLMの評価を取得できませんでした',
            'feedback': '深掘り質問には、結論を急がず具体的な経験・行動・結果を順に答えましょう。',
            'missing': [],
        },
        {
            'id': 'structure', 'label': '構成', 'method': 'LLM（3要素の有無と順序）',
            'status': 'unavailable', 'score': None,
            'evidence': 'LLMの評価を取得できませんでした',
            'feedback': '強み、具体的なエピソード、その強みの活かし方の順に話しましょう。',
            'missing': [],
        },
        {
            'id': 'specificity', 'label': '具体性', 'method': 'LLM（該当要素の引用）',
            'status': 'unavailable', 'score': None,
            'evidence': 'LLMの評価を取得できませんでした',
            'feedback': '5W1H、数字、経験から得た学びを具体的に加えましょう。',
            'missing': [],
        },
    ]


def normalize_criteria(value, fallback):
    normalized = [dict(item) for item in fallback]
    if not isinstance(value, list):
        return normalized
    by_id = {item['id']: item for item in normalized}
    llm_criteria_ids = {'deep_followup', 'structure', 'specificity'}
    for item in value:
        if not isinstance(item, dict) or item.get('id') not in llm_criteria_ids or item.get('id') not in by_id:
            continue
        target = by_id[item['id']]
        for key in ('status', 'evidence'):
            if key in item and item[key] is not None:
                target[key] = str(item[key]).strip()
    return normalized


def make_public_criteria(criteria):
    return [
        {
            key: item.get(key, []) if key == 'missing' else item[key]
            for key in ('id', 'label', 'method', 'status', 'evidence', 'feedback', 'missing')
        }
        for item in criteria
    ]


def normalize_for_match(text):
    return re.sub(r'[\s、。！？!?.,，．・「」『』（）()【】\[\]{}]', '', str(text or ''))


def evidence_exists(evidence, student_text):
    normalized_evidence = normalize_for_match(evidence)
    normalized_student_text = normalize_for_match(student_text)
    return bool(normalized_evidence) and normalized_evidence in normalized_student_text


def answer_sentences(answer):
    return [
        sentence.strip()
        for sentence in re.findall(r'[^。！？!?]+[。！？!?]?', str(answer or '').strip())
        if sentence.strip()
    ]


def build_content_criteria(main_answer, followup_pairs):
    text = str(main_answer or '').strip()
    criteria = []
    sentences = answer_sentences(text)
    activity_sentence = next(
        (
            sentence for sentence in sentences
            if any(word in sentence for word in ('授業', 'アルバイト', 'サークル', 'ゲーム', 'バイト'))
        ),
        '',
    )
    action_words = ('工夫', '担当', '役割', '作成', '改善', '対応', '発表', '調査', '練習', '取り組')
    if activity_sentence and not any(word in text for word in action_words):
        criteria.append({
            'id': 'missing_episode', 'label': '具体的なエピソード・成果', 'method': 'ルールベース',
            'status': 'needs_improvement', 'score': 0,
            'evidence': activity_sentence,
            'feedback': (
                f'「{activity_sentence}」は事実の説明にとどまっています。'
                'その場面で工夫したこと、続けた理由、周囲の反応、結果のどれかを一つ思い出して説明しましょう。'
            ),
            'example': '「〇〇の授業で、〇〇を工夫しました。その結果、〇〇になりました」の形で補いましょう。',
            'missing': [],
        })

    followup_answer = ' '.join(
        str(pair.get('answer', '')).strip()
        for pair in followup_pairs
        if isinstance(pair, dict)
    )
    empty_followup = next(
        (word for word in ('特にない', '普通', 'なんとなく') if word in followup_answer),
        '',
    )
    if empty_followup:
        criteria.append({
            'id': 'empty_followup', 'label': '深掘りへの回答', 'method': 'ルールベース',
            'status': 'needs_improvement', 'score': 0,
            'evidence': empty_followup,
            'feedback': (
                f'深掘り回答の「{empty_followup}」だけでは理由が伝わりません。'
                '「なぜそう考えたか」または「そのとき何をしたか」を一文で答えましょう。'
            ),
            'example': f'「{empty_followup}」のあとに、「そう考えた理由は〇〇です」と続けましょう。',
            'missing': [],
        })
    return criteria


def has_forbidden_advice_content(advice, student_text):
    normalized_advice = str(advice or '').translate(str.maketrans('０１２３４５６７８９', '0123456789'))
    normalized_student_text = str(student_text or '').translate(str.maketrans('０１２３４５６７８９', '0123456789'))
    normalized_advice = re.sub(r'5w1h', '', normalized_advice, flags=re.IGNORECASE)
    advice_numbers = re.findall(r'\d+(?:\.\d+)?', normalized_advice)
    student_numbers = set(re.findall(r'\d+(?:\.\d+)?', normalized_student_text))
    missing_numbers = [number for number in advice_numbers if number not in student_numbers]
    forbidden_words = ('厳しい', '通らない', '不合格', '落ち', '難しいでしょう')
    found_forbidden = [word for word in forbidden_words if word in normalized_advice]
    return missing_numbers, found_forbidden


def analyze_answer_gaps(answer):
    text = (answer or '').strip()
    signals = {
        '動機': any(word in text for word in ('理由', 'きっかけ', 'なぜ', '目指し', '興味')),
        '本人の行動': any(word in text for word in ('私が', 'わたしが', '担当', '役割', '行動', '工夫', '取り組', '対応')),
        '具体的な状況': any(word in text for word in ('いつ', 'どこ', '誰', 'チーム', '学校', 'アルバイト', '授業', 'サークル')),
        '結果': any(word in text for word in ('結果', '成果', '変化', '数字', '増え', '減っ', '達成', '評価')),
        '学び・活かし方': any(word in text for word in ('学び', '気づ', '活か', '改善', '今後', '入社後')),
    }
    return [name for name, present in signals.items() if not present]


def fallback_followup(question, history, followup_count, latest_answer_override=''):
    if followup_count >= MAX_FOLLOWUPS:
        return random.choice(CLOSING_ACKNOWLEDGEMENTS), True
    latest_answer = latest_answer_override
    if not latest_answer:
        for turn in reversed(history):
            if isinstance(turn, dict) and turn.get('role') == 'student':
                latest_answer = str(turn.get('text', ''))
                break
    gaps = analyze_answer_gaps(latest_answer)
    gap_questions = {
        '動機': 'その行動を始めようと思ったきっかけや理由を教えてください。',
        '本人の行動': 'その場面で、あなた自身が具体的にしたことを教えてください。',
        '具体的な状況': 'その経験は、いつどのような状況で起きたのか教えてください。',
        '結果': 'その行動によって、結果や周囲にどのような変化がありましたか？',
        '学び・活かし方': 'その経験から得た学びを、今後どのように活かしたいですか？',
    }
    if gaps:
        return gap_questions[gaps[followup_count % len(gaps)]], False
    patterns = [
        (('チーム', '協力', 'メンバー'), [
            'その経験で、チームの中であなたが担った役割を教えてください。',
            'メンバーと意見が合わないとき、どのように調整しましたか？',
            'チームでの経験を入社後にどう活かしたいですか？',
        ]),
        (('失敗', '苦労', '課題'), [
            'その課題に最初に気づいたきっかけを教えてください。',
            '課題を解決するために、具体的にどんな行動をしましたか？',
            'その経験から得た学びを、次の行動でどう活かしましたか？',
        ]),
        (('強み', '得意'), [
            'その強みが最も活かされた具体的な場面を教えてください。',
            'その強みを伸ばすために、普段から意識していることはありますか？',
            'その強みが仕事で活きるのは、どのような場面だと思いますか？',
        ]),
        (('結果', '成果'), [
            'その成果を出すために、特に意識して取り組んだことは何ですか？',
            '成果を数値や周囲の反応で説明すると、どのようになりますか？',
            'その成果を出した経験から、次に改善したい点はありますか？',
        ]),
    ]
    for keywords, questions in patterns:
        if any(keyword in latest_answer for keyword in keywords):
            return questions[followup_count % len(questions)], False
    generic_questions = [
        'その経験に取り組もうと思ったきっかけを教えてください。',
        'その中で一番難しかったことと、乗り越え方を教えてください。',
        'あなた自身が担った役割と、具体的な行動を教えてください。',
        '周囲からはどのような反応や評価がありましたか？',
        'その経験から得た学びを、今後どのように活かしたいですか？',
    ]
    if '工夫した点' in question:
        return 'その工夫によって、結果や周囲にどのような変化がありましたか？', False
    return generic_questions[followup_count % len(generic_questions)], False


def followup_misses_answer(reply, answer):
    answer = answer or ''
    signals = []
    if any(word in answer for word in ('チーム', 'メンバー', '協力', '分担')):
        signals.append(('チーム', '役割', '分担', 'メンバー', '協力'))
    if any(word in answer for word in ('結果', '成果', '増え', '減っ', '数字', '来場者')):
        signals.append(('結果', '成果', '変化', '数字', '来場者', '増え', '減っ'))
    if any(word in answer for word in ('課題', '困難', '失敗')):
        signals.append(('課題', '困難', '失敗', '問題', '乗り越'))
    if any(word in answer for word in ('チーム', 'メンバー')) and any(word in answer for word in ('役割', '担当', '進行')):
        signals.append(('役割', '担当', '進行', '分担', 'メンバー'))
    generic_phrases = ('リソースを活用', '就活活動', '学生の回答に結びつける', '発言内容')
    return (bool(signals) and not any(any(word in reply for word in group) for group in signals)) or any(phrase in reply for phrase in generic_phrases)


def repeats_previous_question(reply, history):
    normalized_reply = ''.join(reply.split()).replace('？', '').replace('?', '')
    if len(normalized_reply) < 8:
        return True
    for turn in history:
        if not isinstance(turn, dict) or turn.get('role') != 'interviewer':
            continue
        previous = ''.join(str(turn.get('text', '')).split()).replace('？', '').replace('?', '')
        if previous and (normalized_reply == previous or normalized_reply in previous or previous in normalized_reply):
            return True
    return False


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/companies")
def api_companies():
    return jsonify(COMPANIES)


@app.route("/api/logs", methods=["GET"])
def api_logs_list():
    return jsonify(sorted(LOGS, key=lambda l: l["created_at"], reverse=True))


@app.route("/api/interview/reply", methods=["POST"])
def api_interview_reply():
    """Given the student's latest spoken answer, return the interviewer's
    next line: either a short acknowledgement + one deep-dive question, or
    a short acknowledgement only (move_on=True) once enough depth is reached.
    """
    data = request.get_json(force=True) or {}
    question = (data.get("question") or "").strip()
    company = (data.get("company") or "").strip()
    history = data.get("history") or []  # [{role: 'student'|'interviewer', text: str}, ...]
    followup_count = int(data.get("followup_count", 0))

    if '自己紹介' in question:
        return jsonify({
            "reply": "ありがとうございます。よろしくお願いします。それでは、次の質問に移りますね。",
            "move_on": True,
        })

    convo_text = "\n".join(
        f"{'学生' if t.get('role') == 'student' else '面接官'}: {t.get('text', '')}"
        for t in history
    )
    latest_answer = next((str(t.get('text', '')).strip() for t in reversed(history) if t.get('role') == 'student'), '')
    answer_gaps = analyze_answer_gaps(latest_answer)

    system_prompt = (
        "あなたは新卒採用の面接官です。就活生と一対一の面接をしています。\n"
        f"企業名: {company}\n"
        f"今回のメインの質問: {question}\n"
        f"学生の直前の回答: {latest_answer or '回答なし'}\n"
        "回答を、主張・理由・本人の行動・工夫・結果・学びの観点で確認してください。"
        f"回答から不足している可能性がある観点: {', '.join(answer_gaps) if answer_gaps else '大きな不足なし'}。"
        "不足している観点を1つだけ優先し、回答に出てきた固有の経験や行動に結び付けて深掘りしてください。"
        "回答が自己紹介であっても、実際に話された経験・役割・強みだけを根拠にしてください。"
        "直前の質問や、すでに回答された内容をそのまま聞き直してはいけません。"
        "回答にない活動や人物を勝手に追加してはいけません。『リソース』『就活活動』『発言内容』のような抽象的な言い換えは禁止です。"
        "質問には回答中の名詞を少なくとも1つ使い、実際の面接で自然な『具体的に教えてください』『どう対応しましたか』の形にしてください。"
        "深掘り質問を1文だけ、90文字以内で返してください。相槌、説明、番号、回答の要約は付けないでください。\n"
        f"これまでこの質問での深掘り回数: {followup_count}回。"
        f"深掘り回数が{MAX_FOLLOWUPS}回に達している場合や、回答がすでに十分具体的な場合は、"
        "深掘りせず、短い前向きな相槌（1文）だけを返し、move_onをtrueにしてください。\n"
        "出力は必ず次のJSON形式のみで返してください。説明文やコードブロックは付けないこと:\n"
        '{"reply": "発言内容", "move_on": true または false}'
    )

    reply, move_on = "ありがとうございます。次の質問に移ります。", True
    try:
        res = ollama_chat({
                "model": OLLAMA_MODEL,
                "format": "json",
                "stream": False,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"これまでの会話:\n{convo_text}\n\n不足している観点を最優先に選び、JSONのみで返してください。"},
                ],
            }, timeout=30)
        raw = str(res["message"]["content"]).strip().strip("`").strip()
        if raw.lower().startswith("json"):
            raw = raw[4:].strip()
        parsed = json.loads(raw)
        app.logger.debug("interview reply parsed from model: %r", parsed)
        reply = str(parsed.get("reply", reply)).strip() or reply

        # モデルが move_on を JSON の真偽値ではなく文字列 "true"/"false" で
        # 返すことがある。bool("false") は True になってしまうため、
        # 文字列の場合は中身を見て判定する。
        move_on_raw = parsed.get("move_on", True)
        if isinstance(move_on_raw, str):
            model_move_on = move_on_raw.strip().lower() == "true"
        else:
            model_move_on = bool(move_on_raw)

        cap_reached = followup_count >= MAX_FOLLOWUPS
        has_question = '?' in reply or '？' in reply
        if not cap_reached and (model_move_on or not has_question or followup_misses_answer(reply, latest_answer) or repeats_previous_question(reply, history)):
            reply, move_on = fallback_followup(question, history, followup_count, latest_answer)
        else:
            move_on = cap_reached

        # 上限到達によりサーバー側で move_on を強制した場合、モデル自身は
        # まだ深掘りを続けるつもりで「質問文」を reply に入れていることがある
        # （小型モデルは上限の指示を必ずしも守らない）。そのまま読み上げると
        # 「質問を投げかけた直後に唐突に面接が終わる」という不自然な体験に
        # なるため、この場合は reply を短い締めの相槌に差し替える。
        if cap_reached and not model_move_on:
            reply = random.choice(CLOSING_ACKNOWLEDGEMENTS)

        app.logger.debug(
            "interview reply final decision: move_on=%r (model_move_on=%r, "
            "followup_count=%d, MAX_FOLLOWUPS=%d)",
            move_on, model_move_on, followup_count, MAX_FOLLOWUPS,
        )
    except (OllamaError, ValueError, KeyError, TypeError) as e:
        app.logger.warning(
            "interview reply generation failed (is `ollama serve` running and "
            "`%s` pulled?): %s | raw model output: %r",
            OLLAMA_MODEL, e, locals().get("raw"),
        )
        reply, move_on = fallback_followup(question, history, followup_count, latest_answer)

    return jsonify({"reply": reply, "move_on": move_on})


LLM_ADVICE_SCHEMA = (
    {
        'type': 'object',
        'required': ['items', 'followUp', 'good'],
        'properties': {
            'items': {
                'type': 'array',
                'maxItems': 3,
                'items': {
                    'type': 'object',
                    'required': ['title', 'quote', 'advice', 'example'],
                    'properties': {
                        'title': {'type': 'string', 'description': '改善点の見出し'},
                        'quote': {
                            'type': 'string',
                            'description': '回答本文から一字一句そのままの短い引用',
                        },
                        'advice': {
                            'type': 'string',
                            'description': '引用箇所をどう直すかの30文字以上の具体的な助言',
                        },
                        'example': {
                            'type': 'string',
                            'description': '回答に実在する材料だけで書き直した例文。架空の数字や固有名詞は禁止',
                        },
                    },
                },
            },
            'followUp': {
                'type': 'string',
                'description': '深掘りがある場合の評価。深掘りがなければ空文字',
            },
            'good': {'type': 'string', 'description': '良かった点。なければ空文字'},
        },
    }
)


def extract_quoted_text(text):
    return re.findall(r'「([^」]+)」', str(text or ''))


def fabricated_example_tokens(example, source_text):
    source = normalize_for_match(source_text)
    fabricated = []
    for token in re.findall(r'[0-9０-９]+|[二三四五六七八九十百千万億]+(?=[年月日時間人回倍割分秒%％件個])', example):
        if token not in source:
            fabricated.append(token)
    for token in re.findall(r'[A-ZＡ-Ｚ][A-Za-zＡ-Ｚａ-ｚ0-９０-９+#.-]{1,}', example):
        if normalize_for_match(token) not in source:
            fabricated.append(token)
    for token in re.findall(
        r'[ぁ-んァ-ヶ一-龥]{2,20}(?:大学|学校|会社|企業|株式会社|高校|専門学校)',
        example,
    ):
        if normalize_for_match(token) not in source:
            fabricated.append(token)
    return fabricated


def followup_is_empty(answer):
    normalized = normalize_for_match(answer)
    return not normalized or any(
        phrase in normalized
        for phrase in ('特にないです', '特にありません', 'なんとなく', '普通にやっていました')
    )


def normalize_llm_advice(value):
    if not isinstance(value, dict):
        return None, 'missing_items'
    raw_items = value.get('items')
    if not isinstance(raw_items, list):
        return None, 'missing_items'
    items = []
    for index, item in enumerate(raw_items[:3], start=1):
        if not isinstance(item, dict):
            app.logger.warning(
                'interview advice item discarded reason=missing_item_fields item=%d quote=%r',
                index, '',
            )
            continue
        missing = [
            field for field in ('title', 'quote', 'advice', 'example')
            if not isinstance(item.get(field), str) or not item.get(field).strip()
        ]
        if missing:
            app.logger.warning(
                'interview advice item discarded reason=missing_item_fields item=%d fields=%s quote=%r',
                index, ','.join(missing), '',
            )
            continue
        items.append({
            'title': item['title'].strip(),
            'quote': item['quote'].strip(),
            'advice': item['advice'].strip(),
            'example': item['example'].strip(),
        })
    follow_up = value.get('followUp')
    good = value.get('good')
    if not isinstance(follow_up, str) or not isinstance(good, str):
        return None, 'missing_item_fields'
    return {'items': items, 'followUp': follow_up.strip(), 'good': good.strip()}, None


def generate_llm_advice(question, main_answer, followup_pairs):
    question_type = '深掘り質問への回答' if followup_pairs else 'メイン質問への回答'
    followup_text = [
        {
            'question': str(pair.get('question', '')).strip(),
            'answer': str(pair.get('answer', '')).strip(),
        }
        for pair in followup_pairs
        if isinstance(pair, dict)
    ]
    source_text = '\n'.join(
        [main_answer] + [
            f"{pair['question']}\n{pair['answer']}" for pair in followup_text
        ]
    ).strip()
    has_empty_followup = any(
        followup_is_empty(pair['answer']) for pair in followup_text
    )
    prompt = f"""あなたは新卒の面接練習をサポートするコーチです。
以下の回答を読み、次の面接で点が上がるアドバイスを作ってください。

- 改善効果が大きい点を最大3つ選び、観点は固定しない。
- 話し言葉や口癖、一人称と文末、内容の具体性、自己評価の弱さ、
  根拠のない断言、質問への回答、構成などから自由に選ぶ。
- 質問の種類に合った助言にし、自己紹介に成果や数字を足す型を機械的に使わない。
- quoteは回答本文から一字一句そのままの、20文字程度の短い引用にする。引用の語尾や助詞を変えない。「っす」を「です」に直した形を引用にしない。
- adviceはquoteについて、やさしい言葉で30文字以上の1〜2文の具体的な直し方にする。引用だけを書かない。
- 材料が足りないときは、何を入れればよいかを短く添える。〇〇だけの空の穴埋めにしない。
- 回答にない資格、経験、強み、計画性などを前提にしない。
- exampleは回答に実在する材料だけで書き直す。回答にない数字、固有名詞、経験、年数、人数、成果を入れない。
- 深掘り回答がある場合は、followUpに必ずその評価を1つ入れる。
- 深掘りがない場合は、followUpを空文字にする。「なし」などの文字は入れない。
- 深掘り回答が「特にないです」「特にありません」「なんとなく」のように内容がない場合は、followUpに「理由が答えられていません。例えば、始めたきっかけや、そのときに考えたことを思い出して答えましょう」のような助言を書く。
- 内容が乏しい場合は、どんな経験を思い出すとよいかを先に示す。
- 良い点があればgoodに1つ書き、なければ空文字にする。
- 学生が読みやすい、厳しすぎない表現にする。
- 例文に括弧書きの補足を入れない。
- 引用の「」内は、下記の回答に実際に存在する文字列だけにする。

質問: {question}
質問の種類: {question_type}
回答全文: {main_answer}
深掘り質問と回答: {json.dumps(followup_text, ensure_ascii=False)}

JSONのみで返してください。形式は次のとおりです。
{json.dumps(LLM_ADVICE_SCHEMA, ensure_ascii=False)}"""

    last_error = None
    for attempt in range(2):
        try:
            response = ollama_chat({
                    'model': OLLAMA_MODEL,
                    'format': LLM_ADVICE_SCHEMA,
                    'stream': False,
                    'messages': [
                        {'role': 'system', 'content': prompt},
                        {'role': 'user', 'content': '回答を読み、JSONのみで返してください。'},
                    ],
                    'options': {'temperature': 0.25, 'num_predict': 700},
                    'keep_alive': '10m',
                }, timeout=180)
            raw = str(response['message']['content']).strip().strip('`').strip()
            if os.environ.get('DEBUG_LOG_LLM_OUTPUT') == '1':
                app.logger.info('interview advice LLM raw_output=%s', raw)
            if raw.lower().startswith('json'):
                raw = raw[4:].strip()
            try:
                decoded = json.loads(raw)
            except json.JSONDecodeError as error:
                last_error = 'json_parse_error'
                app.logger.warning(
                    'interview advice validation failed reason=json_parse_error detail=%s',
                    error,
                )
                continue
            parsed, normalization_error = normalize_llm_advice(decoded)
            if normalization_error:
                last_error = normalization_error
                app.logger.warning(
                    'interview advice validation failed reason=%s',
                    normalization_error,
                )
                continue

            valid_items = []
            for index, item in enumerate(parsed['items'], start=1):
                quote = item['quote']
                if len(item['advice']) < 30:
                    app.logger.warning(
                        'interview advice item discarded reason=short_advice item=%d quote=%r',
                        index, quote,
                    )
                    continue
                if len(item['example']) < 10 or normalize_for_match(item['example']) == normalize_for_match(quote):
                    app.logger.warning(
                        'interview advice item discarded reason=short_or_same_example item=%d quote=%r',
                        index, quote,
                    )
                    continue
                if not evidence_exists(quote, source_text):
                    app.logger.warning(
                        'interview advice item discarded reason=quote_not_found item=%d quote=%r',
                        index, quote,
                    )
                    continue
                fabricated = fabricated_example_tokens(item['example'], source_text)
                if fabricated:
                    app.logger.warning(
                        'interview advice item discarded reason=fabricated_example item=%d quote=%r tokens=%s',
                        index, quote, ','.join(fabricated),
                    )
                    continue
                valid_items.append(item)

                if not valid_items and not parsed['good']:
                     last_error = 'no_valid_items'
                app.logger.warning(
                    'interview advice validation failed reason=no_valid_items detail=all_items_rejected',
                )
                continue
            if followup_text and not parsed['followUp']:
                last_error = 'missing_follow_up'
                app.logger.warning(
                    'interview advice validation failed reason=missing_follow_up',
                )
                continue
            if has_empty_followup and parsed['followUp'] in {'なし', '特になし', '特にありません'}:
                last_error = 'missing_follow_up'
                app.logger.warning(
                    'interview advice validation failed reason=missing_follow_up detail=empty_followup_needs_reason_advice',
                )
                continue
            return {
                'items': valid_items,
                'followUp': parsed['followUp'],
                'good': parsed['good'],
            }, 'llm', attempt + 1
        except (OllamaError, KeyError, TypeError) as error:
            last_error = str(error)
            app.logger.warning(
                'interview advice generation failed reason=ollama_error detail=%s',
                error,
            )
        app.logger.warning('LLM advice generation attempt %d failed: %s', attempt + 1, last_error)

    raise OllamaError('AIによるアドバイスを取得できませんでした')


@app.route("/api/interview-advice", methods=["POST"])
def api_interview_advice():
    data = request.get_json(force=True) or {}
    question = str(data.get('question', '')).strip()
    dialogue = data.get('dialogue') or []
    students = [item for item in dialogue if isinstance(item, dict) and item.get('role') == 'student']
    student_text = '\n'.join(str(item.get('text', '')).strip() for item in students).strip()
    main_answer = str(students[0].get('text', '')).strip() if students else ''
    followup_count = max(0, len(students) - 1)
    followup_pairs = []
    for index in range(1, len(dialogue) - 1, 2):
        interviewer = dialogue[index]
        student = dialogue[index + 1]
        if (isinstance(interviewer, dict) and interviewer.get('role') == 'interviewer'
                and isinstance(student, dict) and student.get('role') == 'student'):
            followup_pairs.append({
                'question': str(interviewer.get('text', '')).strip(),
                'answer': str(student.get('text', '')).strip(),
            })

    llm_advice = {'items': [], 'followUp': '', 'good': ''}
    source = 'rule_only'
    attempts = 0
    try:
        llm_advice, source, attempts = generate_llm_advice(
            question,
            main_answer,
            followup_pairs,
        )
    except OllamaError:
        app.logger.error('interview advice failed after two attempts')

    rule_items = []
    fillers = [w for w in ('あのー', 'えっと', 'えーと', 'なんか', 'そのー', 'うーん', 'ぶっちゃけ', 'マジで', 'マジ')
               if w in main_answer]
    if re.search(r'っす(?![ぁ-んァ-ヶ一-龯A-Za-z0-9])', main_answer):
        fillers.append('っす')
    if fillers:
        shown = '」「'.join(dict.fromkeys(fillers))
        rule_items.append({
            'title': '話し言葉・口癖',
            'quote': fillers[0],
            'advice': f'「{shown}」は話し言葉や口癖なので、面接では使わず、本題から落ち着いて話し始めましょう。文末は「です・ます」にそろえます。',
            'example': '「私は〜です。」のように、一人称と丁寧な文末で始めましょう。',
        })
    devalue = next((w for w in ('特にない', '普通', 'なんとなく') if w in student_text), '')
    if devalue:
        rule_items.append({
            'title': '自己評価を下げる表現',
            'quote': devalue,
            'advice': f'「{devalue}」と言うと、経験の価値が下がって見えます。続けた理由や工夫を一つ、短く説明しましょう。',
            'example': f'「{devalue}」の代わりに、「続けた理由は〜です」と答えましょう。',
        })

    merged = (rule_items + llm_advice['items'])[:4]
    if not merged and not llm_advice['good']:
        return jsonify({
            'source': 'error',
            'error': 'AIによるアドバイスを取得できませんでした',
        }), 503
    return jsonify({
        **llm_advice,
        'items': merged,
        'source': source,
        'attempts': attempts,
    })
    
@app.route("/api/logs", methods=["POST"])
def api_logs_create():
    company = request.form.get("company", "")
    question = request.form.get("question", "")
    file = request.files.get("video")
    if not file:
        return jsonify({"error": "video file is required"}), 400

    filename = f"{uuid.uuid4().hex}.webm"
    file.save(os.path.join(UPLOAD_DIR, filename))

    log = {
        "id": uuid.uuid4().hex,
        "company": company,
        "question": question,
        "video_url": url_for("static", filename=f"uploads/{filename}"),
        "created_at": datetime.datetime.now().isoformat(timespec="seconds"),
    }
    LOGS.append(log)
    return jsonify(log), 201


if __name__ == "__main__":
    app.run(debug=True)
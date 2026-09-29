import os
import json
import uuid
import random
import datetime

import requests
from flask import Flask, render_template, request, jsonify, url_for

app = Flask(__name__)

# Ollama runs locally and is free to use (https://ollama.com).
# Install it, run `ollama pull <model>` once, then `ollama serve` (it usually
# starts automatically after install). No API key needed.
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:3b")
MAX_FOLLOWUPS = 2  # safety cap enforced server-side too

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


def build_interview_advice(answer, question=''):
    text = (answer or '').strip()
    strengths = []
    improvements = []
    tips = []
    has_action = any(word in text for word in ['行動', '工夫', '役割', '対応', '取り組'])
    has_result = any(word in text for word in ['結果', '成果', '変化', '数字', '増え', '減っ'])
    has_learning = any(word in text for word in ['学び', '気づ', '活か', '改善'])
    has_reason = any(word in text for word in ['理由', 'きっかけ', 'なぜ', 'ため'])

    if len(text) >= 60:
        strengths.append('回答に十分な情報があり、経験を伝えようとしています。')
    else:
        improvements.append('具体的なエピソードをもう少し加えると、内容が伝わりやすくなります。')
    if has_action:
        strengths.append('あなた自身の行動が含まれていて、主体性が伝わります。')
    else:
        improvements.append('「自分が何をしたか」を一つ具体的に説明しましょう。')
    if has_result:
        strengths.append('結果や学びまで話せていて、経験の価値が伝わります。')
    else:
        improvements.append('行動のあとに、相手や状況がどう変わったかを添えましょう。')
    if not has_learning:
        improvements.append('最後に、その経験から得た学びや次に活かすことを加えましょう。')
    if any(word in question for word in ['志望', '応募']):
        tips.append('企業のどの点に惹かれたのかと、自分の経験がどう活きるかを結び付けましょう。')
    elif any(word in question for word in ['自己紹介', '自己PR', '強み']):
        tips.append('最初に結論を一言で伝え、そのあとに強みの具体例を続けましょう。')
    elif has_reason:
        tips.append('きっかけだけでなく、その判断の基準や考え方も一言加えましょう。')
    else:
        tips.append('結論・行動・結果・学びのうち、まだ薄い部分を一つ補って話しましょう。')
    tips.append('要点ごとに少し間を置くと、内容がより伝わりやすくなります。')
    summary = '回答の軸は伝わっています。'
    if not has_action:
        summary = '経験の概要は伝わっています。あなた自身の行動を中心にすると、説得力が増します。'
    elif not has_result:
        summary = '行動は伝わっています。行動によって起きた結果や変化まで話すと、回答が完成します。'
    elif not has_learning:
        summary = '経験と結果は伝わっています。最後に学びや入社後への活かし方を加えると印象に残ります。'
    return {
        'summary': summary,
        'strengths': strengths[:3],
        'improvements': improvements[:3],
        'tips': tips[:2],
    }


def normalize_advice_items(value):
    if isinstance(value, list):
        items = value
    elif isinstance(value, dict):
        items = [value]
    elif isinstance(value, str):
        items = [value]
    else:
        items = []
    normalized = []
    for item in items:
        if isinstance(item, dict):
            item = item.get('value') or item.get('text') or item.get('content') or ''
        text = str(item).strip()
        if text and not text.startswith('{') and not text.startswith('['):
            normalized.append(text.lstrip('-* ').strip())
    return normalized[:3]


def normalize_advice_payload(value, fallback):
    if not isinstance(value, dict):
        return fallback
    summary = value.get('summary') or value.get('総評') or fallback['summary']
    return {
        'summary': str(summary).strip(),
        'strengths': normalize_advice_items(value.get('strengths') or value.get('良い点') or fallback['strengths']),
        'improvements': normalize_advice_items(value.get('improvements') or value.get('改善点') or fallback['improvements']),
        'tips': normalize_advice_items(value.get('tips') or value.get('次の一手') or fallback['tips']),
    }


def fallback_followup(question, history, followup_count, latest_answer_override=''):
    if followup_count >= MAX_FOLLOWUPS:
        return random.choice(CLOSING_ACKNOWLEDGEMENTS), True
    latest_answer = latest_answer_override
    if not latest_answer:
        for turn in reversed(history):
            if isinstance(turn, dict) and turn.get('role') == 'student':
                latest_answer = str(turn.get('text', ''))
                break
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

    system_prompt = (
        "あなたは新卒採用の面接官です。就活生と一対一の面接をしています。\n"
        f"企業名: {company}\n"
        f"今回のメインの質問: {question}\n"
        f"学生の直前の回答: {latest_answer or '回答なし'}\n"
        "回答を、主張・理由・本人の行動・工夫・結果・学びの観点で確認してください。"
        "まだ説明されていない観点を1つだけ選び、回答に出てきた固有の経験や行動に結び付けて深掘りしてください。"
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
        res = requests.post(
            f"{OLLAMA_HOST}/api/chat",
            json={
                "model": OLLAMA_MODEL,
                "format": "json",
                "stream": False,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"これまでの会話:\n{convo_text}\n\n不足している観点を最優先に選び、JSONのみで返してください。"},
                ],
            },
            timeout=30,
        )
        res.raise_for_status()
        raw = res.json()["message"]["content"].strip().strip("`").strip()
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
    except Exception as e:
        app.logger.warning(
            "interview reply generation failed (is `ollama serve` running and "
            "`%s` pulled?): %s | raw model output: %r",
            OLLAMA_MODEL, e, locals().get("raw"),
        )
        reply, move_on = fallback_followup(question, history, followup_count, latest_answer)

    return jsonify({"reply": reply, "move_on": move_on})


@app.route("/api/interview-advice", methods=["POST"])
def api_interview_advice():
    data = request.get_json(force=True) or {}
    answer = str(data.get('answer', '')).strip()
    question = str(data.get('question', '')).strip()
    fallback = build_interview_advice(answer, question)
    prompt = (
        'あなたは就職面接の専門コーチです。候補者の1回答を分析してください。'
        '質問に答えられている点と不足している点を、回答に出てきた経験・役割・行動・結果に触れて具体的に指摘してください。'
        '同じ定型文を避け、回答内容だけを根拠にしてください。'
        'summaryは80字以内、各配列は最大3個とし、JSONの4キーだけを返してください。\n'
        f'質問: {question or "不明"}\n'
        f'回答: {answer or "回答なし"}\n'
        '形式: {"summary":"総評", "strengths":["良い点"], "improvements":["改善点"], "tips":["次の一手"]}'
    )
    try:
        res = requests.post(
            f"{OLLAMA_HOST}/api/chat",
            json={
                'model': OLLAMA_MODEL,
                'format': 'json',
                'stream': False,
                'messages': [
                    {'role': 'system', 'content': prompt},
                    {'role': 'user', 'content': '回答に登場する具体的な言葉を使って、JSONのみで分析してください。'},
                ],
                'options': {'temperature': 0.45},
            },
            timeout=30,
        )
        res.raise_for_status()
        raw = str(res.json()['message']['content']).strip().strip('`').strip()
        if raw.lower().startswith('json'):
            raw = raw[4:].strip()
        parsed = json.loads(raw)
        if isinstance(parsed, dict) and parsed.get('summary'):
            return jsonify(normalize_advice_payload(parsed, fallback))
    except (OSError, ValueError, KeyError, TypeError, requests.RequestException) as error:
        app.logger.warning('interview advice generation failed: %s', error)
    return jsonify(fallback)


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
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
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:7b")
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
            "自己PRをお願いします",
            "チームで困難を乗り越えた経験はありますか",
            "当社の事業についてどう思いますか",
        ],
    },
]

# In-memory log store. Swap for SQLite/Postgres etc. for real persistence.
LOGS = []


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

    convo_text = "\n".join(
        f"{'学生' if t.get('role') == 'student' else '面接官'}: {t.get('text', '')}"
        for t in history
    )

    system_prompt = (
        "あなたは新卒採用の面接官です。就活生と一対一の面接をしています。\n"
        f"企業名: {company}\n"
        f"今回のメインの質問: {question}\n"
        "学生の直前の回答を読み、面接官として自然な短い相槌を1文入れたうえで、"
        "回答の中で具体性が足りない点や気になる点を1つだけ選んで深掘りする質問を1文、続けてください。"
        "話し言葉で、合計60文字程度に収めてください。\n"
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
                    {"role": "user", "content": f"これまでの会話:\n{convo_text}\n\n上記を踏まえて、次の発言をJSONのみで返してください。"},
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
        move_on = model_move_on or cap_reached

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
        move_on = True  # fail safe: always keep the interview moving forward

    return jsonify({"reply": reply, "move_on": move_on})


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
import os
import json
import uuid
import random
import datetime
import re
import time
import unicodedata
import urllib.error
import urllib.request
 
from flask import Flask, render_template, request, jsonify, url_for
 
app = Flask(__name__)
 
# Ollama runs locally and is free to use (https://ollama.com).
# Install it, run `ollama pull <model>` once, then `ollama serve` (it usually
# starts automatically after install). No API key needed.
OLLAMA_URL = os.environ.get("OLLAMA_URL")
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
 
# 深掘り質問（/api/interview/reply）用のモデル。timeout=30 のため軽いモデル（3B）を想定。
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:3b")
 
# 助言（/api/interview-advice）用のモデル。指定がなければ OLLAMA_MODEL と同じ。
# 7B を試すときは、環境変数 ADVICE_MODEL だけを変える。
ADVICE_MODEL = os.environ.get("ADVICE_MODEL") or OLLAMA_MODEL
ADVICE_TIMEOUT = int(os.environ.get("ADVICE_TIMEOUT", "240"))
ADVICE_ATTEMPTS = max(1, int(os.environ.get("ADVICE_ATTEMPTS", "2")))
MAX_FIX_ITEMS = 2  # 直す点の最大数
 
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
 
 
# =====================================================================
# 共通の文字列ヘルパー
# =====================================================================
 
def normalize_for_match(text):
    return re.sub(r'[\s、。！？!?.,，．・「」『』（）()【】\[\]{}]', '', str(text or ''))
 
 
def evidence_exists(evidence, student_text):
    normalized_evidence = normalize_for_match(evidence)
    normalized_student_text = normalize_for_match(student_text)
    return bool(normalized_evidence) and normalized_evidence in normalized_student_text
 
 
def extract_quoted_text(text):
    return re.findall(r'「([^」]+)」', str(text or ''))
 
 
# =====================================================================
# 深掘り質問まわり（変更なし）
# =====================================================================
 
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
 
 
# =====================================================================
# 助言まわり
#   1) 回答に中身があるかどうかを、コードで判定する（モデルには任せない）
#   2) 中身がほとんどない → 「話す材料を探す質問」をコードで作る（モデルは使わない）
#   3) 中身がある → モデルに「良かった点1つ＋直す点最大2つ」を作らせ、機械チェックする
#   4) 話し方（一人称・文末・口癖・俗語）は、どちらの場合もコードで別欄に出す
#   5) モデルが失敗したら、定型の助言に戻す（エラーにしない）
# =====================================================================
 
EMPTY_PHRASES = (
    '特にない', '特にありません', 'なんとなく', '普通です', '普通っす', '普通でした',
    '普通にやって', '普通にやり', '思いつきません', '思い浮かびません', 'わかりません', '分かりません',
)
ACTION_WORDS = (
    '工夫', '担当', '役割', '作成', '改善', '対応', '発表', '調査', '練習', '取り組',
    '開発', '提案', '解決', '続け', '確認', '準備', '計画',
)
ACTIVITY_WORDS = ('授業', 'アルバイト', 'バイト', 'サークル', 'ゲーム', '部活', '勉強', '資格', '制作', '開発')
 
FORBIDDEN_PATTERN = re.compile(r'厳しい|通らない|不合格|落ち(?!着)|落とされ|難しいでしょう|合格でき')
BLANK_PATTERN = re.compile(r'[〇○◯△□]|…|〜|～')
STRAY_ENGLISH_PATTERN = re.compile(r'[A-Za-z]{5,}')
 
REVIEW_FOOTNOTE = '例文は書き方の見本です。実際にあったことに置き換えて使ってください。'
EMPTY_FOLLOWUP_ADVICE = '深掘りの答えに理由がありません。始めたきっかけや、そのときに考えたことを一言で答えましょう。'
 
 
 
def detect_question_kind(question):
    q = str(question or '')
    if '自己紹介' in q:
        return 'intro'
    if any(word in q for word in ('入社後', '挑戦', 'やりたい', '身につけたい')):
        return 'future'
    if any(word in q for word in ('志望', '理由', 'きっかけ', '興味', '印象', 'どう思います')):
        return 'motivation'
    return 'experience'
 
 
def is_thin_answer(main_answer, followup_pairs):
    """回答に話す材料がほとんどないかどうかを、コードで判定する。"""
    main = str(main_answer or '')
    followup_answers = ' '.join(str(pair.get('answer', '')) for pair in followup_pairs)
    all_text = main + ' ' + followup_answers
    has_empty = any(phrase in all_text for phrase in EMPTY_PHRASES)
    has_action = any(word in main for word in ACTION_WORDS)
    if len(normalize_for_match(main)) < 25:
        return True
    if has_empty and not has_action:
        return True
    return False
 
 
# ---------- 話し方のチェック（コード判定・別欄） ----------
 
FILLER_PATTERN = re.compile(r'えっと|えーと|えー|あのー|あの、|そのー|なんか|うーん|まあ')
SLANG_WORDS = ('やばい', 'めっちゃ', 'ウケる', 'ぶっちゃけ', 'とりま', 'まじで', 'おっしゃられる', '拝見させていただく')
POLITE_END = re.compile(r'(です|ます|でした|ました|ません|ください|でしょう|ございます|おります|ですね|ですか|ますか)$')
PLAIN_END = re.compile(r'(思う|考える|感じる|思った|考えた|した|やった|だった|できた|できる|ある|ない|いる|だ|する|なった|えた)$')
 
 
def build_speech_notes(text):
    text = str(text or '')
    notes = []
 
    # 一人称
    casual_first = []
    if '僕' in text:
        casual_first.append('僕')
    if '俺' in text:
        casual_first.append('俺')
    if re.search(r'自分(?:は|が|も|、|,)', text):
        casual_first.append('自分')
    formal_first = bool(re.search(r'私|わたし|わたくし', text))
    if casual_first:
        shown = '」「'.join(casual_first)
        if formal_first:
            notes.append(f'一人称が「{shown}」と「私」で混在しています。「私」に統一しましょう。')
        else:
            notes.append(f'一人称が「{shown}」になっています。面接では「私」を使いましょう。')
 
    # 文末
    sentences = [s.strip() for s in re.split(r'[。！？!?\n]', text) if s.strip()]
    polite = 0
    plain = 0
    for sentence in sentences:
        if POLITE_END.search(sentence):
            polite += 1
        elif PLAIN_END.search(sentence):
            plain += 1
    if polite and plain:
        notes.append('文末が「です・ます」と「〜だ・〜る」で混在しています。「です・ます」にそろえましょう。')
    elif plain and not polite:
        notes.append('文末が「だ・である」調になっています。面接では「です・ます」調で話しましょう。')
 
    # 俗語
    slang = [word for word in SLANG_WORDS if word in text]
    if re.search(r'っす(?![ぁ-んァ-ヶ一-龯A-Za-z0-9])', text):
        slang.append('っす')
    if re.search(r'マジで|(?<![ぁ-んァ-ヶ一-龯A-Za-z0-9])マジ(?![ぁ-んァ-ヶ一-龯A-Za-z0-9])', text):
        slang.append('マジ')
    if re.search(r'超(?!える|過)[ぁ-んァ-ヶー]+', text):
        slang.append('超')
    slang = list(dict.fromkeys(slang))
    if slang:
        notes.append(f'「{"」「".join(slang)}」は話し言葉・俗語です。面接では正式な表現に言い換えましょう。')
 
    # 口癖（フィラー）
    fillers = [word.rstrip('、') for word in FILLER_PATTERN.findall(text)]
    fillers = list(dict.fromkeys(fillers))
    if fillers:
        notes.append(f'「{"」「".join(fillers)}」は口癖（つなぎ言葉）です。一呼吸おいてから、本題を話しましょう。')
 
    # 語尾の伸ばし・強調
    if re.search(r'(です|ます|だ|ね|よ)[ー〜～!！]+|[〜～]{2,}|[!！?？]{2,}', text):
        notes.append('語尾を伸ばしたり強調したりせず、文末で一度区切って話しましょう。')
 
    return notes
 
 
# ---------- 中身がほとんどない回答：話す材料を探す質問（コードだけで作る） ----------
 
MATERIAL_BANKS = {
    'experience': [
        '授業やバイトなどで、苦手でも最後まで続けたことはありますか。',
        '1か月以上続けていることはありますか。ゲームや趣味でも構いません。',
        '友達や先生から「これお願い」と頼まれたことはありますか。',
        '以前より「できるようになった」と思うことはありますか。',
    ],
    'motivation': [
        '説明会やホームページを見て、「ここがいい」と思った点はありますか。',
        'その会社の仕事の中で、興味を持った仕事や、気になった取り組みはありますか。',
        '先輩社員や説明会で、印象に残った言葉や場面はありますか。',
        'ほかの会社と比べて、この会社を選ぶ理由になりそうなことはありますか。',
    ],
    'intro': [
        '今、学校でどんなことを学んでいますか。',
        '授業や自分で作ったもので、人に見せられるものはありますか。',
        '友達や先生から、どんなことが得意だと言われますか。',
    ],
    'future': [
        '授業やこれまでの経験で、「面白い」と感じた作業はありますか。',
        'ITの仕事の中で、気になっている仕事はありますか。開発・テスト・サポートなどから選んでも構いません。',
        '数年後に、どんなことができるようになっていたいですか。',
    ],
}
 
ACTIVITY_QUESTIONS = (
    ('授業', '授業の中で、苦手でも最後までやったことや、工夫したことはありますか。'),
    ('アルバイト', 'アルバイトで、任された仕事や、工夫したことはありますか。'),
    ('バイト', 'アルバイトで、任された仕事や、工夫したことはありますか。'),
    ('ゲーム', 'ゲームで、長く続けていることや、仲間と協力したことはありますか。'),
    ('サークル', 'サークルで、自分から動いたことや、任された役割はありますか。'),
    ('部活', '部活で、自分から動いたことや、任された役割はありますか。'),
)
 
MATERIAL_NEXT_STEPS = {
    'experience': '思い出せたものを1つ選んで、「何をしたか」と「なぜそうしたか」を一言ずつ書いてみましょう。大きな成果がなくても大丈夫です。',
    'motivation': '気になった点を1つ選んで、「何を見たか」と「なぜそう思ったか」を一言ずつ書いてみましょう。',
    'intro': '1つだけ選んで、「何を学んでいるか」と「どんなことができるか」を一言ずつ書いてみましょう。',
    'future': '気になったものを1つ選んで、「どんなことをしてみたいか」と「なぜか」を一言ずつ書いてみましょう。',
}
 
 
def pick_activity_quote(text):
    """回答の中から、実際にやってきたことを表す短い部分を、そのまま取り出す。"""
    clauses = [c.strip() for c in re.split(r'[、。！？!?\n]', str(text or '')) if c.strip()]
    candidates = [c for c in clauses if any(w in c for w in ACTIVITY_WORDS) and 6 <= len(c) <= 40]
    if not candidates:
        return ''
 
    def trim(clause):
        trimmed = re.sub(r'(ですかね|ですよね|ですね|です|っす|かな|かも)$', '', clause).strip()
        return trimmed if len(trimmed) >= 4 else clause
 
    for clause in candidates:
        if trim(clause).endswith('こと'):
            return trim(clause)
    return trim(candidates[0])
 
 
def build_material_questions(kind, answer_text):
    questions = []
    if kind == 'experience':
        for keyword, text in ACTIVITY_QUESTIONS:
            if keyword in answer_text and text not in questions and len(questions) < 2:
                questions.append(text)
    bank = list(MATERIAL_BANKS.get(kind, MATERIAL_BANKS['experience']))
    if kind == 'experience' and questions:
        bank = bank[1:]  # 先頭の「授業やバイトなどで…」は、回答に合わせた質問と似るため外す
    for text in bank:
        if len(questions) >= 3:
            break
        if text not in questions:
            questions.append(text)
    return questions[:3]
 
 
def build_material_advice(kind, student_text):
    quote = pick_activity_quote(student_text) if kind in ('experience', 'intro') else ''
    if quote:
        intro = f'「{quote}」は、実際にやってきたことなので、話の出発点になります。話す材料が、まだ見つかっていないだけかもしれません。'
    else:
        intro = '話す材料が、まだ見つかっていないだけかもしれません。次の質問で、一緒に探してみましょう。'
    return {
        'intro': intro,
        'questions': build_material_questions(kind, student_text),
        'next': MATERIAL_NEXT_STEPS.get(kind, MATERIAL_NEXT_STEPS['experience']),
    }
 
 
# ---------- 中身がある回答：モデルに作らせて、機械チェックする ----------
 
LLM_ADVICE_SCHEMA = {
    'type': 'object',
    'required': ['good', 'items', 'followUp'],
    'properties': {
        'good': {'type': 'string', 'description': '良かった点を1つ。学生の発言を「」で引用し、理由を1文。なければ空文字'},
        'items': {
            'type': 'array',
            'maxItems': 3,
            'items': {
                'type': 'object',
                'required': ['title', 'quote', 'advice', 'example'],
                'properties': {
                    'title': {'type': 'string', 'description': '直す点の見出し（15文字以内）'},
                    'quote': {'type': 'string', 'description': '回答本文から一字一句そのままの短い引用'},
                    'advice': {'type': 'string', 'description': '何を書けばよいかを説明する、15文字以上の1文'},
                    'example': {'type': 'string', 'description': '回答にある材料だけで書いた、書き方の見本1文'},
                },
            },
        },
        'followUp': {'type': 'string', 'description': '深掘り回答の評価1文。深掘りがなければ空文字'},
    },
}
 
 
def fabricated_example_tokens(example, source_text):
    source = normalize_for_match(unicodedata.normalize('NFKC', str(source_text or '')))
    cleaned = unicodedata.normalize('NFKC', str(example or ''))
    cleaned = cleaned.replace('一人ひとり', '')
    cleaned = re.sub(r'[0-9一二三四五六七八九十]+(?=つ|文|点|行)', '', cleaned)
    fabricated = []
    for token in re.findall(
        r'[0-9]+|[一二三四五六七八九十百千万億]+(?=人|年|か月|ヶ月|カ月|回|件|割|倍|円|名|個|日|時間|週間|%)',
        cleaned,
    ):
        if token not in source:
            fabricated.append(token)
    for token in re.findall(r'[A-Z][A-Za-z0-9+#.-]{1,}', cleaned):
        if normalize_for_match(token) not in source:
            fabricated.append(token)
    for token in re.findall(
        r'[ァ-ヶー一-龥A-Za-z]{2,15}(?:大学|高校|専門学校|株式会社)',
        cleaned,
    ):
        if normalize_for_match(token) not in source:
            fabricated.append(token)
    return fabricated
 
 
def has_forbidden_advice_content(advice, student_text):
    normalized_advice = unicodedata.normalize('NFKC', str(advice or ''))
    normalized_student_text = unicodedata.normalize('NFKC', str(student_text or ''))
    normalized_advice = re.sub(r'5w1h', '', normalized_advice, flags=re.IGNORECASE)
    normalized_advice = re.sub(r'\d+(?=つ|文|点|行|か所|箇所)', '', normalized_advice)
    advice_numbers = re.findall(r'\d+(?:\.\d+)?', normalized_advice)
    student_numbers = set(re.findall(r'\d+(?:\.\d+)?', normalized_student_text))
    missing_numbers = [number for number in advice_numbers if number not in student_numbers]
    found_forbidden = FORBIDDEN_PATTERN.findall(normalized_advice)
    return missing_numbers, found_forbidden
 
 
def stray_english_words(text, source_text):
    source_lower = str(source_text or '').lower()
    return [word for word in STRAY_ENGLISH_PATTERN.findall(str(text or '')) if word.lower() not in source_lower]
 
 
def followup_is_empty(answer):
    normalized = normalize_for_match(answer)
    return not normalized or any(
        phrase in normalized
        for phrase in ('特にないです', '特にありません', 'なんとなく', '普通にやっていました')
    )
 
 
def check_advice_item(item, source_text):
    """問題があれば理由（文字列）を返す。問題がなければ空文字を返す。"""
    quote = item['quote']
    if len(item['advice']) < 15:
        return 'short_advice'
    if len(item['example']) < 10 or normalize_for_match(item['example']) == normalize_for_match(quote):
        return 'short_or_same_example'
    if not evidence_exists(quote, source_text):
        return 'quote_not_found'
    if BLANK_PATTERN.search(item['advice'] + item['example']):
        return 'blank_placeholder'
    all_text = ' '.join([item['title'], item['advice'], item['example']])
    english = stray_english_words(all_text, source_text)
    if english:
        return 'stray_english:' + ','.join(english)
    fabricated = fabricated_example_tokens(item['example'], source_text)
    if fabricated:
        return 'fabricated_example:' + ','.join(fabricated)
    missing_numbers, forbidden = has_forbidden_advice_content(all_text, source_text)
    if missing_numbers:
        return 'number_not_in_answer:' + ','.join(missing_numbers)
    if forbidden:
        return 'forbidden_word:' + ','.join(forbidden)
    return ''
 
 
def clean_good(good, source_text):
    """良かった点に、実在する引用が含まれていなければ、その部分だけ空にする。"""
    good = str(good or '').strip()
    if not good:
        return ''
    quotes = extract_quoted_text(good)
    if not quotes or not all(evidence_exists(q, source_text) for q in quotes):
        return ''
    if stray_english_words(good, source_text) or FORBIDDEN_PATTERN.search(good) or BLANK_PATTERN.search(good):
        return ''
    return good
 
 
def normalize_llm_advice(value):
    if not isinstance(value, dict):
        return None, 'missing_items'
    raw_items = value.get('items')
    if not isinstance(raw_items, list):
        return None, 'missing_items'
    items = []
    for index, item in enumerate(raw_items[:4], start=1):
        if not isinstance(item, dict):
            app.logger.warning('interview advice item discarded reason=not_object item=%d', index)
            continue
        missing = [
            field for field in ('title', 'quote', 'advice', 'example')
            if not isinstance(item.get(field), str) or not item.get(field).strip()
        ]
        if missing:
            app.logger.warning(
                'interview advice item discarded reason=missing_item_fields item=%d fields=%s',
                index, ','.join(missing),
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
    # 引用が実在するかの確認には、学生の発言だけを使う（面接官の発言は含めない）
    source_text = '\n'.join([main_answer] + [pair['answer'] for pair in followup_text]).strip()
    has_empty_followup = any(followup_is_empty(pair['answer']) for pair in followup_text)
 
    prompt = f"""あなたは新卒の面接練習をサポートするコーチです。学生の回答を読んで、助言をJSONで作ります。
 
【作り方】
- good: 回答の良かった点を1つ。学生の発言を「」で一字一句そのまま引用し、そのあとに、なぜ良いかを1文で書く。良い点がなければ空文字にする。
- items: 直す点を最大2つ。改善効果が大きいものを選ぶ。各項目は次の4つで書く。
  - title: 直す点の見出し（15文字以内）
  - quote: 直したい箇所を、回答から一字一句そのまま引用した20文字程度の文字列
  - advice: 何を書けばよいかを、やさしい言葉で1文（15文字以上）
  - example: 書き方の見本を1文。回答にある材料だけで書く
- followUp: 深掘り回答がある場合だけ、その評価を1文で書く。ない場合は空文字にする。
 
【守ること】
- 回答にない数字、資格、経験、会社名、成果を足さない。数字は使わない。
- 〇〇や△△のような空欄や、「〜」は使わない。
- 「」は学生の発言を引用するときだけ使う。
- 合格や不合格を断定しない。学生が読みやすい、厳しすぎない表現にする。
- 話し方（一人称・文末・口癖・俗語）は別に判定するので、触れない。
- 日本語だけで書く。英単語は使わない。
- 回答にすでに書いてある内容（数字・結果・学び・役割など）を、足りない点として挙げない。quoteに選んだ部分と同じことを足すよう助言しない。
- 質問の種類に合った助言にする。自己紹介に成果や数字を足すような、型どおりの助言をしない。
- 深掘り回答が「特にないです」のように内容がない場合は、followUpに「理由が答えられていません。始めたきっかけや、そのときに考えたことを一言で答えましょう」という趣旨を書く。
 
質問: {question}
質問の種類: {question_type}
回答全文: {main_answer}
深掘り質問と回答: {json.dumps(followup_text, ensure_ascii=False)}
 
JSONのみで返してください。"""
 
    last_error = None
    for attempt in range(ADVICE_ATTEMPTS):
        attempt_started = time.perf_counter()
        try:
            response = ollama_chat({
                'model': ADVICE_MODEL,
                'format': LLM_ADVICE_SCHEMA,
                'stream': False,
                'messages': [
                    {'role': 'system', 'content': prompt},
                    {'role': 'user', 'content': '回答を読み、JSONのみで返してください。'},
                ],
                'options': {'temperature': 0.25, 'num_predict': 600},
                'keep_alive': '10m',
            }, timeout=ADVICE_TIMEOUT)
            app.logger.info(
                'interview advice model=%s attempt=%d seconds=%.1f',
                ADVICE_MODEL, attempt + 1, time.perf_counter() - attempt_started,
            )
            raw = str(response['message']['content']).strip().strip('`').strip()
            if os.environ.get('DEBUG_LOG_LLM_OUTPUT') == '1':
                app.logger.info('interview advice LLM raw_output=%s', raw)
            if raw.lower().startswith('json'):
                raw = raw[4:].strip()
            try:
                decoded = json.loads(raw)
            except json.JSONDecodeError as error:
                last_error = 'json_parse_error'
                app.logger.warning('interview advice validation failed reason=json_parse_error detail=%s', error)
                continue
            parsed, normalization_error = normalize_llm_advice(decoded)
            if normalization_error:
                last_error = normalization_error
                app.logger.warning('interview advice validation failed reason=%s', normalization_error)
                continue
 
            valid_items = []
            for index, item in enumerate(parsed['items'], start=1):
                problem = check_advice_item(item, source_text)
                if problem:
                    app.logger.warning(
                        'interview advice item discarded reason=%s item=%d quote=%r',
                        problem, index, item['quote'],
                    )
                    continue
                valid_items.append(item)
                if len(valid_items) >= MAX_FIX_ITEMS:
                    break
 
            if not valid_items:
                last_error = 'no_valid_items'
                app.logger.warning('interview advice validation failed reason=no_valid_items')
                continue
            
            follow_up = parsed['followUp'] if followup_text else ''

            if follow_up in {'なし', '特になし', '特にありません'}:

                follow_up = ''

            if followup_text and has_empty_followup:

                follow_up = EMPTY_FOLLOWUP_ADVICE
 
            if follow_up and (stray_english_words(follow_up, source_text) or FORBIDDEN_PATTERN.search(follow_up)):
                last_error = 'bad_follow_up'
                app.logger.warning('interview advice validation failed reason=bad_follow_up')
                continue
            return {
                'good': clean_good(parsed['good'], source_text),
                'items': valid_items,
                'followUp': follow_up,
            }, 'llm', attempt + 1
        except (OllamaError, KeyError, TypeError) as error:
            last_error = str(error)
            app.logger.warning('interview advice generation failed reason=ollama_error detail=%s', error)
        app.logger.warning('LLM advice generation attempt %d failed: %s', attempt + 1, last_error)
 
    raise OllamaError('AIによるアドバイスを取得できませんでした')
 
 
def build_fallback_review(main_answer, has_followup):
    """モデルが失敗したときの、定型の助言。"""
    clauses = [c.strip() for c in re.split(r'[、。！？!?\n]', str(main_answer or '')) if c.strip()]
    quote = next((c for c in clauses if 6 <= len(c) <= 30), '')
    items = []
    if quote:
        items.append({
            'title': '実際にあった場面を足す',
            'quote': quote,
            'advice': '回答の中から、実際にあった場面を1つ選んで、「何をしたか」と「なぜそうしたか」を一言ずつ足しましょう。',
            'example': '',
        })
    follow_up = ''
    if has_followup:
        follow_up = '深掘りには、結論だけでなく、そのとき自分が何をしたかを一言で答えましょう。'
    return {'good': '', 'items': items, 'followUp': follow_up}
 
 
# =====================================================================
# ルート
# =====================================================================
 
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
 
 
@app.route("/api/interview-advice", methods=["POST"])
def api_interview_advice():
    started = time.perf_counter()
    data = request.get_json(force=True) or {}
    question = str(data.get('question', '')).strip()
    dialogue = data.get('dialogue') or []
 
    # 最初の学生の発言をメイン回答、それ以降の学生の発言を深掘りへの回答として扱う。
    main_answer = ''
    student_texts = []
    followup_pairs = []
    last_interviewer = ''
    for item in dialogue:
        if not isinstance(item, dict):
            continue
        text = str(item.get('text', '')).strip()
        if item.get('role') == 'interviewer':
            last_interviewer = text
        elif item.get('role') == 'student':
            student_texts.append(text)
            if len(student_texts) == 1:
                main_answer = text
            else:
                followup_pairs.append({'question': last_interviewer, 'answer': text})
    student_text = '\n'.join(student_texts).strip()
 
    speech = build_speech_notes(student_text)
    kind = detect_question_kind(question)
 
    # --- 中身がほとんどない回答：コードだけで「話す材料を探す質問」を作る ---
    if is_thin_answer(main_answer, followup_pairs):
        materials = build_material_advice(kind, student_text)
        return jsonify({
            'mode': 'material',
            'source': 'rule',
            'attempts': 0,
            'seconds': round(time.perf_counter() - started, 1),
            'good': materials['intro'],  # 古い画面でも表示できるように、導入文を good にも入れる
            'items': [],
            'followUp': '',
            'materials': materials,
            'speech': speech,
            'footnote': '',
            'notice': '',
        })
 
    # --- 中身がある回答：モデルに助言を作らせる。失敗したら定型の助言に戻す ---
    notice = ''
    try:
        advice, source, attempts = generate_llm_advice(question, main_answer, followup_pairs)
    except OllamaError:
        app.logger.error('interview advice failed after %d attempts; using fallback advice', ADVICE_ATTEMPTS)
        advice = build_fallback_review(main_answer, bool(followup_pairs))
        source = 'fallback'
        attempts = ADVICE_ATTEMPTS
        notice = 'AIの助言を作れなかったため、定型の助言を表示しています。もう一度試すと、助言が出ることがあります。'
 
    has_example = any(item.get('example') for item in advice['items'])
    return jsonify({
        'mode': 'review',
        'source': source,
        'attempts': attempts,
        'seconds': round(time.perf_counter() - started, 1),
        'good': advice['good'],
        'items': advice['items'],
        'followUp': advice['followUp'],
        'materials': None,
        'speech': speech,
        'footnote': REVIEW_FOOTNOTE if has_example else '',
        'notice': notice,
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
 
 
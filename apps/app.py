import json
import os
import urllib.request

from flask import Flask, jsonify, render_template, request


def build_heuristic_advice(answer: str, question: str = '', expression_score: int = 0, company: str = '', mode: str = '') -> dict:
    text = (answer or '').strip()
    detail_words = ['経験', '課題', '工夫', '役割', '結果', '学び', '改善', '具体', '強み', '理由', '行動', '対応']
    has_action = any(word in text for word in ['行動', '工夫', '対応', '役割', '具体的'])
    has_result = any(word in text for word in ['結果', '成果', '学び', '改善', '数字'])
    expression_score = max(0, min(100, int(expression_score or 0)))

    strengths = []
    improvements = []
    tips = []

    if len(text) >= 60:
        strengths.append('回答の量があり、意図を説明しようとしている印象です。')
    else:
        improvements.append('もう少し具体例を入れると、面接官に伝わりやすくなります。')

    if has_action:
        strengths.append('どんな行動を取ったかが伝わっていて、説得力があります。')
    else:
        improvements.append('「何をしたか」を1つ具体的に加えると、回答が強くなります。')

    if has_result:
        strengths.append('結果や学びまで言及できていて、成長が伝わります。')
    else:
        improvements.append('最後に結果や学びを添えると、回答の完成度が上がります。')

    if expression_score < 55:
        improvements.append('表情が少し硬めに見えます。最初の30秒は少し笑顔を作ると安心感が増えます。')
    elif expression_score >= 70:
        strengths.append('表情が安定していて、落ち着いて話せている印象です。')
    else:
        strengths.append('表情は概ね安定しており、自然な話し方が見えます。')

    summary = '話の軸は良く、次は具体的な行動と結果を一緒に伝えるとさらに良くなります。'
    if not text:
        summary = '回答がまだ短いため、最初にエピソードを一つ決めて、行動・結果・学びを順に話すと伝わりやすくなります。'

    if '質問' in question or '自己紹介' in question:
        tips.append('結論を最初に一言で伝え、そのあとに具体例を続けると聞き手が理解しやすくなります。')
    else:
        tips.append('「なぜその経験をしたのか」「どう変化したのか」を加えると、面接官の印象が強くなります。')

    tips.append('話すスピードを落として、1つのテーマごとに息を入れると自然で伝わりやすくなります。')

    return {
        'summary': summary,
        'strengths': strengths[:3],
        'improvements': improvements[:3],
        'tips': tips[:2],
    }


def build_summary(answer: str, expression_score: int = 0, company: str = '', mode: str = '') -> dict:
    text = (answer or '').strip()
    score = max(0, min(100, int(expression_score or 0)))
    answer_score = 0
    if text:
        detail_words = ['経験', '課題', '工夫', '役割', '結果', '学び', '改善', '具体', '強み', '理由', '行動']
        detail_count = sum(1 for word in detail_words if word in text)
        sentence_count = len([char for char in text if char in '。！？!?'])
        answer_score = min(100, int(len(text) * 0.32 + detail_count * 7 + sentence_count * 5))
    total_score = max(0, min(100, int(answer_score * 0.7 + score * 0.3)))
    if total_score >= 80:
        verdict = 'かなり良いです。自分の強みが伝わる形になっています。'
    elif total_score >= 60:
        verdict = '良い基礎があります。もう一歩だけ、具体例を増やすと完成度が上がります。'
    else:
        verdict = 'ここからは軸を絞って、行動・結果・学びを一つずつ丁寧に伝えると強くなります。'
    return {
        'total_score': total_score,
        'answer_score': min(100, answer_score),
        'expression_score': score,
        'verdict': verdict,
        'company': company or '企業',
        'mode': mode or '面接',
    }


def fallback_question(answer: str, question_number: int = 0, previous_question: str = '') -> str:
    patterns = [
        (('チーム', '協力', 'メンバー'), [
            'その経験で、チームの中であなたが担った役割を教えてください。',
            'メンバーと意見が合わないとき、どのように調整しましたか？',
            'チームでの経験を入社後にどう活かしたいですか？'
        ]),
        (('失敗', '苦労', '課題'), [
            'その課題に最初に気づいたきっかけを教えてください。',
            '課題を解決するために、具体的にどんな行動をしましたか？',
            'その経験から得た学びを、次の行動でどう活かしましたか？'
        ]),
        (('強み', '得意'), [
            'その強みが最も活かされた具体的な場面を教えてください。',
            'その強みを伸ばすために、普段から意識していることはありますか？',
            'その強みが仕事で活きるのは、どのような場面だと思いますか？'
        ]),
        (('結果', '成果'), [
            'その成果を出すために、特に意識して取り組んだことは何ですか？',
            '成果を数値や周囲の反応で説明すると、どのようになりますか？',
            'その成果を出した経験から、次に改善したい点はありますか？'
        ]),
    ]
    for keywords, questions in patterns:
        if any(keyword in answer for keyword in keywords):
            return questions[question_number % len(questions)]
    generic_questions = [
        'その経験に取り組もうと思ったきっかけを教えてください。',
        'その中で一番難しかったことと、乗り越え方を教えてください。',
        'あなた自身が担った役割と、具体的な行動を教えてください。',
        '周囲からはどのような反応や評価がありましたか？',
        'その経験から得た学びを、今後どのように活かしたいですか？'
    ]
    if '工夫した点' in previous_question:
        return 'その工夫によって、結果や周囲にどのような変化がありましたか？'
    return generic_questions[question_number % len(generic_questions)]


def create_app(config_name: str = "local"):
    app = Flask(__name__, template_folder="../templates", static_folder="../static")

    @app.route("/")
    def interview_practice():
        return render_template("index.html")
import re
import os
import json
from datetime import datetime
from uuid import uuid4
from urllib.request import Request as UrlRequest, urlopen

from flask import Flask, jsonify, render_template, request

QUESTION_GUIDANCE = {
    "志望動機": "なぜその企業・業界・職種なのかを明確にし、自分の経験や価値観と結び付ける。",
    "自己PR": "自分の強み・能力・人柄を、具体的な行動と成果で裏付ける。",
    "ガクチカ": "学生時代の経験について、目標・役割・工夫・成果・学びを順番に示す。",
    "長所・短所": "自分の特徴を具体例で示し、長所の活かし方と短所の改善行動まで書く。",
    "趣味・特技": "趣味や特技そのものだけでなく、継続力や人柄が伝わる経験を添える。",
    "資格・スキル": "資格名やスキル名に加えて、使えるレベルと実際に活用した場面を示す。",
    "学業で力を入れたこと": "授業・研究・ゼミのテーマ、取り組み方、成果、仕事への活かし方を示す。",
    "自己紹介": "自分がどんな人物かを最初に一言で示し、根拠となる経験を簡潔に添える。",
    "就活の軸": "企業選び・仕事選びで大切にしている価値観と、その軸を持った理由を示す。",
    "希望職種": "希望する職種を明確にし、必要な能力や自分の経験との接点を示す。",
    "入社後にしたいこと": "入社後に挑戦したい仕事と、そこで実現したいことを具体的に示す。",
    "将来のキャリア": "3年後・5年後などの目標と、そこへ向けて身につけたい経験や能力を示す。",
    "企業で実現したいこと": "その会社でなければならない理由と、実現したい価値を事業と結び付ける。",
    "チーム経験": "チームの目標、自分の役割、周囲との連携、成果を具体的に示す。",
    "失敗・挫折経験": "困難の状況、原因、取った行動、乗り越え方、そこから得た学びを示す。",
    "課題・改善経験": "課題の発見方法、原因分析、改善策、実施結果を順番に示す。",
    "趣味・興味": "何に興味を持つかだけでなく、始めた理由や続け方から人柄を伝える。",
    "アルバイト経験": "仕事内容だけでなく、自分なりの工夫、成果、仕事で活かせる学びを示す。",
    "部活・サークル経験": "活動内容、役割、工夫したこと、成果、周囲への貢献を示す。",
    "インターン経験": "担当した仕事、学んだこと、社員から得た気づき、志望への変化を示す。",
    "最近気になるニュース": "ニュースの概要・関心を持った理由・自分の考えを分けて示す。",
    "あなたを一言で表すと": "最初に端的な言葉で答え、その言葉を裏付ける具体的な経験を添える。",
    "周囲からどんな人と言われるか": "周囲からの評価をそのまま書くだけでなく、そう言われた具体的な場面を示す。",
    "これまでで一番頑張ったこと": "目標の大きさではなく、継続した行動・工夫・成果・成長を具体的に示す。",
    "挫折したときの乗り越え方": "挫折の原因をどう捉え、誰に相談し、何を変え、何を学んだかを示す。",
    "入社後に身につけたいスキル": "身につけたいスキル、その理由、現在の取り組み、仕事での活用方法を示す。",
}


def evaluate_interview_criteria(essay):
    sentences = [sentence.strip() for sentence in re.split(r"[。！？\n]+", essay) if sentence.strip()]
    polite_sentences = sum(bool(re.search(r"(?:です|ます|ました|ません|でしょう|ください)$", sentence)) for sentence in sentences)
    first_person = bool(re.search(r"(?:私|わたし|わたくし)", essay))
    slang = re.findall(r"(めっちゃ|マジ|ヤバい|すごく|超|〜|ー{2,})", essay)
    over_polite = re.findall(r"(させていただきます|させていただきました|お伺いさせていただ)", essay)
    has_strength = bool(re.search(r"(強み|得意|長所|能力|責任感|協調性|継続力)", essay))
    has_episode = bool(re.search(r"(経験|取り組み|活動|アルバイト|部活|研究|行動|挑戦)", essay))
    has_use = bool(re.search(r"(活か|貢献|入社後|仕事で|役立て)", essay))
    has_wh = bool(re.search(r"(いつ|どこ|誰|何を|なぜ|どのように|期間|人数|件|回|年|月|日|%|\d)", essay))
    has_learning = bool(re.search(r"(学び|学ん|成長|気づき|身につ|改善)", essay))

    return [
        {
            "title": "一人称・文末",
            "ok": first_person and polite_sentences == len(sentences),
            "good": "「私・わたし・わたくし」を使い、です・ます調で統一されています。",
            "advice": "一人称は「私」に統一し、文末を「です・ます」にそろえてください。例えば「頑張った」を「頑張りました」に直します。",
        },
        {
            "title": "不適切な言葉",
            "ok": not slang and not over_polite,
            "good": "俗語や、重なった敬語表現は見当たりません。",
            "advice": f"{('「' + '」「'.join(slang + over_polite) + '」を確認し、') if slang or over_polite else ''}面接では自然な「です・ます」調を使い、「お伺いさせていただく」は「伺う」のように簡潔にしてください。",
        },
        {
            "title": "言葉癖",
            "ok": not re.search(r"(ですです|ますます|ですよね+$|ー{2,}|〜{2,})", essay),
            "good": "語尾の過剰な強調や伸ばしは見当たりません。",
            "advice": "語尾を伸ばしたり強調したりせず、文を言い切ってください。「〜ですー」ではなく「〜です。」のように整えます。",
        },
        {
            "title": "深掘り対応",
            "ok": len(sentences) >= 3 and has_wh and has_learning,
            "good": "複数の文で状況・行動・学びまで具体的に説明できています。",
            "advice": "深掘りされたときに答えられるよう、「なぜ始めたか」「自分は何をしたか」「結果は何か」「何を学んだか」を順番に1文ずつ補足してください。",
        },
        {
            "title": "構成",
            "ok": has_strength and has_episode and has_use,
            "good": "強み、エピソード、仕事での活かし方が含まれています。",
            "advice": "「私の強みは〇〇です」→具体的なエピソード→「入社後は〇〇に活かします」の3段構成に並べ替えてください。",
        },
        {
            "title": "具体性",
            "ok": has_wh and has_learning,
            "good": "状況を具体化する情報と、経験から得た学びが含まれています。",
            "advice": "5W1Hのうち不足している情報を補い、人数・期間・件数などの数字を1つ以上入れてください。最後に「この経験から〇〇を学びました」と学びを明示します。",
        },
    ]
def correct_essay_text(essay):
    common_corrections = {
        "思いましす": "思います",
        "思いましｔ": "思います",
        "行いましった": "行いました",
        "取り組みましたた": "取り組みました",
        "出来きる": "できる",
        "分かりずらい": "分かりづらい",
        "しずらい": "しづらい",
        "あらかしめ": "あらかじめ",
        "コミニュケーション": "コミュニケーション",
        "行なう": "行う",
        "行なえる": "行える",
        "現われる": "現れる",
        "表わす": "表す",
        "問合わせ": "問い合わせ",
    }
    corrected = essay
    changes = []
    for typo, replacement in common_corrections.items():
        if typo in corrected:
            corrected = corrected.replace(typo, replacement)
            changes.append(f"「{typo}」→「{replacement}」")

    corrected_sentences = []
    seen_sentences = set()
    duplicate_count = 0
    parts = re.split(r"(\n|[。！？])", corrected)
    skip_punctuation = False
    for part in parts:
        if skip_punctuation and part in "。！？":
            skip_punctuation = False
            continue
        skip_punctuation = False
        if not part or part == "\n" or part in "。！？":
            corrected_sentences.append(part)
            continue
        normalized = re.sub(r"\s+", "", part)
        if normalized and normalized in seen_sentences:
            duplicate_count += 1
            skip_punctuation = True
            continue
        if normalized:
            seen_sentences.add(normalized)
        corrected_sentences.append(part)
    corrected = "".join(corrected_sentences)
    if duplicate_count:
        changes.append(f"同じ文章を{duplicate_count}件削除")

    sentences = re.split(r"([。！？])", corrected)
    polite_changes = 0
    plain_to_polite = [
        (r"である$", "です"), (r"だった$", "でした"), (r"ではない$", "ではありません"),
        (r"できる$", "できます"), (r"できた$", "できました"), (r"する$", "します"),
        (r"した$", "しました"), (r"なる$", "なります"), (r"なった$", "なりました"),
        (r"ない$", "ありません"), (r"ある$", "あります"), (r"あった$", "ありました"),
        (r"思う$", "思います"), (r"考える$", "考えます"), (r"目指す$", "目指します"),
        (r"取り組む$", "取り組みます"), (r"学ぶ$", "学びます"), (r"続ける$", "続けます"),
    ]
    for index in range(0, len(sentences) - 1, 2):
        sentence, punctuation = sentences[index], sentences[index + 1]
        if re.search(r"(?:です|ます|ました|ません|でしょう|ください)$", sentence):
            sentences[index] = sentence
            continue
        for pattern, replacement in plain_to_polite:
            updated = re.sub(pattern, replacement, sentence)
            if updated != sentence:
                sentence = updated
                polite_changes += 1
                break
        sentences[index] = sentence
    corrected = "".join(sentences)
    if polite_changes:
        changes.append(f"文末を「です・ます」調に{polite_changes}件統一")
    return corrected, changes


def create_app(config_name: str = "local"):
    app = Flask(__name__)
    app.config["TEMPLATES_AUTO_RELOAD"] = True
    app.jinja_env.auto_reload = True
    def review_with_ai(essay, target_char_count):
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            return None

        prompt = f"""あなたは日本語の就職応募書類を添削する専門家です。
文字数上限: {target_char_count}
確認方針: 誤字脱字、表記ゆれ、文体、敬語、読みやすさ、文字数を確認する。

本文:
{essay}

必ずJSONのみを返してください。形式は次のとおりです。
{{"summary": "短い総評", "findings": [{{"type": "良い点|改善|要確認", "title": "評価項目名", "body": "具体的な根拠と修正案"}}], "suggestion": "改善後の文章案"}}
文字数は改行を除いて数え、上限を超えていれば改善にしてください。本文にない誤りを断定せず、修正案は具体的に示してください。"""

        request_body = json.dumps({
            "model": os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": "あなたは正確で簡潔な日本語添削者です。"},
                {"role": "user", "content": prompt},
            ],
        }).encode("utf-8")
        request = UrlRequest(
            os.environ.get("OPENAI_API_URL", "https://api.openai.com/v1/chat/completions"),
            data=request_body,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
            content = payload["choices"][0]["message"]["content"]
            result = json.loads(content)
            if not isinstance(result.get("findings"), list) or not result["findings"]:
                return None
            return {"summary": str(result.get("summary", "")), "findings": result["findings"], "suggestion": str(result.get("suggestion", "")), "ai_used": True}
        except (OSError, KeyError, TypeError, ValueError, TimeoutError):
            return None

    @app.route("/")
    def index():
        return render_template("index.html")

    @app.post("/api/review")
    def review():
        payload = request.get_json(silent=True) or {}
        essay = str(payload.get("essay", "")).strip()
        question_type = str(payload.get("question_type", "")).strip()
        question_guidance = QUESTION_GUIDANCE.get(question_type)
        target_char_count = payload.get("target_char_count")
        try:
            target_char_count = int(target_char_count)
        except (TypeError, ValueError):
            return jsonify({"error": "指定文字数は1以上の整数で入力してください。"}), 400
        if target_char_count < 1 or target_char_count > 10000:
            return jsonify({"error": "指定文字数は1〜10000の範囲で入力してください。"}), 400

        if not essay:
            return jsonify({"error": "添削する文章を入力してください。"}), 400

        corrected_essay, correction_changes = correct_essay_text(essay)
        ai_result = review_with_ai(corrected_essay, target_char_count)
        if ai_result:
            criteria_findings = evaluate_interview_criteria(corrected_essay)
            ai_result["findings"] = [
                {
                    "type": "良い点" if criterion["ok"] else "改善",
                    "title": criterion["title"],
                    "body": criterion["good"] if criterion["ok"] else criterion["advice"],
                }
                for criterion in criteria_findings
            ] + ai_result["findings"]
            if question_guidance:
                ai_result["findings"].insert(0, {
                    "type": "改善",
                    "title": f"{question_type}で重視する点",
                    "body": f"この質問では、{question_guidance}本文にこの観点を示す文があるか確認し、足りなければ具体的な経験や行動を1文追加してください。",
                })
            if correction_changes:
                ai_result["findings"].insert(0, {
                    "type": "改善",
                    "title": "文章を自動修正しました",
                    "body": "、".join(correction_changes) + "。修正後の文章を確認してください。",
                })
            result = {
                "id": str(uuid4()),
                "character_count": len(corrected_essay.replace("\n", "")),
                "target_char_count": target_char_count,
                "corrected_text": corrected_essay,
                **ai_result,
            }
            return jsonify(result)

        essay = corrected_essay
        character_count = len(essay.replace("\n", ""))
        findings = []
        for criterion in evaluate_interview_criteria(essay):
            findings.append({
                "type": "良い点" if criterion["ok"] else "改善",
                "title": criterion["title"],
                "body": criterion["good"] if criterion["ok"] else criterion["advice"],
            })
        if question_guidance:
            findings.append({
                "type": "改善",
                "title": f"{question_type}で重視する点",
                "body": f"この質問では、{question_guidance}本文にこの観点を示す文があるか確認し、足りなければ具体的な経験や行動を1文追加してください。",
            })
        typo_candidates = []
        okurigana_typos = {
            "組み立てる": "組み立てる",
        }

        typo_candidates.extend(correction_changes)

        okurigana_candidates = []
        for typo, correction in okurigana_typos.items():
            if typo in essay and typo != correction:
                okurigana_candidates.append(f"「{typo}」→「{correction}」")

        conjugation_typos = [
            (match.group(0), f"{match.group(1)}ます")
            for match in re.finditer(r"([ぁ-ん一-龥]+)(?:ましす|まます)", essay)
        ]
        for typo, correction in conjugation_typos:
            typo_candidates.append(f"「{typo}」→「{correction}」")

        if "聴力" in essay:
            findings.append({
                "type": "表現確認",
                "title": "「聴力」は意図した表現か確認してください",
                "body": "相手の話を聞いて理解する力を表す場合は、「傾聴力」または「聴く力」とする方が文脈に合う可能性があります。",
            })

        if re.search(r"(.)\1{2,}", essay):
            typo_candidates.append("同じ文字が3文字以上連続している箇所")
        if re.search(r"[、。！？]{2,}", essay):
            typo_candidates.append("句読点・記号が連続している箇所")
        if re.search(r"[ \u3000]+[、。！？]", essay):
            typo_candidates.append("句読点の前に入っている不要な空白")

        sentences = [sentence.strip() for sentence in re.split(r"[。！？\n]+", essay) if sentence.strip()]
        polite_ending_count = sum(
            bool(re.search(r"(?:です|ます|ました|ません|でしょう|ください)$", sentence))
            for sentence in sentences
        )
        plain_ending_count = sum(
            not bool(re.search(r"(?:です|ます|ました|ません|でしょう|ください)$", sentence))
            and bool(re.search(r"(?:だ|である|だった|ではない|する|した|できる|できた|なる|なった|ない|ある|あった|思う|考える|目指す|取り組む|話す|示す|動く|書く|読む|学ぶ|続ける|[うくぐつぬぶむる])$", sentence))
            for sentence in sentences
        )
        if typo_candidates:
                findings.append({
                    "type": "要確認",
                    "title": "誤字・脱字",
                    "body": "、".join(typo_candidates) + "。入力文を見直して、意図した表記か確認してください。",
                })
        else:
            findings.append({"type": "良い点", "title": "誤字・脱字", "body": "機械的に確認できる範囲では、気になる誤字脱字はありません。"})

            if polite_ending_count and plain_ending_count:
                findings.append({"type": "改善", "title": "表現", "body": "「です・ます」調と「だ・である」調が混在しています。ES全体をどちらか一方に統一しましょう。"})
            elif polite_ending_count == 0 and plain_ending_count == 0:
                findings.append({"type": "改善", "title": "表現", "body": "文体を「です・ます」調または「だ・である」調に統一すると、読みやすくなります。"})
            else:
                findings.append({"type": "良い点", "title": "表現", "body": "「です・ます」調で統一されています。「です」と「ます」は同じ丁寧な文体なので、文末が異なっていても問題ありません。"})

            honorific_issues = []
            if "御社" in essay:
                honorific_issues.append("書き言葉では「御社」より「貴社」が適切です")
            if "ご苦労様" in essay:
                honorific_issues.append("目上の相手には「ご苦労様」ではなく「お疲れ様です」を使います")
            if "了解しました" in essay:
                honorific_issues.append("「了解しました」より「承知しました」または「かしこまりました」が適切です")
            if "お伺いさせていただ" in essay or "拝見させていただ" in essay or "ご利用させていただ" in essay:
                honorific_issues.append("「お伺いさせていただく」などは敬語が重なるため、「伺う」「拝見する」などに整理しましょう")
            if len(re.findall(r"させていただ", essay)) >= 2:
                honorific_issues.append("「させていただく」が続いています。可能な箇所は「いたします」「します」にすると自然です")

            if honorific_issues:
                findings.append({"type": "要確認", "title": "敬語・謙譲語", "body": "。".join(honorific_issues) + "。"})
            else:
                findings.append({"type": "良い点", "title": "敬語・謙譲語", "body": "ESで確認できる範囲では、相手との関係に対して不自然な敬語・謙譲語は見つかりませんでした。"})

            if polite_ending_count and plain_ending_count:
                findings.append({"type": "改善", "title": "丁寧語", "body": "文末が混在しているため、丁寧語を使う場合は「です・ます」調に統一しましょう。"})
            elif re.search(r"(でございます|いたします|申し上げます|おります|存じます)", essay):
                findings.append({"type": "良い点", "title": "丁寧語", "body": "「です・ます」調を基本に、丁寧な表現を適切に使えています。過度にかしこまった表現は、文章全体のトーンに合わせて調整しましょう。"})
            elif polite_ending_count:
                findings.append({"type": "良い点", "title": "丁寧語", "body": "「です・ます」調で統一されており、ESとして読みやすい丁寧な文体です。"})
            else:
                findings.append({"type": "改善", "title": "丁寧語", "body": "ESでは「です・ます」調を基本にすると、読み手に配慮した自然な文章になります。"})

            has_conclusion = bool(re.search(r"(私は|私が|目指|志望|強み)", essay))
            has_reason = bool(re.search(r"(ため|理由|経験|きっかけ|通して)", essay))
            findings.append({
                "type": "良い点" if has_conclusion and has_reason else "改善",
                "title": "論理性",
                "body": "結論と理由の流れが読み取れます。" if has_conclusion and has_reason else "冒頭に結論を置き、その後に理由や経験を続けると主張が伝わりやすくなります。",
            })

            long_sentences = [sentence for sentence in sentences if len(sentence) > 65]
            findings.append({
                "type": "改善" if long_sentences else "良い点",
                "title": "文章の分かりやすさ",
                "body": "一文が長い箇所があります。1文1メッセージを意識して、文を分けると読み手が理解しやすくなります。" if long_sentences else "文の長さが大きく偏っておらず、内容を理解しやすい文章です。",
            })

            has_specific_detail = bool(re.search(r"(人|名|件|回|年|月|日|%|\d|具体的|結果|成果|実績)", essay))
            findings.append({
                "type": "良い点" if has_specific_detail else "改善",
                "title": "具体性",
                "body": "数字や成果、具体的な状況が含まれており、経験をイメージしやすいです。" if has_specific_detail else "「頑張った」「成長した」だけで終わらず、いつ・どこで・何をして・どう変わったかを具体的に書きましょう。",
            })

            has_strength = bool(re.search(r"(強み|得意|責任感|協調性|継続|傾聴|コミュニケーション)", essay))
            findings.append({
                "type": "良い点" if has_strength else "改善",
                "title": "自己PRの分かりやすさ",
                "body": "強みを示す言葉があり、自己PRの軸が伝わります。" if has_strength else "自分の強みを一言で示し、それが表れた行動や結果を続けると、自己PRが明確になります。",
            })

            concrete_words = bool(re.search(r"(会社|企業|事業|製品|サービス|業務|貢献|入社後)", essay))
            has_episode_result = bool(re.search(r"(結果|成果|実績|学び|活か|成長|改善)", essay))
            findings.append({
                "type": "良い点" if has_episode_result else "改善",
                "title": "エピソードと主張のつながり",
                "body": "経験から得た学びや成果が主張につながっています。" if has_episode_result else "経験の事実だけで終わらせず、その経験から何を学び、主張する強みや志望理由にどうつながるかを書きましょう。",
            })

        concrete_advice = {
            "誤字・脱字": "修正前後の文を声に出して読み、固有名詞・数字・送り仮名を原文や資料と照合してください。修正した語は検索して、本文中に同じ誤りが残っていないかも確認します。",
            "表現": "各文の文末を確認し、「です・ます」調にする場合は、例えば「参加した」を「参加しました」のようにそろえてください。変更後に前後の文を続けて読み、不自然な接続がないか確認します。",
            "敬語・謙譲語": "該当する表現を1つずつ「誰に対する言葉か」に置き換えて確認し、例えば「御社」は書き言葉の「貴社」に直してください。1文に敬語表現を重ねず、「お伺いさせていただく」は「伺う」のように短くします。",
            "丁寧語": "文末だけを拾って一覧にし、「だ・である」なら「です・ます」へ書き換えるなど、全て同じ文体に統一してください。書き換え後は、語尾だけでなく「〜だが」「〜であるため」などの途中の表現も確認します。",
            "論理性": "1文目を「私は〇〇を実現したいです」のような結論にし、2文目以降で理由・具体的な経験・得た結果、最後に応募先での活かし方を書く順番に組み替えてください。",
            "文章の分かりやすさ": "65文字を超える文を句点で2文に分け、1文につき1つの行動や主張だけを残してください。「〜して、〜して、〜しました」と続く文は、行動と結果で分けると読みやすくなります。",
            "具体性": "「いつ・どこで・何を・何人に・どう行動し・何が変わったか」のうち、数字を含む2項目以上を1文追加してください。例えば「売上が上がった」ではなく「3人で施策を実施し、1か月で参加者を20人増やした」と書きます。",
            "自己PRの分かりやすさ": "冒頭を「私の強みは〇〇です。」と始め、その強みが表れた行動と結果を続けてください。「強み→具体的な行動→数字で示す結果」の3文にすると、読み手が評価しやすくなります。",
            "エピソードと主張のつながり": "エピソードの最後に「この経験から〇〇を学び、入社後は〇〇に活かします。」という一文を追加してください。経験の説明で終わらず、冒頭の強みや志望理由に戻って結びます。",
            "文字数": "超過している場合は、まず重複する前置き・同じ意味の形容詞・背景説明から削り、主張・根拠・結果の3点を残してください。不足している場合は、行動の工夫と数字の結果を1文ずつ追加します。",
        }
        for finding in findings:
            advice = concrete_advice.get(finding["title"])
            if advice and finding["type"] in {"改善", "要確認"}:
                finding["body"] = f"{finding['body']} 具体的には、{advice}"

        length_body = f"{character_count}文字で、指定文字数{target_char_count}文字以内です。" if character_count <= target_char_count else f"{character_count}文字で、指定文字数を{character_count - target_char_count}文字超えています。"
        findings.append({"type": "良い点" if character_count <= target_char_count else "改善", "title": "文字数", "body": length_body})
        result = {
            "id": str(uuid4()),
            "character_count": character_count,
            "target_char_count": target_char_count,
            "summary": "誤字・脱字、表現、文体、読みやすさ、文字数を確認しました。",
            "ai_used": False,
            "corrected_text": essay,
            "suggestion": corrected_essay,
            "findings": findings,
        }
        return jsonify(result)

    @app.post("/api/next-question")
    def next_question():
        payload = request.get_json(silent=True) or {}
        answer = str(payload.get("answer", "")).strip()
        previous_question = str(payload.get("previous_question", "")).strip()
        question_number = int(payload.get("question_number", 0))
        fallback = fallback_question(answer, question_number, previous_question)
        prompt = (
            'あなたは日本語の面接官です。候補者の回答を踏まえた、自然な追質問を1つだけ作ってください。'
            '回答を繰り返さず、具体的な経験・行動・結果・学びのいずれかを深掘りしてください。'
            '質問文だけを返し、説明や番号は付けないでください。\n'
            f'直前の質問: {previous_question}\n候補者の回答: {answer or "回答なし"}\n'
            '直前の質問と同じ聞き方を繰り返さないでください。'
        )
        ollama_url = os.getenv('OLLAMA_URL', 'http://127.0.0.1:11434/api/generate')
        body = json.dumps({
            'model': os.getenv('OLLAMA_MODEL', 'qwen2.5:3b'),
            'prompt': prompt,
            'stream': False,
            'options': {'temperature': 0.4}
        }).encode('utf-8')
        try:
            request_data = urllib.request.Request(ollama_url, data=body, headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(request_data, timeout=20) as response:
                result = json.loads(response.read().decode('utf-8'))
            question = str(result.get('response', '')).strip().replace('\n', ' ')
            if question and len(question) <= 120:
                return jsonify(question=question, source='ollama')
        except (OSError, ValueError, json.JSONDecodeError):
            pass
        return jsonify(question=fallback, source='fallback')

    @app.post("/api/interview-advice")
    def interview_advice():
        payload = request.get_json(silent=True) or {}
        answer = str(payload.get('answer', '')).strip()
        question = str(payload.get('question', '')).strip()
        expression_score = int(payload.get('expression_score', 0) or 0)
        company = str(payload.get('company', '')).strip()
        mode = str(payload.get('mode', '')).strip()
        advice = build_heuristic_advice(answer, question, expression_score, company, mode)
        prompt = (
            'あなたは就職面接のコーチです。候補者の回答と表情の安定度を評価し、'
            '面接の良い点・改善点・次の一言をまとめてJSONで返してください。'
            'JSONのキーは summary, strengths, improvements, tips のみとし、'
            'strengths, improvements, tips は各3個までの配列にしてください。\n'
            f'企業名: {company or "不明"}\n面接形式: {mode or "不明"}\n'
            f'質問: {question or "不明"}\n回答: {answer or "回答なし"}\n'
            f'表情スコア: {expression_score}\n'
            '日本語で簡潔に返してください。'
        )
        ollama_url = os.getenv('OLLAMA_URL', 'http://127.0.0.1:11434/api/generate')
        body = json.dumps({
            'model': os.getenv('OLLAMA_MODEL', 'qwen2.5:3b'),
            'prompt': prompt,
            'stream': False,
            'options': {'temperature': 0.4}
        }).encode('utf-8')
        try:
            request_data = urllib.request.Request(ollama_url, data=body, headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(request_data, timeout=20) as response:
                result = json.loads(response.read().decode('utf-8'))
            candidate = str(result.get('response', '')).strip()
            if candidate:
                cleaned = candidate.strip('`')
                try:
                    parsed = json.loads(cleaned)
                    if isinstance(parsed, dict) and parsed.get('summary'):
                        return jsonify(parsed)
                except (TypeError, ValueError):
                    pass
        except (OSError, ValueError, json.JSONDecodeError):
            pass
        return jsonify(advice)

    @app.post("/api/interview-summary")
    def interview_summary():
        payload = request.get_json(silent=True) or {}
        answer = str(payload.get('answer', '')).strip()
        expression_score = int(payload.get('expression_score', 0) or 0)
        company = str(payload.get('company', '')).strip()
        mode = str(payload.get('mode', '')).strip()
        summary = build_summary(answer, expression_score, company, mode)
        return jsonify(summary)

    @app.post("/api/ai-consult")
    def ai_consult():
        payload = request.get_json(silent=True) or {}
        question = str(payload.get('question', '')).strip()
        answer = str(payload.get('answer', '')).strip()
        company = str(payload.get('company', '')).strip()
        mode = str(payload.get('mode', '')).strip()
        expression_score = int(payload.get('expression_score', 0) or 0)
        prompt = (
            'あなたは就職面接のコーチです。候補者の回答を踏まえて、相手への伝え方や改善点を相談に乗ってください。'
            '話し方、言葉の選び方、練習の方向性を具体的にアドバイスしてください。'
            '120字以内の日本語で、相談の答えだけを返してください。\n'
            f'企業名: {company or "不明"}\n面接形式: {mode or "不明"}\n'
            f'質問: {question or "不明"}\n回答: {answer or "回答なし"}\n'
            f'表情スコア: {expression_score}\n'
        )
        ollama_url = os.getenv('OLLAMA_URL', 'http://127.0.0.1:11434/api/generate')
        body = json.dumps({
            'model': os.getenv('OLLAMA_MODEL', 'qwen2.5:3b'),
            'prompt': prompt,
            'stream': False,
            'options': {'temperature': 0.5}
        }).encode('utf-8')
        try:
            request_data = urllib.request.Request(ollama_url, data=body, headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(request_data, timeout=20) as response:
                result = json.loads(response.read().decode('utf-8'))
            advice = str(result.get('response', '')).strip().replace('\n', ' ')
            if advice:
                return jsonify({'message': advice})
        except (OSError, ValueError, json.JSONDecodeError):
            pass
        fallback = '結論を先に伝え、そのあとに具体例を入れると伝わりやすくなります。特に「行動」「結果」「学び」をセットで話すと印象が強くなります。'
        return jsonify({'message': fallback})

    return app


app = create_app()


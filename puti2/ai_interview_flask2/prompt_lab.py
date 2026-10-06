"""助言(generate_llm_advice)を、モデルごとに複数回試して比べる実験用スクリプト。
 
使い方(ai_interview_flask2 フォルダで):

  python prompt_lab.py --runs 3

  python prompt_lab.py --runs 1 --models qwen2.5:7b --case intro --raw

"""

import argparse

import difflib

import logging

import os

import re

import time
 
import app as advice_app
 
# テスト用の回答(名前は仮名)

CASES = {

    'intro': {

        'question': '自己紹介をしてください',

        'main': (

            '私は山田と申します。大原学園のITシステム科に在籍しております。'

            '私の強みは、課題を粘り強く改善し続けられることです。'

            '学校のチーム開発で、画面の表示が遅い問題がありました。'

            '原因を調べたところ、同じデータを何度も取得していたため、まとめて取得する形に直しました。'

            'その結果、表示時間が約5秒から1秒に短くなりました。'

            'この経験から、数字で確認しながら改善する大切さを学びました。'

            '御社でも、課題を数字で捉えて改善していきたいと考えております。'

        ),

        'followups': [],

    },

    'experience': {

        'question': '学生時代に最も力を入れたことは何ですか',

        'main': (

            '僕は授業のチーム開発で、Javaで予約管理システムを作りました。'

            'えっと、僕はデータベースの設計を担当して、メンバーと毎週相談しながら進めました。'

            '結果的に期限までに完成できて、チームで協力する大切さを学びました。'

        ),

        'followups': [

            {

                'question': 'その行動を始めようと思ったきっかけや理由を教えてください。',

                'answer': (

                    'IT業界で働くには、基礎知識を客観的に証明できる資格が必要だと考えたのがきっかけです。'

                    '先輩から、基本情報技術者試験が就職活動でも評価されたと聞いて、1年生の終わりに受験を決めました'

                ),

            },

        ],

    },

}
 
OPEN_END = re.compile(r'[がてでをにはもとや、]$')
 
 
class Collector(logging.Handler):

    def __init__(self):

        super().__init__()

        self.records = []
 
    def emit(self, record):

        self.records.append(record.getMessage())
 
 
def strip_end(text):

    return re.sub(r'[」』。\s]+$', '', str(text or ''))
 
 
def check_flags(advice, has_followup):

    """機械で見つけられる「気になる点」を返す。"""

    flags = []

    items = advice['items']

    for item in items:

        example = strip_end(item['example'])

        if OPEN_END.search(example):

            flags.append(f'例文が途中で終わっている: {item["title"]}')

        ratio = difflib.SequenceMatcher(

            None,

            advice_app.normalize_for_match(item['quote']),

            advice_app.normalize_for_match(example),

        ).ratio()

        if ratio > 0.8:

            flags.append(f'例文が引用とほぼ同じ: {item["title"]}')

    good = advice['good']

    if good:

        quotes = advice_app.extract_quoted_text(good)

        rest = good

        for quote in quotes:

            rest = rest.replace(quote, '')

        rest = re.sub(r'[「」\s]', '', rest)

        if len(rest) < 10:

            flags.append('良かった点に理由がない')

        for quote in quotes:

            if any(quote in item['quote'] or item['quote'] in quote for item in items):

                flags.append('良かった点と直す点が同じ部分')

                break

    else:

        flags.append('良かった点が空')

    if has_followup and not advice['followUp']:

        flags.append('深掘りの評価が空')

    return flags
 
 
def show_run(model, case_name, run, seconds, advice, error, flags, logs, show_raw):

    print(f'\n=== {model} / {case_name} / {run}回目 ({seconds:.1f}秒) ===')

    if advice:

        print(f'良かった点: {advice["good"] or "(なし)"}')

        for index, item in enumerate(advice['items'], start=1):

            print(f'[{index}] {item["title"]} / 引用: {item["quote"]}')

            print(f'    直し方: {item["advice"]}')

            print(f'    例: {item["example"]}')

        print(f'深掘り評価: {advice["followUp"] or "(なし)"}')

        if flags:

            print('気になる点:')

            for flag in flags:

                print(f'  - {flag}')

    else:

        print(f'失敗: {error}')

    problems = [m for m in logs if 'discarded' in m or 'validation failed' in m or 'generation failed' in m]

    if problems:

        print('捨てられた項目・失敗の理由:')

        for message in problems:

            print(f'  - {message}')

    if show_raw:

        for message in logs:

            if 'raw_output' in message:

                print(message)
 
 
def main():

    parser = argparse.ArgumentParser()

    parser.add_argument('--runs', type=int, default=3)

    parser.add_argument('--models', nargs='+', default=['qwen2.5:3b', 'qwen2.5:7b'])

    parser.add_argument('--case', default='all', choices=['all'] + list(CASES))

    parser.add_argument('--attempts', type=int, default=1, help='1回の実行での再試行回数(既定1=初回の出来を見る)')

    parser.add_argument('--raw', action='store_true', help='モデルの生の出力も表示する')

    args = parser.parse_args()
 
    if args.raw:

        os.environ['DEBUG_LOG_LLM_OUTPUT'] = '1'

    collector = Collector()

    advice_app.app.logger.handlers = [collector]

    advice_app.app.logger.setLevel(logging.INFO)

    advice_app.app.logger.propagate = False

    advice_app.ADVICE_ATTEMPTS = max(1, args.attempts)
 
    case_names = list(CASES) if args.case == 'all' else [args.case]

    summary = {}

    for model in args.models:

        advice_app.ADVICE_MODEL = model

        for case_name in case_names:

            case = CASES[case_name]

            stats = summary.setdefault((model, case_name), {'ok': 0, 'runs': 0, 'seconds': [], 'flags': 0})

            for run in range(1, args.runs + 1):

                collector.records.clear()

                started = time.perf_counter()

                advice, error = None, ''

                try:

                    advice, _source, _attempts = advice_app.generate_llm_advice(

                        case['question'], case['main'], case['followups'],

                    )

                except advice_app.OllamaError as exc:

                    error = str(exc)

                seconds = time.perf_counter() - started

                flags = check_flags(advice, bool(case['followups'])) if advice else []

                show_run(model, case_name, run, seconds, advice, error, flags, list(collector.records), args.raw)

                stats['runs'] += 1

                stats['seconds'].append(seconds)

                if advice:

                    stats['ok'] += 1

                    stats['flags'] += len(flags)
 
    print('\n\n##### まとめ #####')

    print('モデル / ケース / 成功 / 平均秒 / 気になる点(成功した回の合計)')

    for (model, case_name), stats in summary.items():

        average = sum(stats['seconds']) / len(stats['seconds'])

        print(f'{model} / {case_name} / {stats["ok"]}/{stats["runs"]} / {average:.1f}秒 / {stats["flags"]}')
 
 
if __name__ == '__main__':

    main()
 
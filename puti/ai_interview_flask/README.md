# AI面接練習（Flask版）

就活生向けAI面接練習システムのFlaskアプリです。

## 構成
```
ai_interview_flask/
├─ app.py                 # Flaskアプリ本体（ルーティング・API）
├─ requirements.txt
├─ templates/
│  └─ index.html           # 画面のHTML（Jinjaテンプレート）
└─ static/
   ├─ css/style.css        # スタイル
   ├─ js/app.js            # 画面遷移・カメラ/マイク制御・録画アップロード
   └─ uploads/              # アップロードされた面接動画の保存先（自動作成）
```

## セットアップと起動

### 1. Ollama（無料のローカルAI）を用意する
1. https://ollama.com からOllamaをインストールする（Mac/Windows/Linux対応）
2. モデルを1回だけダウンロードする
   ```bash
   ollama pull qwen2.5:7b
   ```
   - 日本語の精度重視なら `qwen2.5:7b`（推奨、メモリ8GB以上の目安）
   - PCのスペックが低い場合は軽量モデルに変更可：`ollama pull qwen2.5:3b` や `ollama pull llama3.2`
3. Ollamaを起動する（インストール後は自動起動していることが多い。手動なら）
   ```bash
   ollama serve
   ```

### 2. Flaskアプリを起動する
```bash
cd ai_interview_flask
python -m venv venv
source venv/bin/activate      # Windowsは venv\Scripts\activate
pip install -r requirements.txt
python app.py
```
ブラウザで `http://127.0.0.1:5000` を開いてください。
カメラ・マイクを使うため、本番運用時は HTTPS 配信が必要です（ローカルの `127.0.0.1` は例外的に許可されます）。

### Dockerの開発コンテナ（devcontainer）から使う場合
FlaskアプリがDockerコンテナの中で動いていて、Ollamaはホスト側（コンテナの外）で動かしている場合、コンテナの中からは `localhost` でホストに届かないことがあります。その場合は環境変数 `OLLAMA_HOST` でホスト側を指定してください。
```bash
# Mac/Windows (Docker Desktop)
export OLLAMA_HOST=http://host.docker.internal:11434
# Linux（コンテナ起動時に --add-host=host.docker.internal:host-gateway が必要な場合あり）
export OLLAMA_HOST=http://host.docker.internal:11434
```
使うモデルを変えたい場合は `export OLLAMA_MODEL=llama3.2` のように指定してください（未設定時は `qwen2.5:7b`）。

Ollamaが起動していない／モデルが未ダウンロードの場合でもアプリ自体は落ちず、最初の2回は定型の深掘り質問を返し、その後に次の質問へ進みます（サーバーのログに警告が出ます）。

## API
| メソッド | パス | 内容 |
|---|---|---|
| GET | `/api/companies` | お気に入り企業と過去質問の一覧を取得 |
| GET | `/api/logs` | 練習ログ（企業名・質問・動画URL・日時）の一覧を取得 |
| POST | `/api/logs` | 録画（video）・企業名（company）・質問（question）をアップロードして保存 |
| POST | `/api/interview/reply` | 学生の直前の回答（テキスト）を受け取り、AI面接官の相槌＋深掘り質問（またはそのまま次の質問へ進む判断）をJSONで返す（ローカルのOllamaを使用、無料） |

## 面接中の会話フロー
1. AIが質問を音声で読み上げる（1回のみ）。
2. Web Speech API（`SpeechRecognition`）でユーザーの発話をテキスト化しながら聞き取る。約1.8秒の無音でユーザーが話し終えたと判断。
3. テキスト化した回答を `/api/interview/reply` に送信し、ローカルのOllama（無料）で相槌＋深掘り質問（またはそのまま終了の判断）を生成。
4. AIの発言を音声で読み上げたのち、`move_on: false` ならもう一度ユーザーの回答を聞き取り（最大2往復まで深掘り）、`move_on: true` になった時点で自動的に次の質問へ進む。ユーザー操作によるボタン送りは廃止。
5. `SpeechRecognition` 非対応ブラウザ（Firefox等）では、自動的にテキスト入力欄が表示され、そこに回答を打ち込んで送信する形にフォールバックする。

## 現状の実装メモ・今後の拡張ポイント
- `COMPANIES` は `app.py` 内のモックデータです。お気に入り企業登録機能（別機能として開発予定）と連携させ、DB等から取得するように差し替えてください。
- 練習ログはメモリ上の配列 `LOGS` に保持しているため、**サーバーを再起動すると履歴データ（メタ情報）は消えます**。動画ファイル自体は `static/uploads/` に残ります。本番運用ではSQLite/PostgreSQL等のDBに置き換えることを推奨します。
- 質問・AIの相槌音声はブラウザのWeb Speech API（`speechSynthesis`）で読み上げています。
- 深掘りAIはOllama（ローカル・無料）を使用しています。応答精度やスピードはPCのスペックと選んだモデルに依存します。速度が遅い・回答が不自然な場合はモデルを変えて試してください。
- 深掘りの最大回数はフロント・バック双方で `MAX_FOLLOWUPS = 2` に設定しています（変更する場合は `app.py` と `static/js/app.js` の両方を合わせてください）。
- アップロードした動画ファイルの容量管理・自動削除は未実装です。

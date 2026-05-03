# AITuber配信パートナー Ph1 技術設計

## 1. 設計目的

Ph1では、YouTube Liveを主対象にしたローカル実演可能なAITuber共同MCを作る。

要求定義の機能を一度に大きな一体型アプリとして作らず、入力、判断、生成、音声、字幕、保存を疎結合のコンポーネントに分ける。これにより、YouTube Chat取得、STT、LLM、TTS、OBS字幕のどれかが未完成でも、モックを差し替えて実演経路を確認できる状態を維持する。

## 2. 全体構成

Ph1の基本構成は、Pythonのバックエンドプロセスと、OBSブラウザソース用の軽量Webフロントエンドに分ける。

```text
YouTube Live Chat  ┐
Microphone STT     ├─> Input Ingest ─> Event Queue ─> Orchestrator
Idle Topic Timer   ┘                                      │
                                                           ├─> Safety / Selection LLM
                                                           ├─> Memory Search
                                                           ├─> Reply LLM
                                                           ├─> TTS
                                                           ├─> OBS Overlay State
                                                           └─> Storage

OBS Browser Source <──────────── Web Overlay Server
Speakers / Audio Device <─────── AivisSpeech Audio Output
```

### 2.1 バックエンド

- 言語はPythonを主軸にする。
- YouTube Chat取得、STT、LLM Router、TTS、SQLite、LanceDBを扱う。
- 非同期I/Oが多いため、実装は`asyncio`ベースを基本候補にする。
- Python 3.13ではSTT周辺の互換性が不安定な可能性があるため、実装開始時はPython 3.11または3.12の仮想環境を優先する。

### 2.2 フロントエンド

- OBSブラウザソース用の字幕オーバーレイを提供する。
- Ph1では複雑なSPAにせず、HTML/CSS/TypeScriptまたは最小限のNode/Vite構成でよい。
- バックエンドからWebSocketまたはServer-Sent Eventsで現在発話中テキストと状態を受け取る。
- Live2D、3D、口パク、表情制御はPh2以降に分離する。

## 3. 推奨ディレクトリ構成

```text
docs/
  requirements.md
  architecture.md
src/
  aituber_partner/
    app.py
    config.py
    models.py
    orchestrator.py
    inputs/
      youtube_chat.py
      microphone.py
      idle_topic.py
    llm/
      ollama_client.py
      router.py
      prompts.py
      safety.py
      selection.py
      reply.py
      vision.py
    memory/
      sqlite_store.py
      vector_store.py
      retrieval.py
    speech/
      aivis_client.py
      player.py
    overlay/
      state.py
      server.py
    logging/
      events.py
tests/
  unit/
  integration/
overlay/
  index.html
  src/
    main.ts
    styles.css
data/
  .gitkeep
```

`data/`配下のSQLite DB、LanceDB、音声ファイル、ログは原則としてGit管理しない。

## 4. 実行プロセス

Ph1の最小実演では、以下の2プロセスを想定する。

### 4.1 Backend Process

役割:

- 入力イベントを収集する。
- 回答対象を選定する。
- 安全判定を行う。
- メモリ検索を行う。
- 返答を生成する。
- TTSを実行する。
- オーバーレイ状態を配信する。
- SQLiteとLanceDBに履歴を保存する。

起動イメージ:

```powershell
python -m aituber_partner.app --config config/local.toml
```

CLIは既定ではOllamaに接続せず、FakeInputSourceと決定的なプレースホルダー回答で閉ループを確認する。ローカルOllama経路を試す場合は、対象モデルをpullまたは起動済みにしたうえで以下を使う。

```powershell
uv run aituber-partner --use-ollama
```

この経路では入力安全判定と出力安全判定に`qwen3.5:4b`、通常回答生成に`qwen3:8b`を使い、Qwen系呼び出しには`think: false`を付ける。

### 4.2 Overlay Process

役割:

- OBSブラウザソース向け字幕画面を提供する。
- バックエンドから現在状態を受け取り、字幕を更新する。

起動イメージ:

```powershell
npm run dev
```

ただし、Ph1初期はバックエンド側で静的ファイルを配信し、Nodeプロセスを不要にしてもよい。

## 5. コンポーネント責務

### 5.1 Input Ingest

入力を`InputEvent`に正規化する。

- YouTube Chat: 新規コメントの取得、重複排除、author情報の付与。
- Microphone: ローカルWhisper系で音声を文字起こしし、音声入力イベント化。
- Idle Topic: 一定時間入力がない場合にトリガーイベントを生成。

YouTube APIやSTTが未実装でもPoCを進められるよう、最初に`FakeInputSource`を用意する。

### 5.2 Event Queue

入力イベントを一度キューに積み、Orchestratorが順に処理する。

- Ph1初期はプロセス内の`asyncio.Queue`でよい。
- 将来、別プロセス化する場合はRedisやSQLiteキューを検討する。
- 返答中に新しい入力が来た場合は、割り込みではなく次候補として保持する。

### 5.3 Orchestrator

配信中の状態遷移を制御する中核。

基本フロー:

1. 入力イベントを受け取る。
2. コメント候補をまとめて選定に回す。
3. 安全判定を行う。
4. 必要なら過去文脈を検索する。
5. 回答を生成する。
6. 回答テキストを最終安全チェックに通す。
7. TTSを作成して再生する。
8. OBS字幕状態を更新する。
9. 全判断と出力を保存する。

初期実装では、`LocalClosedLoopOrchestrator`に`LLMRouter`を注入した場合だけOllama経路を使う。未注入時はCLIと単体テストがローカル依存なしで動くよう、決定的なプレースホルダー経路を維持する。

LLM経路では、入力安全判定、回答生成、出力安全判定の順に実行する。安全判定JSONのパース失敗は`block`として扱い、回答生成または字幕更新へ進めない。`deflect`の場合は安全な話題へ寄せた短い回答を生成する。

### 5.4 LLM Router

Ollamaモデルの役割境界を固定し、呼び出しログに残す。

| 用途 | 既定モデル | 備考 |
| --- | --- | --- |
| 入力分類 | `qwen3.5:4b` | `think: false`必須 |
| 安全判定 | `qwen3.5:4b` | JSON形式を要求 |
| コメント選定 | `qwen3.5:4b` | 複数候補から少数選択 |
| 通常回答 | `qwen3:8b` | `think: false`必須 |
| 画像解析 | `qwen3.5:9b` | 画像付き入力時のみ |
| 日本語品質レビュー | `pakachan/elyza-llama3-8b` | 非リアルタイム経路 |

Qwen系呼び出しでは、常に`think: false`を指定する。モデル応答の後処理でも、万一thinking風のタグや内部思考が混入した場合は字幕/TTSへ渡す前に除去する。

### 5.5 Safety / Selection

安全判定とコメント選定は回答生成より前に行う。

- `allow`: 通常回答する。
- `ignore`: 拾わずログだけ残す。
- `deflect`: 一般化して安全な話題へ転換する。
- `block`: 出力しない。

選定は、安全性、話題性、文脈適合度、返答しやすさをスコア化する。初期実装ではLLMにJSONで返させ、パース失敗時は安全側に倒して不採用にする。

### 5.6 Memory

Ph1では、長期記憶の自動人格反映は行わない。

- SQLite: すべてのイベント、判断、生成結果、TTS結果、セッションを保存する。
- LanceDB: 会話文脈、キャラ設定、運用メモの検索用埋め込みを保存する。
- 回答生成時は、関連する過去文脈を数件だけ取得する。
- メモリ更新ルールは明示設定にし、LLMの判断だけで永続的な人格設定を変更しない。

### 5.7 TTS

AivisSpeechを既定TTSにする。

- 回答テキストをAivisSpeech APIへ送る。
- 生成音声ファイルのパス、voice_id、生成時間、再生状態を`SpeechJob`として保存する。
- TTS失敗時は、字幕だけ更新し、音声失敗を状態表示とログに残す。

### 5.8 Overlay

OBS字幕オーバーレイは、現在状態を表示するだけの薄いUIにする。

表示候補:

- 現在発話中のテキスト。
- 状態: `idle | thinking | speaking | listening | error`。
- 任意で短い話者名。

バックエンドからWebSocketまたはSSEで状態を送る。Ph1初期はSSEのほうが実装が軽い。

## 6. データモデル

要求定義のインターフェース案を、初期実装ではPydanticモデルとして定義する。

### 6.1 InputEvent

```python
class InputEvent(BaseModel):
    id: str
    source: Literal["youtube_chat", "voice", "idle_topic"]
    text: str
    author: str | None = None
    timestamp: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)
    image_ref: str | None = None
```

### 6.2 SafetyDecision

```python
class SafetyDecision(BaseModel):
    status: Literal["allow", "ignore", "deflect", "block"]
    reasons: list[str]
    safe_topic: str | None = None
    confidence: float
```

### 6.3 GeneratedReply

```python
class GeneratedReply(BaseModel):
    id: str
    text: str
    persona_version: str
    memory_refs: list[str]
    generation_model: str
    latency_ms: int
```

### 6.4 OverlayState

```python
class OverlayState(BaseModel):
    status: Literal["idle", "listening", "thinking", "speaking", "error"]
    text: str
    updated_at: datetime
    detail: str | None = None
```

### 6.5 ProcessedEvent

```python
class ProcessedEvent(BaseModel):
    input_event: InputEvent
    safety: SafetyDecision
    output_safety: SafetyDecision | None = None
    reply: GeneratedReply | None
    overlay: OverlayState
```

## 7. SQLite初期テーブル

初期テーブル候補:

- `stream_sessions`
- `input_events`
- `safety_decisions`
- `selected_prompts`
- `generated_replies`
- `speech_jobs`
- `llm_calls`
- `overlay_events`

`llm_calls`には、モデル名、用途、入力要約、出力要約、latency_ms、think指定、成功/失敗、エラー内容を保存する。これにより、`qwen3.5:9b`が通常コメント経路で呼ばれていないことや、Qwen系で`think: false`が指定されていることを検証できる。

## 8. 設定ファイル

ローカル設定は`config/local.toml`を想定する。秘密情報や環境固有値はGit管理しない。

```toml
[ollama]
base_url = "http://127.0.0.1:11434"
keep_alive = "30m"

[models]
classifier = "qwen3.5:4b"
reply = "qwen3:8b"
vision = "qwen3.5:9b"
review = "pakachan/elyza-llama3-8b"

[aivis]
base_url = "http://127.0.0.1:10101"
voice_id = "default"

[overlay]
host = "127.0.0.1"
port = 8787

[storage]
sqlite_path = "data/app.db"
lancedb_path = "data/lancedb"
audio_dir = "data/audio"
```

## 9. 最小PoCの実装順

### Step 1: ローカル閉ループ

- FakeInputSourceで固定コメントを流す。
- `qwen3.5:4b`で安全判定と選定を行う。
- `qwen3:8b`で短い回答を生成する。
- AivisSpeechを呼ぶ代わりに、初期はコンソール出力またはダミーSpeechJobでもよい。
- OverlayStateを更新する。
- SQLiteに保存する。

### Step 2: AivisSpeech接続

- AivisSpeech APIで音声を生成する。
- 音声ファイルを保存し、再生する。
- TTS失敗時の字幕継続を確認する。

### Step 3: OBS字幕

- OBSブラウザソースから見られるオーバーレイを提供する。
- 発話中テキストと状態がリアルタイム更新されることを確認する。

### Step 4: YouTube Chat取得

- YouTube Live Chatから新規コメントを取得する。
- 重複排除とレート制御を入れる。
- コメント候補をまとめて選定する。

### Step 5: STT

- ローカルWhisper系でマイク音声を文字起こしする。
- 音声入力イベントをチャット入力と同じ経路に流す。

### Step 6: LanceDB検索

- 過去発話と運用メモを埋め込み保存する。
- 回答生成時に関連文脈を数件だけ渡す。

## 10. 初期テスト方針

- LLM Routerが用途ごとに正しいモデルを選ぶ。
- Qwen系呼び出しに`think: false`が入る。
- 画像なし通常コメントで`qwen3.5:9b`が呼ばれない。
- 安全判定JSONのパース失敗時に回答しない。
- 荒らし、個人情報、差別的コメントが回答対象から外れる。
- TTS失敗時も字幕更新とログ保存が行われる。
- SQLiteに入力、判断、回答、TTS、モデル呼び出し履歴が保存される。
- 無入力タイマーからidle topicイベントが発火する。

## 11. Ph2以降に残す判断

- Live2Dまたは3Dモデル制御。
- 口パク、表情、モーション制御。
- OBSシーンの高度制御。
- Qwen3-TTSの本格導入。
- 長期記憶の自動更新と人格反映。
- 画像解析を常時リアルタイム経路へ入れること。

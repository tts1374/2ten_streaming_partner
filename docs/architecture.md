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

入力ソースは`IdleTopicInputSource`で包まれ、`config.runtime.idle_timeout_seconds`の間に通常入力が来ない場合は`source="idle_topic"`の`InputEvent`を生成する。idle topicも通常入力と同じ安全判定、回答生成、TTS、OBS字幕、SQLite保存経路を通る。実チャットやSTTのように長時間待機する入力ソースでは、無言時間の穴埋めとして設定済みトピックが順番に使われる。idle topicを一度出した後は`config.runtime.idle_repeat_interval_seconds`だけ待ってから次のidle topicを出すため、コメントが少ない配信でも同じ間隔で話題を連発しにくい。

YouTube Live Chatを実入力にする場合は、`config/local.toml`の`[youtube_chat]`に`live_chat_id`または`video_id`を設定し、`api_key_env`で指定した環境変数、既定では`YOUTUBE_API_KEY`にYouTube Data APIキーを入れてから`--use-youtube-chat`を付ける。`video_id`を指定した場合は、起動時にYouTube Data APIの`videos?part=liveStreamingDetails`から`activeLiveChatId`を解決する。CLIでは`--youtube-video-id`で一時的に動画IDを上書きできる。初期実装はYouTube Live Streaming APIの`liveChat/messages`を標準ライブラリでポーリングし、`nextPageToken`、`pollingIntervalMillis`、メッセージIDの重複排除を使って新規コメントだけを`InputEvent(source="youtube_chat")`へ正規化する。`skip_initial_history = true`が既定なので、起動直後に返る過去コメントには反応せず、次ページ以降の新規コメントを拾う。

`pageTokenInvalid`、`liveChatEnded`、`liveChatDisabled`、`liveChatNotFound`、`quotaExceeded`、`keyInvalid`などのYouTube APIエラーは、HTTPステータスとreasonに加えて、再起動、配信切替、チャット有効化、APIキーまたはquota確認といった運用者向けの短い対処文に整形して表示する。

```powershell
uv run aituber-partner --use-ollama
```

この経路では入力安全判定と出力安全判定に`qwen3.5:4b`、通常回答生成に`qwen3:8b`を使い、Qwen系呼び出しには`think: false`を付ける。

低遅延確認では以下のように出力安全判定だけローカルguardへ切り替えられる。この場合、LLM呼び出しは入力安全判定と回答生成の2回になり、最終段ではthinking風テキスト、空文字、危険語を決定的にブロックする。

```powershell
uv run aituber-partner --use-ollama --fast-output-safety
```

ローカルのAivisSpeechへ音声生成とWAV再生も投げる場合は以下を使う。AivisSpeechは`/audio_query`でクエリを作り、`/synthesis`でWAVを生成する。生成、再生、失敗は`speech_jobs`に保存し、TTSや再生に失敗しても字幕状態は維持する。

```powershell
uv run aituber-partner --use-ollama --fast-output-safety --use-aivis
```

OBSブラウザソース用の字幕オーバーレイも同じバックエンドプロセスで配信できる。`--serve-overlay`を付けると、`config.overlay.host`と`config.overlay.port`で`overlay/index.html`を静的配信し、`/events`からServer-Sent Eventsで`OverlayState`を送る。

```powershell
uv run aituber-partner --use-ollama --fast-output-safety --use-aivis --serve-overlay
```

実チャット、Ollama、AivisSpeech、OBS字幕をまとめて動かす場合は以下の形になる。

```powershell
$env:YOUTUBE_API_KEY = "..."
uv run aituber-partner --use-youtube-chat --use-ollama --fast-output-safety --use-aivis --serve-overlay --config config/local.toml
```

動画IDだけを一時指定して実チャットを試す場合は以下でもよい。

```powershell
$env:YOUTUBE_API_KEY = "..."
uv run aituber-partner --use-youtube-chat --youtube-video-id "PW1OSW2YqCs" --use-ollama --fast-output-safety --serve-overlay --config config/local.toml
```

OBSのブラウザソースには、起動時に表示されるURL、既定では`http://127.0.0.1:8787/`を指定する。Ph1のオーバーレイは字幕firstの薄いUIで、発話中テキスト、簡易状態、短い話者名だけを扱う。話者名は`config.overlay.speaker_name`で変更できる。TTSや音声再生の失敗詳細は`OverlayState.detail`に残すが、OBS画面では`config.overlay.show_detail = true`の時だけ小さく表示する。Live2D、3D、口パク、表情制御、高度なOBS制御は含めない。

OBSで表示位置や文字サイズを調整する場合は、LLM/TTSを通さないデモ字幕を表示できる。

```powershell
uv run aituber-partner demo-overlay --text "OBS表示テスト中です！" --seconds 10
```

指定秒数後に字幕は消えるが、オーバーレイサーバはOBS調整のため起動したままにする。終了するときはCtrl+Cで止める。

字幕を出したまま表示調整する場合は`--keep-visible`を付ける。

直近のLLM呼び出し遅延はSQLiteから簡易確認できる。`model`、`purpose`、`latency_ms`、`think`、成功可否を一覧し、通常経路と低遅延経路の内訳確認に使う。

```powershell
uv run aituber-partner inspect-latency --limit 20
```

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

LLM経路では、入力安全判定、回答生成、出力安全判定の順に実行する。安全判定JSONのパース失敗は`block`として扱い、回答生成または字幕更新へ進めない。`deflect`の場合は安全な話題へ寄せた短い回答を生成する。低遅延モードでは、出力安全判定のみローカルguardに差し替え、追加のLLM安全判定を省く。

回答生成では入力sourceごとに会話目的を変える。`voice`は人間配信者の発言として扱い、配信者へ直接返す。`youtube_chat`は視聴者コメントとして扱い、コメント内容を配信者に取り次ぎ、必要な場合だけ配信者に向けて話題を広げる。`idle_topic`は独り言ではなく、直近の通常入力メタデータがある場合はそれに接続した短い質問または話題として配信者へ投げかける。配信者の呼び名は`config.runtime.streamer_name`で設定し、既定では「つてん」としてプロンプトに渡す。

CLI実行では`config.storage.sqlite_path`のSQLite DBへ処理済みイベントを保存する。初期保存対象は、入力イベント、安全判定、生成回答、字幕状態、LLM呼び出しである。

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
- TTSまたはWAV再生の失敗時は、字幕だけ更新し、音声失敗を状態表示とログに残す。

### 5.8 Overlay

OBS字幕オーバーレイは、現在状態を表示するだけの薄いUIにする。

表示候補:

- 現在発話中のテキスト。
- 状態: `idle | thinking | speaking | listening | error`。
- 設定可能な短い話者名。
- 任意の補助詳細。既定ではOBS上に表示しない。
- 発話終了後またはTTS失敗後は、既定で2.5秒だけ字幕を残してから`idle`へ戻す。

バックエンドからWebSocketまたはSSEで状態を送る。Ph1初期は標準ライブラリのHTTPサーバとSSEで実装し、追加のNodeプロセスやSPA構成は導入しない。

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

初期実装では`SQLiteStore`が`input_events`、`safety_decisions`、`generated_replies`、`speech_jobs`、`overlay_events`、`llm_calls`を作成する。LLM呼び出しは`RecordingLLMClient`でラップした場合に成功・失敗を保存する。TTSとWAV再生は`--use-aivis`指定時だけ実行し、AivisSpeech未起動や再生失敗も`speech_jobs.status = failed`として残す。

## 8. 設定ファイル

ローカル設定は`config/local.toml`を想定する。秘密情報や環境固有値はGit管理しない。
初回は`config/local.example.toml`を`config/local.toml`へコピーし、`[youtube_chat]`の`live_chat_id`など手元の値だけを編集する。

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
voice_id = 888753760
timeout_seconds = 30.0

[overlay]
host = "127.0.0.1"
port = 8787
speaker_name = "2ten"
show_detail = false
clear_after_speech_seconds = 2.5

[youtube_chat]
live_chat_id = "YOUR_LIVE_CHAT_ID"
video_id = ""
api_key_env = "YOUTUBE_API_KEY"
poll_interval_seconds = 5.0
min_poll_interval_seconds = 1.0
request_timeout_seconds = 10.0
max_results = 200
skip_initial_history = true

[storage]
sqlite_path = "data/app.db"
lancedb_path = "data/lancedb"
audio_dir = "data/audio"

[runtime]
streamer_name = "つてん"
idle_timeout_seconds = 30.0
idle_repeat_interval_seconds = 120.0
idle_topics = [
  "最近プレイした音ゲー曲で、判定が光った瞬間の話",
  "今日の配信で次に注目したい譜面の見どころ",
]
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

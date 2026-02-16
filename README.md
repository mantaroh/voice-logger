# voice-logger

USB録音デバイスを監視し、新規音声をローカル保存してUSB上の元ファイルを削除、`whisper.cpp + kotoba-whisper2.2` で文字起こし、任意でLLM要約する `macOS/Linux` 向けアプリです。`macOSメニューバー / Ubuntuトレイ` の常駐UIで状態確認できます。

## 機能

- USBマウント監視（ラベル名ベース）
- 新規音声のみ取り込み（stateファイルで重複防止）
- 取り込み成功後にUSB元ファイルを削除
- `whisper.cpp` 実行で文字起こし保存
- 要約プロバイダ切り替え（`openai / anthropic / gemini / openrouter / cloudflare`）
- 任意で24時間録音コマンドを並行実行（`[recorder]`）
- トレイ常駐実行（`voice-logger-tray`）
- CLI実行 (`run`, `once`)
- 起動時自動実行テンプレート（`launchd`, `autostart .desktop`, `systemd --user`）

## 要件

- Python `3.11+`
- `whisper.cpp` の `whisper-cli`
- `kotoba-whisper2.2` モデルファイル（gguf/bin）
- GUIセッション（トレイ表示のため）

## macOS / Ubuntu インストールと起動

### macOS

1. セットアップ

```bash
cd /Users/mantaroh/code/voice-logger
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
cp config.example.toml config.toml
```

2. `config.toml` を編集（USB名、保存先、`whisper-cli`、モデル、LLMキー環境変数名）
3. 手動起動（トレイ）

```bash
source /Users/mantaroh/code/voice-logger/.venv/bin/activate
voice-logger-tray --config /Users/mantaroh/code/voice-logger/config.toml
```

4. ログイン時自動起動

```bash
cp /Users/mantaroh/code/voice-logger/deploy/launchd/com.mantaroh.voice-logger.plist ~/Library/LaunchAgents/
launchctl unload ~/Library/LaunchAgents/com.mantaroh.voice-logger.plist 2>/dev/null || true
launchctl load ~/Library/LaunchAgents/com.mantaroh.voice-logger.plist
launchctl start com.mantaroh.voice-logger
```

### Ubuntu

1. セットアップ

```bash
cd /Users/mantaroh/code/voice-logger
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
cp config.example.toml config.toml
```

2. `config.toml` を編集（USB名、保存先、`whisper-cli`、モデル、LLMキー環境変数名）
3. 手動起動（トレイ）

```bash
source /Users/mantaroh/code/voice-logger/.venv/bin/activate
voice-logger-tray --config /Users/mantaroh/code/voice-logger/config.toml
```

4. GUIログイン時にトレイ自動起動

```bash
mkdir -p ~/.config/autostart
cp /Users/mantaroh/code/voice-logger/deploy/autostart/voice-logger.desktop ~/.config/autostart/
```

5. 参考: GUIなしサーバー用途（systemd --user）

```bash
mkdir -p ~/.config/systemd/user
cp /Users/mantaroh/code/voice-logger/deploy/systemd/voice-logger.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now voice-logger.service
```

## セットアップ

```bash
cd /Users/mantaroh/code/voice-logger
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
cp config.example.toml config.toml
```

`config.toml` を編集:

- `[usb].device_name`: USBボリューム名
- `[storage].base_dir`: ローカル保存先
- `[whisper].cli_path`, `[whisper].model_path`
- `[summarizer]`（有効時）
- `[recorder]`（24時間録音を同時実行する場合）

## 実行

トレイ常駐（推奨）:

```bash
voice-logger-tray --config /Users/mantaroh/code/voice-logger/config.toml
```

トレイメニューから以下を操作できます:

- Monitor の一時停止/再開
- 手動 `Run Once`
- `raw/transcripts/summaries` フォルダを開く
- Quit

トレイアイコン状態:

- `NO` (黄): USB未装着
- `00-99` (緑): コピー/文字起こし/要約の進捗率
- `OK` (緑): 今回サイクル完了
- 青: 監視中（処理待ち）
- 灰: 一時停止
- 赤: エラー

単発:

```bash
voice-logger --config /Users/mantaroh/code/voice-logger/config.toml once
```

常駐:

```bash
voice-logger --config /Users/mantaroh/code/voice-logger/config.toml run
```

## 出力

`[storage].base_dir` 配下に作成:

- `raw/`: USBから取り込んだ音声
- `transcripts/`: 文字起こし `.txt`
- `summaries/`: 要約 `.md`（enabled時）
- `.voice_logger_state.json`: 処理済み管理

## 自動起動

### macOS (launchd: メニューバー常駐)

```bash
cp deploy/launchd/com.mantaroh.voice-logger.plist ~/Library/LaunchAgents/
launchctl unload ~/Library/LaunchAgents/com.mantaroh.voice-logger.plist 2>/dev/null || true
launchctl load ~/Library/LaunchAgents/com.mantaroh.voice-logger.plist
launchctl start com.mantaroh.voice-logger
```

### Ubuntu (GUIログイン時にトレイ常駐)

```bash
mkdir -p ~/.config/autostart
cp deploy/autostart/voice-logger.desktop ~/.config/autostart/
```

### Ubuntu (参考: ヘッドレス常駐)

```bash
mkdir -p ~/.config/systemd/user
cp deploy/systemd/voice-logger.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now voice-logger.service
```

## LLM APIキー

`config.toml` の `api_key_env` に合わせて設定:

```bash
export OPENAI_API_KEY=...
export ANTHROPIC_API_KEY=...
export GEMINI_API_KEY=...
export OPENROUTER_API_KEY=...
```

Cloudflare AI Gateway を使う場合は `provider = "cloudflare"` と `endpoint` を OpenAI互換エンドポイントに設定してください。

## 24時間録音（任意）

`config.toml` の `[recorder]` を有効化すると、常駐中に録音コマンドを起動し、終了した場合は自動再起動します。
録音コマンド例は `config.example.toml` を参照してください。

## 注意

- USBファイル削除は「コピー成功後」に実行します。
- 文字起こし/要約が失敗しても、コピー済み音声はローカルに残ります。
- USBファイル取り込みと `recorder` の録音先は別管理です。用途に応じてパスを分けてください。

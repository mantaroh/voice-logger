# voice-logger

日本語README。English version: [README.md](./README.md)

USB録音デバイスを監視し、新規音声をローカル保存してUSB上の元ファイルを削除、`whisper.cpp + kotoba-whisper2.2` で文字起こし、任意でLLM要約する `macOS/Linux` 向けアプリです。`macOSメニューバー / Ubuntuトレイ` の常駐UIで状態確認できます。


## 対応デバイス注記

本プロジェクトは **dexion mz008 64GB** 向けに作成しました。
同様にUSBストレージとして認識される音声レコーダーでも動作する想定です。

## 機能

- USBマウント監視（ラベル名ベース）
- 新規音声のみ取り込み（stateファイルで重複防止）
- 取り込み成功後にUSB元ファイルを削除
- `whisper.cpp` 実行で文字起こし保存
- 要約プロバイダ切り替え（`openai / anthropic / gemini / openrouter / cloudflare`）
- トレイ常駐実行（`voice-logger-tray`）
- トレイメニューの `Settings...` から `config.toml` を編集
- CLI実行 (`run`, `once`)
- 起動時自動実行テンプレート（`launchd`, `autostart .desktop`, `systemd --user`）

## 要件

- Python `3.11+`
- GUIセッション（トレイ表示のため）
- インストールスクリプト用に `git`, `cmake`, `curl`, C++コンパイラ（`clang++` または `g++`）

## macOS / Ubuntu インストールと起動

### macOS

1. セットアップ

```bash
cd /Users/mantaroh/code/voice-logger
./scripts/install_whisper_kotoba.sh
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

トレイメニューの `Settings...` から設定を編集・保存できます。

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

`install_whisper_kotoba.sh` は以下をインストールします:

- `whisper.cpp`（`whisper-cli`）
- `kotoba-whisper-v2.2` モデル（Hugging Face から gguf/ggml を自動判定）

必要なら上書き指定できます:

```bash
KOTOBA_MODEL_URL=\"https://.../model.gguf\" ./scripts/install_whisper_kotoba.sh
VOICE_LOGGER_INSTALL_PREFIX=\"$HOME/.local/share/voice-logger\" ./scripts/install_whisper_kotoba.sh
```

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

## whisper.cpp / kotobaモデルのアンインストール

```bash
cd /Users/mantaroh/code/voice-logger
./scripts/uninstall_whisper_kotoba.sh
```

## 注意

- USBファイル削除は「コピー成功後」に実行します。
- 文字起こし/要約が失敗しても、コピー済み音声はローカルに残ります。

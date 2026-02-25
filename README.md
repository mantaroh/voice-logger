# voice-logger

English README. Japanese version: [README.ja.md](./README.ja.md)

`voice-logger` is a macOS/Linux tray app that monitors a USB voice recorder, copies new audio files to local storage, deletes original files from USB, transcribes with `whisper.cpp + kotoba-whisper2.2`, and optionally summarizes with an LLM.

## Purpose / Motivation

This project is heavily inspired by the **MyLifeBits** vision. By continuously collecting daily voice logs and converting them into searchable, summarizable text, it aims to realize a **modern MyLifeBits** approach made practical by today’s local AI tooling and personal compute resources.
Reference: [MyLifeBits - Wikipedia](https://en.wikipedia.org/wiki/MyLifeBits)

## Device compatibility note

This project was originally built for **dexion mz008 64GB**.
It should also work with other USB-recognizable voice recorders that expose audio files as a mounted volume.

## Features

- USB mount monitoring by device/volume name
- Import only new audio files (state-based deduplication)
- Delete source files from USB after successful local copy
- Transcription via `whisper.cpp`
- Optional summarization with configurable provider:
  - `openai`, `anthropic`, `gemini`, `openrouter`, `cloudflare`
- Daily rollup summary generation per recording date (`daily_YYYY-MM-DD.md`)
- Tray UI for macOS menu bar / Ubuntu system tray
- Settings window from tray menu (`Settings...`) to edit `config.toml`
- CLI mode (`run`, `once`)

## Requirements

- Python `3.11+`
- GUI session (for tray mode)
- `git`, `cmake`, `curl`, C++ compiler (`clang++` or `g++`) for install script

## Install

```bash
cd $HOME/code/voice-logger
./scripts/install_whisper_kotoba.sh
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
cp config.example.toml config.toml
```

Edit `config.toml`:

- `[usb].device_name`
- `[storage].base_dir`
- `[whisper].cli_path`, `[whisper].model_path`
- `[summarizer]` (optional)

`install_whisper_kotoba.sh` installs:

- `whisper.cpp` (`whisper-cli`)
- `kotoba-whisper-v2.2` model (`ggml-kotoba-v2.2-q5_0.bin` from Pomni HF repo)

Override options (if needed):

```bash
KOTOBA_MODEL_URL=\"https://.../model.gguf\" ./scripts/install_whisper_kotoba.sh
VOICE_LOGGER_INSTALL_PREFIX=\"$HOME/.local/share/voice-logger\" ./scripts/install_whisper_kotoba.sh
```

## Run

Tray mode (recommended):

```bash
voice-logger-tray --config $HOME/code/voice-logger/config.toml
```

Open `Settings...` from the tray menu to edit and save runtime configuration.

CLI once:

```bash
voice-logger --config $HOME/code/voice-logger/config.toml once
```

CLI daemon loop:

```bash
voice-logger --config $HOME/code/voice-logger/config.toml run
```

## Tray icon states

- `NO` (yellow): USB not mounted
- `00-99` (green): copy/transcribe/summarize progress percentage
- `OK` (green): cycle completed
- Blue: monitoring/idle
- Gray: paused
- Red: error

## Output

Under `[storage].base_dir`:

- `raw/`
- `transcripts/`
- `summaries/` (if enabled)
  - `daily_YYYY-MM-DD.md` (daily rollup per recording date, if enabled)
- `.voice_logger_state.json`

## Autostart

### macOS (launchd, tray)

```bash
cp $HOME/code/voice-logger/deploy/launchd/com.voice-logger.plist ~/Library/LaunchAgents/
launchctl unload ~/Library/LaunchAgents/com.voice-logger.plist 2>/dev/null || true
launchctl load ~/Library/LaunchAgents/com.voice-logger.plist
launchctl start com.voice-logger
```

### Ubuntu (GUI login, tray)

```bash
mkdir -p ~/.config/autostart
cp $HOME/code/voice-logger/deploy/autostart/voice-logger.desktop ~/.config/autostart/
```

### Ubuntu (optional, headless)

```bash
mkdir -p ~/.config/systemd/user
cp $HOME/code/voice-logger/deploy/systemd/voice-logger.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now voice-logger.service
```

## API keys

Set `api_key_env` to either an environment variable name or a direct API key value. Env var is recommended. Example with env vars:

```bash
export OPENAI_API_KEY=...
export ANTHROPIC_API_KEY=...
export GEMINI_API_KEY=...
export OPENROUTER_API_KEY=...
```

For Cloudflare AI Gateway (compat), use an endpoint ending with `/compat` or `/compat/chat/completions`. If `/compat` is set, the app auto-appends `/chat/completions`. Also set model as OpenAI-compatible id (e.g. `gpt-5-mini-2025-08-07`); for Cloudflare compat the app auto-prefixes `openai/` when missing.

## Uninstall whisper.cpp / kotoba model

```bash
cd $HOME/code/voice-logger
./scripts/uninstall_whisper_kotoba.sh
```

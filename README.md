# voice-logger

English README. Japanese version: [README.ja.md](./README.ja.md)

`voice-logger` is a macOS/Linux tray app that monitors a USB voice recorder, copies new audio files to local storage, deletes original files from USB, transcribes with `whisper.cpp + kotoba-whisper2.2`, and optionally summarizes with an LLM.

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
- Optional always-on recorder command (`[recorder]`, e.g. `ffmpeg`)
- Tray UI for macOS menu bar / Ubuntu system tray
- CLI mode (`run`, `once`)

## Requirements

- Python `3.11+`
- `whisper.cpp` (`whisper-cli`)
- `kotoba-whisper2.2` model file (gguf/bin)
- GUI session (for tray mode)

## Install

```bash
cd /Users/mantaroh/code/voice-logger
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
- `[recorder]` (optional)

## Run

Tray mode (recommended):

```bash
voice-logger-tray --config /Users/mantaroh/code/voice-logger/config.toml
```

CLI once:

```bash
voice-logger --config /Users/mantaroh/code/voice-logger/config.toml once
```

CLI daemon loop:

```bash
voice-logger --config /Users/mantaroh/code/voice-logger/config.toml run
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
- `.voice_logger_state.json`

## Autostart

### macOS (launchd, tray)

```bash
cp /Users/mantaroh/code/voice-logger/deploy/launchd/com.mantaroh.voice-logger.plist ~/Library/LaunchAgents/
launchctl unload ~/Library/LaunchAgents/com.mantaroh.voice-logger.plist 2>/dev/null || true
launchctl load ~/Library/LaunchAgents/com.mantaroh.voice-logger.plist
launchctl start com.mantaroh.voice-logger
```

### Ubuntu (GUI login, tray)

```bash
mkdir -p ~/.config/autostart
cp /Users/mantaroh/code/voice-logger/deploy/autostart/voice-logger.desktop ~/.config/autostart/
```

### Ubuntu (optional, headless)

```bash
mkdir -p ~/.config/systemd/user
cp /Users/mantaroh/code/voice-logger/deploy/systemd/voice-logger.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now voice-logger.service
```

## API keys

Set the env var matching `[summarizer].api_key_env`, for example:

```bash
export OPENAI_API_KEY=...
export ANTHROPIC_API_KEY=...
export GEMINI_API_KEY=...
export OPENROUTER_API_KEY=...
```

For Cloudflare AI Gateway, set `provider = "cloudflare"` and configure an OpenAI-compatible `endpoint`.

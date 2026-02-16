from __future__ import annotations

import os
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .utils import AUDIO_EXTENSIONS_DEFAULT


@dataclass(slots=True)
class AppConfig:
    poll_interval_seconds: int = 10
    log_level: str = "INFO"


@dataclass(slots=True)
class UsbConfig:
    device_name: str
    mount_roots: list[Path]
    source_subdir: str = ""
    audio_extensions: tuple[str, ...] = AUDIO_EXTENSIONS_DEFAULT


@dataclass(slots=True)
class StorageConfig:
    base_dir: Path
    raw_dir_name: str = "raw"
    transcript_dir_name: str = "transcripts"
    summary_dir_name: str = "summaries"
    state_file_name: str = ".voice_logger_state.json"


@dataclass(slots=True)
class WhisperConfig:
    cli_path: Path
    model_path: Path
    language: str = "ja"
    extra_args: list[str] = field(default_factory=list)


@dataclass(slots=True)
class SummarizerConfig:
    enabled: bool = False
    provider: str = ""
    endpoint: str = ""
    model: str = ""
    api_key_env: str = ""
    system_prompt: str = ""


@dataclass(slots=True)
class RecorderConfig:
    enabled: bool = False
    command: list[str] = field(default_factory=list)
    cwd: str = ""


@dataclass(slots=True)
class Config:
    app: AppConfig
    usb: UsbConfig
    storage: StorageConfig
    whisper: WhisperConfig
    summarizer: SummarizerConfig
    recorder: RecorderConfig


def _default_mount_roots() -> list[Path]:
    roots: list[Path] = [Path("/Volumes")]
    user = os.getenv("USER") or os.getenv("LOGNAME") or ""
    if user:
        roots.extend([Path(f"/media/{user}"), Path(f"/run/media/{user}")])
    roots.extend([Path("/mnt"), Path("/media")])
    # preserve order, deduplicate
    seen: set[str] = set()
    unique: list[Path] = []
    for root in roots:
        k = str(root)
        if k not in seen:
            seen.add(k)
            unique.append(root)
    return unique


def _expand_path(path: str) -> Path:
    return Path(path).expanduser().resolve()


def load_config(path: Path) -> Config:
    with path.open("rb") as f:
        data = tomllib.load(f)

    app_data = data.get("app", {})
    usb_data = data.get("usb", {})
    storage_data = data.get("storage", {})
    whisper_data = data.get("whisper", {})
    summarizer_data = data.get("summarizer", {})
    recorder_data = data.get("recorder", {})

    device_name = usb_data.get("device_name", "").strip()
    if not device_name:
        raise ValueError("[usb].device_name is required")

    mount_roots_raw = usb_data.get("mount_roots")
    mount_roots = (
        [_expand_path(p) for p in mount_roots_raw]
        if isinstance(mount_roots_raw, list) and mount_roots_raw
        else _default_mount_roots()
    )

    audio_exts = usb_data.get("audio_extensions", list(AUDIO_EXTENSIONS_DEFAULT))
    if not isinstance(audio_exts, list) or not audio_exts:
        audio_exts = list(AUDIO_EXTENSIONS_DEFAULT)
    normalized_exts = tuple(ext.lower() if ext.startswith(".") else f".{ext.lower()}" for ext in audio_exts)

    storage_base = storage_data.get("base_dir")
    if not storage_base:
        raise ValueError("[storage].base_dir is required")

    whisper_cli = whisper_data.get("cli_path", "").strip()
    whisper_model = whisper_data.get("model_path", "").strip()
    if not whisper_cli or not whisper_model:
        raise ValueError("[whisper].cli_path and [whisper].model_path are required")

    summarizer_enabled = bool(summarizer_data.get("enabled", False))
    summarizer_provider = str(summarizer_data.get("provider", "")).strip().lower()
    summarizer_endpoint = str(summarizer_data.get("endpoint", "")).strip()
    summarizer_model = str(summarizer_data.get("model", "")).strip()
    summarizer_api_env = str(summarizer_data.get("api_key_env", "")).strip()

    if summarizer_enabled and (not summarizer_provider or not summarizer_model or not summarizer_api_env):
        raise ValueError(
            "[summarizer] enabled=true requires provider, model, and api_key_env"
        )

    if summarizer_provider in {"openai", "openrouter", "cloudflare"} and not summarizer_endpoint:
        defaults = {
            "openai": "https://api.openai.com/v1/chat/completions",
            "openrouter": "https://openrouter.ai/api/v1/chat/completions",
            "cloudflare": "",
        }
        summarizer_endpoint = defaults[summarizer_provider]

    cfg = Config(
        app=AppConfig(
            poll_interval_seconds=int(app_data.get("poll_interval_seconds", 10)),
            log_level=str(app_data.get("log_level", "INFO")).upper(),
        ),
        usb=UsbConfig(
            device_name=device_name,
            mount_roots=mount_roots,
            source_subdir=str(usb_data.get("source_subdir", "")).strip(),
            audio_extensions=normalized_exts,
        ),
        storage=StorageConfig(
            base_dir=_expand_path(str(storage_base)),
            raw_dir_name=str(storage_data.get("raw_dir_name", "raw")),
            transcript_dir_name=str(storage_data.get("transcript_dir_name", "transcripts")),
            summary_dir_name=str(storage_data.get("summary_dir_name", "summaries")),
            state_file_name=str(storage_data.get("state_file_name", ".voice_logger_state.json")),
        ),
        whisper=WhisperConfig(
            cli_path=_expand_path(whisper_cli),
            model_path=_expand_path(whisper_model),
            language=str(whisper_data.get("language", "ja")),
            extra_args=list(whisper_data.get("extra_args", [])),
        ),
        summarizer=SummarizerConfig(
            enabled=summarizer_enabled,
            provider=summarizer_provider,
            endpoint=summarizer_endpoint,
            model=summarizer_model,
            api_key_env=summarizer_api_env,
            system_prompt=str(
                summarizer_data.get(
                    "system_prompt",
                    "次の会話ログを要約してください。要点、重要決定、TODO、リスクを箇条書きで出力してください。",
                )
            ),
        ),
        recorder=RecorderConfig(
            enabled=bool(recorder_data.get("enabled", False)),
            command=list(recorder_data.get("command", [])),
            cwd=str(recorder_data.get("cwd", "")).strip(),
        ),
    )

    if cfg.app.poll_interval_seconds < 1:
        raise ValueError("[app].poll_interval_seconds must be >= 1")

    if cfg.recorder.enabled and not cfg.recorder.command:
        raise ValueError("[recorder] enabled=true requires command")

    if sys.platform.startswith("darwin") and Path("/Volumes") not in cfg.usb.mount_roots:
        cfg.usb.mount_roots.insert(0, Path("/Volumes"))

    return cfg

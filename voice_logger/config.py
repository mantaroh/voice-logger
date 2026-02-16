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
class Config:
    app: AppConfig
    usb: UsbConfig
    storage: StorageConfig
    whisper: WhisperConfig
    summarizer: SummarizerConfig


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
    )

    if cfg.app.poll_interval_seconds < 1:
        raise ValueError("[app].poll_interval_seconds must be >= 1")

    if sys.platform.startswith("darwin") and Path("/Volumes") not in cfg.usb.mount_roots:
        cfg.usb.mount_roots.insert(0, Path("/Volumes"))

    return cfg


def _toml_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _toml_string(s: str) -> str:
    return f"\"{_toml_escape(s)}\""


def _toml_str_list(items: list[str]) -> str:
    return "[" + ", ".join(_toml_string(i) for i in items) + "]"


def save_config(path: Path, cfg: Config) -> None:
    path = path.expanduser().resolve()
    lines: list[str] = []

    lines.extend([
        "[app]",
        f"poll_interval_seconds = {cfg.app.poll_interval_seconds}",
        f"log_level = {_toml_string(cfg.app.log_level)}",
        "",
        "[usb]",
        f"device_name = {_toml_string(cfg.usb.device_name)}",
        f"mount_roots = {_toml_str_list([str(p) for p in cfg.usb.mount_roots])}",
        f"source_subdir = {_toml_string(cfg.usb.source_subdir)}",
        f"audio_extensions = {_toml_str_list(list(cfg.usb.audio_extensions))}",
        "",
        "[storage]",
        f"base_dir = {_toml_string(str(cfg.storage.base_dir))}",
        f"raw_dir_name = {_toml_string(cfg.storage.raw_dir_name)}",
        f"transcript_dir_name = {_toml_string(cfg.storage.transcript_dir_name)}",
        f"summary_dir_name = {_toml_string(cfg.storage.summary_dir_name)}",
        f"state_file_name = {_toml_string(cfg.storage.state_file_name)}",
        "",
        "[whisper]",
        f"cli_path = {_toml_string(str(cfg.whisper.cli_path))}",
        f"model_path = {_toml_string(str(cfg.whisper.model_path))}",
        f"language = {_toml_string(cfg.whisper.language)}",
        f"extra_args = {_toml_str_list(cfg.whisper.extra_args)}",
        "",
        "[summarizer]",
        f"enabled = {'true' if cfg.summarizer.enabled else 'false'}",
        f"provider = {_toml_string(cfg.summarizer.provider)}",
        f"model = {_toml_string(cfg.summarizer.model)}",
        f"api_key_env = {_toml_string(cfg.summarizer.api_key_env)}",
        f"endpoint = {_toml_string(cfg.summarizer.endpoint)}",
        f"system_prompt = {_toml_string(cfg.summarizer.system_prompt)}",
        "",
    ])

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")

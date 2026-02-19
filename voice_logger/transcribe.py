from __future__ import annotations

import re
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

from .config import WhisperConfig


def _parse_recording_datetime_from_name(audio_path: Path) -> datetime | None:
    # Example: R2027-01-24-16-22-07.WAV
    m = re.search(r"(\d{4})[-_](\d{2})[-_](\d{2})[-_](\d{2})[-_](\d{2})[-_](\d{2})", audio_path.name)
    if not m:
        return None
    try:
        y, mo, d, h, mi, s = (int(x) for x in m.groups())
        return datetime(y, mo, d, h, mi, s)
    except ValueError:
        return None


def _srt_time_to_seconds(v: str) -> float:
    # HH:MM:SS,mmm
    hh = int(v[0:2])
    mm = int(v[3:5])
    ss = int(v[6:8])
    ms = int(v[9:12])
    return (hh * 3600) + (mm * 60) + ss + (ms / 1000.0)


def _render_srt_block(block: list[str], start_at: datetime) -> str:
    if len(block) < 2 or "-->" not in block[1]:
        return ""
    start_str = block[1].split("-->", 1)[0].strip()
    try:
        offset_seconds = _srt_time_to_seconds(start_str)
    except Exception:
        return ""
    text = " ".join(block[2:]).strip()
    if not text:
        return ""
    dt = start_at + timedelta(seconds=offset_seconds)
    return f"[{dt.strftime('%Y-%m-%d %H:%M:%S')}] {text}"


def _render_timestamped_text_from_srt(srt_path: Path, start_at: datetime) -> str:
    content = srt_path.read_text(encoding="utf-8", errors="ignore")
    out: list[str] = []
    block: list[str] = []
    for raw in content.splitlines():
        line = raw.strip()
        if line:
            block.append(line)
            continue
        if block:
            rendered = _render_srt_block(block, start_at)
            if rendered:
                out.append(rendered)
            block = []
    if block:
        rendered = _render_srt_block(block, start_at)
        if rendered:
            out.append(rendered)
    return "\n".join(out).strip()


def transcribe_with_whisper_cpp(audio_path: Path, output_txt_path: Path, cfg: WhisperConfig) -> str:
    output_txt_path.parent.mkdir(parents=True, exist_ok=True)
    # Keep all dots in basename; only strip trailing ".txt" if present.
    if output_txt_path.suffix.lower() == ".txt":
        output_base = output_txt_path.with_name(output_txt_path.name[:-4])
    else:
        output_base = output_txt_path

    cmd = [
        str(cfg.cli_path),
        "-m",
        str(cfg.model_path),
        "-f",
        str(audio_path),
        "-of",
        str(output_base),
        "-otxt",
        "-osrt",
        "-l",
        cfg.language,
        *cfg.extra_args,
    ]

    proc = subprocess.run(cmd, text=True, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"whisper.cpp failed ({proc.returncode})\\nSTDOUT:\\n{proc.stdout}\\nSTDERR:\\n{proc.stderr}"
        )

    actual_txt = Path(f"{output_base}.txt")
    if not actual_txt.exists():
        raise RuntimeError(f"whisper.cpp completed but output not found: {actual_txt}")

    if actual_txt != output_txt_path:
        actual_txt.replace(output_txt_path)

    base_dt = _parse_recording_datetime_from_name(audio_path)
    srt_path = Path(f"{output_base}.srt")
    if base_dt and srt_path.exists():
        ts_text = _render_timestamped_text_from_srt(srt_path, base_dt)
        if ts_text:
            output_txt_path.write_text(ts_text, encoding="utf-8")
            return ts_text

    plain = output_txt_path.read_text(encoding="utf-8", errors="ignore").strip()
    if base_dt and plain:
        prefix = base_dt.strftime("%Y-%m-%d %H:%M:%S")
        lines = [ln.strip() for ln in plain.splitlines() if ln.strip()]
        with_ts = "\n".join(f"[{prefix}] {ln}" for ln in lines)
        output_txt_path.write_text(with_ts, encoding="utf-8")
        return with_ts

    return plain

from __future__ import annotations

import subprocess
from pathlib import Path

from .config import WhisperConfig


def transcribe_with_whisper_cpp(audio_path: Path, output_txt_path: Path, cfg: WhisperConfig) -> str:
    output_txt_path.parent.mkdir(parents=True, exist_ok=True)
    output_base = output_txt_path.with_suffix("")

    cmd = [
        str(cfg.cli_path),
        "-m",
        str(cfg.model_path),
        "-f",
        str(audio_path),
        "-of",
        str(output_base),
        "-otxt",
        "-l",
        cfg.language,
        *cfg.extra_args,
    ]

    proc = subprocess.run(cmd, text=True, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"whisper.cpp failed ({proc.returncode})\\nSTDOUT:\\n{proc.stdout}\\nSTDERR:\\n{proc.stderr}"
        )

    actual_txt = output_base.with_suffix(".txt")
    if not actual_txt.exists():
        raise RuntimeError(f"whisper.cpp completed but output not found: {actual_txt}")

    if actual_txt != output_txt_path:
        actual_txt.replace(output_txt_path)

    return output_txt_path.read_text(encoding="utf-8", errors="ignore").strip()

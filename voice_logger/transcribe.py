from __future__ import annotations

import subprocess
from pathlib import Path

from .config import WhisperConfig


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

    return output_txt_path.read_text(encoding="utf-8", errors="ignore").strip()

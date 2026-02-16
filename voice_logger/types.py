from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class AudioTask:
    source_path: Path
    source_mount: Path
    relative_path: str
    copied_path: Path
    transcript_path: Path
    summary_path: Path
    key: str

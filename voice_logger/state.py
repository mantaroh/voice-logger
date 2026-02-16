from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class ProcessedItem:
    key: str
    source_relative_path: str
    source_size: int
    source_mtime_ns: int
    copied_to: str
    transcript_path: str
    summary_path: str


class StateStore:
    def __init__(self, path: Path):
        self.path = path
        self._state: dict[str, ProcessedItem] = {}

    def load(self) -> None:
        if not self.path.exists():
            self._state = {}
            return
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        items = raw.get("processed", {}) if isinstance(raw, dict) else {}
        parsed: dict[str, ProcessedItem] = {}
        for k, v in items.items():
            if not isinstance(v, dict):
                continue
            parsed[k] = ProcessedItem(
                key=k,
                source_relative_path=str(v.get("source_relative_path", "")),
                source_size=int(v.get("source_size", 0)),
                source_mtime_ns=int(v.get("source_mtime_ns", 0)),
                copied_to=str(v.get("copied_to", "")),
                transcript_path=str(v.get("transcript_path", "")),
                summary_path=str(v.get("summary_path", "")),
            )
        self._state = parsed

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        serialized = {
            "processed": {
                k: {
                    "source_relative_path": item.source_relative_path,
                    "source_size": item.source_size,
                    "source_mtime_ns": item.source_mtime_ns,
                    "copied_to": item.copied_to,
                    "transcript_path": item.transcript_path,
                    "summary_path": item.summary_path,
                }
                for k, item in self._state.items()
            }
        }
        self.path.write_text(json.dumps(serialized, indent=2, ensure_ascii=False), encoding="utf-8")

    def is_processed(self, key: str) -> bool:
        return key in self._state

    def mark_processed(self, item: ProcessedItem) -> None:
        self._state[item.key] = item

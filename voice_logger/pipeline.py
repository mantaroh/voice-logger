from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from .config import Config
from .state import ProcessedItem, StateStore
from .summarizer import summarize_text
from .transcribe import transcribe_with_whisper_cpp
from .types import AudioTask
from .usb import collect_audio_files, find_usb_mount

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class RunResult:
    scanned: int = 0
    processed: int = 0
    failed: int = 0


@dataclass(slots=True)
class ProgressEvent:
    state: str
    message: str
    percent: int = -1
    total: int = 0
    current: int = 0


ProgressCallback = Callable[[ProgressEvent], None]


def _to_key(source_path: Path, mount: Path) -> str:
    st = source_path.stat()
    rel = source_path.relative_to(mount)
    return f"{rel}|{st.st_size}|{st.st_mtime_ns}"


def _build_task(cfg: Config, source_path: Path, mount: Path, key: str) -> AudioTask:
    rel = source_path.relative_to(mount)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_rel = str(rel).replace("/", "__")

    raw_dir = cfg.storage.base_dir / cfg.storage.raw_dir_name
    transcript_dir = cfg.storage.base_dir / cfg.storage.transcript_dir_name
    summary_dir = cfg.storage.base_dir / cfg.storage.summary_dir_name
    raw_dir.mkdir(parents=True, exist_ok=True)
    transcript_dir.mkdir(parents=True, exist_ok=True)
    summary_dir.mkdir(parents=True, exist_ok=True)

    copied_path = raw_dir / f"{ts}_{safe_rel}"
    stem = copied_path.stem
    transcript_path = transcript_dir / f"{stem}.txt"
    summary_path = summary_dir / f"{stem}.md"

    return AudioTask(
        source_path=source_path,
        source_mount=mount,
        relative_path=str(rel),
        copied_path=copied_path,
        transcript_path=transcript_path,
        summary_path=summary_path,
        key=key,
    )


def _emit(cb: ProgressCallback | None, event: ProgressEvent) -> None:
    if cb is not None:
        cb(event)


def run_once(cfg: Config, state: StateStore, progress_cb: ProgressCallback | None = None) -> RunResult:
    result = RunResult()
    mount = find_usb_mount(cfg.usb.device_name, cfg.usb.mount_roots)
    if not mount:
        LOGGER.debug("USB device not found: %s", cfg.usb.device_name)
        _emit(progress_cb, ProgressEvent(state="usb_missing", message="USB not mounted", percent=-1))
        return result

    LOGGER.info("USB mounted: %s", mount)
    audio_files = collect_audio_files(mount, cfg.usb.source_subdir, cfg.usb.audio_extensions)
    result.scanned = len(audio_files)
    _emit(progress_cb, ProgressEvent(state="scan_done", message=f"scanned={result.scanned}", percent=0, total=result.scanned, current=0))

    pending: list[Path] = []
    for source in audio_files:
        try:
            key = _to_key(source, mount)
            if not state.is_processed(key):
                pending.append(source)
        except Exception:
            LOGGER.exception("Failed to inspect file: %s", source)
            result.failed += 1

    total_pending = len(pending)
    if total_pending == 0:
        _emit(progress_cb, ProgressEvent(state="complete", message="No new audio", percent=100, total=0, current=0))
        return result

    for idx, source in enumerate(pending, start=1):
        try:
            key = _to_key(source, mount)
            task = _build_task(cfg, source, mount, key)
            LOGGER.info("Processing: %s", task.relative_path)
            base = int(((idx - 1) / total_pending) * 100)
            _emit(
                progress_cb,
                ProgressEvent(
                    state="processing",
                    message=f"[{idx}/{total_pending}] copy {task.relative_path}",
                    percent=base,
                    total=total_pending,
                    current=idx,
                ),
            )

            task.copied_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(task.source_path, task.copied_path)
            task.source_path.unlink()

            transcribe_pct = min(99, int((((idx - 1) + 0.3) / total_pending) * 100))
            _emit(
                progress_cb,
                ProgressEvent(
                    state="processing",
                    message=f"[{idx}/{total_pending}] transcribe {task.relative_path}",
                    percent=transcribe_pct,
                    total=total_pending,
                    current=idx,
                ),
            )
            transcript = transcribe_with_whisper_cpp(task.copied_path, task.transcript_path, cfg.whisper)

            summary_path_str = ""
            if cfg.summarizer.enabled and transcript:
                summary_pct = min(99, int((((idx - 1) + 0.8) / total_pending) * 100))
                _emit(
                    progress_cb,
                    ProgressEvent(
                        state="processing",
                        message=f"[{idx}/{total_pending}] summarize {task.relative_path}",
                        percent=summary_pct,
                        total=total_pending,
                        current=idx,
                    ),
                )
                try:
                    summary = summarize_text(transcript, cfg.summarizer)
                    task.summary_path.write_text(summary, encoding="utf-8")
                    summary_path_str = str(task.summary_path)
                except Exception as e:
                    LOGGER.warning("Summary failed for %s: %s", task.relative_path, e)
                    task.summary_path.write_text(f"Summary failed: {e}\n", encoding="utf-8")
                    summary_path_str = str(task.summary_path)

            st = source.stat() if source.exists() else task.copied_path.stat()
            state.mark_processed(
                ProcessedItem(
                    key=key,
                    source_relative_path=task.relative_path,
                    source_size=st.st_size,
                    source_mtime_ns=st.st_mtime_ns,
                    copied_to=str(task.copied_path),
                    transcript_path=str(task.transcript_path),
                    summary_path=summary_path_str,
                )
            )
            state.save()
            result.processed += 1
            done_pct = int((idx / total_pending) * 100)
            _emit(
                progress_cb,
                ProgressEvent(
                    state="processing",
                    message=f"[{idx}/{total_pending}] done {task.relative_path}",
                    percent=done_pct,
                    total=total_pending,
                    current=idx,
                ),
            )
        except Exception:
            LOGGER.exception("Failed processing file: %s", source)
            result.failed += 1
            _emit(
                progress_cb,
                ProgressEvent(
                    state="error",
                    message=f"Failed: {source.name}",
                    percent=min(99, int((idx / total_pending) * 100)),
                    total=total_pending,
                    current=idx,
                ),
            )

    _emit(
        progress_cb,
        ProgressEvent(
            state="complete",
            message=f"Complete: processed={result.processed} failed={result.failed}",
            percent=100,
            total=total_pending,
            current=total_pending,
        ),
    )
    return result

from __future__ import annotations

import logging
import re
import subprocess
import tempfile
import wave
from array import array
from datetime import datetime, timedelta
from pathlib import Path

from .config import WhisperConfig

LOGGER = logging.getLogger(__name__)
_SRT_RANGE_RE = re.compile(
    r"^(\d{2}:\d{2}:\d{2},\d{3})\s+-->\s+(\d{2}:\d{2}:\d{2},\d{3})(?:\s+.*)?$"
)


def _parse_recording_datetime_from_name(audio_path: Path) -> datetime | None:
    m = re.search(r"(\d{4})[-_](\d{2})[-_](\d{2})[-_](\d{2})[-_](\d{2})[-_](\d{2})", audio_path.name)
    if not m:
        return None
    try:
        y, mo, d, h, mi, s = (int(x) for x in m.groups())
        return datetime(y, mo, d, h, mi, s)
    except ValueError:
        return None


def _srt_time_to_seconds(v: str) -> float:
    hh = int(v[0:2])
    mm = int(v[3:5])
    ss = int(v[6:8])
    ms = int(v[9:12])
    return (hh * 3600) + (mm * 60) + ss + (ms / 1000.0)


def _seconds_to_hms_ms(sec: float) -> str:
    total_ms = max(0, int(round(sec * 1000.0)))
    hh = total_ms // 3_600_000
    rem = total_ms % 3_600_000
    mm = rem // 60_000
    rem = rem % 60_000
    ss = rem // 1000
    ms = rem % 1000
    return f"{hh:02}:{mm:02}:{ss:02}.{ms:03}"


def _to_timestamp(sec: float, base_dt: datetime | None) -> str:
    if base_dt is None:
        return _seconds_to_hms_ms(sec)
    dt = base_dt + timedelta(seconds=sec)
    return dt.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def _run_cmd(cmd: list[str], context: str) -> str:
    proc = subprocess.run(cmd, text=True, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(f"{context} failed ({proc.returncode})\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")
    return proc.stdout


def _probe_duration_seconds(audio_path: Path) -> float:
    out = _run_cmd(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(audio_path),
        ],
        "ffprobe",
    ).strip()
    try:
        return max(0.0, float(out))
    except ValueError as e:
        raise RuntimeError(f"Invalid ffprobe duration output: {out}") from e


def _prepare_audio(audio_path: Path, prepared_path: Path, cfg: WhisperConfig) -> None:
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(audio_path)]
    if cfg.enable_denoise and cfg.denoise_filter:
        cmd.extend(["-af", cfg.denoise_filter])
    cmd.extend(["-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(prepared_path)])
    _run_cmd(cmd, "ffmpeg preprocess")


def _read_wav_mono_16k_for_vad(prepared_audio_path: Path):
    import torch

    with wave.open(str(prepared_audio_path), "rb") as wf:
        channels = wf.getnchannels()
        sample_width = wf.getsampwidth()
        sample_rate = wf.getframerate()
        frames = wf.readframes(wf.getnframes())

    if sample_width != 2:
        raise RuntimeError(f"Unsupported wav sample width for VAD: {sample_width * 8}bit")
    if sample_rate != 16000:
        raise RuntimeError(f"Unexpected wav sample rate for VAD: {sample_rate}")

    pcm = array("h")
    pcm.frombytes(frames)
    if channels > 1:
        pcm = array("h", pcm[::channels])
    if not pcm:
        return torch.zeros(0, dtype=torch.float32)
    scale = 1.0 / 32768.0
    return torch.tensor([x * scale for x in pcm], dtype=torch.float32)


def _detect_vad_segments(prepared_audio_path: Path, duration: float, cfg: WhisperConfig) -> list[tuple[float, float]]:
    if not cfg.enable_vad:
        return [(0.0, duration)]
    try:
        from silero_vad import get_speech_timestamps, load_silero_vad  # type: ignore
    except Exception as e:
        LOGGER.warning(
            "Silero VAD unavailable; fallback to full audio (%s). "
            "Install dependency in venv (pip install -e .) and ensure Python 3.11-3.13.",
            e,
        )
        return [(0.0, duration)]

    wav = _read_wav_mono_16k_for_vad(prepared_audio_path)
    model = load_silero_vad()
    timestamps = get_speech_timestamps(
        wav,
        model,
        sampling_rate=16000,
        threshold=cfg.vad_threshold,
        min_silence_duration_ms=cfg.vad_min_silence_duration_ms,
        speech_pad_ms=int(cfg.vad_padding_seconds * 1000),
        max_speech_duration_s=cfg.vad_max_speech_duration_seconds,
    )

    segments: list[tuple[float, float]] = []
    for item in timestamps:
        start = max(0.0, float(item["start"]) / 16000.0)
        end = min(duration, float(item["end"]) / 16000.0)
        if end > start:
            segments.append((start, end))
    return segments


def _split_by_max_chunk(segments: list[tuple[float, float]], max_chunk_seconds: float) -> list[tuple[float, float]]:
    chunks: list[tuple[float, float]] = []
    for start, end in segments:
        cur = start
        while cur < end:
            nxt = min(cur + max_chunk_seconds, end)
            if nxt - cur > 0.01:
                chunks.append((cur, nxt))
            cur = nxt
    return chunks


def _extract_chunk(prepared_audio_path: Path, start: float, end: float, out_path: Path) -> None:
    duration = max(0.01, end - start)
    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(prepared_audio_path),
        "-ss",
        f"{start:.3f}",
        "-t",
        f"{duration:.3f}",
        "-ac",
        "1",
        "-ar",
        "16000",
        str(out_path),
    ]
    _run_cmd(cmd, "ffmpeg chunk extract")


def _parse_srt_segments(srt_path: Path) -> list[tuple[float, float, str]]:
    content = srt_path.read_text(encoding="utf-8", errors="ignore")
    lines = content.splitlines()
    out: list[tuple[float, float, str]] = []
    block: list[str] = []
    for raw in lines + [""]:
        line = raw.strip()
        if line:
            block.append(line)
            continue
        if len(block) >= 2:
            m = _SRT_RANGE_RE.match(block[1])
            if m:
                start = _srt_time_to_seconds(m.group(1))
                end = _srt_time_to_seconds(m.group(2))
                text = " ".join(x for x in block[2:] if x).strip()
                if text and end > start:
                    out.append((start, end, text))
        block = []
    return out


def _run_whisper_for_chunk(chunk_path: Path, output_base: Path, cfg: WhisperConfig) -> tuple[list[tuple[float, float, str]], str]:
    cmd = [
        str(cfg.cli_path),
        "-m",
        str(cfg.model_path),
        "-f",
        str(chunk_path),
        "-of",
        str(output_base),
        "-otxt",
        "-osrt",
        "-l",
        cfg.language,
        *cfg.extra_args,
    ]
    _run_cmd(cmd, "whisper.cpp")
    srt_path = Path(f"{output_base}.srt")
    txt_path = Path(f"{output_base}.txt")
    segments: list[tuple[float, float, str]] = []
    if srt_path.exists():
        segments = _parse_srt_segments(srt_path)
    plain = txt_path.read_text(encoding="utf-8", errors="ignore").strip() if txt_path.exists() else ""
    return segments, plain


def _transcribe_whole_file(audio_path: Path, output_txt_path: Path, cfg: WhisperConfig) -> str:
    if output_txt_path.suffix.lower() == ".txt":
        output_base = output_txt_path.with_name(output_txt_path.name[:-4])
    else:
        output_base = output_txt_path

    segments, plain = _run_whisper_for_chunk(audio_path, output_base, cfg)
    base_dt = _parse_recording_datetime_from_name(audio_path)
    if segments:
        lines = []
        for start, end, text in segments:
            ts_start = _to_timestamp(start, base_dt)
            ts_end = _to_timestamp(end, base_dt)
            lines.append(f"[{ts_start} --> {ts_end}] {text}")
        rendered = "\n".join(lines).strip()
        output_txt_path.write_text(rendered, encoding="utf-8")
        return rendered

    if base_dt and plain:
        prefix = _to_timestamp(0.0, base_dt)
        lines = [ln.strip() for ln in plain.splitlines() if ln.strip()]
        with_ts = "\n".join(f"[{prefix}] {ln}" for ln in lines)
        output_txt_path.write_text(with_ts, encoding="utf-8")
        return with_ts
    output_txt_path.write_text(plain, encoding="utf-8")
    return plain


def transcribe_with_whisper_cpp(audio_path: Path, output_txt_path: Path, cfg: WhisperConfig) -> str:
    output_txt_path.parent.mkdir(parents=True, exist_ok=True)
    base_dt = _parse_recording_datetime_from_name(audio_path)

    try:
        with tempfile.TemporaryDirectory(prefix="voice_logger_asr_") as tmp:
            work = Path(tmp)
            prepared = work / "prepared.wav"
            _prepare_audio(audio_path, prepared, cfg)
            total_duration = _probe_duration_seconds(prepared)
            if total_duration <= 0:
                output_txt_path.write_text("", encoding="utf-8")
                return ""

            segments = _detect_vad_segments(prepared, total_duration, cfg)
            if not segments:
                output_txt_path.write_text("", encoding="utf-8")
                return ""
            chunks = _split_by_max_chunk(segments, cfg.max_chunk_seconds)
            if not chunks:
                output_txt_path.write_text("", encoding="utf-8")
                return ""

            rendered_lines: list[tuple[float, str]] = []
            for idx, (global_start, global_end) in enumerate(chunks, start=1):
                chunk_path = work / f"chunk_{idx:04}.wav"
                out_base = work / f"chunk_{idx:04}_whisper"
                _extract_chunk(prepared, global_start, global_end, chunk_path)
                local_segments, plain = _run_whisper_for_chunk(chunk_path, out_base, cfg)
                if local_segments:
                    for local_start, local_end, text in local_segments:
                        abs_start = global_start + local_start
                        abs_end = min(total_duration, global_start + local_end)
                        ts_start = _to_timestamp(abs_start, base_dt)
                        ts_end = _to_timestamp(abs_end, base_dt)
                        rendered_lines.append((abs_start, f"[{ts_start} --> {ts_end}] {text}"))
                    continue

                if plain:
                    ts_start = _to_timestamp(global_start, base_dt)
                    ts_end = _to_timestamp(global_end, base_dt)
                    rendered_lines.append((global_start, f"[{ts_start} --> {ts_end}] {plain}"))

            rendered_lines.sort(key=lambda x: x[0])
            rendered = "\n".join(line for _, line in rendered_lines).strip()
            output_txt_path.write_text(rendered, encoding="utf-8")
            return rendered
    except FileNotFoundError as e:
        LOGGER.warning("ffmpeg/ffprobe not found; fallback to single-pass whisper: %s", e)
        return _transcribe_whole_file(audio_path, output_txt_path, cfg)
    except Exception as e:
        LOGGER.warning("VAD/chunk pipeline failed; fallback to single-pass whisper: %s", e)
        return _transcribe_whole_file(audio_path, output_txt_path, cfg)

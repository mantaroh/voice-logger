from __future__ import annotations

import argparse
import logging
import signal
import subprocess
import sys
import time
from pathlib import Path

from .config import load_config
from .pipeline import run_once
from .state import StateStore


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="USB voice logger daemon")
    parser.add_argument("--config", required=True, help="Path to config.toml")
    parser.add_argument("command", choices=["run", "once"], nargs="?", default="run")
    return parser


def run_loop(config_path: Path) -> int:
    cfg = load_config(config_path)
    _setup_logging(cfg.app.log_level)

    state_path = cfg.storage.base_dir / cfg.storage.state_file_name
    state = StateStore(state_path)
    state.load()

    stop = {"value": False}
    recorder_proc: subprocess.Popen | None = None

    def handle_signal(signum: int, _frame) -> None:
        logging.getLogger(__name__).info("Received signal %s, shutting down", signum)
        stop["value"] = True

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    if cfg.recorder.enabled:
        recorder_proc = subprocess.Popen(
            cfg.recorder.command,
            cwd=cfg.recorder.cwd or None,
        )
        logging.getLogger(__name__).info("Recorder started: pid=%s", recorder_proc.pid)

    while not stop["value"]:
        if cfg.recorder.enabled and recorder_proc is not None and recorder_proc.poll() is not None:
            logging.getLogger(__name__).warning("Recorder exited. restarting...")
            recorder_proc = subprocess.Popen(
                cfg.recorder.command,
                cwd=cfg.recorder.cwd or None,
            )
            logging.getLogger(__name__).info("Recorder restarted: pid=%s", recorder_proc.pid)

        result = run_once(cfg, state)
        logging.getLogger(__name__).debug(
            "Scan finished: scanned=%s processed=%s failed=%s",
            result.scanned,
            result.processed,
            result.failed,
        )
        time.sleep(cfg.app.poll_interval_seconds)

    if recorder_proc is not None and recorder_proc.poll() is None:
        recorder_proc.terminate()
        try:
            recorder_proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            recorder_proc.kill()

    return 0


def run_once_command(config_path: Path) -> int:
    cfg = load_config(config_path)
    _setup_logging(cfg.app.log_level)

    state_path = cfg.storage.base_dir / cfg.storage.state_file_name
    state = StateStore(state_path)
    state.load()

    result = run_once(cfg, state)
    logging.getLogger(__name__).info(
        "Done: scanned=%s processed=%s failed=%s",
        result.scanned,
        result.processed,
        result.failed,
    )
    return 0 if result.failed == 0 else 1


def main() -> int:
    args = build_parser().parse_args()
    config_path = Path(args.config).expanduser().resolve()

    if not config_path.exists():
        print(f"config not found: {config_path}", file=sys.stderr)
        return 2

    if args.command == "once":
        return run_once_command(config_path)

    return run_loop(config_path)


if __name__ == "__main__":
    raise SystemExit(main())

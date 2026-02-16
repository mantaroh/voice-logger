from __future__ import annotations

import argparse
import logging
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

try:
    from PySide6.QtCore import QObject, QThread, Qt, QUrl, Signal
    from PySide6.QtGui import QAction, QColor, QDesktopServices, QFont, QIcon, QPainter, QPixmap
    from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon
except ModuleNotFoundError:
    print("PySide6 is required for tray mode. Install with: pip install -e .", file=sys.stderr)
    raise SystemExit(3)

from .config import Config, load_config
from .pipeline import ProgressEvent, run_once
from .state import StateStore

LOGGER = logging.getLogger(__name__)


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


class MonitorWorker(QThread):
    status_changed = Signal(str, str, int)

    def __init__(self, config_path: Path):
        super().__init__()
        self._config_path = config_path
        self._stop_event = threading.Event()
        self._run_once_event = threading.Event()
        self._lock = threading.Lock()
        self._active = True
        self._cfg: Config | None = None
        self._state: StateStore | None = None
        self._recorder_proc: subprocess.Popen | None = None

    def set_active(self, active: bool) -> None:
        with self._lock:
            self._active = active
        self.status_changed.emit(
            "paused" if not active else "running",
            "monitor active" if active else "monitor paused",
            -1,
        )

    def is_active(self) -> bool:
        with self._lock:
            return self._active

    def trigger_once(self) -> None:
        self._run_once_event.set()

    def request_stop(self) -> None:
        self._stop_event.set()

    def _start_recorder(self) -> None:
        if not self._cfg or not self._cfg.recorder.enabled:
            return
        if self._recorder_proc is not None and self._recorder_proc.poll() is None:
            return
        self._recorder_proc = subprocess.Popen(
            self._cfg.recorder.command,
            cwd=self._cfg.recorder.cwd or None,
        )
        LOGGER.info("Recorder started: pid=%s", self._recorder_proc.pid)

    def _stop_recorder(self) -> None:
        if self._recorder_proc is None:
            return
        if self._recorder_proc.poll() is not None:
            return
        self._recorder_proc.terminate()
        try:
            self._recorder_proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self._recorder_proc.kill()
        LOGGER.info("Recorder stopped")

    def _ensure_loaded(self) -> None:
        if self._cfg is not None and self._state is not None:
            return
        self._cfg = load_config(self._config_path)
        state_path = self._cfg.storage.base_dir / self._cfg.storage.state_file_name
        self._state = StateStore(state_path)
        self._state.load()

    def run(self) -> None:
        try:
            self._ensure_loaded()
        except Exception as e:
            LOGGER.exception("Failed to load config")
            self.status_changed.emit("error", f"config load error: {e}", -1)
            return

        assert self._cfg is not None
        assert self._state is not None

        self.status_changed.emit("running", "monitor started", -1)

        while not self._stop_event.is_set():
            active = self.is_active()
            run_now = self._run_once_event.is_set()

            if not active and not run_now:
                self._stop_recorder()
                if self._stop_event.wait(timeout=1.0):
                    break
                continue

            try:
                self._start_recorder()
                if self._recorder_proc is not None and self._recorder_proc.poll() is not None:
                    LOGGER.warning("Recorder exited. restarting")
                    self._start_recorder()

                def on_progress(event: ProgressEvent) -> None:
                    self.status_changed.emit(event.state, event.message, event.percent)

                result = run_once(self._cfg, self._state, progress_cb=on_progress)
                msg = f"scanned={result.scanned} processed={result.processed} failed={result.failed}"
                if result.failed > 0:
                    self.status_changed.emit("error", msg, -1)
                elif result.processed > 0:
                    self.status_changed.emit("active", msg, 100)
                else:
                    self.status_changed.emit("running", msg, -1)
            except Exception as e:
                LOGGER.exception("Monitor cycle failed")
                self.status_changed.emit("error", str(e), -1)

            self._run_once_event.clear()

            if run_now and not active:
                continue

            if self._stop_event.wait(timeout=self._cfg.app.poll_interval_seconds):
                break

        self._stop_recorder()
        self.status_changed.emit("paused", "monitor stopped", -1)


class TrayApp(QObject):
    def __init__(self, config_path: Path):
        super().__init__()
        self._config_path = config_path
        self._cfg = load_config(config_path)
        _setup_logging(self._cfg.app.log_level)

        self._tray = QSystemTrayIcon(self)
        self._icon_idle = self._make_icon("#6b7280")
        self._icon_running = self._make_icon("#0284c7")
        self._icon_active = self._make_icon("#16a34a")
        self._icon_error = self._make_icon("#dc2626")
        self._icon_usb_missing = self._make_icon("#f59e0b", "NO")
        self._icon_complete = self._make_icon("#16a34a", "OK")

        self._menu = QMenu()

        self._status_action = QAction("Status: starting", self._menu)
        self._status_action.setEnabled(False)
        self._menu.addAction(self._status_action)
        self._menu.addSeparator()

        self._toggle_action = QAction("Pause Monitor", self._menu)
        self._toggle_action.triggered.connect(self._toggle_monitor)
        self._menu.addAction(self._toggle_action)

        self._run_once_action = QAction("Run Once Now", self._menu)
        self._run_once_action.triggered.connect(self._run_once_now)
        self._menu.addAction(self._run_once_action)

        self._menu.addSeparator()

        self._open_raw_action = QAction("Open Raw Folder", self._menu)
        self._open_raw_action.triggered.connect(self._open_raw)
        self._menu.addAction(self._open_raw_action)

        self._open_transcript_action = QAction("Open Transcripts Folder", self._menu)
        self._open_transcript_action.triggered.connect(self._open_transcripts)
        self._menu.addAction(self._open_transcript_action)

        self._open_summary_action = QAction("Open Summaries Folder", self._menu)
        self._open_summary_action.triggered.connect(self._open_summaries)
        self._menu.addAction(self._open_summary_action)

        self._menu.addSeparator()

        self._quit_action = QAction("Quit", self._menu)
        self._quit_action.triggered.connect(self.quit)
        self._menu.addAction(self._quit_action)

        self._tray.setContextMenu(self._menu)
        self._tray.setIcon(self._icon_running)
        self._tray.setToolTip("voice-logger")
        self._tray.show()

        self._worker = MonitorWorker(config_path)
        self._worker.status_changed.connect(self._on_status_changed)
        self._worker.start()

    def _make_icon(self, color_hex: str, badge_text: str = "") -> QIcon:
        pix = QPixmap(32, 32)
        pix.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor(color_hex))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(4, 4, 24, 24)
        if badge_text:
            font = QFont("Sans Serif", 8)
            font.setBold(True)
            painter.setFont(font)
            painter.setPen(Qt.GlobalColor.white)
            painter.drawText(pix.rect(), Qt.AlignmentFlag.AlignCenter, badge_text)
        painter.end()
        return QIcon(pix)

    def _progress_icon(self, percent: int) -> QIcon:
        pct = max(0, min(99, percent))
        badge = "99+" if pct >= 99 else f"{pct:02d}"
        return self._make_icon("#16a34a", badge)

    def _on_status_changed(self, state: str, message: str, percent: int) -> None:
        if state == "error":
            self._tray.setIcon(self._icon_error)
        elif state == "usb_missing":
            self._tray.setIcon(self._icon_usb_missing)
        elif state == "complete":
            self._tray.setIcon(self._icon_complete)
        elif state == "processing":
            self._tray.setIcon(self._progress_icon(percent if percent >= 0 else 0))
        elif state == "active":
            self._tray.setIcon(self._icon_active)
        elif state == "paused":
            self._tray.setIcon(self._icon_idle)
        else:
            self._tray.setIcon(self._icon_running)

        pct_text = f" | {percent}%" if percent >= 0 else ""
        text = f"Status: {state}{pct_text} | {message}"
        self._status_action.setText(text)
        self._tray.setToolTip(text)

    def _toggle_monitor(self) -> None:
        current = self._worker.is_active()
        self._worker.set_active(not current)
        self._toggle_action.setText("Resume Monitor" if current else "Pause Monitor")

    def _run_once_now(self) -> None:
        self._worker.trigger_once()

    def _open_folder(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _open_raw(self) -> None:
        self._open_folder(self._cfg.storage.base_dir / self._cfg.storage.raw_dir_name)

    def _open_transcripts(self) -> None:
        self._open_folder(self._cfg.storage.base_dir / self._cfg.storage.transcript_dir_name)

    def _open_summaries(self) -> None:
        self._open_folder(self._cfg.storage.base_dir / self._cfg.storage.summary_dir_name)

    def quit(self) -> None:
        self._worker.request_stop()
        self._worker.wait(15000)
        self._tray.hide()
        QApplication.instance().quit()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Voice Logger tray app")
    parser.add_argument("--config", required=True, help="Path to config.toml")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    config_path = Path(args.config).expanduser().resolve()

    if not config_path.exists():
        print(f"config not found: {config_path}", file=sys.stderr)
        return 2

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    if not QSystemTrayIcon.isSystemTrayAvailable():
        print("System tray is not available in this session", file=sys.stderr)
        return 1

    tray = TrayApp(config_path)

    def handle_signal(signum: int, _frame) -> None:
        LOGGER.info("Received signal=%s, quitting tray", signum)
        tray.quit()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

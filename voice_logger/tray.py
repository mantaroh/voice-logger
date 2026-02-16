from __future__ import annotations

import argparse
import copy
import logging
import signal
import sys
import threading
import time
from pathlib import Path

try:
    from PySide6.QtCore import QObject, QThread, Qt, QUrl, Signal
    from PySide6.QtGui import QAction, QColor, QDesktopServices, QFont, QIcon, QPainter, QPixmap
    from PySide6.QtWidgets import (
        QApplication,
        QCheckBox,
        QDialog,
        QDialogButtonBox,
        QFormLayout,
        QLineEdit,
        QMenu,
        QMessageBox,
        QSpinBox,
        QSystemTrayIcon,
        QTextEdit,
        QVBoxLayout,
    )
except ModuleNotFoundError:
    print("PySide6 is required for tray mode. Install with: pip install -e .", file=sys.stderr)
    raise SystemExit(3)

from .config import Config, load_config, save_config
from .pipeline import ProgressEvent, run_once
from .state import StateStore

LOGGER = logging.getLogger(__name__)


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


class SettingsDialog(QDialog):
    def __init__(self, cfg: Config, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Voice Logger Settings")
        self.resize(680, 560)
        self._cfg = cfg

        root = QVBoxLayout(self)
        form = QFormLayout()
        root.addLayout(form)

        self.poll_interval = QSpinBox(self)
        self.poll_interval.setRange(1, 3600)
        self.poll_interval.setValue(cfg.app.poll_interval_seconds)
        form.addRow("Poll interval (sec)", self.poll_interval)

        self.log_level = QLineEdit(cfg.app.log_level, self)
        form.addRow("Log level", self.log_level)

        self.usb_device_name = QLineEdit(cfg.usb.device_name, self)
        form.addRow("USB device name", self.usb_device_name)

        self.usb_mount_roots = QLineEdit(",".join(str(p) for p in cfg.usb.mount_roots), self)
        form.addRow("Mount roots (comma)", self.usb_mount_roots)

        self.usb_source_subdir = QLineEdit(cfg.usb.source_subdir, self)
        form.addRow("USB source subdir", self.usb_source_subdir)

        self.usb_audio_ext = QLineEdit(",".join(cfg.usb.audio_extensions), self)
        form.addRow("Audio extensions (comma)", self.usb_audio_ext)

        self.storage_base_dir = QLineEdit(str(cfg.storage.base_dir), self)
        form.addRow("Storage base dir", self.storage_base_dir)

        self.whisper_cli = QLineEdit(str(cfg.whisper.cli_path), self)
        form.addRow("whisper-cli path", self.whisper_cli)

        self.whisper_model = QLineEdit(str(cfg.whisper.model_path), self)
        form.addRow("Model path", self.whisper_model)

        self.whisper_lang = QLineEdit(cfg.whisper.language, self)
        form.addRow("Whisper language", self.whisper_lang)

        self.whisper_extra_args = QLineEdit(" ".join(cfg.whisper.extra_args), self)
        form.addRow("Whisper extra args", self.whisper_extra_args)

        self.summarizer_enabled = QCheckBox(self)
        self.summarizer_enabled.setChecked(cfg.summarizer.enabled)
        form.addRow("Summarizer enabled", self.summarizer_enabled)

        self.summarizer_provider = QLineEdit(cfg.summarizer.provider, self)
        form.addRow("Summarizer provider", self.summarizer_provider)

        self.summarizer_model = QLineEdit(cfg.summarizer.model, self)
        form.addRow("Summarizer model", self.summarizer_model)

        self.summarizer_api_env = QLineEdit(cfg.summarizer.api_key_env, self)
        form.addRow("Summarizer API key env", self.summarizer_api_env)

        self.summarizer_endpoint = QLineEdit(cfg.summarizer.endpoint, self)
        form.addRow("Summarizer endpoint", self.summarizer_endpoint)

        self.summarizer_prompt = QTextEdit(self)
        self.summarizer_prompt.setPlainText(cfg.summarizer.system_prompt)
        self.summarizer_prompt.setMinimumHeight(90)
        form.addRow("Summarizer prompt", self.summarizer_prompt)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    @staticmethod
    def _csv_items(value: str) -> list[str]:
        return [x.strip() for x in value.split(",") if x.strip()]

    @staticmethod
    def _shell_split_or_empty(value: str) -> list[str]:
        import shlex

        stripped = value.strip()
        if not stripped:
            return []
        return shlex.split(stripped)

    def to_config(self) -> Config:
        cfg = copy.deepcopy(self._cfg)
        cfg.app.poll_interval_seconds = int(self.poll_interval.value())
        cfg.app.log_level = self.log_level.text().strip().upper() or "INFO"

        cfg.usb.device_name = self.usb_device_name.text().strip()
        cfg.usb.mount_roots = [Path(x).expanduser().resolve() for x in self._csv_items(self.usb_mount_roots.text())]
        cfg.usb.source_subdir = self.usb_source_subdir.text().strip()
        exts = self._csv_items(self.usb_audio_ext.text())
        cfg.usb.audio_extensions = tuple(e if e.startswith(".") else f".{e}" for e in exts)

        cfg.storage.base_dir = Path(self.storage_base_dir.text().strip()).expanduser().resolve()

        cfg.whisper.cli_path = Path(self.whisper_cli.text().strip()).expanduser().resolve()
        cfg.whisper.model_path = Path(self.whisper_model.text().strip()).expanduser().resolve()
        cfg.whisper.language = self.whisper_lang.text().strip() or "ja"
        cfg.whisper.extra_args = self._shell_split_or_empty(self.whisper_extra_args.text())

        cfg.summarizer.enabled = self.summarizer_enabled.isChecked()
        cfg.summarizer.provider = self.summarizer_provider.text().strip().lower()
        cfg.summarizer.model = self.summarizer_model.text().strip()
        cfg.summarizer.api_key_env = self.summarizer_api_env.text().strip()
        cfg.summarizer.endpoint = self.summarizer_endpoint.text().strip()
        cfg.summarizer.system_prompt = self.summarizer_prompt.toPlainText().strip()

        if not cfg.usb.device_name:
            raise ValueError("USB device name is required")
        if not cfg.usb.mount_roots:
            raise ValueError("At least one mount root is required")
        if not cfg.usb.audio_extensions:
            raise ValueError("At least one audio extension is required")
        if not str(cfg.storage.base_dir):
            raise ValueError("Storage base dir is required")
        if not str(cfg.whisper.cli_path) or not str(cfg.whisper.model_path):
            raise ValueError("whisper-cli path and model path are required")
        if cfg.summarizer.enabled and (not cfg.summarizer.provider or not cfg.summarizer.model or not cfg.summarizer.api_key_env):
            raise ValueError("Summarizer enabled requires provider/model/api_key_env")

        return cfg


class MonitorWorker(QThread):
    status_changed = Signal(str, str, int)

    def __init__(self, config_path: Path):
        super().__init__()
        self._config_path = config_path
        self._stop_event = threading.Event()
        self._run_once_event = threading.Event()
        self._reload_event = threading.Event()
        self._lock = threading.Lock()
        self._active = True
        self._cfg: Config | None = None
        self._state: StateStore | None = None

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

    def request_reload(self) -> None:
        self._reload_event.set()
        self._run_once_event.set()

    def request_stop(self) -> None:
        self._stop_event.set()

    def _ensure_loaded(self) -> None:
        if self._cfg is not None and self._state is not None:
            return
        self._reload_config_now()

    def _reload_config_now(self) -> None:
        self._cfg = load_config(self._config_path)
        state_path = self._cfg.storage.base_dir / self._cfg.storage.state_file_name
        self._state = StateStore(state_path)
        self._state.load()
        self.status_changed.emit("running", "configuration reloaded", -1)

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
            if self._reload_event.is_set():
                try:
                    self._reload_config_now()
                except Exception as e:
                    LOGGER.exception("Failed to reload config")
                    self.status_changed.emit("error", f"reload failed: {e}", -1)
                finally:
                    self._reload_event.clear()

            if not active and not run_now:
                if self._stop_event.wait(timeout=1.0):
                    break
                continue

            try:
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

        self._settings_action = QAction("Settings...", self._menu)
        self._settings_action.triggered.connect(self._open_settings)
        self._menu.addAction(self._settings_action)

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

    def _open_settings(self) -> None:
        dialog = SettingsDialog(self._cfg, None)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            updated_cfg = dialog.to_config()
            save_config(self._config_path, updated_cfg)
            self._cfg = load_config(self._config_path)
            self._worker.request_reload()
            self._tray.showMessage(
                "voice-logger",
                "Settings saved and reloaded",
                QSystemTrayIcon.MessageIcon.Information,
                3000,
            )
        except Exception as e:
            QMessageBox.critical(None, "Settings Error", str(e))

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

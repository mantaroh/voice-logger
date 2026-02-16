#!/usr/bin/env bash
set -euo pipefail

INSTALL_PREFIX="${VOICE_LOGGER_INSTALL_PREFIX:-$HOME/.local/share/voice-logger}"
BIN_DIR="${VOICE_LOGGER_BIN_DIR:-$HOME/.local/bin}"

WHISPER_SRC_DIR="$INSTALL_PREFIX/whisper.cpp"
WHISPER_INSTALL_BIN="$INSTALL_PREFIX/bin/whisper-cli"
MODEL_DIR="$INSTALL_PREFIX/models/kotoba-whisper-v2.2"
ENV_FILE="$INSTALL_PREFIX/env.sh"
LINK_BIN="$BIN_DIR/whisper-cli"

echo "Removing installed whisper.cpp and kotoba-whisper2.2 assets..."

rm -rf "$WHISPER_SRC_DIR"
rm -f "$WHISPER_INSTALL_BIN"
rm -rf "$MODEL_DIR"
rm -f "$ENV_FILE"

if [[ -L "$LINK_BIN" ]]; then
  TARGET="$(readlink "$LINK_BIN")"
  if [[ "$TARGET" == "$WHISPER_INSTALL_BIN" ]]; then
    rm -f "$LINK_BIN"
  fi
fi

rmdir "$INSTALL_PREFIX/bin" 2>/dev/null || true
rmdir "$INSTALL_PREFIX/models" 2>/dev/null || true
rmdir "$INSTALL_PREFIX" 2>/dev/null || true

echo "Uninstall complete."

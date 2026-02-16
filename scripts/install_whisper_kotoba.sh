#!/usr/bin/env bash
set -euo pipefail

INSTALL_PREFIX="${VOICE_LOGGER_INSTALL_PREFIX:-$HOME/.local/share/voice-logger}"
BIN_DIR="${VOICE_LOGGER_BIN_DIR:-$HOME/.local/bin}"
WHISPER_CPP_REPO="${WHISPER_CPP_REPO:-https://github.com/ggml-org/whisper.cpp.git}"
WHISPER_CPP_REF="${WHISPER_CPP_REF:-master}"
KOTOBA_HF_REPO="${KOTOBA_HF_REPO:-kotoba-tech/kotoba-whisper-v2.2}"
KOTOBA_MODEL_URL="${KOTOBA_MODEL_URL:-}"

WHISPER_SRC_DIR="$INSTALL_PREFIX/whisper.cpp"
WHISPER_BUILD_DIR="$WHISPER_SRC_DIR/build"
WHISPER_INSTALL_BIN="$INSTALL_PREFIX/bin/whisper-cli"
MODEL_DIR="$INSTALL_PREFIX/models/kotoba-whisper-v2.2"
MODEL_ALIAS="$MODEL_DIR/kotoba-whisper-v2.2.bin"

need_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "[ERROR] required command not found: $1" >&2
    exit 1
  fi
}

cpu_jobs() {
  if command -v nproc >/dev/null 2>&1; then
    nproc
  elif command -v sysctl >/dev/null 2>&1; then
    sysctl -n hw.ncpu
  else
    echo 4
  fi
}

find_kotoba_model_url() {
  local api="https://huggingface.co/api/models/${KOTOBA_HF_REPO}"
  local picked
  picked="$(curl -fsSL "$api" | python3 -c '
import json,sys
obj=json.load(sys.stdin)
files=[x.get("rfilename","") for x in obj.get("siblings",[])]
rank=[]
for f in files:
    lf=f.lower()
    if lf.endswith(".gguf"):
        score=0
    elif "ggml" in lf and lf.endswith(".bin"):
        score=1
    else:
        continue
    rank.append((score, len(lf), f))
if not rank:
    print("")
else:
    rank.sort()
    print(rank[0][2])
')"

  if [[ -z "$picked" ]]; then
    return 1
  fi

  echo "https://huggingface.co/${KOTOBA_HF_REPO}/resolve/main/${picked}"
}

echo "[1/4] checking prerequisites"
need_cmd git
need_cmd cmake
need_cmd python3
need_cmd curl
if ! command -v c++ >/dev/null 2>&1 && ! command -v clang++ >/dev/null 2>&1 && ! command -v g++ >/dev/null 2>&1; then
  echo "[ERROR] C++ compiler not found (c++/clang++/g++ required)" >&2
  exit 1
fi

mkdir -p "$INSTALL_PREFIX" "$BIN_DIR" "$MODEL_DIR" "$INSTALL_PREFIX/bin"

echo "[2/4] building whisper.cpp"
if [[ ! -d "$WHISPER_SRC_DIR/.git" ]]; then
  git clone --depth 1 --branch "$WHISPER_CPP_REF" "$WHISPER_CPP_REPO" "$WHISPER_SRC_DIR"
else
  git -C "$WHISPER_SRC_DIR" fetch --depth 1 origin "$WHISPER_CPP_REF"
  git -C "$WHISPER_SRC_DIR" checkout -f FETCH_HEAD
fi

cmake -S "$WHISPER_SRC_DIR" -B "$WHISPER_BUILD_DIR" -DCMAKE_BUILD_TYPE=Release
cmake --build "$WHISPER_BUILD_DIR" --config Release -j"$(cpu_jobs)"

WHISPER_BUILT_BIN=""
if [[ -x "$WHISPER_BUILD_DIR/bin/whisper-cli" ]]; then
  WHISPER_BUILT_BIN="$WHISPER_BUILD_DIR/bin/whisper-cli"
elif [[ -x "$WHISPER_BUILD_DIR/bin/main" ]]; then
  WHISPER_BUILT_BIN="$WHISPER_BUILD_DIR/bin/main"
else
  echo "[ERROR] whisper.cpp binary not found in $WHISPER_BUILD_DIR/bin" >&2
  exit 1
fi

cp "$WHISPER_BUILT_BIN" "$WHISPER_INSTALL_BIN"
chmod +x "$WHISPER_INSTALL_BIN"
ln -sfn "$WHISPER_INSTALL_BIN" "$BIN_DIR/whisper-cli"

echo "[3/4] downloading kotoba-whisper2.2 model"
if [[ -z "$KOTOBA_MODEL_URL" ]]; then
  if ! KOTOBA_MODEL_URL="$(find_kotoba_model_url)"; then
    echo "[ERROR] no gguf/ggml model file found in $KOTOBA_HF_REPO" >&2
    echo "        set KOTOBA_MODEL_URL and rerun" >&2
    exit 1
  fi
fi

MODEL_FILENAME="$(basename "${KOTOBA_MODEL_URL%%\?*}")"
MODEL_PATH="$MODEL_DIR/$MODEL_FILENAME"
curl -fL "$KOTOBA_MODEL_URL" -o "$MODEL_PATH"
ln -sfn "$MODEL_PATH" "$MODEL_ALIAS"

echo "[4/4] writing helper env file"
cat > "$INSTALL_PREFIX/env.sh" <<ENV
export WHISPER_CLI_PATH="$WHISPER_INSTALL_BIN"
export KOTOBA_MODEL_PATH="$MODEL_ALIAS"
export PATH="$BIN_DIR:\$PATH"
ENV

echo
echo "Install complete."
echo "whisper-cli: $WHISPER_INSTALL_BIN"
echo "model:       $MODEL_ALIAS -> $MODEL_PATH"
echo
echo "Update your config.toml:"
echo "  [whisper]"
echo "  cli_path = \"$WHISPER_INSTALL_BIN\""
echo "  model_path = \"$MODEL_ALIAS\""

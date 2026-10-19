#!/bin/bash
set -e

echo "=================================="
echo "  ADAM — First Of It's Kind"
echo "  One-command installation"
echo "=================================="
echo ""

ADAM_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODELS_DIR="$ADAM_DIR/models"
LLAMA_DIR="${ADAM_LLAMA_DIR:-$HOME/llama.cpp}"
LLAMA_BIN="$LLAMA_DIR/build/bin/llama-server"

echo "[1/5] Installing Python dependencies..."
pip install -r "$ADAM_DIR/requirements.txt"
python -c "from fastembed import TextEmbedding; TextEmbedding(model_name='BAAI/bge-small-en-v1.5')" 2>/dev/null || echo "  fastembed model will download on first use"

echo "[2/5] Setting up llama.cpp..."
if [ ! -x "$LLAMA_BIN" ]; then
    git clone https://github.com/ggerganov/llama.cpp.git "$LLAMA_DIR"
    cmake -S "$LLAMA_DIR" -B "$LLAMA_DIR/build" -DGGML_NATIVE=ON
    cmake --build "$LLAMA_DIR/build" --config Release -j 2
else
    echo "  llama-server already present at $LLAMA_BIN"
fi

echo "[3/5] Downloading + converting TinyChat15M..."
mkdir -p "$MODELS_DIR"
GGUF="$MODELS_DIR/TinyChat15M.gguf"
if [ ! -f "$GGUF" ]; then
    BIN=$(python -c "
from huggingface_hub import hf_hub_download
print(hf_hub_download(repo_id='starhopp3r/TinyChat', filename='TinyChat15M.bin'))
")
    "$LLAMA_DIR/build/bin/llama-convert-llama2c-to-ggml" \
        --llama2c-model "$BIN" \
        --copy-vocab-from-model "$LLAMA_DIR/models/ggml-vocab-llama-spm.gguf" \
        --llama2c-output-model "$GGUF"
else
    echo "  TinyChat15M.gguf already present"
fi

echo "[4/5] Running tests..."
cd "$ADAM_DIR"
python -m pytest tests/ -q

echo "[5/5] Done!"
echo ""
echo "Quick start:"
echo "  CLI:    python -m interface.cli"
echo "  Web:    python -m interface.web.app"
echo "  Demo:   python -m interface.cli 'hello'"

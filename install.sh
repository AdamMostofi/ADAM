#!/bin/bash
set -e

echo "=================================="
echo "  ADAM — First Of It's Kind"
echo "  One-command installation"
echo "=================================="
echo ""

echo "[1/4] Installing Python dependencies..."
pip install -r requirements.txt

echo "[2/4] Downloading models (Needle 2 + TinyChat15M)..."
python -c "
from transformers import AutoModelForCausalLM, AutoTokenizer
print('  Downloading TinyChat15M...')
AutoTokenizer.from_pretrained('sshleifer/tiny-gpt2')
AutoModelForCausalLM.from_pretrained('sshleifer/tiny-gpt2')
print('  TinyChat15M ready.')
"

echo "[3/4] Running tests..."
python -m pytest tests/ -v --tb=short

echo "[4/4] Done!"
echo ""
echo "Quick start:"
echo "  CLI:    python -m interface.cli"
echo "  Web:    python -m interface.web.app"
echo "  Demo:   python -m interface.cli 'hello'"

#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
fi

export ADAM_DB="$SCRIPT_DIR/data/adam_memory.db"
export ADAM_LANCE="$SCRIPT_DIR/data/adam_vectors.lance"

mkdir -p "$SCRIPT_DIR/data"

echo "=================================="
echo "  ADAM — First Of It's Kind"
echo "  USB Portable Mode"
echo "=================================="
echo ""

if [ "$1" == "--web" ]; then
    echo "Starting Web UI on http://localhost:7860"
    python -m interface.web.app
else
    echo "Starting CLI..."
    python -m interface.cli
fi

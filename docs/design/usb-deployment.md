# ADAM — USB Deployment Guide

## Overview

Run ADAM entirely from a USB drive on any computer. The USB contains the full runtime, models, and dependencies. The host computer only provides CPU, RAM, and GPU (optional).

## Requirements

- USB 3.0 drive, 16GB minimum (32GB recommended)
- Any computer with Python 3.10+ (or use the bundled portable Python)
- No internet required (after initial setup)

## USB Structure

```
ADAM-USB/
├── python/                  # Portable Python 3.12 (optional)
├── venv/                    # Virtual environment with all deps
├── models/
│   ├── needle2/            # Needle 2 binary (14MB)
│   └── tinychat15m/         # TinyChat15M weights (~30MB)
├── adam/                    # This repository
│   ├── kernel/
│   ├── memory/
│   ├── learning/
│   ├── interface/
│   └── tests/
├── data/                    # Runtime data (created on first run)
│   ├── adam_memory.db
│   └── adam_vectors.lance/
├── start.sh                 # Executable launcher (Linux/Mac)
├── start.bat               # Executable launcher (Windows)
└── README.txt
```

## Setup

### 1. Create the USB

```bash
# On your main machine
git clone https://github.com/AdamMostofi/ADAM.git /media/USB/ADAM-USB/adam
cd /media/USB/ADAM-USB
python -m venv venv
source venv/bin/activate
pip install -r adam/requirements.txt
```

### 2. Download Models to USB

```bash
mkdir -p /media/USB/ADAM-USB/models
python -c "
from transformers import AutoModelForCausalLM, AutoTokenizer
import shutil
AutoTokenizer.from_pretrained('sshleifer/tiny-gpt2', cache_dir='/media/USB/ADAM-USB/models')
AutoModelForCausalLM.from_pretrained('sshleifer/tiny-gpt2', cache_dir='/media/USB/ADAM-USB/models')
"
```

### 3. Create Launcher

See `usb-run.sh` in the repo root.

## Usage

Insert USB into any computer:

**Linux/Mac:**
```bash
/media/USB/ADAM-USB/start.sh
```

**Windows:**
```
E:\ADAM-USB\start.bat
```

The launcher:
1. Detects the USB drive letter/mount point
2. Activates the bundled Python environment
3. Sets model paths to USB locations
4. Launches ADAM CLI or Web UI
5. All data stays on the USB

## Data Persistence

All runtime data (memories, skills, EQ state) is stored on the USB in `data/`. Unplug and move to another computer — everything is preserved.

## Performance

- USB 3.0: ~100MB/s read — sufficient for model loading
- First boot: ~10 seconds (load models from USB)
- Subsequent boots: ~2 seconds (OS cache)
- Inference speed: same as local (models loaded into RAM)

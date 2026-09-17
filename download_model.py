#!/usr/bin/env python3
"""Explicit, opt-in download of the application's local faster-whisper models."""
from __future__ import annotations
import argparse
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
CACHE = BASE_DIR / 'huggingface_cache' / 'hub'
# Use the public upstream by default. HF_ENDPOINT may explicitly select a trusted mirror.
os.environ.setdefault('HF_HUB_DISABLE_SYMLINKS_WARNING', '1')


def main() -> int:
    parser = argparse.ArgumentParser(description='主动下载 small/medium；正常转写不会触发下载。')
    parser.add_argument('model', nargs='?', choices=('small', 'medium'), default='small')
    args = parser.parse_args()
    from huggingface_hub import snapshot_download
    print(f'Downloading {args.model} to {CACHE}', flush=True)
    print(f'Endpoint: {os.environ.get("HF_ENDPOINT", "https://huggingface.co")}', flush=True)
    path = snapshot_download(repo_id=f'Systran/faster-whisper-{args.model}', cache_dir=str(CACHE))
    required = ('config.json', 'model.bin', 'tokenizer.json', 'vocabulary.txt')
    missing = [name for name in required if not (Path(path) / name).is_file() or not (Path(path) / name).stat().st_size]
    if missing:
        raise RuntimeError('Model snapshot is incomplete: ' + ', '.join(missing))
    print(f'Model ready: {path}')
    print('Run scripts\\preflight.py after preparing both models, then start.bat.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

"""Build an allowlisted source ZIP without deleting or copying local runtime data."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import zipfile

ROOT = Path(__file__).resolve().parent.parent
ROOT_FILES = (
    '.gitignore', '.gitattributes', 'README.md', 'CHANGELOG.md', 'SECURITY.md',
    'requirements-app.txt', 'requirements-lock.txt', 'setup.bat', 'setup_auto.bat',
    'start.bat', 'run_checks.bat', 'download_model.py', 'download_model.bat',
)
EXACT_FILES = (
    'frontend/package.json', 'frontend/package-lock.json', 'frontend/tsconfig.json',
    'frontend/vite.config.ts', 'frontend/index.html',
    'scripts/start.py', 'scripts/preflight.py', 'scripts/package_source.py',
    'docs/INSTALL.md', 'docs/USAGE.md', 'docs/DEVELOPMENT.md',
    'docs/RELEASING.md', 'docs/VALIDATION.md', '.github/workflows/checks.yml',
)
TREE_TYPES = {'backend': {'.py'}, 'tests': {'.py'}, 'frontend/src': {'.ts', '.tsx', '.css', '.svg'}}
SECRET_PATTERNS = (
    re.compile(rb'gh[pousr]_[A-Za-z0-9]{20,}'),
    re.compile(rb'github_pat_[A-Za-z0-9_]{20,}'),
    re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    re.compile(rb'(?:https?://)[^\s/@:]+:[^\s/@]+@'),
)
MAX_FILE_BYTES = 1024 * 1024


def source_files(root: Path = ROOT) -> list[Path]:
    paths = [root / name for name in (*ROOT_FILES, *EXACT_FILES)]
    for folder, suffixes in TREE_TYPES.items():
        paths.extend(p for p in (root / folder).rglob('*')
                     if p.is_file() and p.suffix in suffixes and '__pycache__' not in p.parts)
    # Do not invent a license; include one only if the maintainer supplies it.
    paths.extend(root / name for name in ('LICENSE', 'LICENSE.md', 'NOTICE') if (root / name).is_file())
    return sorted(set(paths), key=lambda p: p.relative_to(root).as_posix())


def audited_files(root: Path = ROOT) -> list[tuple[str, bytes]]:
    result = []
    for path in source_files(root):
        relative = path.relative_to(root)
        if not path.is_file():
            raise ValueError(f'Required source file missing: {relative}')
        if any(p.is_symlink() for p in (path, *path.parents) if p != root.parent):
            raise ValueError(f'Linked source files are not supported: {relative}')
        path.resolve().relative_to(root.resolve())
        if path.stat().st_size > MAX_FILE_BYTES:
            raise ValueError(f'Source file exceeds 1 MiB review limit: {relative}')
        data = path.read_bytes()
        if any(pattern.search(data) for pattern in SECRET_PATTERNS):
            raise ValueError(f'Possible credential in {relative}; inspect locally, do not publish it')
        # Normalize only publication bytes. Do not rewrite the user's local runtime files.
        text = data.decode('utf-8-sig').replace('\r\n', '\n')
        if path.suffix == '.bat':
            text = text.replace('\n', '\r\n')
        result.append((relative.as_posix(), text.encode('utf-8')))
    return result


def build(output: Path, root: Path = ROOT) -> dict:
    output = output.resolve()
    output.relative_to((root / 'releases').resolve())
    if output.suffix.lower() != '.zip':
        raise ValueError('Output must be a .zip inside the ignored releases/ directory')
    entries = audited_files(root)
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_suffix('.zip.tmp')
    try:
        with zipfile.ZipFile(temp, 'w', zipfile.ZIP_DEFLATED) as archive:
            for name, content in entries:
                info = zipfile.ZipInfo('video/' + name, date_time=(2026, 9, 17, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                archive.writestr(info, content)
        os.replace(temp, output)
    finally:
        temp.unlink(missing_ok=True)
    report = {
        'archive': output.name,
        'file_count': len(entries),
        'source_bytes': sum(len(data) for _, data in entries),
        'archive_bytes': output.stat().st_size,
        'sha256': hashlib.sha256(output.read_bytes()).hexdigest(),
        'files': [{'path': name, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
                  for name, data in entries],
    }
    output.with_suffix('.manifest.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default='releases/video-source.zip')
    args = parser.parse_args()
    report = build(ROOT / args.output)
    print(json.dumps({k: v for k, v in report.items() if k != 'files'}, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

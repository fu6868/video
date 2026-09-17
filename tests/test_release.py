"""Release tooling checks: no model downloads and no writes to application data."""
from pathlib import Path
import importlib.util
import sys
import types
from scripts.package_source import ROOT, audited_files, build


def test_release_allowlist_has_no_runtime_or_private_files():
    files = dict(audited_files())
    assert 'README.md' in files and 'scripts/start.py' in files
    assert 'frontend/package-lock.json' in files
    assert 'requirements-lock.txt' in files
    assert not any(name.startswith(('data/', 'backups/', 'huggingface_cache/', '.venv/')) for name in files)
    assert not any(name.startswith('docs/mcp-') for name in files)
    assert 'scripts/final_delivery.py' not in files
    assert 'docs/final-delivery.md' not in files
    assert 'IMPLEMENTATION_PLAN.md' not in files


def test_package_rejects_output_outside_release_dir(tmp_path):
    import pytest
    with pytest.raises(ValueError):
        build(tmp_path / 'not-in-releases.zip')


def test_explicit_downloader_uses_project_cache_without_inference(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location('release_downloader', ROOT / 'download_model.py')
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    snapshot = tmp_path / 'snapshot'; snapshot.mkdir()
    for name in ('config.json', 'model.bin', 'tokenizer.json', 'vocabulary.txt'):
        (snapshot / name).write_bytes(b'test')
    seen = {}
    def fake_download(**kwargs):
        seen.update(kwargs)
        return str(snapshot)
    monkeypatch.setitem(sys.modules, 'huggingface_hub', types.SimpleNamespace(snapshot_download=fake_download))
    monkeypatch.setattr(sys, 'argv', ['download_model.py', 'medium'])
    assert module.main() == 0
    assert seen['repo_id'] == 'Systran/faster-whisper-medium'
    assert Path(seen['cache_dir']) == ROOT / 'huggingface_cache' / 'hub'

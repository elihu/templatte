"""Shared fixtures for service tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from templatte.core.services import _common

SAMPLE_FILES: dict[str, str] = {
    "config/app.toml": '# app\n[server]\nhost = "0.0.0.0"\nport = 8080\n\n[db]\npassword = "hunter2"\n',
    "config/svc.yaml": "name: api\napi_key: abc123\nretries: 3\n",
    "config/data.json": '{"debug": true, "token": "t0k"}\n',
    "settings.ini": "[main]\nname = demo\n",
    ".env": "PORT=9000\nSECRET_VALUE=s3\n",
}


def write_files(root: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(text.encode("utf-8"))


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    """A workspace populated with one file of every supported format."""
    write_files(tmp_path, SAMPLE_FILES)
    return tmp_path


@pytest.fixture(autouse=True)
def fixed_timestamp(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_common, "timestamp", lambda: "20260101T000000")


def snapshot(root: Path) -> dict[str, bytes]:
    """Map of every file under root to its bytes (for byte-identity assertions)."""
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file() and ".git/" not in p.as_posix()
    }

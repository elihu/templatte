"""Unit tests for filesystem safety utilities and AtomicFileWriter."""

from pathlib import Path

import pytest

from templatte.utils.fs import (
    AtomicFileWriter,
    atomic_write_bytes,
    atomic_write_text,
    is_within_workspace,
    normalize_workspace_path,
)


def test_is_within_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    child = workspace / "config" / "app.toml"
    outside = tmp_path / "outside.txt"

    assert is_within_workspace(child, workspace) is True
    assert is_within_workspace(workspace, workspace) is True
    assert is_within_workspace(outside, workspace) is False
    assert is_within_workspace(workspace / ".." / "outside.txt", workspace) is False


def test_normalize_workspace_path(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    child = workspace / "services" / "api" / "config.toml"

    assert normalize_workspace_path("./services/api/config.toml") == "services/api/config.toml"
    assert normalize_workspace_path("services/api/config.toml") == "services/api/config.toml"
    assert normalize_workspace_path(child, workspace=workspace) == "services/api/config.toml"


def test_atomic_file_writer_success(tmp_path: Path) -> None:
    target = tmp_path / "subdir" / "target.txt"
    content = "Hello, barista!"

    with AtomicFileWriter(target) as f:
        f.write(content)

    assert target.exists()
    assert target.read_text(encoding="utf-8") == content

    # Check that no temporary files remain in the directory
    temp_files = list(target.parent.glob(".target.txt.tmp.*"))
    assert len(temp_files) == 0


def test_atomic_file_writer_rollback_on_error(tmp_path: Path) -> None:
    target = tmp_path / "target.txt"
    target.write_text("initial content", encoding="utf-8")

    with pytest.raises(RuntimeError, match="Simulated crash"), AtomicFileWriter(target) as f:
        f.write("corrupted content")
        raise RuntimeError("Simulated crash")

    # Initial content must be preserved
    assert target.read_text(encoding="utf-8") == "initial content"
    # Temp file must be unlinked
    temp_files = list(tmp_path.glob(".target.txt.tmp.*"))
    assert len(temp_files) == 0


def test_atomic_write_helpers(tmp_path: Path) -> None:
    text_file = tmp_path / "text.txt"
    atomic_write_text(text_file, "roasted beans")
    assert text_file.read_text(encoding="utf-8") == "roasted beans"

    binary_file = tmp_path / "binary.bin"
    atomic_write_bytes(binary_file, b"\x00\xff\xca\xfe")
    assert binary_file.read_bytes() == b"\x00\xff\xca\xfe"

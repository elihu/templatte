"""Unit tests for git helper utilities using real temporary repositories."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from templatte.core.exceptions import UsageError
from templatte.utils.git import (
    BLOCK_END,
    BLOCK_START,
    ensure_gitignored,
    get_tracked_files,
    has_uncommitted_changes,
    is_git_repo,
)

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def git(cwd: Path, *args: str) -> None:
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=t@example.com",
            "-c",
            "user.name=T",
            "-c",
            "commit.gpgsign=false",
            *args,
        ],
        cwd=cwd,
        check=True,
        capture_output=True,
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    git(tmp_path, "init", "-q")
    (tmp_path / "a.txt").write_text("one\n", encoding="utf-8", newline="\n")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.txt").write_text("two\n", encoding="utf-8", newline="\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-q", "-m", "init")
    return tmp_path


def test_non_repo(tmp_path: Path) -> None:
    assert is_git_repo(tmp_path) is False
    assert get_tracked_files(tmp_path) == set()
    f = tmp_path / "x"
    f.write_text("x", encoding="utf-8", newline="\n")
    assert has_uncommitted_changes(f) is False


def test_missing_git_binary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))
    assert is_git_repo(tmp_path) is False
    assert get_tracked_files(tmp_path) == set()
    assert has_uncommitted_changes(tmp_path / "x") is False


def test_is_repo_and_tracked(repo: Path) -> None:
    assert is_git_repo(repo) is True
    assert is_git_repo(repo / "a.txt") is True
    assert get_tracked_files(repo) == {"a.txt", "sub/b.txt"}


def test_untracked_not_in_tracked(repo: Path) -> None:
    (repo / "new.txt").write_text("n", encoding="utf-8", newline="\n")
    assert "new.txt" not in get_tracked_files(repo)
    assert has_uncommitted_changes(repo / "new.txt") is False


def test_modified_vs_clean(repo: Path) -> None:
    assert has_uncommitted_changes(repo / "a.txt") is False
    (repo / "a.txt").write_text("changed\n", encoding="utf-8", newline="\n")
    (repo / "sub" / "b.txt").write_text("changed\n", encoding="utf-8", newline="\n")
    assert has_uncommitted_changes(repo / "a.txt") is True
    assert has_uncommitted_changes(repo / "sub" / "b.txt") is True


def test_no_head_commit(tmp_path: Path) -> None:
    git(tmp_path, "init", "-q")
    (tmp_path / "f").write_text("x", encoding="utf-8", newline="\n")
    assert has_uncommitted_changes(tmp_path / "f") is False


def test_gitignore_created(tmp_path: Path) -> None:
    assert ensure_gitignored(tmp_path, ["b", "a", "b"]) is True
    assert (tmp_path / ".gitignore").read_text(encoding="utf-8") == (
        f"{BLOCK_START}\n# Templatte values & local runtime configurations.\na\nb\n{BLOCK_END}\n"
    )


def test_gitignore_appended_preserving_content(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("*.pyc\nbuild/", encoding="utf-8", newline="\n")
    assert ensure_gitignored(tmp_path, ["x"]) is True
    text = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert text.startswith("*.pyc\nbuild/\n\n" + BLOCK_START)
    assert text.endswith(BLOCK_END + "\n")


def test_gitignore_replaces_only_block(tmp_path: Path) -> None:
    ensure_gitignored(tmp_path, ["old"])
    gi = tmp_path / ".gitignore"
    gi.write_text(
        "# head\n*.log\n\n" + gi.read_text(encoding="utf-8") + "# tail\ntmp/\n",
        encoding="utf-8",
        newline="\n",
    )
    assert ensure_gitignored(tmp_path, ["new1", "new2"]) is True
    text = gi.read_text(encoding="utf-8")
    assert text.startswith("# head\n*.log\n\n" + BLOCK_START)
    assert text.endswith(BLOCK_END + "\n# tail\ntmp/\n")
    assert "old" not in text and "new1\nnew2\n" in text


def test_gitignore_idempotent(tmp_path: Path) -> None:
    assert ensure_gitignored(tmp_path, ["a", "b"]) is True
    gi = tmp_path / ".gitignore"
    before = gi.stat().st_mtime_ns
    content = gi.read_bytes()
    assert ensure_gitignored(tmp_path, ["b", "a", "a"]) is False
    assert gi.read_bytes() == content
    assert gi.stat().st_mtime_ns == before


def test_gitignore_malformed_block(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text(f"{BLOCK_START}\nfoo\n", encoding="utf-8", newline="\n")
    with pytest.raises(UsageError):
        ensure_gitignored(tmp_path, ["a"])

"""Unit tests for the pathspec-backed ignore matcher."""

from __future__ import annotations

from pathlib import Path

from templatte.utils.ignore import IgnoreMatcher


def test_basic_and_unanchored() -> None:
    m = IgnoreMatcher(["*.env", "build/"])
    assert m.matches("prod.env")
    assert m.matches("a/b/prod.env")
    assert m.matches("build/out.txt")
    assert not m.matches("src/a.py")


def test_anchoring() -> None:
    m = IgnoreMatcher(["/top.txt"])
    assert m.matches("top.txt")
    assert not m.matches("sub/top.txt")


def test_double_star_and_negation() -> None:
    m = IgnoreMatcher(["config/**", "!config/keep.toml"])
    assert m.matches("config/a/b.toml")
    assert not m.matches("config/keep.toml")


def test_comments_and_blank_lines_ignored() -> None:
    m = IgnoreMatcher(["# comment", "", "x.txt"])
    assert m.matches("x.txt")
    assert not m.matches("# comment")


def test_empty_matcher() -> None:
    assert not IgnoreMatcher().matches("anything")


def test_from_gitignore(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text(
        "*.log\n!keep.log\nsecret/\n", encoding="utf-8", newline="\n"
    )
    m = IgnoreMatcher.from_gitignore(tmp_path)
    assert m.matches("a.log")
    assert not m.matches("keep.log")
    assert m.matches("secret/x")


def test_from_gitignore_missing(tmp_path: Path) -> None:
    assert not IgnoreMatcher.from_gitignore(tmp_path).matches("a")

"""Unit tests for the grind service."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from templatte.core.exceptions import LegacyRegistryError
from templatte.core.services.cleaner import grind
from templatte.core.services.generator import generate

from .conftest import SAMPLE_FILES, snapshot

HAS_GIT = shutil.which("git") is not None


def git(cwd: Path, *args: str) -> None:
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=t@e.com",
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
def generated(ws: Path) -> Path:
    generate(ws)
    return ws


def test_dry_run_deletes_nothing(generated: Path) -> None:
    before = snapshot(generated)
    r = grind(generated, dry_run=True, force=True)
    assert set(r.to_delete) == set(SAMPLE_FILES) and r.deleted == ()
    assert r.requires_confirmation is False and r.dry_run
    assert snapshot(generated) == before


def test_requires_confirmation_without_force(generated: Path) -> None:
    before = snapshot(generated)
    r = grind(generated)
    assert r.requires_confirmation and set(r.to_delete) == set(SAMPLE_FILES)
    assert r.deleted == ()
    assert snapshot(generated) == before


def test_force_deletes_only_concrete(generated: Path) -> None:
    latte = {k: v for k, v in snapshot(generated).items() if k.endswith(".latte")}
    registry = (generated / "templatte.toml").read_bytes()
    r = grind(generated, force=True)
    assert set(r.deleted) == set(SAMPLE_FILES) and not r.requires_confirmation
    for rel in SAMPLE_FILES:
        assert not (generated / rel).exists()
    assert {k: v for k, v in snapshot(generated).items() if k.endswith(".latte")} == latte
    assert (generated / "templatte.toml").read_bytes() == registry


def test_nothing_to_do(ws: Path) -> None:
    r = grind(ws)
    assert r.to_delete == () and not r.requires_confirmation


def test_only_files_that_exist(generated: Path) -> None:
    (generated / ".env").unlink()
    r = grind(generated, force=True)
    assert ".env" not in r.deleted and len(r.deleted) == 4


def test_backup(generated: Path) -> None:
    r = grind(generated, force=True, backup=True)
    assert len(r.backups) == 5
    bak = generated / "settings.ini.20260101T000000.bak"
    assert bak.read_text() == SAMPLE_FILES["settings.ini"]
    assert not (generated / "settings.ini").exists()


def test_legacy_registry_refused(generated: Path) -> None:
    (generated / "templatte.toml").write_text('"./a_b" = 1\n')
    with pytest.raises(LegacyRegistryError):
        grind(generated, force=True)


@pytest.mark.skipif(not HAS_GIT, reason="git not installed")
class TestTracked:
    @pytest.fixture
    def repo(self, generated: Path) -> Path:
        git(generated, "init", "-q")
        git(generated, "add", "-f", "config/app.toml", "settings.ini")
        git(generated, "commit", "-q", "-m", "x")
        return generated

    def test_clean_tracked_is_deleted(self, repo: Path) -> None:
        r = grind(repo, force=True)
        assert "config/app.toml" in r.deleted and r.skipped_tracked == ()

    def test_modified_tracked_skipped(self, repo: Path) -> None:
        (repo / "config/app.toml").write_text("[server]\nhost = 'x'\n")
        r = grind(repo, force=True)
        assert r.skipped_tracked == ("config/app.toml",)
        assert (repo / "config/app.toml").exists()
        assert "config/app.toml" not in r.to_delete
        assert "settings.ini" in r.deleted

    def test_dry_run_reports_skipped(self, repo: Path) -> None:
        (repo / "config/app.toml").write_text("[server]\nhost = 'x'\n")
        r = grind(repo, dry_run=True)
        assert r.skipped_tracked == ("config/app.toml",)

    def test_force_tracked(self, repo: Path) -> None:
        (repo / "config/app.toml").write_text("[server]\nhost = 'x'\n")
        r = grind(repo, force=True, force_tracked=True, backup=True)
        assert "config/app.toml" in r.deleted and r.skipped_tracked == ()
        bak = repo / "config/app.toml.20260101T000000.bak"
        assert bak.read_text() == "[server]\nhost = 'x'\n"

"""Unit tests for the check service."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from templatte.core.exceptions import LegacyRegistryError, ValidationError
from templatte.core.services.checker import (
    DRIFT,
    ERROR,
    GIT_LEAK,
    MISSING_VALUES,
    WARNING,
    check,
    exit_code_for,
    severity_for,
)
from templatte.core.services.generator import generate

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


@pytest.mark.parametrize(
    ("kinds", "code"),
    [
        ([], 0),
        ([MISSING_VALUES], 3),
        ([DRIFT], 5),
        ([GIT_LEAK], 5),
        ([MISSING_VALUES, DRIFT], 5),
        ([MISSING_VALUES, GIT_LEAK], 5),
        ([DRIFT, GIT_LEAK], 5),
    ],
)
def test_exit_code_mapping(kinds: list[str], code: int) -> None:
    assert exit_code_for(kinds) == code


@pytest.mark.parametrize(
    ("kind", "strict", "sev"),
    [
        (DRIFT, False, ERROR),
        (DRIFT, True, ERROR),
        (GIT_LEAK, False, WARNING),
        (GIT_LEAK, True, ERROR),
        (MISSING_VALUES, False, WARNING),
        (MISSING_VALUES, True, ERROR),
    ],
)
def test_severity_mapping(kind: str, strict: bool, sev: str) -> None:
    assert severity_for(kind, strict) == sev


@pytest.fixture
def generated(ws: Path) -> Path:
    generate(ws)
    return ws


def test_clean_no_git(generated: Path) -> None:
    r = check(generated)
    assert r.findings == () and r.exit_code == 0


def test_missing_registry_and_legacy(ws: Path) -> None:
    with pytest.raises(ValidationError):
        check(ws)
    (ws / "templatte.toml").write_text('"./a_b" = 1\n', encoding="utf-8", newline="\n")
    with pytest.raises(LegacyRegistryError):
        check(ws)


def test_missing_values(generated: Path) -> None:
    text = (
        (generated / "templatte.toml")
        .read_text(encoding="utf-8")
        .replace('"server.port" = 8080\n', "")
    )
    (generated / "templatte.toml").write_text(text, encoding="utf-8", newline="\n")
    r = check(generated)
    [f] = [f for f in r.findings if f.kind == MISSING_VALUES]
    assert f.path == "config/app.toml" and f.missing_keys == ("server.port",)
    assert f.severity == WARNING and r.exit_code == 3
    assert check(generated, strict=True).findings[0].severity == ERROR


def test_drift_with_diff(generated: Path) -> None:
    (generated / "settings.ini").write_text(
        "[main]\nname = other\n", encoding="utf-8", newline="\n"
    )
    r = check(generated)
    [f] = r.findings
    assert f.kind == DRIFT and f.severity == ERROR and f.path == "settings.ini"
    assert f.diff is not None and "-name = other" in f.diff and "+name = demo" in f.diff
    assert r.exit_code == 5


def test_no_drift_when_concrete_absent(generated: Path) -> None:
    (generated / "settings.ini").unlink()
    assert check(generated).findings == ()


def test_profile_changes_expected(generated: Path) -> None:
    with (generated / "templatte.toml").open("a", encoding="utf-8", newline="\n") as f:
        f.write('\n[profiles.prod."settings.ini".values]\n"main.name" = "prod"\n')
    assert check(generated).exit_code == 0
    r = check(generated, profile="prod")
    assert [f.path for f in r.findings] == ["settings.ini"] and r.exit_code == 5


def test_drift_dominates_missing(generated: Path) -> None:
    (generated / "settings.ini").write_text(
        "[main]\nname = other\n", encoding="utf-8", newline="\n"
    )
    text = (
        (generated / "templatte.toml")
        .read_text(encoding="utf-8")
        .replace('"server.port" = 8080\n', "")
    )
    (generated / "templatte.toml").write_text(text, encoding="utf-8", newline="\n")
    assert check(generated).exit_code == 5


@pytest.mark.skipif(not HAS_GIT, reason="git not installed")
class TestGit:
    def test_ignored_ok(self, generated: Path) -> None:
        git(generated, "init", "-q")
        assert check(generated).findings == ()

    def test_tracked_leak(self, generated: Path) -> None:
        git(generated, "init", "-q")
        git(generated, "add", "-f", "config/app.toml", "templatte.toml")
        r = check(generated)
        leaks = {f.path: f for f in r.findings if f.kind == GIT_LEAK}
        assert set(leaks) == {"config/app.toml", "templatte.toml"}
        assert all(f.severity == WARNING for f in leaks.values())
        assert r.exit_code == 5
        assert all(f.severity == ERROR for f in check(generated, strict=True).findings)

    def test_not_ignored_leak(self, generated: Path) -> None:
        git(generated, "init", "-q")
        (generated / ".gitignore").write_text("", encoding="utf-8", newline="\n")
        r = check(generated)
        paths = {f.path for f in r.findings if f.kind == GIT_LEAK}
        assert "config/app.toml" in paths and "templatte.toml" in paths and r.exit_code == 5

    def test_check_git_disabled(self, generated: Path) -> None:
        git(generated, "init", "-q")
        (generated / ".gitignore").write_text("", encoding="utf-8", newline="\n")
        assert check(generated, check_git=False).findings == ()

    def test_custom_config_path_leak(self, ws: Path) -> None:
        generate(ws, config_file=Path("conf/reg.toml"), update_gitignore=False)
        git(ws, "init", "-q")
        (ws / ".gitignore").write_text(
            "config/\nsettings.ini\n.env\n", encoding="utf-8", newline="\n"
        )
        r = check(ws, config_file=Path("conf/reg.toml"))
        assert [f.path for f in r.findings] == ["conf/reg.toml"]

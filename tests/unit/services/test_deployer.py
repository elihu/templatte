"""Unit tests for the deploy service."""

from __future__ import annotations

from pathlib import Path

import pytest

from templatte.core.exceptions import (
    LegacyRegistryError,
    MissingTemplateError,
    MissingValuesError,
    PathTraversalError,
    ValidationError,
)
from templatte.core.services.deployer import deploy
from templatte.core.services.generator import generate

from .conftest import SAMPLE_FILES, snapshot


def latte_snapshot(root: Path) -> dict[str, bytes]:
    return {k: v for k, v in snapshot(root).items() if k.endswith(".latte")}


@pytest.fixture
def generated(ws: Path) -> Path:
    generate(ws)
    return ws


def drop_concrete(ws: Path) -> None:
    for rel in SAMPLE_FILES:
        (ws / rel).unlink()


def test_round_trip(generated: Path) -> None:
    drop_concrete(generated)
    r = deploy(generated)
    assert set(r.created) == set(SAMPLE_FILES)
    assert r.exit_code == 0
    for rel, text in SAMPLE_FILES.items():
        assert (generated / rel).read_text() == text, rel


def test_latte_untouched(generated: Path) -> None:
    before = latte_snapshot(generated)
    assert before
    deploy(generated)  # unchanged
    drop_concrete(generated)
    deploy(generated)
    (generated / "settings.ini").write_text("[main]\nname = other\n")
    deploy(generated, force=True, backup=True)
    deploy(generated, dry_run=True, diff=True)
    assert latte_snapshot(generated) == before


def test_profile_override(generated: Path) -> None:
    drop_concrete(generated)
    with (generated / "templatte.toml").open("a") as f:
        f.write('\n[profiles.prod."config/app.toml".values]\n"server.port" = 443\n')
    deploy(generated, profile="prod")
    assert "port = 443" in (generated / "config/app.toml").read_text()
    (generated / "config/app.toml").unlink()
    deploy(generated)
    assert "port = 8080" in (generated / "config/app.toml").read_text()


def test_missing_values_aggregate_nothing_written(generated: Path) -> None:
    drop_concrete(generated)
    text = (generated / "templatte.toml").read_text()
    text = text.replace('"server.port" = 8080\n', "").replace("PORT = 9000\n", "")
    text = text.replace('"main.name" = "demo"\n', "")
    (generated / "templatte.toml").write_text(text)
    before = snapshot(generated)
    with pytest.raises(MissingValuesError) as ei:
        deploy(generated)
    err = ei.value
    assert err.exit_code == 3
    assert err.details["files"]["config/app.toml"] == ["server.port"]
    assert "settings.ini" in err.details["files"]
    assert "config/app.toml" in err.message
    assert snapshot(generated) == before


def test_missing_registry(ws: Path) -> None:
    with pytest.raises(ValidationError) as ei:
        deploy(ws)
    assert ei.value.exit_code == 3


def test_legacy_registry(ws: Path) -> None:
    (ws / "templatte.toml").write_text('"./a_b" = 1\n')
    with pytest.raises(LegacyRegistryError):
        deploy(ws)


def test_skip_force_backup(generated: Path) -> None:
    target = generated / "config/data.json"
    target.write_text('{"changed": 1}\n')
    r = deploy(generated)
    assert r.skipped_existing == ("config/data.json",)
    assert target.read_text() == '{"changed": 1}\n'

    r = deploy(generated, force=True)
    assert r.overwritten == ("config/data.json",) and r.backups == ()
    assert target.read_text() == SAMPLE_FILES["config/data.json"]

    target.write_text('{"changed": 2}\n')
    r = deploy(generated, force=True, backup=True)
    assert r.backups == ("config/data.json.20260101T000000.bak",)
    assert (generated / r.backups[0]).read_text() == '{"changed": 2}\n'


def test_unchanged_no_write(generated: Path) -> None:
    mtimes = {r: (generated / r).stat().st_mtime_ns for r in SAMPLE_FILES}
    r = deploy(generated, force=True)
    assert set(r.unchanged) == set(SAMPLE_FILES) and not r.created and not r.overwritten
    assert {k: (generated / k).stat().st_mtime_ns for k in SAMPLE_FILES} == mtimes


def test_dry_run_writes_nothing(generated: Path) -> None:
    (generated / "settings.ini").write_text("[main]\nname = x\n")
    (generated / ".env").unlink()
    before = snapshot(generated)
    r = deploy(generated, dry_run=True, force=True, backup=True)
    assert r.created == (".env",) and r.overwritten == ("settings.ini",) and r.dry_run
    assert snapshot(generated) == before


def test_diff(generated: Path) -> None:
    (generated / "settings.ini").write_text("[main]\nname = x\n")
    (generated / ".env").unlink()
    r = deploy(generated, diff=True, dry_run=True)
    assert "-name = x" in r.diffs["settings.ini"] and "+name = demo" in r.diffs["settings.ini"]
    assert "+PORT=9000" in r.diffs[".env"]
    assert deploy(generated, dry_run=True).diffs == {}


def test_single_file(generated: Path) -> None:
    drop_concrete(generated)
    r = deploy(generated, file=Path("config/app.toml.latte"))
    assert r.created == ("config/app.toml",)
    assert not (generated / "config/svc.yaml").exists()
    r = deploy(generated, file=generated / "settings.ini.latte")
    assert r.created == ("settings.ini",)


def test_single_file_errors(generated: Path) -> None:
    with pytest.raises(MissingTemplateError):
        deploy(generated, file=Path("nope.toml.latte"))
    with pytest.raises(ValidationError):
        deploy(generated, file=Path("config/app.toml"))
    with pytest.raises(PathTraversalError):
        deploy(generated, file=Path("../x.latte"))


def test_skips_standing_dirs(generated: Path) -> None:
    (generated / "node_modules").mkdir()
    (generated / "node_modules" / "x.toml.latte").write_text("a = '{{ nope }}'\n")
    deploy(generated)  # would raise if discovered

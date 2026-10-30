"""Unit tests for the genelatte service."""

from __future__ import annotations

from pathlib import Path

import pytest

from templatte.core.exceptions import LegacyRegistryError
from templatte.core.registry import RegistryManager
from templatte.core.services.generator import generate, is_credential_shaped
from templatte.utils.git import BLOCK_END, BLOCK_START
from templatte.utils.ignore import IgnoreMatcher

from .conftest import snapshot, write_files


def load(ws: Path):  # type: ignore[no-untyped-def]
    return RegistryManager(ws).load(ws / "templatte.toml")


def test_credential_shape() -> None:
    assert is_credential_shaped("db.PassWord")
    assert is_credential_shaped("api_key")
    assert is_credential_shaped("auth.tokens[0]")
    assert is_credential_shaped("client.Secret")
    assert not is_credential_shaped("server.port")


def test_multiformat_generation(ws: Path) -> None:
    r = generate(ws)
    assert r.exit_code == 0
    assert r.files_scanned == 5
    assert r.templates_created == (
        ".env.latte",
        "config/app.toml.latte",
        "config/data.json.latte",
        "config/svc.yaml.latte",
        "settings.ini.latte",
    )
    assert r.skipped_existing == () and r.manual_review == ()
    assert r.keys_extracted > 0 and r.gitignore_updated is True
    reg = load(ws)
    assert set(reg.files) == {
        ".env",
        "config/app.toml",
        "config/data.json",
        "config/svc.yaml",
        "settings.ini",
    }
    assert reg.files["config/app.toml"].format == "toml"
    assert reg.files["config/app.toml"].values["server.port"] == 8080
    assert reg.files["config/app.toml"].secrets == {"db.password": True}
    assert reg.files["config/svc.yaml"].secrets == {"api_key": True}
    assert reg.files["config/data.json"].secrets == {"token": True}
    assert reg.files[".env"].secrets == {"SECRET_VALUE": True}
    assert "{{ server.port }}" in (ws / "config/app.toml.latte").read_text()
    assert (ws / "config/app.toml").read_text().count("hunter2") == 1  # concrete untouched


def test_dry_run_writes_nothing(ws: Path) -> None:
    before = snapshot(ws)
    r = generate(ws, dry_run=True)
    assert r.dry_run and len(r.templates_created) == 5 and r.keys_extracted > 0
    assert snapshot(ws) == before


def test_existing_latte_skip_vs_force(ws: Path) -> None:
    generate(ws)
    (ws / "config/app.toml.latte").write_text("custom\n")
    r = generate(ws)
    assert r.templates_created == ()
    assert "config/app.toml.latte" in r.skipped_existing
    assert (ws / "config/app.toml.latte").read_text() == "custom\n"
    r = generate(ws, force=True)
    assert "config/app.toml.latte" in r.templates_created
    assert "custom" not in (ws / "config/app.toml.latte").read_text()


def test_merge_rule(ws: Path) -> None:
    generate(ws)
    path = ws / "templatte.toml"
    text = path.read_text()
    text = "# my comment\n" + text
    text += '\n[profiles.prod."config/app.toml".values]\n"server.port" = 443\n'
    # Hand-flag a non-credential key as secret and add a stale one.
    text = text.replace(
        '[files."config/app.toml".secrets]',
        '[files."config/app.toml".secrets]\n"server.host" = true\n"gone.key" = true',
    )
    path.write_text(text)

    # Change the concrete file: new value, a removed key, a new key.
    (ws / "config/app.toml").write_text(
        '[server]\nhost = "1.2.3.4"\n\n[db]\npassword = "new"\napi_token = "x"\n'
    )
    r = generate(ws, force=True)
    assert "config/app.toml.latte" in r.templates_created

    out = path.read_text()
    assert out.startswith("# my comment\n")
    reg = load(ws)
    entry = reg.files["config/app.toml"]
    assert entry.values == {"server.host": "1.2.3.4", "db.password": "new", "db.api_token": "x"}
    assert entry.secrets == {"server.host": True, "db.password": True, "db.api_token": True}
    assert "gone.key" not in entry.secrets
    assert reg.profiles["prod"]["config/app.toml"].values == {"server.port": 443}
    # untouched entries preserved (not reprocessed? they are, but values unchanged)
    assert reg.files["settings.ini"].values == {"main.name": "demo"}


def test_unprocessed_entries_preserved(ws: Path) -> None:
    generate(ws)
    (ws / "extra").mkdir()
    (ws / "extra" / "x.toml").write_text("a = 1\n")
    # Non-forced rerun with include of a new file only processes the new file.
    (ws / "config/svc.yaml").write_text("name: changed\n")
    r = generate(ws, include=["extra/x.toml"])
    assert r.templates_created == ("extra/x.toml.latte",)
    reg = load(ws)
    assert reg.files["config/svc.yaml"].values["name"] == "api"  # untouched
    assert reg.files["extra/x.toml"].values == {"a": 1}


def test_idempotent_byte_identical(ws: Path) -> None:
    generate(ws)
    first = snapshot(ws)
    r = generate(ws)
    assert r.templates_created == () and r.gitignore_updated is False
    assert snapshot(ws) == first
    generate(ws, force=True)
    assert snapshot(ws) == first


def test_gitignore_block_contents(ws: Path) -> None:
    (ws / ".gitignore").write_text("*.pyc\n")
    generate(ws)
    text = (ws / ".gitignore").read_text()
    assert text.startswith("*.pyc\n\n" + BLOCK_START)
    block = text.split(BLOCK_START)[1].split(BLOCK_END)[0].splitlines()
    entries = [ln for ln in block if ln and not ln.startswith("#")]
    assert entries == sorted(
        [
            ".env",
            "config/app.toml",
            "config/data.json",
            "config/svc.yaml",
            "settings.ini",
            "templatte.*.toml",
            "templatte.toml",
            ".env.*.bak",
            "config/app.toml.*.bak",
            "config/data.json.*.bak",
            "config/svc.yaml.*.bak",
            "settings.ini.*.bak",
            "templatte.toml.*.bak",
        ]
    )
    assert "templatte.toml.enc" not in text
    assert ".latte" not in text


def test_gitignore_covers_backups(ws: Path) -> None:
    generate(ws)
    matcher = IgnoreMatcher.from_gitignore(ws)
    assert matcher.matches("config/app.toml.20261030T100528.bak")
    assert matcher.matches("templatte.toml.20261030T100528-1.bak")
    assert not matcher.matches("templatte.toml.enc")


def test_gitignore_covers_all_latte_not_only_this_run(ws: Path) -> None:
    generate(ws)
    write_files(ws, {"extra/y.toml": "a = 1\n"})
    generate(ws, include=["extra/y.toml"])
    text = (ws / ".gitignore").read_text()
    assert "extra/y.toml" in text and "config/app.toml" in text


def test_gitignore_stale_entry_removed(ws: Path) -> None:
    generate(ws)
    (ws / "settings.ini.latte").unlink()
    generate(ws, exclude=["settings.ini"])
    assert "settings.ini" not in (ws / ".gitignore").read_text().splitlines()


def test_update_gitignore_false(ws: Path) -> None:
    r = generate(ws, update_gitignore=False)
    assert r.gitignore_updated is False
    assert not (ws / ".gitignore").exists()


def test_nondefault_config_file_ignored(ws: Path) -> None:
    generate(ws, config_file=Path("conf/reg.toml"))
    assert (ws / "conf/reg.toml").is_file()
    assert "conf/reg.toml" in (ws / ".gitignore").read_text().splitlines()
    # the registry itself is never templatized
    assert "conf/reg.toml.latte" not in {p.relative_to(ws).as_posix() for p in ws.rglob("*.latte")}


def test_manual_review(ws: Path) -> None:
    write_files(
        ws, {"config/helm.yaml": "name: {{ .Values.n }}\n", "config/gha.yaml": "x: ${{ a }}\n"}
    )
    r = generate(ws)
    assert r.exit_code == 3
    assert r.manual_review == ("config/gha.yaml", "config/helm.yaml")
    assert len(r.templates_created) == 5
    assert not (ws / "config/helm.yaml.latte").exists()


def test_registry_ignored_patterns_and_delimiters(ws: Path) -> None:
    (ws / "templatte.toml").write_text(
        'version = 1\n[workspace]\nignored_patterns = ["config/data.json"]\n'
        '[template]\nopen = "<%"\nclose = "%>"\n'
    )
    write_files(ws, {"config/helm.ini": "[a]\nname = {{ v }}\n"})
    r = generate(ws)
    assert "config/data.json.latte" not in r.templates_created
    assert "config/helm.ini.latte" in r.templates_created  # {{ }} no longer foreign
    assert "<% server.port %>" in (ws / "config/app.toml.latte").read_text()


def test_legacy_registry_propagates(ws: Path) -> None:
    (ws / "templatte.toml").write_text('"./a_b" = "c"\n')
    with pytest.raises(LegacyRegistryError):
        generate(ws)


def test_traversal_config_rejected(ws: Path, tmp_path_factory: pytest.TempPathFactory) -> None:
    from templatte.core.exceptions import PathTraversalError

    with pytest.raises(PathTraversalError):
        generate(ws, config_file=Path("../outside.toml"))

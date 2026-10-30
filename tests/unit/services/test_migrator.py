"""Unit tests for the legacy registry migrator."""

from __future__ import annotations

from pathlib import Path

import pytest

from templatte.core.exceptions import ValidationError
from templatte.core.registry import RegistryManager
from templatte.core.services.deployer import deploy
from templatte.core.services.migrator import migrate, quote_placeholders

LEGACY = """\
"./config/app.toml_title" = "demo"
"./config/app.toml_db.user_name" = "bob"
"./config/app.toml_auth.password" = "hunter2"
"./config/app.toml_server.port" = 8080
"./config/app.toml_server.host" = "0.0.0.0"
"./config/app.toml_extra.toml_x" = 1
"./svc_a/b_c.toml_name" = "svc"
"""

APP_LATTE = (
    "# app\n"
    "title = {{title}}\n"
    "server.port = {{{server.port}}}\n"
    "server.host = {{server.host}}\n"
    "db.user_name = {{ db.user_name }}\n"
    'auth.password = "{{ auth.password }}"\n'
)
APP_CONCRETE = '# app\ntitle = "demo"\nserver.port = 8080\nserver.host = "0.0.0.0"\ndb.user_name = "bob"\nauth.password = "hunter2"\n'


@pytest.fixture
def legacy_ws(tmp_path: Path) -> Path:
    (tmp_path / "templatte.toml").write_text(LEGACY, encoding="utf-8", newline="\n")
    (tmp_path / "config").mkdir()
    (tmp_path / "config/app.toml.latte").write_text(APP_LATTE, encoding="utf-8", newline="\n")
    (tmp_path / "config/app.toml_extra.toml.latte").write_text(
        "x = {{x}}\n", encoding="utf-8", newline="\n"
    )
    (tmp_path / "svc_a").mkdir()
    (tmp_path / "svc_a/b_c.toml.latte").write_text(
        "name = {{name}}\n", encoding="utf-8", newline="\n"
    )
    return tmp_path


def _tree(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_longest_prefix_attribution(legacy_ws: Path) -> None:
    result = migrate(legacy_ws, force=True)
    reg = RegistryManager(legacy_ws).load(legacy_ws / "templatte.toml")
    assert set(reg.files) == {
        "config/app.toml",
        "config/app.toml_extra.toml",
        "svc_a/b_c.toml",
    }
    assert reg.files["config/app.toml_extra.toml"].values == {"x": 1}
    assert reg.files["config/app.toml"].values == {
        "title": "demo",
        "db.user_name": "bob",
        "auth.password": "hunter2",
        "server.port": 8080,
        "server.host": "0.0.0.0",
    }
    assert reg.files["svc_a/b_c.toml"].values == {"name": "svc"}
    assert reg.version == 1 and reg.default_profile == "default"
    assert reg.files["config/app.toml"].format == "toml"
    assert reg.files["config/app.toml"].secrets == {"auth.password": True}
    assert not result.requires_confirmation


def test_template_rewrite_only_unquoted(legacy_ws: Path) -> None:
    migrate(legacy_ws, force=True)
    text = (legacy_ws / "config/app.toml.latte").read_text(encoding="utf-8")
    assert text == (
        "# app\n"
        'title = "{{ title }}"\n'
        'server.port = "{{ server.port }}"\n'
        'server.host = "{{ server.host }}"\n'
        'db.user_name = "{{ db.user_name }}"\n'
        'auth.password = "{{ auth.password }}"\n'
    )


def test_quote_placeholders_leaves_quoted_and_unknown() -> None:
    src = "a = \"x {{a}} y\"\nb = {{b}}\nc = {{c}}\nd = '{{ d }}'\n"
    out = quote_placeholders(src, ["a", "b", "d"])
    assert out == 'a = "x {{a}} y"\nb = "{{ b }}"\nc = {{c}}\nd = \'{{ d }}\'\n'


def test_round_trip_through_deploy(legacy_ws: Path) -> None:
    migrate(legacy_ws, force=True)
    deploy(legacy_ws)
    assert (legacy_ws / "config/app.toml").read_text(encoding="utf-8") == APP_CONCRETE
    assert (legacy_ws / "config/app.toml_extra.toml").read_text(encoding="utf-8") == "x = 1\n"
    assert (legacy_ws / "svc_a/b_c.toml").read_text(encoding="utf-8") == 'name = "svc"\n'


def test_unattributable_key_errors_and_writes_nothing(legacy_ws: Path) -> None:
    with (legacy_ws / "templatte.toml").open("a", encoding="utf-8", newline="\n") as f:
        f.write('"./ghost.toml_k" = 1\n')
    before = _tree(legacy_ws)
    with pytest.raises(ValidationError) as ei:
        migrate(legacy_ws, force=True, backup=True)
    assert ei.value.details["unattributed_keys"] == ["./ghost.toml_k"]
    assert _tree(legacy_ws) == before


def test_unsupported_format_template_cannot_own_keys(tmp_path: Path) -> None:
    (tmp_path / "templatte.toml").write_text('"./a.txt_k" = 1\n', encoding="utf-8", newline="\n")
    (tmp_path / "a.txt.latte").write_text("k = {{k}}\n", encoding="utf-8", newline="\n")
    with pytest.raises(ValidationError):
        migrate(tmp_path, force=True)


def test_already_current_is_noop(tmp_path: Path) -> None:
    (tmp_path / "templatte.toml").write_text("version = 1\n", encoding="utf-8", newline="\n")
    before = _tree(tmp_path)
    result = migrate(tmp_path, force=True, backup=True)
    assert result.nothing_to_migrate and result.exit_code == 0
    assert _tree(tmp_path) == before


def test_missing_registry_is_validation_error(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        migrate(tmp_path)


def test_dry_run_writes_nothing(legacy_ws: Path) -> None:
    before = _tree(legacy_ws)
    result = migrate(legacy_ws, dry_run=True, force=True)
    assert result.dry_run and not result.requires_confirmation
    assert result.templates_rewritten
    assert {f.path for f in result.files} >= {"config/app.toml"}
    assert _tree(legacy_ws) == before


def test_requires_confirmation_without_force(legacy_ws: Path) -> None:
    before = _tree(legacy_ws)
    result = migrate(legacy_ws)
    assert result.requires_confirmation
    assert _tree(legacy_ws) == before


def test_backup_registry_and_rewritten_templates(
    legacy_ws: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("templatte.core.services._common.timestamp", lambda: "T")
    result = migrate(legacy_ws, force=True, backup=True)
    assert "templatte.toml.T.bak" in result.backups
    assert (legacy_ws / "templatte.toml.T.bak").read_text(encoding="utf-8") == LEGACY
    assert (legacy_ws / "config/app.toml.latte.T.bak").read_text(encoding="utf-8") == APP_LATTE
    assert len(result.backups) == 1 + len(result.templates_rewritten)


def test_second_run_is_noop(legacy_ws: Path) -> None:
    migrate(legacy_ws, force=True)
    assert migrate(legacy_ws, force=True).nothing_to_migrate

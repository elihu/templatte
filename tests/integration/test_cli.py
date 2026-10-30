"""Integration tests driving the real Typer app in tmp_path workspaces."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner, Result

from templatte.adapters.crypto import AesGcmCryptoEngine
from templatte.cli.app import app
from templatte.main import app as main_app

PASS = "correct horse battery staple"
APP_TOML = '[db]\nhost = "localhost"\npassword = "hunter2"\n'
LEGACY = '"./config/app.toml_title" = "demo"\n"./config/app.toml_db.user" = "bob"\n'

Invoke = Callable[..., Result]


@pytest.fixture(autouse=True)
def fast_crypto(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "templatte.core.services.crypto.AesGcmCryptoEngine",
        lambda: AesGcmCryptoEngine(iterations=100_000),
    )


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    (tmp_path / "config").mkdir()
    (tmp_path / "config/app.toml").write_text(APP_TOML)
    return tmp_path


@pytest.fixture
def invoke(ws: Path) -> Invoke:
    runner = CliRunner()

    def _invoke(
        *args: str,
        globals_: tuple[str, ...] = ("--json",),
        input: str | None = None,
        env: Mapping[str, str | None] | None = None,
    ) -> Result:
        full_env: dict[str, str | None] = {"TEMPLATTE_PASSPHRASE": None, "NO_COLOR": None}
        full_env.update(env or {})
        return runner.invoke(app, ["-w", str(ws), *globals_, *args], input=input, env=full_env)

    return _invoke


def doc(result: Result) -> dict[str, Any]:
    parsed = json.loads(result.stdout)
    assert isinstance(parsed, dict)
    return parsed


def latte_snapshot(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*.latte")}


@pytest.fixture
def brewed(ws: Path, invoke: Invoke) -> Path:
    assert invoke("genelatte").exit_code == 0
    return ws


# --- JSON for every command ------------------------------------------------------------


def test_genelatte_json(ws: Path, invoke: Invoke) -> None:
    r = invoke("genelatte")
    d = doc(r)
    assert r.exit_code == 0
    assert d["status"] == "success" and d["command"] == "genelatte" and d["exit_code"] == 0
    assert d["workspace"] == str(ws)
    assert sorted(d["generated_templates"]) == ["config/app.toml.latte"]
    assert d["values_file"] == "templatte.toml"
    assert d["total_keys_extracted"] == 2
    assert d["warnings"] == [] and d["skipped_existing"] == [] and d["manual_review"] == []
    assert (ws / "config/app.toml.latte").is_file()


def test_genelatte_dry_run_writes_nothing(ws: Path, invoke: Invoke) -> None:
    d = doc(invoke("genelatte", "--dry-run"))
    assert d["dry_run"] is True and d["generated_templates"]
    assert not (ws / "templatte.toml").exists()


def test_genelatte_existing_latte_skipped_with_warning(brewed: Path, invoke: Invoke) -> None:
    r = invoke("genelatte")
    d = doc(r)
    assert r.exit_code == 0
    assert d["skipped_existing"] == ["config/app.toml.latte"]
    assert len(d["warnings"]) == 1


def test_genelatte_manual_review_exits_3(ws: Path, invoke: Invoke) -> None:
    (ws / "config/other.toml").write_text('x = "${{ secrets.X }}"\n')
    r = invoke("genelatte")
    d = doc(r)
    assert r.exit_code == 3
    assert d["status"] == "warning" and d["exit_code"] == 3
    assert d["manual_review"] == ["config/other.toml"]


def test_deploy_dry_run_and_real_json(brewed: Path, invoke: Invoke) -> None:
    d = doc(invoke("deploy", "--dry-run", "--diff"))
    assert d["dry_run"] is True
    assert d["target_files"] == [
        {
            "template": "config/app.toml.latte",
            "destination": "config/app.toml",
            "action": "unchanged",
        }
    ]
    assert d["missing_keys"] == [] and "diffs" in d

    (brewed / "config/app.toml").unlink()
    d = doc(invoke("deploy", "--dry-run"))
    assert d["target_files"][0]["action"] == "would_create"
    assert "diffs" not in d
    assert not (brewed / "config/app.toml").exists()

    d = doc(invoke("deploy"))
    assert d["target_files"][0]["action"] == "create"
    assert (brewed / "config/app.toml").read_text() == APP_TOML


def test_check_grind_press_pour_migrate_json(brewed: Path, invoke: Invoke) -> None:
    invoke("deploy")
    d = doc(invoke("check"))
    assert (
        d["status"] == "success"
        and d["findings"] == []
        and d["summary"]
        == {
            "errors": 0,
            "warnings": 0,
        }
    )

    d = doc(invoke("grind", "--dry-run"))
    assert d["dry_run"] is True and d["to_delete"] == ["config/app.toml"]
    assert (brewed / "config/app.toml").exists()
    d = doc(invoke("grind", "--force"))
    assert d["deleted"] == ["config/app.toml"] and d["skipped_tracked"] == []

    d = doc(invoke("press", "--passphrase-env", "MY_PW", env={"MY_PW": PASS}))
    assert d["output"] == "templatte.toml.enc" and d["plain_removed"] is True
    d = doc(invoke("pour", env={"TEMPLATTE_PASSPHRASE": PASS}))
    assert d["output"] == "templatte.toml" and d["encrypted_removed"] is False

    d = doc(invoke("migrate"))
    assert d["nothing_to_migrate"] is True and d["exit_code"] == 0


# --- exit codes ---------------------------------------------------------------------------


def test_missing_registry_exit_3(invoke: Invoke) -> None:
    for cmd in ("deploy", "check", "press"):
        r = invoke(cmd, "--passphrase", PASS) if cmd == "press" else invoke(cmd)
        d = doc(r)
        assert r.exit_code == 3, cmd
        assert d["status"] == "error" and d["exit_code"] == 3
        assert d["error_type"] == "ValidationError"


def test_missing_values_exit_3(brewed: Path, invoke: Invoke) -> None:
    reg = brewed / "templatte.toml"
    reg.write_text("\n".join(ln for ln in reg.read_text().splitlines() if "hunter2" not in ln))
    r = invoke("deploy")
    d = doc(r)
    assert r.exit_code == 3 and d["error_type"] == "MissingValuesError"
    assert "db.password" in json.dumps(d["details"])
    r = invoke("check")
    assert r.exit_code == 3 and doc(r)["findings"][0]["kind"] == "missing_values"


def test_wrong_passphrase_exit_4(brewed: Path, invoke: Invoke) -> None:
    assert invoke("press", "--passphrase", PASS).exit_code == 0
    r = invoke("pour", "--passphrase", "totally wrong passphrase")
    assert r.exit_code == 4
    assert doc(r)["exit_code"] == 4
    assert not (brewed / "templatte.toml").exists()


def test_corrupted_envelope_exit_4(brewed: Path, invoke: Invoke) -> None:
    assert invoke("press", "--passphrase", PASS).exit_code == 0
    (brewed / "templatte.toml.enc").write_text("{not an envelope")
    r = invoke("pour", "--passphrase", PASS)
    assert r.exit_code == 4
    assert doc(r)["error_type"] == "CorruptedEnvelopeError"


def test_weak_passphrase_exit_4(brewed: Path, invoke: Invoke) -> None:
    r = invoke("press", "--passphrase", "short")
    assert r.exit_code == 4 and doc(r)["error_type"] == "WeakPassphraseError"


def test_drift_exit_5(brewed: Path, invoke: Invoke) -> None:
    invoke("deploy")
    (brewed / "config/app.toml").write_text('[db]\nhost = "changed"\npassword = "hunter2"\n')
    r = invoke("check")
    d = doc(r)
    assert r.exit_code == 5
    assert d["status"] == "warning" and d["findings"][0]["kind"] == "drift"
    assert "changed" in d["findings"][0]["diff"]


def test_usage_errors_exit_2(ws: Path, invoke: Invoke) -> None:
    assert invoke("deploy", "--nope").exit_code == 2
    assert invoke("bogus").exit_code == 2
    assert CliRunner().invoke(app, ["-w", str(ws / "missing"), "check"]).exit_code == 2
    # No passphrase source and nothing interactive: service UsageError.
    invoke("genelatte")
    r = invoke("press")
    assert r.exit_code == 2 and doc(r)["error_type"] == "UsageError"


def test_unexpected_exception_exit_1(
    brewed: Path, invoke: Invoke, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_a: object, **_k: object) -> None:
        raise RuntimeError("kaboom")

    monkeypatch.setattr("templatte.cli.commands.check.check_service", boom)
    r = invoke("check")
    assert r.exit_code == 1
    assert doc(r) == {
        "status": "error",
        "exit_code": 1,
        "error_type": "RuntimeError",
        "message": "kaboom",
    }
    assert "Traceback" not in r.stderr
    r = invoke("check", globals_=("--json", "--verbose"))
    assert r.exit_code == 1 and "Traceback" in r.stderr and "kaboom" in r.stderr
    json.loads(r.stdout)


def test_human_error_goes_to_stderr(ws: Path, invoke: Invoke) -> None:
    r = invoke("deploy", globals_=())
    assert r.exit_code == 3
    assert "error:" in r.stderr and "genelatte" in r.stderr
    assert r.stdout == ""


def test_keyboard_interrupt_exit_130(
    brewed: Path, invoke: Invoke, monkeypatch: pytest.MonkeyPatch
) -> None:
    def interrupt(*_a: object, **_k: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr("templatte.cli.commands.check.check_service", interrupt)
    assert invoke("check").exit_code == 130


# --- full cycle, invariants ---------------------------------------------------------------


def test_full_cycle_and_latte_immutability(ws: Path, invoke: Invoke) -> None:
    assert invoke("genelatte").exit_code == 0
    latte = latte_snapshot(ws)
    assert latte
    assert invoke("deploy").exit_code == 0
    assert latte_snapshot(ws) == latte
    assert (ws / "config/app.toml").read_text() == APP_TOML
    assert invoke("check").exit_code == 0
    assert invoke("grind", "--force").exit_code == 0
    assert not (ws / "config/app.toml").exists()
    assert latte_snapshot(ws) == latte
    original_registry = (ws / "templatte.toml").read_bytes()
    assert invoke("press", "--passphrase", PASS).exit_code == 0
    assert not (ws / "templatte.toml").exists()
    assert (ws / "templatte.toml.enc").is_file()
    assert invoke("pour", "--passphrase", PASS).exit_code == 0
    assert (ws / "templatte.toml").read_bytes() == original_registry
    assert invoke("deploy").exit_code == 0
    assert (ws / "config/app.toml").read_text() == APP_TOML
    assert latte_snapshot(ws) == latte


def test_pour_no_keep_encrypted_and_force_backup(brewed: Path, invoke: Invoke) -> None:
    invoke("press", "--passphrase", PASS, "--keep-plain")
    r = invoke("pour", "--passphrase", PASS)
    assert r.exit_code == 2  # output exists, no --force
    d = doc(invoke("pour", "--passphrase", PASS, "--force", "--backup", "--no-keep-encrypted"))
    assert d["encrypted_removed"] is True and d["backup"].startswith("templatte.toml.")
    assert not (brewed / "templatte.toml.enc").exists()


# --- passphrase sources -----------------------------------------------------------------


@pytest.mark.parametrize("source", ["file", "env", "custom-env", "stdin"])
def test_passphrase_sources(brewed: Path, invoke: Invoke, source: str, tmp_path: Path) -> None:
    kwargs: dict[str, Any] = {}
    args: list[str] = []
    if source == "file":
        pf = brewed / "pw.txt"
        pf.write_text(PASS + "\n")
        args = ["--passphrase-file", str(pf)]
    elif source == "env":
        kwargs["env"] = {"TEMPLATTE_PASSPHRASE": PASS}
    elif source == "custom-env":
        args = ["--passphrase-env", "OTHER_PW"]
        kwargs["env"] = {"OTHER_PW": PASS}
    else:
        kwargs["input"] = PASS + "\n"
    assert invoke("press", *args, **kwargs).exit_code == 0
    assert (brewed / "templatte.toml.enc").is_file()
    assert invoke("pour", *args, **kwargs).exit_code == 0
    assert (brewed / "templatte.toml").is_file()


def test_passphrase_flag_warns_on_stderr_only(brewed: Path, invoke: Invoke) -> None:
    r = invoke("press", "--passphrase", PASS)
    assert r.exit_code == 0
    assert "--passphrase" in r.stderr
    json.loads(r.stdout)  # stdout still exactly one JSON document


# --- non-interactive / interactive confirmation ------------------------------------------


def test_noninteractive_deploy_without_force_exit_2(brewed: Path, invoke: Invoke) -> None:
    invoke("deploy")
    target = brewed / "config/app.toml"
    target.write_text("# local edit\n")
    for globals_ in (("--json",), ()):
        r = invoke("deploy", globals_=globals_)
        assert r.exit_code == 2
        assert target.read_text() == "# local edit\n"
    assert "--force" in invoke("deploy", globals_=()).stderr


def test_noninteractive_grind_without_force_exit_2(brewed: Path, invoke: Invoke) -> None:
    invoke("deploy")
    r = invoke("grind")
    assert r.exit_code == 2
    assert (brewed / "config/app.toml").exists()


@pytest.fixture
def tty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("templatte.cli.output.stdin_is_tty", lambda: True)


def test_interactive_deploy_confirm_yes_and_no(brewed: Path, invoke: Invoke, tty: None) -> None:
    invoke("deploy")
    target = brewed / "config/app.toml"
    target.write_text("# local edit\n")
    r = invoke("deploy", globals_=(), input="n\n")
    assert r.exit_code != 0 and target.read_text() == "# local edit\n"
    assert "Deploy will overwrite 1 existing files. Proceed? [y/N]" in r.output
    r = invoke("deploy", globals_=(), input="y\n")
    assert r.exit_code == 0 and target.read_text() == APP_TOML
    # --json is never interactive, even on a TTY.
    target.write_text("# local edit\n")
    assert invoke("deploy", input="y\n").exit_code == 2


def test_interactive_grind_confirm_yes_and_no(brewed: Path, invoke: Invoke, tty: None) -> None:
    invoke("deploy")
    target = brewed / "config/app.toml"
    r = invoke("grind", globals_=(), input="n\n")
    assert r.exit_code != 0 and target.exists()
    assert "Grind will delete 1 concrete configuration files. Proceed? [y/N]" in r.output
    r = invoke("grind", globals_=(), input="y\n")
    assert r.exit_code == 0 and not target.exists()


# --- aliases and global options -----------------------------------------------------------


def test_roast_alias_and_hidden(brewed: Path, invoke: Invoke) -> None:
    invoke("deploy")
    r = invoke("roast")
    assert r.exit_code == 0 and doc(r)["command"] == "check"
    help_ = CliRunner().invoke(app, ["--help"])
    assert "roast" not in help_.stdout and "check" in help_.stdout


def test_global_options_must_precede_command(ws: Path) -> None:
    runner = CliRunner()
    assert runner.invoke(app, ["genelatte", "-w", str(ws)]).exit_code == 2
    assert runner.invoke(app, ["-w", str(ws), "genelatte", "--json"]).exit_code == 2
    assert runner.invoke(app, ["--json", "-w", str(ws), "genelatte"]).exit_code == 0


def test_config_file_relative_to_workspace(
    ws: Path, monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
) -> None:
    elsewhere = tmp_path_factory.mktemp("cwd")
    monkeypatch.chdir(elsewhere)
    runner = CliRunner()
    base = ["-w", str(ws), "--json", "-c", "conf/reg.toml"]
    r = runner.invoke(app, [*base, "genelatte"])
    assert r.exit_code == 0 and json.loads(r.stdout)["values_file"] == "conf/reg.toml"
    assert (ws / "conf/reg.toml").is_file()
    assert not (elsewhere / "conf").exists() and not (ws / "templatte.toml").exists()
    assert runner.invoke(app, [*base, "deploy"]).exit_code == 0
    absolute = ["-w", str(ws), "--json", "-c", str(ws / "conf/reg.toml")]
    assert runner.invoke(app, [*absolute, "check"]).exit_code == 0


def test_profile_option_applies(brewed: Path, invoke: Invoke) -> None:
    with (brewed / "templatte.toml").open("a") as f:
        f.write('\n[profiles.prod."config/app.toml".values]\n"db.host" = "prod-host"\n')
    d = doc(invoke("deploy", "--force", globals_=("--json", "-p", "prod")))
    assert d["target_files"][0]["action"] == "overwrite"
    assert 'host = "prod-host"' in (brewed / "config/app.toml").read_text()


def test_no_color_and_no_ansi_in_human_output(brewed: Path, invoke: Invoke) -> None:
    for globals_, env in (((), {"NO_COLOR": "1"}), (("--no-color",), {})):
        r = invoke("check", globals_=globals_, env=env)
        assert r.exit_code == 0 and "\x1b" not in r.output and "check" in r.stdout


def test_main_entrypoint_importable() -> None:
    assert main_app is app


# --- legacy registry -----------------------------------------------------------------------


@pytest.fixture
def legacy(ws: Path) -> Path:
    (ws / "templatte.toml").write_text(LEGACY)
    (ws / "config/app.toml").unlink()
    (ws / "config/app.toml.latte").write_text("title = {{title}}\ndb.user = {{{db.user}}}\n")
    return ws


def test_legacy_registry_refused_with_hint(legacy: Path, invoke: Invoke) -> None:
    for cmd in (["genelatte"], ["deploy"], ["grind"], ["check"], ["press", "--passphrase", PASS]):
        r = invoke(*cmd, globals_=())
        assert r.exit_code == 3, cmd
        assert "templatte migrate" in r.stderr, cmd
        r = invoke(*cmd)
        assert doc(r)["error_type"] == "LegacyRegistryError"
        assert doc(r)["details"]["action_required"] == "templatte migrate"


def test_migrate_cycle(legacy: Path, invoke: Invoke) -> None:
    before = (legacy / "templatte.toml").read_bytes()
    d = doc(invoke("migrate", "--dry-run"))
    assert d["dry_run"] is True and d["templates_rewritten"] == ["config/app.toml.latte"]
    assert (legacy / "templatte.toml").read_bytes() == before

    r = invoke("migrate")  # non-interactive without --force
    assert r.exit_code == 2 and (legacy / "templatte.toml").read_bytes() == before

    d = doc(invoke("migrate", "--force", "--backup"))
    assert d["nothing_to_migrate"] is False and len(d["backups"]) == 2
    assert d["files"][0]["path"] == "config/app.toml"
    assert invoke("deploy").exit_code == 0
    assert (legacy / "config/app.toml").read_text() == 'title = "demo"\ndb.user = "bob"\n'
    assert invoke("check").exit_code == 0


def test_migrate_interactive_confirm(legacy: Path, invoke: Invoke, tty: None) -> None:
    before = (legacy / "templatte.toml").read_bytes()
    r = invoke("migrate", globals_=(), input="n\n")
    assert r.exit_code != 0 and (legacy / "templatte.toml").read_bytes() == before
    r = invoke("migrate", globals_=(), input="y\n")
    assert r.exit_code == 0 and (legacy / "templatte.toml").read_bytes() != before


def test_migrate_unattributable_exit_3(legacy: Path, invoke: Invoke) -> None:
    with (legacy / "templatte.toml").open("a") as f:
        f.write('"./ghost.toml_k" = 1\n')
    before = (legacy / "templatte.toml").read_bytes()
    r = invoke("migrate", "--force")
    assert r.exit_code == 3 and "ghost" in json.dumps(doc(r))
    assert (legacy / "templatte.toml").read_bytes() == before

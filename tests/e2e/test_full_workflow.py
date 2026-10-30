"""End-to-end lifecycle suite (TASK-602), driven through the real Typer app.

Implements the scenario matrix of ``03_AGENT_HARNESS_AND_TASKS.md`` Phase 6.
Every section below is labelled ``STEP n`` after the matrix row it asserts.

Fixture design (Invariant 6): each fixture under ``tests/fixtures/workspace`` is
written in its format's *already-normalized lexical form* (for example the YAML
inline comment sits at the column ruamel re-emits it at, and TOML scalars use
canonical double-quoted/decimal spelling). Consequently the catalogued
normalizations in ``tests/unit/adapters/test_fidelity_matrix.py`` are no-ops on
these files and STEP 7(c) can demand plain byte equality for every format
instead of inventing new allowed differences.
"""

from __future__ import annotations

import configparser
import hashlib
import json
import os
import re
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import tomlkit
from ruamel.yaml import YAML
from typer.testing import CliRunner, Result

from templatte.adapters.crypto import AesGcmCryptoEngine
from templatte.cli.app import app

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "workspace"
PASSPHRASE = "dummy passphrase for the e2e suite"
CONCRETE = [
    ".env",
    "config/app.toml",
    "config/data.json",
    "config/legacy.ini",
    "config/services.yaml",
]
LATTES = [f"{p}.latte" for p in CONCRETE]

# Every key genelatte must extract into templatte.toml, per file (STEP 1).
EXPECTED_KEYS: dict[str, set[str]] = {
    ".env": {"APP_NAME", "GREETING", "EMPTY", "PORT", "API_SECRET_KEY"},
    "config/app.toml": {
        "title",
        "server.host",
        "server.port",
        "server.tls.enabled",
        "server.tls.cert",
        "server.limits.max_connections",
        "server.timeouts.read",
        "database.name",
        "database.credentials.user",
        "database.credentials.password",
        "database.description",
        "services[0].name",
        "services[0].replicas",
        "services[1].name",
        "services[1].replicas",
        "logging.level",
        "logging.paths",
    },
    "config/data.json": {
        "name",
        "version",
        "features.search",
        "features.limits.max_items",
        "features.limits.ratio",
        "tags",
        "endpoints[0].path",
        "endpoints[0].public",
        "endpoints[1].path",
        "endpoints[1].public",
    },
    "config/legacy.ini": {
        "general.name",
        "general.debug",
        "database.host",
        "database.port",
        "database.secret",
        "paths.root",
    },
    "config/services.yaml": {
        "defaults.timeout",
        "defaults.retries",
        "web.name",
        "web.ports",
        "web.env.mode",
        "web.env.api_token",
        "workers[0].name",
        "workers[0].queue",
        "workers[1].name",
        "workers[1].queue",
    },
}

Invoke = Callable[..., Result]


# --- helpers -----------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def hermetic(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fast KDF, no global/system git config, no ambient passphrase."""
    monkeypatch.setattr(
        "templatte.core.services.crypto.AesGcmCryptoEngine",
        lambda: AesGcmCryptoEngine(iterations=100_000),
    )
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.delenv("TEMPLATTE_PASSPHRASE", raising=False)


def tree_digest(root: Path) -> dict[str, str]:
    return {
        p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def snapshot(ws: Path, rels: list[str]) -> dict[str, bytes]:
    return {r: (ws / r).read_bytes() for r in rels}


def git(ws: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=ws, check=True, capture_output=True, text=True, encoding="utf-8"
    )


@pytest.fixture
def fixtures_untouched() -> Any:
    before = tree_digest(FIXTURES)
    yield before
    assert tree_digest(FIXTURES) == before, "tests/fixtures was modified"


@pytest.fixture
def ws(tmp_path: Path, fixtures_untouched: Any) -> Path:
    root = tmp_path / "ws"
    shutil.copytree(FIXTURES, root)
    git(root, "init", "-q")
    git(root, "config", "user.email", "e2e@example.com")
    git(root, "config", "user.name", "E2E")
    git(root, "config", "commit.gpgsign", "false")
    return root


@pytest.fixture
def invoke(ws: Path) -> Invoke:
    runner = CliRunner()

    def _invoke(*args: str) -> Result:
        # Always the same -w <ws>: a mismatched workspace between steps is a bug.
        return runner.invoke(app, ["-w", str(ws), "--no-color", *args])

    return _invoke


@pytest.fixture
def passfile(tmp_path: Path) -> Path:
    f = tmp_path / "passphrase.txt"
    f.write_bytes(PASSPHRASE.encode("utf-8"))
    return f


def ok(result: Result, code: int = 0) -> None:
    assert result.exit_code == code, f"exit {result.exit_code}\n{result.stdout}\n{result.stderr}"


# --- native-parser data models (key order preserved as ordered pair lists) --------------


def _ordered(obj: Any) -> Any:
    if isinstance(obj, dict):
        return [(k, _ordered(v)) for k, v in obj.items()]
    if isinstance(obj, list):
        return [_ordered(v) for v in obj]
    return obj


def model_toml(text: str) -> Any:
    return _ordered(tomlkit.parse(text).unwrap())


def model_yaml(text: str) -> Any:
    return _ordered(YAML(typ="safe").load(text))


def model_json(text: str) -> Any:
    return json.loads(text, object_pairs_hook=lambda pairs: [(k, _ordered(v)) for k, v in pairs])


def model_ini(text: str) -> Any:
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str  # type: ignore[assignment,method-assign]
    parser.read_string(text)
    return [(s, list(parser.items(s))) for s in parser.sections()]


def model_env(text: str) -> Any:
    out = []
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, _, value = line.partition("=")
        if len(value) >= 2 and value[0] == value[-1] == '"':
            value = value[1:-1]
        out.append((key, value))
    return out


MODELS: dict[str, Callable[[str], Any]] = {
    ".env": model_env,
    "config/app.toml": model_toml,
    "config/data.json": model_json,
    "config/legacy.ini": model_ini,
    "config/services.yaml": model_yaml,
}

_INLINE_COMMENT = re.compile(r"\s#\s.*$")


def comments(text: str) -> list[str]:
    """Whole-line and inline comments, whitespace-normalized."""
    found = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(("#", ";")):
            found.append(" ".join(stripped.split()))
        elif m := _INLINE_COMMENT.search(line):
            found.append(" ".join(m.group(0).split()))
    return found


# --- the lifecycle -----------------------------------------------------------------------


def test_full_workflow(ws: Path, invoke: Invoke, passfile: Path) -> None:
    # STEP 0: snapshot every original fixture file before any Templatte command.
    original = snapshot(ws, CONCRETE)
    for rel, data in original.items():
        assert data == (FIXTURES / rel).read_bytes()
    assert not list(ws.rglob("*.latte"))

    # STEP 1: genelatte creates a .latte per fixture, registry holds every key,
    # originals untouched.
    ok(invoke("genelatte"))
    for rel in LATTES:
        assert (ws / rel).is_file(), rel
    assert snapshot(ws, CONCRETE) == original, "STEP 1: originals were modified"
    registry_doc = tomlkit.parse((ws / "templatte.toml").read_text(encoding="utf-8")).unwrap()
    for rel, keys in EXPECTED_KEYS.items():
        assert set(registry_doc["files"][rel]["values"]) == keys, f"STEP 1: {rel}"
    assert registry_doc["files"][".env"]["secrets"]["API_SECRET_KEY"] is True
    latte_bytes = snapshot(ws, LATTES)  # reference for Invariant 1

    def assert_lattes_untouched(step: str) -> None:
        assert snapshot(ws, LATTES) == latte_bytes, f"Invariant 1 violated at {step}"

    # STEP 2: deploy regenerates concrete files; .latte untouched (Invariant 1).
    # Originals exist and are byte-equal, so no --force is needed.
    ok(invoke("deploy"))
    assert_lattes_untouched("STEP 2 deploy")
    for rel in CONCRETE:
        assert (ws / rel).is_file()

    # STEP 3: grind removes concrete files; .latte and registry untouched.
    registry_before_grind = (ws / "templatte.toml").read_bytes()
    ok(invoke("grind", "--force"))
    for rel in CONCRETE:
        assert not (ws / rel).exists(), f"STEP 3: {rel} still present"
    assert_lattes_untouched("STEP 3 grind")
    assert (ws / "templatte.toml").read_bytes() == registry_before_grind

    # STEP 4: press creates the envelope and removes the plaintext registry.
    registry_plain = (ws / "templatte.toml").read_bytes()
    ok(invoke("press", "--passphrase-file", str(passfile)))
    assert (ws / "templatte.toml.enc").is_file()
    assert not (ws / "templatte.toml").exists()
    assert PASSPHRASE.encode() not in (ws / "templatte.toml.enc").read_bytes()
    assert b"dummy-password-0000" not in (ws / "templatte.toml.enc").read_bytes()
    assert_lattes_untouched("STEP 4 press")

    # STEP 5: pour restores a byte-identical registry.
    ok(invoke("pour", "--passphrase-file", str(passfile)))
    assert (ws / "templatte.toml").read_bytes() == registry_plain
    assert_lattes_untouched("STEP 5 pour")

    # STEP 6: deploy regenerates the concrete files again.
    ok(invoke("deploy"))
    assert_lattes_untouched("STEP 6 deploy")
    after_step6 = snapshot(ws, CONCRETE)

    # STEP 7: fidelity of each regenerated file against its STEP 0 snapshot.
    for rel in CONCRETE:
        before = original[rel].decode("utf-8")
        after = after_step6[rel].decode("utf-8")
        # 7(a) semantic equivalence incl. key order, via the native parser.
        assert MODELS[rel](after) == MODELS[rel](before), f"STEP 7a: {rel}"
        # 7(b) every comment survives.
        assert set(comments(before)) <= set(comments(after)), f"STEP 7b comments: {rel}"
        # 7(c) byte equality (fixtures are in normalized form, see module docstring;
        # .env and INI are byte-exact per Invariant 6 in any case).
        assert after_step6[rel] == original[rel], f"STEP 7c: {rel}"

    toml_after = after_step6["config/app.toml"].decode("utf-8")
    toml_before = original["config/app.toml"].decode("utf-8")
    header = re.compile(r"^\s*\[\[?[^\]]+\]\]?", re.MULTILINE)
    assert len(header.findall(toml_after)) == len(header.findall(toml_before))
    assert toml_after.count("[[services]]") == 2
    assert "credentials = { user = " in toml_after, "STEP 7b: inline table was expanded"
    assert 'description = """first line\nsecond line\n"""' in toml_after
    assert "tls.enabled = false" in toml_after and "tls.cert = " in toml_after

    yaml_after = after_step6["config/services.yaml"].decode("utf-8")
    assert "defaults: &defaults" in yaml_after, "STEP 7b: anchor lost"
    assert "<<: *defaults" in yaml_after, "STEP 7b: merge key expanded"
    assert "ports: [8000, 8001]" in yaml_after, "STEP 7b: flow sequence changed"
    assert yaml_after.count("timeout:") == 1, "STEP 7b: merge key was expanded"

    ini_after = after_step6["config/legacy.ini"].decode("utf-8")
    ini_before = original["config/legacy.ini"].decode("utf-8")
    assert len(model_ini(ini_after)) == len(model_ini(ini_before)) == 3

    # STEP 8: second full round trip leaves every concrete file byte-identical.
    # genelatte needs --force here because the .latte files already exist.
    ok(invoke("genelatte", "--force"))
    ok(invoke("deploy", "--force"))
    assert snapshot(ws, CONCRETE) == after_step6, "STEP 8: fixed point violated"
    assert_lattes_untouched("STEP 8 deploy")

    # STEP 9: no drift, no missing keys, no git leakage.
    result = invoke("check", "--strict")
    ok(result)
    # Fixtures are still pristine inside the workspace sources too.
    assert snapshot(ws, CONCRETE) == original


def test_check_strict_fails_when_concrete_file_is_tracked(ws: Path, invoke: Invoke) -> None:
    """STEP 9 (negative): a force-added concrete file is a git leak -> exit 5."""
    ok(invoke("genelatte"))
    ok(invoke("deploy", "--force"))
    ok(invoke("check", "--strict"))

    git(ws, "add", "-f", "config/app.toml")
    assert "config/app.toml" in git(ws, "ls-files").stdout.split()
    result = invoke("check", "--strict")
    assert result.exit_code == 5, f"{result.stdout}\n{result.stderr}"

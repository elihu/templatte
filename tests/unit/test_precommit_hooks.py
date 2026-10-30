"""The shipped pre-commit hook definition (TASK-601, 04 spec section 3.4)."""

from __future__ import annotations

import shlex
from pathlib import Path

from ruamel.yaml import YAML
from typer.testing import CliRunner

from templatte.cli.app import app

HOOKS_FILE = Path(__file__).resolve().parents[2] / ".pre-commit-hooks.yaml"


def load_hook() -> dict[str, object]:
    with HOOKS_FILE.open(encoding="utf-8") as fh:
        hooks = YAML(typ="safe").load(fh)
    assert isinstance(hooks, list) and len(hooks) == 1
    hook = hooks[0]
    assert isinstance(hook, dict)
    return hook


def test_hook_fields() -> None:
    hook = load_hook()
    assert hook["id"] == "templatte-check"
    assert hook["entry"] == "templatte check --strict"
    assert hook["language"] == "python"
    assert hook["pass_filenames"] is False
    assert hook["always_run"] is True
    assert hook["stages"] == ["pre-commit", "pre-push"]
    assert hook["minimum_pre_commit_version"] == "3.2.0"


def test_hook_entry_is_a_real_command(tmp_path: Path) -> None:
    entry = shlex.split(str(load_hook()["entry"]))
    assert entry[0] == "templatte"
    # Global options precede the command; the hook runs in the workspace (cwd).
    result = CliRunner().invoke(app, ["-w", str(tmp_path), *entry[1:]])
    # Exit 0-5 are the documented codes; 2 with "No such option" would be a usage error.
    assert result.exit_code in {0, 1, 2, 3, 4, 5}
    assert "no such option" not in (result.stdout + result.stderr).lower()

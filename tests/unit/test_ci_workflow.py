"""Static guarantees of the CI workflow (TASK-603, 04 spec sections 5 and 8.3)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
from ruamel.yaml import YAML

WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ci.yml"
PINNED = re.compile(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$")


@pytest.fixture(scope="module")
def workflow() -> dict[str, Any]:
    with WORKFLOW.open(encoding="utf-8") as fh:
        loaded = YAML(typ="safe").load(fh)
    assert isinstance(loaded, dict)
    return loaded


def triggers(workflow: dict[str, Any]) -> dict[str, Any]:
    # YAML 1.1 loaders may read the bare key `on` as the boolean True.
    return workflow["on"] if "on" in workflow else workflow[True]


def test_triggers_are_push_and_pull_request_only(workflow: dict[str, Any]) -> None:
    assert set(triggers(workflow)) == {"push", "pull_request"}
    assert "pull_request_target" not in WORKFLOW.read_text(encoding="utf-8")


def test_top_level_permissions_are_read_only(workflow: dict[str, Any]) -> None:
    assert workflow["permissions"] == {"contents": "read"}


def test_every_action_is_pinned_to_a_full_sha(workflow: dict[str, Any]) -> None:
    uses = [
        step["uses"] for job in workflow["jobs"].values() for step in job["steps"] if "uses" in step
    ]
    assert uses, "workflow has no actions"
    for ref in uses:
        assert PINNED.match(ref), f"action not pinned to a 40-char SHA: {ref}"
    # Each pin carries a trailing version comment.
    for line in WORKFLOW.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith(("- uses:", "uses:")):
            assert re.search(r"@[0-9a-f]{40} # v\d+\.\d+\.\d+$", line), line


def test_matrix(workflow: dict[str, Any]) -> None:
    (job,) = workflow["jobs"].values()
    strategy = job["strategy"]
    assert strategy["fail-fast"] is False
    assert strategy["matrix"]["os"] == ["ubuntu-latest", "macos-latest", "windows-latest"]
    assert strategy["matrix"]["python-version"] == ["3.10", "3.11", "3.12", "3.13"]


def test_steps_and_concurrency(workflow: dict[str, Any]) -> None:
    (job,) = workflow["jobs"].values()
    runs = [step["run"] for step in job["steps"] if "run" in step]
    assert runs == [
        "uv sync --frozen",
        "uv run ruff check .",
        "uv run ruff format --check templatte tests",
        "uv run pytest",
    ]
    assert workflow["concurrency"]["cancel-in-progress"] is True

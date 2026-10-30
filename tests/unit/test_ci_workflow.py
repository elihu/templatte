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


def test_triggers_on_pull_request_only(workflow: dict[str, Any]) -> None:
    assert set(triggers(workflow)) == {"pull_request"}
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


def test_lint_and_test_jobs(workflow: dict[str, Any]) -> None:
    jobs = workflow["jobs"]
    assert set(jobs) == {"lint", "test"}
    runs = {name: [s["run"] for s in job["steps"] if "run" in s] for name, job in jobs.items()}
    assert runs["lint"] == [
        "uv sync --frozen",
        "uv run ruff check .",
        "uv run ruff format --check templatte tests",
    ]
    assert runs["test"] == ["uv sync --frozen", "uv run pytest"]
    matrix = jobs["test"]["strategy"]["matrix"]
    assert matrix["os"] == ["ubuntu-latest", "macos-latest", "windows-latest"]
    assert matrix["python-version"] == ["3.10", "3.13"]

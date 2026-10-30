"""``check`` service: missing values, drift and git leaks (FUNCTIONAL_SPEC §2.6, GIT §3.3)."""

from __future__ import annotations

import difflib
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from templatte.core.exceptions import MissingValuesError
from templatte.core.services._common import (
    adapter_for,
    concrete_of,
    discover_latte,
    load_required_registry,
    plain_values,
    read_text_exact,
    render_with_real_path,
    resolve_config,
    resolve_workspace,
    workspace_rel,
)
from templatte.utils.git import get_tracked_files, is_git_repo
from templatte.utils.ignore import IgnoreMatcher

MISSING_VALUES = "missing_values"
DRIFT = "drift"
GIT_LEAK = "git_leak"
WARNING = "warning"
ERROR = "error"

EXIT_OK = 0
EXIT_MISSING = 3
EXIT_DRIFT = 5


def severity_for(kind: str, strict: bool) -> str:
    """Severity mapping: drift is always an error; leaks and missing values escalate in strict."""
    if kind == DRIFT:
        return ERROR
    return ERROR if strict else WARNING


def exit_code_for(kinds: Iterable[str]) -> int:
    """5 for any drift or git leak (regardless of strict), else 3 for missing values, else 0."""
    present = set(kinds)
    if present & {DRIFT, GIT_LEAK}:
        return EXIT_DRIFT
    if MISSING_VALUES in present:
        return EXIT_MISSING
    return EXIT_OK


@dataclass(frozen=True)
class Finding:
    """A single check finding."""

    kind: str
    severity: str
    path: str  # workspace-relative POSIX concrete (or registry) path
    message: str
    missing_keys: tuple[str, ...] = ()
    diff: str | None = None


@dataclass(frozen=True)
class CheckResult:
    """All findings of a check run."""

    findings: tuple[Finding, ...] = ()

    @property
    def exit_code(self) -> int:
        return exit_code_for(f.kind for f in self.findings)


def check(
    workspace: Path | str,
    config_file: Path | str = Path("templatte.toml"),
    profile: str | None = None,
    *,
    strict: bool = False,
    check_git: bool = True,
) -> CheckResult:
    """Validate templates against the registry and concrete files."""
    root = resolve_workspace(workspace)
    config_path = resolve_config(root, config_file)
    registry = load_required_registry(root, config_path)
    config_rel = workspace_rel(root, config_path)

    findings: list[Finding] = []
    concretes: list[str] = []
    for latte_rel in discover_latte(root):
        rel = concrete_of(latte_rel)
        concretes.append(rel)
        entry = registry.files.get(rel)
        adapter = adapter_for(entry.format if entry else None, rel)
        values = plain_values(registry.get_effective_values(rel, profile))
        try:
            rendered = render_with_real_path(
                adapter, read_text_exact(root / latte_rel), values, registry, rel
            )
        except MissingValuesError as exc:
            findings.append(
                Finding(
                    MISSING_VALUES,
                    severity_for(MISSING_VALUES, strict),
                    rel,
                    f"Missing values for '{rel}': {', '.join(exc.missing_keys)}",
                    missing_keys=tuple(exc.missing_keys),
                )
            )
            continue
        target = root / rel
        if target.is_file():
            try:
                actual = read_text_exact(target)
            except UnicodeDecodeError:
                actual = None
            if actual != rendered:
                diff = "".join(
                    difflib.unified_diff(
                        (actual or "").splitlines(keepends=True),
                        rendered.splitlines(keepends=True),
                        fromfile=f"a/{rel}",
                        tofile=f"b/{rel}",
                    )
                )
                findings.append(
                    Finding(
                        DRIFT,
                        severity_for(DRIFT, strict),
                        rel,
                        f"Configuration drift detected in '{rel}'",
                        diff=diff,
                    )
                )

    if check_git and is_git_repo(root):
        tracked = get_tracked_files(root)  # single `git ls-files` call
        ignored = IgnoreMatcher.from_gitignore(root)
        for rel in sorted({*concretes, config_rel}):
            if rel in tracked:
                reason = "is tracked by Git"
            elif not ignored.matches(rel):
                reason = "is not ignored by .gitignore"
            else:
                continue
            findings.append(
                Finding(
                    GIT_LEAK,
                    severity_for(GIT_LEAK, strict),
                    rel,
                    f"Git Leak Warning: '{rel}' {reason}. "
                    f"Run 'templatte grind' or 'git rm --cached {rel}'",
                )
            )
    return CheckResult(findings=tuple(findings))

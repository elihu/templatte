"""Workspace file discovery for ``genelatte`` (FUNCTIONAL_SPEC §2.1, MASTER_SPEC §6.2).

Discovery is an opt-in whitelist. It deliberately does NOT apply the workspace
``.gitignore``: genelatte itself adds concrete files to it, so honoring it would make
every re-run discover nothing.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from templatte.adapters import get_adapter_for_file
from templatte.core.exceptions import UnsupportedFormatError
from templatte.core.services._common import PRUNE_DIRS
from templatte.utils.ignore import IgnoreMatcher

DEFAULT_FORMATS: tuple[str, ...] = ("toml", "yaml", "json", "ini", "env")
DEFAULT_WHITELIST: tuple[str, ...] = ("*.env", "*.env.*", "config/**", "settings.*")

#: Directory excludes; never overridable.
STANDING_DIR_EXCLUDES: tuple[str, ...] = (
    ".git/**",
    ".venv/**",
    "__pycache__/**",
    "node_modules/**",
    "dist/**",
)
#: Never overridable, not even by ``force_include``.
STANDING_EXCLUDES: tuple[str, ...] = (*STANDING_DIR_EXCLUDES, "templatte.toml*")

HARD_DENYLIST: tuple[str, ...] = (
    "package.json",
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "tsconfig*.json",
    "composer.json",
    "composer.lock",
    "pyproject.toml",
    "uv.lock",
    "poetry.lock",
    "Cargo.toml",
    "Cargo.lock",
    "*.lock",
    ".github/**",
    "docker-compose*.yml",
    "*.latte",
)


@dataclass(frozen=True)
class Candidate:
    """A discovered configuration file and its detected format."""

    path: str  # workspace-relative POSIX
    format: str


@dataclass(frozen=True)
class ScanResult:
    """Outcome of a workspace scan, deterministically sorted."""

    candidates: tuple[Candidate, ...]
    manual_review: tuple[str, ...]


def _has_foreign_delimiters(text: str, open_tag: str, close_tag: str) -> bool:
    pair = re.compile(re.escape(open_tag) + r".*?" + re.escape(close_tag), re.DOTALL)
    if pair.search(text):
        return True
    if open_tag == "{{":
        return re.search(r"\$\{\{.*?" + re.escape(close_tag), text, re.DOTALL) is not None
    return False


def scan_workspace(
    workspace: Path | str,
    formats: Iterable[str] = DEFAULT_FORMATS,
    include: Sequence[str] = (),
    exclude: Sequence[str] = (),
    force_include: bool = False,
    open_tag: str = "{{",
    close_tag: str = "}}",
) -> ScanResult:
    """Discover templatizable configuration files under ``workspace``."""
    root = Path(workspace).resolve()
    wanted = {f.lower() for f in formats}

    whitelist = IgnoreMatcher([*DEFAULT_WHITELIST, *include])
    include_matcher = IgnoreMatcher(include)
    standing = IgnoreMatcher(STANDING_EXCLUDES)
    user_excludes = IgnoreMatcher(exclude)
    denylist = IgnoreMatcher(HARD_DENYLIST)
    # A template of a template makes no sense, so `*.latte` stays blocked even with
    # force_include (conservative reading of the spec).
    latte = IgnoreMatcher(["*.latte"])

    candidates: list[Candidate] = []
    manual: list[str] = []

    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if d not in PRUNE_DIRS)
        for name in sorted(filenames):
            full = Path(dirpath) / name
            if full.is_symlink() or not full.is_file():
                continue
            rel = full.relative_to(root).as_posix()

            if standing.matches(rel) or user_excludes.matches(rel):
                continue
            if not whitelist.matches(rel):
                continue
            if denylist.matches(rel):
                lifted = force_include and include_matcher.matches(rel) and not latte.matches(rel)
                if not lifted:
                    continue

            try:
                adapter = get_adapter_for_file(full)
            except UnsupportedFormatError:
                continue
            if adapter.format_name not in wanted:
                continue

            try:
                text = full.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue

            if _has_foreign_delimiters(text, open_tag, close_tag):
                manual.append(rel)
            else:
                candidates.append(Candidate(path=rel, format=adapter.format_name))

    candidates.sort(key=lambda c: c.path)
    return ScanResult(candidates=tuple(candidates), manual_review=tuple(sorted(manual)))

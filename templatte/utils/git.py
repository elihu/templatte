"""Git helper utilities (ARCHITECTURE §6.2, GIT_AND_WORKFLOW §3).

Only the ``git`` binary is invoked, always with a list argv, ``shell=False`` and
``check=False``. Missing git or a non-repository directory degrade gracefully
instead of raising.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from templatte.core.exceptions import UsageError
from templatte.utils.fs import atomic_write_bytes

BLOCK_START = "# >>> templatte managed >>>"
BLOCK_END = "# <<< templatte managed <<<"
BLOCK_HEADER = "# Templatte values & local runtime configurations."


def _run_git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[bytes] | None:
    """Run ``git <args>`` in ``cwd``; return None if git or the directory is unavailable."""
    try:
        return subprocess.run(
            ["git", *args],
            cwd=cwd,
            shell=False,
            check=False,
            capture_output=True,
        )
    except (FileNotFoundError, NotADirectoryError, PermissionError):
        return None


def _as_dir(path: Path | str) -> Path:
    p = Path(path)
    return p if p.is_dir() else p.parent


def is_git_repo(path: Path | str) -> bool:
    """Return True if ``path`` (or its parent, for a file) is inside a git work tree."""
    result = _run_git(["rev-parse", "--is-inside-work-tree"], _as_dir(path))
    return result is not None and result.returncode == 0 and result.stdout.strip() == b"true"


def get_tracked_files(workspace: Path | str) -> set[str]:
    """Return workspace-relative POSIX paths of all tracked files (one ``git ls-files`` call)."""
    result = _run_git(["ls-files", "-z"], Path(workspace))
    if result is None or result.returncode != 0:
        return set()
    return {
        entry.decode("utf-8", errors="surrogateescape")
        for entry in result.stdout.split(b"\0")
        if entry
    }


def has_uncommitted_changes(path: Path | str) -> bool:
    """Return True if a tracked file's working tree content differs from ``HEAD``.

    Untracked files, clean files, non-repositories and repositories without a
    ``HEAD`` commit all yield False.
    """
    p = Path(path)
    if not is_git_repo(p.parent):  # outside a repo `git diff` degrades to --no-index
        return False
    result = _run_git(["diff", "--quiet", "HEAD", "--", p.name], p.parent)
    return result is not None and result.returncode == 1


def ensure_gitignored(workspace: Path | str, patterns: list[str]) -> bool:
    """Keep the Templatte-managed block of ``.gitignore`` in sync with ``patterns``.

    Creates ``.gitignore`` when absent, appends the block when it has no markers,
    otherwise replaces only the content between the markers. Entries are sorted and
    de-duplicated. Returns True if the file changed (second identical call: False).

    Raises:
        UsageError: the start marker exists without a matching end marker.
    """
    target = Path(workspace) / ".gitignore"
    original = target.read_bytes().decode("utf-8") if target.exists() else None
    text = original or ""
    nl = "\r\n" if "\r\n" in text else "\n"

    entries = sorted({p.strip() for p in patterns if p.strip()})
    block = nl.join([BLOCK_START, BLOCK_HEADER, *entries, BLOCK_END])

    lines = text.splitlines(keepends=True)
    start_idx = next((i for i, ln in enumerate(lines) if ln.strip() == BLOCK_START), None)
    if start_idx is None:
        prefix = text
        if prefix and not prefix.endswith(("\n", "\r")):
            prefix += nl
        if prefix:
            prefix += nl
        new_text = prefix + block + nl
    else:
        end_idx = next(
            (i for i in range(start_idx + 1, len(lines)) if lines[i].strip() == BLOCK_END),
            None,
        )
        if end_idx is None:
            raise UsageError(f"Malformed .gitignore: '{BLOCK_START}' has no matching '{BLOCK_END}'")
        tail = lines[end_idx]
        eol = tail[len(tail.rstrip("\r\n")) :]
        new_text = "".join(lines[:start_idx]) + block + eol + "".join(lines[end_idx + 1 :])

    if original is not None and new_text == original:
        return False
    atomic_write_bytes(target, new_text.encode("utf-8"))
    return True

"""``.gitignore``-compatible pattern evaluation built on ``pathspec`` (ARCHITECTURE §5)."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from pathspec import GitIgnoreSpec


class IgnoreMatcher:
    """Evaluate workspace-relative POSIX paths against gitignore-style patterns.

    Negation (``!``), anchoring (``/``), ``**`` and directory-only patterns follow
    git semantics as implemented by ``pathspec``.
    """

    def __init__(self, patterns: Iterable[str] = ()) -> None:
        self.patterns: tuple[str, ...] = tuple(patterns)
        self._spec = GitIgnoreSpec.from_lines(self.patterns)

    @classmethod
    def from_gitignore(cls, workspace: Path | str) -> IgnoreMatcher:
        """Build a matcher from ``<workspace>/.gitignore`` (empty matcher if absent)."""
        gitignore = Path(workspace) / ".gitignore"
        if not gitignore.is_file():
            return cls([])
        text = gitignore.read_text(encoding="utf-8", errors="replace")
        return cls(text.splitlines())

    def matches(self, rel_posix_path: str) -> bool:
        """Return True if the path is matched (ignored) by the patterns."""
        return bool(self._spec.match_file(rel_posix_path))

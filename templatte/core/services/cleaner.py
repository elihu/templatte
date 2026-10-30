"""``grind`` service: delete concrete files whose ``.latte`` template exists (FUNCTIONAL_SPEC §2.3).

Never touches ``.latte`` files or the registry. Confirmation is the CLI's job: when
neither ``force`` nor ``dry_run`` is set, nothing is deleted and the result carries
``requires_confirmation=True`` plus the candidate list.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from templatte.core.registry import RegistryManager
from templatte.core.services._common import (
    backup_file,
    concrete_of,
    discover_latte,
    resolve_config,
    resolve_workspace,
    workspace_rel,
)
from templatte.utils.git import get_tracked_files, has_uncommitted_changes, is_git_repo


@dataclass(frozen=True)
class GrindResult:
    """Outcome of a grind run (workspace-relative POSIX paths)."""

    to_delete: tuple[str, ...] = ()
    deleted: tuple[str, ...] = ()
    backups: tuple[str, ...] = ()
    skipped_tracked: tuple[str, ...] = ()
    requires_confirmation: bool = False
    dry_run: bool = False

    @property
    def exit_code(self) -> int:
        return 0


def grind(
    workspace: Path | str,
    config_file: Path | str = Path("templatte.toml"),
    *,
    force: bool = False,
    force_tracked: bool = False,
    dry_run: bool = False,
    backup: bool = False,
) -> GrindResult:
    """Delete concrete files that have a ``.latte`` template."""
    root = resolve_workspace(workspace)
    config_path = resolve_config(root, config_file)
    if config_path.is_file():
        # Only validates the schema version (legacy registries are refused); never writes.
        RegistryManager(root).load_document(config_path)

    candidates = [
        concrete_of(latte)
        for latte in discover_latte(root)
        if (root / concrete_of(latte)).is_file()
    ]
    tracked = get_tracked_files(root) if candidates and is_git_repo(root) else set()

    to_delete: list[str] = []
    skipped: list[str] = []
    for rel in candidates:
        if rel in tracked and not force_tracked and has_uncommitted_changes(root / rel):
            skipped.append(rel)
        else:
            to_delete.append(rel)

    if dry_run:
        return GrindResult(to_delete=tuple(to_delete), skipped_tracked=tuple(skipped), dry_run=True)
    if not force:
        return GrindResult(
            to_delete=tuple(to_delete),
            skipped_tracked=tuple(skipped),
            requires_confirmation=bool(to_delete),
        )

    backups: list[str] = []
    deleted: list[str] = []
    for rel in to_delete:
        target = root / rel
        if backup:
            backups.append(workspace_rel(root, backup_file(target)))
        target.unlink()
        deleted.append(rel)
    return GrindResult(
        to_delete=tuple(to_delete),
        deleted=tuple(deleted),
        backups=tuple(backups),
        skipped_tracked=tuple(skipped),
    )

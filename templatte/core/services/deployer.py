"""``deploy`` service: render ``.latte`` templates into concrete files (FUNCTIONAL_SPEC §2.2).

INVARIANT 1: ``.latte`` files are only ever read here, never written, renamed or deleted.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from pathlib import Path

from templatte.core.exceptions import MissingTemplateError, MissingValuesError, ValidationError
from templatte.core.services._common import (
    LATTE_SUFFIX,
    adapter_for,
    backup_file,
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
from templatte.utils.fs import atomic_write_bytes


@dataclass(frozen=True)
class DeployResult:
    """Outcome of a deploy run. Paths are workspace-relative POSIX concrete paths.

    ``created``/``overwritten`` list what was (or, under ``dry_run``, would be) written;
    ``skipped_existing`` are differing files left alone because ``force`` was not set
    (the CLI may prompt and re-run with ``force``).
    """

    created: tuple[str, ...] = ()
    overwritten: tuple[str, ...] = ()
    unchanged: tuple[str, ...] = ()
    skipped_existing: tuple[str, ...] = ()
    backups: tuple[str, ...] = ()
    diffs: dict[str, str] = field(default_factory=dict)
    dry_run: bool = False

    @property
    def exit_code(self) -> int:
        return 0


def _unified(old: str, new: str, rel: str) -> str:
    return "".join(
        difflib.unified_diff(
            old.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile=f"a/{rel}",
            tofile=f"b/{rel}",
        )
    )


def deploy(
    workspace: Path | str,
    config_file: Path | str = Path("templatte.toml"),
    profile: str | None = None,
    *,
    dry_run: bool = False,
    diff: bool = False,
    force: bool = False,
    backup: bool = False,
    file: Path | str | None = None,
) -> DeployResult:
    """Render every ``.latte`` (or just ``file``) into its concrete sibling."""
    root = resolve_workspace(workspace)
    registry = load_required_registry(root, resolve_config(root, config_file))

    if file is not None:
        latte_rel = workspace_rel(root, file)
        if not latte_rel.endswith(LATTE_SUFFIX):
            raise ValidationError(
                f"Not a template file (expected '*{LATTE_SUFFIX}'): '{latte_rel}'",
                details={"file": latte_rel},
            )
        if not (root / latte_rel).is_file():
            raise MissingTemplateError(latte_rel)
        latte_files = [latte_rel]
    else:
        latte_files = discover_latte(root)

    # Phase 1: render everything; write nothing if any placeholder lacks a value.
    rendered: dict[str, str] = {}
    missing: dict[str, list[str]] = {}
    for latte_rel in latte_files:
        rel = concrete_of(latte_rel)
        entry = registry.files.get(rel)
        adapter = adapter_for(entry.format if entry else None, rel)
        values = plain_values(registry.get_effective_values(rel, profile))
        try:
            rendered[rel] = render_with_real_path(
                adapter, read_text_exact(root / latte_rel), values, registry, rel
            )
        except MissingValuesError as exc:
            missing[rel] = exc.missing_keys
    if missing:
        err = MissingValuesError(
            ", ".join(missing),
            [f"{path}: {key}" for path, keys in missing.items() for key in keys],
        )
        err.details["files"] = missing
        raise err

    # Phase 2: decide and (unless dry_run) write.
    created: list[str] = []
    overwritten: list[str] = []
    unchanged: list[str] = []
    skipped: list[str] = []
    backups: list[str] = []
    diffs: dict[str, str] = {}

    for rel, new_text in rendered.items():
        target = root / rel
        old_text: str | None = None
        if target.exists():
            try:
                old_text = read_text_exact(target)
            except UnicodeDecodeError:
                old_text = None  # binary/non-UTF-8: treat as different
        if target.exists() and old_text == new_text:
            unchanged.append(rel)
            continue
        if diff:
            diffs[rel] = _unified(old_text or "", new_text, rel)
        if not target.exists():
            created.append(rel)
        elif force:
            overwritten.append(rel)
            if backup and not dry_run:
                backups.append(workspace_rel(root, backup_file(target)))
        else:
            skipped.append(rel)
            continue
        if not dry_run:
            atomic_write_bytes(target, new_text.encode("utf-8"))

    return DeployResult(
        created=tuple(created),
        overwritten=tuple(overwritten),
        unchanged=tuple(unchanged),
        skipped_existing=tuple(skipped),
        backups=tuple(backups),
        diffs=diffs,
        dry_run=dry_run,
    )

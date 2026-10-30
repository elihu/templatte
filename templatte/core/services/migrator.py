"""``migrate`` service: upgrade a pre-2.0 flat registry to the current schema (FUNCTIONAL_SPEC §2.7).

Legacy layout (pre-2.0 prototype): a flat TOML table whose keys are
``"<file_path>_<dot.key>"`` (the path as walked, usually ``./``-prefixed) and
``.latte`` files with unquoted placeholders (``key = {{key}}`` or ``{{{key}}}``).

This is the only service allowed to modify ``.latte`` files, and only to quote
placeholders of keys it attributed to that file. Confirmation is the CLI's job:
without ``force`` (and not ``dry_run``) nothing is written and the result carries
``requires_confirmation=True``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import tomlkit

from templatte.adapters import get_adapter_for_file
from templatte.core.exceptions import UnsupportedFormatError, ValidationError
from templatte.core.models import FileEntry, ValuesRegistry
from templatte.core.registry import RegistryManager
from templatte.core.services._common import (
    LATTE_SUFFIX,
    backup_file,
    concrete_of,
    discover_latte,
    plain_values,
    read_text_exact,
    resolve_config,
    resolve_workspace,
    workspace_rel,
)
from templatte.core.services.generator import is_credential_shaped
from templatte.utils.fs import atomic_write_bytes


@dataclass(frozen=True)
class MigratedFile:
    """One concrete file's share of the migrated registry."""

    path: str
    format: str
    keys: int
    secrets: int
    template_rewritten: bool


@dataclass(frozen=True)
class MigrateResult:
    """Outcome of a migrate run (workspace-relative POSIX paths)."""

    registry: str
    nothing_to_migrate: bool = False
    files: tuple[MigratedFile, ...] = ()
    templates_rewritten: tuple[str, ...] = ()
    backups: tuple[str, ...] = ()
    requires_confirmation: bool = False
    dry_run: bool = False

    @property
    def exit_code(self) -> int:
        return 0


def _inside_quotes(prefix: str) -> bool:
    """Whether the end of ``prefix`` (text before a match on its line) is within a string."""
    quote: str | None = None
    i = 0
    while i < len(prefix):
        ch = prefix[i]
        if quote is None:
            if ch in "\"'":
                quote = ch
        elif ch == "\\" and quote == '"':
            i += 1
        elif ch == quote:
            quote = None
        i += 1
    return quote is not None


def quote_placeholders(text: str, keys: list[str]) -> str:
    """Replace unquoted ``{{key}}``/``{{ key }}``/``{{{key}}}`` by ``"{{ key }}"``.

    Placeholders already inside a quoted string, and keys not in ``keys``, are untouched;
    every other byte is preserved.
    """
    if not keys:
        return text
    alt = "|".join(re.escape(k) for k in sorted(keys, key=len, reverse=True))
    pattern = re.compile(rf"\{{\{{\{{\s*({alt})\s*\}}\}}\}}|\{{\{{\s*({alt})\s*\}}\}}")

    def repl(m: re.Match[str]) -> str:
        line_start = text.rfind("\n", 0, m.start()) + 1
        if _inside_quotes(text[line_start : m.start()]):
            return m.group(0)
        key = m.group(1) or m.group(2)
        return f'"{{{{ {key} }}}}"'

    return pattern.sub(repl, text)


def _attribute(
    keys: list[str], concrete_paths: list[str]
) -> tuple[dict[str, dict[str, str]], list[str]]:
    """Map legacy keys to ``{concrete_path: {legacy_key: dot_key}}`` by longest path prefix."""
    by_len = sorted(concrete_paths, key=len, reverse=True)
    attributed: dict[str, dict[str, str]] = {}
    unattributed: list[str] = []
    for key in keys:
        stripped = key
        while stripped.startswith("./"):
            stripped = stripped[2:]
        for path in by_len:
            prefix = path + "_"
            if stripped.startswith(prefix) and len(stripped) > len(prefix):
                attributed.setdefault(path, {})[key] = stripped[len(prefix) :]
                break
        else:
            unattributed.append(key)
    return attributed, unattributed


def migrate(
    workspace: Path | str,
    config_file: Path | str = Path("templatte.toml"),
    *,
    dry_run: bool = False,
    force: bool = False,
    backup: bool = False,
) -> MigrateResult:
    """Migrate a legacy registry (and its templates) to schema version 1."""
    root = resolve_workspace(workspace)
    config_path = resolve_config(root, config_file)
    config_rel = workspace_rel(root, config_path)
    if not config_path.is_file():
        raise ValidationError(
            f"Values registry not found: '{config_rel}'. Nothing to migrate.",
            details={"file": config_rel},
        )

    doc = tomlkit.parse(read_text_exact(config_path))
    if "version" in doc:
        return MigrateResult(registry=config_rel, nothing_to_migrate=True, dry_run=dry_run)

    # Only templates with a supported adapter can own legacy keys.
    concrete_paths: list[str] = []
    for latte in discover_latte(root):
        rel = concrete_of(latte)
        try:
            get_adapter_for_file(rel)
        except UnsupportedFormatError:
            continue
        concrete_paths.append(rel)

    legacy = {str(k): v for k, v in doc.items()}
    attributed, unattributed = _attribute(list(legacy), concrete_paths)
    if unattributed:
        raise ValidationError(
            "Cannot attribute legacy registry keys to any .latte template: "
            + ", ".join(unattributed),
            details={"file": config_rel, "unattributed_keys": unattributed},
        )

    registry = ValuesRegistry()
    new_templates: dict[str, str] = {}
    files: list[MigratedFile] = []
    for path in sorted(attributed):
        mapping = attributed[path]
        values: dict[str, Any] = plain_values(
            {dot: legacy[legacy_key] for legacy_key, dot in mapping.items()}
        )
        fmt = get_adapter_for_file(path).format_name
        secrets = {k: True for k in values if is_credential_shaped(k)}
        registry.files[path] = FileEntry(format=fmt, values=values, secrets=secrets)

        latte_rel = path + LATTE_SUFFIX
        old = read_text_exact(root / latte_rel)
        new = quote_placeholders(old, list(values))
        if new != old:
            new_templates[latte_rel] = new
        files.append(MigratedFile(path, fmt, len(values), len(secrets), new != old))

    plan = MigrateResult(
        registry=config_rel,
        files=tuple(files),
        templates_rewritten=tuple(sorted(new_templates)),
        dry_run=dry_run,
    )
    if dry_run:
        return plan
    if not force:
        return MigrateResult(
            registry=plan.registry,
            files=plan.files,
            templates_rewritten=plan.templates_rewritten,
            requires_confirmation=True,
        )

    backups: list[str] = []
    if backup:
        backups.append(workspace_rel(root, backup_file(config_path)))
        backups.extend(workspace_rel(root, backup_file(root / t)) for t in sorted(new_templates))
    # Templates first, registry last: a crash in between leaves a legacy registry whose
    # rewrite is idempotent (already-quoted placeholders are skipped on the next run).
    for latte_rel, text in sorted(new_templates.items()):
        atomic_write_bytes(root / latte_rel, text.encode("utf-8"))
    RegistryManager(root).save(registry, config_path)
    return MigrateResult(
        registry=plan.registry,
        files=plan.files,
        templates_rewritten=plan.templates_rewritten,
        backups=tuple(backups),
    )

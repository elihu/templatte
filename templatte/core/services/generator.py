"""``genelatte`` service: discover configs, write ``.latte`` templates and the registry.

Implements FUNCTIONAL_SPEC §2.1 steps 1-8 as pure application logic. The service
returns a :class:`GenerateResult`; presentation and prompting belong to the CLI.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tomlkit.toml_document import TOMLDocument

from templatte.core.models import FileEntry, ValuesRegistry
from templatte.core.registry import RegistryManager
from templatte.core.services._common import (
    LATTE_SUFFIX,
    adapter_for,
    concrete_of,
    discover_latte,
    extract_with_real_path,
    read_text_exact,
    resolve_config,
    resolve_workspace,
    workspace_rel,
)
from templatte.core.services.scanner import DEFAULT_FORMATS, scan_workspace
from templatte.utils.fs import atomic_write_bytes
from templatte.utils.git import ensure_gitignored

CREDENTIAL_MARKERS = ("password", "secret", "token", "key")
DEFAULT_CONFIG_REL = "templatte.toml"
FIXED_IGNORE_PATTERNS = ("templatte.toml", "templatte.*.toml")
#: Backups written by deploy/grind/pour (``<name>.<timestamp>.bak``) hold plaintext secrets.
BACKUP_GLOB = "{}.*.bak"
EXIT_MANUAL_REVIEW = 3


def is_credential_shaped(dot_path: str) -> bool:
    """Case-insensitive substring match on password/secret/token/key."""
    lowered = dot_path.lower()
    return any(marker in lowered for marker in CREDENTIAL_MARKERS)


@dataclass(frozen=True)
class GenerateResult:
    """Outcome of a genelatte run. All paths are workspace-relative POSIX.

    ``templates_created`` and ``skipped_existing`` hold ``.latte`` paths;
    ``manual_review`` holds the concrete source files left untouched.
    """

    files_scanned: int
    templates_created: tuple[str, ...]
    skipped_existing: tuple[str, ...]
    manual_review: tuple[str, ...]
    keys_extracted: int
    gitignore_updated: bool
    dry_run: bool = False

    @property
    def exit_code(self) -> int:
        """3 when any file needs manual review (MASTER_SPEC §6.2), else 0."""
        return EXIT_MANUAL_REVIEW if self.manual_review else 0


def _prune_stale(doc: TOMLDocument, rel: str, entry: FileEntry) -> None:
    """Drop keys no longer present from an existing doc's values/secrets tables."""
    files = doc.get("files")
    if files is None or rel not in files:
        return
    f_table = files[rel]
    for name, keep in (("values", entry.values), ("secrets", entry.secrets)):
        table = f_table.get(name)
        if table is None:
            continue
        for key in [k for k in table if k not in keep]:
            del table[key]
        if name == "secrets" and not table:
            del f_table[name]


def generate(
    workspace: Path | str,
    config_file: Path | str = Path("templatte.toml"),
    *,
    formats: Sequence[str] = DEFAULT_FORMATS,
    include: Sequence[str] = (),
    exclude: Sequence[str] = (),
    force_include: bool = False,
    force: bool = False,
    dry_run: bool = False,
    update_gitignore: bool = True,
) -> GenerateResult:
    """Run genelatte over ``workspace``."""
    root = resolve_workspace(workspace)
    config_path = resolve_config(root, config_file)
    config_rel = workspace_rel(root, config_path)

    manager = RegistryManager(root)
    existing_doc: TOMLDocument | None = None
    if config_path.is_file():
        existing_doc = manager.load_document(config_path)  # LegacyRegistryError propagates
        registry = manager.document_to_model(existing_doc)
    else:
        registry = ValuesRegistry()

    excludes = [*exclude, *registry.workspace.ignored_patterns]
    if config_rel != DEFAULT_CONFIG_REL:
        excludes.append(config_rel)
    scan = scan_workspace(
        root,
        formats,
        include,
        excludes,
        force_include,
        open_tag=registry.template.open,
        close_tag=registry.template.close,
    )

    created: list[str] = []
    skipped: list[str] = []
    pending: list[tuple[str, str, FileEntry]] = []  # (latte_rel, template, entry)
    keys_extracted = 0

    # Compute everything first so a syntax error aborts before any write.
    for cand in scan.candidates:
        latte_rel = cand.path + LATTE_SUFFIX
        if (root / latte_rel).exists() and not force:
            skipped.append(latte_rel)
            continue
        adapter = adapter_for(cand.format, cand.path)
        values, template = extract_with_real_path(
            adapter, read_text_exact(root / cand.path), registry, cand.path
        )
        previous = registry.files.get(cand.path)
        old_flags = previous.secrets if previous else {}
        secrets: dict[str, bool] = {}
        for key in values:
            if old_flags.get(key) is True or is_credential_shaped(key):
                secrets[key] = True
        entry = FileEntry(format=cand.format, values=values, secrets=secrets)
        pending.append((latte_rel, template, entry))
        created.append(latte_rel)
        keys_extracted += len(values)

    gitignore_updated = False
    if not dry_run:
        for latte_rel, template, entry in pending:
            atomic_write_bytes(root / latte_rel, template.encode("utf-8"))
            rel = concrete_of(latte_rel)
            registry.files[rel] = entry
            if existing_doc is not None:
                _prune_stale(existing_doc, rel, entry)
        if pending:
            manager.save(registry, config_path, existing_doc=existing_doc)

        if update_gitignore:
            latte_all = discover_latte(root)
            if pending or latte_all:
                patterns: list[Any] = list(FIXED_IGNORE_PATTERNS)
                protected = [config_rel, *(concrete_of(p) for p in latte_all)]
                if config_rel != DEFAULT_CONFIG_REL:
                    patterns.append(config_rel)
                patterns.extend(protected[1:])
                patterns.extend(BACKUP_GLOB.format(p) for p in protected)
                gitignore_updated = ensure_gitignored(root, patterns)

    return GenerateResult(
        files_scanned=len(scan.candidates) + len(scan.manual_review),
        templates_created=tuple(created),
        skipped_existing=tuple(skipped),
        manual_review=scan.manual_review,
        keys_extracted=keys_extracted,
        gitignore_updated=gitignore_updated,
        dry_run=dry_run,
    )

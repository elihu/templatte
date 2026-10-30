"""Shared helpers for application services (no I/O to the terminal, ever)."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any

from templatte.adapters import get_adapter_by_format, get_adapter_for_file
from templatte.adapters.base import FormatAdapter
from templatte.core.exceptions import (
    ConfigSyntaxError,
    MissingValuesError,
    PathTraversalError,
    UnsupportedFormatError,
    ValidationError,
)
from templatte.core.models import ValuesRegistry
from templatte.core.registry import RegistryManager
from templatte.utils.fs import atomic_write_bytes, is_within_workspace, normalize_workspace_path

LATTE_SUFFIX = ".latte"
PRUNE_DIRS = frozenset({".git", ".venv", "__pycache__", "node_modules", "dist"})


def timestamp() -> str:
    """Backup timestamp (``YYYYmmddTHHMMSS``). Monkeypatch in tests for determinism."""
    return datetime.now().astimezone().strftime("%Y%m%dT%H%M%S")


def resolve_workspace(workspace: Path | str) -> Path:
    return Path(workspace).resolve()


def resolve_config(workspace: Path, config_file: Path | str) -> Path:
    """Resolve the registry path relative to the workspace (absolute honored)."""
    p = Path(config_file)
    return p if p.is_absolute() else workspace / p


def workspace_rel(workspace: Path, path: Path | str) -> str:
    """Workspace-relative POSIX path; PathTraversalError if outside the workspace."""
    p = Path(path)
    if not p.is_absolute():
        p = workspace / p
    if not is_within_workspace(p, workspace):
        raise PathTraversalError(str(path), str(workspace))
    # Normalize lexically-resolved parent, but do not follow a final symlink.
    return normalize_workspace_path(p.parent.resolve() / p.name, workspace)


def discover_latte(workspace: Path) -> list[str]:
    """Recursively list ``*.latte`` files as sorted workspace-relative POSIX paths."""
    found: list[str] = []
    for dirpath, dirnames, filenames in os.walk(workspace, followlinks=False):
        dirnames[:] = [d for d in dirnames if d not in PRUNE_DIRS]
        for name in filenames:
            if name.endswith(LATTE_SUFFIX):
                full = Path(dirpath) / name
                if full.is_file() and not full.is_symlink():
                    found.append(full.relative_to(workspace).as_posix())
    return sorted(found)


def concrete_of(latte_rel: str) -> str:
    """``config/app.toml.latte`` -> ``config/app.toml``."""
    return latte_rel.removesuffix(LATTE_SUFFIX)


def load_required_registry(workspace: Path, config_path: Path) -> ValuesRegistry:
    """Load the registry or fail with an exit-3 ``ValidationError`` if it is missing.

    ``LegacyRegistryError`` from the registry manager propagates unchanged.
    """
    if not config_path.is_file():
        rel = normalize_workspace_path(config_path, workspace)
        raise ValidationError(
            f"Values registry not found: '{rel}'. Run 'templatte genelatte' first.",
            details={"file": rel},
        )
    return RegistryManager(workspace).load(config_path)


def adapter_for(entry_format: str | None, concrete_rel: str) -> FormatAdapter:
    """Adapter from the registry entry's format, falling back to the file extension."""
    if entry_format and entry_format != "unknown":
        try:
            return get_adapter_by_format(entry_format)
        except UnsupportedFormatError:
            pass
    return get_adapter_for_file(concrete_rel)


def render_with_real_path(
    adapter: FormatAdapter,
    template_text: str,
    values: dict[str, Any],
    registry: ValuesRegistry,
    real_path: str,
) -> str:
    """Render, re-reporting ``MissingValuesError`` with the real workspace path."""
    try:
        return adapter.render(
            template_text,
            values,
            open_tag=registry.template.open,
            close_tag=registry.template.close,
        )
    except MissingValuesError as exc:
        raise MissingValuesError(real_path, exc.missing_keys) from None
    except ConfigSyntaxError as exc:
        raise ConfigSyntaxError(real_path, exc.details.get("reason", exc.message)) from None


def extract_with_real_path(
    adapter: FormatAdapter,
    text: str,
    registry: ValuesRegistry,
    real_path: str,
) -> tuple[dict[str, Any], str]:
    """Extract values/template, re-reporting syntax errors with the real path."""
    try:
        return adapter.extract_values(
            text, open_tag=registry.template.open, close_tag=registry.template.close
        )
    except ConfigSyntaxError as exc:
        raise ConfigSyntaxError(real_path, exc.details.get("reason", exc.message)) from None


def read_text_exact(path: Path) -> str:
    """Read UTF-8 text without newline translation."""
    return path.read_bytes().decode("utf-8")


def backup_file(path: Path) -> Path:
    """Copy ``path`` to a sibling ``<name>.<timestamp>.bak`` (never overwriting one)."""
    ts = timestamp()
    candidate = path.with_name(f"{path.name}.{ts}.bak")
    n = 1
    while candidate.exists():
        candidate = path.with_name(f"{path.name}.{ts}-{n}.bak")
        n += 1
    atomic_write_bytes(candidate, path.read_bytes())
    return candidate


def plain_values(values: dict[str, Any]) -> dict[str, Any]:
    """Unwrap tomlkit items (registry values) into plain Python objects.

    Adapters such as YAML cannot represent tomlkit ``Integer``/``String`` wrappers.
    """

    def unwrap(v: Any) -> Any:
        if hasattr(v, "unwrap"):
            return v.unwrap()
        if isinstance(v, bool):
            return bool(v)
        if isinstance(v, int) and type(v) is not int:
            return int(v)
        if isinstance(v, float) and type(v) is not float:
            return float(v)
        if isinstance(v, str) and type(v) is not str:
            return str(v)
        if isinstance(v, list):
            return [unwrap(x) for x in v]
        if isinstance(v, dict):
            return {k: unwrap(x) for k, x in v.items()}
        return v

    return {k: unwrap(v) for k, v in values.items()}

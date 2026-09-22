"""Configuration format adapters and static registry."""

from __future__ import annotations

from pathlib import Path

from templatte.adapters.base import FormatAdapter
from templatte.adapters.env_adapter import EnvAdapter
from templatte.adapters.ini_adapter import IniAdapter
from templatte.adapters.json_adapter import JsonAdapter
from templatte.adapters.toml_adapter import TomlAdapter
from templatte.adapters.yaml_adapter import YamlAdapter
from templatte.core.exceptions import UnsupportedFormatError

ADAPTERS: dict[str, type[FormatAdapter]] = {
    "toml": TomlAdapter,
    "yaml": YamlAdapter,
    "json": JsonAdapter,
    "ini": IniAdapter,
    "env": EnvAdapter,
}


def get_adapter_for_file(path: Path | str) -> FormatAdapter:
    """Find and instantiate the matching format adapter for a file path."""
    p = Path(path)
    for adapter_cls in ADAPTERS.values():
        adapter = adapter_cls()
        if adapter.can_handle(p):
            return adapter
    raise UnsupportedFormatError(str(p))


def get_adapter_by_format(format_name: str) -> FormatAdapter:
    """Find and instantiate the format adapter by its format name."""
    clean_name = format_name.lower().strip()
    if clean_name in ADAPTERS:
        return ADAPTERS[clean_name]()
    raise UnsupportedFormatError(format_name)


__all__ = [
    "ADAPTERS",
    "EnvAdapter",
    "FormatAdapter",
    "IniAdapter",
    "JsonAdapter",
    "TomlAdapter",
    "YamlAdapter",
    "get_adapter_by_format",
    "get_adapter_for_file",
]

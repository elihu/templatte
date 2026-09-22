"""JSON format adapter with exact formatting, indentation, and type preservation."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from templatte.adapters.base import (
    is_all_scalar_or_nested_scalar_list as _is_all_scalar_or_nested_scalar_list,
)
from templatte.core.exceptions import ConfigSyntaxError, MissingValuesError


class JsonAdapter:
    """Adapter for JSON configuration files preserving data types, indentation, and formatting."""

    format_name = "json"
    supported_extensions = (".json",)

    def can_handle(self, file_path: Path | str) -> bool:
        p = Path(file_path)
        name = p.name
        name = name.removesuffix(".latte")
        return name.endswith(self.supported_extensions)

    def _detect_formatting(
        self, content: str
    ) -> tuple[int | str | None, tuple[str, str], bool]:
        """Detect indentation, item/key separators, and trailing-newline presence
        from a JSON string, to reproduce them when re-serializing.

        This heuristic assumes separator style is consistent across the whole
        document; a document mixing separator styles between object and array
        levels is not guaranteed byte-for-byte.
        """
        has_trailing_newline = content.endswith("\n")
        raw = content.rstrip("\r\n")
        lines = raw.splitlines()

        if len(lines) <= 1:
            # Compact / single-line JSON
            item_sep = ", " if ", " in raw else ","
            key_sep = ": " if ": " in raw else ":"
            return None, (item_sep, key_sep), has_trailing_newline

        # Multiline JSON: detect indentation
        indent: int | str = 2
        for line in lines[1:]:
            stripped = line.lstrip()
            if stripped:
                indent_str = line[: len(line) - len(stripped)]
                if "\t" in indent_str:
                    indent = "\t"
                else:
                    indent = len(indent_str)
                break

        key_sep = ": " if ": " in raw else ":"
        return indent, (",", key_sep), has_trailing_newline

    def extract_values(
        self,
        content: str,
        open_tag: str = "{{",
        close_tag: str = "}}",
    ) -> tuple[dict[str, Any], str]:
        """Extract dot-paths into dictionary and return formatted JSON template."""
        try:
            data = json.loads(content)
        except Exception as exc:
            raise ConfigSyntaxError("content", str(exc)) from exc

        indent, separators, has_newline = self._detect_formatting(content)
        extracted: dict[str, Any] = {}

        def _traverse_extract(obj: Any, prefix: str = "") -> Any:
            if isinstance(obj, dict):
                res_dict: dict[str, Any] = {}
                for k, v in obj.items():
                    full_key = f"{prefix}.{k}" if prefix else str(k)
                    res_dict[k] = _traverse_extract(v, full_key)
                return res_dict
            if isinstance(obj, list):
                if _is_all_scalar_or_nested_scalar_list(obj):
                    # Leaf array: extracted whole, under a single dot-path key
                    extracted[prefix] = obj
                    return f"{open_tag} {prefix} {close_tag}"
                # Array-of-objects: indexed element by element (TOML AoT convention)
                res_list: list[Any] = []
                for idx, item in enumerate(obj):
                    item_key = f"{prefix}[{idx}]"
                    res_list.append(_traverse_extract(item, item_key))
                return res_list
            # Leaf scalar value
            extracted[prefix] = obj
            return f"{open_tag} {prefix} {close_tag}"

        template_data = _traverse_extract(data)
        template_str = json.dumps(template_data, indent=indent, separators=separators)
        if has_newline:
            template_str += "\n"
        return extracted, template_str

    def render(
        self,
        template_content: str,
        values: dict[str, Any],
        open_tag: str = "{{",
        close_tag: str = "}}",
    ) -> str:
        """Render JSON template by replacing placeholders with typed registry values."""
        try:
            data = json.loads(template_content)
        except Exception as exc:
            raise ConfigSyntaxError("template", str(exc)) from exc

        indent, separators, has_newline = self._detect_formatting(template_content)
        pattern = re.compile(rf"^{re.escape(open_tag)}\s*(.*?)\s*{re.escape(close_tag)}$")
        missing_keys: list[str] = []

        def _traverse_render(obj: Any) -> Any:
            if isinstance(obj, dict):
                return {k: _traverse_render(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [_traverse_render(item) for item in obj]
            if isinstance(obj, str):
                m = pattern.match(obj)
                if m:
                    key_name = m.group(1)
                    if key_name in values:
                        return values[key_name]
                    missing_keys.append(key_name)
                    return obj
            return obj

        rendered_data = _traverse_render(data)

        if missing_keys:
            raise MissingValuesError("template.json.latte", missing_keys)

        rendered_str = json.dumps(rendered_data, indent=indent, separators=separators)
        if has_newline:
            rendered_str += "\n"
        return rendered_str

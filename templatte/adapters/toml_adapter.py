"""TOML format adapter with comment and structure preservation using tomlkit."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import tomlkit
from tomlkit.container import Container
from tomlkit.items import AoT, InlineTable, Table

from templatte.core.exceptions import ConfigSyntaxError, MissingValuesError

# Mapping-like nodes we recurse into. ``InlineTable`` is *not* a subclass of
# ``Container``/``Table`` in tomlkit, so it must be listed explicitly; without
# it an inline table is treated as a scalar leaf and rebuilt by
# ``tomlkit.item(dict)`` on render, which emits a ``[section]`` block and
# breaks Invariant 6.b (readable structure preservation). Mutating the
# ``InlineTable`` in place keeps it inline.
_MAPPING_TYPES = (Container, Table, InlineTable)

# Opening delimiters of the two multiline TOML string forms.
_MULTILINE_DELIMITERS = ('"""', "'''")


def _is_multiline_string(value: Any) -> bool:
    """Whether ``value`` is a TOML string written with triple delimiters.

    The flag is carried through the template by writing the placeholder itself
    as a multiline string (``key = \"\"\"{{ key }}\"\"\"``), so ``render`` can
    honour Invariant 6.b ("a multiline string remains multiline") without the
    values registry having to describe layout.
    """
    if not isinstance(value, str) or not hasattr(value, "as_string"):
        return False
    return value.as_string().startswith(_MULTILINE_DELIMITERS)


def _toml_string_item(value: str, multiline: bool) -> Any:
    """Build a TOML string item, degrading to single line when unrepresentable."""
    if multiline and '"""' not in value and not value.endswith('"'):
        return tomlkit.string(value, multiline=True)
    return tomlkit.item(value)


class TomlAdapter:
    """Adapter for TOML configuration files preserving comments and structure."""

    format_name = "toml"
    supported_extensions = (".toml",)

    def can_handle(self, file_path: Path | str) -> bool:
        p = Path(file_path)
        name = p.name
        name = name.removesuffix(".latte")
        return name.endswith(".toml")

    def extract_values(
        self,
        content: str,
        open_tag: str = "{{",
        close_tag: str = "}}",
    ) -> tuple[dict[str, Any], str]:
        """Extract dot-paths into dictionary and return template string with placeholders."""
        try:
            doc = tomlkit.parse(content)
        except Exception as exc:
            raise ConfigSyntaxError("content", str(exc)) from exc

        extracted: dict[str, Any] = {}

        def _traverse_extract(container: Any, prefix: str = "") -> None:
            for k, v in list(container.items()):
                full_key = f"{prefix}.{k}" if prefix else k
                if isinstance(v, _MAPPING_TYPES):
                    _traverse_extract(v, full_key)
                elif isinstance(v, AoT):
                    for idx, item in enumerate(v):
                        aot_prefix = f"{full_key}[{idx}]"
                        _traverse_extract(item, aot_prefix)
                else:
                    # Unwrap value to native python representation
                    val = v.unwrap() if hasattr(v, "unwrap") else v
                    extracted[full_key] = val
                    # Replace with quoted placeholder token
                    placeholder = tomlkit.string(
                        f"{open_tag} {full_key} {close_tag}",
                        multiline=_is_multiline_string(v),
                    )
                    if hasattr(v, "trivia"):
                        placeholder.trivia.comment = v.trivia.comment
                        placeholder.trivia.comment_ws = v.trivia.comment_ws
                    container[k] = placeholder

        _traverse_extract(doc)
        template_str = tomlkit.dumps(doc)
        return extracted, template_str

    def render(
        self,
        template_content: str,
        values: dict[str, Any],
        open_tag: str = "{{",
        close_tag: str = "}}",
    ) -> str:
        """Render template content replacing placeholders with typed values while preserving formatting."""
        try:
            doc = tomlkit.parse(template_content)
        except Exception as exc:
            raise ConfigSyntaxError("template", str(exc)) from exc

        pattern = re.compile(rf"^{re.escape(open_tag)}\s*(.*?)\s*{re.escape(close_tag)}$")
        missing_keys: list[str] = []

        def _traverse_render(container: Any) -> None:
            if isinstance(container, _MAPPING_TYPES):
                for k in list(container.keys()):
                    v = container[k]
                    if isinstance(v, _MAPPING_TYPES):
                        _traverse_render(v)
                    elif isinstance(v, AoT):
                        for item in v:
                            _traverse_render(item)
                    elif isinstance(v, str):
                        m = pattern.match(str(v))
                        if m:
                            key_name = m.group(1)
                            if key_name in values:
                                raw_val = values[key_name]
                                if isinstance(raw_val, str):
                                    new_item = _toml_string_item(raw_val, _is_multiline_string(v))
                                else:
                                    new_item = tomlkit.item(raw_val)
                                if hasattr(v, "trivia"):
                                    new_item.trivia.comment = v.trivia.comment
                                    new_item.trivia.comment_ws = v.trivia.comment_ws
                                container[k] = new_item
                            else:
                                missing_keys.append(key_name)
            elif isinstance(container, AoT):
                for item in container:
                    _traverse_render(item)

        _traverse_render(doc)

        if missing_keys:
            raise MissingValuesError("template.toml.latte", missing_keys)

        return tomlkit.dumps(doc)

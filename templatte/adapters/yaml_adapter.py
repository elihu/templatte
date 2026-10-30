"""YAML format adapter with comment and key-order preservation using ruamel.yaml."""

from __future__ import annotations

import io
import re
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.scalarstring import DoubleQuotedScalarString, PlainScalarString

from templatte.adapters.base import (
    is_all_scalar_or_nested_scalar_list as _is_all_scalar_or_nested_scalar_list,
)
from templatte.core.exceptions import ConfigSyntaxError, MissingValuesError


def _own_keys(obj: Any) -> list[Any]:
    """Return only the keys a mapping physically declares itself.

    ruamel's round-trip ``CommentedMap`` exposes keys inherited through a YAML
    merge key (``<<: *anchor``) via ``keys()``/``items()`` as if they belonged
    to the mapping. Extracting or assigning those keys materialises them as
    literal own keys, which duplicates the anchor's content next to the still
    emitted ``<<:`` line and therefore expands the merge -- a real change to
    the document, forbidden by Invariant 6.b.

    ``non_merged_items()`` yields exactly the entries written in the mapping
    itself (including any that explicitly override a merged key), so the
    inherited ones are left untouched and keep resolving through the anchor.
    The anchor's own definition is traversed where it is declared, so its
    values are still templatised -- once, at their single source.
    """
    if isinstance(obj, CommentedMap) and obj.merge:
        return [k for k, _ in obj.non_merged_items()]
    return list(obj.keys())


class YamlAdapter:
    """Adapter for YAML configuration files preserving comments and structure."""

    format_name = "yaml"
    supported_extensions = (".yaml", ".yml")

    def __init__(self) -> None:
        self.yaml = YAML(typ="rt")
        self.yaml.preserve_quotes = True
        self.yaml.indent(mapping=2, sequence=4, offset=2)

    def can_handle(self, file_path: Path | str) -> bool:
        p = Path(file_path)
        name = p.name
        name = name.removesuffix(".latte")
        return name.endswith(self.supported_extensions)

    def extract_values(
        self,
        content: str,
        open_tag: str = "{{",
        close_tag: str = "}}",
    ) -> tuple[dict[str, Any], str]:
        """Extract dot-paths into dictionary and return YAML template with quoted placeholders."""
        try:
            data = self.yaml.load(content)
        except Exception as exc:
            raise ConfigSyntaxError("content", str(exc)) from exc

        if data is None:
            return {}, content

        extracted: dict[str, Any] = {}

        def _to_plain_list(seq: list[Any]) -> list[Any]:
            """Convert a leaf sequence to plain Python containers for the registry."""
            return [_to_plain_list(i) if isinstance(i, list) else i for i in seq]

        def _handle_node(v: Any, key: str) -> Any:
            """Return the replacement node for ``v``, or ``None`` to keep it in place."""
            if isinstance(v, dict):
                _traverse_extract(v, key)
                return None
            if isinstance(v, list):
                if not _is_all_scalar_or_nested_scalar_list(v):
                    # Sequence of mappings: indexed element by element (TOML AoT convention)
                    _traverse_extract(v, key)
                    return None
                # Leaf sequence: extracted whole, under a single dot-path key
                extracted[key] = _to_plain_list(v)
                placeholder = DoubleQuotedScalarString(f"{open_tag} {key} {close_tag}")
                if isinstance(v, CommentedSeq) and v.fa.flow_style():
                    # The template keeps the flow brackets around the single
                    # placeholder, so `render` can restore the flow style the
                    # document was written with (Invariant 6.b).
                    flow_placeholder = CommentedSeq([placeholder])
                    flow_placeholder.fa.set_flow_style()
                    return flow_placeholder
                return placeholder
            extracted[key] = v
            return DoubleQuotedScalarString(f"{open_tag} {key} {close_tag}")

        def _traverse_extract(obj: Any, prefix: str = "") -> None:
            if isinstance(obj, dict):
                for k in _own_keys(obj):
                    full_key = f"{prefix}.{k}" if prefix else str(k)
                    replacement = _handle_node(obj[k], full_key)
                    if replacement is not None:
                        obj[k] = replacement
            elif isinstance(obj, list):
                for idx, item in enumerate(obj):
                    replacement = _handle_node(item, f"{prefix}[{idx}]")
                    if replacement is not None:
                        obj[idx] = replacement

        _traverse_extract(data)
        buf = io.StringIO()
        self.yaml.dump(data, buf)
        return extracted, buf.getvalue()

    def render(
        self,
        template_content: str,
        values: dict[str, Any],
        open_tag: str = "{{",
        close_tag: str = "}}",
    ) -> str:
        """Render YAML template replacing placeholders with typed values."""
        try:
            data = self.yaml.load(template_content)
        except Exception as exc:
            raise ConfigSyntaxError("template", str(exc)) from exc

        if data is None:
            return template_content

        pattern = re.compile(rf"^{re.escape(open_tag)}\s*(.*?)\s*{re.escape(close_tag)}$")
        missing_keys: list[str] = []

        def _to_yaml_val(val: Any, flow: bool = False) -> Any:
            if isinstance(val, str):
                if "\n" in val or ":" in val or "#" in val:
                    return DoubleQuotedScalarString(val)
                return PlainScalarString(val)
            if isinstance(val, list):
                # A whole array replacing a placeholder: reinsert as a ruamel
                # sequence so it stays consistent with the rest of the document.
                seq = CommentedSeq(_to_yaml_val(item, flow) for item in val)
                if flow:
                    seq.fa.set_flow_style()
                return seq
            if isinstance(val, dict):
                return CommentedMap((k, _to_yaml_val(v)) for k, v in val.items())
            return val

        def _flow_placeholder_key(node: Any) -> str | None:
            """Return the key a flow-wrapped array placeholder stands for.

            ``extract_values`` writes a leaf sequence that was in flow style as
            ``key: ["{{ dotted.path }}"]``, so the style survives in the
            template itself and can be restored here.
            """
            if not isinstance(node, list) or len(node) != 1:
                return None
            if not isinstance(node, CommentedSeq) or not node.fa.flow_style():
                return None
            inner = node[0]
            if not isinstance(inner, str):
                return None
            m = pattern.match(inner)
            return m.group(1) if m else None

        def _resolve(node: Any) -> Any:
            """Return the replacement for ``node``, or ``None`` to keep it."""
            key_name = _flow_placeholder_key(node)
            if key_name is not None:
                if key_name in values:
                    return _to_yaml_val(values[key_name], flow=True)
                missing_keys.append(key_name)
                return None
            if isinstance(node, (dict, list)):
                _traverse_render(node)
                return None
            if isinstance(node, str):
                m = pattern.match(node)
                if m:
                    key_name = m.group(1)
                    if key_name in values:
                        return _to_yaml_val(values[key_name])
                    missing_keys.append(key_name)
            return None

        def _traverse_render(obj: Any) -> None:
            if isinstance(obj, dict):
                for k in _own_keys(obj):
                    replacement = _resolve(obj[k])
                    if replacement is not None:
                        obj[k] = replacement
            elif isinstance(obj, list):
                for idx, v in enumerate(obj):
                    replacement = _resolve(v)
                    if replacement is not None:
                        obj[idx] = replacement

        _traverse_render(data)

        if missing_keys:
            raise MissingValuesError("template.yaml.latte", missing_keys)

        buf = io.StringIO()
        self.yaml.dump(data, buf)
        return buf.getvalue()

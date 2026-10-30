"""INI and .properties format adapter preserving comments and structure."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from templatte.core.exceptions import MissingValuesError


class IniAdapter:
    """Adapter for INI and .properties configuration files."""

    format_name = "ini"
    supported_extensions = (".ini", ".properties", ".cfg", ".conf")

    _SECTION_RE = re.compile(r"^\s*\[(.*?)\]\s*$")
    _KEY_VAL_RE = re.compile(r"^(\s*)([^#;=\s:][^#;=:]*?)(\s*[:=]\s*)(.*?)(?:\s*([#;].*))?$")

    def can_handle(self, file_path: Path | str) -> bool:
        p = Path(file_path)
        name = p.name
        name = name.removesuffix(".latte")
        return name.endswith(self.supported_extensions)

    def _parse_scalar(self, val_str: str) -> Any:
        stripped = val_str.strip()
        lower = stripped.lower()
        if lower == "true":
            return True
        if lower == "false":
            return False
        try:
            return int(stripped)
        except ValueError:
            pass
        try:
            return float(stripped)
        except ValueError:
            pass
        # Check if list of numbers or strings
        if "," in stripped and not stripped.startswith('"') and not stripped.startswith("'"):
            parts = [p.strip() for p in stripped.split(",")]
            # Attempt to convert to numbers if all elements are numeric
            try:
                return [int(p) for p in parts]
            except ValueError:
                return parts
        # Strip surrounding quotes if present
        if (stripped.startswith('"') and stripped.endswith('"')) or (
            stripped.startswith("'") and stripped.endswith("'")
        ):
            return stripped[1:-1]
        return stripped

    def _format_value(self, val: Any) -> str:
        if isinstance(val, bool):
            return "true" if val else "false"
        if isinstance(val, (list, tuple)):
            return ",".join(str(x) for x in val)
        return str(val)

    def extract_values(
        self,
        content: str,
        open_tag: str = "{{",
        close_tag: str = "}}",
    ) -> tuple[dict[str, Any], str]:
        """Extract dot-paths from INI/.properties and generate template content."""
        extracted: dict[str, Any] = {}
        template_lines: list[str] = []
        current_section = ""

        for line in content.splitlines(keepends=True):
            raw_line = line.rstrip("\r\n")
            sec_match = self._SECTION_RE.match(raw_line)
            if sec_match:
                current_section = sec_match.group(1).strip()
                template_lines.append(line)
                continue

            kv_match = self._KEY_VAL_RE.match(raw_line)
            if kv_match:
                indent, key, delim, val_str, comment = kv_match.groups()
                clean_key = key.strip()
                full_key = f"{current_section}.{clean_key}" if current_section else clean_key
                extracted[full_key] = self._parse_scalar(val_str)

                placeholder = f"{open_tag} {full_key} {close_tag}"
                comment_part = f" {comment}" if comment else ""
                end_chars = line[len(raw_line) :]
                template_lines.append(f"{indent}{key}{delim}{placeholder}{comment_part}{end_chars}")
            else:
                template_lines.append(line)

        return extracted, "".join(template_lines)

    def render(
        self,
        template_content: str,
        values: dict[str, Any],
        open_tag: str = "{{",
        close_tag: str = "}}",
    ) -> str:
        """Render INI template replacing placeholders with stringified values."""
        pattern = re.compile(rf"{re.escape(open_tag)}\s*(.*?)\s*{re.escape(close_tag)}")
        missing_keys: list[str] = []
        output_lines: list[str] = []

        for line in template_content.splitlines(keepends=True):
            raw_line = line.rstrip("\r\n")
            kv_match = self._KEY_VAL_RE.match(raw_line)
            if kv_match:
                indent, key, delim, val_str, comment = kv_match.groups()
                m = pattern.search(val_str)
                if m:
                    key_name = m.group(1)
                    if key_name in values:
                        rendered_val = self._format_value(values[key_name])
                        new_val_str = pattern.sub(rendered_val, val_str)
                        comment_part = f" {comment}" if comment else ""
                        end_chars = line[len(raw_line) :]
                        output_lines.append(
                            f"{indent}{key}{delim}{new_val_str}{comment_part}{end_chars}"
                        )
                    else:
                        missing_keys.append(key_name)
                        output_lines.append(line)
                else:
                    output_lines.append(line)
            else:
                output_lines.append(line)

        if missing_keys:
            raise MissingValuesError("template.ini.latte", missing_keys)

        return "".join(output_lines)

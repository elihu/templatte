"""Environment variable (.env) file adapter preserving comments and spacing."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from templatte.core.exceptions import MissingValuesError


class EnvAdapter:
    """Adapter for .env files extracting flat KEY=value pairs."""

    format_name = "env"
    supported_extensions = (".env",)

    _LINE_RE = re.compile(r"^(\s*)([A-Za-z_][A-Za-z0-9_]*)(\s*=\s*)(.*?)(?:\s*(#.*))?$")

    def can_handle(self, file_path: Path | str) -> bool:
        p = Path(file_path)
        name = p.name
        name = name.removesuffix(".latte")
        return name.startswith(".env") or name.endswith(".env")

    def _parse_scalar(self, val_str: str) -> Any:
        stripped = val_str.strip()
        # Handle quoted strings
        if (stripped.startswith('"') and stripped.endswith('"')) or (
            stripped.startswith("'") and stripped.endswith("'")
        ):
            return stripped[1:-1]
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
        return stripped

    def _format_value(self, val: Any) -> str:
        if isinstance(val, bool):
            return "true" if val else "false"
        if isinstance(val, (list, tuple)):
            s = ",".join(str(x) for x in val)
        else:
            s = str(val)

        # Apply shell-safe quoting if value contains whitespace, quotes, or newlines
        if any(c in s for c in (" ", "\t", "\n", '"', "'", "#")):
            escaped = s.replace('"', '\\"')
            return f'"{escaped}"'
        return s

    def extract_values(
        self,
        content: str,
        open_tag: str = "{{",
        close_tag: str = "}}",
    ) -> tuple[dict[str, Any], str]:
        """Extract flat keys into dictionary and return .env template."""
        extracted: dict[str, Any] = {}
        template_lines: list[str] = []

        for line in content.splitlines(keepends=True):
            raw_line = line.rstrip("\r\n")
            m = self._LINE_RE.match(raw_line)
            if m:
                indent, key, delim, val_str, comment = m.groups()
                extracted[key] = self._parse_scalar(val_str)
                placeholder = f"{open_tag} {key} {close_tag}"
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
        """Render .env template replacing placeholders with shell-safe values."""
        pattern = re.compile(rf"{re.escape(open_tag)}\s*(.*?)\s*{re.escape(close_tag)}")
        missing_keys: list[str] = []
        output_lines: list[str] = []

        for line in template_content.splitlines(keepends=True):
            raw_line = line.rstrip("\r\n")
            m = self._LINE_RE.match(raw_line)
            if m:
                indent, key, delim, val_str, comment = m.groups()
                pm = pattern.search(val_str)
                if pm:
                    key_name = pm.group(1)
                    if key_name in values:
                        formatted = self._format_value(values[key_name])
                        new_val_str = pattern.sub(formatted, val_str)
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
            raise MissingValuesError(".env.latte", missing_keys)

        return "".join(output_lines)

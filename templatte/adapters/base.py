"""Base protocol definition for configuration format adapters."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol, runtime_checkable


def is_all_scalar_or_nested_scalar_list(obj: list[Any]) -> bool:
    """Return True if a sequence is a *leaf* array for registry purposes.

    A leaf array contains only scalars, or nested sequences that are themselves
    leaf arrays (e.g. ``[8000, 8001]`` or ``[["delta", "phi"], [3.14]]``). Such an
    array is extracted whole, under a single dot-path key, matching TOML's native
    array handling (MASTER_SPEC §5, "Array" row).

    A sequence containing any mapping is *not* a leaf: it is structurally an
    array-of-tables and is extracted element by element with indexed keys
    (MASTER_SPEC §6.3). An empty sequence counts as a leaf.
    """
    for item in obj:
        if isinstance(item, dict):
            return False
        if isinstance(item, list) and not is_all_scalar_or_nested_scalar_list(item):
            return False
    return True


@runtime_checkable
class FormatAdapter(Protocol):
    """Protocol defining the interface for configuration format adapters."""

    format_name: str
    supported_extensions: tuple[str, ...]

    def can_handle(self, file_path: Path | str) -> bool:
        """Determine if this adapter supports the given file path or extension."""
        ...

    def extract_values(
        self,
        content: str,
        open_tag: str = "{{",
        close_tag: str = "}}",
    ) -> tuple[dict[str, Any], str]:
        """Parse configuration content.

        Returns:
            - A flat dictionary of leaf dot-paths to extracted values.
            - The generated template content containing placeholder tokens.
        """
        ...

    def render(
        self,
        template_content: str,
        values: dict[str, Any],
        open_tag: str = "{{",
        close_tag: str = "}}",
    ) -> str:
        """Render template content using values from the registry."""
        ...

"""Unit tests for TomlAdapter."""

from pathlib import Path

import pytest

from templatte.adapters.toml_adapter import TomlAdapter
from templatte.core.exceptions import ConfigSyntaxError, MissingValuesError

SAMPLE_TOML = """# Master TOML File
title = "TOML Example"

[owner]
name = "Tom Preston-Werner"
dob = 1979-05-27T07:32:00-08:00

[database]
enabled = true
ports = [8000, 8001, 8002]
data = [["delta", "phi"], [3.14]]

[database.temp_targets]
cpu = 79.5 # CPU temperature target
case = 72.0

[[servers]]
ip = "10.0.0.1" # Frontend server
role = "frontend"

[[servers]]
ip = "10.0.0.2"
role = "backend"
"""


def test_toml_adapter_can_handle() -> None:
    adapter = TomlAdapter()
    assert adapter.can_handle(Path("config.toml")) is True
    assert adapter.can_handle(Path("config.toml.latte")) is True
    assert adapter.can_handle(Path("config.yaml")) is False


def test_toml_adapter_extract_and_render_roundtrip() -> None:
    adapter = TomlAdapter()
    values, template = adapter.extract_values(SAMPLE_TOML)

    assert values["title"] == "TOML Example"
    assert values["owner.name"] == "Tom Preston-Werner"
    assert values["database.enabled"] is True
    assert values["database.ports"] == [8000, 8001, 8002]
    assert values["database.temp_targets.cpu"] == 79.5
    assert values["servers[0].ip"] == "10.0.0.1"
    assert values["servers[0].role"] == "frontend"
    assert values["servers[1].ip"] == "10.0.0.2"
    assert values["servers[1].role"] == "backend"

    # Verify template contains quoted placeholders
    assert 'title = "{{ title }}"' in template
    assert 'cpu = "{{ database.temp_targets.cpu }}" # CPU temperature target' in template
    assert 'ip = "{{ servers[0].ip }}" # Frontend server' in template

    # Render back
    rendered = adapter.render(template, values)
    assert rendered == SAMPLE_TOML


def test_toml_adapter_missing_values() -> None:
    adapter = TomlAdapter()
    _, template = adapter.extract_values(SAMPLE_TOML)

    with pytest.raises(MissingValuesError) as exc_info:
        adapter.render(template, {"title": "Only Title"})

    assert "owner.name" in exc_info.value.missing_keys


def test_toml_adapter_syntax_error() -> None:
    adapter = TomlAdapter()
    with pytest.raises(ConfigSyntaxError):
        adapter.extract_values("this is not = [valid toml")


def test_toml_inline_table_stays_inline() -> None:
    """Invariant 6.b: an inline table must not become a `[section]` block."""
    adapter = TomlAdapter()
    source = "pt = { x = 1, y = 2 }\n"

    values, template = adapter.extract_values(source)

    assert values == {"pt.x": 1, "pt.y": 2}
    assert template == 'pt = { x = "{{ pt.x }}", y = "{{ pt.y }}" }\n'

    rendered = adapter.render(template, values)

    assert rendered == source
    assert "[pt]" not in rendered

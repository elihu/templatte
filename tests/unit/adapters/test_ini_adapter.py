"""Unit tests for INI and .properties format adapter."""

from pathlib import Path

import pytest

from templatte.adapters.ini_adapter import IniAdapter
from templatte.core.exceptions import MissingValuesError

SAMPLE_INI = """# Database settings
[database]
host = localhost
port = 5432 ; default postgres port
enabled = true
ports = 8000,8001,8002

[service]
timeout = 30.5
name = my_service
"""


def test_ini_adapter_can_handle() -> None:
    adapter = IniAdapter()
    assert adapter.can_handle(Path("config.ini")) is True
    assert adapter.can_handle(Path("app.properties")) is True
    assert adapter.can_handle(Path("setup.cfg")) is True
    assert adapter.can_handle(Path("nginx.conf.latte")) is True
    assert adapter.can_handle(Path("config.yaml")) is False


def test_ini_adapter_roundtrip() -> None:
    adapter = IniAdapter()
    values, template = adapter.extract_values(SAMPLE_INI)

    assert values["database.host"] == "localhost"
    assert values["database.port"] == 5432
    assert values["database.enabled"] is True
    assert values["database.ports"] == [8000, 8001, 8002]
    assert values["service.timeout"] == 30.5
    assert values["service.name"] == "my_service"

    # Template retains structure and inline comment
    assert "; default postgres port" in template
    assert "{{ database.port }}" in template

    rendered = adapter.render(template, values)
    assert rendered == SAMPLE_INI


def test_ini_adapter_missing_keys() -> None:
    adapter = IniAdapter()
    _, template = adapter.extract_values(SAMPLE_INI)

    with pytest.raises(MissingValuesError):
        adapter.render(template, {"database.host": "localhost"})

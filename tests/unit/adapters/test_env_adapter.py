"""Unit tests for .env format adapter."""

from pathlib import Path

import pytest

from templatte.adapters.env_adapter import EnvAdapter
from templatte.core.exceptions import MissingValuesError

SAMPLE_ENV = """# Application configuration
APP_NAME=templatte
PORT=8080
DEBUG=true

# Secrets
SECRET_KEY="super secret passphrase"
DATABASE_URL=postgres://localhost:5432/db
"""


def test_env_adapter_can_handle() -> None:
    adapter = EnvAdapter()
    assert adapter.can_handle(Path(".env")) is True
    assert adapter.can_handle(Path(".env.local")) is True
    assert adapter.can_handle(Path(".env.latte")) is True
    assert adapter.can_handle(Path(".env.production.latte")) is True
    assert adapter.can_handle(Path("config.toml")) is False


def test_env_adapter_roundtrip() -> None:
    adapter = EnvAdapter()
    values, template = adapter.extract_values(SAMPLE_ENV)

    assert values["APP_NAME"] == "templatte"
    assert values["PORT"] == 8080
    assert values["DEBUG"] is True
    assert values["SECRET_KEY"] == "super secret passphrase"
    assert values["DATABASE_URL"] == "postgres://localhost:5432/db"

    # Template preserves comments
    assert "# Application configuration" in template
    assert "{{ SECRET_KEY }}" in template

    rendered = adapter.render(template, values)
    assert rendered == SAMPLE_ENV


def test_env_adapter_missing_keys() -> None:
    adapter = EnvAdapter()
    _, template = adapter.extract_values(SAMPLE_ENV)

    with pytest.raises(MissingValuesError):
        adapter.render(template, {"APP_NAME": "templatte"})

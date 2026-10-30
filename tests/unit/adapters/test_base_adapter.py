"""Unit tests for adapter base protocol and dispatch registry."""

import pytest

from templatte.adapters import (
    EnvAdapter,
    IniAdapter,
    JsonAdapter,
    TomlAdapter,
    YamlAdapter,
    get_adapter_by_format,
    get_adapter_for_file,
)
from templatte.core.exceptions import UnsupportedFormatError


def test_get_adapter_for_file() -> None:
    assert isinstance(get_adapter_for_file("app.toml"), TomlAdapter)
    assert isinstance(get_adapter_for_file("app.yaml"), YamlAdapter)
    assert isinstance(get_adapter_for_file("app.yml"), YamlAdapter)
    assert isinstance(get_adapter_for_file("app.json"), JsonAdapter)
    assert isinstance(get_adapter_for_file("app.ini"), IniAdapter)
    assert isinstance(get_adapter_for_file("app.properties"), IniAdapter)
    assert isinstance(get_adapter_for_file(".env"), EnvAdapter)
    assert isinstance(get_adapter_for_file(".env.local"), EnvAdapter)

    with pytest.raises(UnsupportedFormatError):
        get_adapter_for_file("script.py")


def test_get_adapter_by_format() -> None:
    assert isinstance(get_adapter_by_format("toml"), TomlAdapter)
    assert isinstance(get_adapter_by_format("yaml"), YamlAdapter)
    assert isinstance(get_adapter_by_format("json"), JsonAdapter)
    assert isinstance(get_adapter_by_format("ini"), IniAdapter)
    assert isinstance(get_adapter_by_format("env"), EnvAdapter)

    with pytest.raises(UnsupportedFormatError):
        get_adapter_by_format("xml")

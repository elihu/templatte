"""Unit tests for domain models."""

from pathlib import Path

import pytest

from templatte.core.models import (
    ConfigFile,
    CryptoEnvelope,
    FileEntry,
    ProfileFileEntry,
    TemplateFile,
    ValuesRegistry,
)


def test_config_file_model() -> None:
    cf = ConfigFile(path=Path("config/app.toml"), format="toml", content="title = 'test'")
    assert cf.format == "toml"
    assert cf.path == Path("config/app.toml")
    assert cf.content == "title = 'test'"


def test_template_file_model() -> None:
    tf = TemplateFile.from_path("config/app.toml.latte")
    assert tf.path == Path("config/app.toml.latte")
    assert tf.target_path == Path("config/app.toml")

    with pytest.raises(ValueError, match=r"Template file path must end with \.latte"):
        TemplateFile.from_path("config/app.toml")


def test_values_registry_model() -> None:
    registry = ValuesRegistry(
        files={
            "config/app.toml": FileEntry(
                format="toml",
                values={"server.port": 8080, "server.host": "localhost"},
                secrets={"auth.token": True},
            )
        },
        profiles={
            "prod": {
                "config/app.toml": ProfileFileEntry(
                    values={"server.host": "api.production.internal"}
                )
            }
        },
    )

    # Default profile values
    default_vals = registry.get_effective_values("config/app.toml")
    assert default_vals["server.port"] == 8080
    assert default_vals["server.host"] == "localhost"

    # Prod profile values
    prod_vals = registry.get_effective_values("config/app.toml", profile="prod")
    assert prod_vals["server.port"] == 8080
    assert prod_vals["server.host"] == "api.production.internal"


def test_crypto_envelope_model() -> None:
    env_dict = {
        "$schema": "https://templatte.dev/schema/v1/encrypted.json",
        "version": 1,
        "algorithm": "AES-256-GCM",
        "kdf": {
            "name": "PBKDF2HMAC",
            "hash": "SHA256",
            "iterations": 600000,
            "salt": "c2FsdF8zMl9ieXRlcw==",
        },
        "iv": "aXZfMTJfYnl0ZXM=",
        "tag": "dGFnXzE2X2J5dGVz",
        "ciphertext": "Y2lwaGVydGV4dA==",
    }
    envelope = CryptoEnvelope.model_validate(env_dict)
    assert envelope.version == 1
    assert envelope.algorithm == "AES-256-GCM"
    assert envelope.kdf.iterations == 600000

    dumped = envelope.model_dump(by_alias=True)
    assert "$schema" in dumped
    assert dumped["$schema"] == "https://templatte.dev/schema/v1/encrypted.json"

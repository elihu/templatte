"""Unit tests for domain exceptions hierarchy."""

from templatte.core.exceptions import (
    ConfigurationDriftError,
    CorruptedEnvelopeError,
    GitLeakError,
    InvalidPassphraseError,
    LegacyRegistryError,
    MissingTemplateError,
    MissingValuesError,
    PathTraversalError,
    TemplatteError,
    UsageError,
    ValidationError,
    WeakPassphraseError,
)


def test_exception_exit_codes() -> None:
    # General / Base
    base_err = TemplatteError("Generic error")
    assert base_err.exit_code == 1

    # Usage
    usage_err = UsageError("Bad arguments")
    assert usage_err.exit_code == 2
    traversal_err = PathTraversalError("../secret", "/workspace")
    assert traversal_err.exit_code == 2

    # Validation
    val_err = ValidationError("Invalid config")
    assert val_err.exit_code == 3
    missing_tpl = MissingTemplateError("app.toml.latte")
    assert missing_tpl.exit_code == 3
    missing_val = MissingValuesError("app.toml", ["db.password"])
    assert missing_val.exit_code == 3
    legacy_err = LegacyRegistryError("templatte.toml")
    assert legacy_err.exit_code == 3
    assert "templatte migrate" in str(legacy_err)

    # Crypto
    invalid_pw = InvalidPassphraseError()
    assert invalid_pw.exit_code == 4
    weak_pw = WeakPassphraseError()
    assert weak_pw.exit_code == 4
    corrupt_env = CorruptedEnvelopeError("Invalid JSON")
    assert corrupt_env.exit_code == 4

    # Drift & Git Leak
    drift_err = ConfigurationDriftError("app.toml")
    assert drift_err.exit_code == 5
    leak_err = GitLeakError("app.toml", "is tracked by Git")
    assert leak_err.exit_code == 5


def test_exception_to_dict() -> None:
    err = MissingValuesError("config/app.toml", ["db.port", "db.host"])
    data = err.to_dict()

    assert data["status"] == "error"
    assert data["exit_code"] == 3
    assert data["error_type"] == "MissingValuesError"
    assert data["details"]["file"] == "config/app.toml"
    assert data["details"]["missing_keys"] == ["db.port", "db.host"]

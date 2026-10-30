"""Domain exceptions hierarchy mapped to CLI exit codes."""

from __future__ import annotations

from typing import Any


class TemplatteError(Exception):
    """Base exception for all Templatte domain errors.

    Mapped to exit code 1 (ERROR_GENERAL) by default.
    """

    exit_code: int = 1

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        """Serialize error for machine-readable JSON output (--json)."""
        data: dict[str, Any] = {
            "status": "error",
            "exit_code": self.exit_code,
            "error_type": self.__class__.__name__,
            "message": self.message,
        }
        if self.details:
            data["details"] = self.details
        return data


# --- Exit Code 2: Usage Errors ---


class UsageError(TemplatteError):
    """Raised for invalid CLI usage, bad flags or workspace path issues."""

    exit_code: int = 2


class PathTraversalError(UsageError):
    """Raised when a file path attempts to escape the designated workspace boundary."""

    def __init__(self, path: str, workspace: str) -> None:
        super().__init__(
            f"Security violation: path '{path}' traverses outside workspace '{workspace}'",
            details={"path": path, "workspace": workspace},
        )


# --- Exit Code 3: Validation Errors ---


class ValidationError(TemplatteError):
    """Raised when values or templates fail validation or are missing."""

    exit_code: int = 3


class MissingTemplateError(ValidationError):
    """Raised when a requested template file does not exist."""

    def __init__(self, template_path: str) -> None:
        super().__init__(
            f"Template file not found: '{template_path}'",
            details={"template": template_path},
        )


class MissingValuesError(ValidationError):
    """Raised when placeholders in a template have no matching values in the registry."""

    def __init__(self, file_path: str, missing_keys: list[str]) -> None:
        keys_str = ", ".join(missing_keys)
        super().__init__(
            f"Missing required template values for '{file_path}': [{keys_str}]",
            details={"file": file_path, "missing_keys": missing_keys},
        )
        self.file_path = file_path
        self.missing_keys = missing_keys


class ConfigSyntaxError(ValidationError):
    """Raised when parsing configuration or template fails due to syntax errors."""

    def __init__(self, file_path: str, reason: str) -> None:
        super().__init__(
            f"Failed to parse '{file_path}': {reason}",
            details={"file": file_path, "reason": reason},
        )


class UnsupportedFormatError(ValidationError):
    """Raised when an unsupported file format or extension is encountered."""

    def __init__(self, file_path: str) -> None:
        super().__init__(
            f"No adapter available for configuration format of '{file_path}'",
            details={"file": file_path},
        )


class LegacyRegistryError(ValidationError):
    """Raised when templatte.toml lacks a version field (pre-2.0 flat schema).

    Directs user to run `templatte migrate`.
    """

    def __init__(self, config_file: str = "templatte.toml") -> None:
        super().__init__(
            f"Legacy registry detected in '{config_file}'. "
            "Please run 'templatte migrate' to upgrade the schema to Templatte 2.0.",
            details={"file": config_file, "action_required": "templatte migrate"},
        )


# --- Exit Code 4: Crypto Errors ---


class CryptoError(TemplatteError):
    """Base error for cryptographic operations and envelope verification."""

    exit_code: int = 4


class InvalidPassphraseError(CryptoError):
    """Raised when passphrase is wrong or authentication tag / AAD fails."""

    def __init__(self, message: str = "Invalid passphrase or corrupted authentication tag") -> None:
        super().__init__(message)


class WeakPassphraseError(CryptoError):
    """Raised when passphrase does not satisfy minimum length requirements."""

    def __init__(self, min_length: int = 14) -> None:
        super().__init__(
            f"Passphrase must be at least {min_length} characters long",
            details={"min_length": min_length},
        )


class CorruptedEnvelopeError(CryptoError):
    """Raised when cryptographic envelope JSON structure is corrupted or invalid."""

    def __init__(self, reason: str) -> None:
        super().__init__(
            f"Cryptographic envelope is corrupted or invalid: {reason}",
            details={"reason": reason},
        )


# --- Exit Code 5: Drift & Git Leak Errors ---


class DriftError(TemplatteError):
    """Base error for configuration drift and uncommitted secret leaks."""

    exit_code: int = 5


class ConfigurationDriftError(DriftError):
    """Raised when concrete config files differ from rendered templates."""

    def __init__(self, file_path: str, diff: str | None = None) -> None:
        super().__init__(
            f"Configuration drift detected in '{file_path}'",
            details={"file": file_path, "diff": diff},
        )


class GitLeakError(DriftError):
    """Raised when a secret or concrete config is tracked or untracked without .gitignore."""

    def __init__(self, file_path: str, reason: str) -> None:
        super().__init__(
            f"Git Leak Warning: '{file_path}' {reason}. Run 'templatte grind' or 'git rm --cached {file_path}'",
            details={"file": file_path, "reason": reason},
        )

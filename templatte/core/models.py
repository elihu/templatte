"""Pydantic domain models for Templatte 2.0."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ConfigFile(BaseModel):
    """Represents a concrete configuration file in the workspace."""

    path: Path
    format: str
    content: str | None = None

    model_config = ConfigDict(arbitrary_types_allowed=True)


class TemplateFile(BaseModel):
    """Represents a .latte configuration template file."""

    path: Path
    target_path: Path
    content: str | None = None

    model_config = ConfigDict(arbitrary_types_allowed=True)

    @classmethod
    def from_path(cls, path: Path | str, content: str | None = None) -> TemplateFile:
        p = Path(path)
        if not p.name.endswith(".latte"):
            raise ValueError(f"Template file path must end with .latte, got '{p}'")
        target = p.with_name(p.name[:-6])
        return cls(path=p, target_path=target, content=content)


class WorkspaceConfig(BaseModel):
    """Workspace-level scanning and ignoring configuration."""

    ignored_patterns: list[str] = Field(default_factory=list)


class TemplateConfig(BaseModel):
    """Template delimiter configuration."""

    open: str = "{{"
    close: str = "}}"


class FileEntry(BaseModel):
    """Registry entry for a single configuration file."""

    format: str
    values: dict[str, Any] = Field(default_factory=dict)
    secrets: dict[str, bool] = Field(default_factory=dict)


class ProfileFileEntry(BaseModel):
    """Profile-specific value overrides for a file."""

    values: dict[str, Any] = Field(default_factory=dict)
    secrets: dict[str, bool] = Field(default_factory=dict)


class ValuesRegistry(BaseModel):
    """Central values registry model (templatte.toml schema)."""

    version: int = 1
    default_profile: str = "default"
    workspace: WorkspaceConfig = Field(default_factory=WorkspaceConfig)
    template: TemplateConfig = Field(default_factory=TemplateConfig)
    files: dict[str, FileEntry] = Field(default_factory=dict)
    profiles: dict[str, dict[str, ProfileFileEntry]] = Field(default_factory=dict)

    def get_effective_values(self, file_path: str, profile: str | None = None) -> dict[str, Any]:
        """Get flattened dot-path values for a file, applying profile overrides if present."""
        target_profile = profile or self.default_profile
        base_values = dict(self.files.get(file_path, FileEntry(format="unknown")).values)
        if target_profile in self.profiles and file_path in self.profiles[target_profile]:
            override_values = self.profiles[target_profile][file_path].values
            base_values.update(override_values)
        return base_values


class KdfConfig(BaseModel):
    """Key derivation function parameters in cryptographic envelope."""

    name: str = "PBKDF2HMAC"
    hash: str = "SHA256"
    iterations: int = 600_000
    salt: str


class CryptoEnvelope(BaseModel):
    """Authenticated encryption envelope for templatte.toml.enc."""

    schema_url: str = Field(
        default="https://templatte.dev/schema/v1/encrypted.json",
        alias="$schema",
    )
    version: int = 1
    algorithm: str = "AES-256-GCM"
    kdf: KdfConfig
    iv: str
    tag: str
    ciphertext: str

    model_config = ConfigDict(populate_by_name=True)


class WorkspaceContext(BaseModel):
    """Runtime workspace execution context."""

    root: Path
    config_file: Path
    profile: str = "default"
    dry_run: bool = False
    force: bool = False

    model_config = ConfigDict(arbitrary_types_allowed=True)

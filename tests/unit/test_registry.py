"""Unit tests for values registry persistence and version enforcement."""

from pathlib import Path

import pytest

from templatte.core.exceptions import LegacyRegistryError
from templatte.core.models import FileEntry, ProfileFileEntry, ValuesRegistry
from templatte.core.registry import RegistryManager, load_registry, save_registry


def test_load_valid_registry(tmp_path: Path) -> None:
    toml_content = """
# templatte.toml - test
version = 1
default_profile = "default"

[workspace]
ignored_patterns = ["dist/**"]

[template]
open = "{{"
close = "}}"

[files."config/app.toml"]
format = "toml"

[files."config/app.toml".values]
"server.port" = 8080
"server.host" = "0.0.0.0"

[files."config/app.toml".secrets]
"auth.jwt" = true

[profiles.prod."config/app.toml".values]
"server.host" = "api.internal"
"""
    reg_path = tmp_path / "templatte.toml"
    reg_path.write_text(toml_content.strip(), encoding="utf-8")

    manager = RegistryManager(workspace_root=tmp_path)
    registry = manager.load(reg_path)

    assert registry.version == 1
    assert registry.default_profile == "default"
    assert registry.workspace.ignored_patterns == ["dist/**"]
    assert "config/app.toml" in registry.files
    file_entry = registry.files["config/app.toml"]
    assert file_entry.format == "toml"
    assert file_entry.values["server.port"] == 8080
    assert file_entry.secrets["auth.jwt"] is True

    # Profile override
    assert "prod" in registry.profiles
    assert registry.get_effective_values("config/app.toml", profile="prod")["server.host"] == "api.internal"


def test_detect_legacy_registry_raises_error(tmp_path: Path) -> None:
    legacy_content = """
# Legacy registry lacking top-level 'version'
"config/app.toml_server.port" = 8080
"""
    reg_path = tmp_path / "templatte.toml"
    reg_path.write_text(legacy_content.strip(), encoding="utf-8")

    manager = RegistryManager(workspace_root=tmp_path)
    with pytest.raises(LegacyRegistryError, match="templatte migrate") as exc_info:
        manager.load(reg_path)

    assert exc_info.value.exit_code == 3


def test_save_and_roundtrip_registry(tmp_path: Path) -> None:
    registry = ValuesRegistry(
        version=1,
        default_profile="default",
        files={
            "app.yaml": FileEntry(
                format="yaml",
                values={"db.host": "localhost", "db.port": 5432},
                secrets={"db.password": True},
            )
        },
        profiles={
            "staging": {
                "app.yaml": ProfileFileEntry(
                    values={"db.host": "staging.db"}
                )
            }
        },
    )

    reg_path = tmp_path / "templatte.toml"
    save_registry(registry, reg_path)

    assert reg_path.exists()
    loaded = load_registry(reg_path)

    assert loaded.version == 1
    assert "app.yaml" in loaded.files
    assert loaded.files["app.yaml"].values["db.host"] == "localhost"
    assert loaded.files["app.yaml"].values["db.port"] == 5432
    assert loaded.files["app.yaml"].secrets["db.password"] is True
    assert loaded.profiles["staging"]["app.yaml"].values["db.host"] == "staging.db"


def test_save_preserves_comments_with_existing_doc(tmp_path: Path) -> None:
    initial_content = """# Header comment
version = 1
default_profile = "default"

# Database file section
[files."db.toml"]
format = "toml"

[files."db.toml".values]
# The database port
"port" = 5432
"""
    reg_path = tmp_path / "templatte.toml"
    reg_path.write_text(initial_content, encoding="utf-8")

    manager = RegistryManager(workspace_root=tmp_path)
    doc = manager.load_document(reg_path)
    model = manager.document_to_model(doc)

    # Update value
    model.files["db.toml"].values["port"] = 5433

    # Save with existing doc
    manager.save(model, reg_path, existing_doc=doc)

    updated_text = reg_path.read_text(encoding="utf-8")
    assert "# Header comment" in updated_text
    assert "# Database file section" in updated_text
    assert "# The database port" in updated_text
    assert "5433" in updated_text

"""Values registry persistence and schema management (templatte.toml)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import tomlkit
from tomlkit.toml_document import TOMLDocument

from templatte.core.exceptions import LegacyRegistryError
from templatte.core.models import (
    FileEntry,
    ProfileFileEntry,
    TemplateConfig,
    ValuesRegistry,
    WorkspaceConfig,
)
from templatte.utils.fs import AtomicFileWriter, normalize_workspace_path


class RegistryManager:
    """Manages loading, updating, and saving of templatte.toml registries."""

    def __init__(self, workspace_root: Path | str | None = None) -> None:
        self.workspace_root = Path(workspace_root).resolve() if workspace_root else Path.cwd()

    def parse_document(self, content: str, source_path: str = "templatte.toml") -> TOMLDocument:
        """Parse raw TOML string and ensure version compatibility."""
        doc = tomlkit.parse(content)
        if "version" not in doc:
            raise LegacyRegistryError(source_path)
        return doc

    def load_document(self, path: Path | str) -> TOMLDocument:
        """Read templatte.toml and return TOMLDocument, enforcing schema version."""
        p = Path(path)
        if not p.is_absolute():
            p = self.workspace_root / p
        content = p.read_text(encoding="utf-8")
        return self.parse_document(
            content, source_path=normalize_workspace_path(p, self.workspace_root)
        )

    def load(self, path: Path | str) -> ValuesRegistry:
        """Load templatte.toml into a validated ValuesRegistry Pydantic model."""
        doc = self.load_document(path)
        return self.document_to_model(doc)

    def document_to_model(self, doc: TOMLDocument | dict[str, Any]) -> ValuesRegistry:
        """Convert a parsed tomlkit TOMLDocument or dict into ValuesRegistry model."""
        version = int(doc.get("version", 1))
        default_profile = str(doc.get("default_profile", "default"))

        ws_data = doc.get("workspace", {})
        workspace_cfg = WorkspaceConfig(ignored_patterns=list(ws_data.get("ignored_patterns", [])))

        tpl_data = doc.get("template", {})
        template_cfg = TemplateConfig(
            open=str(tpl_data.get("open", "{{")),
            close=str(tpl_data.get("close", "}}")),
        )

        files: dict[str, FileEntry] = {}
        if "files" in doc and isinstance(doc["files"], dict):
            for file_path, file_data in doc["files"].items():
                if isinstance(file_data, dict):
                    format_name = str(file_data.get("format", "unknown"))
                    vals = dict(file_data.get("values", {}))
                    secs = dict(file_data.get("secrets", {}))
                    files[file_path] = FileEntry(format=format_name, values=vals, secrets=secs)

        profiles: dict[str, dict[str, ProfileFileEntry]] = {}
        if "profiles" in doc and isinstance(doc["profiles"], dict):
            for prof_name, prof_files in doc["profiles"].items():
                if isinstance(prof_files, dict):
                    profiles[prof_name] = {}
                    for file_path, file_data in prof_files.items():
                        if isinstance(file_data, dict):
                            vals = dict(file_data.get("values", {}))
                            secs = dict(file_data.get("secrets", {}))
                            profiles[prof_name][file_path] = ProfileFileEntry(
                                values=vals, secrets=secs
                            )

        return ValuesRegistry(
            version=version,
            default_profile=default_profile,
            workspace=workspace_cfg,
            template=template_cfg,
            files=files,
            profiles=profiles,
        )

    def model_to_document(
        self,
        registry: ValuesRegistry,
        existing_doc: TOMLDocument | None = None,
    ) -> TOMLDocument:
        """Convert ValuesRegistry model to tomlkit document, preserving existing structure if available."""
        doc = existing_doc if existing_doc is not None else tomlkit.document()

        doc["version"] = registry.version
        doc["default_profile"] = registry.default_profile

        if registry.workspace.ignored_patterns or "workspace" in doc:
            ws_table = doc.get("workspace", tomlkit.table())
            ws_table["ignored_patterns"] = registry.workspace.ignored_patterns
            doc["workspace"] = ws_table

        if (registry.template.open != "{{" or registry.template.close != "}}") or "template" in doc:
            tpl_table = doc.get("template", tomlkit.table())
            tpl_table["open"] = registry.template.open
            tpl_table["close"] = registry.template.close
            doc["template"] = tpl_table

        files_table = doc.get("files", tomlkit.table())
        for file_path, file_entry in registry.files.items():
            f_table = files_table.get(file_path, tomlkit.table())
            f_table["format"] = file_entry.format

            v_table = f_table.get("values", tomlkit.table())
            for k, v in file_entry.values.items():
                v_table[k] = v
            f_table["values"] = v_table

            if file_entry.secrets:
                s_table = f_table.get("secrets", tomlkit.table())
                for k, s in file_entry.secrets.items():
                    s_table[k] = s
                f_table["secrets"] = s_table

            files_table[file_path] = f_table
        doc["files"] = files_table

        if registry.profiles:
            profiles_table = doc.get("profiles", tomlkit.table())
            for prof_name, prof_data in registry.profiles.items():
                p_table = profiles_table.get(prof_name, tomlkit.table())
                for file_path, p_file_entry in prof_data.items():
                    pf_table = p_table.get(file_path, tomlkit.table())
                    pv_table = pf_table.get("values", tomlkit.table())
                    for k, v in p_file_entry.values.items():
                        pv_table[k] = v
                    pf_table["values"] = pv_table
                    if p_file_entry.secrets:
                        ps_table = pf_table.get("secrets", tomlkit.table())
                        for k, s in p_file_entry.secrets.items():
                            ps_table[k] = s
                        pf_table["secrets"] = ps_table
                    p_table[file_path] = pf_table
                profiles_table[prof_name] = p_table
            doc["profiles"] = profiles_table

        return doc

    def save(
        self,
        registry: ValuesRegistry,
        path: Path | str,
        existing_doc: TOMLDocument | None = None,
    ) -> None:
        """Atomically persist ValuesRegistry to disk using AtomicFileWriter."""
        p = Path(path)
        if not p.is_absolute():
            p = self.workspace_root / p

        doc = self.model_to_document(registry, existing_doc=existing_doc)
        content = tomlkit.dumps(doc)
        with AtomicFileWriter(p, mode="w", encoding="utf-8") as f:
            f.write(content)


def load_registry(path: Path | str, workspace_root: Path | str | None = None) -> ValuesRegistry:
    """Convenience helper to load a values registry from a path."""
    return RegistryManager(workspace_root=workspace_root).load(path)


def save_registry(
    registry: ValuesRegistry,
    path: Path | str,
    workspace_root: Path | str | None = None,
) -> None:
    """Convenience helper to atomically save a values registry to a path."""
    RegistryManager(workspace_root=workspace_root).save(registry, path)

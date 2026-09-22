# Templatte 2.0: Architecture & Extensibility Specification

**Document:** `docs/spec/02_ARCHITECTURE_AND_EXTENSIBILITY.md`  
**Status:** Approved for Implementation  
**Pattern:** Ports & Adapters (Hexagonal) / Clean Architecture  

---

## 1. High-Level Architecture

Templatte 2.0 is structured into decoupled layers, separating presentation (CLI) and file system details from core business rules and format parsing logic.

```
┌─────────────────────────────────────────────────────────────┐
│                      Presentation Layer                     │
│    typer CLI Commands │ Rich Console UX │ JSON Presenter    │
└──────────────────────────────┬──────────────────────────────┘
                               │ calls
┌──────────────────────────────▼──────────────────────────────┐
│                    Application Services                     │
│  GenelatteService │ DeployService │ GrindService            │
│  CryptoService    │ CheckService  │ DiffService             │
└──────────────┬──────────────────────────────┬───────────────┘
               │ operates on                  │ interacts with
┌──────────────▼──────────────┐┌──────────────▼───────────────┐
│        Domain Models        ││         Ports & Adapters     │
│  • ConfigFile               ││  • FormatAdapter (Protocol)  │
│  • TemplateFile             ││    ├── TomlAdapter           │
│  • ValuesRegistry           ││    ├── YamlAdapter           │
│  • CryptoEnvelope           ││    ├── JsonAdapter           │
│  • WorkspaceContext         ││    ├── IniAdapter            │
│                             ││    └── EnvAdapter            │
│                             ││  • CryptoEngine (Protocol)   │
│                             ││    └── AesGcmCryptoEngine    │
│                             ││  • FileSystem / AtomicWriter │
└─────────────────────────────┘└──────────────────────────────┘
```

---

## 2. Directory Layout & Module Structure

The refactored package adheres to standard modern Python layout:

```text
templatte/
├── __init__.py                 # Version & public metadata
├── cli/                        # Presentation Layer
│   ├── __init__.py
│   ├── app.py                  # Main Typer app initialization
│   ├── commands/               # Modular command groups
│   │   ├── genelatte.py
│   │   ├── deploy.py
│   │   ├── grind.py
│   │   ├── press.py
│   │   ├── pour.py
│   │   └── check.py
│   ├── console.py              # Rich theme, barista banners & formatters
│   └── output.py               # JSON vs Text response handler
├── core/                       # Domain & Application Logic
│   ├── __init__.py
│   ├── models.py               # Pydantic / Dataclass domain entities
│   ├── exceptions.py           # Typed domain exception hierarchy
│   ├── registry.py             # ValuesRegistry parser and manager
│   ├── services/               # Orchestration use cases
│   │   ├── scanner.py          # Workspace file discovery
│   │   ├── generator.py        # Genelatte use case
│   │   ├── deployer.py         # Deploy use case
│   │   ├── cleaner.py          # Grind use case
│   │   ├── checker.py          # Check/Roast use case
│   │   └── crypto.py           # Press/Pour orchestration
├── adapters/                   # Ports & Adapter Implementations
│   ├── __init__.py
│   ├── base.py                 # FormatAdapter base protocol
│   ├── toml_adapter.py         # TOML parsing & comment-preserving rendering
│   ├── yaml_adapter.py         # YAML adapter (ruamel.yaml or PyYAML)
│   ├── json_adapter.py         # JSON adapter
│   ├── ini_adapter.py          # INI / Properties adapter
│   ├── env_adapter.py          # .env key-value adapter
│   └── crypto/
│       ├── engine.py           # AES-256-GCM authenticated cipher
│       └── envelope.py         # JSON envelope serialization
└── utils/                      # Low-level utilities
    ├── fs.py                   # Atomic file writing & path sanitization
    └── ignore.py               # .gitignore pattern evaluator
```

---

## 3. FormatAdapter Port Specification

Every configuration format supported by Templatte implements the `FormatAdapter` Protocol:

```python
from typing import Protocol, Any, runtime_checkable
from pathlib import Path

@runtime_checkable
class FormatAdapter(Protocol):
    """Protocol for configuration format adapters."""
    
    format_name: str
    supported_extensions: tuple[str, ...]

    def can_handle(self, file_path: Path) -> bool:
        """Determines if this adapter supports the given file."""
        ...

    def extract_values(self, content: str) -> tuple[dict[str, Any], str]:
        """
        Parses configuration content.
        Returns:
            - A flat dictionary of leaf dot-paths to values (e.g. {'db.port': 5432}).
            - The generated template content containing placeholder tags.
        """
        ...

    def render(self, template_content: str, values: dict[str, Any]) -> str:
        """
        Renders template content by replacing placeholders with typed values,
        preserving formatting and comments.
        """
        ...
```

### 3.1 Format Adapter Registry
A centralized `AdapterRegistry` dispatches files to the appropriate adapter:
```python
class AdapterRegistry:
    def __init__(self):
        self._adapters: list[FormatAdapter] = []

    def register(self, adapter: FormatAdapter) -> None:
        self._adapters.append(adapter)

    def get_adapter_for_file(self, path: Path) -> FormatAdapter:
        for adapter in self._adapters:
            if adapter.can_handle(path):
                return adapter
        raise UnsupportedFormatError(f"No adapter found for file {path}")
```

---

## 4. Cryptographic Engine Specification

### 4.1 Native Cross-Platform Cryptography
Instead of depending on an external `gpg` binary, Templatte utilizes Python's standard `cryptography` library (`hazmat.primitives.ciphers.aead.AESGCM`).

```python
import os
import base64
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

class AesGcmCryptoEngine:
    SALT_BYTES = 32
    NONCE_BYTES = 12
    KEY_BYTES = 32  # 256 bits
    ITERATIONS = 600_000

    def encrypt(self, plaintext: bytes, passphrase: str) -> dict:
        salt = os.urandom(self.SALT_BYTES)
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=self.KEY_BYTES,
            salt=salt,
            iterations=self.ITERATIONS,
        )
        key = kdf.derive(passphrase.encode("utf-8"))
        
        nonce = os.urandom(self.NONCE_BYTES)
        aesgcm = AESGCM(key)
        ciphertext_and_tag = aesgcm.encrypt(nonce, plaintext, None)
        
        # In AESGCM, the 16-byte authentication tag is appended to the ciphertext
        tag = ciphertext_and_tag[-16:]
        ciphertext = ciphertext_and_tag[:-16]

        return {
            "version": 1,
            "algorithm": "AES-256-GCM",
            "kdf": {
                "name": "PBKDF2HMAC",
                "hash": "SHA256",
                "iterations": self.ITERATIONS,
                "salt": base64.b64encode(salt).decode("ascii"),
            },
            "iv": base64.b64encode(nonce).decode("ascii"),
            "tag": base64.b64encode(tag).decode("ascii"),
            "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
        }

    def decrypt(self, envelope: dict, passphrase: str) -> bytes:
        salt = base64.b64decode(envelope["kdf"]["salt"])
        iterations = envelope["kdf"]["iterations"]
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=self.KEY_BYTES,
            salt=salt,
            iterations=iterations,
        )
        key = kdf.derive(passphrase.encode("utf-8"))
        
        nonce = base64.b64decode(envelope["iv"])
        ciphertext = base64.b64decode(envelope["ciphertext"])
        tag = base64.b64decode(envelope["tag"])
        
        aesgcm = AESGCM(key)
        # Recombine ciphertext and tag for verification
        return aesgcm.decrypt(nonce, ciphertext + tag, None)
```

---

## 5. File System Safety & Atomic Operations

To prevent data corruption during crashes or aborted runs:
1. **Atomic Writes (`AtomicFileWriter`):**
   * Files are always written to a temporary sibling file (e.g. `config.toml.tmp.12345`).
   * Once flushed and fsynced, `os.replace` replaces the target file atomically.
2. **Path Sanitization:**
   * Relative paths are validated to ensure they do not traverse outside the workspace root (`path.resolve().is_relative_to(workspace_root)`).
3. **Workspace Ignore Filtering:**
   * Files matching `.gitignore` or standard excludes (`.git`, `.venv`, `node_modules`, `dist`, `__pycache__`) are skipped automatically.

---

## 6. Modern Packaging, Toolchain & Git Architecture

### 6.1 Toolchain Standards: `uv` and PEP 621
Templatte 2.0 standardizes exclusively on **`uv`** as its fast, deterministic package manager, virtual environment manager, and project toolchain:
* **Project Spec:** Standard Python PEP 621 in `pyproject.toml`.
* **Build System Backend:** `hatchling`.
* **Target Python Versions:** Python `>=3.10` up to `3.14+`.
* **Dependency Matrix:**
  * `typer>=0.15.1`: Modern typed CLI with sub-command routing and shell completion.
  * `rich>=13.7.1`: Modern terminal output, tables, status spinners, and syntax highlighting.
  * `cryptography>=42.0.0`: Authenticated AES-256-GCM cipher without external binary requirements.
  * `tomlkit>=0.13.2`: Comment-preserving, structure-preserving TOML parser and serializer.
  * `pyyaml>=6.0.2`: Standard YAML serialization.
  * `pydantic>=2.6.0`: Strict data validation and schema serialization.
* **Development & Quality Tools:**
  * `pytest>=8.0.0`, `pytest-cov>=4.1.0`
  * `ruff>=0.3.0` (Linter and code formatter replacing flake8, isort, and black).

### 6.2 Git Architecture (`templatte.utils.git`)
The utility module `templatte.utils.git` encapsulates repository interaction:
* `is_git_repo(path: Path) -> bool`
* `get_tracked_files(workspace: Path) -> set[str]`: queries `git ls-files` without shell injection risk.
* `ensure_gitignored(workspace: Path, patterns: list[str]) -> bool`: parses and safely updates `.gitignore`.


# Templatte: Comprehensive Technical & Functional Audit Report

**Date:** September 2026  
**Audited Branch:** `main` (commit `427e2ce`)  
**Project:** `templatte` (v0.1.0 Alpha Prototype)  
**Authors/Maintainers:** elihu  

---

## 1. Executive Summary

**Templatte** was conceived as an elegant, coffee-themed configuration manager and templating engine designed to bridge the gap between application configuration, environment secrets, and template automation. The core metaphor is that of a barista:
* **Beans/Blend**: Concrete configuration values and secrets.
* **Latte**: Parameterized template files (`.latte`) with structural placeholders.
* **Genelatte**: Extraction of values from configs into a centralized values registry (`templatte.toml`) and generation of template files.
* **Grind**: Removal of concrete config files containing sensitive values before committing to version control.
* **Press**: Symmetric encryption of the centralized values file.
* **Pour**: Decryption of the encrypted values file.
* **Deploy**: Injection of centralized values back into templates to generate functional configuration files.

While the concept and developer experience (DX) metaphor are creative, compelling, and highly relevant, the current codebase (`v0.1.0`) is a fragile, incomplete prototype created during early AI experimentation. It suffers from critical functional bugs (including permanent data loss during `deploy`), invalid syntax generation, monolithic architectural coupling, complete lack of automated testing, and total dependency on external system binaries (`gpg`).

This audit outlines the findings across Functional, Architectural, Security, and Tooling dimensions, followed by a gap analysis against modern AI-assisted engineering standards.

---

## 2. Functional Audit

### 2.1 Command-by-Command Breakdown

| Command | Stated Intent | Current Implementation Status | Critical Flaws & Bugs |
| :--- | :--- | :--- | :--- |
| `genelatte` | Recursively scan workspace for configs, generate `.latte` templates and `templatte.toml`. | **Partially Working (TOML only)** | • Hardcoded to TOML only; ignores `config_type` argument.<br>• Generates **invalid TOML** in `.latte` files (`key = {{key}}`).<br>• Keys flattened via `f"{file_path}_{key}"` (e.g. `./tests/example.toml_database.ports`), making them brittle to relative path changes.<br>• Does not preserve comments or formatting.<br>• Scans everything recursively without respecting `.gitignore` or standard directory excludes (`.git`, `node_modules`, `.venv`, `dist`). |
| `deploy` | Populate config files by injecting values from `templatte.toml` into `.latte` templates. | **CRITICAL BUG (Data Loss)** | • **Deletes `.latte` template files upon generation** (`os.remove(file_path)` at line 348)! Subsequent runs fail because templates are deleted.<br>• Brittle parsing: reads templates with `line.strip().split(' = ')`, crashing on lines with multiple `=` or non-standard spacing.<br>• Completely destroys original TOML structure, table grouping, comments, and array-of-tables.<br>• No `--dry-run` or validation before overwriting. |
| `grind` | Recursively search for `.latte` files and delete associated concrete config files. | **Defective / Unsafe** | • If `deploy` was run previously, `.latte` files were deleted, so `grind` finds nothing.<br>• Destructive operation with no `--dry-run`, no interactive confirmation prompt, and no backup mechanism.<br>• Path extraction `file.split('.latte')[0]` is naive and breaks on files with multiple occurrences of `.latte`. |
| `press` | Encrypt `templatte.toml` with a passphrase. | **Fragile / Non-Portable** | • Hardcoded dependency on system `gpg` binary via `subprocess`. Fails immediately if GPG is not installed (e.g. in standard containers, Windows, or minimal environments).<br>• Uses `getpass.getpass()`, making it impossible to run in CI/CD, automated scripts, or via environment variables.<br>• Deletes plaintext `templatte.toml` without verifying encryption integrity. |
| `pour` | Decrypt `templatte.toml.gpg` with a passphrase. | **Fragile / Non-Portable** | • Same system `gpg` dependency.<br>• Non-interactive execution is impossible.<br>• Deletes `.gpg` file automatically upon decryption, leaving no backup if the process or subsequent steps fail. |

---

### 2.2 In-Depth Flaw Analysis

#### A. Invalid TOML in Generated Latte Files
In `templatte/main.py`:
```python
def write_template_structure_to_file(template_structure, file_path):
    with open(file_path, 'w') as f:
        for key, value in template_structure.items():
            f.write(f"{key} = {value}\n")
```
For `tests/example.toml`, this generates:
```toml
title = {{title}}
database.enabled = {{database.enabled}}
database.ports = {{database.ports}}
```
**Issue:** `{{title}}` is NOT valid TOML syntax. Any TOML linter, parser, or editor will flag this as a parse error. If a user or tool attempts to read or validate `.toml.latte`, it fails. A proper template syntax should either wrap values in valid quotes/escapes or use a recognized template engine (e.g. Jinja2 / MiniJinja) with explicit template delimiter rules.

#### B. Catastrophic Template Deletion during `deploy`
In `templatte/main.py` lines 346–349:
```python
write_value_structure_to_file(original_data, file_path.split('.latte', 1)[0])
if os.path.exists(file_path):
    # Delete the file
    os.remove(file_path)
```
**Issue:** `file_path` is the `.latte` file. Deleting the template when deploying concrete configs completely violates the lifecycle. In Git workflows, `.latte` files MUST be committed and preserved as the source of truth, while concrete configs are deployed for runtime and ignored in `.gitignore`. Once deleted, a developer cannot deploy again without re-running `genelatte`.

#### C. Brittle Key Generation & Path Sensitivity
In `templatte/main.py` line 249:
```python
file_values = {f"{file_path}_{key}": value for key, value in value_structure.items()}
```
Resulting keys in `templatte.toml`:
```toml
"./tests/example.toml_database.ports" = [ 8000, 8001, 8002,]
```
**Issue:**
1. If the command is run from `./tests` instead of `.`, the key becomes `"./example.toml_database.ports"`. Existing keys in `templatte.toml` will no longer match.
2. If a filename contains an underscore (e.g. `my_config.toml`), separating the file path from the key name via splitting becomes ambiguous.
3. The format is flat and unreadable. A structured TOML format (e.g. `[files."tests/example.toml"]`) is dramatically cleaner, deterministic, and self-documenting.

#### D. Loss of Complex Structures, Types, and Comments
* **Comments:** Standard `toml` library strips all comments when parsing and dumping.
* **Arrays of Tables:** TOML structures like `[[servers]]` are not handled properly by recursive flattening; they get converted to Python lists and cannot be restored into valid TOML table arrays.
* **Dates & Times:** TOML native datetimes are dumped without proper formatting or timezone preservation.

---

## 3. Architectural Audit

### 3.1 Monolithic Structure
The repository contains all logic inside a single file: `templatte/main.py` (397 lines).
* CLI parameter parsing, business logic, file system traversal, string formatting, serialization, and subprocess execution are completely intertwined.
* There is no separation between the **Core Domain** (templating, values registry, encryption) and the **I/O / Presentation Layer** (CLI, file system).

### 3.2 Scratch Files & Repository Hygiene
The repository contains untracked, experimental prototype scripts with severe syntax errors and hardcoded paths:
* `templatte/usecase.py`, `templatte/usecase2.py`, `templatte/usecase3.py`: Messy scripts duplicating parts of `main.py`. `usecase3.py` ends with invalid syntax (`print(...) lowcode`).
* `templatte/restore.py`: Contains unquoted dictionary keys and broken mustache syntax outside strings.
* `templatte.toml`: Checked-in/untracked values file containing paths specific to previous developer runs (`./tests/`, `./tests2/`, `./tests3/`).
* `.gitignore`: Modified to ignore `tests*`, hiding test fixtures from Git.

### 3.3 Extensibility & Format Support
* Although the project claims to support configurations generally, it is hard-coded to TOML.
* In `tests/orig/`, fixtures for YAML, JSON, INI, and `.properties` exist, but no adapter or interface exists in code to support them.
* Adding a new format requires rewriting `process_toml_files`, `generate_value_structure`, and `restore_original_toml`.

### 3.4 Cryptography Architecture
* Relying on `gpg` CLI via `subprocess.run` has major drawbacks:
  1. System dependency: gpg must be installed, on `$PATH`, and properly configured.
  2. Subprocess injection & IPC risk: passing passphrases via standard input (`--passphrase-fd 0`) can fail across operating systems (especially Windows).
  3. No envelope or metadata: The encrypted file has no version header, algorithm tag, or salt metadata.
  4. Modern alternative: A pure Python, cross-platform cryptographic standard like AES-256-GCM with PBKDF2/Argon2id (using `cryptography`) or `age` encryption provides zero-dependency portability and robust security.

---

## 4. Dependencies & Packaging Audit

| Dependency / Tool | Current Version | Modern Standard (2026) | Assessment |
| :--- | :--- | :--- | :--- |
| **Python** | `^3.10` | `3.10 - 3.14+` | Outdated constraint. Modern Python 3.11+ provides built-in `tomllib`. |
| **Typer** | `^0.1.0` | `^0.15.0+` | Version `0.1.0` is ancient (circa 2020), missing rich formatting, modern sub-command routing, typing improvements, and modern Click integrations. |
| **getpass4** | `^0.0.14.1` | **Deprecated / Remove** | Obscure, unmaintained library. Python standard library `getpass` or Typer's `typer.prompt(hide_input=True)` should be used. |
| **pyyaml** | `^6.0.1` | `^6.0.2` or `ruamel.yaml` | Imported in `main.py` but never invoked. If comment preservation is desired, `ruamel.yaml` is superior. |
| **toml** | Not in `pyproject.toml` | `tomli` / `tomli_w` or `tomlkit` | Missing from dependencies despite being heavily imported in `main.py`! Furthermore, `toml` is unmaintained; `tomlkit` preserves comments and formatting. |
| **Build System** | Poetry 1.x lockfile | `uv` / standard PEP 621 | No lockfile for modern package managers like `uv`. |
| **Testing** | None | `pytest`, `pytest-cov` | Zero test coverage. No CI configuration. |
| **Linter / Formatter** | None | `ruff` | No code style or static analysis enforcement. |

---

## 5. Security & Safety Audit

1. **Risk of Data Loss**:
   * Running `deploy` deletes the template files.
   * Running `grind` deletes concrete config files without dry-run or confirmation.
   * Running `press` deletes the unencrypted values file without verifying that the ciphertext can be decrypted.
2. **Secret Exposure in Terminal & History**:
   * Interactive prompts lack cancel/escape safety.
   * No checks to prevent accidental commit of decrypted `templatte.toml` to Git (missing automatic `.gitignore` injection).
3. **Environment Security**:
   * No separation between multiple environments (e.g., Development, Staging, Production). Secrets for all environments are dumped into a single flat file.

---

## 6. Gap Analysis: 2024 Alpha vs. 2026 Agent-Ready Standard

| Capability | Current State (2024 Alpha) | Modernized Requirement (2026) |
| :--- | :--- | :--- |
| **Multi-Format Support** | TOML only (brittle) | Universal: TOML, YAML, JSON, INI, `.env` with comment preservation. |
| **Template Engine** | Broken string splitting on ` = ` | Standardized Jinja2-compatible delimiter engine (`{{ key }}`). |
| **Lifecycle Safety** | Destructive; deletes templates | Safe lifecycle: templates are permanent; `--dry-run` and backups on destructive actions. |
| **Cryptography** | Fragile `gpg` subprocess | Pure Python, zero-external-binary AES-256-GCM / Age encryption with Argon2id/PBKDF2. |
| **Environment Profiles** | Single monolithic file | Multi-profile support (`dev`, `staging`, `prod`) and workspace scoping. |
| **Agent / CI Readiness** | Interactive only, no exit codes, human text only | Non-interactive flags, environment variables, exit codes, JSON output mode (`--json`). |
| **Verification & Drift** | None | `check` / `diff` command to detect config drift between deployed files and templates. |
| **Developer Ergonomics** | Minimal text print | Rich Barista terminal UX with coffee roast levels, tables, and spinners. |

---

## 7. Conclusion & Next Steps

The original concept of Templatte is exceptional and fills a real void in developer workflows and AI agent automation. However, the current code cannot be patched incrementally; it requires a structured **Spec-Driven Modernization**.

The complete architectural and functional specifications, along with an explicit **Agent Implementation Harness**, have been authored and organized in the `docs/spec/` suite on branch `spec/agent-driven-modernization`.

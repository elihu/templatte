# Templatte 2.0: Functional Specification

**Document:** `docs/spec/01_FUNCTIONAL_SPEC.md`  
**Status:** Approved for Implementation  
**Target:** CLI Layer (`templatte.cli`) & Commands  

---

## 1. CLI Global Design & Options

The Templatte CLI is powered by modern `typer` with `rich` formatting. Every command inherits global flags:

```bash
templatte [GLOBAL_OPTIONS] COMMAND [COMMAND_OPTIONS] [ARGS]
```

### Global Options
| Option | Short | Type | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `--workspace` | `-w` | `Path` | `.` | Root directory of the target workspace. |
| `--config-file`| `-c` | `Path` | `templatte.toml` | Path to the values registry file. |
| `--profile` | `-p` | `str` | `default` | Target environment profile (e.g. `dev`, `prod`). |
| `--json` | | `bool` | `False` | Output results in structured JSON for agents & scripts. |
| `--verbose` | `-v` | `bool` | `False` | Enable debug logging. |
| `--no-color` | | `bool` | `False` | Disable ANSI color output (respects `NO_COLOR`). |

---

## 2. Command Specifications

### 2.1 `templatte genelatte`
**Purpose:** Discovers configuration files in the workspace, extracts values into `templatte.toml`, and creates corresponding `.latte` template files.

#### Syntax
```bash
templatte genelatte [OPTIONS]
```

#### Command Options
* `--format`, `-f` (`list[str]`, default: `["toml", "yaml", "json", "ini", "env"]`): Formats to discover.
* `--include`, `-i` (`list[str]`, optional): Glob patterns to explicitly include (e.g. `["config/**", "*.toml"]`).
* `--exclude`, `-e` (`list[str]`, optional): Additional glob patterns to exclude. Default excludes: `.git/**`, `.venv/**`, `__pycache__/**`, `node_modules/**`, `dist/**`, `templatte.toml*`.
* `--force`, `-y` (`bool`, default: `False`): Overwrite existing `.latte` files without prompting.
* `--dry-run` (`bool`, default: `False`): Scan and display what would be created without writing any files to disk.

#### Behavior Specification
1. Resolve workspace path relative to current working directory.
2. Load existing `templatte.toml` if present (to merge new discoveries without losing existing custom values).
3. Walk workspace directory, ignoring excluded patterns.
4. For each detected config file:
   a. Check if a corresponding `.latte` file already exists. If yes and `--force` is false, skip or prompt.
   b. Parse the file using the appropriate `FormatAdapter`.
   c. Extract leaf values into normalized dot-paths (`section.subset.key`).
   d. Generate the template content with placeholders (`{{ section.subset.key }}`) preserving comments and ordering.
   e. Record values in `templatte.toml` under `[files."<relative_path>".values]`.
5. Write the `.latte` files alongside each original file.
6. Write or update `templatte.toml`.
7. Output summary (files scanned, templates generated, keys extracted).

---

### 2.2 `templatte deploy`
**Purpose:** Reads values from `templatte.toml` and renders `.latte` files into runnable, concrete configuration files.

#### CRITICAL RULE (INVARIANT 1)
> **`deploy` MUST NEVER DELETE, RENAME, OR MUTATE `.latte` FILES.**  
> Template files are permanent project assets. Deleting `.latte` files is a critical regression.

#### Syntax
```bash
templatte deploy [OPTIONS]
```

#### Command Options
* `--dry-run` (`bool`, default: `False`): Simulate deployment and report modified files without writing.
* `--diff` (`bool`, default: `False`): Display unified diff of changes against existing concrete files.
* `--force`, `-y` (`bool`, default: `False`): Overwrite existing concrete files without confirmation.
* `--file`, `-f` (`Path`, optional): Target a specific `.latte` file instead of deploying all workspace templates.

#### Behavior Specification
1. Verify `templatte.toml` exists. If missing, fail with exit code `3`.
2. Discover all `*.latte` files recursively within the workspace (or the single file specified by `--file`).
3. For each `.latte` file:
   a. Compute the target concrete file path by stripping the `.latte` suffix (e.g. `app.toml.latte` -> `app.toml`).
   b. Look up values for the relative path in `templatte.toml` (and active `--profile`).
   c. If required placeholders in the template are missing from the values registry:
      - Accumulate missing key errors.
      - If missing keys exist, do not write files; report missing keys and exit with code `3`.
   d. Render the template using the format-aware template engine.
   e. If `--diff` is set, print unified diff.
   f. If not `--dry-run`, write rendered content to the target concrete path.
4. Keep all `.latte` files completely intact.
5. Exit with code `0` on success.

---

### 2.3 `templatte grind`
**Purpose:** Discards concrete configuration files whose `.latte` templates exist, preventing secret leakage before Git operations.

#### Syntax
```bash
templatte grind [OPTIONS]
```

#### Command Options
* `--force`, `-y` (`bool`, default: `False`): Delete files immediately without interactive confirmation.
* `--dry-run` (`bool`, default: `False`): List files that would be deleted without removing them.
* `--backup` (`bool`, default: `False`): Create a temporary `.bak` archive before deletion.

#### Behavior Specification
1. Find all `*.latte` files in the workspace.
2. For each `.latte` file, identify the corresponding concrete file.
3. Check if the concrete file exists.
4. If `--dry-run`: display list of matching concrete files and return 0.
5. If interactive and `--force` is false: ask user for confirmation:
   `"Grind will delete X concrete configuration files. Proceed? [y/N]"`.
6. If confirmed or `--force`:
   - Delete concrete files.
   - Leave all `.latte` files untouched.
   - Leave `templatte.toml` untouched.
7. Print summary of deleted files.

---

### 2.4 `templatte press`
**Purpose:** Encrypts `templatte.toml` using AES-256-GCM authenticated encryption into `templatte.toml.enc`.

#### Syntax
```bash
templatte press [OPTIONS]
```

#### Command Options
* `--output`, `-o` (`Path`, default: `<config-file>.enc`): Target encrypted output file.
* `--passphrase` (`str`, optional): Passphrase string (use with caution in shell history).
* `--passphrase-env` (`str`, default: `TEMPLATTE_PASSPHRASE`): Environment variable name to read passphrase from.
* `--keep-plain` (`bool`, default: `False`): Do not delete the unencrypted `templatte.toml` after successful encryption.
* `--force`, `-y` (`bool`, default: `False`): Overwrite existing output file without confirmation.

#### Behavior Specification
1. Ensure input file `templatte.toml` exists.
2. Acquire passphrase via priority order:
   1. `--passphrase` CLI argument.
   2. Value in environment variable specified by `--passphrase-env`.
   3. Interactive prompt (masked, with double-entry confirmation).
3. Validate passphrase (minimum 8 characters).
4. Generate 32-byte cryptographically secure random salt and 12-byte IV.
5. Derive 256-bit encryption key using PBKDF2-HMAC-SHA256 (600,000 iterations).
6. Encrypt plaintext using AES-256-GCM, obtaining ciphertext and 16-byte authentication tag.
7. Build cryptographic envelope JSON.
8. Validate envelope: immediately perform an in-memory decrypt check with the same key to verify integrity.
9. Write envelope to `templatte.toml.enc`.
10. Unless `--keep-plain` is true, safely remove `templatte.toml`.
11. Exit with code `0`.

---

### 2.5 `templatte pour`
**Purpose:** Decrypts `templatte.toml.enc` back into unencrypted `templatte.toml`.

#### Syntax
```bash
templatte pour [OPTIONS]
```

#### Command Options
* `--input`, `-i` (`Path`, default: `<config-file>.enc`): Encrypted input file.
* `--output`, `-o` (`Path`, default: `<config-file>`): Output plaintext path.
* `--passphrase` (`str`, optional): Passphrase string.
* `--passphrase-env` (`str`, default: `TEMPLATTE_PASSPHRASE`): Environment variable name to read passphrase from.
* `--keep-encrypted` (`bool`, default: `True`): Retain the `.enc` file after decryption (defaults to True for safety).
* `--force`, `-y` (`bool`, default: `False`): Overwrite existing output file without confirmation.

#### Behavior Specification
1. Ensure input encrypted envelope exists.
2. Parse JSON envelope and validate schema version.
3. Acquire passphrase (CLI -> Env -> Interactive prompt).
4. Re-derive key using salt, iterations, and algorithm specified in envelope.
5. Decrypt and authenticate ciphertext with AES-256-GCM.
   - If authentication tag fails: fail with exit code `4` (`"Invalid passphrase or corrupted file"`).
6. Write restored plaintext to `templatte.toml`.
7. Exit with code `0`.

---

### 2.6 `templatte check` (Alias: `templatte roast`)
**Purpose:** Validates template consistency, verifies values coverage, and checks for uncommitted concrete files or drift. Ideal for pre-commit hooks and CI pipelines.

#### Syntax
```bash
templatte check [OPTIONS]
```

#### Command Options
* `--strict` (`bool`, default: `False`): Treat warnings as errors (exit code 5).
* `--check-git` (`bool`, default: `True`): Verify that concrete files with templates are not tracked in Git.

#### Behavior Specification
1. Scan all `.latte` files.
2. Cross-reference every placeholder `{{ key }}` against `templatte.toml`. Report any unassigned placeholders.
3. If concrete files exist, compare their content against rendered templates. Report any configuration drift.
4. If `--check-git` is enabled and git is available, verify that concrete config files are ignored in `.gitignore`.
5. Return:
   - Exit code `0` if all checks pass.
   - Exit code `3` if missing template values are detected.
   - Exit code `5` if drift or git leakage is detected in `--strict` mode.

---

## 3. Exit Code Taxonomy

| Code | Label | Meaning |
| :---: | :--- | :--- |
| **0** | `SUCCESS` | Command completed successfully. |
| **1** | `ERROR_GENERAL` | Unexpected exception or runtime failure. |
| **2** | `ERROR_USAGE` | Invalid CLI arguments, missing required options. |
| **3** | `ERROR_VALIDATION` | Missing values in `templatte.toml`, missing template file, syntax error in config. |
| **4** | `ERROR_CRYPTO` | Invalid passphrase, corrupted envelope, HMAC mismatch. |
| **5** | `ERROR_DRIFT` | Drift detected between deployed config and template, or git leakage in `--strict` mode. |

---

## 4. Machine-Readable JSON Mode (`--json`)

When `--json` is supplied, stdout contains solely valid JSON, while informational/logging output is suppressed or redirected to stderr.

### Example: `templatte genelatte --json`
```json
{
  "status": "success",
  "command": "genelatte",
  "workspace": "/home/user/project",
  "scanned_files": 4,
  "generated_templates": [
    "config/app.toml.latte",
    "services/auth/settings.yaml.latte"
  ],
  "values_file": "templatte.toml",
  "total_keys_extracted": 28,
  "warnings": []
}
```

### Example: `templatte deploy --dry-run --json`
```json
{
  "status": "success",
  "command": "deploy",
  "dry_run": true,
  "target_files": [
    {
      "template": "config/app.toml.latte",
      "destination": "config/app.toml",
      "action": "would_create"
    }
  ],
  "missing_keys": []
}
```

### Example: Error Response
```json
{
  "status": "error",
  "exit_code": 3,
  "error_type": "ValidationError",
  "message": "Missing required template values in templatte.toml",
  "details": {
    "file": "config/app.toml.latte",
    "missing_keys": ["database.password", "database.replica_host"]
  }
}
```

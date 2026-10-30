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
| `--config-file`| `-c` | `Path` | `templatte.toml` | Path to the values registry file, resolved relative to `--workspace`. |
| `--profile` | `-p` | `str` | `default` | Target environment profile (e.g. `dev`, `prod`). |
| `--json` | | `bool` | `False` | Output results in structured JSON for agents & scripts. |
| `--verbose` | `-v` | `bool` | `False` | Enable debug logging. |
| `--no-color` | | `bool` | `False` | Disable ANSI color output (respects `NO_COLOR`). |

The values registry always lives at the root of the resolved `--workspace` directory, never at the process's current working directory — this keeps behavior identical whether Templatte is invoked from the workspace root or from a subdirectory within it. `--config-file` is a path relative to `--workspace` (an absolute path is honored as given).

---

## 2. Command Specifications

### 2.1 `templatte genelatte`
**Purpose:** Discovers configuration files in the workspace, extracts values into `templatte.toml`, and creates corresponding `.latte` template files.

#### Syntax
```bash
templatte genelatte [OPTIONS]
```

#### Discovery Model: Opt-In Whitelist
`genelatte` scans for candidate files under an opt-in model rather than a blanket recursive walk: by default it only considers files matching a curated whitelist of common configuration patterns, plus anything the user explicitly names via `--include`.

**Default whitelist patterns:**
`*.env`, `*.env.*`, `config/**`, `settings.*` (excluding `templatte.toml` itself).

**Hard denylist** — never templatized, even when matched by `--include`, unless the caller also passes `--force-include`:
`package.json`, `package-lock.json`, `yarn.lock`, `pnpm-lock.yaml`, `tsconfig*.json`, `composer.json`, `composer.lock`, `pyproject.toml`, `uv.lock`, `poetry.lock`, `Cargo.toml`, `Cargo.lock`, `*.lock`, `.github/**`, `docker-compose*.yml`, `*.latte`, in addition to the standing directory excludes (`.git/**`, `.venv/**`, `__pycache__/**`, `node_modules/**`, `dist/**`). These are files whose exact byte-for-byte content and lock-format guarantees matter to other tooling (package managers, CI) — templatizing them by accident is a correctness hazard the denylist forecloses by default.

#### Command Options
* `--format`, `-f` (`list[str]`, default: `["toml", "yaml", "json", "ini", "env"]`): Formats to discover.
* `--include`, `-i` (`list[str]`, optional): Glob patterns to explicitly include on top of the default whitelist (e.g. `["config/**", "*.toml"]`).
* `--exclude`, `-e` (`list[str]`, optional): Additional glob patterns to exclude. Default excludes: `.git/**`, `.venv/**`, `__pycache__/**`, `node_modules/**`, `dist/**`, `templatte.toml*`, plus the hard denylist above.
* `--force-include` (`bool`, default: `False`): Allow `--include` patterns to match files on the hard denylist.
* `--force`, `-y` (`bool`, default: `False`): Overwrite existing `.latte` files without prompting.
* `--dry-run` (`bool`, default: `False`): Scan and display what would be created without writing any files to disk.
* `--no-gitignore-update` (`bool`, default: `False`): Do not automatically append `templatte.toml` and its templatized concrete files to workspace `.gitignore`.

#### Behavior Specification
1. Resolve workspace path relative to current working directory.
2. Load existing `templatte.toml` if present (to merge new discoveries without losing existing custom values).
3. Walk workspace directory, considering only files matching the default whitelist or `--include`, minus the hard denylist (unless `--force-include`) and the standing directory excludes.
4. For each detected config file:
   a. Check if the file already contains `{{ }}` or `${{ }}` delimiters belonging to another template engine (see `00_MASTER_SPEC.md` §6.2). If so, skip it, report it as requiring manual review, and continue scanning the rest of the workspace.
   b. Check if a corresponding `.latte` file already exists. If yes and `--force` is false, skip or prompt.
   c. Parse the file using the appropriate `FormatAdapter`.
   d. Extract leaf values into normalized dot-paths (`section.subset.key`).
   e. Generate the template content with placeholders (`"{{ section.subset.key }}"`) preserving comments and ordering.
   f. Record values in `templatte.toml` under `[files."<relative_path>".values]`, flagging any key that looks credential-shaped (matching `password`, `secret`, `token`, `key`) in the sibling `[files."<relative_path>".secrets]` table (see `00_MASTER_SPEC.md` §5, "Secret Marking").
5. Write the `.latte` files alongside each original file.
6. Write or update `templatte.toml`.
7. Unless `--no-gitignore-update` is true: after each `.latte` file is generated, add the templatized concrete file's path, together with `templatte.toml`, `templatte.*.toml`, and the timestamped `.bak` backup pattern of each of these files (backups hold plaintext secrets), to the workspace `.gitignore`. `templatte.toml.enc` is intentionally **not** ignored: it is the encrypted artifact meant to be committed (see `04_GIT_AND_WORKFLOW_SPEC.md` §3.1–§3.2). Templatte creates the `# >>> templatte managed >>>` / `# <<< templatte managed <<<` marker block on first run if absent, and rewrites only the content between the markers on subsequent runs — making the update idempotent and safe to re-run without disturbing the rest of the file.
8. Output summary (files scanned, templates generated, keys extracted, files flagged for manual review).

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
* `--backup` (`bool`, default: `False`): When used with `--force`, copy each concrete file being overwritten to a timestamped `.bak` sibling before writing the new content.
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
* `--force-tracked` (`bool`, default: `False`): Allow deletion of concrete files that are tracked by Git. Without it, `grind` refuses to delete a tracked file whose working-tree content differs from `HEAD` (uncommitted changes), to avoid silently discarding unsaved work.
* `--dry-run` (`bool`, default: `False`): List files that would be deleted without removing them.
* `--backup` (`bool`, default: `False`): Create a temporary `.bak` archive before deletion.

#### Behavior Specification
1. Find all `*.latte` files in the workspace.
2. For each `.latte` file, identify the corresponding concrete file.
3. Check if the concrete file exists.
4. If the concrete file is tracked by Git and its working-tree content differs from `HEAD` (i.e. it has uncommitted changes), skip it and report it as requiring `--force-tracked`, unless `--force-tracked` is set.
5. If `--dry-run`: display list of matching concrete files and return 0.
6. If interactive and `--force` is false: ask user for confirmation:
   `"Grind will delete X concrete configuration files. Proceed? [y/N]"`.
7. If confirmed or `--force`:
   - If `--backup` is set, copy each concrete file to a `.bak` sibling before deleting it.
   - Delete concrete files (respecting the tracked-file guard above).
   - Leave all `.latte` files untouched.
   - Leave `templatte.toml` untouched.
8. Print summary of deleted files, backed-up files, and files skipped due to uncommitted tracked changes.

---

### 2.4 `templatte press`
**Purpose:** Encrypts `templatte.toml` using AES-256-GCM authenticated encryption into `templatte.toml.enc`.

#### Syntax
```bash
templatte press [OPTIONS]
```

#### Command Options
* `--output`, `-o` (`Path`, default: `<config-file>.enc`): Target encrypted output file.
* `--passphrase` (`str`, optional): Passphrase string. Discouraged for CI/CD use — argv values are visible to other processes via `ps` and are commonly captured in shell history and CI job logs. Prefer `--passphrase-file` or stdin in automated environments.
* `--passphrase-file` (`Path`, optional): Path to a file containing the passphrase (its content, trimmed of a trailing newline, is used verbatim). The file is never modified.
* `--passphrase-env` (`str`, default: `TEMPLATTE_PASSPHRASE`): Environment variable name to read passphrase from.
* `--keep-plain` (`bool`, default: `False`): Do not delete the unencrypted `templatte.toml` after successful encryption.
* `--force`, `-y` (`bool`, default: `False`): Overwrite existing output file without confirmation.

#### Behavior Specification
1. Ensure input file `templatte.toml` exists.
2. Acquire passphrase via priority order:
   1. `--passphrase` CLI argument.
   2. `--passphrase-file` contents.
   3. Value in environment variable specified by `--passphrase-env`.
   4. Passphrase piped via stdin, when stdin is not a TTY.
   5. Interactive prompt (masked, with double-entry confirmation).
3. Validate passphrase (minimum 14 characters).
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
* `--backup` (`bool`, default: `False`): When used with `--force`, copy the existing output file to a timestamped `.bak` sibling before overwriting it.

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
* `--strict` (`bool`, default: `False`): Additionally treat non-drift warnings (e.g. git leakage, unassigned placeholders reported as warnings) as errors.
* `--check-git` (`bool`, default: `True`): Verify that concrete files with templates are not tracked in Git.

#### Behavior Specification
1. Scan all `.latte` files.
2. Cross-reference every placeholder `{{ key }}` against `templatte.toml`. Report any unassigned placeholders.
3. If concrete files exist, compare their content against rendered templates. Report any configuration drift.
4. If `--check-git` is enabled and git is available, verify that concrete config files are ignored in `.gitignore`.
5. Return:
   - Exit code `0` if all checks pass.
   - Exit code `3` if missing template values are detected.
   - Exit code `5` if configuration drift or git leakage is detected — unconditionally, whether or not `--strict` is set, since both are always actionable defects rather than mere style warnings. Without `--strict`, git leakage is reported as a warning (still at exit code `5`); with `--strict`, it is reported as an error, and other non-drift conditions (e.g. unassigned placeholders) that would otherwise only warn are also escalated into the error category.

---

### 2.7 `templatte migrate`
**Purpose:** Upgrades a values registry written by an earlier Templatte release to the current schema, so that older workspaces can be brought forward without hand-editing `templatte.toml`.

#### Syntax
```bash
templatte migrate [OPTIONS]
```

#### Command Options
* `--dry-run` (`bool`, default: `False`): Report the migration that would be performed without writing changes.
* `--force`, `-y` (`bool`, default: `False`): Overwrite the registry in place without a confirmation prompt.
* `--backup` (`bool`, default: `False`): Copy the pre-migration registry to a `.bak` sibling before writing the migrated file.

#### Behavior Specification
1. Load `templatte.toml` and inspect it for a top-level `version` field.
2. A registry is considered **legacy** when `version` is absent — this is the signature of the pre-2.0 flat schema, which uses unnormalized concatenated keys (e.g. `"./path_key"`) and unquoted placeholders in `.latte` files.
3. If the registry is legacy, migrate it in memory:
   a. Split each flat `"<file_path>_<key>"` entry into its owning `[files."<relative_path>".values]` table, normalizing the path to a workspace-relative POSIX path.
   b. Rewrite each corresponding `.latte` file's unquoted `{{ key }}` placeholders as quoted `"{{ key }}"` tokens.
   c. Set `version = 1` and `default_profile = "default"` on the migrated registry.
4. Write the migrated registry and templates atomically (respecting `--dry-run` and `--backup`).
5. Every other command (`deploy`, `grind`, `press`, `pour`, `check`) that detects a legacy registry (missing `version`) refuses to operate on it and exits with code `3`, printing an actionable message directing the user to run `templatte migrate` first, instead of surfacing a generic parse error.
6. Exit with code `0` on success, or `0` with a "nothing to migrate" message if the registry is already current.

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

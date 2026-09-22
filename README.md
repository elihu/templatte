# **Templatte** ☕️
### *Crafting Configurations Like a Barista*

<p align="center">
  <img src="static/templatte.png" alt="Templatte Logo" width="280" height="auto">
</p>

<p align="center">
  <b>Automated, parameter-driven configuration lifecycle management and secret encryption with a barista touch.</b>
</p>

<p align="center">
  <a href="docs/spec/00_MASTER_SPEC.md"><img src="https://img.shields.io/badge/Spec-2.0%20Modernized-brown?style=flat-square" alt="Spec 2.0"></a>
  <a href="docs/spec/03_AGENT_HARNESS_AND_TASKS.md"><img src="https://img.shields.io/badge/AI%20Harness-Spec--Driven-orange?style=flat-square" alt="Agent Harness"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-Apache--2.0-blue?style=flat-square" alt="License"></a>
  <img src="https://img.shields.io/badge/Python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.13%20%7C%203.14-green?style=flat-square" alt="Python">
</p>

---

## ☕️ What is Templatte?

Modern software projects and AI agents deal with dozens of configuration files (`config.toml`, `settings.yaml`, `.env`, `docker-compose.yml`, `db.json`). Managing secrets, avoiding accidental commits, and manually creating `.example` templates is error-prone, tedious, and fragile.

**Templatte** turns your messy configuration files into clean, parameter-driven `.latte` templates while centralizing values in a secure, encryptable values registry (`templatte.toml`).

* 🎯 **Universal Format Support:** Native support for TOML, YAML, JSON, INI, and `.env`.
* 🛡 **Zero-Leakage Security:** Cross-platform AES-256-GCM encryption without requiring external GPG binaries.
* 🤖 **AI Agent Ready:** Built with a **Spec-Driven Development (SDD) Harness**, predictable exit codes, non-interactive flags, and structured `--json` output.
* ☕️ **Pure Barista Delight:** Clear coffee-themed mental model for the full config lifecycle.

---

## 📜 The Barista Mental Model

Every step in your configuration workflow maps to brewing coffee:

| Barista Concept | Templatte Command | What it Does |
| :--- | :--- | :--- |
| **Roastery** | `templatte genelatte` | Scans workspace configs, extracts values to `templatte.toml`, and creates `.latte` templates. |
| **Serve / Cup** | `templatte deploy` | Injects values from `templatte.toml` into `.latte` templates to generate runnable configs. **(Templates are permanently preserved!)** |
| **Coffee Grinder** | `templatte grind` | Safely removes uncommitted concrete config files before committing to Git. |
| **French Press** | `templatte press` | Authenticated encryption (AES-256-GCM) of `templatte.toml` into a portable `.enc` envelope. |
| **Pour-Over** | `templatte pour` | Decrypts your `.enc` values registry back into plaintext when preparing an environment. |
| **Roast Inspection** | `templatte check` | Lints templates, detects configuration drift, and ensures no secrets leak into Git. |

---

## 🔄 Configuration Lifecycle

```text
[ Concrete Configs ] ──── genelatte ────► [ *.latte Templates ] (Committed to Git)
(config.toml, etc.)                             │
        │                                       │
        ▼ (extracts values)                     ▼ deploy (hydrates)
 [ templatte.toml ]                       [ Active Concrete Configs ]
        │
   press│pour (AES-256-GCM)
        ▼
 [ templatte.toml.enc ] (Safe to share / commit)
```

---

## 🚀 Quick Start

### 1. Installation
```bash
pip install templatte
# Or using uv (recommended):
uv tool install templatte
```

### 2. Extract & Template Your Project
Turn existing config files into `.latte` templates and extract values into `templatte.toml`:
```bash
templatte genelatte
```

### 3. Grind Away Raw Configs (Before Git Commit)
Discard the concrete configuration files containing sensitive local credentials:
```bash
templatte grind --force
```

### 4. Lock Your Blend (Encrypt Values)
Encrypt your centralized values with a passphrase:
```bash
templatte press --passphrase-env MY_PASSPHRASE
```

### 5. Hydrate on Deployment / Development
When pulling the repository or deploying to a server:
```bash
templatte pour --passphrase-env MY_PASSPHRASE
templatte deploy
```
*Your concrete configurations are generated instantly, while your `.latte` templates remain intact.*

---

## 🤖 Spec-Driven Development for AI Agents

Templatte 2.0 is designed from the ground up for agentic coding and automation:
* **Deterministic Output:** Use `--json` on any command for structured machine parsing.
* **Non-Interactive First:** Passphrases can be fed via `--passphrase-env` or `--passphrase` flags.
* **Predictable Exit Codes:**
  * `0`: Success
  * `2`: CLI Usage Error
  * `3`: Missing template values
  * `4`: Cryptography / passphrase error
  * `5`: Drift detected in `--strict` mode

Complete agent specifications, verification harness, and atomic implementation prompts are available in:
* 📑 [Master Specification](docs/spec/00_MASTER_SPEC.md)
* ⚙️ [Functional & CLI Specification](docs/spec/01_FUNCTIONAL_SPEC.md)
* 🏛 [Architecture & Adapters Specification](docs/spec/02_ARCHITECTURE_AND_EXTENSIBILITY.md)
* 🤖 [AI Agent Implementation Harness](docs/spec/03_AGENT_HARNESS_AND_TASKS.md)
* 🔍 [Alpha Audit Report & Technical Debt](docs/audit/AUDIT_REPORT.md)

---

## 🛡 Security Philosophy

* **Native Authenticated Cryptography:** Uses AES-256-GCM with PBKDF2-HMAC-SHA256 (600,000 iterations). Protects against ciphertext tampering.
* **Zero System Dependencies:** Pure Python implementation eliminates system-level `gpg` subprocess vulnerabilities and platform incompatibilities.
* **Atomic File Writes:** Deploys and updates write to temporary files before atomic file swapping, preventing corrupt configs during unexpected interrupts.
* **Strict Non-Destructive Invariants:** Templates are never deleted during hydration.

---

## 📃 License

Templatte is licensed under the [Apache-2.0 License](LICENSE).

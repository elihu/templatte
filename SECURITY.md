# Security Policy

Templatte's core value is a cryptographic engine that protects values which are,
by design, committed to a public repository. A flaw in that engine is not an
ordinary bug: reporting it in a public issue would disclose the exploit to every
fork and clone at once.

## Reporting a vulnerability

Use **GitHub private vulnerability reporting (Security Advisories)**. This is the
only supported channel:

<https://github.com/elihu/templatte/security/advisories/new>

Do not open a public issue, pull request or discussion for a suspected
vulnerability, and do not include real secrets, real `templatte.toml` files or
real `.enc` envelopes in your report; a minimal reproduction with dummy values is
enough.

## Scope

In scope (report privately):

- **Envelope forgery:** crafting or modifying a `templatte.toml.enc` envelope so
  that it is accepted as authentic, or any bypass of the authentication tag.
- **KDF brute-force feasibility below the documented cost:** a way to recover a
  passphrase more cheaply than the documented PBKDF2-HMAC-SHA256 cost allows.
- **Plaintext leakage through `grind`, `press` or `pour`,** including `.bak`
  backups that expose plaintext values.
- **`.gitignore` management failing to cover a templatized file,** so that a
  concrete file or the plaintext registry could be committed by `git add .`.

Anything else (crashes, formatting differences, wrong exit codes, documentation
errors) is an ordinary bug: please use the public
[bug report form](https://github.com/elihu/templatte/issues/new/choose).

## Response commitment

- We acknowledge every report within **7 days**.
- We practice **coordinated disclosure**: a fix is released and tagged before the
  advisory is made public, giving downstream users a chance to upgrade first.

## Already exposed a secret?

If a secret or passphrase was committed or exposed, rotate it first. Removing it
from the repository history does not un-expose it; see section 6 of
[`docs/spec/04_GIT_AND_WORKFLOW_SPEC.md`](docs/spec/04_GIT_AND_WORKFLOW_SPEC.md)
("Secret Handling in Git History") for rotation and history rewriting guidance.

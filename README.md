# Templatte ☕️

*Crafting configurations like a barista.*

<p align="center">
  <img src="static/templatte.png" alt="Templatte logo" width="280" height="auto">
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache--2.0-blue?style=flat-square" alt="License: Apache-2.0"></a>
  <img src="https://img.shields.io/badge/python-3.10%2B-green?style=flat-square" alt="Python 3.10+">
</p>

Every project ends up with a `config.toml`, a `.env`, a `settings.yaml` and a
`db.json`, half of them holding passwords. Then someone has to keep the
`.env.example` in sync by hand, and sooner or later someone commits the real
`.env`. We have all been that someone.

Templatte splits each config file in two:

- a **`.latte` template**: the file's shape, comments and all, with the values
  replaced by placeholders. This one goes into Git.
- the **values**, collected in a single `templatte.toml` that never goes into
  Git as plain text. You can encrypt it into `templatte.toml.enc` and commit
  that instead.

When you need the real files back, Templatte pours the values into the
templates. The templates stay where they are, ready for the next cup.

## Install

```bash
uv tool install templatte
# or
pip install templatte
```

Python 3.10 or newer. Works on Linux, macOS and Windows, and needs no GPG or
other system binaries.

## The menu

| Command | Barista version | What it actually does |
| :--- | :--- | :--- |
| `genelatte` | Roasting | Finds your config files, writes a `.latte` template next to each one and collects the values in `templatte.toml`. Also keeps your `.gitignore` up to date. |
| `deploy` | Serving | Renders every `.latte` into its real config file. Never touches the templates. |
| `grind` | Cleaning the grinder | Deletes the real config files that have a template, so they can't sneak into a commit. |
| `press` | French press | Encrypts `templatte.toml` into `templatte.toml.enc` (AES-256-GCM). |
| `pour` | Pour-over | Decrypts `templatte.toml.enc` back into `templatte.toml`. |
| `check` | Taste test | Looks for missing values, drift between templates and real files, and config files Git is tracking when it shouldn't. |
| `migrate` | Changing beans | Upgrades a `templatte.toml` from Templatte 0.x to the current format. |

`templatte <command> --help` lists every flag.

## A quick brew

Say you have this `config/app.toml`:

```toml
# where the app listens
[server]
host = "127.0.0.1"
port = 8080

[db]
user = "barista"
password = "hunter2"  # do not tell anyone
```

Run:

```bash
templatte genelatte
```

You get `config/app.toml.latte`, which is safe to commit:

```toml
# where the app listens
[server]
host = "{{ server.host }}"
port = "{{ server.port }}"

[db]
user = "{{ db.user }}"
password = "{{ db.password }}"  # do not tell anyone
```

And the values go to `templatte.toml`, with anything that looks like a
credential flagged as a secret:

```toml
version = 1
default_profile = "default"

[files."config/app.toml"]
format = "toml"

[files."config/app.toml".values]
"server.host" = "127.0.0.1"
"server.port" = 8080
"db.user" = "barista"
"db.password" = "hunter2"

[files."config/app.toml".secrets]
"db.password" = true
```

Don't worry about the quoted `"{{ server.port }}"`: on deploy it goes back to
being the number `8080`. Types come from the values, not from the template.

`genelatte` also adds a managed block to `.gitignore` covering `templatte.toml`,
every real config file it templated and their `.bak` backups. Your own
`.gitignore` lines are left alone.

### Seal it, share it

```bash
export TEMPLATTE_PASSPHRASE="a long passphrase, 14 characters minimum"
templatte press     # templatte.toml -> templatte.toml.enc, plaintext removed
templatte grind     # remove the real config files before committing
git add .gitignore templatte.toml.enc '*.latte'
git commit -m "chore: templatize configuration"
```

### Brew it somewhere else

On a fresh clone, a CI runner or a server:

```bash
export TEMPLATTE_PASSPHRASE="..."
templatte pour      # templatte.toml.enc -> templatte.toml
templatte deploy    # *.latte -> real config files
```

The passphrase can also come from `--passphrase-file`, or be typed at a prompt.
`--passphrase` exists too, but it ends up in your shell history and in `ps`, so
it's decaf at best.

## What it preserves

Templatte edits files, it doesn't regenerate them. A deploy keeps comments, key
order, TOML inline tables, YAML anchors and multiline strings where they were.
`.env` and INI files come back byte for byte. For every format, running
`genelatte` and `deploy` again on the result produces exactly the same bytes, so
redeploying won't leave noise in your `git diff`.

Supported formats: TOML, YAML, JSON, INI and `.env`.

## Profiles

One set of templates, several environments. Override only what changes:

```toml
[profiles.prod."config/app.toml".values]
"server.host" = "0.0.0.0"
"server.port" = 443
```

```bash
templatte --profile prod deploy
```

## Keeping secrets out of Git

`templatte check` fails if a real config file or `templatte.toml` is tracked by
Git or not ignored. To run it on every commit, add it to your
`.pre-commit-config.yaml`:

```yaml
repos:
  - repo: https://github.com/elihu/templatte
    rev: v1.0.0
    hooks:
      - id: templatte-check
```

## Scripting and agents

Every command accepts `--json`: stdout then carries exactly one JSON document and
everything else goes to stderr. Nothing prompts when you pass `--force` and a
non-interactive passphrase source, so it behaves in CI and in AI coding agents.

| Exit code | Meaning |
| :---: | :--- |
| `0` | All good |
| `1` | Something else went wrong |
| `2` | Bad usage |
| `3` | Validation error (missing values, broken template, bad config) |
| `4` | Crypto error (wrong passphrase, tampered file) |
| `5` | Drift or a config file leaking into Git |
| `130` | Interrupted |

## Under the hood

- Encryption is AES-256-GCM with a key derived by PBKDF2-HMAC-SHA256 (600,000
  iterations). Tampering with any byte of the envelope, header included, makes
  decryption fail.
- Every write goes to a temporary file first and is then renamed into place, so
  a `Ctrl+C` never leaves you with half a config.
- `deploy` never deletes or rewrites a `.latte` file. The templates are the
  recipe, and the recipe stays on the counter.

The full design lives in [`docs/spec/`](docs/spec/00_MASTER_SPEC.md).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Found a security problem? Please read
[SECURITY.md](SECURITY.md) and don't open a public issue.

## License

[Apache-2.0](LICENSE). Coffee stains not included.

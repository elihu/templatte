"""``press`` / ``pour`` orchestration around the AES-256-GCM engine (FUNCTIONAL_SPEC §2.4-§2.5).

Passphrase acquisition is injectable (environment, stdin, prompt callable) so the
service never touches the terminal itself.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from templatte.adapters.crypto import AesGcmCryptoEngine, CryptoEngine, from_json, to_json
from templatte.core.exceptions import CryptoError, UsageError, WeakPassphraseError
from templatte.core.services._common import (
    backup_file,
    load_required_registry,
    resolve_config,
    resolve_workspace,
    workspace_rel,
)
from templatte.utils.fs import atomic_write_bytes, atomic_write_text

MIN_PASSPHRASE_LENGTH = 14
DEFAULT_ENV_VAR = "TEMPLATTE_PASSPHRASE"


def _strip_one_newline(text: str) -> str:
    if text.endswith("\r\n"):
        return text[:-2]
    if text.endswith("\n"):
        return text[:-1]
    return text


def acquire_passphrase(
    *,
    passphrase: str | None = None,
    passphrase_file: Path | str | None = None,
    env_var: str = DEFAULT_ENV_VAR,
    environ: Mapping[str, str] | None = None,
    stdin: TextIO | None = None,
    stdin_is_tty: bool | None = None,
    prompt: Callable[[str], str] | None = None,
    confirm: bool = False,
) -> str:
    """Resolve a passphrase: argument, file, env var, piped stdin, then interactive prompt.

    Raises:
        UsageError: no source available, an unreadable file, an empty result or a
            confirmation mismatch.
    """
    if passphrase is not None:
        return _non_empty(passphrase)

    if passphrase_file is not None:
        try:
            raw = Path(passphrase_file).read_bytes().decode("utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise UsageError(f"Cannot read passphrase file '{passphrase_file}': {exc}") from None
        return _non_empty(_strip_one_newline(raw))

    env = os.environ if environ is None else environ
    from_env = env.get(env_var)
    if from_env:
        return from_env

    stream = sys.stdin if stdin is None else stdin
    tty = (stream.isatty() if stdin_is_tty is None else stdin_is_tty) if stream else True
    if not tty:
        line = _strip_one_newline(stream.readline())
        if line:
            return line

    if prompt is not None:
        first = prompt("Passphrase: ")
        if confirm and prompt("Confirm passphrase: ") != first:
            raise UsageError("Passphrases do not match")
        return _non_empty(first)

    raise UsageError(
        "No passphrase available: use --passphrase, --passphrase-file, "
        f"the {env_var} environment variable, stdin or an interactive prompt"
    )


def _non_empty(value: str) -> str:
    if not value:
        raise UsageError("Passphrase must not be empty")
    return value


def validate_passphrase_strength(passphrase: str) -> None:
    """Enforce the minimum length used when creating new envelopes."""
    if len(passphrase) < MIN_PASSPHRASE_LENGTH:
        raise WeakPassphraseError(MIN_PASSPHRASE_LENGTH)


@dataclass(frozen=True)
class PressResult:
    """Outcome of press (workspace-relative POSIX paths)."""

    output: str
    plain_removed: bool

    @property
    def exit_code(self) -> int:
        return 0


@dataclass(frozen=True)
class PourResult:
    """Outcome of pour (workspace-relative POSIX paths)."""

    output: str
    backup: str | None
    encrypted_removed: bool

    @property
    def exit_code(self) -> int:
        return 0


def _resolve(root: Path, p: Path | str) -> Path:
    path = Path(p)
    return path if path.is_absolute() else root / path


def press(
    workspace: Path | str,
    config_file: Path | str = Path("templatte.toml"),
    output: Path | str | None = None,
    *,
    passphrase: str | None = None,
    passphrase_file: Path | str | None = None,
    env_var: str = DEFAULT_ENV_VAR,
    environ: Mapping[str, str] | None = None,
    stdin: TextIO | None = None,
    stdin_is_tty: bool | None = None,
    prompt: Callable[[str], str] | None = None,
    keep_plain: bool = False,
    force: bool = False,
    engine: CryptoEngine | None = None,
) -> PressResult:
    """Encrypt the registry into an envelope file, verifying it before writing."""
    root = resolve_workspace(workspace)
    config_path = resolve_config(root, config_file)
    load_required_registry(root, config_path)  # exists and not legacy
    out_path = (
        _resolve(root, output)
        if output is not None
        else config_path.with_name(config_path.name + ".enc")
    )
    out_rel = workspace_rel(root, out_path)
    if out_path.exists() and not force:
        raise UsageError(
            f"Output file already exists: '{out_rel}'. Use --force to overwrite.",
            details={"file": out_rel},
        )

    secret = acquire_passphrase(
        passphrase=passphrase,
        passphrase_file=passphrase_file,
        env_var=env_var,
        environ=environ,
        stdin=stdin,
        stdin_is_tty=stdin_is_tty,
        prompt=prompt,
        confirm=True,
    )
    validate_passphrase_strength(secret)

    crypto = engine or AesGcmCryptoEngine()
    plaintext = config_path.read_bytes()
    envelope = crypto.encrypt(plaintext, secret)
    if crypto.decrypt(envelope, secret) != plaintext:  # in-memory verification
        raise CryptoError("Encryption verification failed; nothing was written")

    atomic_write_text(out_path, to_json(envelope))

    removed = False
    if not keep_plain and out_path.resolve() != config_path.resolve():
        config_path.unlink()
        removed = True
    return PressResult(output=out_rel, plain_removed=removed)


def pour(
    workspace: Path | str,
    config_file: Path | str = Path("templatte.toml"),
    input: Path | str | None = None,
    output: Path | str | None = None,
    *,
    passphrase: str | None = None,
    passphrase_file: Path | str | None = None,
    env_var: str = DEFAULT_ENV_VAR,
    environ: Mapping[str, str] | None = None,
    stdin: TextIO | None = None,
    stdin_is_tty: bool | None = None,
    prompt: Callable[[str], str] | None = None,
    keep_encrypted: bool = True,
    force: bool = False,
    backup: bool = False,
    engine: CryptoEngine | None = None,
) -> PourResult:
    """Decrypt an envelope back into the registry file.

    Any non-empty passphrase is accepted so that envelopes created under older,
    laxer rules remain decryptable.
    """
    root = resolve_workspace(workspace)
    config_path = resolve_config(root, config_file)
    in_path = (
        _resolve(root, input)
        if input is not None
        else config_path.with_name(config_path.name + ".enc")
    )
    out_path = _resolve(root, output) if output is not None else config_path
    in_rel = workspace_rel(root, in_path)
    out_rel = workspace_rel(root, out_path)

    if not in_path.is_file():
        raise UsageError(f"Encrypted input not found: '{in_rel}'", details={"file": in_rel})
    if out_path.exists() and not force:
        raise UsageError(
            f"Output file already exists: '{out_rel}'. Use --force to overwrite.",
            details={"file": out_rel},
        )

    envelope = from_json(in_path.read_bytes())  # CorruptedEnvelopeError propagates
    secret = acquire_passphrase(
        passphrase=passphrase,
        passphrase_file=passphrase_file,
        env_var=env_var,
        environ=environ,
        stdin=stdin,
        stdin_is_tty=stdin_is_tty,
        prompt=prompt,
        confirm=False,
    )
    plaintext = (engine or AesGcmCryptoEngine()).decrypt(envelope, secret)

    backup_rel: str | None = None
    if out_path.exists() and force and backup:
        backup_rel = workspace_rel(root, backup_file(out_path))
    atomic_write_bytes(out_path, plaintext)

    removed = False
    if not keep_encrypted and in_path.resolve() != out_path.resolve():
        in_path.unlink()
        removed = True
    return PourResult(output=out_rel, backup=backup_rel, encrypted_removed=removed)

"""Unit tests for the press/pour service and passphrase acquisition."""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from templatte.adapters.crypto import AesGcmCryptoEngine, CryptoEnvelope
from templatte.core.exceptions import (
    CorruptedEnvelopeError,
    CryptoError,
    InvalidPassphraseError,
    LegacyRegistryError,
    UsageError,
    ValidationError,
    WeakPassphraseError,
)
from templatte.core.services.crypto import acquire_passphrase, pour, press

PASS = "correct horse battery staple"
REGISTRY = 'version = 1\n\n[files."a.toml"]\nformat = "toml"\n[files."a.toml".values]\nx = 1\n'


@pytest.fixture
def engine() -> AesGcmCryptoEngine:
    return AesGcmCryptoEngine(iterations=100_000)


@pytest.fixture
def reg(tmp_path: Path) -> Path:
    (tmp_path / "templatte.toml").write_text(REGISTRY, encoding="utf-8", newline="\n")
    return tmp_path


class FakeStdin(io.StringIO):
    def __init__(self, text: str, tty: bool) -> None:
        super().__init__(text)
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


# --- acquire_passphrase -------------------------------------------------------------


def test_priority_arg_wins(tmp_path: Path) -> None:
    f = tmp_path / "pw"
    f.write_text("file-pass\n", encoding="utf-8", newline="\n")
    got = acquire_passphrase(
        passphrase="arg-pass",
        passphrase_file=f,
        environ={"TEMPLATTE_PASSPHRASE": "env-pass"},
        stdin=FakeStdin("stdin-pass\n", False),
        prompt=lambda _: "prompt-pass",
    )
    assert got == "arg-pass"


def test_priority_file_over_env_stdin_prompt(tmp_path: Path) -> None:
    f = tmp_path / "pw"
    f.write_text("file-pass\n", encoding="utf-8", newline="\n")
    got = acquire_passphrase(
        passphrase_file=f,
        environ={"TEMPLATTE_PASSPHRASE": "env-pass"},
        stdin=FakeStdin("stdin-pass\n", False),
        prompt=lambda _: "prompt-pass",
    )
    assert got == "file-pass"


def test_priority_env_over_stdin_prompt() -> None:
    got = acquire_passphrase(
        environ={"MY_PW": "env-pass"},
        env_var="MY_PW",
        stdin=FakeStdin("stdin-pass\n", False),
        prompt=lambda _: "prompt-pass",
    )
    assert got == "env-pass"


def test_priority_stdin_over_prompt() -> None:
    got = acquire_passphrase(
        environ={}, stdin=FakeStdin("stdin-pass\r\nmore\n", False), prompt=lambda _: "prompt"
    )
    assert got == "stdin-pass"


def test_tty_stdin_not_read_falls_to_prompt() -> None:
    stdin = FakeStdin("stdin-pass\n", True)
    got = acquire_passphrase(environ={}, stdin=stdin, prompt=lambda _: "prompt-pass")
    assert got == "prompt-pass"
    assert stdin.tell() == 0


def test_stdin_is_tty_override() -> None:
    got = acquire_passphrase(
        environ={}, stdin=FakeStdin("s\n", True), stdin_is_tty=False, prompt=None
    )
    assert got == "s"


def test_empty_piped_stdin_falls_through() -> None:
    got = acquire_passphrase(environ={}, stdin=FakeStdin("", False), prompt=lambda _: "p")
    assert got == "p"


def test_file_newline_handling_and_untouched(tmp_path: Path) -> None:
    f = tmp_path / "pw"
    for raw, expected in [
        (b"abc\n", "abc"),
        (b"abc\r\n", "abc"),
        (b"abc\n\n", "abc\n"),
        (b"abc", "abc"),
        (b" a b \n", " a b "),
    ]:
        f.write_bytes(raw)
        assert acquire_passphrase(passphrase_file=f, environ={}) == expected
        assert f.read_bytes() == raw


def test_missing_file_is_usage_error(tmp_path: Path) -> None:
    with pytest.raises(UsageError):
        acquire_passphrase(passphrase_file=tmp_path / "nope", environ={})


def test_confirm_prompts_twice_and_mismatch() -> None:
    answers = iter(["same-pass", "same-pass"])
    assert (
        acquire_passphrase(
            environ={}, stdin=FakeStdin("", True), prompt=lambda _: next(answers), confirm=True
        )
        == "same-pass"
    )
    answers = iter(["one", "two"])
    with pytest.raises(UsageError):
        acquire_passphrase(
            environ={}, stdin=FakeStdin("", True), prompt=lambda _: next(answers), confirm=True
        )


def test_no_source_raises() -> None:
    with pytest.raises(UsageError):
        acquire_passphrase(environ={}, stdin=FakeStdin("", True))


def test_empty_values_rejected() -> None:
    with pytest.raises(UsageError):
        acquire_passphrase(passphrase="", environ={})


# --- press / pour -------------------------------------------------------------------


def test_round_trip_byte_identical(reg: Path, engine: AesGcmCryptoEngine) -> None:
    original = (reg / "templatte.toml").read_bytes()
    r = press(reg, passphrase=PASS, engine=engine)
    assert r.output == "templatte.toml.enc" and r.plain_removed and r.exit_code == 0
    assert not (reg / "templatte.toml").exists()
    assert (reg / "templatte.toml.enc").is_file()
    p = pour(reg, passphrase=PASS, engine=engine)
    assert p.output == "templatte.toml" and not p.encrypted_removed
    assert (reg / "templatte.toml").read_bytes() == original
    assert (reg / "templatte.toml.enc").exists()


def test_keep_plain(reg: Path, engine: AesGcmCryptoEngine) -> None:
    r = press(reg, passphrase=PASS, keep_plain=True, engine=engine)
    assert not r.plain_removed and (reg / "templatte.toml").exists()


def test_press_custom_output_and_env(reg: Path, engine: AesGcmCryptoEngine) -> None:
    press(reg, output="out/x.enc", environ={"PW": PASS}, env_var="PW", engine=engine)
    assert (reg / "out/x.enc").is_file()


def test_press_weak_passphrase(reg: Path, engine: AesGcmCryptoEngine) -> None:
    before = (reg / "templatte.toml").read_bytes()
    with pytest.raises(WeakPassphraseError):
        press(reg, passphrase="short", engine=engine)
    assert (reg / "templatte.toml").read_bytes() == before
    assert not (reg / "templatte.toml.enc").exists()


def test_press_missing_and_legacy_registry(tmp_path: Path, engine: AesGcmCryptoEngine) -> None:
    with pytest.raises(ValidationError):
        press(tmp_path, passphrase=PASS, engine=engine)
    (tmp_path / "templatte.toml").write_text('"./a_b" = 1\n', encoding="utf-8", newline="\n")
    with pytest.raises(LegacyRegistryError):
        press(tmp_path, passphrase=PASS, engine=engine)


def test_press_existing_output_requires_force(reg: Path, engine: AesGcmCryptoEngine) -> None:
    (reg / "templatte.toml.enc").write_text("old", encoding="utf-8", newline="\n")
    with pytest.raises(UsageError):
        press(reg, passphrase=PASS, engine=engine)
    assert (reg / "templatte.toml.enc").read_text(encoding="utf-8") == "old"
    assert (reg / "templatte.toml").exists()
    press(reg, passphrase=PASS, force=True, engine=engine)
    assert (reg / "templatte.toml.enc").read_text(encoding="utf-8") != "old"


def test_press_output_outside_workspace(reg: Path, engine: AesGcmCryptoEngine) -> None:
    from templatte.core.exceptions import PathTraversalError

    with pytest.raises(PathTraversalError):
        press(reg, output="../evil.enc", passphrase=PASS, engine=engine)


def test_press_verify_before_write(reg: Path) -> None:
    class BadEngine(AesGcmCryptoEngine):
        def decrypt(self, envelope: CryptoEnvelope, passphrase: str) -> bytes:
            return b"wrong"

    with pytest.raises(CryptoError):
        press(reg, passphrase=PASS, engine=BadEngine(iterations=100_000))
    assert not (reg / "templatte.toml.enc").exists()
    assert (reg / "templatte.toml").exists()


def test_pour_wrong_passphrase(reg: Path, engine: AesGcmCryptoEngine) -> None:
    press(reg, passphrase=PASS, engine=engine)
    with pytest.raises(InvalidPassphraseError) as ei:
        pour(reg, passphrase="wrong passphrase here", engine=engine)
    assert ei.value.exit_code == 4
    assert not (reg / "templatte.toml").exists()


def test_pour_accepts_short_passphrase(reg: Path, engine: AesGcmCryptoEngine) -> None:
    # Envelope made directly with a short passphrase (legacy) must still pour.
    env = engine.encrypt(b"version = 1\n", "short")
    from templatte.adapters.crypto import to_json

    (reg / "templatte.toml.enc").write_text(to_json(env), encoding="utf-8", newline="\n")
    (reg / "templatte.toml").unlink()
    pour(reg, passphrase="short", engine=engine)
    assert (reg / "templatte.toml").read_bytes() == b"version = 1\n"


def test_pour_corrupted_and_missing_input(reg: Path, engine: AesGcmCryptoEngine) -> None:
    with pytest.raises(UsageError):
        pour(reg, passphrase=PASS, engine=engine)
    (reg / "templatte.toml.enc").write_text("{not json", encoding="utf-8", newline="\n")
    with pytest.raises(CorruptedEnvelopeError):
        pour(reg, passphrase=PASS, force=True, engine=engine)


def test_pour_force_backup(reg: Path, engine: AesGcmCryptoEngine) -> None:
    original = (reg / "templatte.toml").read_bytes()
    press(reg, passphrase=PASS, keep_plain=True, engine=engine)
    (reg / "templatte.toml").write_text("local edits\n", encoding="utf-8", newline="\n")
    with pytest.raises(UsageError):
        pour(reg, passphrase=PASS, engine=engine)
    assert (reg / "templatte.toml").read_text(encoding="utf-8") == "local edits\n"
    r = pour(reg, passphrase=PASS, force=True, backup=True, engine=engine)
    assert r.backup == "templatte.toml.20260101T000000.bak"
    assert (reg / r.backup).read_text(encoding="utf-8") == "local edits\n"
    assert (reg / "templatte.toml").read_bytes() == original


def test_pour_force_without_backup_makes_none(reg: Path, engine: AesGcmCryptoEngine) -> None:
    press(reg, passphrase=PASS, keep_plain=True, engine=engine)
    r = pour(reg, passphrase=PASS, force=True, engine=engine)
    assert r.backup is None
    assert not list(reg.glob("*.bak"))


def test_pour_keep_encrypted_false(reg: Path, engine: AesGcmCryptoEngine) -> None:
    press(reg, passphrase=PASS, engine=engine)
    r = pour(reg, passphrase=PASS, keep_encrypted=False, engine=engine)
    assert r.encrypted_removed and not (reg / "templatte.toml.enc").exists()


def test_pour_custom_paths(reg: Path, engine: AesGcmCryptoEngine) -> None:
    press(reg, output="vault/x.enc", passphrase=PASS, engine=engine)
    pour(reg, input="vault/x.enc", output="restored.toml", passphrase=PASS, engine=engine)
    assert (reg / "restored.toml").read_text(encoding="utf-8") == REGISTRY

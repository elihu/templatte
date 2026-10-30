"""Unit tests for the AES-256-GCM crypto engine and envelope."""

import base64
import dataclasses
import json

import pytest

from templatte.adapters.crypto import (
    AesGcmCryptoEngine,
    CryptoEnvelope,
    canonical_aad,
    from_json,
    header_aad,
    to_json,
)
from templatte.core.exceptions import (
    CorruptedEnvelopeError,
    CryptoError,
    InvalidPassphraseError,
)

PASSPHRASE = "correct horse battery staple"


@pytest.fixture
def engine() -> AesGcmCryptoEngine:
    return AesGcmCryptoEngine(iterations=100_000)


@pytest.fixture
def envelope(engine: AesGcmCryptoEngine) -> CryptoEnvelope:
    return engine.encrypt(b"secret = 'value'\n", PASSPHRASE)


def _flip(data: bytes) -> bytes:
    return bytes([data[0] ^ 0x01]) + data[1:]


def _doc(envelope: CryptoEnvelope) -> dict:
    return json.loads(to_json(envelope))


def test_default_iterations_is_600k() -> None:
    assert AesGcmCryptoEngine.ITERATIONS == 600_000
    assert AesGcmCryptoEngine().iterations == 600_000


@pytest.mark.parametrize("iterations", [99_999, 10_000_001])
def test_iterations_out_of_range_rejected(iterations: int) -> None:
    with pytest.raises(ValueError):
        AesGcmCryptoEngine(iterations=iterations)


def test_encrypt_aad_matches_envelope_header(engine: AesGcmCryptoEngine) -> None:
    env = engine.encrypt(b"x", PASSPHRASE)
    assert header_aad(env.iterations, env.salt) == canonical_aad(env)


@pytest.mark.parametrize("plaintext", [b"", b"hello", "café ☃ 日本".encode(), bytes(range(256))])
def test_round_trip(engine: AesGcmCryptoEngine, plaintext: bytes) -> None:
    env = engine.encrypt(plaintext, PASSPHRASE)
    assert engine.decrypt(env, PASSPHRASE) == plaintext


def test_round_trip_through_json(engine: AesGcmCryptoEngine) -> None:
    plaintext = "naïve ☃".encode()
    env = engine.encrypt(plaintext, PASSPHRASE)
    restored = from_json(to_json(env))
    assert restored == env
    assert engine.decrypt(restored, PASSPHRASE) == plaintext
    assert from_json(to_json(env).encode("utf-8")) == env


def test_encryptions_are_non_deterministic(engine: AesGcmCryptoEngine) -> None:
    a = engine.encrypt(b"same", PASSPHRASE)
    b = engine.encrypt(b"same", PASSPHRASE)
    assert a.salt != b.salt
    assert a.iv != b.iv
    assert a.ciphertext != b.ciphertext


def test_flipped_ciphertext_byte_fails(
    engine: AesGcmCryptoEngine, envelope: CryptoEnvelope
) -> None:
    bad = dataclasses.replace(envelope, ciphertext=_flip(envelope.ciphertext))
    with pytest.raises(InvalidPassphraseError):
        engine.decrypt(bad, PASSPHRASE)


def test_flipped_tag_byte_fails(engine: AesGcmCryptoEngine, envelope: CryptoEnvelope) -> None:
    bad = dataclasses.replace(envelope, tag=_flip(envelope.tag))
    with pytest.raises(InvalidPassphraseError):
        engine.decrypt(bad, PASSPHRASE)


def test_tampered_iterations_fails(engine: AesGcmCryptoEngine, envelope: CryptoEnvelope) -> None:
    assert envelope.iterations == 100_000
    bad = dataclasses.replace(envelope, iterations=100_001)
    with pytest.raises(InvalidPassphraseError):
        engine.decrypt(bad, PASSPHRASE)


def test_tampered_salt_fails(engine: AesGcmCryptoEngine, envelope: CryptoEnvelope) -> None:
    bad = dataclasses.replace(envelope, salt=_flip(envelope.salt))
    with pytest.raises(InvalidPassphraseError):
        engine.decrypt(bad, PASSPHRASE)


def test_wrong_passphrase_fails(engine: AesGcmCryptoEngine, envelope: CryptoEnvelope) -> None:
    with pytest.raises(InvalidPassphraseError) as exc_info:
        engine.decrypt(envelope, "wrong passphrase!!")
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__suppress_context__


def test_json_has_exact_spec_keys(envelope: CryptoEnvelope) -> None:
    text = to_json(envelope)
    assert text.endswith("\n")
    doc = json.loads(text)
    assert list(doc) == ["$schema", "version", "algorithm", "kdf", "iv", "tag", "ciphertext"]
    assert doc["$schema"] == "https://templatte.dev/schema/v1/encrypted.json"
    assert doc["version"] == 1
    assert doc["algorithm"] == "AES-256-GCM"
    assert list(doc["kdf"]) == ["name", "hash", "iterations", "salt"]
    assert doc["kdf"]["name"] == "PBKDF2HMAC"
    assert doc["kdf"]["hash"] == "SHA256"
    assert len(base64.b64decode(doc["kdf"]["salt"])) == 32
    assert len(base64.b64decode(doc["iv"])) == 12
    assert len(base64.b64decode(doc["tag"])) == 16


def _mutated(envelope: CryptoEnvelope, mutate) -> str:
    doc = _doc(envelope)
    mutate(doc)
    return json.dumps(doc)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.pop("tag"),
        lambda d: d["kdf"].pop("salt"),
        lambda d: d.pop("kdf"),
        lambda d: d.update(kdf="nope"),
        lambda d: d.update(iv="!!!not-base64!!!"),
        lambda d: d.update(ciphertext=123),
        lambda d: d.update(iv=base64.b64encode(b"x" * 16).decode()),
        lambda d: d["kdf"].update(salt=base64.b64encode(b"x" * 31).decode()),
        lambda d: d.update(tag=base64.b64encode(b"x" * 15).decode()),
        lambda d: d.update(version=2),
        lambda d: d.update(version=True),
        lambda d: d.update(algorithm="AES-128-CBC"),
        lambda d: d["kdf"].update(name="scrypt"),
        lambda d: d["kdf"].update(hash="SHA1"),
        lambda d: d["kdf"].update(iterations=99_999),
        lambda d: d["kdf"].update(iterations=10_000_001),
        lambda d: d["kdf"].update(iterations="600000"),
        lambda d: d["kdf"].update(iterations=600000.0),
    ],
)
def test_from_json_rejects_malformed(envelope: CryptoEnvelope, mutate) -> None:
    with pytest.raises(CorruptedEnvelopeError):
        from_json(_mutated(envelope, mutate))


@pytest.mark.parametrize("text", ["garbage {{", "", "[1, 2, 3]", '"str"', "null", b"\xff\xfe"])
def test_from_json_rejects_garbage(text: str | bytes) -> None:
    with pytest.raises(CorruptedEnvelopeError):
        from_json(text)


@pytest.mark.parametrize("exc", [CorruptedEnvelopeError("x"), InvalidPassphraseError()])
def test_errors_are_crypto_errors_with_exit_code_4(exc: Exception) -> None:
    assert isinstance(exc, CryptoError)
    assert exc.exit_code == 4

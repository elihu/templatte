"""Cryptographic envelope data structure and JSON (de)serialization.

Implements the envelope standard from MASTER_SPEC §7. Raw bytes are held
internally; base64 is only applied at the JSON boundary.
"""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from typing import Any

from templatte.core.exceptions import CorruptedEnvelopeError

SCHEMA_URL = "https://templatte.dev/schema/v1/encrypted.json"
ENVELOPE_VERSION = 1
ALGORITHM = "AES-256-GCM"
KDF_NAME = "PBKDF2HMAC"
KDF_HASH = "SHA256"

SALT_BYTES = 32
NONCE_BYTES = 12
TAG_BYTES = 16

MIN_ITERATIONS = 100_000
MAX_ITERATIONS = 10_000_000


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


@dataclass(frozen=True)
class CryptoEnvelope:
    """Self-describing encrypted payload with all binary fields as raw bytes."""

    iterations: int
    salt: bytes
    iv: bytes
    tag: bytes
    ciphertext: bytes
    version: int = ENVELOPE_VERSION
    algorithm: str = ALGORITHM
    kdf_name: str = KDF_NAME
    kdf_hash: str = KDF_HASH

    def __post_init__(self) -> None:
        """Validate structural invariants, rejecting anything unsupported."""
        if not _is_int(self.version) or self.version != ENVELOPE_VERSION:
            raise CorruptedEnvelopeError(f"unsupported version: {self.version!r}")
        if self.algorithm != ALGORITHM:
            raise CorruptedEnvelopeError(f"unsupported algorithm: {self.algorithm!r}")
        if self.kdf_name != KDF_NAME:
            raise CorruptedEnvelopeError(f"unsupported kdf name: {self.kdf_name!r}")
        if self.kdf_hash != KDF_HASH:
            raise CorruptedEnvelopeError(f"unsupported kdf hash: {self.kdf_hash!r}")
        if not _is_int(self.iterations):
            raise CorruptedEnvelopeError("kdf iterations must be an integer")
        if not MIN_ITERATIONS <= self.iterations <= MAX_ITERATIONS:
            raise CorruptedEnvelopeError(
                f"kdf iterations out of range [{MIN_ITERATIONS}, {MAX_ITERATIONS}]: "
                f"{self.iterations}"
            )
        for name, value, size in (
            ("salt", self.salt, SALT_BYTES),
            ("iv", self.iv, NONCE_BYTES),
            ("tag", self.tag, TAG_BYTES),
        ):
            if not isinstance(value, bytes) or len(value) != size:
                raise CorruptedEnvelopeError(f"{name} must be exactly {size} bytes")
        if not isinstance(self.ciphertext, bytes):
            raise CorruptedEnvelopeError("ciphertext must be bytes")


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def header_aad(
    iterations: int,
    salt: bytes,
    version: int = ENVELOPE_VERSION,
    algorithm: str = ALGORITHM,
    kdf_name: str = KDF_NAME,
    kdf_hash: str = KDF_HASH,
) -> bytes:
    """Return the deterministic header encoding authenticated as AES-GCM AAD.

    Covers ``version``, ``algorithm`` and all KDF parameters (name, hash,
    iterations, salt), so tampering with any of them fails authentication.
    """
    return f"{version}|{algorithm}|{kdf_name}|{kdf_hash}|{iterations}|{_b64(salt)}".encode()


def canonical_aad(envelope: CryptoEnvelope) -> bytes:
    """Return the AAD for an existing envelope's header (see ``header_aad``)."""
    return header_aad(
        envelope.iterations,
        envelope.salt,
        envelope.version,
        envelope.algorithm,
        envelope.kdf_name,
        envelope.kdf_hash,
    )


def to_json(envelope: CryptoEnvelope) -> str:
    """Serialize an envelope to the MASTER_SPEC §7 JSON document."""
    doc = {
        "$schema": SCHEMA_URL,
        "version": envelope.version,
        "algorithm": envelope.algorithm,
        "kdf": {
            "name": envelope.kdf_name,
            "hash": envelope.kdf_hash,
            "iterations": envelope.iterations,
            "salt": _b64(envelope.salt),
        },
        "iv": _b64(envelope.iv),
        "tag": _b64(envelope.tag),
        "ciphertext": _b64(envelope.ciphertext),
    }
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"


def _require(obj: dict[str, Any], key: str, where: str = "envelope") -> Any:
    if key not in obj:
        raise CorruptedEnvelopeError(f"missing field '{key}' in {where}")
    return obj[key]


def _decode_b64(obj: dict[str, Any], key: str, where: str = "envelope") -> bytes:
    value = _require(obj, key, where)
    if not isinstance(value, str):
        raise CorruptedEnvelopeError(f"field '{key}' must be a base64 string")
    try:
        return base64.b64decode(value.encode("ascii"), validate=True)
    except (binascii.Error, ValueError, UnicodeEncodeError):
        raise CorruptedEnvelopeError(f"field '{key}' is not valid base64") from None


def from_json(text: str | bytes) -> CryptoEnvelope:
    """Parse and validate an envelope JSON document.

    Raises:
        CorruptedEnvelopeError: for any structural, encoding or range problem.
    """
    try:
        doc = json.loads(text)
    except (ValueError, RecursionError):  # JSONDecodeError and UnicodeDecodeError
        raise CorruptedEnvelopeError("not valid JSON") from None
    if not isinstance(doc, dict):
        raise CorruptedEnvelopeError("top-level JSON value must be an object")

    version = _require(doc, "version")
    algorithm = _require(doc, "algorithm")
    kdf = _require(doc, "kdf")
    if not isinstance(kdf, dict):
        raise CorruptedEnvelopeError("field 'kdf' must be an object")

    kdf_name = _require(kdf, "name", "kdf")
    kdf_hash = _require(kdf, "hash", "kdf")
    iterations = _require(kdf, "iterations", "kdf")
    salt = _decode_b64(kdf, "salt", "kdf")
    iv = _decode_b64(doc, "iv")
    tag = _decode_b64(doc, "tag")
    ciphertext = _decode_b64(doc, "ciphertext")

    # __post_init__ enforces version/algorithm/kdf support, ranges and lengths.
    return CryptoEnvelope(
        version=version,
        algorithm=algorithm,
        kdf_name=kdf_name,
        kdf_hash=kdf_hash,
        iterations=iterations,
        salt=salt,
        iv=iv,
        tag=tag,
        ciphertext=ciphertext,
    )

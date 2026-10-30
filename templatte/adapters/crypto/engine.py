"""Pure-Python AES-256-GCM cryptography engine (ARCHITECTURE §4.1).

In-memory bytes in, envelope out. No file I/O, no passphrase acquisition.
"""

from __future__ import annotations

import os
from typing import Protocol

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from templatte.adapters.crypto.envelope import (
    MAX_ITERATIONS,
    MIN_ITERATIONS,
    NONCE_BYTES,
    SALT_BYTES,
    TAG_BYTES,
    CryptoEnvelope,
    canonical_aad,
    header_aad,
)
from templatte.core.exceptions import InvalidPassphraseError


class CryptoEngine(Protocol):
    """Interface for authenticated encryption engines."""

    def encrypt(self, plaintext: bytes, passphrase: str) -> CryptoEnvelope:
        """Encrypt plaintext under a key derived from the passphrase."""
        ...

    def decrypt(self, envelope: CryptoEnvelope, passphrase: str) -> bytes:
        """Authenticate and decrypt an envelope."""
        ...


class AesGcmCryptoEngine:
    """AES-256-GCM with PBKDF2-HMAC-SHA256 key derivation.

    The canonical envelope header is passed as AAD, so tampering with it fails
    authentication exactly like tampering with the ciphertext.
    """

    SALT_BYTES = SALT_BYTES
    NONCE_BYTES = NONCE_BYTES
    KEY_BYTES = 32  # 256 bits
    TAG_BYTES = TAG_BYTES
    ITERATIONS = 600_000

    def __init__(self, iterations: int = ITERATIONS) -> None:
        if not MIN_ITERATIONS <= iterations <= MAX_ITERATIONS:
            raise ValueError(
                f"iterations must be within [{MIN_ITERATIONS}, {MAX_ITERATIONS}]: {iterations}"
            )
        self.iterations = iterations

    def _derive_key(self, passphrase: str, salt: bytes, iterations: int) -> bytes:
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=self.KEY_BYTES,
            salt=salt,
            iterations=iterations,
        )
        return kdf.derive(passphrase.encode("utf-8"))

    def encrypt(self, plaintext: bytes, passphrase: str) -> CryptoEnvelope:
        """Encrypt ``plaintext`` and return a self-describing envelope."""
        salt = os.urandom(self.SALT_BYTES)
        nonce = os.urandom(self.NONCE_BYTES)
        key = self._derive_key(passphrase, salt, self.iterations)

        aad = header_aad(self.iterations, salt)
        sealed = AESGCM(key).encrypt(nonce, plaintext, aad)
        # AESGCM appends the 16-byte tag to the ciphertext.
        return CryptoEnvelope(
            iterations=self.iterations,
            salt=salt,
            iv=nonce,
            tag=sealed[-self.TAG_BYTES :],
            ciphertext=sealed[: -self.TAG_BYTES],
        )

    def decrypt(self, envelope: CryptoEnvelope, passphrase: str) -> bytes:
        """Authenticate and decrypt ``envelope``.

        Raises:
            InvalidPassphraseError: wrong passphrase, or tampered ciphertext,
                tag or authenticated header.
        """
        key = self._derive_key(passphrase, envelope.salt, envelope.iterations)
        try:
            return AESGCM(key).decrypt(
                envelope.iv,
                envelope.ciphertext + envelope.tag,
                canonical_aad(envelope),
            )
        except InvalidTag:
            raise InvalidPassphraseError() from None

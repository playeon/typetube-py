"""
TAP cryptographic session management, ECDH key exchange, and AES-256-GCM framing.
Matches src/tap/crypto.ts.
"""
from __future__ import annotations
import hmac
import hashlib
import struct
from typing import Optional, Tuple
from cryptography.hazmat.primitives.asymmetric import ec, ed25519
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.serialization import (
    Encoding, PublicFormat, PrivateFormat, NoEncryption
)

GCM_TAG_LENGTH = 16
GCM_IV_LENGTH = 12

class TapCryptoSession:
    def __init__(self, shared_secret: bytes, is_server: bool = False, psk: Optional[str] = None) -> None:
        salt = psk.encode("utf-8") if (psk and len(psk) > 0) else b"TAP_CRYPTO_SALT_v1"
        prk = hmac.new(salt, shared_secret, hashlib.sha256).digest()
        c2s_key = hmac.new(prk, b"TAP_C2S_KEY", hashlib.sha256).digest()
        s2c_key = hmac.new(prk, b"TAP_S2C_KEY", hashlib.sha256).digest()
        self.base_iv = hmac.new(prk, b"TAP_BASE_IV", hashlib.sha256).digest()[:8]

        if is_server:
            self.send_key = s2c_key
            self.recv_key = c2s_key
        else:
            self.send_key = c2s_key
            self.recv_key = s2c_key

        self.send_cipher = AESGCM(self.send_key)
        self.recv_cipher = AESGCM(self.recv_key)
        self.send_nonce_counter = 0
        self.recv_nonce_counter = 0

    def _make_iv(self, counter: int) -> bytes:
        return self.base_iv + struct.pack(">I", counter)

    def encrypt(self, plaintext: bytes, aad: Optional[bytes] = None) -> bytes:
        self.send_nonce_counter += 1
        iv = self._make_iv(self.send_nonce_counter)
        # cryptography's AESGCM.encrypt returns ciphertext + 16-byte tag appended at the end
        ciphertext_and_tag = self.send_cipher.encrypt(iv, plaintext, aad)
        tag = ciphertext_and_tag[-GCM_TAG_LENGTH:]
        ciphertext = ciphertext_and_tag[:-GCM_TAG_LENGTH]
        # TAP framing expects: [tag (16 bytes)][ciphertext]
        return tag + ciphertext

    def decrypt(self, payload: bytes, aad: Optional[bytes] = None) -> bytes:
        if len(payload) < GCM_TAG_LENGTH:
            raise ValueError("Payload too short to contain AES-GCM authentication tag")
        tag = payload[:GCM_TAG_LENGTH]
        ciphertext = payload[GCM_TAG_LENGTH:]
        self.recv_nonce_counter += 1
        iv = self._make_iv(self.recv_nonce_counter)
        # cryptography's AESGCM.decrypt expects ciphertext + tag
        data_to_decrypt = ciphertext + tag
        return self.recv_cipher.decrypt(iv, data_to_decrypt, aad)


def generate_ecdh_key_pair() -> Tuple[ec.EllipticCurvePrivateKey, bytes]:
    private_key = ec.generate_private_key(ec.SECP256R1())
    # Raw uncompressed point format: 0x04 || X (32) || Y (32) -> 65 bytes
    public_bytes = private_key.public_key().public_bytes(
        Encoding.X962,
        PublicFormat.UncompressedPoint
    )
    return private_key, public_bytes


def compute_shared_secret(private_key: ec.EllipticCurvePrivateKey, remote_public_bytes: bytes) -> bytes:
    peer_public_key = ec.EllipticCurvePublicKey.from_encoded_point(
        ec.SECP256R1(),
        remote_public_bytes
    )
    return private_key.exchange(ec.ECDH(), peer_public_key)


def compute_handshake_proof(key: str, data: bytes) -> bytes:
    k = key.encode("utf-8") if isinstance(key, str) else key
    return hmac.new(k, data, hashlib.sha256).digest()


def verify_handshake_proof(key: str, data: bytes, expected_proof: bytes) -> bool:
    actual = compute_handshake_proof(key, data)
    return hmac.compare_digest(actual, expected_proof)


def verify_signature(public_key_der: bytes, data: bytes, signature: bytes) -> bool:
    try:
        from cryptography.hazmat.primitives.serialization import load_der_public_key
        pub_key = load_der_public_key(public_key_der)
        if isinstance(pub_key, ed25519.Ed25519PublicKey):
            pub_key.verify(signature, data)
            return True
        return False
    except Exception:
        return False

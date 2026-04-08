import hashlib
import json
import os
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import settings


def _aes_key() -> bytes:
    if settings.token_encryption_key.strip():
        return hashlib.sha256(settings.token_encryption_key.strip().encode()).digest()
    return hashlib.sha256(settings.secret_key.encode()).digest()


def encrypt_json(payload: dict[str, Any]) -> bytes:
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    aesgcm = AESGCM(_aes_key())
    nonce = os.urandom(12)
    return nonce + aesgcm.encrypt(nonce, raw, associated_data=None)


def decrypt_json(blob: bytes) -> dict[str, Any]:
    if len(blob) < 13:
        raise ValueError("invalid ciphertext")
    nonce, ct = blob[:12], blob[12:]
    aesgcm = AESGCM(_aes_key())
    raw = aesgcm.decrypt(nonce, ct, associated_data=None)
    return json.loads(raw.decode("utf-8"))


def encrypt_secret(text: str) -> bytes:
    """Шифрование одной строки (api_hash, session Telethon и т.п.)."""
    return encrypt_json({"_v": text})


def decrypt_secret(blob: bytes) -> str:
    data = decrypt_json(blob)
    v = data.get("_v")
    if not isinstance(v, str):
        raise ValueError("invalid secret payload")
    return v

"""
Envelope encryption helpers for OAuth tokens.

Google Calendar OAuth access/refresh tokens are encrypted at rest using
Fernet symmetric encryption before being written to doctor_google_credentials.
The key is loaded from the ENCRYPTION_KEY environment variable — never a
hardcoded string.

Usage:
    from common.encryption import encrypt_token, decrypt_token
    ciphertext = encrypt_token("ya29.real_token_here")
    plaintext  = decrypt_token(ciphertext)
"""
from __future__ import annotations

from cryptography.fernet import Fernet
from django.conf import settings


def _get_fernet() -> Fernet:
    key = settings.ENCRYPTION_KEY
    if not key:
        raise RuntimeError(
            "ENCRYPTION_KEY is not set. "
            "Generate one with: "
            "python -c 'from cryptography.fernet import Fernet;"
            " print(Fernet.generate_key().decode())'"
        )
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt_token(plaintext: str) -> str:
    """Encrypt a token string and return the ciphertext as a string."""
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt_token(ciphertext: str) -> str:
    """Decrypt a ciphertext string and return the original token."""
    return _get_fernet().decrypt(ciphertext.encode()).decode()

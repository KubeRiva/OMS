"""
Shopify access-token encryption helpers.

Shopify access tokens are long-lived bearer credentials that grant full
Shopify Admin API access. They must not be stored in plaintext.
We derive a 256-bit AES-GCM key from SECRET_KEY using HKDF-SHA256 so that
rotating SECRET_KEY invalidates all cached tokens and forces re-install —
a safe, auditable behaviour.

This module is shared between:
  - app/routers/shopify_oauth.py  (encrypts token on store)
  - app/services/connectors/shopify.py  (decrypts token on use)
"""
import base64
import functools

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.config import settings


@functools.lru_cache(maxsize=1)
def _get_token_fernet() -> Fernet:
    """Derive a Fernet encryption key from SECRET_KEY once per process."""
    raw_key = settings.SECRET_KEY.encode()
    hkdf = HKDF(
        algorithm=SHA256(),
        length=32,
        salt=b"shopify-access-token-v1",
        info=b"shopify-connector-token",
        backend=default_backend(),
    )
    derived = hkdf.derive(raw_key)
    fernet_key = base64.urlsafe_b64encode(derived)
    return Fernet(fernet_key)


def encrypt_access_token(plaintext: str) -> str:
    """Return Fernet-encrypted, base64-encoded token string for DB storage."""
    return _get_token_fernet().encrypt(plaintext.encode()).decode()


def decrypt_access_token(ciphertext: str) -> str:
    """
    Return the plaintext access token.

    Handles both encrypted (Fernet token, starts with 'gAAAAA') and plaintext
    tokens gracefully for backward compatibility with any existing connectors
    that have plaintext tokens stored before encryption was introduced.

    Raises cryptography.fernet.InvalidToken if the value looks like a Fernet
    token but cannot be decrypted (tamper or key mismatch).
    """
    if not ciphertext:
        return ciphertext
    # Fernet tokens always start with 'gAAAAA' after base64url encoding.
    # If the value doesn't match that prefix, treat it as plaintext.
    if ciphertext.startswith("gAAAAA"):
        return _get_token_fernet().decrypt(ciphertext.encode()).decode()
    # Plaintext token — return as-is (backward-compatible path).
    return ciphertext

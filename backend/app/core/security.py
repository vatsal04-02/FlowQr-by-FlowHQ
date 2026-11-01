"""Password hashing (Argon2id), opaque tokens, CSRF and token encryption."""
import hashlib
import hmac
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings

_ph = PasswordHasher()  # Argon2id by default


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _ph.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _ph.check_needs_rehash(password_hash)


# A fixed hash used to equalise timing when the user does not exist.
DUMMY_HASH = _ph.hash("not-a-real-password")


def new_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def hash_token(token: str) -> str:
    """SHA-256 for high-entropy random tokens (session, reset, invitation)."""
    return hashlib.sha256(token.encode()).hexdigest()


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


def sign_state(payload: str) -> str:
    sig = hmac.new(settings.secret_key.encode(), payload.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{payload}.{sig}"


def verify_state(signed: str) -> str | None:
    payload, _, sig = signed.rpartition(".")
    if not payload:
        return None
    expected = sign_state(payload).rpartition(".")[2]
    return payload if hmac.compare_digest(sig, expected) else None


class TokenCipher:
    """Fernet encryption for Google refresh/access tokens at rest."""

    def __init__(self, key: str):
        if not key:
            raise RuntimeError("TOKEN_ENCRYPTION_KEY is not configured")
        self._f = Fernet(key.encode())

    def encrypt(self, plaintext: str) -> str:
        return self._f.encrypt(plaintext.encode()).decode()

    def decrypt(self, ciphertext: str) -> str:
        try:
            return self._f.decrypt(ciphertext.encode()).decode()
        except InvalidToken as exc:
            raise RuntimeError("Unable to decrypt token (wrong TOKEN_ENCRYPTION_KEY?)") from exc


def get_cipher() -> TokenCipher:
    return TokenCipher(settings.token_encryption_key)

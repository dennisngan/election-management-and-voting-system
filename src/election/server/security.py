from hashlib import sha256

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError

password_hasher = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)
_dummy_hash = password_hasher.hash("unusable-dummy-account")


def normalize_username(value: str) -> str:
    if not value.strip():
        raise ValueError("A username is required")
    return value.strip()


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(stored_hash: str | None, password: str) -> bool:
    try:
        result = password_hasher.verify(stored_hash or _dummy_hash, password)
        return result and stored_hash is not None
    except VerificationError:
        return False


def token_digest(token: str) -> str:
    return sha256(token.encode()).hexdigest()

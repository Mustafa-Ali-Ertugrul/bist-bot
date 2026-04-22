"""Modern password hashing with scrypt and legacy bcrypt fallback."""

from __future__ import annotations

import bcrypt
from werkzeug.security import check_password_hash, generate_password_hash


_MODERN_HASH_PREFIX = "scrypt:"


def hash_password(password: str) -> str:
    return generate_password_hash(password, method="scrypt")


def _is_modern_hash(password_hash: str) -> bool:
    return password_hash.startswith((_MODERN_HASH_PREFIX, "pbkdf2:"))


def _is_bcrypt_hash(password_hash: str) -> bool:
    return password_hash.startswith(("$2a$", "$2b$", "$2y$"))


def verify_and_rehash_password(password: str, password_hash: str) -> tuple[bool, str | None]:
    if not password_hash:
        return False, None

    if _is_modern_hash(password_hash):
        if not check_password_hash(password_hash, password):
            return False, None
        if not password_hash.startswith(_MODERN_HASH_PREFIX):
            return True, hash_password(password)
        return True, None

    if _is_bcrypt_hash(password_hash):
        try:
            verified = bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
        except ValueError:
            return False, None
        if not verified:
            return False, None
        return True, hash_password(password)

    return False, None

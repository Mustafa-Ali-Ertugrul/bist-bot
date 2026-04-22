"""Password hashing utility tests."""

from __future__ import annotations

import bcrypt

from bist_bot.auth.passwords import hash_password, verify_and_rehash_password


def test_hash_password_creates_scrypt_hash() -> None:
    password_hash = hash_password("secret-password")

    assert password_hash.startswith("scrypt:")


def test_verify_and_rehash_password_accepts_modern_hash() -> None:
    password_hash = hash_password("secret-password")

    verified, upgraded_hash = verify_and_rehash_password("secret-password", password_hash)

    assert verified is True
    assert upgraded_hash is None


def test_verify_and_rehash_password_migrates_legacy_bcrypt_hash() -> None:
    legacy_hash = bcrypt.hashpw(b"legacy-password", bcrypt.gensalt()).decode("utf-8")

    verified, upgraded_hash = verify_and_rehash_password("legacy-password", legacy_hash)

    assert verified is True
    assert isinstance(upgraded_hash, str)
    assert upgraded_hash.startswith("scrypt:")

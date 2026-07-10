from __future__ import annotations

import hashlib
import hmac
import secrets


PBKDF2_ALGORITHM = "sha256"
PBKDF2_ITERATIONS = 310_000
HASH_PREFIX = "pbkdf2_sha256"
SALT_BYTES = 16


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(SALT_BYTES)
    digest = hashlib.pbkdf2_hmac(
        PBKDF2_ALGORITHM,
        password.encode("utf-8"),
        salt,
        PBKDF2_ITERATIONS,
    )
    return f"{HASH_PREFIX}${PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def is_hashed_password(value: str | None) -> bool:
    return bool(value and value.startswith(f"{HASH_PREFIX}$"))


def verify_password(password: str, stored_value: str | None) -> bool:
    if not stored_value:
        return False

    if not is_hashed_password(stored_value):
        return hmac.compare_digest(stored_value, password)

    try:
        _, iterations, salt_hex, digest_hex = stored_value.split("$", maxsplit=3)
        expected = hashlib.pbkdf2_hmac(
            PBKDF2_ALGORITHM,
            password.encode("utf-8"),
            bytes.fromhex(salt_hex),
            int(iterations),
        )
    except (TypeError, ValueError):
        return False

    return hmac.compare_digest(expected.hex(), digest_hex)


def should_upgrade_password(stored_value: str | None) -> bool:
    if not stored_value or not is_hashed_password(stored_value):
        return True

    try:
        _, iterations, _, _ = stored_value.split("$", maxsplit=3)
    except ValueError:
        return True
    return int(iterations) < PBKDF2_ITERATIONS

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError


password_hasher = PasswordHasher()

# Perform a real Argon2 verification even when an account does not exist. This
# reduces the timing difference between an unknown email and a wrong password.
DUMMY_PASSWORD_HASH = password_hasher.hash(
    "food-truck-works-dummy-password-verification"
)

MIN_PASSWORD_LENGTH = 10
MAX_PASSWORD_LENGTH = 128


def validate_password(password: str) -> str | None:
    """Return a user-facing validation message, or None when valid."""
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
    if len(password) > MAX_PASSWORD_LENGTH:
        return f"Password must be no more than {MAX_PASSWORD_LENGTH} characters."
    return None


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    hash_to_verify = password_hash or DUMMY_PASSWORD_HASH

    try:
        return password_hasher.verify(hash_to_verify, password)
    except VerificationError:
        return False


def password_needs_rehash(password_hash: str) -> bool:
    """Return whether a valid hash should be upgraded to current settings."""
    return password_hasher.check_needs_rehash(password_hash)

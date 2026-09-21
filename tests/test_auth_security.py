import unittest

from argon2 import PasswordHasher

from auth import (
    hash_password,
    password_needs_rehash,
    verify_password,
)


class PasswordSecurityTests(unittest.TestCase):
    def test_hash_verifies_only_the_correct_password(self):
        password_hash = hash_password("a sufficiently long password")

        self.assertTrue(
            verify_password("a sufficiently long password", password_hash)
        )
        self.assertFalse(verify_password("the wrong password", password_hash))

    def test_missing_account_still_performs_verification_and_fails(self):
        self.assertFalse(verify_password("any supplied password", None))

    def test_weaker_argon2_hash_is_marked_for_upgrade(self):
        older_hasher = PasswordHasher(
            time_cost=1,
            memory_cost=1024,
            parallelism=1,
        )
        older_hash = older_hasher.hash("a sufficiently long password")

        self.assertTrue(password_needs_rehash(older_hash))


if __name__ == "__main__":
    unittest.main()

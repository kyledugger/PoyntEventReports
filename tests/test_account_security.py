import os
import unittest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from email_service import EmailDeliveryError, send_password_reset_email
from models import Base, User
from security_tokens import (
    EMAIL_VERIFICATION,
    EMAIL_VERIFICATION_LIFETIME,
    PASSWORD_RESET,
    create_security_token,
    get_valid_security_token,
    hash_token,
)


class SecurityTokenTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        with Session(self.engine) as session:
            user = User(
                email="owner@example.com",
                password_hash="not-used-in-this-test",
            )
            session.add(user)
            session.commit()
            self.user_id = user.id

    def test_raw_token_is_not_stored_and_token_is_purpose_bound(self):
        with Session(self.engine) as session:
            raw_token = create_security_token(
                session,
                self.user_id,
                EMAIL_VERIFICATION,
                EMAIL_VERIFICATION_LIFETIME,
            )
            session.commit()

            token = get_valid_security_token(
                session, raw_token, EMAIL_VERIFICATION
            )
            self.assertIsNotNone(token)
            self.assertEqual(token.token_hash, hash_token(raw_token))
            self.assertNotEqual(token.token_hash, raw_token)
            self.assertIsNone(
                get_valid_security_token(session, raw_token, PASSWORD_RESET)
            )

    def test_creating_a_replacement_invalidates_the_previous_token(self):
        with Session(self.engine) as session:
            first = create_security_token(
                session,
                self.user_id,
                EMAIL_VERIFICATION,
                EMAIL_VERIFICATION_LIFETIME,
            )
            second = create_security_token(
                session,
                self.user_id,
                EMAIL_VERIFICATION,
                EMAIL_VERIFICATION_LIFETIME,
            )
            session.commit()

            self.assertIsNone(
                get_valid_security_token(session, first, EMAIL_VERIFICATION)
            )
            self.assertIsNotNone(
                get_valid_security_token(session, second, EMAIL_VERIFICATION)
            )

    def test_expired_token_is_rejected(self):
        with Session(self.engine) as session:
            raw_token = create_security_token(
                session,
                self.user_id,
                PASSWORD_RESET,
                timedelta(seconds=-1),
            )
            session.commit()
            self.assertIsNone(
                get_valid_security_token(session, raw_token, PASSWORD_RESET)
            )


class PostmarkEmailTests(unittest.TestCase):
    @patch.dict(
        os.environ,
        {
            "POSTMARK_SERVER_TOKEN": "test-token",
            "EMAIL_FROM": "support@example.com",
            "APP_BASE_URL": "https://foodtruckworks.com/",
        },
        clear=False,
    )
    @patch("email_service.httpx.post")
    def test_password_reset_email_uses_postmark_without_exposing_server_token(
        self, post
    ):
        response = Mock()
        response.raise_for_status.return_value = None
        post.return_value = response

        send_password_reset_email("owner@example.com", "raw-secret-token")

        _, kwargs = post.call_args
        self.assertEqual(
            kwargs["headers"]["X-Postmark-Server-Token"], "test-token"
        )
        self.assertNotIn("test-token", str(kwargs["json"]))
        self.assertIn(
            "https://foodtruckworks.com/reset-password/raw-secret-token",
            kwargs["json"]["TextBody"],
        )

    @patch.dict(os.environ, {}, clear=True)
    def test_missing_email_configuration_fails_closed(self):
        with self.assertRaises(EmailDeliveryError):
            send_password_reset_email("owner@example.com", "token")


if __name__ == "__main__":
    unittest.main()

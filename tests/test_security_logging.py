import json
import logging
import unittest

from starlette.requests import Request

from security_logging import log_security_event


def make_request(headers=None):
    raw_headers = [
        (key.lower().encode("ascii"), value.encode("ascii"))
        for key, value in (headers or {}).items()
    ]
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/invite/secret-token",
            "headers": raw_headers,
            "client": ("10.0.0.1", 12345),
            "server": ("testserver", 80),
            "scheme": "http",
        }
    )


class SecurityLoggingTests(unittest.TestCase):
    def test_event_is_structured_and_omits_request_path(self):
        request = make_request(
            {
                "cf-connecting-ip": "203.0.113.10",
                "user-agent": "Security test client",
            }
        )

        with self.assertLogs("security", level=logging.INFO) as captured:
            log_security_event(
                request,
                "login",
                "failed",
                user_id=12,
                reason="invalid_password",
            )

        message = captured.output[0]
        payload = json.loads(message.split("SECURITY_EVENT ", 1)[1])
        self.assertEqual(payload["client_ip"], "203.0.113.10")
        self.assertEqual(payload["ip_source"], "cloudflare")
        self.assertEqual(payload["user_id"], 12)
        self.assertNotIn("path", payload)
        self.assertNotIn("secret-token", message)

    def test_untrusted_headers_cannot_create_new_log_lines(self):
        request = make_request({"user-agent": "agent\r\nforged-event"})

        with self.assertLogs("security", level=logging.INFO) as captured:
            log_security_event(request, "logout", "succeeded")

        message = captured.output[0]
        self.assertNotIn("\r", message)
        self.assertNotIn("\n", message)


if __name__ == "__main__":
    unittest.main()

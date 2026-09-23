import html
import os
import re

import httpx


POSTMARK_EMAIL_URL = "https://api.postmarkapp.com/email"


class EmailDeliveryError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        postmark_error_code: int | None = None,
        postmark_message: str | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.postmark_error_code = postmark_error_code
        self.postmark_message = postmark_message


def _safe_postmark_message(message: object) -> str | None:
    if not isinstance(message, str) or not message:
        return None
    single_line = message.replace("\r", " ").replace("\n", " ")
    redacted = re.sub(
        r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}",
        "[redacted-email]",
        single_line,
        flags=re.IGNORECASE,
    )
    return redacted[:300]


def _configuration() -> tuple[str, str, str]:
    server_token = os.getenv("POSTMARK_SERVER_TOKEN")
    from_address = os.getenv("EMAIL_FROM")
    app_base_url = os.getenv("APP_BASE_URL")
    if not server_token or not from_address or not app_base_url:
        raise EmailDeliveryError(
            "POSTMARK_SERVER_TOKEN, EMAIL_FROM, and APP_BASE_URL must be configured"
        )
    return server_token, from_address, app_base_url.rstrip("/")


def _send_email(to_address: str, subject: str, text_body: str, html_body: str) -> None:
    server_token, from_address, _ = _configuration()
    try:
        response = httpx.post(
            POSTMARK_EMAIL_URL,
            headers={"X-Postmark-Server-Token": server_token},
            json={
                "From": from_address,
                "To": to_address,
                "Subject": subject,
                "TextBody": text_body,
                "HtmlBody": html_body,
                "MessageStream": "outbound",
            },
            timeout=10.0,
        )
    except httpx.RequestError as exc:
        raise EmailDeliveryError("Unable to connect to Postmark") from exc

    if response.is_success:
        return

    error_code = None
    postmark_message = None
    try:
        error_payload = response.json()
        error_code = error_payload.get("ErrorCode")
        postmark_message = _safe_postmark_message(error_payload.get("Message"))
    except (ValueError, AttributeError):
        pass

    raise EmailDeliveryError(
        "Postmark did not accept the email",
        status_code=response.status_code,
        postmark_error_code=error_code,
        postmark_message=postmark_message,
    )


def send_verification_email(to_address: str, raw_token: str) -> None:
    _, _, app_base_url = _configuration()
    url = f"{app_base_url}/verify-email/{raw_token}"
    safe_url = html.escape(url, quote=True)
    _send_email(
        to_address,
        "Verify your Food Truck Works email",
        f"Verify your email address by visiting this link:\n\n{url}\n\n"
        "This link expires in 24 hours.",
        "<p>Verify your email address to finish creating your Food Truck Works "
        f"account.</p><p><a href=\"{safe_url}\">Verify email address</a></p>"
        "<p>This link expires in 24 hours.</p>",
    )


def send_password_reset_email(to_address: str, raw_token: str) -> None:
    _, _, app_base_url = _configuration()
    url = f"{app_base_url}/reset-password/{raw_token}"
    safe_url = html.escape(url, quote=True)
    _send_email(
        to_address,
        "Reset your Food Truck Works password",
        f"Reset your password by visiting this link:\n\n{url}\n\n"
        "This link expires in 30 minutes. If you did not request this, ignore it.",
        "<p>A password reset was requested for your Food Truck Works account.</p>"
        f"<p><a href=\"{safe_url}\">Reset password</a></p>"
        "<p>This link expires in 30 minutes. If you did not request this, "
        "you can ignore this email.</p>",
    )

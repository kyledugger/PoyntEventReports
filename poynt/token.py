import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import jwt
import logging

logger = logging.getLogger(__name__)


PRIVATE_KEY_PATH = (
    Path(__file__).resolve().parent.parent
    / "jwt"
    / "poynt_private_key.pem"
)


PRIVATE_KEY_PATH = Path(
    os.getenv(
        "POYNT_PRIVATE_KEY_PATH",
        Path(__file__).resolve().parent.parent
        / "jwt"
        / "poynt_private_key.pem"
    )
)


def load_private_key() -> str:
    if not PRIVATE_KEY_PATH.exists():
        raise FileNotFoundError(
            f"Poynt private key not found at {PRIVATE_KEY_PATH}"
        )

    return PRIVATE_KEY_PATH.read_text(encoding="utf-8")


def create_self_signed_jwt() -> str:
    poynt_app_id = os.environ["POYNT_APP_ID"]    
    now = datetime.now(timezone.utc)

    payload = {
        "exp": now + timedelta(minutes=5),
        "iat": now,
        "iss": poynt_app_id,
        "sub": poynt_app_id,
        "aud": "https://services.poynt.net",
        "jti": str(uuid.uuid4()),
    }

    private_key = load_private_key()

    return jwt.encode(
        payload,
        private_key,
        algorithm="RS256",
    )


async def exchange_authorization_code(
    code: str,
    redirect_uri: str,
) -> dict:

    poynt_app_id = os.environ["POYNT_APP_ID"]
    poynt_token_url = os.environ["POYNT_TOKEN_URL"]

    self_signed_jwt = create_self_signed_jwt()

    headers = {
        "Accept": "application/json",
        "api-version": "1.2",
        "Authorization": f"Bearer {self_signed_jwt}",
        "Content-Type": "application/x-www-form-urlencoded",
    }

    data = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": poynt_app_id,
        "redirect_uri": redirect_uri,
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            poynt_token_url,
            headers=headers,
            data=data,
        )

    if not response.is_success:
        logger.error(
            "Poynt token request failed:\n"
            f"  HTTP status: {response.status_code}\n"
            f"  Response: {response.text}\n"
            f"  Token URL: {poynt_token_url}\n"
            f"  App ID: {poynt_app_id}\n"
            f"  Redirect URI: {redirect_uri}\n"
            f"  Grant type: {data['grant_type']}\n"
            f"  Code present: {bool(code)}\n"
            f"  Self-signed JWT present: {bool(self_signed_jwt)}\n"
            f"  Self-signed JWT length: {len(self_signed_jwt)}"
        )

        response.raise_for_status()

    return response.json()



async def refresh_access_token(
    refresh_token: str,
) -> dict:
    """
    Refresh an active Poynt authorization.

    Poynt's refresh flow uses the existing refresh token and does
    not require the application's self-signed JWT.
    """

    poynt_token_url = os.environ["POYNT_TOKEN_URL"]

    headers = {
        "Accept": "application/json",
        "api-version": "1.2",
        "Content-Type": "application/x-www-form-urlencoded",
        "Poynt-Request-Id": str(uuid.uuid4()),
    }

    data = {
        "grantType": "REFRESH_TOKEN",
        "refreshToken": refresh_token,
    }

    logger.info("Refreshing Poynt access token with refresh token" )

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            poynt_token_url,
            headers=headers,
            data=data,
        )

    if not response.is_success:
        logger.error(
            "Poynt token exchange failed: HTTP %d",
            response.status_code,
        )
        logger.debug(
            "Poynt token exchange error response: %s",
            response.text,
        )        

        response.raise_for_status()

    return response.json()
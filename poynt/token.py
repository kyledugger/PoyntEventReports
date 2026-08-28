import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import jwt



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
        print("Poynt token request failed:")
        print("  HTTP status:", response.status_code)
        print("  Response:", response.text)
        print("  Token URL:", poynt_token_url)
        print("  App ID:", poynt_app_id)
        print("  Redirect URI:", redirect_uri)
        print("  Grant type:", data["grant_type"])
        print("  Code present:", bool(code))
        print("  Self-signed JWT present:", bool(self_signed_jwt))
        print("  Self-signed JWT length:", len(self_signed_jwt))

        response.raise_for_status()

    return response.json()

async def get_catalogs(
    access_token: str,
    business_id: str,
) -> dict:
    url = (
        f"https://services.poynt.net"
        f"/businesses/{business_id}/catalogs"
    )

    headers = {
        "Accept": "application/json",
        "api-version": "1.2",
        "Authorization": f"Bearer {access_token}",
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            url,
            headers=headers,
        )

    print("Poynt catalog request:")
    print("  HTTP status:", response.status_code)
    print("  Business ID:", business_id)

    if not response.is_success:
        print("Poynt token request failed:")
        print("  HTTP status:", response.status_code)
        print("  Token URL:", poynt_token_url)
        print("  App ID:", poynt_app_id)
        print("  Redirect URI:", redirect_uri)
        print("  Grant type:", data["grant_type"])
        print("  Code present:", bool(code))
        print("  Self-signed JWT present:", bool(self_signed_jwt))
        print("  Self-signed JWT length:", len(self_signed_jwt))

        response.raise_for_status()

    return response.json()
import httpx

from poynt.connection import PoyntCredentials


class PoyntAPIError(Exception):
    """Raised when a Poynt API request fails."""


class PoyntClient:
    BASE_URL = "https://services.poynt.net"
    API_VERSION = "1.2"

    def __init__(self, credentials: PoyntCredentials):
        self.business_id = credentials.business_id
        self.access_token = credentials.access_token
        self.token_type = credentials.token_type or "BEARER"

    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "api-version": self.API_VERSION,
            "Authorization": f"{self.token_type} {self.access_token}",
        }

    async def get_catalogs(self) -> dict:
        url = (
            f"{self.BASE_URL}"
            f"/businesses/{self.business_id}/catalogs"
        )

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                url,
                headers=self._headers(),
            )

        if not response.is_success:
            raise PoyntAPIError(
                f"Poynt API returned HTTP {response.status_code}"
            )

        return response.json()
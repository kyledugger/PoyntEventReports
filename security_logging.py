import json
import logging
from typing import Any

from starlette.requests import Request


security_logger = logging.getLogger("security")


def _clean_text(value: str, max_length: int = 256) -> str:
    """Keep untrusted header values on one bounded log line."""
    return value.replace("\r", " ").replace("\n", " ")[:max_length]


def _request_ip(request: Request) -> tuple[str, str]:
    """Return the best available client IP plus the header source used."""
    cloudflare_ip = request.headers.get("cf-connecting-ip")
    if cloudflare_ip:
        return _clean_text(cloudflare_ip, 64), "cloudflare"

    if request.client:
        return _clean_text(request.client.host, 64), "peer"

    return "unknown", "unknown"


def log_security_event(
    request: Request,
    event: str,
    outcome: str,
    *,
    level: int = logging.INFO,
    user_id: int | None = None,
    organization_id: int | None = None,
    reason: str | None = None,
    **details: Any,
) -> None:
    """Write one structured event without credentials or secret URL values."""
    client_ip, ip_source = _request_ip(request)
    payload: dict[str, Any] = {
        "event": event,
        "outcome": outcome,
        "client_ip": client_ip,
        "ip_source": ip_source,
        "method": request.method,
        "user_agent": _clean_text(request.headers.get("user-agent", "unknown")),
    }

    if user_id is not None:
        payload["user_id"] = user_id
    if organization_id is not None:
        payload["organization_id"] = organization_id
    if reason is not None:
        payload["reason"] = reason

    for key, value in details.items():
        if value is not None:
            payload[key] = value

    security_logger.log(
        level,
        "SECURITY_EVENT %s",
        json.dumps(payload, separators=(",", ":"), sort_keys=True),
    )

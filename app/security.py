from fastapi import Header, HTTPException

from .config import settings


def require_bearer(authorization: str | None = Header(default=None)) -> None:
    expected = settings.inbound_bearer_token.strip()
    if not expected:
        return
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    incoming = authorization.replace("Bearer ", "", 1).strip()
    if incoming != expected:
        raise HTTPException(status_code=401, detail="Invalid bearer token")

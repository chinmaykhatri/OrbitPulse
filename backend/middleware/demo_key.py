"""X-Demo-Key authentication middleware.

Protects all POST and DELETE endpoints with a shared secret key.
GET endpoints are public (read-only data access).
The key is validated against DEMO_SECRET_KEY in the environment config.

This is a demo-appropriate authentication layer. Production deployments
would use OAuth2 or API key management instead.
"""
import logging

from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

logger = logging.getLogger("orbitpulse.middleware.demo_key")


class DemoKeyMiddleware(BaseHTTPMiddleware):
    """Validates X-Demo-Key header on mutating requests (POST/DELETE)."""

    def __init__(self, app, secret_key: str) -> None:
        super().__init__(app)
        self.secret_key = secret_key

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        if request.method in ("POST", "DELETE"):
            # Health check and WebSocket upgrade are always public
            if request.url.path in ("/api/health", "/ws/live"):
                return await call_next(request)

            key = request.headers.get("X-Demo-Key")
            if key != self.secret_key:
                logger.warning(
                    f"Rejected {request.method} {request.url.path} — "
                    f"invalid or missing X-Demo-Key"
                )
                raise HTTPException(
                    status_code=403,
                    detail="Invalid or missing X-Demo-Key header",
                )

        return await call_next(request)

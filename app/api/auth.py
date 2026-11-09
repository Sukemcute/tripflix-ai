"""Service tokens from core (TF058): only core-api may call the internal endpoints.

Same checks as core's own guard (libs/auth/src/service-token.ts): ES256 signature from core's
JWKS, issuer, audience, required sub/typ/iat/exp, and typ "service" so a user token never
passes. The token itself is never logged.
"""

from collections.abc import Callable, Sequence
from functools import cache
from typing import Annotated, Any

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import get_moderation_settings

SERVICE_TOKEN_TYPE = "service"
ALGORITHMS = ["ES256"]  # core signs with ES256 (libs/auth/src/verifier.ts)

_bearer = HTTPBearer(auto_error=False)


class InvalidServiceTokenError(Exception):
    pass


class ServiceNotAllowedError(Exception):
    pass


class ServiceTokenVerifier:
    def __init__(
        self,
        key_for: Callable[[str], Any],
        *,
        issuer: str,
        audience: str,
        callers: Sequence[str],
    ) -> None:
        self.key_for = key_for  # token -> verification key (JWKS lookup by kid)
        self.issuer = issuer
        self.audience = audience
        self.callers = frozenset(callers)

    def verify(self, token: str) -> str:
        """The calling service's client id, or an error."""
        try:
            claims = jwt.decode(
                token,
                self.key_for(token),
                algorithms=ALGORITHMS,
                audience=self.audience,
                issuer=self.issuer,
                options={"require": ["sub", "typ", "iat", "exp"]},
            )
        except jwt.PyJWKClientConnectionError:
            raise  # core's JWKS is down: not the caller's fault
        except jwt.PyJWTError as e:
            raise InvalidServiceTokenError(type(e).__name__) from e
        if claims["typ"] != SERVICE_TOKEN_TYPE:
            raise InvalidServiceTokenError("not a service token")
        if claims["sub"] not in self.callers:
            raise ServiceNotAllowedError(claims["sub"])
        return str(claims["sub"])


@cache
def get_service_verifier() -> ServiceTokenVerifier:
    settings = get_moderation_settings()
    jwks = jwt.PyJWKClient(settings.resolved_jwks_url)  # caches keys, refetches on a new kid
    return ServiceTokenVerifier(
        lambda token: jwks.get_signing_key_from_jwt(token).key,
        issuer=settings.auth_jwt_issuer,
        audience=settings.service_audience,
        callers=settings.moderation_callers,
    )


def require_core_caller(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    verifier: Annotated[ServiceTokenVerifier, Depends(get_service_verifier)],
) -> str:
    """Sync on purpose: the JWKS fetch blocks, so FastAPI runs it in its thread pool."""
    unauthorized = HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        "invalid or expired service token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None:
        raise unauthorized
    try:
        return verifier.verify(credentials.credentials)
    except InvalidServiceTokenError as e:
        raise unauthorized from e
    except ServiceNotAllowedError as e:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "service not allowed") from e
    except jwt.PyJWKClientConnectionError as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "cannot verify tokens") from e

"""Who is asking: the bearer token of a user or of a service, issued by Keycloak.

Every service checks the signature itself and does not take the gateway's
word (docs/CONTRACTS.md, 1.2). The application's roles are the client roles
`resource_access.<client>.roles`; `twin.admin` is the system administrator.
"""
from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass

import jwt
from fastapi import Depends, Request

from .errors import Problem

ADMIN_ROLE = "twin.admin"
current: ContextVar[Identity | None] = ContextVar("twin_identity", default=None)


@dataclass(frozen=True)
class Identity:
    kind: str                      # user | service
    sub: str
    login: str = ""
    name: str = ""
    email: str | None = None
    roles: tuple[str, ...] = ()

    @property
    def is_admin(self) -> bool:
        return ADMIN_ROLE in self.roles

    def actor(self) -> dict:
        """As it goes into an event."""
        return {"kind": self.kind, "id": self.sub}


class TokenVerifier:
    """Checks tokens against the realm's keys (fetched on first use and cached)
    or against the given public keys (tests)."""

    def __init__(self, issuer: str, internal: str, client_id: str, keys: dict[str, object] | None = None):
        self.issuer, self.client_id, self._keys = issuer, client_id, keys
        self._jwks = None if keys is not None else jwt.PyJWKClient(
            f"{internal}/protocol/openid-connect/certs", cache_keys=True, lifespan=600, timeout=5)

    def _key(self, token: str):
        if self._keys is not None:
            kid = jwt.get_unverified_header(token).get("kid")
            if kid not in self._keys:
                raise jwt.InvalidTokenError("unknown key")
            return self._keys[kid]
        return self._jwks.get_signing_key_from_jwt(token).key

    def claims(self, token: str) -> dict:
        try:
            return jwt.decode(token, self._key(token), algorithms=["RS256"], issuer=self.issuer,
                              options={"verify_aud": False, "require": ["exp", "iat", "sub"]}, leeway=10)
        except jwt.PyJWKClientConnectionError as ex:
            raise Problem(503, "auth_unavailable", "Сервис входа недоступен — проверить токен нельзя") from ex
        except jwt.PyJWTError as ex:
            raise Problem(401, "unauthenticated", "Токен недействителен или просрочен",
                          headers={"WWW-Authenticate": "Bearer"}) from ex

    def identity(self, token: str) -> Identity:
        c = self.claims(token)
        login = c.get("preferred_username", "")
        roles = tuple(c.get("resource_access", {}).get(self.client_id, {}).get("roles", ()))
        return Identity(kind="service" if login.startswith("service-account-") else "user", sub=c["sub"], login=login,
                        name=c.get("name") or login, email=c.get("email"), roles=roles)


def _verify(request: Request) -> Identity:
    # sync on purpose: fetching the realm's keys blocks, so FastAPI runs it in a worker thread
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise Problem(401, "unauthenticated", "Нужен токен: Authorization: Bearer …",
                      headers={"WWW-Authenticate": "Bearer"})
    return request.app.state.verifier.identity(token.strip())


async def current_identity(me: Identity = Depends(_verify)) -> Identity:
    """FastAPI dependency: the caller, or 401. Also remembered for the rest of
    the request (events take their actor from it)."""
    current.set(me)
    return me


def require_admin(me: Identity = Depends(current_identity)) -> Identity:
    if not me.is_admin:
        raise Problem(403, "forbidden", "Нужна роль администратора системы")
    return me

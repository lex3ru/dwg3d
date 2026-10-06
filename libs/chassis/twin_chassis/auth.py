"""Who is asking: the bearer token of a user or of a service, issued by Keycloak.

Every service checks the signature itself and does not take the gateway's
word (docs/CONTRACTS.md, 1.2). The application's roles are the client roles
`resource_access.<client>.roles`; `twin.admin` is the system administrator.

A guest — someone who opened a link to look at a building, a floor or a room —
carries a token of the access service (issuer `twin-access-guest`, keys at
TWIN_GUEST_JWKS): it names the area, and the guest may only look at it.
"""
from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass

import jwt
from fastapi import Depends, Request

from .errors import Problem

ADMIN_ROLE = "twin.admin"
GUEST_ISSUER = "twin-access-guest"
current: ContextVar[Identity | None] = ContextVar("twin_identity", default=None)


@dataclass(frozen=True)
class Identity:
    kind: str                      # user | service | guest
    sub: str
    login: str = ""
    name: str = ""
    email: str | None = None
    roles: tuple[str, ...] = ()
    # a guest's area: (scope kind, scope id, building id, floor id or "")
    guest: tuple[str, str, str, str] | None = None

    @property
    def is_admin(self) -> bool:
        return ADMIN_ROLE in self.roles

    def actor(self) -> dict:
        """As it goes into an event."""
        return {"kind": self.kind, "id": self.sub}


class TokenVerifier:
    """Checks tokens against the realm's keys (fetched on first use and cached)
    or against the given public keys (tests)."""

    def __init__(self, issuer: str, internal: str, client_id: str, keys: dict[str, object] | None = None,
                 guest_jwks: str | None = None, guest_keys: dict[str, object] | None = None):
        self.issuer, self.client_id, self._keys = issuer, client_id, keys
        self._jwks = None if keys is not None else jwt.PyJWKClient(
            f"{internal}/protocol/openid-connect/certs", cache_keys=True, lifespan=600, timeout=5)
        # guests: the access service's keys — fetched, given (tests) or trusted by the access service itself
        self._guest_keys = dict(guest_keys or {})
        self._guest_jwks = jwt.PyJWKClient(guest_jwks, cache_keys=True, lifespan=600, timeout=5) if guest_jwks else None

    def trust_guest_key(self, kid: str, key) -> None:
        self._guest_keys[kid] = key

    def _guest_key(self, token: str):
        kid = jwt.get_unverified_header(token).get("kid")
        if kid in self._guest_keys:
            return self._guest_keys[kid]
        if self._guest_jwks is None:
            raise jwt.InvalidTokenError("guests are not accepted here")
        return self._guest_jwks.get_signing_key_from_jwt(token).key

    def _key(self, token: str):
        if self._keys is not None:
            kid = jwt.get_unverified_header(token).get("kid")
            if kid not in self._keys:
                raise jwt.InvalidTokenError("unknown key")
            return self._keys[kid]
        return self._jwks.get_signing_key_from_jwt(token).key

    def claims(self, token: str) -> dict:
        try:
            if self._issuer_of(token) == GUEST_ISSUER:
                return jwt.decode(token, self._guest_key(token), algorithms=["RS256"], issuer=GUEST_ISSUER,
                                  options={"verify_aud": False, "require": ["exp", "iat", "sub"]}, leeway=10)
            return jwt.decode(token, self._key(token), algorithms=["RS256"], issuer=self.issuer,
                              options={"verify_aud": False, "require": ["exp", "iat", "sub"]}, leeway=10)
        except jwt.PyJWKClientConnectionError as ex:
            raise Problem(503, "auth_unavailable", "Сервис входа недоступен — проверить токен нельзя") from ex
        except jwt.PyJWTError as ex:
            raise Problem(401, "unauthenticated", "Токен недействителен или просрочен",
                          headers={"WWW-Authenticate": "Bearer"}) from ex

    @staticmethod
    def _issuer_of(token: str) -> str | None:
        try:
            return jwt.decode(token, options={"verify_signature": False}).get("iss")
        except jwt.PyJWTError:
            return None

    def identity(self, token: str) -> Identity:
        c = self.claims(token)
        if c.get("iss") == GUEST_ISSUER:
            area = c.get("area") or {}
            return Identity(kind="guest", sub=c["sub"], login="guest", name="Гость",
                            guest=(area.get("kind", ""), area.get("id", ""), c.get("building_id", ""),
                                   c.get("floor_id") or ""))
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


def require_admin_or_service(me: Identity = Depends(current_identity)) -> Identity:
    """For requests other services make too (marked «служебный» in the contracts)."""
    if not me.is_admin and me.kind != "service":
        raise Problem(403, "forbidden", "Нужна роль администратора системы")
    return me


def forbid_guests(me: Identity = Depends(current_identity)) -> Identity:
    """For whatever a guest by a link has no business with: people, history, files, the journal…"""
    if me.kind == "guest":
        raise Problem(403, "guest", "Гостю по ссылке это недоступно")
    return me


def require_service(me: Identity = Depends(current_identity)) -> Identity:
    if me.kind != "service":
        raise Problem(403, "forbidden", "Запрос только для сервисов")
    return me


def require_admin(me: Identity = Depends(current_identity)) -> Identity:
    if not me.is_admin:
        raise Problem(403, "forbidden", "Нужна роль администратора системы")
    return me

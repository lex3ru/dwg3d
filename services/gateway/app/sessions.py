"""Sign-in sessions: a random cookie in the browser, the Keycloak tokens here.

A request arrives with the cookie; services receive the user's access token,
refreshed here when it is about to expire.

A guest — someone who opened a link (/s/<token>) — gets a session of their own
under another cookie: here the link and the guest token of the access service,
renewed by the link while it is good. The guest cookie wins over the user's one:
opening a link means looking as a guest.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx
from cryptography.fernet import Fernet, InvalidToken
from fastapi import Depends, Request, Response
from sqlalchemy import delete, insert, select, update
from twin_chassis import Database, Identity, Problem
from twin_chassis.auth import TokenVerifier, current

from .config import GatewayConfig
from .models import guest_sessions, sessions
from .oidc import Oidc, SignInFailed

COOKIE = "twin_session"
GUEST_COOKIE = "twin_guest"
REFRESH_BEFORE = timedelta(seconds=30)
RENEW_BEFORE = timedelta(seconds=60)
TOUCH_EVERY = timedelta(minutes=5)
GUEST_ENDED = "Просмотр по ссылке закончился: ссылка отозвана или истекла"
GUEST_REFUSED = "Гостю по ссылке это недоступно"


@dataclass(frozen=True)
class Signed:
    """Who is asking and the token to pass on to services."""
    identity: Identity
    token: str
    by_cookie: bool
    until: datetime | None = None      # a guest by a link: until when the link is good


class LinkAway(Exception):
    """The access service did not answer about a link."""


def _digest(cookie: str) -> str:
    return hashlib.sha256(cookie.encode()).hexdigest()


class Sessions:
    def __init__(self, db: Database, config: GatewayConfig, oidc: Oidc, verifier: TokenVerifier,
                 http: httpx.AsyncClient):
        self.db, self.config, self.oidc, self.verifier, self.http = db, config, oidc, verifier, http
        self._box = Fernet(base64.urlsafe_b64encode(hashlib.sha256(config.secret.encode()).digest()))

    def _seal(self, token: str | None) -> str | None:
        return self._box.encrypt(token.encode()).decode() if token else None

    def _open(self, sealed: str | None) -> str | None:
        try:
            return self._box.decrypt(sealed.encode()).decode() if sealed else None
        except InvalidToken:
            return None                 # TWIN_SECRET has changed: the session is useless

    def _tokens(self, tokens: dict) -> dict:
        claims = self.verifier.claims(tokens["access_token"])
        return {"access_token": self._seal(tokens["access_token"]),
                "refresh_token": self._seal(tokens.get("refresh_token")),
                "access_expires_at": datetime.fromtimestamp(claims["exp"], UTC)}

    # --------------------------------------------------------------- cookie ---
    def set_cookie(self, response: Response, cookie: str) -> None:
        response.set_cookie(COOKIE, cookie, max_age=int(self.config.session_days * 86400), httponly=True,
                            secure=self.config.secure, samesite="lax", path="/")

    def clear_cookie(self, response: Response) -> None:
        response.delete_cookie(COOKIE, path="/", httponly=True, secure=self.config.secure, samesite="lax")

    def set_guest_cookie(self, response: Response, cookie: str, until: datetime) -> None:
        response.set_cookie(GUEST_COOKIE, cookie, max_age=max(0, int((until - datetime.now(UTC)).total_seconds())),
                            httponly=True, secure=self.config.secure, samesite="lax", path="/")

    def clear_guest_cookie(self, response: Response) -> None:
        response.delete_cookie(GUEST_COOKIE, path="/", httponly=True, secure=self.config.secure, samesite="lax")

    def guest_ended(self) -> Problem:
        """401 for a guest whose look is over; the browser forgets the guest cookie with it."""
        gone = Response()
        self.clear_guest_cookie(gone)
        return Problem(401, "guest_ended", GUEST_ENDED, headers={"set-cookie": gone.headers["set-cookie"]})

    # ------------------------------------------------------------- lifecycle ---
    async def create(self, tokens: dict, user_agent: str) -> str:
        me = await asyncio.to_thread(self.verifier.identity, tokens["access_token"])
        cookie = secrets.token_urlsafe(32)
        async with self.db.begin() as session:
            await session.execute(insert(sessions).values(
                token_hash=_digest(cookie), user_sub=me.sub, login=me.login, name=me.name, email=me.email,
                roles=list(me.roles), id_token=self._seal(tokens.get("id_token")), user_agent=user_agent[:300],
                **self._tokens(tokens)))
        return cookie

    async def end(self, cookie: str | None) -> str | None:
        """Forget the session; returns its id token (for signing out of Keycloak too)."""
        if not cookie:
            return None
        async with self.db.begin() as session:
            sealed = (await session.execute(delete(sessions).where(sessions.c.token_hash == _digest(cookie))
                                            .returning(sessions.c.id_token))).scalar_one_or_none()
        return self._open(sealed)

    async def resolve(self, cookie: str | None) -> Signed | None:
        """The session of the cookie with a token that is still good, or None."""
        if not cookie:
            return None
        key, now = _digest(cookie), datetime.now(UTC)
        async with self.db.begin() as session:
            row = (await session.execute(select(sessions).where(sessions.c.token_hash == key))).one_or_none()
            if row is None or row.last_seen_at < now - timedelta(days=self.config.session_days):
                return None
            if row.access_expires_at - now > REFRESH_BEFORE:
                if now - row.last_seen_at > TOUCH_EVERY:
                    await session.execute(update(sessions).where(sessions.c.token_hash == key).values(last_seen_at=now))
                token = self._open(row.access_token)
                return self._signed(row, token) if token else None
        return await self._refresh(key)

    async def _refresh(self, key: str) -> Signed | None:
        now = datetime.now(UTC)
        async with self.db.begin() as session:
            # one request refreshes; the others wait on the row and find the new token
            locked = select(sessions).where(sessions.c.token_hash == key).with_for_update()
            row = (await session.execute(locked)).one_or_none()
            if row is None:
                return None
            if row.access_expires_at - now > REFRESH_BEFORE:
                token = self._open(row.access_token)
                return self._signed(row, token) if token else None
            refresh_token = self._open(row.refresh_token)
            try:
                if not refresh_token:
                    raise SignInFailed("no refresh token")
                tokens = await self.oidc.refresh(refresh_token)
                me = await asyncio.to_thread(self.verifier.identity, tokens["access_token"])
            except (SignInFailed, Problem) as ex:
                if isinstance(ex, Problem) and ex.status == 503:
                    raise
                await session.execute(delete(sessions).where(sessions.c.token_hash == key))
                return None
            await session.execute(update(sessions).where(sessions.c.token_hash == key).values(
                login=me.login, name=me.name, email=me.email, roles=list(me.roles), last_seen_at=now,
                **self._tokens(tokens)))
            return Signed(me, tokens["access_token"], by_cookie=True)

    @staticmethod
    def _signed(row, token: str) -> Signed:
        me = Identity(kind="user", sub=row.user_sub, login=row.login, name=row.name, email=row.email,
                      roles=tuple(row.roles))
        return Signed(me, token, by_cookie=True)

    # ------------------------------------------------------ guests by a link ---
    async def _open_link(self, link: str, *, renew: bool, address: str | None = None) -> dict | None:
        """The access service's answer to a link: a guest token on its area, or None — the link opens nothing."""
        base = self.config.services.get("access")
        if base is None:
            raise LinkAway("no access service")
        try:
            r = await self.http.post(f"{base}/api/access/v1/shares/open", timeout=10,
                                     json={"token": link, "renew": renew, "address": address})
        except httpx.HTTPError as ex:
            raise LinkAway(str(ex)) from ex
        if r.status_code >= 500:
            raise LinkAway(f"access answered {r.status_code}")
        return r.json() if r.status_code == 200 else None

    def _guest_token(self, opened: dict, now: datetime) -> dict:
        return {"access_token": self._seal(opened["token"]),
                "access_expires_at": now + timedelta(seconds=opened["expires_in"]),
                "link_expires_at": datetime.fromisoformat(opened["expires_at"])}

    async def create_guest(self, link: str, address: str | None, user_agent: str) -> tuple[str, datetime] | None:
        """A guest session by the link: (the cookie, until when the link is good), or None — the link is no good.
        Raises LinkAway when the access service does not answer."""
        opened = await self._open_link(link, renew=False, address=address)
        if opened is None:
            return None
        me = await asyncio.to_thread(self.verifier.identity, opened["token"])
        kind, scope_id, building_id, floor_id = me.guest
        cookie, now = secrets.token_urlsafe(32), datetime.now(UTC)
        values = self._guest_token(opened, now)
        async with self.db.begin() as session:
            # the looks whose links have run out are of no use to anyone
            await session.execute(delete(guest_sessions).where(guest_sessions.c.link_expires_at <= now))
            await session.execute(insert(guest_sessions).values(
                token_hash=_digest(cookie), link=self._seal(link), guest_sub=me.sub, building_id=building_id,
                scope_kind=kind, scope_id=scope_id, floor_id=floor_id or None, user_agent=user_agent[:300], **values))
        return cookie, values["link_expires_at"]

    async def end_guest(self, cookie: str | None) -> None:
        if cookie:
            async with self.db.begin() as session:
                await session.execute(delete(guest_sessions).where(guest_sessions.c.token_hash == _digest(cookie)))

    async def resolve_guest(self, cookie: str) -> Signed | None:
        """The guest session of the cookie with a token that is still good, or None — the look is over."""
        key, now = _digest(cookie), datetime.now(UTC)
        async with self.db.begin() as session:
            found = select(guest_sessions).where(guest_sessions.c.token_hash == key)
            row = (await session.execute(found)).one_or_none()
        if row is None or row.link_expires_at <= now:
            await self.end_guest(cookie)
            return None
        if row.access_expires_at - now > RENEW_BEFORE:
            token = self._open(row.access_token)
            return self._guest(row, token) if token else None
        return await self._renew(key)

    async def _renew(self, key: str) -> Signed | None:
        now = datetime.now(UTC)
        async with self.db.begin() as session:
            # one request renews; the others wait on the row and find the new token
            locked = select(guest_sessions).where(guest_sessions.c.token_hash == key).with_for_update()
            row = (await session.execute(locked)).one_or_none()
            if row is None:
                return None
            if row.access_expires_at - now > RENEW_BEFORE:
                token = self._open(row.access_token)
                return self._guest(row, token) if token else None
            link = self._open(row.link)
            try:
                opened = await self._open_link(link, renew=True) if link else None
            except LinkAway as ex:
                token = self._open(row.access_token)
                if token and row.access_expires_at > now:
                    return self._guest(row, token)          # the access service is away: the token is still good
                raise Problem(503, "service_unavailable", "Сервис «access» недоступен",
                              extra={"service": "access"}) from ex
            if opened is None:                              # revoked or expired while the guest was looking
                await session.execute(delete(guest_sessions).where(guest_sessions.c.token_hash == key))
                return None
            values = self._guest_token(opened, now)
            row = (await session.execute(update(guest_sessions).where(guest_sessions.c.token_hash == key)
                                         .values(**values).returning(guest_sessions))).one()
            return self._guest(row, opened["token"])

    @staticmethod
    def _guest(row, token: str) -> Signed:
        me = Identity(kind="guest", sub=row.guest_sub, login="guest", name="Гость",
                      guest=(row.scope_kind, row.scope_id, row.building_id, row.floor_id or ""))
        return Signed(me, token, by_cookie=True, until=row.link_expires_at)


async def signed(request: Request) -> Signed:
    """FastAPI dependency: who is asking — by the session cookie (the guest one first), or by
    a bearer token of their own (programs calling the API directly) — or 401."""
    app = request.app
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() == "bearer" and token:
        identity = await asyncio.to_thread(app.state.verifier.identity, token.strip())
        me = Signed(identity, token.strip(), by_cookie=False)
    elif GUEST_COOKIE in request.cookies:
        me = await app.state.sessions.resolve_guest(request.cookies[GUEST_COOKIE])
        if me is None:
            raise app.state.sessions.guest_ended()
    else:
        me = await app.state.sessions.resolve(request.cookies.get(COOKIE))
        if me is None:
            raise Problem(401, "unauthenticated", "Требуется вход")
    current.set(me.identity)
    return me


async def not_guest(who: Signed = Depends(signed)) -> Signed:
    """FastAPI dependency: what the gateway gathers itself beyond a guest's area — the cabinet, reports,
    the status of the system, the events — is not for a guest by a link."""
    if who.identity.kind == "guest":
        raise Problem(403, "guest", GUEST_REFUSED)
    return who

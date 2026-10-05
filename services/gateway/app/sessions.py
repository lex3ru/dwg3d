"""Sign-in sessions: a random cookie in the browser, the Keycloak tokens here.

A request arrives with the cookie; services receive the user's access token,
refreshed here when it is about to expire.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from cryptography.fernet import Fernet, InvalidToken
from fastapi import Request, Response
from sqlalchemy import delete, insert, select, update
from twin_chassis import Database, Identity, Problem
from twin_chassis.auth import TokenVerifier, current

from .config import GatewayConfig
from .models import sessions
from .oidc import Oidc, SignInFailed

COOKIE = "twin_session"
REFRESH_BEFORE = timedelta(seconds=30)
TOUCH_EVERY = timedelta(minutes=5)


@dataclass(frozen=True)
class Signed:
    """Who is asking and the token to pass on to services."""
    identity: Identity
    token: str
    by_cookie: bool


def _digest(cookie: str) -> str:
    return hashlib.sha256(cookie.encode()).hexdigest()


class Sessions:
    def __init__(self, db: Database, config: GatewayConfig, oidc: Oidc, verifier: TokenVerifier):
        self.db, self.config, self.oidc, self.verifier = db, config, oidc, verifier
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


async def signed(request: Request) -> Signed:
    """FastAPI dependency: who is asking — by the session cookie, or by a
    bearer token of their own (programs calling the API directly) — or 401."""
    app = request.app
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() == "bearer" and token:
        identity = await asyncio.to_thread(app.state.verifier.identity, token.strip())
        me = Signed(identity, token.strip(), by_cookie=False)
    else:
        me = await app.state.sessions.resolve(request.cookies.get(COOKIE))
        if me is None:
            raise Problem(401, "unauthenticated", "Требуется вход")
    current.set(me.identity)
    return me

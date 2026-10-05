"""For the tests of a service: a scratch database, signed tokens, its own corner of NATS.

PostgreSQL and NATS are infrastructure, not neighbours — tests use real ones
(the dev stack: `docker compose -f deploy/docker-compose.yml up -d db nats`):

  TWIN_TEST_DATABASE_URL   a superuser connection (default: the dev stack's)
  TWIN_TEST_NATS_URL       default: the dev stack's

Other services are never needed: a service's tests replace them with stubs.
"""
from __future__ import annotations

import json
import os
import secrets
import time
from collections.abc import Iterator
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path

import jwt
import sqlalchemy as sa
from cryptography.hazmat.primitives.asymmetric import rsa

from .auth import TokenVerifier
from .migrate import upgrade
from .settings import Settings, find_contracts

ADMIN_URL = os.environ.get("TWIN_TEST_DATABASE_URL", "postgresql+psycopg://twin:twin@127.0.0.1:5433/postgres")
NATS_URL = os.environ.get("TWIN_TEST_NATS_URL", "nats://127.0.0.1:4223")
ISSUER = "http://keycloak.test/kc/realms/twin"
CLIENT_ID = "twin"


@contextmanager
def scratch_database(migrations: Path | str | None = "migrations") -> Iterator[str]:
    """A new empty database with the service's migrations applied; dropped afterwards."""
    name = f"test_{secrets.token_hex(6)}"
    admin = sa.create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT", poolclass=sa.pool.NullPool)
    with admin.connect() as c:
        c.execute(sa.text(f'CREATE DATABASE "{name}"'))
    url = sa.make_url(ADMIN_URL).set(database=name).render_as_string(hide_password=False)
    try:
        if migrations is not None:
            upgrade(url, migrations)
        yield url
    finally:
        with admin.connect() as c:
            c.execute(sa.text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


def test_settings(service: str, database_url: str, *, nats_url: str = NATS_URL) -> Settings:
    """Settings of a service under test: its scratch database and a bus prefix of its own."""
    return Settings(service=service, database_url=database_url, nats_url=nats_url, oidc_issuer=ISSUER,
                    oidc_internal=ISSUER, oidc_client_id=CLIENT_ID, contracts=find_contracts(),
                    bus_prefix=f"test{secrets.token_hex(4)}")


test_settings.__test__ = False      # not a test, despite the name


@asynccontextmanager
async def running(app):
    """The app started (bus tasks running) for the time of a test; its test stream is removed afterwards."""
    async with app.router.lifespan_context(app):
        try:
            yield app
        finally:
            bus = app.state.bus
            if bus.connected:
                try:
                    await bus.js.delete_stream(bus.stream)
                except Exception:
                    pass


class Tokens:
    """Signs tokens the way Keycloak would; `verifier()` accepts exactly these."""

    def __init__(self):
        self._key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.kid = "test-key"

    def verifier(self) -> TokenVerifier:
        return TokenVerifier(ISSUER, ISSUER, CLIENT_ID, keys={self.kid: self._key.public_key()})

    def make(self, sub: str = "user-1", *, roles: tuple[str, ...] = (), login: str = "ivanov",
             name: str = "Иван Иванов", email: str | None = "ivanov@example.test", service: bool = False,
             expires_in: int = 300, **claims) -> str:
        now = int(time.time())
        payload = {"iss": ISSUER, "sub": sub, "iat": now, "exp": now + expires_in,
                   "preferred_username": f"service-account-{login}" if service else login, "name": name,
                   "resource_access": {CLIENT_ID: {"roles": list(roles)}}, **claims}
        if email and not service:
            payload["email"] = email
        return jwt.encode(payload, self._key, algorithm="RS256", headers={"kid": self.kid})

    def bearer(self, sub: str = "user-1", **kw) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.make(sub, **kw)}"}

    def admin(self, sub: str = "admin-1") -> dict[str, str]:
        return self.bearer(sub, roles=("twin.admin",), login="admin", name="Администратор")


def openapi_text(app) -> str:
    """The service's OpenAPI as it is stored in contracts/openapi/."""
    return json.dumps(app.openapi(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def assert_contract(app, service: str) -> None:
    """The requests the service really has are the ones in contracts/openapi/<service>.v1.json.
    To change the contract on purpose:  python -m twin_chassis.contracts <service>"""
    path = find_contracts() / "openapi" / f"{service}.v1.json"
    assert path.is_file(), f"Нет контракта {path} — создайте: python -m twin_chassis.contracts {service}"
    assert path.read_text(encoding="utf-8") == openapi_text(app), (
        f"Запросы сервиса разошлись с {path.name}. "
        f"Если изменение намеренное: python -m twin_chassis.contracts {service}")

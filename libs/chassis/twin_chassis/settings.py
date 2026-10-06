"""Where things are: read once from the environment.

  TWIN_DATABASE_URL   the service's own database (postgresql+psycopg://...)
  TWIN_NATS_URL       the event bus (default nats://127.0.0.1:4223, the dev stack)
  TWIN_OIDC_ISSUER    Keycloak realm as users see it — the `iss` of tokens
  TWIN_OIDC_INTERNAL  the same realm as this service reaches it (default: the issuer)
  TWIN_OIDC_CLIENT_ID the client whose roles are the application's roles (default twin)
  TWIN_SERVICE_SECRET the secret of this service's own Keycloak client twin-svc-<service>, for calling other services
  TWIN_BUS_PREFIX     first part of event subjects and the stream's name (default twin; tests use their own)
  TWIN_CONTRACTS      the contracts/ directory (default: found above the working directory)
  TWIN_PUBLIC_URL     the address users open (default http://localhost:8090): links the services write, e.g. in QR codes
  TWIN_GUEST_JWKS     the keys of guest tokens (the access service's); unset — guests are not accepted
"""
from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path

DEV_ISSUER = "http://localhost:8090/kc/realms/twin"


def find_contracts(start: Path | None = None) -> Path:
    here = (start or Path.cwd()).resolve()
    for d in (here, *here.parents):
        if (d / "contracts" / "events" / "envelope.json").is_file():
            return d / "contracts"
    raise RuntimeError("Не найден каталог contracts/ — задайте TWIN_CONTRACTS")


@dataclass(frozen=True)
class Settings:
    service: str
    database_url: str
    nats_url: str
    oidc_issuer: str
    oidc_internal: str
    oidc_client_id: str
    contracts: Path
    bus_prefix: str = "twin"
    service_secret: str | None = None
    public_url: str = "http://localhost:8090"
    guest_jwks: str | None = None

    @classmethod
    def from_env(cls, service: str, **overrides) -> Settings:
        env = os.environ
        issuer = env.get("TWIN_OIDC_ISSUER", DEV_ISSUER).rstrip("/")
        s = cls(
            service=service,
            database_url=env.get("TWIN_DATABASE_URL", f"postgresql+psycopg://{service}:{service}@127.0.0.1:5433/{service}"),
            nats_url=env.get("TWIN_NATS_URL", "nats://127.0.0.1:4223"),
            oidc_issuer=issuer,
            oidc_internal=(env.get("TWIN_OIDC_INTERNAL") or issuer).rstrip("/"),
            oidc_client_id=env.get("TWIN_OIDC_CLIENT_ID", "twin"),
            contracts=Path(env["TWIN_CONTRACTS"]) if env.get("TWIN_CONTRACTS") else find_contracts(),
            bus_prefix=env.get("TWIN_BUS_PREFIX", "twin"),
            service_secret=env.get("TWIN_SERVICE_SECRET") or None,
            public_url=env.get("TWIN_PUBLIC_URL", cls.public_url).rstrip("/"),
            guest_jwks=env.get("TWIN_GUEST_JWKS") or None,
        )
        return replace(s, **overrides)

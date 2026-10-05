"""What the gateway needs beyond the common settings.

  TWIN_PUBLIC_URL          the address users open; sign-in returns to it
  TWIN_OIDC_CLIENT_SECRET  the secret of the Keycloak client
  TWIN_SECRET              signs the sign-in state, encrypts stored tokens
  TWIN_SERVICES            where requests go: "ping=http://ping:8000,assets=http://assets:8000"
  TWIN_SESSION_DAYS        how long a session lives without use (default 14)
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class GatewayConfig:
    public_url: str = "http://localhost:8090"
    client_secret: str = "dev-client-secret"
    secret: str = "dev-secret-change-me"
    services: dict[str, str] = field(default_factory=dict)
    session_days: float = 14

    @classmethod
    def from_env(cls) -> GatewayConfig:
        env = os.environ
        services = dict(pair.strip().split("=", 1) for pair in env.get("TWIN_SERVICES", "").split(",") if "=" in pair)
        return cls(
            public_url=env.get("TWIN_PUBLIC_URL", cls.public_url).rstrip("/"),
            client_secret=env.get("TWIN_OIDC_CLIENT_SECRET", cls.client_secret),
            secret=env.get("TWIN_SECRET", cls.secret),
            services={name: url.rstrip("/") for name, url in services.items()},
            session_days=float(env.get("TWIN_SESSION_DAYS", "14")),
        )

    @property
    def secure(self) -> bool:
        return self.public_url.startswith("https://")

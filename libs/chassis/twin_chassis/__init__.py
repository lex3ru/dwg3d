"""The chassis of a digital twin service.

A service is `create_app("name", routers=[...])` plus its own tables and
handlers; everything the services must do the same way lives here:

  settings   where the database, NATS and Keycloak are (environment)
  auth       who is asking: the Keycloak token of a user or a service
  errors     application/problem+json for every failure
  db         the service's own database and the outbox / inbox tables
  events     the event envelope, checked against contracts/events/
  bus        publishing the outbox to NATS JetStream, consuming with dedup
  log        JSON log lines carrying the request id
  access     rights by area: the caller's scopes from the access service, decided locally
  client     calling another service, with the user's token or the service's own
  files      the service's bucket in S3-compatible storage
  migrate    the service's Alembic migrations, run at start
  testing    fixtures: a scratch database, signed test tokens

The rules behind it are in docs/CONTRACTS.md, section 1.
"""
from .app import create_app
from .auth import Identity, current_identity, forbid_guests, require_admin, require_admin_or_service, require_service
from .db import Database, metadata, uuid7
from .errors import Problem
from .events import emit
from .settings import Settings

__all__ = ["Database", "Identity", "Problem", "Settings", "create_app", "current_identity", "emit",
           "forbid_guests", "metadata", "require_admin", "require_admin_or_service", "require_service", "uuid7"]

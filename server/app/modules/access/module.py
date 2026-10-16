from fastapi import FastAPI

from app.core import auth
from app.core.module import Module
from app.modules.access import api
from app.modules.access.routes import auth as auth_router
from app.modules.access.routes import share as share_router
from app.modules.access.routes import users as users_router


def _setup(app: FastAPI) -> None:
    # действующего определяет сеанс входа — для всех модулей (app.core.auth)
    app.dependency_overrides[auth.current_actor] = api.resolve_actor


module = Module(name="access", title="Доступ", routers=[auth_router, users_router, share_router],
                setup=_setup)

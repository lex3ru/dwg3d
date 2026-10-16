"""Кто делает запрос — для всех модулей.

Модули берут действующего через `Depends(current_actor)` или `Depends(admin)` и не знают,
как устроен вход. Настоящую проверку сеанса подставляет модуль доступа при сборке
приложения (app/main.py); так вход можно сменить или дополнить (Keycloak, 2.4), не трогая
модули.
"""

from typing import Annotated

from fastapi import Depends

from app.core.actor import Actor
from app.core.errors import Forbidden


def current_actor() -> Actor:  # подменяется модулем доступа
    raise NotImplementedError("модуль доступа не подключён")


def admin(actor: Annotated[Actor, Depends(current_actor)]) -> Actor:
    if not actor.is_admin:
        raise Forbidden()
    return actor


def member(actor: Annotated[Actor, Depends(current_actor)]) -> Actor:
    """Учётная запись: администратор или «просмотр». Гостю по ссылке — нельзя: ему открыто
    только то, что объявлено через AnyActor (план и 3D здания, 5.7.2)."""
    if actor.is_guest:
        raise Forbidden()
    return actor


CurrentActor = Annotated[Actor, Depends(member)]
# и гость по ссылке на просмотр — только план, расстановка, каталог для рисования, файлы
AnyActor = Annotated[Actor, Depends(current_actor)]
Admin = Annotated[Actor, Depends(admin)]

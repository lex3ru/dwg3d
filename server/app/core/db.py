"""База данных: одно подключение на приложение, одна транзакция на запрос.

Каждый модуль держит свои таблицы в своей схеме PostgreSQL (схема = имя модуля);
служебные таблицы ядра — в схеме core. Транзакция запроса общая для всех модулей,
поэтому операция, задевающая несколько модулей, выполняется целиком или никак (9.2 п. 2).
"""

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from sqlalchemy import Engine, MetaData, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import config

NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


OUTSIDE_QUEUE = 2
# прочие клиенты базы: обработчик фоновых задач (слушатель очереди, свой пул и по процессу
# задачи в каждой из двух полос — до 7), резервная копия, psql администратора
OTHERS = 10


def connections_needed(workers: int) -> int:
    """Соединений с базой установке под пиком: у каждого из workers процессов приложения —
    пул очереди, запас сокетам и слушатель изменений (R-036, ADR-0020), и прочие клиенты."""
    return workers * (config().db_pool + OUTSIDE_QUEUE + 1) + OTHERS


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


@lru_cache
def engine() -> Engine:
    # пул — столько же, сколько запросов пускает очередь процесса (core/admission.py), и
    # OUTSIDE_QUEUE сверх: сокеты изменений проверяют сеанс мимо очереди и под пиком не
    # должны ждать, пока освободится соединение запроса (R-036, ADR-0020)
    return create_engine(config().database_url, pool_pre_ping=True,
                         pool_size=config().db_pool, max_overflow=OUTSIDE_QUEUE)


@lru_cache
def _factory() -> sessionmaker[Session]:
    return sessionmaker(engine(), expire_on_commit=False)


@contextmanager
def transaction() -> Iterator[Session]:
    """Сессия в транзакции: фиксируется при выходе, откатывается при исключении."""
    session = _factory()()
    try:
        with session.begin():
            yield session
    finally:
        session.close()


def get_session() -> Iterator[Session]:
    """Зависимость FastAPI: транзакция на весь запрос."""
    with transaction() as session:
        yield session


# транзакция фиксируется до отправки ответа (scope="function"): если фиксация не удалась,
# человек получит ошибку, а не «сохранено»
DB = Annotated[Session, Depends(get_session, scope="function")]

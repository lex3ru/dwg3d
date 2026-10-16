"""Описание модуля для сборки приложения."""

from collections.abc import Callable
from dataclasses import dataclass, field

from fastapi import APIRouter, FastAPI


@dataclass(frozen=True)
class Module:
    name: str
    title: str
    routers: list[APIRouter] = field(default_factory=list)
    # вызывается при сборке приложения: подставить зависимости, зарегистрировать
    # источники поиска и т. п.
    setup: Callable[[FastAPI], None] | None = None

"""Все таблицы приложения — для миграций и тестов."""

import importlib

from app.modules import INSTALLED


def load_all() -> None:
    importlib.import_module("app.core.tasks")
    for name in INSTALLED:
        try:
            importlib.import_module(f"app.modules.{name}.models")
        except ModuleNotFoundError as e:
            if e.name != f"app.modules.{name}.models":
                raise

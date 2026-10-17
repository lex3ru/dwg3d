"""Настройки установки — из переменных окружения APP_* (deploy/.env)."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="APP_", env_file=None)

    database_url: str = "postgresql+psycopg://app:app@localhost:55432/app"
    # файлы системы (фото, чертежи, 3D-модели) — 9.4 п. 3
    data_dir: Path = Path("/data")
    # куда сервис резервного копирования кладёт копии и last.json — 8.5 п. 4
    backup_dir: Path = Path("/backups")
    # собранный интерфейс; если каталога нет, сервер отдаёт только /api
    static_dir: Path = Path("/app/web")
    # cookie сеанса только по HTTPS; в тестах и при разработке без Caddy — false
    secure_cookies: bool = True
    # сеанс завершается после стольких часов бездействия — 8.4 п. 2
    session_idle_hours: int = 12
    log_level: str = "INFO"
    # процессов приложения: тяжёлый запрос (отчёт, выгрузка) не задерживает остальных —
    # по числу ядер сервера (8.2: 4 ядра)
    workers: int = 4


@lru_cache
def config() -> Config:
    return Config()

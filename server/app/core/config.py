"""Настройки установки — из переменных окружения APP_* (deploy/.env)."""

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="APP_", env_file=None)

    analytics_preview_port: int = 8769
    analytics_token: SecretStr = SecretStr("")

    database_url: str = "postgresql+psycopg://app:app@127.0.0.1:55432/app"
    # файлы системы (фото, чертежи, 3D-модели) — 9.4 п. 3
    data_dir: Path = Path("/data")
    # куда сервис резервного копирования кладёт копии и last.json — 8.5 п. 4
    backup_dir: Path = Path("/backups")
    # собранный интерфейс; если каталога нет, сервер отдаёт только /api
    static_dir: Path = Path("/app/web")
    # cookie сеанса только по HTTPS; в тестах и при разработке без Caddy — false
    secure_cookies: bool = True
    # адрес системы из установки (PUBLIC_URL в deploy/.env, его пишет install.sh): по умолчанию
    # на него ведут QR-метки (5.4.7, R-016); пусто — при разработке
    public_url: str = ""
    # сеанс завершается после стольких часов бездействия — 8.4 п. 2
    session_idle_hours: int = 12
    log_level: str = "INFO"
    # процессов приложения: тяжёлый запрос (отчёт, выгрузка) не задерживает остальных —
    # по числу ядер сервера (8.2: 4 ядра)
    workers: int = 4
    # запросов, которые процесс приложения обслуживает одновременно, остальные ждут очереди, —
    # и столько же соединений в его пуле (R-036, ADR-0020); у процесса ещё 2 соединения
    # сокетам изменений и 1 — слушателю изменений. Всего — db.connections_needed, в пределах
    # max_connections PostgreSQL (deploy/compose.yml)
    db_pool: int = 10
    # память LibreDWG (dwg2dxf) при чтении DWG, МБ: файлы приходят от подрядчиков (R-017)
    dwg2dxf_memory_mb: int = 4096
    # память процесса фоновой задачи сверх занятого обработчиком, МБ (Linux): кривой чертёж за
    # минуту съедает десятки ГБ, а на сервере и база; задач одновременно две — по полосе
    # (ADR-0011)
    task_memory_mb: int = 4096


@lru_cache
def config() -> Config:
    return Config()

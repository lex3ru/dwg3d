# Локальный стенд Frigate

Запуск: `docker compose -f deploy/frigate/compose.yml up -d`.
Интерфейс: http://localhost:5000 — только на этом компьютере.
Порт 5000 — внутренний интерфейс без авторизации, поэтому он привязан строго к loopback.
Для удалённого доступа нужно отдельно настроить авторизованный интерфейс 8971.

Конфигурация и БД находятся в `config/` (исключены из Git), медиа — в Docker volume.
Начальная конфигурация `config/config.yml`:

```yaml
mqtt:
  enabled: false
cameras: {}
detect:
  enabled: false
```

Камеры пока не подключены. Перед использованием аналитики настроить источник,
детектор и включить detect. Стенд пока не связан с приложением планировки.
Остановка с сохранением данных: `docker compose -f deploy/frigate/compose.yml down`.
Документация: https://docs.frigate.video/frigate/installation/

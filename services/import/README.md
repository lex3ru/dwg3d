# import

Импорт чертежей: принимает DWG/DXF, собирает из них этажи, помещения и 3D-модель,
хранит файлы сборок. Не знает ни объектов, ни людей, ни прав на помещения; результат
забирает сервис `buildings`.

Два процесса из одного образа:

| Процесс | Команда | Что делает |
|---|---|---|
| API | `uvicorn app.main:build --factory` | загрузка, состояние сборок, файлы, экспорт |
| обработчик очереди | `python -m app.worker` | берёт сборки из очереди и выполняет конвейер разбора |

Конвейер разбора (`app/dwg`) перенесён из `legacy/backend/dwg3d` без изменений — тест
`test_pipeline_is_the_one_of_the_single_application_version` сравнивает файлы, поэтому
обе версии распознают чертёж одинаково. Менять конвейер — осознанно, вместе с этим тестом.

## Запросы

`/api/import/v1` — `contracts/openapi/import.v1.json`. До этапа 2 всё доступно
администратору системы; чтение — также другим сервисам.

| Запрос | Что делает |
|---|---|
| `POST /drawings` | файл и `building_id` → чертёж; сборка ставится в очередь |
| `POST /drawings/{id}/files` | новый файл чертежа; тот же файл повторно — `unchanged`, без сборки |
| `GET /drawings?building_id=`, `GET /drawings/{id}` | чертежи и состояние последней сборки |
| `DELETE /drawings/{id}` | удалить чертёж |
| `GET /drawings/{id}/config`, `GET /config/default` | настройки разбора и правки 2D-редактора (`config.edits`) |
| `POST /drawings/{id}/builds` | пересобрать, при необходимости изменив настройки и правки |
| `GET /builds/{id}`, `GET /builds/{id}/result` | состояние и результат сборки |
| `GET /builds/{id}/files/{путь}` | `model.glb`, `plans/floor_<id>.json`, `model.ifc`, `model_obj.zip` |
| `GET /drawings/{id}/export?format=dxf\|dwg` | исходный чертёж с правками 2D-редактора |

Пока идёт сборка, изменяющие запросы к чертежу отвечают `409 busy`.

## События

| Публикует | Когда |
|---|---|
| `import.drawing.uploaded` / `.deleted` | загружен файл чертежа / чертёж удалён |
| `import.build.started` / `.finished` / `.failed` | ход сборки |
| `import.build.progress` | этап и доля — не хранится, только для показа |

Событий не получает.

## Очередь сборок

Сборку забирает один из обработчиков (`FOR UPDATE SKIP LOCKED`); их можно запустить
несколько (`--scale import-worker=N`). Работающая сборка отмечается каждые 15 секунд;
если обработчик умер, через 2 минуты сборка помечается ошибкой с событием `failed`,
и её можно запустить заново.

## Настройки

Общие (`libs/chassis`), плюс:

| Переменная | По умолчанию | Что задаёт |
|---|---|---|
| `TWIN_S3_ENDPOINT`, `TWIN_S3_ACCESS_KEY`, `TWIN_S3_SECRET_KEY`, `TWIN_S3_BUCKET` | S3 стека разработки, корзина `twin-import` | хранилище файлов |
| `TWIN_DATA` | временный каталог | рабочие копии и кэш конвейера; потеря только замедлит следующую сборку |
| `TWIN_MAX_UPLOAD_MB` | `200` | предел размера чертежа |
| `DWG3D_DWG2DXF` | `dwg2dxf` в `PATH` | конвертер LibreDWG (в образе установлен) |
| `DWG3D_ODA` | — | ODA File Converter: лучше читает DWG и нужен для записи DWG |

## Запуск и тесты

```bash
docker compose -f deploy/docker-compose.yml up -d db db-init nats s3
cd services/import
uv run python -m twin_chassis.migrate && uv run uvicorn app.main:build --factory --port 8000
uv run python -m app.worker                      # в другом терминале
uv run ruff check . && uv run pytest
```

Тестам нужны PostgreSQL, NATS и S3 стека разработки; другие сервисы не нужны.
Чертёж в тестах — синтетический DXF (`tests/make_sample.py`), конвертер DWG не требуется.

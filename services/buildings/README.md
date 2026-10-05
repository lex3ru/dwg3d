# buildings

Здание: здания, этажи и помещения с идентификаторами, которые не меняются при новой
сборке чертежа; планы этажей, поиск помещений, метки, привязка к карте, модель фасада.

## Как сборка чертежа становится зданием

По событию `import.build.finished` сервис забирает результат сборки у `import`
(своей служебной учётной записью `twin-svc-buildings`) и публикует его (`app/publish.py`):

- **этаж** узнаётся по листу чертежа, на котором он нарисован;
- **помещение** — по перекрытию контуров (совпадение названия учитывается дополнительно);
- найденные сохраняют идентификатор, новые получают новый, пропавшие **снимаются**
  (`status: retired`), а не удаляются — на них могут ссылаться объекты, люди и права;
- название и тип, заданные вручную, новая сборка не перезаписывает.

До этапа 7 каждая сборка публикуется сразу, без просмотра различий.

Геометрия (планы, контуры помещений, точки для `locate`) — в координатах чертежа
этажа, метры. Положение чертежа в здании (`placement`) хранится отдельно.

## Запросы

`/api/buildings/v1` — `contracts/openapi/buildings.v1.json`. До этапа 2 всё доступно
администратору системы; чтение — также другим сервисам.

| Запрос | Что делает |
|---|---|
| `GET` / `POST /buildings`, `GET` / `PATCH` / `DELETE /buildings/{id}` | здания |
| `PUT /buildings/{id}/site` | привязка к карте |
| `PUT` / `PATCH` / `DELETE /buildings/{id}/facade`, `GET …/facade.glb` | детальная модель фасада и её выравнивание |
| `GET /buildings/{id}/drawings`, `PATCH …/drawings/{drawing_id}` | чертежи здания и их положение |
| `GET /buildings/{id}/tree` | этажи и помещения кратко |
| `GET /buildings/{id}/model` | по каждому чертежу: адрес файла модели и состав — этажи, помещения, входы |
| `GET /floors/{id}/plan`, `PATCH /floors/{id}` | план этажа; переименование |
| `POST /floors/{id}/locate` | в каком помещении каждая из точек |
| `GET /rooms`, `GET /rooms/{id}`, `POST /rooms/batch-get`, `PATCH /rooms/{id}` | помещения |
| `GET` / `POST /buildings/{id}/pins`, `PATCH` / `DELETE /pins/{id}` | метки на модели |

Изменения несут `version`; при расхождении — `409 version_conflict` с текущим состоянием.

## События

| Публикует | Когда |
|---|---|
| `buildings.building.created` / `.changed` / `.deleted` | здание |
| `buildings.revision.published` | сборка чертежа стала состоянием здания: какие этажи и помещения созданы, изменены, сняты |
| `buildings.floor.changed`, `buildings.room.changed` | правки вручную |
| `buildings.room.retired` | помещения больше нет |

| Получает | Реакция |
|---|---|
| `import.drawing.uploaded` | запомнить чертёж здания |
| `import.build.finished` | забрать результат и опубликовать; более старая сборка, пришедшая позже, игнорируется |
| `import.drawing.deleted` | снять этажи и помещения чертежа |

Если `import` недоступен, событие остаётся необработанным и доставляется снова.

## Настройки

Общие (`libs/chassis`), плюс `TWIN_SERVICE_SECRET` (секрет клиента `twin-svc-buildings`
в Keycloak), `TWIN_SERVICES` (`import=http://import:8000`) и переменные S3 (корзина
`twin-buildings` — модели фасадов).

## Запуск и тесты

```bash
docker compose -f deploy/docker-compose.yml up -d db db-init nats s3
cd services/buildings
uv run python -m twin_chassis.migrate && uv run uvicorn app.main:build --factory --port 8000
uv run ruff check . && uv run pytest
```

В тестах `import` заменён заглушкой, отдающей результаты настоящего конвейера,
записанные в `tests/data` (как получены — см. `tests/conftest.py`).

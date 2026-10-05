# Контракты сервисов

> Состояние: черновик от 05.10.2026, к [ТЗ](TZ.md). Здесь — границы сервисов:
> запросы, события и кто от кого зависит. Точные схемы полей (OpenAPI и
> JSON Schema событий) появятся в каталоге `contracts/` на этапе 0 и будут
> единственным источником истины; этот документ — их описание для людей.

## 1. Общие правила

### 1.1. Адреса и версии

- Запросы сервиса: `/api/<сервис>/v1/...`. Шлюз пропускает их без изменений.
- Версия в пути меняется только при несовместимом изменении; добавление
  полей и запросов версию не меняет. Клиент обязан игнорировать незнакомые поля.
- Сервисы: `buildings`, `import`, `catalog`, `assets`, `people`, `access`,
  `journal`, `planning`, `copilot`.

### 1.2. Кто обращается

Каждый запрос несёт токен в заголовке `Authorization: Bearer`:

| Кто | Токен | Кем выдан |
|---|---|---|
| Пользователь | токен доступа | Keycloak (шлюз хранит сессию в cookie и подставляет токен) |
| Сервис | токен служебной учётной записи | Keycloak (client credentials) |
| Гость по ссылке | гостевой токен на 1 час | сервис «Доступ» |

- Сервис проверяет подпись токена сам (ключи Keycloak и «Доступа»).
- Запрос, вызванный действием пользователя, идёт дальше с токеном
  пользователя; реакция на событие — с токеном сервиса.
- Администратор системы — клиентская роль Keycloak `twin.admin`; ему
  разрешено всё, «Доступ» не спрашивается.
- Служебному токену разрешены только запросы, помеченные ниже «служебный».

### 1.3. Форматы

- Идентификаторы — UUID версии 7, строкой. Выдаёт сервис-владелец.
- Время — ISO 8601 в UTC. Даты без времени — `YYYY-MM-DD`.
- Координаты — метры в системе координат здания; угол — градусы против
  часовой стрелки; отметки — метры от пола этажа.
- Списки: `?limit=` (до 500) и `?cursor=`; ответ `{items, next}`.
- Пакетное чтение по идентификаторам: `POST .../batch-get {ids}` — до 1000
  за раз; недоступные и несуществующие в ответ просто не попадают.

### 1.4. Изменения

- У изменяемых сущностей есть `version`. Изменение присылает версию,
  которую видел клиент; при расхождении — `409` с текущим состоянием.
- `POST`, создающий сущность, принимает заголовок `Idempotency-Key`:
  повтор с тем же ключом возвращает первый результат.
- Долгие операции (сборка чертежа, импорт Excel, экспорт) отвечают `202`
  и ссылкой на задачу: `{id, status, progress, message, error, result}`.

### 1.5. Ошибки

Тело — `application/problem+json`: `{type, title, status, code, detail, errors[]}`.

| Статус | Когда |
|---|---|
| 401 | нет токена или он недействителен |
| 403 | сущность видна, действие запрещено |
| 404 | сущности нет или она не видна запросившему |
| 409 | расхождение версий, нарушение уникальности (`code` уточняет) |
| 422 | данные не проходят проверку; `errors[]` — по полям |
| 503 | недоступен сервис, без которого ответ невозможен |

### 1.6. События

Шина — NATS JetStream. Тема: `twin.<сервис>.<сущность>.<что произошло>`.

```json
{
  "id": "0192…",                       // UUID события, по нему отсекаются повторы
  "type": "assets.asset.moved",
  "time": "2026-10-05T09:12:44Z",
  "actor": {"kind": "user|service|guest", "id": "…", "person_id": "…"},
  "building_id": "…",                  // область события; заполняется всё, что известно:
  "floor_id": "…", "room_id": "…",     //   по этим полям «Журнал» отбирает ленту
  "asset_id": "…", "person_id": "…",   //   и проверяет право на чтение
  "subject": {"kind": "asset", "id": "…"},
  "data": { … }                        // по схеме типа события
}
```

- Сервис записывает событие в свою базу в той же транзакции, что и
  изменение, и публикует после неё — событие не теряется и не появляется
  без изменения.
- Доставка — не менее одного раза; получатель обязан переносить повторы и
  не полагаться на порядок событий разных сущностей.
- Событие описывает свершившийся факт и содержит всё, что нужно
  получателю для реакции без обратного запроса (в пределах разумного).
- В событиях нет персональных данных, кроме идентификаторов.
- Несовместимое изменение события — новый тип с суффиксом `.v2`; старый
  публикуется параллельно, пока есть получатели.
- События хранятся в шине 30 дней; бессрочно их хранит «Журнал».

## 2. Доступ (`access`)

Права хранятся как назначения человеку (`person_id`), не учётной записи.
Связь «учётная запись ↔ человек» сервис получает из событий «Людей».
Пользователь без записи в справочнике не имеет никаких прав.

**Назначение**: `{id, person_id, role, scope: {kind, id}, building_id, origin}`

- `role`: `viewer` | `responsible` | `admin`
- `scope.kind`: `building` | `floor` | `room` | `asset`
- `origin`: `manual` | `assignment` (привязка к помещению) | `responsible` (ответственный за объект)

**Действия и роли**

| Действие | viewer | responsible | admin |
|---|---|---|---|
| `view` — видеть объекты и людей области | да | да | да |
| `edit` — править свойства «О», состояние, файлы | | да | да |
| `move_portable` — перемещать переносные объекты | | да | да |
| `manage` — всё остальное | | | да |
| `plan` — видеть план и 3D здания | даёт любое назначение в этом здании | | |

Иерархию «объект → помещение → этаж → здание» сервис не хранит: её
присылает спрашивающий в поле `chain`.

### Запросы

| Запрос | Что делает | Кому |
|---|---|---|
| `POST /check` | `{checks: [{action, chain: [{kind, id}, …]}]}` → `[{allowed, role}]`; субъект — из токена | всем, служебный |
| `GET /me/scopes` | назначения текущего субъекта и список зданий, где есть `plan` | всем |
| `GET /scopes?person_id=` | то же для указанного человека | служебный |
| `GET /grants?building_id=&person_id=&scope_kind=&scope_id=` | список назначений | admin здания |
| `POST /grants` | выдать (`origin: manual`) | admin здания |
| `DELETE /grants/{id}` | отозвать | admin здания |
| `GET /shares?building_id=` | гостевые ссылки | admin здания |
| `POST /shares` | `{scope, building_id, expires_at, note}` → `{id, url}` | admin здания |
| `DELETE /shares/{id}` | отозвать | admin здания |
| `POST /shares/open` | `{token}` → гостевой токен: `viewer` на область, без людей | без токена |
| `GET /.well-known/jwks.json` | ключи для проверки гостевых токенов | без токена |

Сервисы кешируют ответы `check` и `scopes` не дольше 30 секунд и
сбрасывают кеш по событиям `access.grant.*`.

### События

| Публикует | Данные |
|---|---|
| `access.grant.created` / `.revoked` | назначение целиком |
| `access.share.created` / `.revoked` / `.opened` | `share_id`, область; для `.opened` — адрес и время |

| Получает | Реакция |
|---|---|
| `people.person.linked` / `.unlinked` | обновить связь учётной записи с человеком |
| `people.person.assigned` / `.unassigned` | создать / отозвать `viewer` на помещение (`origin: assignment`) |
| `people.person.left` | отозвать все назначения человека |
| `assets.asset.responsible_changed` | отозвать `responsible` у прежнего, выдать новому (`origin: responsible`) |
| `assets.asset.retired` | отозвать назначения на объект |
| `assets.asset.moved` (смена здания) | обновить `building_id` назначений на объект |
| `buildings.room.merged` | перенести назначения на помещение-наследник |
| `buildings.room.retired` | отозвать назначения на помещение |
| `buildings.building.deleted` | отозвать всё по зданию |

## 3. Здание (`buildings`)

**Сущности**: `Building {id, name, address, site, facade, version}`,
`Floor {id, building_id, drawing_id, name, level, elevation, height}`,
`Room {id, building_id, floor_id, name, number, type, area, polygon, status: active|retired, version}`,
`Revision {id, building_id, drawing_id, build_id, status: draft|published|discarded, summary}`,
`Pin`, `Comment`.

### Запросы

| Запрос | Что делает | Право |
|---|---|---|
| `GET /buildings` | здания, где у субъекта есть `plan` | — |
| `POST /buildings` | создать | админ системы |
| `GET` / `PATCH` / `DELETE /buildings/{id}` | карточка, правка, удаление | plan / manage / админ системы |
| `PUT /buildings/{id}/site` | привязка к карте | manage |
| `PUT /buildings/{id}/facade` | детальная модель фасада (GLB) и её выравнивание | manage |
| `GET /buildings/{id}/tree` | этажи и помещения кратко (id, название, номер, тип, площадь) | plan |
| `GET /buildings/{id}/model` | ссылки на 3D-модели этажей текущих ревизий | plan |
| `GET /buildings/{id}/drawings` | чертежи здания и их положение | plan |
| `PATCH /buildings/{id}/drawings/{drawing_id}` | сдвиг, поворот, отметки этажей чертежа | manage |
| `PATCH /floors/{id}` | название, уровень, отметка, высота | manage |
| `GET /floors/{id}/plan` | геометрия плана: стены, проёмы, контуры помещений | plan |
| `POST /floors/{id}/locate` | `{points: [[x, y], …]}` → `room_id` для каждой точки | plan, служебный |
| `GET /rooms?building_id=&floor_id=&q=&type=&status=` | поиск помещений | plan |
| `GET /rooms/{id}`, `POST /rooms/batch-get` | помещение | plan, служебный |
| `PATCH /rooms/{id}` | название, номер, тип | manage |
| `POST /rooms/{id}/merge` | `{with: [ids]}` — объединить, наследник — `{id}` | manage |
| `POST /rooms/{id}/split` | `{parts: [polygon…], heir: 0}` — разделить | manage |
| `GET /buildings/{id}/revisions` | ревизии | manage |
| `GET /revisions/{id}` | черновик: какие помещения узнаны, новые, пропавшие, с изменённым контуром | manage |
| `PATCH /revisions/{id}/matches` | поправить сопоставление вручную | manage |
| `POST /revisions/{id}/publish` / `/discard` | опубликовать / отбросить | manage |
| `GET` / `POST /buildings/{id}/pins`, `PATCH` / `DELETE /pins/{id}` | метки | plan / manage (свои — автор) |
| `GET /comments?building_id=&target_kind=&target_id=` | комментарии к точке, помещению, объекту | view цели |
| `POST /comments`, `PATCH` / `DELETE /comments/{id}`, `POST /comments/{id}/resolve` | оставить, изменить, закрыть | view цели; правка — автор, manage |

Гость видит дерево, план и модель только своей области; комментарии — нет.

### События

| Публикует | Данные |
|---|---|
| `buildings.building.created` / `.changed` / `.deleted` | здание |
| `buildings.revision.drafted` | `revision_id`, `drawing_id`, сводка |
| `buildings.revision.published` | `revision_id`, `drawing_id`, этажи; помещения: `created[]`, `changed[]` (с признаком смены контура), `retired[]` |
| `buildings.room.changed` | помещение, список изменённых полей |
| `buildings.room.retired` | `room_id`, `floor_id` |
| `buildings.room.merged` | `from[]`, `into` |
| `buildings.room.split` | `from`, `into[]`, `heir` |
| `buildings.comment.created` / `.resolved` | цель, автор |

| Получает | Реакция |
|---|---|
| `import.build.finished` | забрать результат сборки, создать черновик ревизии; первая ревизия чертежа публикуется сразу |
| `import.drawing.deleted` | снять этажи и помещения чертежа |

## 4. Импорт чертежей (`import`)

**Сущности**: `Drawing {id, building_id, name, filename, size, config, current_file}`,
`Build {id, drawing_id, status, stage, progress, warnings}`, `Export`.

### Запросы

| Запрос | Что делает | Право |
|---|---|---|
| `POST /drawings` | файл DWG/DXF и `building_id` → чертёж; сборка запускается сама | manage здания |
| `GET /drawings?building_id=`, `GET /drawings/{id}` | чертежи | manage |
| `POST /drawings/{id}/files` | новый файл чертежа (будущая ревизия) | manage |
| `DELETE /drawings/{id}` | удалить чертёж | manage |
| `GET` / `PUT /drawings/{id}/config` | настройки разбора | manage |
| `GET` / `PUT /drawings/{id}/edits` | правки 2D-редактора | manage |
| `GET /drawings/{id}/source` | исходная геометрия для 2D-редактора | manage |
| `POST /drawings/{id}/builds` | запустить сборку → задача | manage |
| `GET /builds/{id}` | состояние сборки | manage |
| `GET /builds/{id}/result` | этажи, помещения, проёмы, предупреждения, ключи файлов | служебный |
| `GET /builds/{id}/files/{name}` | модель этажа и прочие файлы — переадресация на подписанную ссылку | служебный; пользователю — через `buildings` |
| `POST /drawings/{id}/exports` | `{format: dxf|dwg|ifc|obj|glb, objects: […]}` → задача; `objects` — блоки с атрибутами для чертежа с объектами | manage, служебный |
| `GET /exports/{id}` | состояние и ссылка на файл | тот, кто запустил |

Сервис не знает ни объектов, ни людей: для чертежа с объектами их
присылают в `objects` готовыми (название блока, точка, угол, габариты,
атрибуты, слой).

### События

| Публикует | Данные |
|---|---|
| `import.drawing.uploaded` / `.deleted` | `drawing_id`, `building_id` |
| `import.build.started` | `build_id`, `drawing_id` |
| `import.build.progress` | этап, доля — без хранения, только для интерфейса |
| `import.build.finished` | `build_id`, `drawing_id`, `building_id`, число этажей и помещений, предупреждения |
| `import.build.failed` | `build_id`, понятное сообщение |

Событий не получает.

### Как сделано на этапе 1 (отличия от таблиц выше)

Точные запросы — в `contracts/openapi/import.v1.json` и `buildings.v1.json`; от
описания выше они отличаются так:

- **Модель — один файл на чертёж**, а не на этаж: `GET /buildings/{id}/model` отдаёт
  по каждому чертежу адрес GLB (узел на этаж и на помещение), положение чертежа и
  состав модели с идентификаторами этажей и помещений.
- **Файлы сборки отдаёт сам `import`** (`GET /builds/{id}/files/…`) с проверкой
  токена, без подписанных ссылок: хранилище снаружи недоступно.
- **Правки 2D-редактора — часть настроек чертежа** (`config.edits`); отдельного
  запроса `/edits` нет. Пересборка с изменёнными настройками — `POST /drawings/{id}/builds`.
- **Экспорт чертежа с правками — обычный запрос** (`GET /drawings/{id}/export`),
  не задача; файлы модели (IFC, OBJ, GLB) — среди файлов сборки.
- **Геометрия — в координатах чертежа этажа.** Положение чертежа в здании
  (`placement`) хранится отдельно и применяется при показе.
- **Ход сборки** (`import.build.progress`) идёт мимо хранения: тема
  `twin-live.<тип>`, шлюз передаёт его в браузер вместе с остальными событиями.
- **Ревизии** публикуются сразу; черновик, сопоставление вручную, объединение и
  разделение помещений — этап 7. Комментарии — этап 5.
- **Вызов между сервисами без пользователя** идёт с токеном служебной учётной
  записи `twin-svc-<сервис>` (Keycloak, client credentials); такие запросы
  помечены «служебный».

## 5. Каталог (`catalog`)

**Сущности**: `Category {id, name, color, sort}`,
`PropertySet {id, name, properties[], version}`,
`Type {id, category_id, name, size: [w, d, h], elevation, wall_mounted, shape, color, model, container, portable, sets[], properties[], values{}, article, supplier, price, currency, active, schema_version}`.

**Свойство**: `{key, title, kind, unit, options[], required, stored, editable_by}`

- `kind`: `text` | `number` | `date` | `bool` | `choice` | `person`
- `stored`: `type` (значение в `Type.values`) | `asset` (значение у объекта)
- `editable_by`: `system` | `admin` | `responsible`

### Запросы

| Запрос | Что делает | Право |
|---|---|---|
| `GET /categories`, `GET /types?category_id=&q=&active=`, `GET /types/{id}` | чтение | любой вошедший, гость |
| `POST /types/batch-get` | типы по идентификаторам | любой, служебный |
| `GET /types/{id}/schema` | развёрнутая схема: наборы + свои свойства, `schema_version` | любой, служебный |
| `POST` / `PATCH` / `DELETE /categories…` | разделы | админ системы |
| `POST /types`, `PATCH /types/{id}` | тип | админ системы |
| `POST /types/{id}/archive` / `/restore` | убрать из выбора, не удаляя | админ системы |
| `PUT` / `DELETE /types/{id}/model` | модель GLB | админ системы |
| `GET /property-sets`, `GET /property-sets/{id}` | наборы свойств | любой |
| `POST` / `PATCH` / `DELETE /property-sets…` | наборы свойств; удалить используемый нельзя | админ системы |

Изменение схемы: добавить свойство и ослабить требование можно всегда;
удалить свойство или сменить `kind` — только если ни у одного объекта нет
значения (каталог спрашивает `assets`), иначе `409`.

### События

| Публикует | Данные |
|---|---|
| `catalog.type.created` / `.changed` / `.archived` / `.restored` | тип, `schema_version`, признак «схема изменилась» |
| `catalog.property_set.changed` | набор, `type_ids[]` затронутых типов |

Событий не получает.

## 6. Объекты (`assets`)

**Объект**:

```
Asset {
  id, type_id, schema_version,
  building_id, floor_id, room_id,        // room_id сервис определяет сам по точке
  x, y, angle, elevation,                // у вложенного отсутствуют
  container_id,                          // у вложенного
  inventory_no, serial_no,
  state: in_use | faulty | in_repair | in_storage | retired,
  responsible_id,                        // person_id
  props {key: value},                    // по схеме типа, только stored: asset
  note, needs_placement, qr_code,
  version, created_at, updated_at
}
```

### Запросы

| Запрос | Что делает | Право |
|---|---|---|
| `GET /assets?building_id=&floor_id=&room_id=&type_id=&category_id=&state=&responsible_id=&container_id=&needs_placement=&q=&prop.<key>=&prop.<key>.lte=&sort=` | список в пределах видимого субъекту; `q` — название типа, инвентарный и серийный номер | view |
| `GET /assets/{id}`, `POST /assets/batch-get` | объект | view, служебный |
| `GET /assets/{id}/children` | вложенные объекты | view |
| `POST /assets` | создать: тип, точка или контейнер, номера, свойства | manage помещения |
| `POST /assets/batch` | несколько одинаковых: точки, шаблон инвентарного номера, начало счёта | manage |
| `POST /assets/import` | Excel → объекты одним запросом (без фоновой задачи); при ошибках — отчёт по строкам и ничего не создаётся | manage здания |
| `PATCH /assets/{id}` | номера, свойства, примечание; каждое свойство проверяется по `editable_by` | edit / manage |
| `POST /assets/{id}/move` | `{floor_id, x, y, angle, elevation}` или `{container_id}` | manage; для переносных — `move_portable` в исходном помещении и `view` в целевом |
| `POST /assets/{id}/state` | сменить состояние | edit; `retired` — manage |
| `POST /assets/{id}/responsible` | `{person_id}` или пусто | manage |
| `GET /assets/{id}/history` | история: кто, когда, что было и стало | view |
| `POST /assets/{id}/history/{entry_id}/revert` | откатить изменение | manage |
| `GET` / `POST /assets/{id}/files` | список; загрузить фото или документ | view / edit |
| `GET /files/{id}`, `DELETE /files/{id}` | переадресация на подписанную ссылку; удалить | view / edit |
| `GET /qr/{code}` | код метки → `asset_id` | любой вошедший (существование объекта не раскрывается: нет права — `404`) |
| `GET /assets/{id}/label` | метка в PDF | view |
| `POST /labels` | `{asset_ids \| filter, layout}` → лист меток в PDF | manage |
| `GET /usage?type_id=&prop=` | есть ли объекты типа и значения свойства | служебный (для каталога) |

Правила:

- `room_id` и `floor_id` при создании и перемещении сервис получает от
  `buildings` (`/floors/{id}/locate`); точка вне помещений — `422`.
- Инвентарный номер уникален в организации — иначе `409 inventory_no_taken`.
- Свойства проверяются по схеме типа; схему сервис держит у себя и
  обновляет по событиям каталога.
- Гость видит объекты своей области без `responsible_id`, истории и файлов.

### События

| Публикует | Данные |
|---|---|
| `assets.asset.created` | объект целиком |
| `assets.asset.changed` | `changes: {поле: [было, стало]}` |
| `assets.asset.moved` | откуда и куда: здание, этаж, помещение, точка, контейнер |
| `assets.asset.state_changed` | было, стало |
| `assets.asset.responsible_changed` | `from`, `to` (person_id), `building_id` |
| `assets.asset.retired` | объект |
| `assets.asset.file_added` / `.file_removed` | `file_id`, вид, имя |

| Получает | Реакция |
|---|---|
| `buildings.revision.published` | для объектов помещений со сменой контура — проверить, что точка внутри; иначе `needs_placement` |
| `buildings.room.retired` | объекты помещения: `needs_placement` |
| `buildings.room.merged` | перенести объекты в наследника |
| `buildings.room.split` | определить помещение каждого объекта заново по точке |
| `catalog.type.changed`, `catalog.property_set.changed` | обновить схему; объекты, не проходящие новую схему, пометить «требует заполнения» |
| `people.person.left` | снять человека с ответственных (с событием `responsible_changed`) |

## 7. Люди (`people`)

**Сущности**: `Person {id, full_name, position, department, email, phone, user_sub, status: active|left, version}`,
`Assignment {person_id, building_id, room_id, workplace_asset_id}`.

### Запросы

| Запрос | Что делает | Право |
|---|---|---|
| `GET /me` | запись человека для текущей учётной записи; при первом входе связывает по почте | любой вошедший |
| `GET /people?building_id=&room_id=&department=&q=` | люди, привязанные к видимым субъекту помещениям | view помещения |
| `GET /people/{id}` | карточка | view помещения человека |
| `POST /people/batch-get` | `{ids, fields: brief}` — только имя и должность | любой вошедший, служебный |
| `GET /rooms/{room_id}/people` | люди помещения | view |
| `POST /people`, `PATCH /people/{id}` | создать, изменить | manage здания |
| `POST /people/import` | Excel → задача | manage здания |
| `POST /people/{id}/leave` | человек выбыл | manage здания |
| `PUT` / `DELETE /people/{id}/link` | связать с учётной записью / разорвать | manage здания |
| `GET /people/{id}/assignments` | привязки | view |
| `PUT /people/{id}/assignments/{room_id}` | привязать к помещению, необязательно — к рабочему месту | manage помещения |
| `DELETE /people/{id}/assignments/{room_id}` | отвязать | manage помещения |

Краткие данные (имя и должность) отдаются по идентификатору любому
вошедшему: это нужно для карточки объекта («ответственный») и истории.
Контакты и привязки — только по праву на помещение. Гостям — ничего.

### События

| Публикует | Данные |
|---|---|
| `people.person.created` / `.changed` | `person_id`, изменённые поля (без значений) |
| `people.person.linked` / `.unlinked` | `person_id`, `user_sub` |
| `people.person.assigned` / `.unassigned` | `person_id`, `building_id`, `room_id` |
| `people.person.left` | `person_id` |

| Получает | Реакция |
|---|---|
| `buildings.room.merged` | перенести привязки в наследника |
| `buildings.room.retired` | снять привязки (с событиями `unassigned`) |
| `assets.asset.retired` | очистить `workplace_asset_id` |

## 8. Журнал (`journal`)

Подписан на `twin.>`; хранит события как есть, ничего не публикует.

| Запрос | Что делает | Право |
|---|---|---|
| `GET /events?building_id=&floor_id=&room_id=&asset_id=&person_id=&actor_id=&type=&from=&to=` | лента, новые сверху | view области события; без фильтра по зданию — админ системы |
| `GET /events/{id}` | событие | то же |

Область события (здание, этаж, помещение, объект) журнал берёт из самого
события, поэтому события об объектах и людях несут `building_id`,
`floor_id`, `room_id`.

## 9. Проектирование (`planning`) — этап 8

Контракт уточняется перед этапом; границы такие:

| Группа запросов | Содержание |
|---|---|
| `/variants` | вариант — набор предполагаемых операций над объектами здания (добавить, переместить, изменить, убрать); создать, скопировать, удалить |
| `/variants/{id}/view` | фактическое состояние с наложенным вариантом — для показа на плане |
| `/variants/{id}/compare?with=` | что добавлено, убрано, перемещено, изменено; разница спецификаций |
| `/variants/{id}/spec` | спецификация с ценами из каталога |
| `/variants/{id}/apply` | выполнить операции через `assets` от имени пользователя; частичный отказ возвращается списком |
| `/shapes` | маршруты людей, зоны, кабельные трассы |
| `/checks` | пересечения потоков, заходы в запрещённые зоны, нехватка извещателей |
| `/coverage` | Wi-Fi, освещение, извещатели, обзор камер — по фактическому состоянию или варианту |

Получает `assets.asset.*`, `buildings.room.*`, `buildings.revision.published`,
`catalog.type.changed` — чтобы помечать варианты и маршруты устаревшими.
Публикует `planning.variant.created` / `.applied` / `.deleted`.

## 10. Копилот (`copilot`) — этап 9

| Запрос | Что делает |
|---|---|
| `GET` / `POST /chats`, `GET /chats/{id}` | беседы пользователя |
| `POST /chats/{id}/messages` | сообщение; ответ потоком (SSE) |
| `GET` / `PUT /settings` | адрес и модель внешнего ИИ — админ системы |

Работает только через запросы остальных сервисов с токеном пользователя;
изменения предлагает как вариант в `planning`, сам ничего не меняет.

## 11. Шлюз

Своих данных не хранит, кроме сессий входа.

| Адрес | Что делает |
|---|---|
| `/auth/login`, `/auth/callback`, `/auth/logout` | вход через Keycloak, сессия в cookie |
| `/api/<сервис>/v1/…` | пропускает запрос в сервис, подставляя токен |
| `GET /api/me` | учётная запись, человек (`people/me`), области (`access/me/scopes`) |
| `GET /api/views/cabinet` | личный кабинет: мои здания, помещения, объекты в них и объекты, за которые отвечаю |
| `GET /api/views/assets/{id}` | карточка объекта: объект + тип со схемой + помещение + ответственный + что разрешено субъекту |
| `GET /api/views/rooms/{id}` | помещение: карточка + объекты + люди |
| `GET /api/views/floors/{id}/scene` | всё для показа этажа: план, объекты с видом из каталога, метки |
| `GET /api/reports/assets.xlsx?…` | список объектов по тем же фильтрам, что `assets` |
| `GET /api/reports/rooms/{id}/sheet.pdf` | ведомость помещения |
| `POST /api/reports/buildings/{id}/drawing` | `{format, drawing_id}` → чертёж с объектами (задача) |
| `GET /api/stream` | поток событий в браузер (SSE), отфильтрованный по правам субъекта |
| `GET /api/system/status` | состояние сервисов: отвечает ли, доступна ли база, подключён ли к шине — администратору системы |
| `GET /q/{code}` | QR-метка: без входа — на вход; затем на карточку объекта |
| `GET /s/{token}` | гостевая ссылка: получает гостевой токен и открывает просмотрщик на области |

Поток событий: каждое сообщение — `id: <id события>` и `data: <конверт события в JSON>`; тип события —
внутри конверта. Пропущенное за время разрыва не досылается: после переподключения страница перечитывает то,
что показывает. До появления сервиса «Доступ» (этап 2) администратор системы получает все события, остальные —
только вызванные ими самими.

Запрос с собственным токеном (`Authorization: Bearer`) шлюз пропускает без сессии — так к API обращаются
программы. Изменяющий запрос с cookie принимается только со страниц самой системы (проверка `Origin`).

Сборные ответы (`/api/views/*`) — только чтение. При недоступности
необязательной части (люди, каталог) шлюз отдаёт остальное и перечисляет
недостающее в поле `partial`.

## 12. Кто от кого зависит

Запросы (стрелка — «обращается к»):

| Сервис | Обращается к | Зачем |
|---|---|---|
| buildings | access; import | права; результат сборки и файлы моделей |
| import | access | права |
| catalog | assets | можно ли менять схему |
| assets | access; buildings; catalog | права; помещение по точке; схема типа (при промахе кеша) |
| people | access | права |
| access | — | — |
| journal | access | права на чтение ленты |
| planning | access, assets, buildings, catalog | всё, что нужно для вариантов и расчётов |
| copilot | все | через их открытые запросы |
| шлюз | все | — |

Циклов по запросам нет, кроме пары `catalog ↔ assets`: она разорвана тем,
что `assets` берёт схему из событий, а к каталогу обращается только при
пустом кеше.

Что работает при отказе:

| Не работает | Последствия |
|---|---|
| access | все сервисы живут на кеше 30 секунд, затем отказывают в изменениях; чтение — по последним известным областям до 5 минут |
| buildings | нельзя создавать и перемещать объекты; списки, карточки и правка свойств работают |
| catalog | объекты работают по сохранённым схемам; нельзя править каталог |
| people | карточки без имён ответственных (`partial`) |
| journal | события копятся в шине и дочитываются после запуска |
| import | нельзя загружать чертежи и строить экспорт |
| NATS | изменения выполняются, события ждут в базах сервисов и уходят после восстановления |

## 13. Какие контракты нужны на каком этапе

| Этап | Контракты |
|---|---|
| 0 | разделы 1 и 11 (вход, пропуск запросов, поток событий), конверт события |
| 1 | `import`, `buildings` без ревизий и ручных правок помещений |
| 2 | `people` без привязок к помещениям; `access` без гостевых ссылок и автоматических назначений |
| 3 | `catalog` |
| 4 | `assets` |
| 5 | `/api/views/*`, `/q/{code}`, метки QR, отчёты |
| 6 | привязки в `people`, `journal`, автоматические назначения в `access` |
| 7 | ревизии и сопоставление помещений в `buildings`, реакции `assets`, `people`, `access`; гостевые ссылки |
| 8 | `planning` |
| 9 | `copilot` |

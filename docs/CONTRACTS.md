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
| Гость по ссылке | гостевой токен на 10 минут, шлюз продлевает его, пока ссылка действует | сервис «Доступ» |

- Сервис проверяет подпись токена сам (ключи Keycloak и «Доступа»).
- Запрос, вызванный действием пользователя, идёт дальше с токеном
  пользователя; реакция на событие — с токеном сервиса.
- Роли приложения — только клиентские роли из `resource_access.<client_id>.roles` вида
  `dwg3d.<role>` (роли realm и роли других имён не учитываются). Администратор системы —
  `dwg3d.admin`: ему разрешено всё, «Доступ» не спрашивается. Пользователь — `dwg3d.user`;
  учётная запись без ролей `dwg3d.*` тоже входит как пользователь (решение заказчика): что ей
  видно, решают права в зданиях. Остальные `dwg3d.<role>` шлюз отдаёт в `GET /api/me` (`user.roles`).
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
| `POST /shares` | `{scope, building_id, floor_id, expires_at, note}` → ссылка с `url` и `token` — показываются один раз, хранится только хеш | admin здания |
| `DELETE /shares/{id}` | отозвать | admin здания |
| `POST /reconcile` | сверить автоматические назначения с `people` и `assets` (также само: на старте и раз в `TWIN_RECONCILE_S`) | admin системы, служебный |
| `POST /shares/open` | `{token, renew, address}` → гостевой токен на область (10 мин, не дольше срока ссылки); неизвестная, отозванная и истёкшая ссылки — одинаково `404`; `renew` — продление, не считается открытием | без токена |
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
| `POST /rooms/{id}/split` | `{line: [[x, y], …]}` или `{parts: [polygon…]}`, `heir` (по умолчанию — большая часть) — разделить | manage |
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
| `buildings.revision.drafted` / `.discarded` | `revision_id`, `drawing_id`, сводка |
| `buildings.revision.published` | `revision_id`, `drawing_id`, этажи; помещения: `created[]`, `changed[]` (с признаком смены контура), `retired[]`; `moves` — сдвиг этажей, выровненных иначе |
| `buildings.room.changed` | помещение, список изменённых полей |
| `buildings.room.retired` | `room_id`, `floor_id` |
| `buildings.room.merged` | `from[]`, `into` — объединение вручную или в новой сборке, где перегородку убрали |
| `buildings.room.split` | `from`, `into[]`, `heir` (наследник — тот же `from`), `floor_id` |
| `buildings.comment.created` / `.resolved` | цель, автор |

| Получает | Реакция |
|---|---|
| `import.build.finished` | забрать результат сборки; первая ревизия чертежа и ревизия, которая ничего не снимает, публикуются сразу, остальные ждут черновиком. Номер помещения берётся из плана, если план его даёт (нарисованный план), и не меняется, если задан вручную. Помещение, целиком (не меньше 90 % площади) вошедшее в помещение сборки, не снимается, а объединяется с ним (`room.merged`): убранная перегородка не требует проверки |
| `import.drawing.deleted` | снять этажи и помещения чертежа |
| `import.drawing.uploaded`, `import.drawing.drawn` | запомнить чертёж и его название (`drawn` — нарисованный план) |

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
| `POST /sketches` | `building_id` → нарисованный план: пустой лист 2D-редактора | manage здания |
| `POST /drawings/{id}/underlays`, `GET /drawings/{id}/underlays/{name}` | картинка-подложка нарисованного плана (PNG, JPEG, WebP до 20 МБ) | запись — manage; чтение — кто видит план |
| `POST /drawings/{id}/to-sketch` | загруженный чертёж с готовой сборкой → нарисованный план из неё, тот же чертёж; его сборки дают те же листы, этажи и помещения здания продолжаются | manage чертежа |
| `GET` / `PUT /drawings/{id}/sketch` | нарисованный план и номер сохранения; сохранение поверх чужого — `409 conflict` с текущим номером | чтение — кто видит план; запись — manage |
| `GET /drawings/{id}/sketch/check` | проблемы нарисованного плана (ошибки редактора и больше: свободные концы, помещения без названия, повторы номеров, узкие двери, несущие не на несущих) и его сводка | кто видит план |
| `POST /drawings/{id}/sketch/repair` | `{codes?, floor_id?}` → починенный план (не сохраняется), что исправлено и что осталось | manage |
| `POST /sketch-templates` | `{template: corridor|rooms_row|open_space, params}` → план по шаблону (не сохраняется), сводка и проверка | вошедший |
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
| `import.drawing.drawn` | `drawing_id`, `name`, `from_file`: создан нарисованный план или загруженный чертёж переведён в план |
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
`Type {id, category_id, name, size: [w, d, h], elevation, wall_mounted, ceiling_mounted, shape, color, model, container, portable, sets[], properties[], values{}, article, supplier, price, currency, active, schema_version}`.

`Product {id, type_id, vendor, name, article, supplier, price, currency, note, active, version, sort}` — марка и модель типа: `GET /products?type_id=`, `GET|POST /types/{id}/products`, `GET|PATCH /products/{id}`, `POST /products/{id}/archive|restore`.

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
  product_id, product_name,              // марка и модель, если названа (catalog.products)
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
| `GET /assets/{id}/label?size=` | метка в PDF (сторона наклейки в мм) | view |
| `POST /labels` | `{asset_ids \| building_id \| floor_id \| room_id, size}` → лист меток на A4 | manage |
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
| `GET /people?building_id=&room_id=&department=&q=` | хранителям справочника — все (с фильтрами); остальным, с `building_id`, — люди, привязанные к видимым субъекту помещениям | view помещения |
| `GET /people/{id}` | карточка | view помещения человека |
| `POST /people/batch-get` | `{ids, fields: brief}` — только имя и должность | любой вошедший, служебный |
| `GET /rooms/{room_id}/people` | люди помещения | view |
| `POST /people`, `PATCH /people/{id}` | создать, изменить | manage здания |
| `POST /people/import` | Excel → отчёт в ответе (без задачи) | manage здания |
| `POST /people/{id}/leave` | человек выбыл | manage здания |
| `PUT` / `DELETE /people/{id}/link` | связать с учётной записью / разорвать | manage здания |
| `GET /people/{id}/assignments` | привязки | view |
| `PUT /people/{id}/assignments/{room_id}` | привязать к помещению, необязательно — к рабочему месту | manage помещения |
| `DELETE /people/{id}/assignments/{room_id}` | отвязать | manage помещения |
| `GET /assignments` | все привязки — для сверки прав | служебный |

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
| `GET /events?building_id=&floor_id=&room_id=&asset_id=&person_id=&actor_id=&type=&from=&to=&limit=&cursor=` | лента, новые сверху; `type` точно или по началу (`assets.`) | view области события; события о человеке — он сам; без области — админ системы |
| `GET /events/{id}` | событие | то же |

Область события (здание, этаж, помещение, объект) журнал берёт из самого
события, поэтому события об объектах и людях несут `building_id`,
`floor_id`, `room_id`.

## 9. Проектирование (`planning`) — этап 8

Уточнён 06.10.2026 для вариантов расстановки (маршруты, зоны, трассы, проверки и расчёты — позже).
Все запросы — администратору здания (`manage`); факт (объекты, каталог) сервис спрашивает у `assets` и
`catalog` с токеном пользователя, применение выполняет `assets` от его имени.

**Вариант**: `{id, building_id, name, based_on, status: draft|applied, stale, stale_reasons[], last_result, version}`.
**Операция**: `{id, op: add|move|change|remove, asset_id, base_version, data}` — `base_version` — версия
объекта, против которой сделана операция; объект, изменённый в факте после неё, даёт конфликт.

| Запрос | Что делает |
|---|---|
| `GET /variants?building_id=`, `POST /variants` `{building_id, name, based_on}` | варианты здания; создать от факта или копией |
| `GET` / `PATCH` / `DELETE /variants/{id}` | вариант с операциями (у каждой — `conflict`), переименовать, удалить |
| `POST /variants/{id}/edits` | правки из редактора: `place`, `move`, `remove`, `note` над объектом факта (`asset_id`, `version`) или добавленным вариантом (`op_id`); у объекта факта — не больше одной операции каждого вида |
| `GET /variants/{id}/view?floor_id=` | объекты с наложенным вариантом |
| `GET /compare?building_id=&a=fact\|<id>&b=fact\|<id>` | что добавлено, убрано, перемещено, изменено; спецификации обеих сторон с ценами каталога |
| `GET /variants/{id}/spec` | спецификация варианта и разница с фактом |
| `POST /variants/{id}/apply` | выполнить операции через `assets`; выполненные уходят из варианта, отклонённые остаются с причиной (`last_result`) |
| `POST /placements` | `{building_id, type_id, floor_id|room_ids, count, where: along_wall|center|corners|grid|front_of|at_wall|at_point, side, along, anchor, companion_type_id, gap}` → места в помещениях (внутри контура, не на других предметах, не в дверях и проходах, не на перегородках; настенное — не над проёмами); `at_wall` — точное место на стене `side`: край предмета в `along` м от её начала (`from_end` — от конца) или start/middle/end, занятое сдвигается к ближайшему свободному с пометкой в `notes`; `at_point` — точка с проверкой, занятая заменяется ближайшей свободной в 2 м с причиной; ничего не ставит |
| `POST /layout-check` | `{building_id, floor_id, places: [{type_id, x, y, angle, room_id?}], moves: [{asset_id, x, y, angle?}]}` → по каждому предмету: помещение, что не так (вне помещений, в дверях, на перегородке, на предмете, настенное не на стене или над проёмом), стена рядом, на что смотрит, ближайшее свободное место `fix`; ничего не ставит |
| `POST /detectors` | `{building_id, type_id, floor_id|room_ids}` → по помещениям: есть, нужно (0,7·π·r² на извещатель), где добавить |
| `GET /coverage?building_id=&floor_id=` | обзор камер: доля площади помещения в обзоре, где различимо лицо, слепые места |
| `GET /checks?building_id=&floor_id=` | что стоит не так: в проходах и дверях, на перегородках, друг на друге, вне стен; пустые помещения; плохо просматриваемые; узкие двери |

Первоначальные границы:

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

Получает `assets.asset.*` (кроме смены ответственного) и `buildings.revision.published` (с новыми,
снятыми помещениями или сдвигом этажа) — помечает черновые варианты с операциями над этими объектами
или этажами устаревшими. Публикует `planning.variant.created` / `.applied` / `.deleted`.

## 10. Копилот (`copilot`) — этап 9

Подробно — [COPILOT.md](COPILOT.md). Работает только запросами остальных сервисов с токеном
пользователя; сам ничего не меняет — всё предлагает на одобрение: предложение со списком действий,
которое пользователь применяет кнопкой (объекты — с показом мест на плане этажа).

| Запрос | Что делает |
|---|---|
| `GET /status` | `{enabled, model, used_today, daily_limit, can_propose}` — показывать ли помощника |
| `GET` / `PUT /settings`, `POST /settings/check` | адрес, модель, ключ (назад не отдаётся), лимиты — админ системы; проверка связи |
| `GET /chats?building_id=`, `POST /chats`, `GET` / `DELETE /chats/{id}` | беседы пользователя |
| `POST /chats/{id}/messages` | `{text, ui}`; ответ потоком (SSE): `text`, `thinking`, `tool`, `proposal`, `ui`, `error`, `done` |
| `GET /proposals?building_id=&status=`, `GET /proposals/{id}` | предложения копилота |
| `POST /proposals/{id}/apply`, `POST /proposals/{id}/reject` | выполнить действия с токеном применяющего (админ здания); отклонить с причиной |

События: `copilot.proposal.created` / `.applied` / `.rejected` — `{proposal_id, chat_id, summary, actions}`.

## 11. Шлюз

Своих данных не хранит, кроме сессий входа.

| Адрес | Что делает |
|---|---|
| `/auth/login`, `/auth/callback`, `/auth/logout` | вход через Keycloak, сессия в cookie |
| `/api/<сервис>/v1/…` | пропускает запрос в сервис, подставляя токен |
| `GET /api/me` | учётная запись, человек (`people/me`), области (`access/me/scopes`) |
| `GET /api/views/cabinet?building_id=` | личный кабинет в здании: мои помещения, объекты, требующие внимания, объекты, за которые отвечаю; `partial` |
| ~~`GET /api/views/assets/{id}`, `/rooms/{id}`, `/floors/{id}/scene`~~ | не делались: карточку и план интерфейс собирает из ответов сервисов сам (`assets` уже отдаёт объект со схемой и правами); при отказе `people` карточка показывает пометку о неполных данных |
| `GET /api/reports/assets.xlsx?…` | список объектов по тем же фильтрам, что `assets` |
| `GET /api/reports/rooms/{id}/sheet.pdf` | ведомость помещения |
| `POST /api/reports/buildings/{id}/drawing` | `{format, drawing_id}` → чертёж с объектами; строится в запросе, без задачи (`import`: `POST /drawings/{id}/export`) |
| `GET /api/stream` | поток событий в браузер (SSE), отфильтрованный по правам субъекта |
| `GET /api/system/status` | состояние сервисов: отвечает ли, доступна ли база, подключён ли к шине — администратору системы |
| `GET /q/{code}` | QR-метка: без входа — на вход; затем на `#/q/{code}`, где интерфейс спрашивает `assets` (`/qr/{code}`) и открывает карточку или «нет доступа» |
| `GET /s/{token}` | гостевая ссылка: открывает её в `access`, заводит гостевой сеанс (cookie `twin_guest`) и переводит на `#/g`; недействительная — на `#/g?invalid=1`, `access` недоступен — на `#/g?unavailable=1` |

Поток событий: каждое сообщение — `id: <id события>` и `data: <конверт события в JSON>`; тип события —
внутри конверта. Пропущенное за время разрыва не досылается: после переподключения страница перечитывает то,
что показывает. До появления сервиса «Доступ» (этап 2) администратор системы получает все события, остальные —
только вызванные ими самими.

Гость по ссылке. Гостевой сеанс важнее сеанса пользователя в том же браузере: открыв ссылку, смотрят как гость,
`POST /auth/logout` заканчивает только гостевой просмотр. Шлюз хранит гостевой токен (10 минут) и сам продлевает
его в `access`, пока ссылка действует; отозванная или истёкшая ссылка заканчивает просмотр при ближайшем продлении —
ответ `401` с кодом `guest_ended`. `GET /api/me` гостю: `{kind: "guest", name, guest: {building_id, building_name,
scope, floor_id, expires_at}}`. Кабинет, отчёты, поток событий, состояние системы и QR-метки гостю — `403` с кодом
`guest`; запросы к сервисам идут с гостевым токеном, и каждый сервис отдаёт гостю только свою область: план, 3D
и объекты (без ответственных, примечаний и свойств-людей); люди, журнал, варианты, история, файлы, комментарии —
`403` или пусто.

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
| access | people, assets | только сверка автоматических назначений (своей учётной записью); права выдаются и проверяются без обращений |
| journal | access | права на чтение ленты |
| planning | access, assets, catalog | права; факт и цены; применение вариантов — с токеном пользователя (расчёты — позже, им понадобится и buildings) |
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
| planning | нет вариантов: учёт, кабинет и редактор (слой факта) работают |
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

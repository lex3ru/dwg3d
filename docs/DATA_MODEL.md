# Модель данных сервисов

> Состояние: черновик от 05.10.2026, к [ТЗ](TZ.md) и [контрактам](CONTRACTS.md).
> Таблицы каждого сервиса — его внутреннее дело: менять их можно без
> согласования с другими, пока не меняется контракт.

## 1. Общие правила

- Один сервер PostgreSQL 16, у каждого сервиса **своя база и своя роль**;
  роль не имеет прав на чужие базы. Разнести базы по серверам можно позже
  без изменения кода.
- Первичные ключи — `uuid` (версия 7, выдаёт приложение). Время —
  `timestamptz`. Перечисления — `text` с ограничением `CHECK`, не типы `ENUM`.
- Внешние ключи — только внутри базы. Идентификатор чужой сущности —
  обычный столбец `uuid` без ограничения, в таблицах ниже помечен «→ сервис».
- У изменяемых сущностей `version integer` — растёт при каждом изменении.
- Миграции — Alembic, у каждого сервиса свои.
- Файлы — в S3, у каждого сервиса своя корзина; в базе хранится только ключ.

### Служебные таблицы (в каждой базе)

**outbox** — события, ожидающие публикации

| Столбец | Тип | |
|---|---|---|
| id | uuid PK | он же `id` события |
| type | text | |
| payload | jsonb | конверт целиком |
| created_at | timestamptz | |
| published_at | timestamptz null | индекс по `created_at` где `published_at is null` |

Опубликованные строки удаляются через 7 дней.

**inbox** — обработанные события (защита от повторов)

| Столбец | Тип | |
|---|---|---|
| event_id | uuid | PK (event_id, handler) |
| handler | text | |
| processed_at | timestamptz | строки старше 35 дней удаляются |

**jobs** — долгие операции (там, где они есть)

| Столбец | Тип | |
|---|---|---|
| id | uuid PK | |
| kind | text | `build`, `export`, `import_xlsx`, `labels`… |
| status | text | `queued` \| `running` \| `done` \| `failed` |
| progress | real | 0…1 |
| message, error | text | `error` — понятный текст; трассировка — только в журнале сервера |
| params, result | jsonb | |
| requested_by | text | учётная запись |
| worker, heartbeat_at | | для подхвата зависших |
| created_at, started_at, finished_at | timestamptz | |

## 2. Доступ (`access`)

**subjects** — связь учётной записи с человеком (копия из «Людей»)

| Столбец | Тип | |
|---|---|---|
| user_sub | text PK | идентификатор в Keycloak |
| person_id | uuid unique | → people |

**grants**

| Столбец | Тип | |
|---|---|---|
| id | uuid PK | |
| person_id | uuid | → people |
| role | text | `viewer` \| `responsible` \| `admin` |
| scope_kind | text | `building` \| `floor` \| `room` \| `asset` |
| scope_id | uuid | → buildings / assets |
| building_id | uuid | → buildings; здание, внутри которого область |
| origin | text | `manual` \| `assignment` \| `responsible` |
| created_by | text | учётная запись или имя сервиса |
| created_at | timestamptz | |

- Уникальность: `(person_id, role, scope_kind, scope_id, origin)` — ручное и
  автоматическое назначение на одну область существуют независимо, и отзыв
  одного не снимает другое.
- Индексы: `(person_id)`, `(scope_kind, scope_id)`, `(building_id)`.
- Отозванное назначение удаляется; история — в «Журнале».

**shares** — гостевые ссылки

| Столбец | Тип | |
|---|---|---|
| id | uuid PK | |
| token_hash | text unique | сам токен не хранится |
| scope_kind, scope_id, building_id | | область |
| note | text | для кого ссылка |
| expires_at | timestamptz | обязателен, не дальше года |
| revoked_at | timestamptz null | |
| opens | integer | счётчик открытий |
| last_opened_at | timestamptz null | |
| created_by, created_at | | |

**signing_keys** — ключи подписи гостевых токенов: `kid PK`, `private_key`
(зашифрован ключом из настроек сервиса), `created_at`, `retired_at`.
Меняются раз в 90 дней, старый действует ещё сутки.

## 3. Здание (`buildings`)

**buildings**

| Столбец | Тип | |
|---|---|---|
| id | uuid PK | |
| name, address | text | |
| site | jsonb null | широта, долгота, азимут, масштаб |
| facade | jsonb null | ключ GLB и выравнивание |
| version | integer | |
| created_by, created_at, updated_at | | |
| deleted_at | timestamptz null | удаление мягкое, 30 дней |

**drawings** — чертежи в составе здания (сам файл — у «Импорта»)

| Столбец | Тип | |
|---|---|---|
| id | uuid PK | → import, тот же идентификатор |
| building_id | uuid FK | |
| name | text | |
| placement | jsonb | сдвиг, поворот, масштаб относительно системы координат здания |
| current_revision_id | uuid null FK | |
| sort | integer | |

**revisions**

| Столбец | Тип | |
|---|---|---|
| id | uuid PK | |
| building_id, drawing_id | uuid FK | |
| build_id | uuid | → import |
| n | integer | номер по порядку в чертеже; уникален с `drawing_id` |
| status | text | `draft` \| `published` \| `discarded` |
| matches | jsonb | сопоставление: новое помещение ↔ прежнее, с оценкой и признаком ручной правки |
| summary | jsonb | сколько создано, изменено, снято |
| created_at, published_at, published_by | | |

У чертежа не больше одного черновика (частичный уникальный индекс по
`drawing_id` где `status = 'draft'`).

**floors**

| Столбец | Тип | |
|---|---|---|
| id | uuid PK | сохраняется между ревизиями |
| building_id, drawing_id | uuid FK | |
| anchor | jsonb | признаки, по которым этаж узнаётся в новой ревизии |
| name | text | |
| level | integer | номер этажа; уникален в здании среди действующих |
| elevation, height | double | метры |
| model_key | text | 3D-модель этажа в S3 |
| status | text | `active` \| `retired` |
| revision_id | uuid FK | ревизия, из которой текущая геометрия |

**floor_plans** — геометрия плана, отдельно от `floors`, потому что большая

| Столбец | Тип | |
|---|---|---|
| floor_id | uuid PK FK | |
| revision_id | uuid FK | |
| data | jsonb | стены, проёмы, лестницы, лифты, входы — в координатах здания |

**rooms**

| Столбец | Тип | |
|---|---|---|
| id | uuid PK | сохраняется между ревизиями |
| building_id, floor_id | uuid FK | |
| name, number | text | |
| type | text null | вид помещения (кабинет, коридор, санузел…) |
| area | double | м² |
| polygon | jsonb | контур с отверстиями |
| label_point | jsonb | точка подписи |
| anchor | jsonb | признаки для узнавания в новой ревизии |
| manual | text[] | поля, исправленные вручную: новая ревизия их не перезаписывает |
| status | text | `active` \| `retired` |
| retired_at | timestamptz null | |
| merged_into | uuid null FK rooms | наследник при объединении |
| revision_id | uuid FK | ревизия последнего изменения контура |
| version | integer | |

- Индексы: `(floor_id)` где `status = 'active'`; `(building_id, status)`;
  триграммный по `name || ' ' || number` для поиска.
- Снятые помещения не удаляются: на них могут ссылаться объекты, история и журнал.
- Поиск помещения по точке (`locate`) — в памяти по контурам этажа
  (shapely); PostGIS не нужен.

**pins**: `id`, `building_id`, `floor_id`, `kind` (вход, лифт, лестница,
своя), `x`, `y`, `z`, `title`, `note`, `auto` (найдена разбором чертежа),
`created_by`, `created_at`.

**comments**

| Столбец | Тип | |
|---|---|---|
| id | uuid PK | |
| building_id, floor_id | uuid FK | |
| target_kind | text | `point` \| `room` \| `asset` |
| target_id | uuid null | → rooms / assets |
| x, y | double null | для `point` |
| parent_id | uuid null FK | ответ на комментарий |
| body | text | |
| author_person_id | uuid | → people |
| resolved_at, resolved_by | | |
| created_at, updated_at, deleted_at | | |

Индексы: `(building_id, floor_id)`, `(target_kind, target_id)`.

## 4. Импорт чертежей (`import`)

**drawings**

| Столбец | Тип | |
|---|---|---|
| id | uuid PK | |
| building_id | uuid | → buildings |
| name | text | |
| config | jsonb | настройки разбора |
| edits | jsonb | правки 2D-редактора |
| edits_version | integer | |
| current_file_id | uuid FK | |
| created_by, created_at, deleted_at | | |

**drawing_files** — загруженные файлы, не изменяются

| Столбец | Тип | |
|---|---|---|
| id | uuid PK | |
| drawing_id | uuid FK | |
| n | integer | номер по порядку |
| filename | text | исходное имя |
| size | bigint | |
| sha256 | text | повторная загрузка того же файла не создаёт новый |
| storage_key | text | |
| uploaded_by, uploaded_at | | |

**builds**

| Столбец | Тип | |
|---|---|---|
| id | uuid PK | он же идентификатор задачи |
| drawing_id, file_id | uuid FK | |
| n | integer | |
| status, stage, progress, message, error, trace | | как в `jobs` |
| config, edits | jsonb | снимок на момент сборки |
| result | jsonb | этажи, помещения, проёмы, входы, предупреждения, ключи файлов |
| out_prefix | text | каталог сборки в S3 |
| worker, heartbeat_at, created_at, started_at, finished_at | | |

Хранятся последние 5 сборок чертежа и все, на которые ссылается
опубликованная ревизия (сообщает «Здание» событием `revision.published`).

**exports**: `id`, `drawing_id`, `build_id`, `format`, `params` (в том числе
присланные объекты), `status`, `storage_key`, `error`, `requested_by`,
`created_at`, `finished_at`, `expires_at` (файл живёт сутки).

S3: `drawings/<id>/files/<n>/<имя>`, `builds/<id>/floor_<n>.glb`,
`builds/<id>/model.ifc`, `exports/<id>/<имя>`.

## 5. Каталог (`catalog`)

**categories**: `id`, `name`, `color`, `sort`, `layer_kind` (к какому
инженерному слою относится раздел — для «Проектирования»).

**property_sets**: `id`, `name`, `description`, `version`, `updated_at`.

**properties** — свойства наборов и собственные свойства типов

| Столбец | Тип | |
|---|---|---|
| id | uuid PK | |
| owner_kind | text | `set` \| `type` |
| owner_id | uuid | набор или тип |
| key | text | латиницей, не меняется после создания |
| title | text | |
| kind | text | `text` \| `number` \| `date` \| `bool` \| `choice` \| `person` |
| unit | text null | |
| options | jsonb null | варианты для `choice`: `[{value, title}]` |
| required | boolean | |
| stored | text | `type` \| `asset` |
| editable_by | text | `system` \| `admin` \| `responsible` |
| sort | integer | |

Уникальность `(owner_kind, owner_id, key)`; приложение дополнительно
проверяет, что ключи не повторяются в развёрнутой схеме типа.

**types**

| Столбец | Тип | |
|---|---|---|
| id | uuid PK | |
| category_id | uuid FK | |
| name | text | |
| w, d, h | double | габариты, м |
| elevation | double null | высота установки по умолчанию |
| wall_mounted | boolean | |
| shape | text | условная фигура |
| color | text null | |
| model_key, model_rot | | GLB в S3 и поворот |
| container, portable | boolean | |
| values | jsonb | значения свойств с `stored = type` |
| params | jsonb null | расчётные параметры: обзор камеры, радио, извещатель, светильник |
| article, supplier | text null | |
| price, currency | numeric(12,2), char(3) | |
| tags | text | |
| active | boolean | |
| schema_version | integer | растёт при изменении схемы типа или любого его набора |
| version, sort, updated_at | | |

**type_sets**: `type_id FK`, `set_id FK`, `sort`; PK `(type_id, set_id)`.

Начальное наполнение (разделы, наборы «Учёт», «Медицинское изделие»,
«Мебель», типы) — из файла при первом запуске; правки каталога он не трогает.

> Сделано иначе (этап 3): свойства хранятся списком в самом наборе и в самом типе
> (`properties` — jsonb), отдельной таблицы `properties` и таблицы `type_sets` нет: наборы
> типа — массив идентификаторов по порядку. Свойство нигде не ищется отдельно от схемы.

## 6. Объекты (`assets`)

**assets**

| Столбец | Тип | |
|---|---|---|
| id | uuid PK | |
| type_id | uuid | → catalog |
| type_name, category_id | | копия из каталога — для поиска и фильтров |
| schema_version | integer | схема, по которой проверены `props` |
| building_id, floor_id, room_id | uuid | → buildings |
| x, y | double null | метры; пусто у вложенного |
| angle | real | |
| elevation | double null | |
| container_id | uuid null FK assets | |
| inventory_no | text | уникален |
| serial_no | text null | |
| state | text | `in_use` \| `faulty` \| `in_repair` \| `in_storage` \| `retired` |
| responsible_id | uuid null | → people |
| props | jsonb | значения свойств с `stored = asset` |
| note | text null | |
| needs_placement | boolean | помещение снято или точка оказалась вне контура |
| needs_fill | boolean | свойства не проходят текущую схему |
| qr_code | text unique | 10 знаков, случайный, не меняется |
| version | integer | |
| created_by, created_at, updated_by, updated_at | | |
| retired_at | timestamptz null | |

Ограничения:

- `inventory_no` уникален по всей таблице, включая списанные: номера не
  используются повторно.
- либо `container_id`, либо координаты: `(container_id is null) = (x is not null)`.
- контейнер сам не вложен и стоит в том же помещении — проверяет приложение
  в той же транзакции.

Индексы: `(room_id)`, `(floor_id)`, `(building_id, state)`, `(type_id)`,
`(responsible_id)`, `(container_id)`; GIN по `props`; триграммный по
`type_name || ' ' || inventory_no || ' ' || coalesce(serial_no, '')`;
частичный `(building_id)` где `needs_placement`.

Списанный объект не удаляется: остаётся с `state = retired`, из обычных
списков исключён, по прямой ссылке и в истории доступен.

**asset_history** — только добавление

| Столбец | Тип | |
|---|---|---|
| id | uuid PK | |
| asset_id | uuid FK | |
| at | timestamptz | |
| actor_kind | text | `user` \| `service` |
| actor_id | text | учётная запись или сервис |
| actor_person_id | uuid null | → people |
| action | text | `created` \| `changed` \| `moved` \| `state` \| `responsible` \| `file_added` \| `file_removed` \| `retired` \| `reverted` \| `system` |
| changes | jsonb | `{поле: [было, стало]}` |
| reverts | uuid null FK | какую запись откатывает |
| reason | text null | для системных: «помещение снято в ревизии…» |

Индекс `(asset_id, at desc)`. Запись истории и изменение объекта — в одной
транзакции. Откат применяет обратные изменения только к тем полям, которые
с тех пор не менялись; иначе `409`.

**asset_files**: `id`, `asset_id FK`, `kind` (`photo` | `document`), `name`,
`mime`, `size`, `storage_key`, `thumb_key` (уменьшенная копия фото),
`uploaded_by`, `uploaded_at`, `deleted_at`.

**type_schemas** — копия схем из каталога

| Столбец | Тип | |
|---|---|---|
| type_id | uuid PK | → catalog |
| schema_version | integer | |
| name, category_id | | |
| container, portable, archived | boolean | |
| schema | jsonb | развёрнутый список свойств |
| type_props | jsonb | свойства, хранимые у типа, со значениями — для карточки объекта |
| updated_at | timestamptz | |

## 7. Люди (`people`)

**persons**

| Столбец | Тип | |
|---|---|---|
| id | uuid PK | |
| full_name | text | |
| position, department | text null | |
| email, phone | text null | |
| user_sub | text null unique | учётная запись Keycloak |
| status | text | `active` \| `left` |
| left_at | timestamptz null | |
| version | integer | |
| created_by, created_at, updated_at | | |

Индексы: `lower(email)` — для связывания при первом входе; триграммный по
`full_name`; `(department)`.

Выбывший человек не удаляется (на него ссылаются история и журнал); через
срок, заданный в настройках, контакты очищаются, остаются имя и должность.

**assignments** — привязка к помещению

| Столбец | Тип | |
|---|---|---|
| person_id | uuid FK | PK (person_id, room_id) |
| room_id | uuid | → buildings |
| building_id, floor_id | uuid | → buildings |
| workplace_asset_id | uuid null | → assets |
| created_by, created_at | | |

Индексы: `(room_id)`, `(building_id)`.

## 8. Журнал (`journal`)

**events** — только добавление, секции по месяцам (`time`)

| Столбец | Тип | |
|---|---|---|
| id | uuid | PK (id, time) |
| type | text | |
| time | timestamptz | время события |
| actor_kind, actor_id, actor_person_id | | |
| building_id, floor_id, room_id, asset_id, person_id | uuid null | область события — из конверта |
| subject_kind, subject_id | | |
| data | jsonb | |
| received_at | timestamptz | |

Индексы (в каждой секции): `(building_id, time desc)`, `(room_id, time desc)`,
`(asset_id, time desc)`, `(person_id, time desc)`, `(actor_person_id, time desc)`,
`(type, time desc)`.

Срок хранения — настройка (по умолчанию 5 лет); устаревшие секции удаляются целиком.

## 9. Проектирование (`planning`) — этап 8

Уточняется перед этапом. Ожидаемые таблицы:

- **variants**: `id`, `building_id`, `name`, `based_on` (вариант-источник),
  `status` (`draft` | `applied` | `stale`), `created_by`, `version`.
- **variant_ops**: `id`, `variant_id`, `op` (`add` | `move` | `change` | `remove`),
  `asset_id` (для существующих), `data` (тип, место, свойства), `sort`.
- **shapes**: маршруты, зоны, трассы — `id`, `building_id`, `variant_id null`,
  `kind`, `floor_id`, `points`, `props`, `version`.
- **room_cache**, **asset_cache** — копии для расчётов, обновляются по событиям.

## 10. Копилот (`copilot`) и шлюз

- copilot: **chats** (`id`, `user_sub`, `building_id`, `title`), **messages**
  (`chat_id`, `role`, `content`, `tool_calls`, `at`), **settings** (адрес,
  модель; ключ зашифрован).
- шлюз: **sessions** (`token_hash PK`, `user_sub`, зашифрованные токены
  Keycloak, `user_agent`, `created_at`, `last_seen_at`).

## 11. Копии чужих данных и сверка

Сервисы намеренно держат у себя копии того, чем владеют другие:

| Где | Что | Чьё | Обновляется |
|---|---|---|---|
| access.subjects | учётная запись ↔ человек | people | `person.linked` / `.unlinked` |
| access.grants.building_id | здание области | buildings, assets | `asset.moved`, `room.merged` |
| buildings.drawings | состав чертежей | import | `drawing.uploaded` / `.deleted` |
| assets.type_schemas, type_name, category_id | схема и название типа | catalog | `type.*`, `property_set.changed` |
| assets.building_id, floor_id, room_id | место | buildings | при перемещении; `room.merged` / `.split` |
| people.assignments.building_id, floor_id | место | buildings | `room.merged` / `.retired` |
| journal.events | всё | все | все события |

Событие может потеряться из-за ошибки в обработчике, поэтому у каждого
сервиса есть **сверка** — задача раз в сутки и по кнопке администратора
системы:

- access: назначения на несуществующих людей, помещения, объекты;
  ответственные по `assets` без назначения и наоборот.
- assets: объекты в несуществующих или снятых помещениях без
  `needs_placement`; схемы, отставшие от каталога.
- people: привязки к снятым помещениям.

Сверка только чинит копии и пишет расхождения в журнал сервера; чужие
данные не меняет.

## 12. Объём и резервные копии

| Таблица | Ожидаемый объём |
|---|---|
| rooms | до 20 000 (20 зданий) |
| assets | до 50 000 |
| asset_history | до 2 млн за 5 лет |
| persons | до 5 000 |
| grants | до 100 000 |
| journal.events | до 5 млн за 5 лет |

Специальных решений (шардирование, отдельные хранилища) объём не требует.

Резервная копия — ежедневно: все базы одним согласованным по времени
проходом (`pg_dump` каждой базы подряд) и корзины S3. Восстанавливать базы
можно по отдельности; после восстановления одной базы запускается сверка.

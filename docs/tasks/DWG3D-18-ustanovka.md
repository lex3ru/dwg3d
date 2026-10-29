---
id: DWG3D-18
title: Установка — сборка образа, журналы контейнеров, откат обновления
status: done
owner: Yury Mikhailov
branch: DWG3D-18-ustanovka
mr: https://git.mosai.pro/tristanov.ab/dwg3d/-/merge_requests/18
plane: https://plane.mosai.pro/mosai/projects/8f656022-6097-4c22-8b21-3d9a197dfe4a/issues/e49a39b0-ea98-432f-8af1-2e4fbe987df2
updated: 2026-10-29
---

# DWG3D-18: Установка — сборка образа, журналы контейнеров, откат обновления

## Цель

Находки R-037, R-038 (оставшаяся часть) и R-039 из ревью 21.10.2026 (подзадача DWG3D-1).
Сборка образа зависит от того, что лежит в интернете в момент сборки: архив LibreDWG не
сверяется с контрольной суммой, базовые образы берутся по плавающим тегам — каждое обновление
может собрать немного другую систему. В образ могут попасть данные разработки
(`server/.dev-data`, `server/.volume-data`). Журналы контейнеров растут без предела и со
временем займут диск. Если обновление не поднялось, как вернуть прежнюю версию — нигде не
описано. Решить в задаче: закрепить образы на Debian 12 или переехать на Debian 13 — образы uv
для Debian 12 больше не выходят.

## Критерии готовности

- [x] Архив LibreDWG проверяется по sha256; с неверной суммой сборка падает (на 4,5 с, до
      распаковки).
- [x] Базовые образы в `deploy/Dockerfile` и `deploy/compose.yml` (и `deploy/backup/Dockerfile`)
      закреплены дайджестами; в INSTALL — «Базовые образы (для разработчиков)».
- [x] Данные разработки не попадают в образ: `.dockerignore` — белый список, проверен
      настоящим контекстом сборки и содержимым `/app` в образе.
- [x] У всех служб `compose.yml` журналы ограничены по размеру: `x-logging`, на стенде
      `docker inspect` у всех пяти контейнеров.
- [x] В INSTALL есть раздел «Если обновление не удалось»: вернуть прежнюю версию и
      восстановить копию, сделанную перед обновлением; версии отмечаются тегами (ADR-0023).
      Откат проверен на стенде: сломанная миграция и «не собралось».
- [x] Выбор Debian 12 / Debian 13 — ADR-0022 (Debian 13).
- [x] Сценарий каждой находки покрыт тестом, который до исправления падал (R-033):
      `test_deploy.py` (4 из 5 падали на `main`); `test_r037_*` — на `1b7bd6a` падает
      (`restore.sh` удалял текущую базу до копии); откат и битая копия — стенд, первый прогон
      воспроизвёл падение `restore.sh`.
- [x] В FINDINGS у R-037, R-038, R-039 — «исправлена (!18)», `launch.json` — отклонено с
      причиной.
- [x] Справка и `docs/` обновлены (INSTALL, architecture, ACCEPTANCE, ADR-0001); CI
      зелёный: конвейер 1526 (`420d7cd`, последний коммит с кодом) — `server`, `web`, `e2e`,
      `agent-files`.

## План

- [x] 1. Тест, который падает: `server/tests/test_deploy.py` (как `test_serve.py` читает
      `deploy/compose.yml`) — каждый `FROM` в `deploy/Dockerfile`, `deploy/backup/Dockerfile`
      и каждый `image:` в `compose.yml` — `тег@sha256:…`; архив LibreDWG проверяется
      `sha256sum -c` до распаковки; у каждой службы `compose.yml` — `logging` с `max-size` и
      `max-file`; правила `.dockerignore` не пускают в контекст `server/.dev-data`,
      `server/.volume-data`, `server/tests`, `.env` и пускают `server/app`, `migrations`,
      `web/src`. На `main` падает: 4 из 5 (пятый — проверка разбора правил `.dockerignore`).
- [x] 2. Debian 12 или 13 — ADR-0022. Проверить на Debian 13: сборка LibreDWG, пакеты Pango и
      шрифтов для WeasyPrint, uv-образ нужной версии.
- [x] 3. `deploy/Dockerfile`: базовые образы — `тег@sha256`, архив LibreDWG — в файл,
      `LIBREDWG_SHA256` и `sha256sum -c`, потом распаковка. Сборка с неверной суммой падает —
      вывод в «Решения и находки».
- [x] 4. `compose.yml` и `deploy/backup/Dockerfile`: `postgres`, `caddy` — по дайджесту; общий
      якорь `x-logging` (json-file, 20m × 5) у всех служб. `test_deploy.py` зелёный;
      `docker inspect` показывает ограничения журналов у запущенных контейнеров (на стенде
      шага 8).
- [x] 5. `.dockerignore` — белый список: `server/app`, `server/migrations`, `server/alembic.ini`,
      `server/pyproject.toml`, `server/uv.lock`, `web/` без `node_modules` и `dist`. В собранном
      образе нет `.dev-data`, `.volume-data`, `tests`, `tools`.
- [x] 6. CI на той же версии Debian, что образ: `UV_RELEASE` и образ uv в `.gitlab-ci.yml`,
      сумма архива uv для `e2e`; ADR-0001 — последствия. pytest в образе CI локально зелёный,
      с тестами PDF: 225 passed, 3 skipped (чертежи заказчика и LibreDWG — как всегда).
- [x] 7. Откат (R-037): `install.sh` запоминает установленную версию
      (`git describe --tags --always`), при обновлении печатает прежнюю версию и путь копии
      «перед обновлением», при неудачной сборке или запуске — команды отката. INSTALL:
      «Обновление базовых образов» и «Если обновление не удалось»; как ставятся теги версий —
      ADR-0023.
- [x] 8. Откат на стенде: клон в отдельном каталоге, свой `COMPOSE_PROJECT_NAME`, порты
      8081/8444, свои имена образов (не трогать стенд `planuchet`): установить версию A,
      завести данные, обновиться на B со сломанной миграцией → `install.sh` падает → шаги из
      INSTALL → работает A с данными из копии. Протокол — в «Решения и находки»; первый прогон
      нашёл ошибку `restore.sh` (исправлена), второй — откат прошёл.
- [x] 9. Документы и проверки: FINDINGS (R-037, R-038, R-039), `e2e/README.md` (стенд объёмов
      собирается из того же Dockerfile — команды не изменились), `architecture.md`,
      `ACCEPTANCE.md`; проверки как в CI — зелёные; e2e на образе из `deploy/Dockerfile`
      (Debian 13 за Caddy, 61 passed), DWG — образцы LibreDWG через `to_dxf` в образе.
- [x] 10. `finish`: описание MR по шаблону, черновик снят, ADR-0022 и ADR-0023 — «принято»,
      в `glossary.md` — «Версия установки» и «Копия перед обновлением». После merge — тег
      `v0.1.0` на `main` (ADR-0023): шаг сопровождающего, не этого MR.

## Решения и находки

<!-- ГГГГ-ММ-ДД — что решили и почему; что пробовали и отвергли. Архитектурное → ADR. -->

- 2026-10-29 — выбрано с пользователем: образ и CI переезжают на Debian 13 (trixie) — образы
  uv для Debian 12 не выходят с 0.9.30, у Debian 12 уже только LTS; оформить ADR-0022 после
  проверки сборки LibreDWG и Pango на trixie (шаг 2).
- 2026-10-29 — выбрано с пользователем: версии отмечаются семантическими тегами `vX.Y.Z`; что
  считать мажорным и минорным изменением — в ADR-0023 (шаг 7). Первый тег — `v0.1.0` после
  merge этого MR, `v1.0.0` — версия, принятая заказчиком (выбор пользователя). Тексты
  ADR-0022 и ADR-0023 показаны пользователю и одобрены.
- 2026-10-29 — `test_deploy.py` на `74d00fb` (deploy как в `main`): не закреплены 7 образов
  (`debian:bookworm-slim`, `node:24-alpine`, `ghcr.io/astral-sh/uv:python3.12-bookworm-slim`,
  `python:3.12-slim-bookworm`, `postgres:16-alpine` в `backup/Dockerfile` и `compose.yml`,
  `caddy:2.10-alpine`); нет `LIBREDWG_SHA256`; у `db` (и остальных) нет `logging`; в контекст
  сборки идут `server/.dev-data`, `server/.volume-data`, `server/tools`, `server/.env`,
  `web/.env.local`. Разбор правил `.dockerignore` в тесте — упрощённый, как у Docker
  (последнее совпавшее правило, правило про каталог — на всё внутри); сверить с настоящим
  контекстом сборки в шаге 5.
- 2026-10-29 — LibreDWG 0.14: сумма архива `62ebb73b…81275` совпала с суммой GitHub, подпись
  `.sig` проверена ключом Reini Urban (`38A4167B0DB69E49C5F7216CB8C28866AB27A7A2`, с
  keyserver.ubuntu.com, во временной связке ключей). uv — 0.12.24 (08.10.2026, последний
  выпуск 0.12; 0.13.0 вышла 09.10 и за 18 дней получила шесть исправлений); сумма архива для
  `e2e` — из `.sha256` релиза, совпала с суммой GitHub. Дайджесты — списков платформ
  (`docker buildx imagetools inspect`), не одной amd64.
- 2026-10-29 — образ на Debian 13 (`planuchet-app:dwg3d-18`, сборка 6 мин 52 с): Debian 13.7,
  Python 3.12.16 (в образе uv — 3.12.15, `.venv` работает), `dwg2dxf 0.14`, WeasyPrint 70.0
  печатает PDF с кириллицей (Pango 1.56.3, HarfBuzz 10.2.0, DejaVu 2.37); в `/app` — только
  `.venv`, `alembic.ini`, `app`, `migrations`, `pyproject.toml`, `uv.lock`, `web`.
- 2026-10-29 — неверная сумма: `--build-arg LIBREDWG_SHA256=000…0` → «sha256sum: WARNING: 1
  computed checksum did NOT match», `/tmp/libredwg.tar.xz: FAILED`, сборка падает на 4,5 с,
  до распаковки; образ не создан.
- 2026-10-29 — настоящий контекст сборки (`COPY . /ctx` и `find` с новым `.dockerignore`):
  `server/{alembic.ini,app,migrations,pyproject.toml,uv.lock}` и `web/` без `node_modules`,
  `dist`, `tsconfig.tsbuildinfo` — 331 файл; совпадает с разбором правил в `test_deploy.py`.
- 2026-10-29 — задание `server` локально, как в CI: образ
  `ghcr.io/astral-sh/uv:0.12.24-python3.12-trixie-slim`, пакеты Pango из `before_script`,
  `postgres:16-alpine` в своей сети, `CI=true` (тесты PDF не пропускаются), копия рабочего
  дерева (`git stash create` + `git archive`): ruff чистый, pytest 225 passed, 3 skipped за
  4 мин 34 с. WeasyPrint предупреждает «HarfBuzz-Subset will be required by future versions»
  (`libharfbuzz-subset0` не ставится ни в образе, ни в CI) — пока только предупреждение.
- 2026-10-29 — стенд отката: WSL Ubuntu (тот же Docker Engine), клон ветки в `~/dwg3d18-otkat`,
  теги только в клоне (A = `v9.0.0` — ветка, B = `v9.1.0` — миграция `9001` создаёт
  `core.otkat_probe` со строкой, затем `serve` падает), `COMPOSE_PROJECT_NAME=planuchet-otkat`,
  порты 8081/8444, свои имена образов в неотслеживаемом `deploy/compose.override.yml`. Стенд
  `planuchet` не тронут. Ловушка: `wsl -- bash -lc '…'` раскрывает `$…` во внешней оболочке —
  только `wsl --exec`.
- 2026-10-29 — прогон 1 (A = `3e5a292`): у всех пяти контейнеров `json-file`
  `{"max-file":"5","max-size":"20m"}`. Обновление на B: копия перед обновлением, сборка,
  `up --wait` не завис — «container planuchet-otkat-app-1 is unhealthy», `install.sh` напечатал
  `git checkout v9.0.0` и `restore.sh <копия>`; в базе — `9001` и строка B, `.version` —
  по-прежнему `v9.0.0`. Откат по INSTALL **упал**: `pg_restore --clean --if-exists` —
  «cannot drop schema core because other objects depend on it… table core.otkat_probe»,
  «errors ignored on restore: 2», `restore.sh` вышел с ошибкой, система выключена, база —
  смесь двух версий. `--clean` удаляет только объекты из копии. Исправлено в `1b7bd6a`: база
  пересоздаётся (`dropdb --force`, `createdb`), `pg_restore --exit-on-error`; `install.sh`
  первым шагом отката печатает сохранение журнала.
- 2026-10-29 — прогон 2 (стенд снесён: `down -v`, копии; A = `1b7bd6a`, установка 26 с из
  кэша): «Поликлиника» — `0016`, 3 этажа, 69 помещений, 324 записи журнала, 79 файлов.
  Обновление на B: `install.sh` — код 1 за 14 с, напечатал по порядку сохранение журнала,
  `git checkout v9.0.0`, `docker compose build && ./restore.sh …/daily/2026-10-29_212507`.
  Шаги из INSTALL как есть — 23 с, всё здорово: `0016`, `core.otkat_probe` нет, 3 / 69 / 324,
  79 файлов (как в копии), `.version` и `git describe` — `v9.0.0`, HTTPS 200, http → 301 на
  https; в `update-failed.log` — причина сбоя B; в журнале `app` — ни одной ошибки, кроме
  fontconfig (ниже).
- 2026-10-29 — прогон 3, «не собралось» (C = `v9.2.0`, неверная `LIBREDWG_SHA256`): копия,
  сборка падает на сверке суммы, `install.sh` — код 1, «сборка не удалась, система работает
  на прежней версии», `git checkout v9.0.0`; система всё это время отвечает 200, контейнеры
  прежние.
- 2026-10-29 — DWG на Debian 13: образцы из подписанного архива LibreDWG (`example_r14`,
  `example_2007`, `sample_2018`) через `drawing.read.to_dxf` в образе — DXF 805 КБ, 1,4 МБ,
  78 КБ.
- 2026-10-29 — e2e целиком на стенде отката (образ из `deploy/Dockerfile`, Debian 13, за
  Caddy по HTTPS, `E2E_URL=https://localhost:8444`, временный пароль — `reset-password`):
  61 passed, 9 skipped (замеры объёмов без `E2E_VOLUME`) за 4,2 мин.
- 2026-10-29 — на ревью (вопрос пользователя «не риск ли потери данных?»): исправление
  `1b7bd6a` удаляло текущую базу (`dropdb --force`) до того, как `pg_restore` открывал копию.
  Битая копия стоила бы данных; прежний `pg_restore --clean` на нечитаемом файле падал, ничего
  не удалив. Решено с пользователем: копия — в отдельную базу `app_restore`, пока система
  работает; подмена переименованием `app` → `app_before_restore`, `app_restore` → `app`
  одной транзакцией (на PostgreSQL 16 проверено: сбой второго переименования откатывает
  первое); прежняя база удаляется после удачного `up --wait`, при неудачном — `restore-db.sh
  undo`. Логика — `deploy/backup/restore-db.sh` в образе `backup` (одинарные кавычки SQL в
  `sh -c '…'` внутри `restore.sh` не вкладываются). Файлы по-прежнему: удалить и скопировать —
  при сбое восстановление повторяется из той же копии; копировать рядом — удвоение места под
  файлы, отвергнуто.
- 2026-10-29 — прогон 4 (A = `b1eaa5f`, затем `cca12e7`): копия K, затем битые копии —
  4 КБ мусора вместо `db.dump` («input file does not appear to be a valid archive») и
  половина `db.dump` («could not read from input file: end of file»): `restore.sh` — код 1,
  «Копия базы не восстановилась — текущая база не тронута», база та же (3 / 69 / 324),
  система отвечает 200, `app_restore` не осталось. Удачное восстановление K после второй
  «Поликлиники» (6 / 138 / 332 → 3 / 69 / 324) — 15 с, базы — только `app`. `load` + `swap` +
  `undo` — прежняя база вернулась (6 / 138 / 332). Удачное обновление A → A′, затем B со
  сломанной миграцией (`9001`, 502) → шаги из INSTALL — 29 с: `0016`, данные на момент
  обновления (6 / 138 / 332), `core.otkat_probe` нет, базы — только `app`, 79 файлов, 200.
- 2026-10-29 — замечено, не в этой задаче: при печати PDF fontconfig пишет «No writable cache
  directories» (12 строк на процесс) — `HOME=/app` принадлежит root, кэш шрифтов не пишется и
  строится заново в каждом процессе. Так же было на Debian 12 (fontconfig 2.14) — не следствие
  переезда. Та же причина у ezdxf: «Cannot create cache home directory: '/app/.cache/ezdxf'».
  В журнале `app` — 16 таких строк при каждом запуске. Лечится каталогом кэша, доступным
  пользователю `app` (`XDG_CACHE_HOME`), — отдельной задачей.
- 2026-10-29 — `.claude/launch.json` ссылается на `legacy/.tools/libredwg` (R-038), но
  AGENTS.md велит устаревшие конфигурации не трогать, и в задаче Plane этого пункта нет: не
  правим, в FINDINGS — с причиной.
- 2026-10-29 — на машине разработчика запущен стенд `planuchet` (compose, образ
  `planuchet-app:latest`) для ручных прогонов: в `compose.yml` имена образов заданы жёстко,
  поэтому сборки и стенд отката — со своими тегами образов и `COMPOSE_PROJECT_NAME`, чтобы не
  подменить ему образ.
- 2026-10-29 — на сегодня: `ghcr.io/astral-sh/uv` — последний релиз 0.13.6 (27.10.2026),
  образы `python3.12-trixie-slim` выходят, `python3.12-bookworm-slim` остановлен на 0.9.30;
  `python:3.12-slim-trixie`, `debian:trixie-slim` есть.

## Журнал сессий

<!-- Новые записи сверху: дата · кто · агент / модель · что сделано · коммиты · Entire-Checkpoint -->

- 2026-10-29 · Yury Mikhailov · Claude Code / Claude Opus 5.5 · по вопросу на ревью:
  `restore.sh` не трогает базу, пока копия не восстановлена (`restore-db.sh`: отдельная база,
  подмена переименованием, удаление после запуска, `undo`); тест `test_r037_*`; стенд —
  битые копии, удачное восстановление, `undo`, откат обновления; INSTALL, ADR-0023,
  FINDINGS · `373c3f4..` итоговый коммит.
- 2026-10-29 · Yury Mikhailov · Claude Code / Claude Opus 5.5 · finish: ADR-0022 и ADR-0023 —
  «принято», термины в `glossary.md`, итог задачи, описание MR, черновик снят · `6625c20..`
  итоговый коммит.
- 2026-10-29 · Yury Mikhailov · Claude Code / Claude Opus 5.5 · план и шаги 1–9: тест
  `test_deploy.py`; образ и CI на Debian 13 из закреплённых дайджестами образов, сумма
  LibreDWG, белый список `.dockerignore`, ротация журналов; `install.sh` помнит версию и
  печатает откат, `restore.sh` пересоздаёт базу (ошибку нашёл стенд); INSTALL, ADR-0022,
  ADR-0023, FINDINGS; стенд отката в WSL, e2e на образе · `74d00fb..19b7fa8` и handoff.

## Итог

**Сделано:** R-037, R-038 (остаток), R-039 исправлены.
- Образ и CI — на Debian 13 и uv 0.12.24 (ADR-0022). Базовые образы — по дайджесту в
  `deploy/Dockerfile`, `deploy/backup/Dockerfile`, `deploy/compose.yml`; архив LibreDWG
  сверяется с `LIBREDWG_SHA256` до распаковки; `.dockerignore` — белый список. Как обновлять —
  INSTALL, «Базовые образы».
- Журнал каждой службы — до 5 файлов по 20 МБ (`x-logging`).
- Версии — теги `vX.Y.Z`, обновление — `git checkout <тег>` (ADR-0023). `install.sh` пишет
  версию в `deploy/.version`, печатает «прежняя → новая» и путь копии перед обновлением, при
  сбое — команды отката. INSTALL — «Если обновление не удалось».
- `restore.sh` не трогает текущую базу, пока копия не восстановлена: копия — в отдельную базу,
  пока система работает, подмена переименованием, прежняя удаляется после удачного запуска
  (`deploy/backup/restore-db.sh`). С `pg_restore --clean` откат падал (нашёл стенд); битая
  копия теперь — ошибка без потери данных.
- Тест — `server/tests/test_deploy.py` (до исправлений падали). Откат и битая копия проверены
  на стенде (прогоны 1–4 в «Решениях и находках»), e2e на образе — 61 passed, pytest в образе
  CI — 225 passed, CI зелёный.

**За рамками:**
- Тег `v0.1.0` на `main` после merge — сопровождающий:
  `git tag -a v0.1.0 -m "…" && git push origin v0.1.0` (ADR-0023).
- fontconfig и ezdxf не могут писать кэш в `HOME=/app` (16 строк «No writable cache
  directories» при каждом запуске, кэш шрифтов строится в каждом процессе) — было и на
  Debian 12; WeasyPrint предупреждает, что скоро потребует `libharfbuzz-subset0`. Кандидаты в
  отдельную задачу Plane.
- `legacy/.tools` в `.claude/launch.json` (R-038) — отклонено: AGENTS.md велит устаревшие
  конфигурации не трогать.

**Ловушки:**
- В `compose.yml` имена образов жёсткие (`planuchet-app:latest`): вторая установка на той же
  машине Docker подменит образ первой. Для стенда — свой `COMPOSE_PROJECT_NAME` в `.env` и
  неотслеживаемый `deploy/compose.override.yml` с другими именами образов.
- `wsl -- bash -lc '…'` раскрывает `$…` во внешней оболочке: в WSL — только `wsl --exec`.
- Копии резервного копирования пишут контейнеры от root — удалять каталог копий стенда
  контейнером, не `rm`.
- Клон в WSL не берёт кэш сборки из рабочей копии Windows (другие права файлов): первый
  `npm ci` в образе там шёл 23 мин.
- Двойной `-q` у pytest (`addopts = "-q"` и `-q` в команде) прячет итоговую строку — для
  счёта тестов `-o addopts=""`.

**Как проверить:**

```bash
cd server && uv run pytest tests/test_deploy.py -q          # закрепление, сумма, журналы, контекст
docker build -f deploy/Dockerfile -t planuchet-app:check .  # не тегом latest, если рядом стенд
docker build --target libredwg --build-arg LIBREDWG_SHA256=$(printf '0%.0s' {1..64}) -f deploy/Dockerfile .  # должна упасть
```

Откат — по `docs/INSTALL.md`, «Если обновление не удалось»; как поднимали стенд — «Решения и
находки» (прогоны 1–3).

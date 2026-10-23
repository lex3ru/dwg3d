# Этап 0. Базовая линия

Коммит `e43c6a9`, 21.10.2026. Логи и отчёты — `artifacts/stage0/`.

## Итог

- **Код сервера по своим тестам зелёный** — в Linux с Pango: 97 passed, 3 skipped, покрытие 82 %.
- **CI красный целиком.** `server`: 7 тестов PDF падают — в образе нет Pango (R-005).
  `e2e`: 4 из 46 падают — 1 дефект интерфейса (R-007), 3 — дефекты тестов (R-008).
- **Новый дефект:** после применения проекта итог не показывается (R-007).
- **Зависимости:** Pillow 12.3.0 с 8 известными уязвимостями (R-004); npm — чисто.
- На Windows, где идёт разработка, 13 из 100 тестов сервера падают (R-006).

## Окружение

| | |
|---|---|
| Хост | Windows 11, Docker 29.4.1, uv 0.7.20, Python 3.12.7, Node 24.14.1, npm 11.11.0 |
| База разработки | контейнер `planuchet-devdb`, PostgreSQL 16.13, `127.0.0.1:55432` (как в README) |
| «Как CI» | сеть `review-ci`, `review-ci-db` (postgres:16-alpine), образ задания `ghcr.io/astral-sh/uv:python3.12-bookworm-slim`, копия `HEAD` (`git archive`) |
| E2E | образ `review-app:e43c6a9` из `deploy/Dockerfile` по копии `HEAD`; `review-e2e-app` (`127.0.0.1:18000`) и `review-e2e-worker`, база `e2e` в `review-ci-db`; Playwright 1.63 с Windows |

Стенд `planuchet-*` и образ `planuchet-app:latest` не тронуты.

## Результаты

| Проверка | Результат | Время | Файл |
|---|---|---|---|
| `ruff check app migrations tests` (0.17.1) | чисто | 1 с | `ruff.log` |
| `pytest` на Windows | 84 passed, **13 failed**, 3 skipped | 9 мин 25 с | `pytest.log`, `pytest.xml` |
| `pytest` в образе CI | 88 passed, **9 failed** (7 — Pango; 2 — моя копия без `docs/samples`), 3 skipped | 3 мин | `pytest-ci-linux.log`, `pytest-ci.xml` |
| `pytest` в образе CI + Pango + `docs/samples` | **97 passed**, 3 skipped | 2 мин 47 с | `pytest-linux-pango.log`, `pytest-pango.xml` |
| Покрытие (там же, `pytest-cov`, строки + ветви) | 82 % | — | `coverage.json`, `coverage-html/`, `coverage-summary.txt` |
| `tsc -b` | чисто | 12 с | `web-typecheck.log` |
| `oxlint src` (1.88) | чисто: 79 файлов, 96 правил | 1 с | `web-lint.log` |
| `vite build` | собрано | 3,4 с | `web-build.log` |
| Модульные тесты `web` | нет ни одного (R-003) | — | — |
| `pip-audit` по `uv.lock` | Pillow 12.3.0 — 8 CVE (R-004) | — | `pip-audit.log` |
| `npm audit` `web`, `e2e` | 0 | — | `npm-audit-*.json` |
| Устаревшие | мелкие отставания; крупные: react-router 7→8, typescript 6→7 (не обязательно) | — | `*-outdated.txt` |
| E2E, полный прогон | 35 passed, **4 failed**, 7 skipped (6 — стенд объёмов, 1 — без `E2E_PERF_BUILDING`) | 1,6 мин | `e2e.log`, `e2e-results/` |
| E2E, повтор упавших ×2 | a11y — проходит; stage4 «Предупреждения», stage8 С9 — падают снова | 1,9 мин | `e2e-rerun.log`, `e2e-rerun/` |
| Сборка образа | собран | 6 мин | `docker-build.log` |

Пропуски `pytest`: «Бастион» и дополнительные DWG — чертежей заказчика в репозитории нет
(`.gitignore`), LibreDWG локально нет. Перевод DWG проверяется только в образе.

## Разбор падений

| Где | Тест | Причина | Находка |
|---|---|---|---|
| CI-образ | 7 тестов PDF | нет `libpango` в образе задания | R-005 |
| Windows | 8 тестов PDF | нет GTK/Pango | R-006 (окружение) |
| Windows | `test_architecture` ×2, `test_base_catalog_comes_with_3d_models` | `read_text()` без `encoding` → cp1251 | R-006 |
| Windows | `test_files_are_checked_by_content…`, `test_not_a_drawing_is_refused` | `os.unlink` открытого файла (`files/api.py:83`) → 500 вместо 4xx | R-006 |
| Windows | `test_events::test_admin_receives_changes` | первым пришёл `ping`, а не событие — тест зависит от времени | этап 8 |
| e2e | a11y ×2 | на чистой базе нет зданий, `all[0]!` | R-008 |
| e2e | stage4 «Предупреждения…» | обрыв `POST /api/auth/password` при `goto` | R-008 |
| e2e | stage8 С9 | окно итога применения пропадает | **R-007** |

## Покрытие по модулям

| Модуль | Строк | Строки | Ветви |
|---|---:|---:|---:|
| building | 2 681 | 81,6 % | 66,5 % |
| inventory | 2 540 | 84,7 % | 66,7 % |
| catalog | 1 261 | 87,5 % | 74,0 % |
| reports | 398 | 91,5 % | 68,5 % |
| остальные модули и ядро | — | 92–96 % | 64–81 % |

Слабее всего: `building/drawing/convert.py` и `read.py` — 57 % (DWG-тесты пропущены),
`inventory/places.py` — 57 %, `inventory/units.py` — 70 %, `core/tasks.py` — 78 %.
Тестов 100 на ~19 тыс. строк — крупные сценарные; глубину проверок смотреть на этапе 8.

## Заметки для следующих этапов

- **Этап 1:** `test_architecture.py` не видит относительных импортов (`level > 0`) и формы
  `from app.modules import inventory` — обходы правила «только через api».
- **Этап 2:** доходят ли загруженные картинки до Pillow через WeasyPrint (важность R-004);
  `MAX_SIZE` в `files/api.py` — 300 МБ.
- **Этап 7:** «просмотру» в редакторе показан текст «Перетащите тип из каталога слева…» (ТЗ 2.3).
- **Этап 8:** `test_events` зависит от времени; в нескольких файлах по 1–2 теста.
- **Этап 10:** `oxlint` возвращает 0 при предупреждениях — CI на них не падает;
  `.dockerignore` не исключает `server/.dev-data`, `server/.volume-data`;
  `.claude/launch.json` ссылается на `legacy/.tools/libredwg` — в репозитории нет.

## Что оставлено работать

Для следующих этапов (проверки по API, повтор e2e):

```bash
docker ps --filter name=review- --filter name=planuchet-devdb
```

Убрать после ревью:

```bash
docker rm -f review-e2e-app review-e2e-worker review-ci-db planuchet-devdb && docker volume rm review-e2e-data && docker network rm review-ci && docker rmi review-app:e43c6a9
```

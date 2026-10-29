# Сценарии ТЗ — автоматические тесты (8.7 п. 2)

Playwright проходит сценарии С1–С22 (раздел 4) на работающей системе: по одному файлу на
этап (`tests/stage0.spec.ts` … `stage10.spec.ts`), доступность (`a11y.spec.ts`), замеры 8.2
(`perf.spec.ts`, `volume.spec.ts`).

```bash
npm ci
npx playwright install chromium
npx playwright test
```

## Куда и кем

| Переменная | Что | По умолчанию |
|---|---|---|
| `E2E_URL` | адрес системы: установленной (`https://…`) или интерфейса разработки | `http://localhost:5190` |
| `E2E_ADMIN`, `E2E_PASSWORD` | администратор | `admin`, `Dev-admin-pass1` |
| `E2E_TEMP_PASSWORD` | временный пароль администратора свежей базы: перед тестами он сменится на `E2E_PASSWORD` | — |

Тесты заводят свои здания и учётные записи с уникальными именами, поэтому идут и на базе,
где уже есть данные.

## Проекты

- «компьютер» — Chrome 1440 × 900, все сценарии, кроме помеченных `@телефон`;
- «телефон» — Pixel 7, только `@телефон` (обход, инвентаризация, сканер, размеры кнопок).

## Замеры 8.2

- `perf.spec.ts` — план и 3D (`E2E_PERF_BUILDING=<id здания>`), этаж с 2 000 предметов,
  расчёты. 3D мерится видеокартой машины с `E2E_GPU=1`; без неё Chromium рисует программно и
  медленнее человека.
- `volume.spec.ts` — на **стенде объёмов 8.1** (`python -m app sample volume` на отдельной
  установке, [docs/INSTALL.md](../docs/INSTALL.md)) с `E2E_VOLUME=1`: план, 3D, поиск,
  карточка, переходы, проведение документа на 100 строк, проверка Excel на 1 000 строк,
  отчёты и выгрузка, QR-метка на телефоне, 20 одновременных пользователей (8.1) и пик в 50 и
  200 одновременных запросов — без 500 и обрывов (R-036). Без `E2E_VOLUME` пропускается.

```bash
E2E_VOLUME=1 E2E_URL=http://localhost:8011 npx playwright test tests/volume.spec.ts
```

Одновременные запросы и пик имеет смысл мерить, как в установке: приложение в образе
`deploy/Dockerfile`, 4 процесса, ограничено 4 ядрами и 8 ГБ (8.2), — а не `python -m app serve`
в Windows, где процесс один (ADR-0007), и с обработчиком фоновых задач: ведомость стоимости
считает он (ADR-0021). Например, с базой `volume` в контейнере `planuchet-devdb`:

```bash
docker build -f deploy/Dockerfile -t planuchet-perf:dev .
docker network create planuchet-perf && docker network connect planuchet-perf planuchet-devdb
docker run -d --name planuchet-perf --network planuchet-perf --cpus 4 --memory 8g \
  -p 127.0.0.1:8020:8000 -e APP_SECURE_COOKIES=false \
  -e APP_DATABASE_URL=postgresql+psycopg://app:app@planuchet-devdb:5432/volume planuchet-perf:dev
docker run -d --name planuchet-perf-worker --network planuchet-perf --init \
  -e APP_DATABASE_URL=postgresql+psycopg://app:app@planuchet-devdb:5432/volume \
  planuchet-perf:dev python -m app worker
E2E_VOLUME=1 E2E_URL=http://127.0.0.1:8020 npx playwright test tests/volume.spec.ts -g "одновременных"
```

## Чистка базы разработки после прогонов

Тесты заводят здания, учётные записи, склады и типы с суффиксом прогона и не удаляют их.
`clean-dev-db.sql` убирает всё это вместе с документами, журналом и ненужными файлами,
оставляя «Поликлинику», «Лабораторный корпус» и «Тестовое» (список — в начале файла).
Сначала проба (в конце — ROLLBACK, видно, что и сколько удалится), затем по-настоящему:

```bash
(cat e2e/clean-dev-db.sql; echo 'ROLLBACK;') | docker exec -i planuchet-devdb psql -U app -d app -q
(cat e2e/clean-dev-db.sql; echo 'COMMIT;') | docker exec -i planuchet-devdb psql -U app -d app -q
```

Только для базы разработки, не для рабочей установки.

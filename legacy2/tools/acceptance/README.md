# Приёмка системы в целом

Инструменты для раздела 12 [docs/ACCEPTANCE.md](../../docs/ACCEPTANCE.md). Всё запускается из
корня репозитория на машине со стеком. Проверки нагрузки и восстановления идут на отдельных
стендах рядом с рабочим, со своими контейнерами, томами и портами, — рабочие данные они не
трогают.

| Файл | Что делает |
|---|---|
| `stack.sh` | запускает команду для отдельного стенда: `stack.sh <имя> <n> compose …` — интерфейс на порту 8090+n |
| `make_office.py` | чертёж офисного здания: 5 этажей, коридор и 20 кабинетов на этаж (105 помещений) |
| `seed.py` | наполняет стенд через API: 20 зданий, 50 000 объектов, 5 000 человек, 50 пользователей с правами |
| `load.py` | нагрузка: каждый пользователь входит своей учётной записью и ходит по своему зданию, как интерфейс |
| `probe.py` | попытки чужих пользователей и посторонних прочитать и изменить чужое — через шлюз и мимо него |
| `compare.py` | снимок стенда (строки и контрольные суммы таблиц, файлы хранилища), сравнение снимков, проверка связей между сервисами |
| `restore-test.sh` | копия одного стенда, восстановление на чистый, сверка, вход |

Пароли учётных записей, созданных `seed.py`, и идентификаторы зданий лежат в
`tools/acceptance/.state.json` (не в git); при каждом наполнении пароли новые.

## Порядок

```bash
cd e2e && npx playwright test                                   # 12.1: все сквозные сценарии подряд
```

```bash
tools/acceptance/stack.sh twin-accept 1 compose up -d --wait   # отдельный стенд на :8091
```

```bash
tools/acceptance/stack.sh twin-accept 1 uv run tools/acceptance/seed.py
```

```bash
tools/acceptance/stack.sh twin-accept 1 uv run tools/acceptance/load.py --users 50 --minutes 5   # 12.2
```

```bash
tools/acceptance/stack.sh twin-accept 1 uv run tools/acceptance/probe.py                         # 12.4
```

Обновление одного сервиса под нагрузкой (12.5): запустить `load.py --users 20 --minutes 2` и
во время него пересоздать сервис:

```bash
tools/acceptance/stack.sh twin-accept 1 compose up -d --no-deps --force-recreate --wait assets
```

Восстановление на чистый стенд (12.3), стенд `twin-restore` на :8092 создаётся заново:

```bash
tools/acceptance/restore-test.sh twin-accept 1 twin-restore 2
```

Проверка связей между сервисами на рабочем стенде (только чтение):

```bash
python3 tools/acceptance/compare.py check twin
```

Убрать отдельные стенды вместе с данными:

```bash
tools/acceptance/stack.sh twin-accept 1 compose down -v
```

```bash
tools/acceptance/stack.sh twin-restore 2 compose down -v
```

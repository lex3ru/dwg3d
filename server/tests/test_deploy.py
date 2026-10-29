"""Сборка и установка (deploy/, 9.3, 8.5): образ собирается из закреплённых базовых образов и
проверенного архива LibreDWG, данные разработки в него не попадают (R-038); журналы
контейнеров ограничены по размеру (R-039)."""

import re
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "deploy"
DOCKERFILES = [DEPLOY / "Dockerfile", DEPLOY / "backup" / "Dockerfile"]
# тег — для человека, дайджест — для сборки: «postgres:16-alpine@sha256:…»
PINNED = re.compile(r"[\w.\-/]+:[\w.\-]+@sha256:[0-9a-f]{64}")
SIZE = {"k": 1024, "m": 1024**2, "g": 1024**3}


def services() -> dict[str, Any]:
    compose = yaml.safe_load((DEPLOY / "compose.yml").read_text(encoding="utf-8"))
    return compose["services"]


def base_images(dockerfile: Path) -> list[str]:
    """Образы из строк FROM; «FROM <стадия>» — не базовый образ."""
    stages: set[str] = set()
    images: list[str] = []
    for line in dockerfile.read_text(encoding="utf-8").splitlines():
        found = re.match(r"FROM\s+(?:--platform=\S+\s+)?(\S+)(?:\s+AS\s+(\S+))?", line, re.I)
        if found:
            if found[1] not in stages:
                images.append(found[1])
            if found[2]:
                stages.add(found[2])
    return images


def test_r038_base_images_are_pinned_by_digest() -> None:
    """По плавающему тегу `build --pull` при каждом обновлении берёт новый образ — каждая
    установка собирает немного другую систему (R-038)."""
    images = [image for dockerfile in DOCKERFILES for image in base_images(dockerfile)]
    images += [s["image"] for s in services().values() if "build" not in s]
    assert len(images) >= 6
    assert [image for image in images if not PINNED.fullmatch(image)] == []


def test_backup_dumps_with_the_postgres_of_the_database() -> None:
    """pg_dump старше сервера не выгрузит базу: закрепляя образы, их не развести."""
    assert base_images(DEPLOY / "backup" / "Dockerfile") == [services()["db"]["image"]]


def test_ci_checks_on_the_debian_and_uv_of_the_image() -> None:
    """CI проверяет на той же версии Debian и uv, что собирает образ (ADR-0001, ADR-0022):
    иначе тесты PDF зелёные с одной Pango, а печатает другая."""
    ci = yaml.safe_load((ROOT / ".gitlab-ci.yml").read_text(encoding="utf-8"))
    images = base_images(DEPLOY / "Dockerfile")
    uv = next(i for i in images if i.startswith("ghcr.io/astral-sh/uv:")).split("@")[0]
    assert ci["server"]["image"].replace("$UV_RELEASE", ci["variables"]["UV_RELEASE"]) == uv
    debian = re.fullmatch(r".*-python3\.12-(\w+)-slim", uv)
    assert debian
    assert [i for i in images if "alpine" not in i and debian[1] not in i] == []


def test_r038_libredwg_archive_is_checked_before_unpacking() -> None:
    """Архив LibreDWG из интернета сверяется с суммой из Dockerfile до распаковки: с неверной
    суммой сборка падает (R-038)."""
    text = (DEPLOY / "Dockerfile").read_text(encoding="utf-8")
    assert re.search(r"^ARG LIBREDWG_SHA256=[0-9a-f]{64}$", text, re.M)
    run = next(r for r in re.split(r"^RUN ", text, flags=re.M) if "libredwg-${" in r)
    check = run.find("sha256sum -c")
    assert check >= 0 and "${LIBREDWG_SHA256}" in run
    assert "| tar" not in run
    assert check < run.index("tar -x")


def test_r039_every_service_limits_its_log() -> None:
    """У драйвера json-file по умолчанию нет предела: журнал uvicorn (строка на запрос, ошибки —
    со стектрейсом) рос на диске Docker без ограничения (R-039)."""
    for name, service in services().items():
        logging = service.get("logging", {})
        options = logging.get("options", {})
        assert logging.get("driver") == "json-file", name
        size = re.fullmatch(r"(\d+)([kmg])", options.get("max-size", ""))
        assert size and options.get("max-file", "").isdigit(), name
        assert int(size[1]) * SIZE[size[2]] * int(options["max-file"]) <= 200 * SIZE["m"], name


def ignored(path: str, rules: list[str]) -> bool:
    """Не попадёт ли путь в контекст сборки по правилам .dockerignore, как их читает Docker:
    решает последнее совпавшее правило («!» — исключение), правило про каталог касается
    всего, что в нём."""
    parts = path.split("/")
    result = False
    for rule in rules:
        pattern = rule.removeprefix("!").strip("/")
        regex = (re.escape(pattern).replace(r"\*\*/", "(?:.*/)?").replace(r"\*\*", ".*")
                 .replace(r"\*", "[^/]*").replace(r"\?", "[^/]"))
        if any(re.fullmatch(regex, "/".join(parts[:n])) for n in range(1, len(parts) + 1)):
            result = not rule.startswith("!")
    return result


def test_ignored_reads_rules_like_docker() -> None:
    rules = ["*", "!server/", "server/.venv", "**/__pycache__"]
    assert ignored("docs/TZ.md", rules)
    assert not ignored("server/app/main.py", rules)
    assert ignored("server/.venv/bin/python", rules)
    assert ignored("server/app/core/__pycache__/db.pyc", rules)


def test_r038_development_data_stays_out_of_the_image() -> None:
    """В контекст сборки идут только сервер и интерфейс, без данных разработки, тестов,
    окружения и настроек: `COPY server/ ./` в Dockerfile уносил в образ `server/.dev-data`
    и `server/.volume-data` из рабочей копии разработчика (R-038)."""
    rules = [line.strip() for line in (ROOT / ".dockerignore").read_text(encoding="utf-8")
             .splitlines() if line.strip() and not line.startswith("#")]
    inside = ["server/app/main.py", "server/app/modules/catalog/models3d/aspirator.glb",
              "server/migrations/env.py", "server/migrations/versions/x.py",
              "server/alembic.ini", "server/pyproject.toml", "server/uv.lock",
              "web/package.json", "web/package-lock.json", "web/index.html",
              "web/vite.config.ts", "web/src/main.tsx", "web/public/favicon.svg"]
    outside = ["server/.dev-data/files/ab/cd", "server/.volume-data/files/ab/cd",
               "server/tests/test_deploy.py", "server/tools/models3d.py",
               "server/.venv/bin/python", "server/.pytest_cache/v/x", "server/.env",
               "server/app/__pycache__/main.cpython-312.pyc", "web/node_modules/vite/x.js",
               "web/dist/index.html", "web/.env.local", "deploy/.env", "deploy/backups/x",
               "legacy/x", "docs/TZ.md", ".git/HEAD"]
    assert [p for p in inside if ignored(p, rules)] == []
    assert [p for p in outside if not ignored(p, rules)] == []

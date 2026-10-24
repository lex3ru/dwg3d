"""Документы учёта (5.4.4): черновик → проведён; проводится целиком или никак; проведённый
не правится — ошибка исправляется отменой, обратным документом со ссылкой на исходный."""

import uuid
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session

from app.core.actor import Actor
from app.core.errors import AppError, Conflict, NotFound, stale
from app.modules.catalog import api as catalog
from app.modules.inventory.models import (
    Cell,
    CountPlace,
    DocFile,
    DocLine,
    Document,
    StockMove,
    Unit,
    UnitEvent,
)
from app.modules.inventory.places import Place, Places, admin, is_storage, label_code
from app.modules.inventory.rules import KINDS, STATE_BY_TITLE, STATES, doc_title
from app.modules.inventory.units import Numbers, get_unit, value_now
from app.modules.journal import api as journal

LINE_FIELDS = (
    "unit_id",
    "type_id",
    "model_id",
    "qty",
    "price",
    "number",
    "serial",
    "responsible",
    "department",
    "state",
    "commissioned_on",
    "life_months",
    "note",
    "values",
    "from_place",
    "to_place",
    "reason",
    "new_value",
)
HEADER_FIELDS = (
    "date",
    "from_place",
    "to_place",
    "basis",
    "supplier",
    "contractor",
    "repair",
    "repair_cost",
    "reason",
    "note",
)


# Подписчики (связь с планом, 5.5): документ переместил или списал единицы — вызываются в
# той же транзакции
UnitsHook = Callable[[Session, Actor, list[Unit]], None]
_units_hooks: list[UnitsHook] = []


def on_units_changed(hook: UnitsHook) -> None:
    _units_hooks.append(hook)


def _units_changed(session: Session, actor: Actor, units: list[Unit]) -> None:
    if units:
        session.flush()
        for hook in _units_hooks:
            hook(session, actor, units)


def _d(v: Any) -> Decimal:
    return Decimal(str(v or 0))


# ---------------------------------------------------------------- очередь учёта (ADR-0003)

# ключ рекомендательной блокировки PostgreSQL; 7310001 — у миграций (app/__main__.py)
LEDGER_LOCK = 7310002


def lock(session: Session) -> None:
    """Встать в очередь учёта до конца транзакции: номера выдаёт и остатки меняет один сеанс
    за раз (8.3 п. 2). Повторный вызов в той же транзакции не ждёт."""
    session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": LEDGER_LOCK})


# ---------------------------------------------------------------- черновики


def get_document(
    session: Session, actor: Actor, doc_id: uuid.UUID, for_update: bool = False
) -> Document:
    """for_update — чтобы изменить: строка блокируется до конца транзакции и читается заново,
    даже если уже загружена, — сверка статуса и версии видит то, что записал другой сеанс."""
    admin(actor)
    doc = (
        session.get(Document, doc_id, with_for_update=True, populate_existing=True)
        if for_update
        else session.get(Document, doc_id)
    )
    if doc is None:
        raise NotFound("Документ не найден.")
    return doc


def _date(value: Any) -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        raise AppError("Дата — в виде ГГГГ-ММ-ДД.", field="date") from None


def create_document(session: Session, actor: Actor, kind: str, header: dict[str, Any]) -> Document:
    admin(actor)
    if kind not in KINDS:
        raise AppError("Неизвестный вид документа.", field="kind")
    lock(session)  # номер — следующий после занятых, в том числе другим сеансом
    number = (
        session.scalar(select(func.max(Document.number)).where(Document.kind == kind)) or 0
    ) + 1
    doc = Document(
        id=uuid.uuid4(),
        kind=kind,
        number=number,
        status="draft",
        date=date.today(),
        created_by=actor.full_name,
        basis="",
        supplier="",
        contractor="",
        reason="",
        note="",
        version=1,
    )
    if kind == "repair":
        doc.repair = "send"
    session.add(doc)
    _header(doc, header)
    session.flush()
    return doc


# Разбор шапки и строк из запроса: неразборчивое значение — ошибка с полем и подсказкой, а
# не «внутренняя ошибка» (6.1 п. 6, R-022). Подсказки — для полей, где разбор может не выйти.
HEADER_HINTS = {
    "repair_cost": "Стоимость ремонта — число",
    "from_place": "Откуда — выберите место из списка",
    "to_place": "Куда — выберите место из списка",
}
LINE_HINTS = {
    "unit_id": "инвентарная единица — выберите из списка",
    "type_id": "тип — выберите из каталога",
    "model_id": "модель — выберите из каталога",
    "qty": "количество — число",
    "price": "цена — число",
    "new_value": "новая стоимость — число",
    "number": "инвентарный номер — не длиннее 40 знаков",
    "state": "состояние — в работе, неисправна, в ремонте или на хранении",
    "commissioned_on": "дата ввода — в виде ГГГГ-ММ-ДД",
    "life_months": "срок службы — от 1 до 1200 месяцев",
    "values": "характеристики — набор «характеристика: значение»",
    "from_place": "откуда — выберите место из списка",
    "to_place": "куда — выберите место из списка",
}


def _number(table: Any, k: str, v: Any) -> Decimal | None:
    """Число для столбца Numeric: пусто — None; не число, NaN, бесконечность или не помещается
    в столбец — ValueError."""
    if v in (None, ""):
        return None
    d = Decimal(str(v))
    column = table.c[k].type
    if not d.is_finite() or abs(d) >= Decimal(10) ** (column.precision - column.scale):
        raise ValueError(k)
    return d


def _text(table: Any, k: str, v: Any) -> str:
    """Текст обрезается по длине столбца; у Text предела нет — до 5000 знаков."""
    return str(v or "")[: getattr(table.c[k].type, "length", None) or 5000]


def _place(table: Any, k: str, v: Any) -> str | None:
    """Ключ места; есть ли такое место, проверяет проведение."""
    if v in (None, ""):
        return None
    if not isinstance(v, str) or len(v) > table.c[k].type.length:
        raise ValueError(k)
    return v


def _header(doc: Document, header: dict[str, Any]) -> None:
    table = Document.__table__
    for k, v in header.items():
        if k not in HEADER_FIELDS:
            continue
        try:
            if k == "date":
                doc.date = _date(v)
            elif k == "repair":
                if v not in ("send", "return"):
                    raise AppError("Ремонт — отправка или возврат.", field="repair")
                doc.repair = v
            elif k == "repair_cost":
                doc.repair_cost = _number(table, k, v)
            elif k in ("from_place", "to_place"):
                setattr(doc, k, _place(table, k, v))
            else:
                setattr(doc, k, _text(table, k, v))
        except (ValueError, TypeError, ArithmeticError):
            raise AppError(f"{HEADER_HINTS[k]}.", field=k) from None


def update_document(
    session: Session,
    actor: Actor,
    doc_id: uuid.UUID,
    version: int,
    header: dict[str, Any],
    lines: list[dict[str, Any]] | None,
) -> Document:
    doc = get_document(session, actor, doc_id, for_update=True)
    if doc.status != "draft":
        raise Conflict("Проведённый документ не правится — его можно только отменить.")
    if doc.version != version:
        raise stale("Документ")
    _header(doc, header)
    if lines is not None:
        for old in session.scalars(select(DocLine).where(DocLine.document_id == doc.id)):
            session.delete(old)
        session.flush()
        for i, raw in enumerate(lines):
            session.add(_line(doc, i, raw))
    doc.version += 1
    session.flush()
    return doc


def _uuid(v: Any) -> uuid.UUID | None:
    if v in (None, ""):
        return None
    return v if isinstance(v, uuid.UUID) else uuid.UUID(str(v))


def _line_field(line: DocLine, k: str, v: Any) -> None:
    """Поле строки из запроса; не разобрать — ValueError, TypeError или ArithmeticError."""
    table = DocLine.__table__
    if k in ("unit_id", "type_id", "model_id"):
        setattr(line, k, _uuid(v))
    elif k in ("qty", "price", "new_value"):
        setattr(line, k, _number(table, k, v))
    elif k == "commissioned_on":
        line.commissioned_on = _date(v) if v else None
    elif k == "life_months":
        months = None if v in (None, "") else Decimal(str(v))
        if months is not None and (months != months.to_integral_value() or not 1 <= months <= 1200):
            raise ValueError(k)
        line.life_months = None if months is None else int(months)
    elif k == "values":
        if v and not isinstance(v, dict):
            raise ValueError(k)
        line.values = dict(v or {})
    elif k == "state":
        state = STATE_BY_TITLE.get(v, v) if v else None
        if state is not None and state not in STATES:
            raise ValueError(k)
        line.state = state
    elif k in ("from_place", "to_place"):
        setattr(line, k, _place(table, k, v))
    elif k == "number":
        number = str(v or "").strip()
        if len(number) > table.c.number.type.length:
            raise ValueError(k)
        line.number = number
    else:
        setattr(line, k, _text(table, k, v))


def _line(doc: Document, position: int, raw: dict[str, Any]) -> DocLine:
    line = DocLine(
        id=uuid.uuid4(),
        document_id=doc.id,
        position=position,
        values={},
        created_units=[],
        number="",
        serial="",
        responsible="",
        department="",
        note="",
        reason="",
    )
    for k in LINE_FIELDS:
        if k in raw:
            try:
                _line_field(line, k, raw[k])
            except (ValueError, TypeError, ArithmeticError, AppError):
                hint = LINE_HINTS.get(k, f"«{k}» — неверное значение")
                raise AppError(f"Строка {position + 1}: {hint}.", field=k) from None
    if line.qty is None:
        line.qty = Decimal(1)
    return line


def delete_draft(session: Session, actor: Actor, doc_id: uuid.UUID) -> None:
    doc = get_document(session, actor, doc_id, for_update=True)
    if doc.status != "draft":
        raise Conflict("Удалить можно только черновик; проведённый документ отменяется.")
    session.delete(doc)


def lines_of(session: Session, doc: Document) -> list[DocLine]:
    return list(
        session.scalars(
            select(DocLine).where(DocLine.document_id == doc.id).order_by(DocLine.position)
        )
    )


# ---------------------------------------------------------------- проведение


@dataclass
class Fail(Exception):
    message: str


class Posting:
    def __init__(self, session: Session, actor: Actor, doc: Document):
        self.session = session
        self.actor = actor
        self.doc = doc
        self.places = Places(session, actor)
        self._numbers: Numbers | None = None
        self.units: list[Unit] = []
        self.created: list[Unit] = []
        self.qty_lines: list[tuple[str, Decimal, str]] = []  # тип, количество, единица

    @property
    def numbers(self) -> Numbers:
        if self._numbers is None:
            given = {n for line in lines_of(self.session, self.doc) if (n := line.number.strip())}
            self._numbers = Numbers(self.session, reserved=given)
        return self._numbers

    def place(self, key: str | None, what: str) -> Place:
        if not key:
            raise Fail(f"не указано, {what}")
        try:
            return self.places.get(key)
        except (NotFound, AppError) as e:
            raise Fail(getattr(e, "message", str(e))) from None

    # события единиц: что стало после документа
    def event(self, unit: Unit, kind: str, at: date | None = None) -> None:
        self.session.add(
            UnitEvent(
                unit_id=unit.id,
                document_id=self.doc.id,
                date=at or self.doc.date,
                kind=kind,
                place=unit.place,
                building_id=unit.building_id,
                floor_id=unit.floor_id,
                state=unit.state,
                value_base=unit.value_base,
                value_date=unit.value_date,
                undone=False,
            )
        )

    def move_unit(self, unit: Unit, to: Place) -> None:
        was_storage = unit.place.startswith(("w:", "c:"))
        for u in [unit, *self.session.scalars(select(Unit).where(Unit.parent_id == unit.id))]:
            u.place, u.building_id, u.floor_id = to.key, to.building_id, to.floor_id
            # на склад — «на хранении»; со склада в помещение — снова «в работе»
            if is_storage(to) and u.state in ("in_use", "storage"):
                u.state = "storage"
            elif not is_storage(to) and was_storage and u.state == "storage":
                u.state = "in_use"
            u.version += 1
            self.event(u, self.doc.kind)
            if u is not unit:
                self.units.append(u)

    def stock(
        self,
        place: Place,
        type_id: uuid.UUID,
        model_id: uuid.UUID | None,
        qty: Decimal,
        amount: Decimal,
        line: DocLine,
        at: date | None = None,
    ) -> None:
        self.session.add(
            StockMove(
                document_id=self.doc.id,
                line_id=line.id,
                date=at or self.doc.date,
                place=place.key,
                building_id=place.building_id,
                floor_id=place.floor_id,
                type_id=type_id,
                model_id=model_id,
                qty=qty,
                amount=amount,
            )
        )
        self.session.flush()

    @staticmethod
    def _position(place: str, type_id: uuid.UUID, model_id: uuid.UUID | None) -> list[Any]:
        return [
            StockMove.place == place,
            StockMove.type_id == type_id,
            StockMove.model_id.is_(None) if model_id is None else StockMove.model_id == model_id,
        ]

    def balance(
        self, place: str, type_id: uuid.UUID, model_id: uuid.UUID | None, at: date | None = None
    ) -> tuple[Decimal, Decimal]:
        q = select(
            func.coalesce(func.sum(StockMove.qty), 0), func.coalesce(func.sum(StockMove.amount), 0)
        ).where(*self._position(place, type_id, model_id))
        if at is not None:
            q = q.where(StockMove.date <= at)
        qty, amount = self.session.execute(q).one()
        return Decimal(qty), Decimal(amount)

    def available(
        self, place: str, type_id: uuid.UUID, model_id: uuid.UUID | None
    ) -> tuple[Decimal, date | None]:
        """Сколько можно взять датой документа: наименьший остаток на эту дату и на каждую более
        позднюю дату движения — задним числом остаток не уходит в минус в промежутке (ADR-0004).
        Второе — дата этого наименьшего остатка, если она позже даты документа."""
        rows = self.session.execute(
            select(StockMove.date, func.sum(StockMove.qty))
            .where(*self._position(place, type_id, model_id))
            .group_by(StockMove.date)
            .order_by(StockMove.date)
        ).all()
        running = have = Decimal(0)
        when = None
        for day, qty in rows:
            running += Decimal(qty)
            if day <= self.doc.date:
                have = running
            elif running < have:
                have, when = running, day
        return have, when

    def take(
        self,
        place: Place,
        type_id: uuid.UUID,
        model_id: uuid.UUID | None,
        qty: Decimal,
        line: DocLine,
        name: str,
    ) -> Decimal:
        """Списать количество с места по средней цене; не больше остатка ни на дату
        документа, ни на одну дату после неё."""
        have, when = self.available(place.key, type_id, model_id)
        if qty > have:
            later = f" на {when:%d.%m.%Y} (позже даты документа уже был расход)" if when else ""
            raise Fail(
                f"«{name}» на месте «{place.short}» — {have.normalize():f}{later}, "
                f"нужно {qty.normalize():f}"
            )
        q_now, a_now = self.balance(place.key, type_id, model_id)
        avg = (a_now / q_now) if q_now else Decimal(0)
        amount = (avg * qty).quantize(Decimal("0.01"))
        self.stock(place, type_id, model_id, -qty, -amount, line)
        return amount

    def unit_of(self, line: DocLine) -> Unit:
        if not line.unit_id:
            raise Fail("не выбрана инвентарная единица")
        unit = self.session.get(Unit, line.unit_id, with_for_update=True)
        if unit is None:
            raise Fail("инвентарная единица не найдена")
        if unit.state == "written_off":
            raise Fail(f"{unit.number} уже списана")
        if any(u.id == unit.id for u in self.units):
            raise Fail(f"{unit.number} — уже в другой строке")
        self.not_before_last_event(unit)
        self.units.append(unit)
        return unit

    def not_before_last_event(self, unit: Unit) -> None:
        """Документ по единице — не раньше её последнего события (документ, перенос при
        объединении помещений): иначе карточка, отчёты «на дату» и отмена увидели бы разную
        историю (5.4.4 п. 2, ADR-0004). В тот же день можно — порядок задаёт проведение.
        Отменённый документ и обратный к нему взаимно гасятся и не в счёт, как и в `cancel`:
        так забытый документ проводится после отмены более поздних."""
        last = self.session.execute(
            select(UnitEvent.date, Document.kind, Document.number)
            .outerjoin(Document, Document.id == UnitEvent.document_id)
            .where(
                UnitEvent.unit_id == unit.id,
                UnitEvent.undone.is_(False),
                or_(
                    Document.id.is_(None),
                    (Document.status != "cancelled") & Document.cancels_id.is_(None),
                ),
            )
            .order_by(UnitEvent.date.desc(), UnitEvent.seq.desc())
            .limit(1)
        ).first()
        if last is None or last.date <= self.doc.date:
            return
        what = (
            f"по ней уже есть «{doc_title(last.kind, last.number)}» от {last.date:%d.%m.%Y}"
            if last.kind
            else f"{last.date:%d.%m.%Y} её перенесли при объединении помещений"
        )
        raise Fail(f"{unit.number}: {what} — дата документа не раньше этого дня")

    def type_of(self, line: DocLine) -> Any:
        if not line.type_id:
            raise Fail("не выбран тип")
        t = catalog.get_type(self.session, line.type_id)
        if line.model_id:
            m = catalog.get_model(self.session, line.model_id)
            if m.type_id != t.id:
                raise Fail("модель другого типа")
        return t

    # -------------------------------------------------------------- виды документов

    def new_items(self, line: DocLine) -> None:
        """Ввод остатков и приход: новые единицы или количество."""
        t = self.type_of(line)
        to = self.place(line.to_place or self.doc.to_place, "куда")
        qty = _d(line.qty)
        if qty <= 0:
            raise Fail("количество — больше нуля")
        price = _d(line.price)
        if line.price is None or price < 0:
            raise Fail("укажите цену (0 — если без стоимости)")
        # ввод остатков ставит на учёт то, что уже есть: числится с даты ввода
        since = (line.commissioned_on or self.doc.date) if self.doc.kind == "opening" else None
        if since and since > self.doc.date:
            raise Fail("дата ввода — позже даты документа")
        if t.accounting == "quantity":
            self.stock(
                to, t.id, line.model_id, qty, (price * qty).quantize(Decimal("0.01")), line, since
            )
            self.qty_lines.append((t.name, qty, t.unit))
            return
        if qty != qty.to_integral_value():
            raise Fail(f"«{t.name}» учитывается поштучно — количество целое")
        count = int(qty)
        if line.number and count > 1:
            raise Fail(
                "номер вводится для одной вещи — у строки с несколькими номера выдаст система"
            )
        state = line.state or ("storage" if is_storage(to) else "in_use")
        if state not in STATES or state == "written_off":
            raise Fail("состояние — в работе, неисправна, в ремонте или на хранении")
        commissioned = line.commissioned_on or self.doc.date
        if commissioned > date.today():
            raise Fail("дата ввода — в будущем")
        created = []
        for _ in range(count):
            try:
                number = self.numbers.check(line.number) if line.number else self.numbers.issue()
            except AppError as e:
                raise Fail(e.message) from None
            unit = Unit(
                id=uuid.uuid4(),
                number=number,
                type_id=t.id,
                model_id=line.model_id,
                serial=line.serial,
                place=to.key,
                building_id=to.building_id,
                floor_id=to.floor_id,
                state=state,
                responsible=line.responsible,
                department=line.department,
                note=line.note,
                values=dict(line.values or {}),
                price=price,
                commissioned_on=commissioned,
                life_months=line.life_months or t.life_months,
                label_code=label_code(),
                writeoff_reason="",
                created_doc_id=self.doc.id,
                version=1,
            )
            self.session.add(unit)
            self.session.flush()
            self.event(unit, self.doc.kind, since)
            created.append(unit)
        line.created_units = [str(u.id) for u in created]
        self.created.extend(created)

    def transfer(self, line: DocLine) -> None:
        to = self.place(line.to_place or self.doc.to_place, "куда")
        if line.unit_id:
            unit = self.unit_of(line)
            if unit.parent_id:
                raise Fail(
                    f"{unit.number} входит в состав другой единицы — перемещается вместе с ней"
                )
            src = line.from_place or self.doc.from_place
            if src and unit.place != src:
                raise Fail(f"{unit.number} числится не там: {self.places.title(unit.place)}")
            if unit.place == to.key:
                raise Fail(f"{unit.number} уже числится там")
            line.from_place = unit.place
            self.move_unit(unit, to)
            return
        t = self.type_of(line)
        frm = self.place(line.from_place or self.doc.from_place, "откуда")
        if frm.key == to.key:
            raise Fail("откуда и куда — одно место")
        qty = _d(line.qty)
        if qty <= 0:
            raise Fail("количество — больше нуля")
        amount = self.take(frm, t.id, line.model_id, qty, line, t.name)
        self.stock(to, t.id, line.model_id, qty, amount, line)
        self.qty_lines.append((t.name, qty, t.unit))

    def repair(self, line: DocLine) -> None:
        unit = self.unit_of(line)
        if self.doc.repair == "return":
            if unit.state != "repair":
                raise Fail(f"{unit.number} не в ремонте")
            unit.state = line.state if line.state in ("in_use", "broken") else "in_use"
        else:
            if unit.state not in ("in_use", "broken", "storage"):
                raise Fail(f"{unit.number} — {STATES[unit.state]}, отправить в ремонт нельзя")
            unit.state = "repair"
        unit.version += 1
        self.event(unit, "repair")

    def writeoff(self, line: DocLine) -> None:
        reason = line.reason or self.doc.reason
        if line.unit_id:
            unit = self.unit_of(line)
            if not reason:
                raise Fail(f"{unit.number}: укажите причину списания")
            unit.state = "written_off"
            unit.written_off_on = self.doc.date
            unit.writeoff_reason = reason
            unit.version += 1
            for child in self.session.scalars(select(Unit).where(Unit.parent_id == unit.id)):
                child.parent_id = None
            self.event(unit, "writeoff")
            return
        t = self.type_of(line)
        frm = self.place(line.from_place or self.doc.from_place, "откуда")
        qty = _d(line.qty)
        if qty <= 0:
            raise Fail("количество — больше нуля")
        self.take(frm, t.id, line.model_id, qty, line, t.name)
        self.qty_lines.append((t.name, qty, t.unit))

    def inventory(self, line: DocLine) -> None:
        """Проведение инвентаризации (5.4.6 п. 3): строки составлены из отметок обхода."""
        if line.reason == "без расхождений":
            return
        if line.unit_id:
            unit = self.unit_of(line)
            if line.state == "not_found":
                unit.state = "not_found"
                unit.version += 1
                self.event(unit, "inventory")
                return
            to = self.place(line.to_place, "где найдена")
            if unit.parent_id:
                raise Fail(f"{unit.number} входит в состав другой единицы — отметьте её основу")
            line.from_place = unit.place
            if unit.state == "not_found":
                unit.state = "storage" if is_storage(to) else "in_use"
            self.move_unit(unit, to)
            self.event(unit, "inventory")
            return
        t = self.type_of(line)
        qty = _d(line.qty)
        if line.reason == "недостача":
            frm = self.place(line.from_place, "где не хватает")
            self.take(frm, t.id, line.model_id, qty, line, t.name)
            self.qty_lines.append((t.name, -qty, t.unit))
        elif line.reason == "излишек":
            to = self.place(line.to_place, "где излишек")
            have, amount = self.balance(to.key, t.id, line.model_id)
            price = (
                _d(line.price)
                if line.price is not None
                else (amount / have if have > 0 else _d(t.price))
            )
            self.stock(to, t.id, line.model_id, qty, (price * qty).quantize(Decimal("0.01")), line)
            self.qty_lines.append((t.name, qty, t.unit))
        else:
            self.new_items(line)  # вещь без метки — новая единица

    def revaluation(self, line: DocLine) -> None:
        unit = self.unit_of(line)
        if line.new_value is None or _d(line.new_value) < 0:
            raise Fail(f"{unit.number}: укажите новую стоимость")
        unit.value_base = _d(line.new_value)
        unit.value_date = self.doc.date
        unit.version += 1
        self.event(unit, "revaluation")


def doc_places(session: Session, doc: Document) -> set[str]:
    """Места, которых касается документ: шапка, строки, где числятся его единицы."""
    places = {doc.from_place, doc.to_place}
    unit_ids = []
    for line in lines_of(session, doc):
        places |= {line.from_place, line.to_place}
        if line.unit_id:
            unit_ids.append(line.unit_id)
    if unit_ids:
        places |= set(session.scalars(select(Unit.place).where(Unit.id.in_(unit_ids))))
    if doc.kind == "inventory":
        places |= set(
            session.scalars(select(CountPlace.place).where(CountPlace.document_id == doc.id))
        )
    return {p for p in places if p}


def _check_date(session: Session, actor: Actor, doc: Document) -> None:
    if doc.date > date.today():
        raise AppError("Дата документа — не позже сегодняшней.", field="date")
    # 5.4.4 п. 2 — не раньше последней проведённой инвентаризации мест документа: иначе её
    # результат задним числом перестал бы сходиться
    places = doc_places(session, doc)
    if not places:
        return
    last = session.execute(
        select(Document, CountPlace.place)
        .join(CountPlace, CountPlace.document_id == Document.id)
        .where(
            Document.kind == "inventory",
            Document.status == "posted",
            Document.id != doc.id,
            Document.date > doc.date,
            CountPlace.place.in_(places),
        )
        .order_by(Document.date.desc())
        .limit(1)
    ).first()
    if last is not None:
        inv, place = last
        raise AppError(
            f"Дата документа — раньше проведённой «{doc_title(inv.kind, inv.number)}» от "
            f"{inv.date:%d.%m.%Y} ({Places(session, actor).title(place)}): её результат "
            "перестал бы сходиться. Поставьте дату не раньше.",
            field="date",
        )


def open_counts(session: Session, places: set[str], exclude: uuid.UUID | None = None) -> list[str]:
    """Незакрытые инвентаризации этих мест — движения по ним предупреждают (5.4.6 п. 5)."""
    if not places:
        return []
    rows = session.execute(
        select(Document)
        .join(CountPlace, CountPlace.document_id == Document.id)
        .where(
            Document.kind == "inventory",
            Document.status == "draft",
            CountPlace.place.in_(places),
            Document.id != exclude,
        )
        .distinct()
    ).scalars()
    return [doc_title(d.kind, d.number) for d in rows]


def post(session: Session, actor: Actor, doc_id: uuid.UUID, version: int) -> Document:
    admin(actor)
    lock(session)
    doc = get_document(session, actor, doc_id, for_update=True)
    if doc.status != "draft":
        raise Conflict("Документ уже проведён.")
    if doc.version != version:
        raise stale("Документ")
    _check_date(session, actor, doc)
    lines = lines_of(session, doc)
    if not lines:
        raise AppError("В документе нет строк.")
    if doc.kind == "repair" and doc.repair == "send" and not doc.contractor.strip():
        raise AppError("Укажите, кто ремонтирует.", field="contractor")
    p = Posting(session, actor, doc)
    act = {
        "opening": p.new_items,
        "receipt": p.new_items,
        "transfer": p.transfer,
        "repair": p.repair,
        "writeoff": p.writeoff,
        "revaluation": p.revaluation,
        "inventory": p.inventory,
    }[doc.kind]
    errors: list[str] = []
    nested = session.begin_nested()
    for i, line in enumerate(lines, 1):
        try:
            act(line)
        except Fail as e:
            errors.append(f"строка {i}: {e.message}")
    if errors:
        nested.rollback()
        raise AppError(
            "Документ не проведён: " + "; ".join(errors[:5]) + ("…" if len(errors) > 5 else ""),
            code="not_posted",
            details={"errors": errors},
        )
    nested.commit()
    doc.status = "posted"
    doc.posted_at = datetime.now(UTC)
    doc.posted_by = actor.full_name
    doc.version += 1
    _journal(session, actor, doc, p, "inventory.document_post", "Проведён")
    _units_changed(session, actor, p.units)
    return doc


def _journal(
    session: Session, actor: Actor, doc: Document, p: Posting, action: str, verb: str
) -> None:
    parts = []
    units = [*p.created, *p.units]
    if units:
        parts.append(f"единиц: {len(units)}")
    counted: Counter[tuple[str, str]] = Counter()
    for name, qty, unit in p.qty_lines:
        counted[(name, unit)] += qty  # type: ignore[assignment]
    parts.extend(f"{name} — {qty.normalize():f} {unit}" for (name, unit), qty in counted.items())
    where = " → ".join(
        t for t in (p.places.title(doc.from_place), p.places.title(doc.to_place)) if t
    )
    rooms = {u.place for u in units} | {doc.from_place or "", doc.to_place or ""}
    journal.record(
        session,
        actor,
        action,
        f"{verb} «{doc_title(doc.kind, doc.number)}»"
        + (f" ({where})" if where else "")
        + (": " + ", ".join(parts) if parts else ""),
        entity=f"document:{doc.id}",
        refs=[
            *[f"room:{k[2:]}" for k in rooms if k.startswith("r:")],
            *[f"warehouse:{k[2:]}" for k in rooms if k.startswith("w:")],
            *[f"unit:{u.id}" for u in units],
        ],
    )


# ---------------------------------------------------------------- отмена (5.4.4 п. 4)


def cancel(session: Session, actor: Actor, doc_id: uuid.UUID) -> Document:
    admin(actor)
    lock(session)
    doc = get_document(session, actor, doc_id, for_update=True)
    if doc.status != "posted":
        raise Conflict("Отменить можно только проведённый документ.")
    if doc.cancels_id:
        raise Conflict("Это уже обратный документ — отмену не отменяют.")
    today = date.today()
    events = list(
        session.scalars(
            select(UnitEvent).where(UnitEvent.document_id == doc.id, UnitEvent.undone.is_(False))
        )
    )
    problems = []
    previous: dict[uuid.UUID, UnitEvent | None] = {}
    # отменённые документы и их обратные взаимно гасятся — их события не в счёт
    neutral = set(
        session.scalars(
            select(Document.id).where(
                (Document.status == "cancelled") | Document.cancels_id.is_not(None)
            )
        )
    )
    for e in events:
        # по порядку проведения, а не по дате: отменить можно, только если после этого
        # документа единицу больше никто не менял (ADR-0004)
        history = [
            x
            for x in session.scalars(
                select(UnitEvent)
                .where(UnitEvent.unit_id == e.unit_id, UnitEvent.undone.is_(False))
                .order_by(UnitEvent.seq)
            )
            if x.seq == e.seq or x.document_id not in neutral
        ]
        unit = session.get(Unit, e.unit_id)
        if history[-1].seq != e.seq:
            problems.append(
                f"{unit.number if unit else '?'} с тех пор уже меняли другим документом"
            )
            continue
        before = history[:-1]
        previous[e.unit_id] = before[-1] if before else None
    if problems:
        raise AppError("Отменить нельзя: " + "; ".join(problems[:5]), code="cannot_cancel")
    back = create_document(session, actor, doc.kind, {})
    back.status, back.date, back.cancels_id = "posted", today, doc.id
    back.from_place, back.to_place = doc.to_place, doc.from_place
    back.basis = f"Отмена «{doc_title(doc.kind, doc.number)}»"
    back.repair = ("return" if doc.repair == "send" else "send") if doc.repair else None
    back.posted_at, back.posted_by = datetime.now(UTC), actor.full_name
    for line in lines_of(session, doc):
        copy = DocLine(
            id=uuid.uuid4(),
            document_id=back.id,
            position=line.position,
            unit_id=line.unit_id,
            type_id=line.type_id,
            model_id=line.model_id,
            qty=line.qty,
            price=line.price,
            from_place=line.to_place,
            to_place=line.from_place,
            reason=back.basis,
            values={},
            created_units=list(line.created_units),
            number="",
            serial="",
            responsible="",
            department="",
            note="",
        )
        session.add(copy)
    session.flush()
    p = Posting(session, actor, back)
    for unit_id, prev in previous.items():
        unit = session.get(Unit, unit_id, with_for_update=True)
        assert unit is not None
        if prev is None:  # единица заведена этим документом — уходит, номер остаётся занятым
            unit.state, unit.written_off_on = "written_off", today
            unit.writeoff_reason = back.basis
        else:
            unit.place, unit.building_id, unit.floor_id = (
                prev.place,
                prev.building_id,
                prev.floor_id,
            )
            unit.state, unit.value_base, unit.value_date = (
                prev.state,
                prev.value_base,
                prev.value_date,
            )
            if prev.state != "written_off":
                unit.written_off_on, unit.writeoff_reason = None, ""
        unit.version += 1
        p.event(unit, "cancel")
        p.units.append(unit)
    # остатки — обратными движениями сегодняшним числом
    for move in list(session.scalars(select(StockMove).where(StockMove.document_id == doc.id))):
        session.add(
            StockMove(
                document_id=back.id,
                line_id=move.line_id,
                date=today,
                place=move.place,
                building_id=move.building_id,
                floor_id=move.floor_id,
                type_id=move.type_id,
                model_id=move.model_id,
                qty=-move.qty,
                amount=-move.amount,
            )
        )
        session.flush()
        qty, _ = p.balance(move.place, move.type_id, move.model_id)
        if qty < 0:
            t = catalog.get_type(session, move.type_id)
            raise AppError(
                f"Отменить нельзя: «{t.name}» с места «{p.places.title(move.place)}» уже "
                "израсходован или перемещён.",
                code="cannot_cancel",
            )
    doc.status = "cancelled"
    doc.cancelled_by_id = back.id
    doc.version += 1
    _journal(session, actor, doc, p, "inventory.document_cancel", "Отменён")
    _units_changed(session, actor, p.units)
    return back


# ---------------------------------------------------------------- вид и список


def _head(doc: Document, places: Places) -> dict[str, Any]:
    return {
        "id": doc.id,
        "kind": doc.kind,
        "kind_title": KINDS[doc.kind],
        "number": doc.number,
        "title": doc_title(doc.kind, doc.number),
        "status": doc.status,
        "date": doc.date,
        "from_place": doc.from_place,
        "from_title": places.title(doc.from_place),
        "to_place": doc.to_place,
        "to_title": places.title(doc.to_place),
        "basis": doc.basis,
        "supplier": doc.supplier,
        "contractor": doc.contractor,
        "repair": doc.repair,
        "repair_cost": float(doc.repair_cost) if doc.repair_cost is not None else None,
        "reason": doc.reason,
        "note": doc.note,
        "cancels_id": doc.cancels_id,
        "cancelled_by_id": doc.cancelled_by_id,
        "created_by": doc.created_by,
        "created_at": doc.created_at,
        "posted_by": doc.posted_by,
        "posted_at": doc.posted_at,
        "version": doc.version,
    }


def doc_view(session: Session, actor: Actor, doc: Document, full: bool = True) -> dict[str, Any]:
    places = Places(session, actor)
    out = _head(doc, places)
    lines = lines_of(session, doc)
    unit_ids = [line.unit_id for line in lines if line.unit_id]
    created_ids = [uuid.UUID(u) for line in lines for u in line.created_units]
    units = {
        u.id: u for u in session.scalars(select(Unit).where(Unit.id.in_([*unit_ids, *created_ids])))
    }
    types = catalog.types_by_id(
        session,
        [line.type_id for line in lines if line.type_id] + [u.type_id for u in units.values()],
    )
    models = catalog.models_by_id(
        session, [line.model_id for line in lines] + [u.model_id for u in units.values()]
    )
    total = Decimal(0)
    rows = []
    for line in lines:
        unit = units.get(line.unit_id) if line.unit_id else None
        t = types.get(unit.type_id if unit else line.type_id)  # type: ignore[arg-type]
        m = models.get(unit.model_id if unit else line.model_id)  # type: ignore[arg-type]
        price = Decimal(str(unit.price)) if unit is not None else _d(line.price)
        qty = Decimal(1) if unit is not None else _d(line.qty)
        amount = (price * qty).quantize(Decimal("0.01"))
        total += amount
        rows.append(
            {
                "id": line.id,
                "unit_id": line.unit_id,
                "number": unit.number if unit else line.number,
                "unit_state": unit.state if unit else None,
                "unit_place": places.title(unit.place) if unit else None,
                "type_id": unit.type_id if unit else line.type_id,
                "type_name": t.name if t else "",
                "accounting": t.accounting if t else "piece",
                "unit": t.unit if t else "шт.",
                "model_id": unit.model_id if unit else line.model_id,
                "model_name": " ".join(x for x in (m.manufacturer, m.name) if x) if m else "",
                "qty": float(qty),
                "price": float(price),
                "amount": float(amount),
                "value": value_now(unit) if unit else None,
                "serial": line.serial,
                "responsible": line.responsible,
                "department": line.department,
                "state": line.state,
                "commissioned_on": line.commissioned_on,
                "life_months": line.life_months,
                "note": line.note,
                "values": line.values,
                "from_place": line.from_place,
                "from_title": places.title(line.from_place),
                "to_place": line.to_place,
                "to_title": places.title(line.to_place),
                "reason": line.reason,
                "new_value": float(line.new_value) if line.new_value is not None else None,
                "created_units": [
                    {"id": u, "number": units[uuid.UUID(u)].number}
                    for u in line.created_units
                    if uuid.UUID(u) in units
                ],
            }
        )
    out["lines"] = rows if full else len(rows)
    out["total"] = float(total)
    out["files"] = (
        [
            {"id": f.id, "file_id": f.file_id, "url": f"/api/files/{f.file_id}"}
            for f in session.scalars(select(DocFile).where(DocFile.document_id == doc.id))
        ]
        if full
        else []
    )
    # идёт инвентаризация мест документа — движение предупреждает (5.4.6 п. 5)
    out["warnings"] = (
        [
            f"По месту идёт «{t}»: движение после начала обхода — учтите его при проведении."
            for t in open_counts(session, doc_places(session, doc), exclude=doc.id)
        ]
        if full and doc.status == "draft" and doc.kind != "inventory"
        else []
    )
    return out


def documents(
    session: Session,
    actor: Actor,
    *,
    kind: str | None = None,
    status: str | None = None,
    since: date | None = None,
    until: date | None = None,
    place: str | None = None,
    unit_id: uuid.UUID | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    admin(actor)
    q = select(Document).order_by(Document.date.desc(), Document.created_at.desc())
    if kind:
        q = q.where(Document.kind == kind)
    if status:
        q = q.where(Document.status == status)
    if since:
        q = q.where(Document.date >= since)
    if until:
        q = q.where(Document.date <= until)
    if place:
        sub = select(DocLine.document_id).where(
            (DocLine.from_place == place) | (DocLine.to_place == place)
        )
        q = q.where(
            (Document.from_place == place) | (Document.to_place == place) | Document.id.in_(sub)
        )
    if unit_id:
        q = q.where(Document.id.in_(select(DocLine.document_id).where(DocLine.unit_id == unit_id)))
    found = list(session.scalars(q.limit(limit)))
    # список (8.1: 20 000 документов): шапка, число строк и сумма — одним запросом на все,
    # места — пачкой; строки целиком — только в карточке документа
    places = Places(session, actor)
    places.preload(k for d in found for k in (d.from_place, d.to_place))
    amount = func.coalesce(
        Unit.price, func.coalesce(DocLine.price, 0) * func.coalesce(DocLine.qty, 0)
    )
    sums = {
        doc_id: (n, float(total or 0))
        for doc_id, n, total in session.execute(
            select(DocLine.document_id, func.count(), func.sum(func.round(amount, 2)))
            .outerjoin(Unit, Unit.id == DocLine.unit_id)
            .where(DocLine.document_id.in_([d.id for d in found]))
            .group_by(DocLine.document_id)
        )
    }
    out = []
    for d in found:
        n, total = sums.get(d.id, (0, 0.0))
        out.append(_head(d, places) | {"lines": n, "total": total, "files": [], "warnings": []})
    return out


def attach_file(session: Session, actor: Actor, doc_id: uuid.UUID, file_id: uuid.UUID) -> None:
    doc = get_document(session, actor, doc_id)
    session.add(DocFile(id=uuid.uuid4(), document_id=doc.id, file_id=file_id))


# ---------------------------------------------------------------- остатки (5.4.3)


def balances(
    session: Session,
    actor: Actor,
    *,
    place: str | None = None,
    at: date | None = None,
    building_id: uuid.UUID | None = None,
) -> list[dict[str, Any]]:
    q = select(
        StockMove.place,
        StockMove.type_id,
        StockMove.model_id,
        func.sum(StockMove.qty),
        func.sum(StockMove.amount),
    ).group_by(StockMove.place, StockMove.type_id, StockMove.model_id)
    if place:
        if place.startswith("w:"):
            cells = [
                f"c:{c}"
                for c in session.scalars(
                    select(Cell.id).where(Cell.warehouse_id == uuid.UUID(place[2:]))
                )
            ]
            q = q.where(StockMove.place.in_([place, *cells]))
        else:
            q = q.where(StockMove.place == place)
    if at:
        q = q.where(StockMove.date <= at)
    if building_id:
        q = q.where(StockMove.building_id == building_id)
    if not actor.is_admin:
        q = q.where(StockMove.building_id.in_(list(actor.building_ids) or [uuid.uuid4()]))
    rows = [r for r in session.execute(q).all() if r[3] and r[3] > 0]
    types = catalog.types_by_id(session, [r[1] for r in rows])
    models = catalog.models_by_id(session, [r[2] for r in rows])
    places = Places(session, actor)
    out = []
    for key, type_id, model_id, qty, amount in rows:
        t, m = types[type_id], models.get(model_id)
        row: dict[str, Any] = {
            "place": key,
            "place_title": places.title(key),
            "type_id": type_id,
            "type_name": t.name,
            "model_id": model_id,
            "model_name": " ".join(x for x in (m.manufacturer, m.name) if x) if m else "",
            "unit": t.unit,
            "qty": float(qty),
        }
        if actor.sees_cost:
            row["amount"] = float(amount)
            row["avg_price"] = float(round(amount / qty, 2)) if qty else 0.0
        out.append(row)
    out.sort(key=lambda r: (r["place_title"], r["type_name"]))
    return out


def stock_history(
    session: Session, actor: Actor, place: str, type_id: uuid.UUID, model_id: uuid.UUID | None
) -> list[dict[str, Any]]:
    """Движение по позиции остатка."""
    admin(actor)
    rows = session.execute(
        select(StockMove, Document)
        .join(Document, Document.id == StockMove.document_id)
        .where(
            StockMove.place == place,
            StockMove.type_id == type_id,
            StockMove.model_id.is_(None) if model_id is None else StockMove.model_id == model_id,
        )
        .order_by(StockMove.date, StockMove.seq)
    ).all()
    total = Decimal(0)
    out = []
    for move, doc in rows:
        total += Decimal(move.qty)
        out.append(
            {
                "date": move.date,
                "document_id": doc.id,
                "title": doc_title(doc.kind, doc.number),
                "qty": float(move.qty),
                "amount": float(move.amount),
                "balance": float(total),
            }
        )
    return out


def unit_get(session: Session, actor: Actor, unit_id: uuid.UUID) -> Unit:
    return get_unit(session, actor, unit_id)

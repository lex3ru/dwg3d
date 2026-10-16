"""План этажа — документ (9.4 п. 1). Единицы — миллиметры; ось X вправо, Y вверх, как в
чертежах. Этот файл — описание документа для сервера; то же описание у интерфейса —
web/src/editor/plan.ts."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

Id = Annotated[str, Field(min_length=1, max_length=64)]
Coord = Annotated[float, Field(ge=-1e7, le=1e7)]
Point = tuple[Coord, Coord]


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Wall(_M):
    id: Id
    a: Id  # узел начала
    b: Id  # узел конца
    thickness: float = Field(gt=0, le=3000)
    kind: Literal["bearing", "partition"] = "partition"
    # дуга: bulge = tg(θ/4), как в DXF; > 0 — дуга выгнута вправо от направления a → b
    bulge: float = Field(default=0, ge=-1, le=1)


class Opening(_M):
    id: Id
    wall: Id
    kind: Literal["door", "window", "passage", "glazing"]
    # центр проёма — расстояние вдоль стены от узла a
    at: float = Field(ge=-1e6, le=1e6)
    width: float = Field(gt=0, le=20000)
    height: float = Field(gt=0, le=20000)
    sill: float = Field(default=0, ge=0, le=20000)
    # дверь: петли у начала или у конца проёма, открывается влево или вправо от a → b
    hinge: Literal["start", "end"] = "start"
    side: Literal["left", "right"] = "left"
    label: str | None = Field(default=None, max_length=50)


class Column(_M):
    id: Id
    x: Coord
    y: Coord
    w: float = Field(gt=0, le=10000)
    d: float = Field(gt=0, le=10000)
    angle: float = 0
    round: bool = False


class Stair(_M):
    """Лестница с этого этажа на следующий выше: начинается в (x, y) — середина нижней
    ступени — и идёт в направлении angle (градусы) на length."""

    id: Id
    x: Coord
    y: Coord
    width: float = Field(gt=0, le=10000)
    length: float = Field(gt=0, le=30000)
    angle: float = 0
    steps: int = Field(default=12, ge=2, le=60)


class RoomLabel(_M):
    """Подпись помещения: по ней помещение узнаётся при правке плана (5.1.6). id — ключ
    помещения в базе; у новой подписи — временный, начинающийся с "new"."""

    id: Id
    x: Coord
    y: Coord
    number: str = Field(default="", max_length=30)
    name: str = Field(default="", max_length=200)
    purpose_id: str | None = Field(default=None, max_length=64)


class Underlay(_M):
    """Подложка: файл (PDF — страница page) кладётся так, что пиксель (0, 0) картинки — в
    точке (x, y), а один пиксель — scale мм; повернута на angle градусов."""

    file_id: str = Field(max_length=64)
    page: int = Field(default=1, ge=1, le=1000)
    x: Coord = 0
    y: Coord = 0
    scale: float = Field(default=10, gt=0, le=1e5)
    angle: float = 0
    opacity: float = Field(default=0.5, ge=0, le=1)
    visible: bool = True


class Plan(_M):
    nodes: dict[Id, Point] = {}
    walls: list[Wall] = []
    openings: list[Opening] = []
    columns: list[Column] = []
    stairs: list[Stair] = []
    rooms: list[RoomLabel] = []
    underlay: Underlay | None = None


EMPTY: dict[str, object] = Plan().model_dump()

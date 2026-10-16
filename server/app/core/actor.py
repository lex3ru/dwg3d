"""Кто действует. Строится модулем доступа, используется всеми модулями и журналом."""

from dataclasses import dataclass, field
from typing import Literal
from uuid import UUID

Role = Literal["admin", "viewer"]


@dataclass(frozen=True)
class Actor:
    user_id: UUID
    login: str
    full_name: str
    role: Role
    # здания, выданные «просмотру»; администратору доступны все (2.2)
    building_ids: frozenset[UUID] = field(default_factory=frozenset)

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    def can_see_building(self, building_id: UUID) -> bool:
        return self.is_admin or building_id in self.building_ids

    # «Просмотр» и гости не видят стоимость, инвентарные номера и проекты (2.2).
    # Модули проверяют это на сервере при каждом ответе (8.4 п. 3).
    @property
    def sees_cost(self) -> bool:
        return self.is_admin

    @property
    def sees_inventory_numbers(self) -> bool:
        return self.is_admin

    @property
    def sees_projects(self) -> bool:
        return self.is_admin

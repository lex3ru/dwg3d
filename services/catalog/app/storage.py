"""The catalog's bucket: 3D models of types (models/<type>/<id>.glb)."""
from __future__ import annotations

from functools import cache

from twin_chassis.files import Bucket


@cache
def bucket() -> Bucket:
    return Bucket("catalog")

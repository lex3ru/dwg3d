"""The service's bucket: photos and documents of objects (assets/<asset>/<file>)."""
from __future__ import annotations

from functools import cache

from twin_chassis.files import Bucket


@cache
def bucket() -> Bucket:
    return Bucket("assets")

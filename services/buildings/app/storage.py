"""The service's bucket: detailed facade models (facades/<building>/<id>.glb)."""
from __future__ import annotations

from functools import cache

from twin_chassis.files import Bucket


@cache
def bucket() -> Bucket:
    return Bucket("buildings")

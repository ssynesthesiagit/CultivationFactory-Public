"""Public source-learning adapter contract, used by table advancement.

Acquisitions remain in the existing sphere advancement rows. Providers validate
an owner's input before that row is saved, then project it onto the owner sheet.
This module neither grants talents nor interprets individual source rules.
"""
from typing import Any

from . import ext
from .tabletop import TabletopError


def options(sheet: dict, talents: list[dict]) -> list[dict]:
    return ext.run_strict("source_learning_options", sheet, talents)


def prepare(sheet: dict, sphere_id: str, choice: Any, talents: list[dict], *, gm: bool) -> dict | None:
    replies = ext.run_strict("prepare_source_learning", sheet, sphere_id, choice, talents, gm)
    if len(replies) > 1:
        raise TabletopError("TABLETOP_LEARNING_CONFLICT", "Two sources handle the same learning choice.", 409)
    if not replies and choice is not None:
        raise TabletopError("TABLETOP_LEARNING_UNKNOWN", "This Sphere has no such learning choice.", 400)
    return replies[0] if replies else None


def project(sheet: dict, row: dict) -> dict:
    replies = ext.run_strict("project_source_learning", sheet, row)
    if len(replies) > 1:
        raise ValueError("Two providers project the same source-learning row")
    return replies[0] if replies else sheet

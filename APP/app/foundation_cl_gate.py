"""The published Foundation acquisition rule, in one place.

A Foundation is only acquirable at the published acquisition CL carried by
``non_sphere_authority.foundation_mechanics.INITIAL_FOUNDATION_MECHANICS_POLICY``.
Four entry points have to enforce that rule: the creation form, the user-lock
freeze, the post-creation Foundation picker and the target-level picker.

Used by ``character_builder.service`` (creation request),
``project_store.service`` (user locks frozen before a build) and
``non_sphere_authority.service`` (``select_foundation``, ``set_target_cl``).

Callers pass the published acquisition CL in, so this module imports no owner
authority data and its tests can run on the public CI.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

from app.core import FoundryError

FOUNDATION_CL_TOO_LOW = "CHARACTER_FOUNDATION_CL_TOO_LOW"
TARGET_CL_FIELD = "target_cl"
LOCKED_CHOICES_FIELD = "character_sheet.locked_choices"


def foundation_below_acquisition_cl(
    *, target_cl: Any, acquisition_cl: int, foundation_ids: Iterable[Any] | None,
) -> bool:
    """True when a Foundation is chosen for a level below the published acquisition CL.

    Inert without a Foundation: characters that never picked one keep every
    target level. A missing or malformed level is left to the normal
    target-level validation instead of being treated as "below".
    """
    return bool(foundation_ids) and isinstance(target_cl, int) and target_cl < acquisition_cl


def foundation_cl_too_low_error(
    *,
    target_cl: Any,
    acquisition_cl: int,
    keeps_foundation: bool = False,
    details: Mapping[str, Any] | None = None,
) -> FoundryError:
    """Build the newcomer-readable refusal for a Foundation below its acquisition CL."""
    if keeps_foundation:
        action = (
            f"This character keeps a Foundation, so the target level cannot go below {acquisition_cl}. "
            f"Raise the target level to {acquisition_cl} or higher, or clear the Foundation first."
        )
    else:
        action = (
            f"Raise the intended level to {acquisition_cl} or higher, or leave the Foundation unset."
        )
    return FoundryError(
        FOUNDATION_CL_TOO_LOW,
        f"Foundations open at level {acquisition_cl}. {action}",
        details={"target_cl": target_cl, "acquisition_cl": acquisition_cl, **dict(details or {})},
    )


def refuse_foundation_below_acquisition_cl(
    *,
    target_cl: Any,
    acquisition_cl: int,
    foundation_ids: Iterable[Any] | None,
    keeps_foundation: bool = False,
    details: Mapping[str, Any] | None = None,
) -> None:
    """Raise ``CHARACTER_FOUNDATION_CL_TOO_LOW`` before anything is frozen or saved."""
    if not foundation_below_acquisition_cl(
        target_cl=target_cl, acquisition_cl=acquisition_cl, foundation_ids=foundation_ids,
    ):
        return
    raise foundation_cl_too_low_error(
        target_cl=target_cl,
        acquisition_cl=acquisition_cl,
        keeps_foundation=keeps_foundation,
        details=details,
    )


def locked_foundation_ids(new_locks: Iterable[Mapping[str, Any]]) -> list[Any]:
    """Foundation choices carried by the user locks being appended.

    A value that is not an object is left for the normal lock validation to
    reject; it must never crash the gate first.
    """
    foundation_ids: list[Any] = []
    for item in new_locks:
        if not isinstance(item, Mapping) or item.get("field") != LOCKED_CHOICES_FIELD:
            continue
        value = item.get("value")
        if not isinstance(value, Mapping):
            continue
        choices = value.get("foundation_choice")
        if isinstance(choices, list):
            foundation_ids.extend(choices)
    return foundation_ids


def effective_target_cl(old_locks: Iterable[Any], new_locks: Iterable[Any]) -> Any:
    """The last target level carried by the old and new locks (None when absent)."""
    return next((
        item.get("value") for item in reversed([*old_locks, *new_locks])
        if isinstance(item, Mapping) and item.get("field") == TARGET_CL_FIELD
    ), None)


def refuse_early_foundation_locks(
    *, old_locks: Iterable[Any], new_locks: Iterable[Mapping[str, Any]], acquisition_cl: int,
) -> None:
    """Refuse a Foundation lock below the acquisition CL before the lock freeze writes anything."""
    refuse_foundation_below_acquisition_cl(
        target_cl=effective_target_cl(old_locks, new_locks),
        acquisition_cl=acquisition_cl,
        foundation_ids=locked_foundation_ids(new_locks),
    )

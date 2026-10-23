"""Shared cleanup for conditions that make their bearer Incapacitated.

Data-defined persistent_companions remain when their parent condition ends.
The 2024 condition rules end Concentration when Incapacitated is imposed,
including through Stunned, Paralyzed, Petrified, or Unconscious. This lifecycle
hook uses Gate 2's evented ending path for current and held techniques.
"""

from __future__ import annotations

from typing import Any

from . import hook

@hook("event", nested=True)
def impose_persistent_companions(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """Impose independent conditions on application and legacy-save removal.

    Nested delivery includes healing/condition-removal inside another event
    consumer. No configured companion, or an already present one, is inert.
    """
    if event_type not in {"CONDITION_APPLIED", "CONDITION_REMOVED"}:
        return
    payload = kwargs.get("payload") or {}
    if payload.get("retained_instance_update"):
        return
    from ..typed_executor import CONDITION_PREFIX, rules

    name = str(payload.get("condition_id") or "")
    name = name[len(CONDITION_PREFIX):] if name.startswith(CONDITION_PREFIX) else ""
    name = (rules().get("condition_aliases") or {}).get(name, name)
    definition = rules()["conditions"].get(name, {})
    # Some imposed conditions remain after their parent ends (2024 Unconscious
    # leaves the creature Prone). These use ordinary persisted condition events,
    # not a temporary rule overlay or a parent-coupled expiry. The removal edge
    # also covers pre-fix saves which never stored the companion on application.
    for target_id in kwargs.get("target_ids") or ():
        actor = engine.state.actors.get(target_id)
        if actor is None:
            continue
        for companion in definition.get("persistent_companions") or ():
            cid = CONDITION_PREFIX + companion
            if any(c.condition_id == cid for c in actor.conditions.values()):
                continue
            engine._apply_condition(actor, cid, kwargs.get("source_definition_id") or "system:condition",
                                    kwargs.get("actor_id") or actor.entity_id,
                                    expires_on="STAND_UP" if rules()["conditions"].get(companion, {}).get("ends_on_stand_up") else "UNTIL_REMOVED")
@hook("event", nested=True)
def end_concentration_on_incapacitation(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """Notify consumers, then end all current and held Concentration on new incapacity."""
    if event_type != "CONDITION_APPLIED":
        return
    payload = kwargs.get("payload") or {}
    if payload.get("retained_instance_update"):
        return
    from .needle import incapacitated  # the shared test ends_if_incapacitated uses: Incapacitated or any state including it

    for target_id in kwargs.get("target_ids") or ():
        actor = engine.state.actors.get(target_id)
        if actor is None or not incapacitated(actor):
            continue
        from . import run

        run("became_incapacitated", engine, actor, kwargs)
        # Ending the current copy resumes the newest held copy. Keep using the
        # engine path until that resume chain is exhausted.
        while actor.concentration is not None:
            engine._end_concentration(actor, "INCAPACITATED")
        from .. import concentration

        concentration.end_all_held(engine, actor, "INCAPACITATED")

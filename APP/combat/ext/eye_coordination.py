"""Hidden Eye talents that share an ability with allies (eye, 2026-09-28): Cooperative Stealth, Advisory Stalker,
Meridian-Seeking Ledger. Court of the Hidden Eye needed only a typing correction (reviewed_final.d/eye.json); Advisory
Researcher still needs target-scoped temporary talent grants. Cooperative
Perception's qualified passive observations are in riders14_awareness.py.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook
from .eye_common import ANALYZED, FOCUS, has, numbers_of
from .condition_events import drop_condition as _drop

COOPERATIVE_STEALTH = "TAL_THE_HIDDEN_EYE_COOPERATIVE_STEALTH"
COOP_STEALTH_TAG = "condition:typed.cooperative_stealth_available"
COOP_SOURCE = "passive:eye.cooperative_stealth"

MERIDIAN = "tianxia.talent.the_hidden_eye.meridian_seeking_ledger"
LEDGER = "condition:typed.meridian_ledger"
LEDGER_SOURCE = "passive:eye.meridian_seeking_ledger"
LEDGER_OPTIONS = [
    ("attack", "Advantage on its next attack roll", [
        {"type": "advantage", "applies_to": "target", "on": "its next attack roll",
         "evidence": "Meridian-Seeking Ledger: Advantage on its next attack roll against the recorded target."}]),
    ("save", "Advantage on its next save vs. the target", [
        {"type": "advantage", "applies_to": "target", "on": "its next saving throw against an effect created by the recorded target",
         "evidence": "Meridian-Seeking Ledger: Advantage on its next saving throw against an effect created by the recorded target "
                     "(GM-adjudicated: this table has no save-advantage hook scoped to one specific source creature)."}]),
    ("detect", "+PB on its next check about the target", [
        {"type": "rider", "evidence": "Meridian-Seeking Ledger: +Proficiency Bonus on its next Wisdom (Perception), Wisdom "
                                      "(Insight), or Wisdom (Survival) check made to detect, follow, or understand the recorded target."}]),
]


# ---------------------------------------------------------------- Cooperative Stealth
@hook("event")
def cooperative_stealth_tag(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """"When you successfully take the Hide action, choose a number of willing allies within range equal to your
    Proficiency Bonus [doubled while you hold Martial Focus]. Each chosen ally... may use your recorded Dexterity
    (Stealth) check total in place of its own... before the start of your next turn." "Choose" defaults to the
    nearest eligible allies, since the built-in AI has no other preference."""
    if event_type != "CONDITION_APPLIED":
        return None
    from .. import stealth

    payload = kwargs.get("payload") or {}
    if payload.get("condition_id") != stealth.HIDDEN:
        return None
    owner = engine.state.actors.get(kwargs.get("actor_id") or "")
    if owner is None or not has(engine, owner.entity_id, "cooperative_stealth"):
        return None
    iid = stealth.hidden(owner)
    if iid is None:
        return None
    total = int((owner.conditions[iid].data or {}).get("stealth_total") or 0)
    pb = int(numbers_of(engine, owner).get("pb") or 2)
    count = pb * (2 if owner.resources.get(FOCUS, 0) >= 1 else 1)
    allies = sorted((other for other in engine.state.actors.values() if other.active and other.entity_id != owner.entity_id
                     and other.team_id == owner.team_id and engine.grid.distance_ft(other.position, owner.position) <= 60),
                    key=lambda other: engine.grid.distance_ft(other.position, owner.position))
    from .needle import CHOICE, ask, checkpoint_id

    chosen = ask(engine, getattr(engine, "_active_intent", None),
                 checkpoint_id(engine, "EYE_COOPERATIVE_STEALTH", owner.entity_id), owner,
                 CHOICE + "eye_cooperative_stealth", [a.entity_id for a in allies],
                 labels={a.entity_id: a.display_name for a in allies}, maximum=count, allow_decline=True,
                 preferred=[a.entity_id for a in allies][:count],
                 prompt=f"Cooperative Stealth after {owner.display_name}'s successful Hide: choose allies to share the Stealth total")
    for ally in allies:
        if ally.entity_id not in chosen:
            continue
        for existing_iid, condition in list(ally.conditions.items()):
            if condition.condition_id == COOP_STEALTH_TAG and condition.source_actor_id == owner.entity_id:
                _drop(engine, ally, existing_iid, COOP_SOURCE)
        engine._apply_condition(ally, COOP_STEALTH_TAG, COOP_SOURCE, owner.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN",
                                data={"total": total})
    return None


@hook("hide_check_override")
def cooperative_stealth_override(engine: Any, actor: Any) -> int | None:
    tags = [(iid, condition) for iid, condition in actor.conditions.items() if condition.condition_id == COOP_STEALTH_TAG]
    tag = max(tags, key=lambda pair: int((pair[1].data or {}).get("total") or 0), default=None)
    if tag is None:
        return None
    iid, condition = tag
    total = int((condition.data or {}).get("total") or 0)
    owner = engine.state.actors.get(condition.source_actor_id or "")
    from .needle import CHOICE, ask, checkpoint_id

    picked = ask(engine, getattr(engine, "_active_intent", None),
                 checkpoint_id(engine, "EYE_USE_COOPERATIVE_STEALTH", actor.entity_id), actor,
                 CHOICE + "eye_use_cooperative_stealth", ["shared_total"], allow_decline=True,
                 labels={"shared_total": f"Use shared Stealth total {total}"},
                 prompt=f"Cooperative Stealth on {actor.display_name}'s Hide: use {owner.display_name if owner else 'the ally'}'s recorded total?")
    if not picked:
        return None
    _drop(engine, actor, iid, COOP_SOURCE)  # one use, spent whether or not the Hide attempt then succeeds
    if owner is not None and has(engine, owner.entity_id, "advisory_stalker"):
        engine._append_event("GM_RIDER", "passive:eye.advisory_stalker", actor_id=owner.entity_id, target_ids=(actor.entity_id,),
                             payload={"rider": f"Advisory Stalker: choose one Stalker talent {owner.display_name} knows for "
                                      f"{actor.display_name} to gain while it stays hidden through this use of Cooperative Stealth."})
    return total


# ---------------------------------------------------------------- Meridian-Seeking Ledger
@hook("event")
def meridian_ledger_record(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type != "CONDITION_APPLIED":
        return None
    payload = kwargs.get("payload") or {}
    if payload.get("condition_id") != ANALYZED:
        return None
    owner = engine.state.actors.get(kwargs.get("actor_id") or "")
    if owner is None or not has(engine, owner.entity_id, "meridian_seeking_ledger"):
        return None
    target_id = next(iter(kwargs.get("target_ids") or ()), None)
    if not target_id:
        return None
    capacity = max(1, int(numbers_of(engine, owner).get("key_mod") or 0))
    existing = sorted(((iid, condition) for iid, condition in owner.conditions.items() if condition.condition_id == LEDGER),
                      key=lambda pair: pair[1].applied_sequence)
    if len(existing) >= capacity:
        _drop(engine, owner, existing[0][0], LEDGER_SOURCE)
    engine._apply_condition(owner, LEDGER, LEDGER_SOURCE, owner.entity_id, expires_on="UNTIL_REMOVED", data={"target_id": target_id})
    return None


@hook("compile_actions")
def meridian_ledger_advise(info: dict[str, Any]) -> list[Any] | None:
    if MERIDIAN not in info["owned_ids"]:
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    from ..action_variants import choice, with_variant
    rows = [ActionDefinition(
        source_definition_id=f"action:typed.{info['short']}.meridian_ledger.{key}", display_name=f"Advise (Ledger): {label}",
        owner_id=info["actor_id"], economy=EconomyKind.BONUS_ACTION, resolution_kind="TYPED", target_kind="ALLY_OR_SELF",
        parameters={"typed": {"effects": [{"type": "meridian_consume_ledger"}, *effects], "numbers": info["numbers"],
                              "duration": {"kind": "instant"},
                              "riders": ["Advising instead takes 1 minute of explanation outside combat; this table offers the "
                                        "Bonus Action form only, the realistic one mid-fight."]},
                    "expected_damage": 0})
        for key, label, effects in LEDGER_OPTIONS]
    return [with_variant(row, f"action:typed.{info['short']}.meridian_ledger", "Advise (Ledger)", [choice("advice", key, label)])
            for row, (key, label, _effects) in zip(rows, LEDGER_OPTIONS)]


@hook("candidate_allowed")
def meridian_ledger_candidate(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if action is None or ".meridian_ledger." not in str(getattr(action, "source_definition_id", "")):
        return None
    return any(condition.condition_id == LEDGER for condition in actor.conditions.values())


@effect("meridian_consume_ledger")
def meridian_consume_ledger(ctx: Any, eff: dict[str, Any]) -> None:
    owner = ctx.actor
    ledgers = sorted(((iid, condition) for iid, condition in owner.conditions.items() if condition.condition_id == LEDGER),
                     key=lambda pair: pair[1].applied_sequence)
    if not ledgers:
        ctx.rider("Meridian-Seeking Ledger: no ledger recorded; nothing to advise about.")
        return
    iid, condition = ledgers[0]
    target = ctx.engine.state.actors.get((condition.data or {}).get("target_id") or "")
    _drop(ctx.engine, owner, iid, ctx.source)
    who = ctx.target.display_name if ctx.target is not None else "an ally"
    about = target.display_name if target is not None else "its recorded target"
    ctx.rider(f"Meridian-Seeking Ledger: advising {who} about {about}.")

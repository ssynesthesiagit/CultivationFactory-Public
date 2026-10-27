"""Pressure Points riders (rider lane C2, 2026-09-30: "i want everything we can automated").  Rules text: the owner's Sphere Compendium,
"Pressure Points" (authority/typed_mechanics/rules_text.json).  Touch the Point itself, and applying the Point / closing the Seal a
character picked, is combat/ext/shi_pressure_points.py; its public ``apply_point`` is reused here for "apply one Point talent you know".

  pp_apply_point        effect: apply the character's picked Point (with its Pressure Point mark) to the effect's target -- Retaliatory
                        Nerve's and Intercepting Tap's hit.
  Needle Meets Blade    ``hit_absorbed``: when its reduction takes the melee hit to 0, apply one Point to the attacker.
  pp_eye_watering       effect: the next Wisdom (Perception) check, ranged attack roll, or attack roll against a creature more than 10 feet
                        away before the start of the user's next turn has Disadvantage (``attack_mode`` for the attack rolls).
  pp_dazed              effect: Shut the Heaven Gate's Dazed -- no Reactions, and an Action or a Bonus Action on its turn, not both
                        (``candidate_allowed``), until the start of the user's next turn.
  Meridian Stillness Field  for hostile creatures inside it that bear the user's Pressure Point: Speed -10 and no Opportunity Attacks
                        (``speed``, ``opportunity_allowed``); its once-a-round technique save is the area's own typed "technique"
                        trigger, fired from ``technique_start`` for any technique (combat/ext/qi_instability.py fires the same moment
                        for techniques that cost CP; the trigger's per_round key keeps it to one save a round).
Every hook returns early unless the creature carries one of this module's conditions or stands in such a field.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook

EYE = "condition:typed.pp_eye_watering"
DAZED = "condition:typed.pp_dazed"
FIELD = "tianxia.talent.pressure_points.meridian_stillness_field"
NEEDLE = "tianxia.talent.pressure_points.needle_meets_blade"
PATIENT = "tianxia.talent.pressure_points.patient_hand"


@hook('compile_block')
def patient_compile(block, spec, row, numbers):
    if block == 'pp_patient_hand':
        return [{**row, 'range_ft': 30, **({'second_pass': True} if spec.get('second_pass') else {})}]


@hook('resolution_final')
def patient_focus(engine, actor, action, candidate, intent):
    """An actual Dodge, Search or Study restores absent Focus in a perceived fight."""
    from ..gate2_runtime_models import EconomyKind
    from ..relations import relation, ENEMY
    from ..senses import perceives
    rows = [r for r in engine.typed_passive_rows.get(actor.entity_id, []) if r.get('block') == 'pp_patient_hand']
    if not rows or not actor.active or action.economy != EconomyKind.ACTION:
        return
    parameters = action.parameters or {}
    qualifies = (action.source_definition_id == 'system:combat.dodge'
                 or parameters.get('stealth') == 'search' or parameters.get('illusion_study') == 1)
    focus = 'resource:core.martial_focus'
    if not qualifies or actor.resources.get(focus, 0) >= 1:
        return
    if any(other.active and relation(engine, actor, other) == ENEMY
           and engine._distance_actor_to_actor(actor, other) <= 30 and perceives(engine, actor, other)
           for other in engine.state.actors.values()):
        engine._gain_resource(actor, focus, 1, PATIENT)
        if any(r.get('second_pass') for r in rows):
            from .pressure_points_second_pass import grant_patient
            grant_patient(engine, actor, intent)


@effect("pp_apply_point")
def apply_point_effect(ctx: Any, eff: dict[str, Any]) -> None:
    from .shi_pressure_points import apply_point

    for target in ctx.targets or ([ctx.target] if ctx.target else []):
        if target is not None and target.active:
            apply_point(ctx, target)


@hook("hit_absorbed")
def needle_meets_blade(engine: Any, target: Any, attacker: Any, reduced_by: Any) -> None:
    """Needle Meets Blade: "If this reduces the damage to 0, apply one Point talent you know to the attacker.\""""
    if NEEDLE not in tuple(reduced_by or ()) or attacker is None or not attacker.active or not target.active:
        return
    from ..typed_reactions import triggered_context
    from .needle import numbers_of
    from .shi_pressure_points import apply_point

    from .attack_reduction import follow_up_scope
    with follow_up_scope(engine, target, attacker.entity_id, NEEDLE):
        ctx = triggered_context(engine, target, attacker, {"feature_id": NEEDLE, "name": "Needle Meets Blade", "numbers": numbers_of(engine, target),
                                                            "effects": []})
        apply_point(ctx, attacker)


# ------------------------------------------------------------------------------------------------ Eye-Watering Point
@effect("pp_eye_watering")
def eye_watering(ctx: Any, eff: dict[str, Any]) -> None:
    from ..typed_executor import effect_expiry

    for subject in ctx.targets or ([ctx.target] if ctx.target else []):
        if subject is None or not subject.active:
            continue
        ctx.engine._remove_condition(subject, EYE, ctx.source)
        ctx.engine._apply_condition(subject, EYE, ctx.source, ctx.actor.entity_id,
                                    expires_on=effect_expiry(ctx, {"duration": "until_start_of_your_next_turn"}, subject, condition=True),
                                    data={"label": "Eye-Watering Point: Disadvantage on the next Perception check, ranged attack or attack beyond 10 feet, before the user's next turn",
                                          "rule": {"check_mode": {"Perception": "DISADVANTAGE"}}})


@hook("attack_mode")
def eye_watering_attack(ctx: Any, target: Any) -> str | None:
    """Disadvantage on the blurred creature's next ranged attack roll or attack roll against a creature more than 10 feet away."""
    engine, actor = ctx.engine, ctx.actor
    held = next((c for c in actor.conditions.values() if c.condition_id == EYE), None)
    if held is None or target is None:
        return None
    ranged = ctx.typed.get("range_ft") is not None and int(ctx.typed.get("range_ft") or 0) > 5
    if not ranged and engine._distance_actor_to_actor(actor, target) <= 10:
        return None
    engine._remove_condition(actor, EYE, held.source_definition_id)  # "the next ... attack roll"
    return "DISADVANTAGE"


@hook("ability_check_mode")
def eye_watering_perception(engine: Any, actor: Any, ability: str, skill: str, against: Any) -> str | None:
    held = next((c for c in actor.conditions.values() if c.condition_id == EYE), None)
    if held is None or str(skill or "").lower() != "perception":
        return None
    return "DISADVANTAGE"


@hook("search_mode")
def eye_watering_search(engine: Any, actor: Any) -> str | None:
    """Pure mode query also supports older saved Eye-Watering conditions."""
    return "DISADVANTAGE" if any(c.condition_id == EYE for c in actor.conditions.values()) else None


@hook("event")
def eye_watering_check_used(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """Consume on an actual qualifying roll, never on a mode query or automatic
    detection without a roll. Analyze identifies the chosen skill in its reason.
    """
    if event_type != "CHECK_ROLLED":
        return
    payload = kwargs.get("payload") or {}
    roll = payload.get("actor") or {}
    if roll.get("natural_result") is None:
        return
    skill = str(payload.get("check") or payload.get("skill") or "").lower()
    if skill != "perception" and not str(roll.get("reason") or "").lower().endswith(":perception"):
        return
    actor = engine.state.actors.get(kwargs.get("actor_id"))
    if actor is not None:
        for held in list(actor.conditions.values()):
            if held.condition_id == EYE:
                engine._remove_condition(actor, EYE, held.source_definition_id)


# ------------------------------------------------------------------------------------------------ Dazed (Shut the Heaven Gate)
# The printed Daze and the Action-or-Bonus restriction are shared: combat/ext/dazed_restriction.py owns both.
@effect("pp_dazed")
def dazed(ctx: Any, eff: dict[str, Any]) -> None:
    from ..typed_executor import effect_expiry

    from . import dazed_restriction

    for subject in ctx.targets or ([ctx.target] if ctx.target else []):
        dazed_restriction.apply(ctx.engine, subject, DAZED, ctx.source, ctx.actor.entity_id,
                                expires_on=effect_expiry(ctx, {"duration": "until_start_of_your_next_turn"}, subject, condition=True),
                                label="Dazed: no Reactions; an Action or a Bonus Action, not both, until the user's next turn")


# ------------------------------------------------------------------------------------------------ Meridian Stillness Field
def _fields_on(engine: Any, creature: Any) -> list[Any]:
    """The Meridian Stillness Fields holding ``creature``: hostile to their maker and bearing its Pressure Point."""
    from .. import zones, typed_executor as te
    from ..relations import relation, ENEMY

    out = []
    for zone in zones.typed_zones(engine):
        action = engine.action_catalog.get(zone.source_definition_id)
        if (((getattr(action, "parameters", None) or {}).get("typed") or {}).get("source")) != FIELD:
            continue
        owner = engine.state.actors.get(zone.owner_id)
        if owner is None or relation(engine, owner, creature) != ENEMY or not te.bears_mark(creature, owner.entity_id, "Pressure Point"):
            continue
        if engine._footprint_intersects(creature, {(cell.x, cell.y) for cell in zone.affected_cells}):
            out.append(zone)
    return out


@hook("speed")
def field_speed(engine: Any, actor: Any) -> int | None:
    return -10 if _fields_on(engine, actor) else None


@hook("opportunity_allowed")
def field_no_opportunity(engine: Any, reactor: Any, mover: Any) -> bool | None:
    return False if _fields_on(engine, reactor) else None


@hook("concentration_mode_removed")
def field_no_concentration_advantage(engine: Any, actor: Any) -> set[str] | None:
    """"cannot benefit from Advantage on Concentration saving throws" (rider lane C14: combat/concentration.py save_mode)."""
    return {"ADVANTAGE"} if _fields_on(engine, actor) else None


@hook("technique_start")
def field_technique(engine: Any, actor: Any, action: Any) -> bool | None:
    """Meridian Stillness Field: "the first time each round they activate a non-Secret technique, they make a Constitution saving throw" --
    the field's own "technique" trigger (once a round, only for a creature bearing the maker's Pressure Point: its typed trigger)."""
    typed = ((getattr(action, "parameters", None) or {}).get("typed") or {})
    source = str(getattr(action, "source_definition_id", "") or "")
    if not actor.active or not typed.get("source") or ".weapon." in source or source.startswith("system:") or typed.get("weapon"):
        return None  # a technique, not a weapon attack or a table action
    from .. import zones
    from .qiweaving_common import is_secret_inheritance

    if is_secret_inheritance(action):
        return None
    for zone in _fields_on(engine, actor):
        zones.fire_trigger(engine, zone, actor, "technique")
    return None

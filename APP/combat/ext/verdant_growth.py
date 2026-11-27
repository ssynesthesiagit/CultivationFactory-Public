"""Verdant Growth riders (rider lane C2, 2026-09-30).  Rules text: the owner's Sphere Compendium, "Sphere of Verdant Growth".

Only the lines that do not need the sphere's chassis live here.  The chassis -- Living Claims, Growth Mark counting and the Verdant
Responses -- and the talents built on it are combat/ext/verdant_chassis.py (rider lane C16).

  Thousand-Root Prison  successful ``MOVEMENT_COMMITTED`` teleport: "If the target teleports, the roots tear away and the effect ends, but the target takes 4d10
                        Piercing damage" -- the teleport goes ahead; the Restrained the prison put on it ends and the roots deal the damage.
"""

from __future__ import annotations

from typing import Any

from . import hook


@hook('attack_geometry_mode')
def canopy_crossing(engine, attacker, target, ranged):
    """Printed ranged crossing penalty; light obscurement alone is no penalty."""
    if ranged is not True:
        return None
    from ..zones import typed_zones, actor_inside_zone
    from ..zone_attack_geometry import path_distance_ft
    canopy = 'TAL_VERDANT_GROWTH_CANOPY_OF_TEN_THOUSAND_LEAVES'
    for zone in typed_zones(engine):
        owner = engine.state.actors.get(zone.owner_id)
        action = engine.action_catalog.get(zone.source_definition_id)
        if (owner is None or action is None or action.owner_id != owner.entity_id
                or ((action.parameters or {}).get('typed') or {}).get('source') != canopy):
            continue
        if (actor_inside_zone(engine, attacker, zone)
                and actor_inside_zone(engine, target, zone)):
            continue  # the printed inside-to-inside exception
        if path_distance_ft(engine, zone, attacker, target) >= 10 - 1e-9:
            return {'mode': 'DISADVANTAGE', 'effect': 'Canopy of Ten Thousand Leaves',
                    'owner': owner.display_name, 'why': 'ranged attack passes through 10+ feet of canopy'}
    return None

PRISON = "TAL_VERDANT_GROWTH_THOUSAND_ROOT_PRISON"


@hook('standing_roll_reasons')
def canopy_standing(engine, actor):
    from ..zones import typed_zones, actor_inside_zone
    for zone in typed_zones(engine):
        action = engine.action_catalog.get(zone.source_definition_id)
        owner = engine.state.actors.get(zone.owner_id)
        if (owner is not None and action is not None and action.owner_id == owner.entity_id
                and ((action.parameters or {}).get('typed') or {}).get('source') ==
                'TAL_VERDANT_GROWTH_CANOPY_OF_TEN_THOUSAND_LEAVES' and actor_inside_zone(engine, actor, zone)):
            return ['Attacks against you: Disadvantage for ranged attacks passing through 10+ feet of Canopy of Ten Thousand Leaves, unless both creatures are inside.']
    return None
HOLDS = ("condition:typed.restrained", "condition:typed.grappled")


@hook("event")
def prison_tears(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """Tear once per prison only after movement succeeds; authorization is pure."""
    if event_type != "MOVEMENT_COMMITTED" or not (kwargs.get("payload") or {}).get("teleport"):
        return
    actor = engine.state.actors.get(kwargs.get("actor_id"))
    if actor is None:
        return
    torn = set()
    for condition in list(actor.conditions.values()):
        if condition.condition_id not in HOLDS:
            continue
        action = engine.action_catalog.get(condition.source_definition_id)
        if (((getattr(action, "parameters", None) or {}).get("typed") or {}).get("source")) != PRISON:
            continue
        caster = engine.state.actors.get(condition.source_actor_id)
        engine._remove_condition(actor, condition.condition_id, condition.source_definition_id)
        key = (condition.source_actor_id, condition.source_definition_id)
        if caster is None or key in torn:
            continue
        torn.add(key)
        from .. import typed_executor as te

        typed = {**((action.parameters or {}).get("typed") or {}), "effects": []}
        te.run_effects(te.Context(engine, caster, action, None, typed, [actor], actor, {}),
                       [{"type": "damage", "applies_to": "target", "dice": {"count": 4, "sides": 10}, "damage_types": ["piercing"],
                         "evidence": "Thousand-Root Prison: the roots tear away as it teleports, 4d10 Piercing"}])


@hook("event", nested=True)
def incarnation_fire(engine, event_type, kwargs):
    """Committed Fire, including damage absorbed by temp HP, suppresses the next incarnation claim."""
    if event_type != "DAMAGE_COMMITTED":
        return
    payload = kwargs.get("payload") or {}
    if str(payload.get("damage_type") or "").upper() != "FIRE" or int(payload.get("reduced_to") or 0) <= 0:
        return
    from . import verdant_chassis as verdant
    from .states import active
    for aid in kwargs.get("target_ids") or ():
        actor = engine.state.actors.get(aid)
        if (actor is None or (verdant.row(engine, actor, "verdant_incarnation") or {}).get("fire_stunts_claim") != 1
                or not active(engine, actor, "verdant_incarnation")):
            continue
        engine._remove_condition(actor, "condition:typed.verdant_scorched",
            "tianxia.talent.verdant_growth.verdant_incarnation_body_becomes_the_ancient_tree")
        engine._apply_condition(actor, "condition:typed.verdant_scorched",
            "tianxia.talent.verdant_growth.verdant_incarnation_body_becomes_the_ancient_tree", actor.entity_id,
            # The owner-start hook consumes this after suppressing its next free claim.
            expires_on="CONSUMED",
            data={"label": "Fire prevents your next free Living Claim from Verdant Incarnation."})


@hook('save_mode')
def medicinal_native_save(engine, target, ability, dc, source_id, roll_context):
    """Native repeat saves name their actual held condition; typed saves use their outcome-aware hook."""
    from ..typed_executor import active_save_pending
    if str(ability).upper() != 'CON' or active_save_pending(engine,source_id,target.entity_id):
        return None
    sprout = next((c for c in target.conditions.values()
                   if c.condition_id == 'condition:typed.verdant_medicinal'
                   and (c.data or {}).get('medicinal_categories') == 1),None)
    if sprout is None or not {'poisoned','disease'} & set((roll_context or {}).get('named') or []):
        return None
    from .rider_support import remove_instance
    remove_instance(engine,target,sprout.instance_id,sprout.source_definition_id)
    return 'ADVANTAGE'


@hook('save_effects')
def medicinal_typed_save(ctx, subject, ability, fail_effects, success_effects, categories):
    """A pending condition must directly affect this CON-saving creature."""
    if str(ability).upper() != 'CON':
        return None
    sprout = next((c for c in subject.conditions.values()
                   if c.condition_id == 'condition:typed.verdant_medicinal'
                   and (c.data or {}).get('medicinal_categories') == 1),None)
    if sprout is None:
        return None
    from dataclasses import replace
    from ..typed_executor import effect_subjects
    direct = replace(ctx,target=subject,targets=[subject])
    relevant = bool(set(categories) & {'disease','environmental_exposure_exhaustion','ongoing_poison_damage'}) or any(
        e.get('type') == 'condition' and str(e.get('condition') or '').lower() in ('poisoned','disease')
        and subject in effect_subjects(direct,e,harmful=True) for e in fail_effects)
    if not relevant:
        return None
    from .rider_support import remove_instance
    remove_instance(ctx.engine,subject,sprout.instance_id,sprout.source_definition_id)
    return {'modes':['ADVANTAGE']}

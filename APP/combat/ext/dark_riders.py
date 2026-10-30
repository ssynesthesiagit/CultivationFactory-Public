"""Dark sphere riders (rider lane C4, 2026-09-30; owner: "i want everything we can automated, keep going until its only the
non-combat ones left"). combat/ext/tabik_dark.py already runs the Darkness talents' areas (Clinging, Directional, Rolling Blackout,
Creeping Lethargy, Fearful Darkness, Dark Slaughter); combat/zones.py shapes the Darkness with the chosen talent (its
``talents`` names). This adds the lines that were still read to the GM. Each hook returns early unless a creature is affected by a
Darkness area whose owner chose that talent.

- Black Lung: "A creature Poisoned by Black Lung that attempts to activate an ability requiring clear speech must make a Constitution
  saving throw. On a failure, the activation fails and the action and any CP spent are lost." (technique_start; combat/speech.py
  needs_voice decides which abilities need clear speech).
- Snagging Darkness: "A Restrained creature may use a Bonus Action to make a Strength (Athletics) or Dexterity (Acrobatics) check
  against your Cultivation Save DC, ending the condition on itself on a success." (a Bonus Action every such creature gets).
- Shadow Slick: "Creatures inside the area have Advantage on Dexterity checks made to escape the Grappled condition." (escape_mode,
  for a creature whose Dexterity is at least its Strength -- the escape check is the better of Athletics or Acrobatics).
- Creeping Lethargy: "Another creature may use an Action to wake a creature asleep from Creeping Lethargy" (an Action offered to a
  creature beside a sleeping ally).
- Blindfold: "Darkvision does not overcome Blindfold. A creature that can see through supernatural Darkness is immune."
  (condition_attempt, scoped to Blindfold's own incoming Blinded row -- see the handler). The end-of-turn repeat save
  is the engine's own ``repeat_save``, typed on the record (combat/typed_executor.py reads it, combat/gate2_engine.py
  rolls it), so only the immunity was left to read.

Still the GM's on Disorienting Darkness: "The creature moves as though the rolled direction were its intended route".
Rotating a declared move destination has no seam -- combat/gate2_engine.py resolves it and is a saved-fight lock
file -- so the reroll and its 0 CP Reaction are recorded as a lock-round item rather than faked at the step level.
"""
from __future__ import annotations

import copy
from typing import Any

from . import effect, hook

RESTRAINED, POISONED, GRAPPLED, ASLEEP = ("condition:typed.restrained", "condition:typed.poisoned", "condition:typed.grappled",
                                          "condition:typed.unconscious")
SNAG_ESCAPE, WAKE = "system:combat.dark_snag_escape", "system:combat.dark_wake"


@hook("flight")
def night_flight(engine: Any, actor: Any) -> dict[str, int]:
    """One With The Night grants actual flight while its Concentration state lasts."""
    from .states import active
    from ..concentration import concentrating_on

    state = active(engine, actor, "one_with_the_night")
    if state is None or not concentrating_on(actor, state.source_definition_id):
        return {}
    return {"fly_speed_ft": 30, "flight_hover": 1}


@hook("damage_defenses")
def night_nonmagical_resistance(engine: Any, target: Any, damage_type: str,
                               typed: dict[str, Any], source_actor_id: str | None) -> list[dict[str, Any]] | None:
    """Reviewed Night state resists only explicitly mundane physical packets.

    The shared defense pipeline supplies source classification for native and
    typed damage, and handles rounding/non-stacking. Old sealed actions retain
    their own resistance modifiers and never opt into this replacement reader.
    """
    if typed.get("mundane") is not True:
        return None
    _state, kinds = _night_kinds(engine, target)
    return [{"kind": "resistance", "damage_types": kinds, "mundane_only": True}] if damage_type in kinds else None


@hook("defense_description")
def night_nonmagical_description(engine: Any, target: Any) -> list[dict[str, Any]] | None:
    """One With the Night's Resistance, as the Defences card names it: "only against nonmagical attacks"."""
    state, kinds = _night_kinds(engine, target)
    return [{"feature_id": state.source_definition_id, "damage_types": kinds,
             "note": "only against nonmagical attacks"}] if state is not None and kinds else None


def _night_kinds(engine: Any, target: Any) -> tuple[Any, list[str]]:
    """The live One With the Night state and its nonmagical damage types (none unless concentration and source hold).

    Shared by the damage resolver and the Defences card, so both read the same gate."""
    from .states import active
    from ..concentration import concentrating_on

    state = active(engine, target, "one_with_the_night")
    if state is None or not concentrating_on(target, state.source_definition_id):
        return None, []
    action = engine.action_catalog.get(state.source_definition_id)
    source = (action.parameters.get("typed") or {}) if action else {}
    if source.get("source") != "TAL_DARK_ONE_WITH_THE_NIGHT":
        return None, []
    return state, [str(kind).upper() for eff in source.get("effects") or []
                   if eff.get("type") == "state" and eff.get("name") == "one_with_the_night"
                   for kind in eff.get("nonmagical_resistance") or []]


def _darkness(engine: Any, source: str) -> list[Any]:
    """The live Darkness areas made by this action (a condition's source)."""
    from .. import zones

    return [zone for zone in zones.typed_zones(engine) if zone.source_definition_id == source]


def _from_talent(engine: Any, condition: Any, talent: str) -> Any:
    return next((zone for zone in _darkness(engine, condition.source_definition_id) if talent in (zone.trigger_profile.get("talents") or [])), None)


# ------------------------------------------------------------------------------------------------ Blindfold
BLINDFOLD = "TAL_DARK_BLINDFOLD"


def _sees_supernatural_darkness(engine: Any, creature: Any) -> bool:
    """Whether the creature's own senses reach through magical darkness of any kind.

    Read from the one shared table of what pierces what (combat/rules/senses.json): a sense whose "through" list
    carries "darkness" sees through supernatural Darkness, while Darkvision carries only "darkness_named" -- it
    sees through the sphere's plain Darkness and no further. That is the printed line exactly: "Darkvision does not
    overcome Blindfold. A creature that can see through supernatural Darkness is immune."
    """
    from .. import senses

    return senses.sees_through_unconditionally(engine, creature, "darkness")


@hook("condition_attempt")
def blindfold_immune(ctx: Any, subject: Any, effect_row: dict[str, Any] | None) -> bool | None:
    """"Darkvision does not overcome Blindfold. A creature that can see through supernatural Darkness is immune."

    Scoped to the *incoming* effect, which is what makes it Blindfold's own printed exception and not a blanket
    immunity: the row refused here must be the Blinded condition of Blindfold's own failed save
    (``condition_attempt`` is asked with the source actor, the action and the exact condition row before the
    condition is applied). Every other source's Blinded -- a Light sphere's flare, a mundane Darkness, another
    talent -- is untouched, for this creature and for every other creature.

    The victim does not have to own Blindfold. The printed exception belongs to the effect: a Truesighted or
    Blindsight creature cannot be blinded *by Blindfold*, whether or not it can cast it.
    """
    row = effect_row or {}
    if subject is None or str(row.get("condition") or "").lower() != "blinded":
        return None
    from .ability_source import mechanic_of

    if mechanic_of(ctx.action) != BLINDFOLD:
        return None
    if not _sees_supernatural_darkness(ctx.engine, subject):
        return None
    return False


# ------------------------------------------------------------------------------------------------ Black Lung
@hook("technique_start")
def black_lung_speech(engine: Any, actor: Any, action: Any) -> bool | None:
    from .. import speech
    from . import note

    if action is None or not speech.needs_voice(action):
        return None
    lungs = [(c, zone) for c in actor.conditions.values() if c.condition_id == POISONED
             for zone in [_from_talent(engine, c, "Black Lung")] if zone is not None]
    if not lungs:
        return None
    condition, zone = lungs[0]
    dc = int((zone.trigger_profile.get("numbers") or {}).get("save_dc") or 10)
    roll = engine._roll_save(actor, "CON", dc, zone.source_definition_id)
    if roll is not None and roll.total < dc:
        note(engine, zone.source_definition_id, actor, f"Black Lung: {actor.display_name} chokes on the miasma; {action.display_name} fails "
                                                       "(the action and any CP spent are lost).", (actor,))
        return True
    return None


# ------------------------------------------------------------------------------------------------ Snagging Darkness
def _snags(engine: Any, actor: Any) -> list[tuple[str, Any, Any]]:
    return [(key, c, zone) for key, c in actor.conditions.items() if c.condition_id == RESTRAINED
            for zone in [_from_talent(engine, c, "Snagging Darkness")] if zone is not None]


@hook("match_start")
def snag_actions(engine: Any) -> None:
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    engine.action_catalog[SNAG_ESCAPE] = ActionDefinition(
        source_definition_id=SNAG_ESCAPE, display_name="Tear free of the snagging darkness", owner_id="*", economy=EconomyKind.BONUS_ACTION,
        resolution_kind="TYPED", target_kind="SELF", parameters={
            "typed": {"effects": [{"type": "dark_snag_escape"}], "numbers": {}, "duration": {"kind": "instant"}, "riders": []},
            "expected_damage": 0, "dark_snag_escape": True,
            "description": "Restrained by Snagging Darkness: use your Bonus Action for a Strength (Athletics) or Dexterity (Acrobatics) check "
                           "against its creator's save DC; on a success the Restrained ends."})
    engine.action_catalog[WAKE] = ActionDefinition(
        source_definition_id=WAKE, display_name="Wake a sleeping ally (Creeping Lethargy)", owner_id="*", economy=EconomyKind.ACTION,
        resolution_kind="TYPED", target_kind="SELF", parameters={
            "typed": {"effects": [{"type": "dark_wake"}], "numbers": {}, "duration": {"kind": "instant"}, "riders": []},
            "expected_damage": 0, "dark_wake": True,
            "description": "Use your Action to shake awake an ally within 5 feet who fell asleep from Creeping Lethargy."})


def _sleepers(engine: Any, actor: Any) -> list[Any]:
    return [other for other in engine.state.actors.values() if other.entity_id != actor.entity_id and other.team_id == actor.team_id
            and any(c.condition_id == ASLEEP and (c.data or {}).get("sleep") == "creeping_lethargy" for c in other.conditions.values())
            and engine._distance_actor_to_actor(actor, other) <= 5]


@hook("additional_actions")
def dark_offers(engine: Any, actor: Any) -> list[str]:
    out = []
    if SNAG_ESCAPE in engine.action_catalog and _snags(engine, actor):
        out.append(SNAG_ESCAPE)
    if WAKE in engine.action_catalog and actor.active and _sleepers(engine, actor):
        out.append(WAKE)
    return out


@hook("candidate_allowed")
def dark_allowed(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    parameters = (getattr(action, "parameters", None) or {}) if action is not None else {}
    if parameters.get("dark_snag_escape"):
        return bool(_snags(engine, actor))
    if parameters.get("dark_wake"):
        return bool(_sleepers(engine, actor))
    return None


@effect("dark_snag_escape")
def snag_escape(ctx: Any, row: dict[str, Any]) -> None:
    from .ability_source import escape_bonus
    from .escape_checks import resolve_escape_check

    snags = _snags(ctx.engine, ctx.actor)
    if not snags:
        return
    key, condition, zone = snags[0]
    dc = int((zone.trigger_profile.get("numbers") or {}).get("save_dc") or 10)
    if resolve_escape_check(ctx, {"bonus": escape_bonus(ctx.engine, ctx.actor)}, dc, [condition], ("restrained",),
                            check_name="Tear free of the snagging darkness (Athletics or Acrobatics)"):
        ctx.actor.conditions.pop(key, None)
        ctx.engine._append_event("CONDITION_REMOVED", ctx.source, actor_id=ctx.actor.entity_id, target_ids=(ctx.actor.entity_id,),
                                 payload={"condition_id": RESTRAINED, "instance_id": key})


@effect("dark_wake")
def wake(ctx: Any, row: dict[str, Any]) -> None:
    from . import note

    sleepers = _sleepers(ctx.engine, ctx.actor)
    if not sleepers:
        return
    ally = min(sleepers, key=lambda other: (other.current_hp, other.entity_id))
    for key, condition in list(ally.conditions.items()):
        if condition.condition_id == ASLEEP and (condition.data or {}).get("sleep") == "creeping_lethargy":
            ally.conditions.pop(key, None)
            ctx.engine._append_event("CONDITION_REMOVED", ctx.source, actor_id=ctx.actor.entity_id, target_ids=(ally.entity_id,),
                                     payload={"condition_id": ASLEEP, "instance_id": key, "reason": "WOKEN"})
    note(ctx.engine, ctx.source, ctx.actor, f"{ctx.actor.display_name} shakes {ally.display_name} awake.", (ally,))


# ------------------------------------------------------------------------------------------------ Shadow Slick
@hook("escape_mode")
def slick_escape(engine: Any, escaper: Any, grips: Any) -> str | None:
    from .. import zones
    from ..ability_checks import ability_modifier

    if not any(getattr(g, "condition_id", "") == GRAPPLED for g in grips or ()):
        return None
    if ability_modifier(escaper, "DEX") < ability_modifier(escaper, "STR"):
        return None  # the Athletics escape is not a Dexterity check
    if any("Shadow Slick" in (zone.trigger_profile.get("talents") or []) and engine._footprint_intersects(escaper, zone.affected_cells)
           for zone in zones.typed_zones(engine)):
        return "ADVANTAGE"
    return None


# ------------------------------------------------------------------------------------------------ Tenebrous Legerdemain
TENEBROUS, DARKNESS = "TAL_DARK_TENEBROUS_LEGERDEMAIN", "DARK_BASE_DARKNESS"


def _legerdemain_zone(engine: Any, owner: Any, creature: Any) -> Any:
    from .. import zones

    return next((zone for zone in zones.typed_zones(engine) if zone.owner_id == owner.entity_id
                 and "Tenebrous Legerdemain" in (zone.trigger_profile.get("talents") or []) and engine._footprint_intersects(creature, zone.affected_cells)), None)


@hook("compile_actions")
def legerdemain_action(info: dict[str, Any]) -> list[Any] | None:
    """Tenebrous Legerdemain: "As a Bonus Action, attempt to steal one worn or held object from a creature inside the area. Make either a
    ranged Cultivation Attack or a Dexterity (Sleight of Hand) check ... Success: Pull the object away and move it to another space inside
    the same Darkness. You have Disadvantage if the object is firmly secured or held in two hands." Both printed roll methods
    use the same represented held-weapon result; other objects stay with the GM."""
    if TENEBROUS not in info["owned_ids"]:
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    from .ability_source import mechanic_of

    darkness = next((a for a in info["actions"] if mechanic_of(a) == DARKNESS), None)
    typed = ((darkness.parameters or {}).get("typed") or {}) if darkness is not None else {}
    return [ActionDefinition(
        source_definition_id=f"action:typed.{info['short']}.tenebrous_legerdemain", display_name="Tenebrous Legerdemain: pull a weapon away",
        owner_id=info["actor_id"], economy=EconomyKind.BONUS_ACTION, resolution_kind="TYPED", target_kind="HOSTILE_ENTITY", range_ft=120,
        parameters={"typed": {"effects": copy.deepcopy(info["mechanics"][TENEBROUS]["effects"]),
                              "numbers": dict(typed.get("numbers") or info["numbers"]), "duration": {"kind": "instant"}, "riders": [],
                              "source": TENEBROUS, "sphere": typed.get("sphere"), "range_ft": 120},
                    "expected_damage": 0, "dark_legerdemain": True,
                    "description": "Bonus Action, no CP cost: choose a ranged Cultivation Attack that must hit the creature's AC, or "
                                   "a Dexterity (Sleight of Hand) check that must beat its chosen Strength (Athletics) or Dexterity "
                                   "(Acrobatics) check. A hit or winning check moves its held weapon elsewhere inside your Darkness. "
                                   "A tied check leaves it held. Disadvantage against a two-handed weapon; other objects need the GM."})]


@hook("candidate_allowed")
def legerdemain_target(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if not ((getattr(action, "parameters", None) or {}) if action is not None else {}).get("dark_legerdemain"):
        return None
    targets = [engine.state.actors.get(t) for t in (getattr(candidate, "target_ids", None) or ())]
    return None if targets and all(t is not None and _legerdemain_zone(engine, actor, t) is not None for t in targets) else False


def _two_handed(engine: Any, target: Any) -> bool:
    from ..typed_executor import _best_weapon_action

    weapon = _best_weapon_action(engine, target)
    typed = ((engine.action_catalog[weapon].parameters or {}).get("typed") or {}) if weapon else {}
    return "two-handed" in str((typed.get("weapon") or {}).get("properties") or "").lower()


@hook("attack_mode")
def legerdemain_two_handed(ctx: Any, target: Any) -> str | None:
    if not (ctx.action.parameters or {}).get("dark_legerdemain"):
        return None
    return "DISADVANTAGE" if _two_handed(ctx.engine, target) else None


@hook("contest_check_mode")
def legerdemain_check_mode(ctx: Any, subject: Any, opponent: Any, spec: dict[str, Any]) -> str | None:
    if subject is ctx.actor and (ctx.action.parameters or {}).get("dark_legerdemain"):
        return "DISADVANTAGE" if _two_handed(ctx.engine, opponent) else None
    return None


@effect("dark_pull_weapon")
def pull_weapon(ctx: Any, row: dict[str, Any]) -> None:
    from ..typed_executor import CONDITION_PREFIX, _best_weapon_action
    from . import note

    target = ctx.target
    if target is None:
        return
    weapon = _best_weapon_action(ctx.engine, target)
    zone = _legerdemain_zone(ctx.engine, ctx.actor, target)
    if weapon is None or zone is None:
        note(ctx.engine, ctx.source, ctx.actor, f"Tenebrous Legerdemain: {target.display_name} holds no weapon to pull away (another object is the GM's).", (target,))
        return
    spot = max(zone.affected_cells, key=lambda cell: (ctx.engine.grid.distance_ft(cell, target.position), -cell.y, -cell.x))
    ctx.engine._apply_condition(target, CONDITION_PREFIX + "disarmed", ctx.source, ctx.actor.entity_id, expires_on="UNTIL_REMOVED",
                                data={"disables_action": weapon, "dropped_at": spot.model_dump(mode="json"),
                                      "label": f"Disarmed: its weapon lies at {spot.x},{spot.y} in the Darkness"})

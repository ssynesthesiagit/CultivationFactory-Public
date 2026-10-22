"""Shared Air queries for air_second_pass (ownership and projectile crossings). Air sphere riders: Air Currents, projectiles through them, the Guard reactions and collisions (rider lane C9, 2026-09-30).

Rules text (owner's Sphere Compendium, "Sphere of Air", authority/typed_mechanics/rules_text.json):

  Air Current        "An Air Current is a temporary controlled area of moving air created by an Air talent." -> every active area on
                     the map that an Air-sphere ability of that creature made (combat/zone_sources: the area's sphere).
                     Public: currents(engine, owner), in_current(engine, owner, creature).
  Air Check          "d20 + Proficiency Bonus + your Path key ability modifier".
  Projectiles        An Air area's typed zone row may carry "air_ranged": {"kind": "tiny" | "ranged_weapon" | "ranged",
                     "through": bool, "into": bool, "out": bool, "first": bool}. Before the d20 of an attack whose kind matches
                     and whose line crosses the area (into it, out of it, or through it, as the row says), the attack has
                     Disadvantage; "first" spends the rule on the first such attack while the area lasts.
                     kind "tiny": an ordinary Tiny projectile -- a weapon with the Ammunition property (arrows, bolts, needles,
                     pellets; a reading: thrown weapons are not counted as Tiny). "ranged_weapon": any ranged weapon attack
                     (Ammunition or Thrown). "ranged": any ranged attack.
                     Gather Current's Turn ("The first ordinary Tiny projectile that passes through the Current before it ends
                     has Disadvantage"), Wind Wall ("Ordinary Tiny projectiles that pass through the wall have Disadvantage"),
                     Cyclone Prison ("Ordinary ranged weapon attacks into, out of, or through the Cyclone have Disadvantage").
  Arrow-Turning Breath  Reaction, "A creature you can see within 30 feet is hit by an ordinary ranged weapon attack. Roll an Air
                     Check against the attack roll. Success: Reduce the attack's damage by 1d8 + your Proficiency Bonus. Success
                     by 5 or more: The attack misses instead. At Foundation Realm, you may use this against magical ammunition and
                     thrown weapons." -> hit_response: asked of its owner (a player chooses; an AI uses it), the Reaction is
                     spent, the check is rolled; the reduction is taken off that attack's damage (damage_pending). Below CL 5 it
                     answers Ammunition weapons only; from CL 5 thrown weapons too (the table cannot tell magical ammunition).
  Cloud-Sleeve Guard "While you have an active Air Current, you may use your Reaction when an attack roll is made against you ...
                     If this causes the attack to miss, you may move 5 feet without provoking Opportunity Attacks from the
                     attacker." -> row_allowed gates the generic row on an active Current; effect "cloud_sleeve_watch" remembers
                     the attack and attack_result offers the 5-foot step only when its penalty caused a miss.
  Court of the Four Winds  "Once per round when an ordinary ranged weapon attack passes through one of your Currents, you may
                     impose Disadvantage on that attack without using your Reaction." -> before_attack while the Court's state
                     (combat/ext/states.py) is on: asked of its owner (an AI uses it), once per round. The Court's own 60-foot
                     area is the domain the Currents sit in and is not itself one of them.
  Sky-Sovereign Incarnation  "You may use Arrow-Turning Breath without spending your Reaction once per round." -> while its state
                     is on, the first Arrow-Turning Breath of each round keeps the Reaction.
  Invisible Blade Current  "When you use Wind Lash from an active Air Current, you may choose to make the attack invisible until
                     it strikes. The target makes a Wisdom (Perception) check against your Cultivation Save DC before the attack
                     roll. Failure: The attack has Advantage. ... A creature with blindsight, tremorsense that can read air
                     pressure, Wind-Sense, or a comparable feature may have Advantage on this check." -> before_attack: a Wind
                     Lash made while its user stands in one of its own Air Currents (a reading of "from") is offered invisible
                     (asked of a player); the target rolls d20 + its Perception bonus (its Search bonus), with Advantage for
                     blindsight, for Tremorsense that can read air pressure, or for a live printed air-reading talent such as
                     Wind-Sense (reads_air, which asks the sense row rather than the sense's name, so ground-contact Tremorsense
                     gets nothing); a failure gives the attack Advantage.
  Storm Without Direction, No Steady Foot  "Hostile creatures that move more than half their Speed must succeed on a Dexterity
                     saving throw or fall Prone at the end of that movement." -> an Air area whose zone row says "air_steady_foot":
                     when a hostile creature's own movement this turn inside it passes half its Speed, it makes the Dexterity save
                     against the area's DC (once a turn); a failure knocks it Prone.
  Gale Push / Pressure Break  "If the target collides with a solid obstacle during this movement, it falls Prone" / "If it collides
                     with a solid obstacle or another creature, it falls Prone" -> effect "air_push" runs its nested push row and the
                     collision hook knocks the creature Prone when the push stops short ("obstacle" or "obstacle_or_creature").
  Sky Road  "Create a road of stable wind ... Other creatures treat the road as Difficult Terrain and must succeed on a Dexterity
                     saving throw the first time they enter it on a turn or fall through. ... Creatures you designate may stand,
                     walk, run, or fall Prone on the road as though it were solid ground." -> the road is a typed area (its shape,
                     Difficult Terrain and crossing save are the reviewed row's own); "Other" and "you designate" are its printed
                     qualifications, so technique_used asks the creator once which creatures the road is for and
                     zone_recipient_allowed leaves those creatures and the creator out of both penalties. Reviewed roads opt into native support surfaces; a failed crossing removes that support
                     for the visitor and native falling resolves the descent.

Hooks: compile_block (block "air"), status_description (the Press mark), compile_actions (choice-owner rows only), event (No Steady Foot), before_attack, hit_response, damage_pending, attack_roll_finished (exact-roll cleanup), row_allowed, attack_result, technique_used and zone_recipient_allowed (Sky Road's designations), collision.
Effects: air_push, cloud_sleeve_watch. Each returns early unless the creature owns the row or the area is its own.
"""

from __future__ import annotations

from ..paid_relocation import activation

from dataclasses import replace
from typing import Any

from . import effect, hook, note

AIR = "tianxia.sphere.air"
BLOCK = "air"
ARROW_TURNING = "TAL_AIR_ARROW_TURNING_BREATH"
CLOUD_SLEEVE = "TAL_AIR_CLOUD_SLEEVE_GUARD"
SLEEVE_PENDING = "cloud_sleeve_round_pending"
FIRST_USED = "air_first_projectile_"  # + zone id: the zone owner's turn flag (the area ends by then at the latest)
FOUNDATION_CL = 5
INVISIBLE_BLADE = "TAL_AIR_INVISIBLE_BLADE_CURRENT"
WIND_LASH = "AIR_BASE_WIND_LASH"
COURT = "TAL_AIR_COURT_OF_THE_FOUR_WINDS"
COURT_STATE = "court_of_the_four_winds"
SOVEREIGN_STATE = "sky_sovereign_incarnation"
COURT_USED = "air_court_round_used"
SOVEREIGN_FREE = "air_sovereign_round_free"
ARROW_PENDING = "condition:typed.air_arrow_pending"
SKY_ROAD = "TAL_AIR_SKY_ROAD"
CYCLONE = "TAL_AIR_CYCLONE_PRISON"
DOWNBURST = "TAL_AIR_DOWNBURST_SEAL"
DESIGNATED = "air_sky_road_designated"  # zone.trigger_profile key: the actor ids the road's creator designated


@effect("air_downburst_descent")
def downburst_descent(ctx: Any, row: dict[str, Any]) -> None:
    """The failed-save packet uses native descent and only knocks down a landed creature.

    Newly reviewed Downburst rows opt in; historical sealed condition packets
    retain their behavior. Hovering creatures resist the printed descent.
    """
    from ..falling import displace, supported
    from ..flight import profile
    from ..typed_executor import run_effects

    target = ctx.target
    if ctx.typed.get("source") != DOWNBURST or target is None:
        return
    if target.position.z and not profile(ctx.engine, target).hover:
        displace(ctx.engine, target, -min(target.position.z, 6), ctx.source,
                 intent=ctx.intent, settle_after=False)
    if supported(ctx.engine, target):
        run_effects(ctx, [{"type": "condition", "condition": "prone", "duration": "instant"}])


@effect("air_cyclone_lift")
def cyclone_lift(ctx: Any, row: dict[str, Any]) -> None:
    """Wind holds the failed-save recipient aloft while its restraint lasts.

    Restraint immunity/reactions, repeat saves and expiry stay native. The
    recorded suspension belongs to that exact condition, so ending the hold
    also releases the creature to the ordinary fall/flight rules.
    """
    from ..falling import displace
    from ..typed_executor import run_effects

    if ctx.typed.get("source") != CYCLONE or ctx.target is None:
        return
    run_effects(ctx, [{"type": "condition", "condition": "restrained",
                      "duration": "until_start_of_next_turn",
                      "condition_data": {"flight_suspended": 1},
                      "repeat_save": {"ability": "STR", "when": "end"}}])
    displace(ctx.engine, ctx.target, 2, ctx.source, intent=ctx.intent, settle_after=False)


@hook("attack_result")
def slashing_hit(ctx: Any, target: Any, hit: bool, critical: bool) -> None:
    """Snapshot this strike's dealt damage before any bonus can qualify itself.

    Only reviewed Air on-hit rows opting into air_slashing_rider use this
    resolution-local cache. Each strike replaces it, including misses and
    fully prevented damage; it is never part of saved fight state.
    """
    if not any(row.get("air_slashing_rider") for row in
               (getattr(ctx, "attack_effect", None) or {}).get("on_hit", [])):
        return
    dealt = False
    for event in reversed(ctx.engine.events):
        if (event.event_type == "ATTACK_ROLLED" and event.actor_id == ctx.actor.entity_id
                and event.source_definition_id == ctx.source and target.entity_id in event.target_ids
                and event.payload == ctx.attack_result):
            break
        if (hit and event.event_type == "DAMAGE_COMMITTED" and event.actor_id == ctx.actor.entity_id
                and event.source_definition_id == ctx.source and target.entity_id in event.target_ids
                and str(event.payload.get("damage_type") or "").upper() == "SLASHING"
                and int(event.payload.get("hp_damage") or 0)
                + int(event.payload.get("temporary_hp_absorbed") or 0) > 0):
            dealt = True
    else:
        dealt = False  # No matching strike boundary: never use earlier damage.
    ctx.damage_cache["_air_slashing_hit"] = {"target": target.entity_id, "dealt": dealt}


@hook("effect_allowed")
def slashing_rider_allowed(ctx: Any, row: dict[str, Any]) -> bool | None:
    """Cutting Wind and Vacuum Needle require actual slashing Wind Lash damage.

    The reviewed marker gates the whole save or bonus, not its extra damage
    alone. Legacy bundles without it keep their sealed effects. The CL-11
    Concentration rider also requires a currently held technique.
    """
    if not row.get("air_slashing_rider"):
        return None
    recorded = ctx.damage_cache.get("_air_slashing_hit") or {}
    if ctx.target is None or recorded.get("target") != ctx.target.entity_id or not recorded.get("dealt"):
        return False
    if row.get("air_requires_concentration"):
        from .. import concentration

        if ctx.target.concentration is None and not concentration.held(ctx.target):
            return False
    return None


@hook("compile_block")
def air_block(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    if block != BLOCK:
        return None
    return [{**row, "block": BLOCK, "kind": spec.get("kind"), "choice_owner": True,
             "pb": int(numbers.get("pb") or 2), "key_mod": int(numbers.get("key_mod") or 0), "cl": int(numbers.get("cl") or 1),
             "save_dc": int(numbers.get("save_dc") or 10)}]


@hook("compile_actions")
def air_choosers(info: dict[str, Any]) -> None:
    """Choices on other creatures' turns belong to the player controlling the Air cultivator (choice_owner): the Court's
    projectile turn and Cloud-Sleeve Guard's 5-foot step. Adds no action."""
    owned, passives = set(info.get("owned_ids") or ()), info.get("passives")
    if not isinstance(passives, list):
        return None
    for feature, kind, name in ((COURT, "court", "Court of the Four Winds"), (CLOUD_SLEEVE, "cloud_sleeve", "Cloud-Sleeve Guard")):
        if feature in owned and not any(row.get("feature_id") == feature and row.get("block") == BLOCK for row in passives):
            passives.append({"feature_id": feature, "block": BLOCK, "kind": kind, "name": name, "choice_owner": True})
    return None


def _rows(engine: Any, actor_id: str, kind: str) -> list[dict[str, Any]]:
    return [row for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor_id, [])
            if row.get("block") == BLOCK and row.get("kind") == kind]


def owned_air_rows(engine, actor_id, kind):
    """Public ownership query for Air feature kinds; consumed by air_second_pass. No mutation."""
    return _rows(engine, actor_id, kind)


@hook('placement_search_possible')
def current_search_possible(engine, actor, action, root, context):
    """Prove a missed Gather Current search cannot catch an observed hostile.

    This only avoids scoring an entirely empty cube under the existing AI
    empty-area filter. It never removes the ability, a picker cell or an aim.
    Chebyshev triangle inequality bounds every hostile volume by placement
    range plus half the cube's side.
    """
    typed = action.parameters.get('typed') or {}
    area = typed.get('area') or {}
    if (action.owner_id != actor.entity_id or typed.get('source') != 'AIR_BASE_GATHER_CURRENT'
            or action.resolution_kind != 'TYPED' or action.target_kind != 'CELL'
            or action.parameters.get('any_cell') or (typed.get('zone_spec') or {}).get('wall')
            or action.parameters.get('ai_allow_empty_area')
            or not action.parameters.get('ai_empty_area_filter', True)
            or area.get('shape') != 'cube' or type(area.get('size_ft')) is not int
            or area['size_ft'] <= 0):
        return None
    from ..cell_placement import profile
    if profile(engine, actor, action) is not None:
        return None
    from ..candidate_knowledge import roster
    from ..relations import relation, ENEMY
    from ..action_geometry import activate
    observed = roster(engine)
    if observed is None:
        return None  # No explicit observed-query scope means no proof.
    with activate(engine, actor, action.source_definition_id, root.metadata.get('effect_origin')):
        origin = engine._effect_volume(actor)
    reach = int(action.range_ft or 0) + (area['size_ft'] + 1) // 2
    if any(other.active and relation(engine, actor, other) == ENEMY
           and engine.grid.distance_between_cell_sets_ft(origin, engine._actor_volume(other)) <= reach
           for other in observed):
        return None
    return False


def projectile_crosses_current(engine, zone, attacker, target, rule):
    """Public exact projectile/current crossing for air_second_pass; sealed geometry."""
    return _crosses(engine, zone, attacker, target, rule)


@hook("status_description")
def press_description(engine: Any, holder: Any, row: dict[str, Any], data: dict[str, Any]) -> dict[str, str] | None:
    if not str(row.get("condition_id") or "").startswith("condition:typed.mark.air_press."):
        return None
    return {"text": "Gather Current (Press): the wind pushes against this creature -- the squares of that Air Current are difficult "
                    "terrain for it (each 5 feet there costs 10 feet of movement) until the start of the Current's creator's next turn.",
            "handling": "The table applies the difficult terrain to this creature only."}


# ------------------------------------------------------------------------------------------------ Air Currents
def _sphere_of(zone: Any) -> str:
    from .. import zone_sources

    profile = zone_sources.of(zone) or {}
    return str(profile.get("sphere_id") or "")


def _mechanic_of(zone: Any) -> str:
    from .. import zone_sources

    return str((zone_sources.of(zone) or {}).get("mechanic_id") or "")


def currents(engine: Any, owner: Any) -> list[Any]:
    """The owner's active Air Currents: areas on the map an Air-sphere ability of the owner made (the Court of the Four Winds'
    own domain area holds Currents and is not one)."""
    from .. import zones

    return [zone for zone in zones.typed_zones(engine) if zone.active and zone.owner_id == owner.entity_id and _sphere_of(zone) == AIR
            and _mechanic_of(zone) != COURT]


def in_current(engine: Any, owner: Any, creature: Any) -> bool:
    from ..spatial_areas import zone_contains

    return any(zone_contains(engine, creature, zone) if zone.trigger_profile.get("height_ft") is not None
               else engine._footprint_intersects(creature, zone.affected_cells)
               for zone in currents(engine, owner))


# ------------------------------------------------------------------------------------------------ projectiles through an area
def _zone_rule(engine: Any, zone: Any) -> dict[str, Any] | None:
    action = getattr(engine, "action_catalog", {}).get(zone.source_definition_id)
    typed = ((getattr(action, "parameters", None) or {}).get("typed") or {}) if action is not None else {}
    return next((dict(row["air_ranged"]) for row in typed.get("effects") or ()
                 if isinstance(row, dict) and row.get("type") == "zone" and row.get("air_ranged")), None)


def attack_kind(engine: Any, attacker: Any, context: dict[str, Any]) -> str | None:
    """"tiny" (Ammunition weapon), "thrown" (a Thrown weapon at range), "ranged" (another ranged attack) or None (melee)."""
    source = str((context or {}).get("source_id") or "")
    action = getattr(engine, "action_catalog", {}).get(source)
    typed = ((getattr(action, "parameters", None) or {}).get("typed") or {}) if action is not None else {}
    reach = int((context or {}).get("range_ft") or getattr(action, "range_ft", 0) or 0)
    if reach <= 5:
        return None
    properties = str((typed.get("weapon") or {}).get("properties") or "").lower()
    kind = str(((context or {}).get("effect") or {}).get("attack_kind") or "")
    if "ammunition" in properties:
        return "tiny"
    if "thrown" in properties and kind in ("weapon", ""):
        return "thrown"
    return "ranged"


def _crosses(engine: Any, zone: Any, attacker: Any, target: Any, rule: dict[str, Any]) -> bool:
    if zone.trigger_profile.get("height_ft") is not None:
        from ..gate2_runtime_models import Position
        from ..spatial_areas import zone_contains
        from ..typed_executor import in_area

        # Explicit height belongs to the sealed volume, not its painted ground
        # cells. Legacy zones keep the previous two-dimensional branch below.
        if rule.get("into") and zone_contains(engine, target, zone):
            return True
        if rule.get("out") and zone_contains(engine, attacker, zone):
            return True
        return bool(rule.get("through", True) and any(
            in_area(engine, zone.center, zone.center, Position(x=x, y=y, z=z), zone.trigger_profile)
            for x, y, z in engine.grid.effect_ray_cells(attacker.position, target.position)[1:]))
    cells = {(cell.x, cell.y) for cell in zone.affected_cells}
    ray = list(engine.grid.ray_cells(attacker.position, target.position))
    if rule.get("into") and engine._footprint_intersects(target, zone.affected_cells):
        return True
    if rule.get("out") and engine._footprint_intersects(attacker, zone.affected_cells):
        return True
    through = {(cell[0], cell[1]) if isinstance(cell, tuple) else (cell.x, cell.y) for cell in ray[1:]}
    return bool(rule.get("through", True) and through & cells)


def _matches(kind: str | None, wanted: str) -> bool:
    return kind is not None and (wanted == "ranged" or (wanted == "ranged_weapon" and kind in ("tiny", "thrown")) or (wanted == "tiny" and kind == "tiny"))


@hook("before_attack")
def projectiles_through_air(engine: Any, attacker: Any, defender: Any, intent: Any, context: dict[str, Any]) -> dict[str, Any] | None:
    from .. import zones

    kind = None
    for zone in zones.typed_zones(engine):
        if not zone.active or _sphere_of(zone) != AIR:
            continue
        rule = _zone_rule(engine, zone)
        if not rule:
            continue
        kind = kind if kind is not None else attack_kind(engine, attacker, context) or ""
        if not _matches(kind or None, str(rule.get("kind") or "ranged")) or not _crosses(engine, zone, attacker, defender, rule):
            continue
        owner = engine.state.actors.get(zone.owner_id)
        if rule.get("first"):
            if owner is None or owner.turn_flags.get(FIRST_USED + zone.zone_id):
                continue
            owner.turn_flags[FIRST_USED + zone.zone_id] = True
        name = str(zone.trigger_profile.get("name") or "Air Current")
        note(engine, zone.source_definition_id, owner or attacker,
             f"{name}: the wind turns {attacker.display_name}'s projectile -- Disadvantage on the attack against {defender.display_name}.",
             (attacker.entity_id, defender.entity_id))
        return {"mode": "DISADVANTAGE"}
    return _court_turns(engine, attacker, defender, intent, context, kind)


def _court_turns(engine: Any, attacker: Any, defender: Any, intent: Any, context: dict[str, Any], kind: str | None) -> dict[str, Any] | None:
    """Court of the Four Winds: once per round, an ordinary ranged weapon attack through one of the owner's Currents."""
    from . import states

    for owner in sorted(engine.state.actors.values(), key=lambda actor: actor.entity_id):
        if not owner.active or owner.team_id == attacker.team_id or not states.active(engine, owner, COURT_STATE):
            continue
        if owner.turn_flags.get(COURT_USED) == str(engine.state.round_number):
            continue
        kind = kind if kind is not None else attack_kind(engine, attacker, context) or ""
        if kind not in ("tiny", "thrown"):
            return None
        rule = {"through": True, "into": True, "out": True}
        crossed = [zone for zone in currents(engine, owner) if _crosses(engine, zone, attacker, defender, rule)]
        if not crossed:
            continue
        from .rider_choices import pick

        chosen = pick(engine, owner, "air_court_turn", "Court of the Four Winds", ["use"], subject=defender, intent=intent,
                      labels={"use": f"Give {attacker.display_name}'s ranged weapon attack Disadvantage (once per round, no Reaction)"},
                      trigger=f"{attacker.display_name}'s projectile passes through your Current")
        if not chosen:
            continue
        owner.turn_flags[COURT_USED] = str(engine.state.round_number)  # a "_round_"-free key: its owner's turn start clears it
        note(engine, COURT, owner, f"Court of the Four Winds: the winds turn {attacker.display_name}'s projectile -- Disadvantage.",
             (attacker.entity_id, defender.entity_id))
        return {"mode": "DISADVANTAGE"}
    return None


# ------------------------------------------------------------------------------------------------ No Steady Foot
STEADY_USED = "air_steady_foot_checked"


def _steady_zones(engine: Any, mover: Any, path: list[dict[str, int]]) -> list[Any]:
    from .. import zones
    from ..gate2_runtime_models import Position

    out = []
    for zone in zones.typed_zones(engine):
        if not zone.active or _sphere_of(zone) != AIR or not any(
                engine._footprint_intersects(mover.model_copy(update={"position": Position(**cell)}), zone.affected_cells)
                for cell in path):
            continue
        action = getattr(engine, "action_catalog", {}).get(zone.source_definition_id)
        typed = ((getattr(action, "parameters", None) or {}).get("typed") or {}) if action is not None else {}
        owner = engine.state.actors.get(zone.owner_id)
        if owner is not None and owner.team_id != mover.team_id and any(
                isinstance(row, dict) and row.get("type") == "zone" and row.get("air_steady_foot") for row in typed.get("effects") or ()):
            out.append(zone)
    return out


@hook("event")
def no_steady_foot(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type != "MOVEMENT_COMMITTED":
        return
    payload = kwargs.get("payload") or {}
    mover = engine.state.actors.get(kwargs.get("actor_id") or "")
    if mover is None or not mover.active or payload.get("forced") or payload.get("teleport") or mover.turn_flags.get(STEADY_USED):
        return
    if engine.state.current_actor_id != mover.entity_id:
        return  # its own movement, on its turn
    zones_here = _steady_zones(engine, mover, payload.get("path") or [])
    if not zones_here:
        return
    starts = [event.sequence for event in engine.events if event.event_type == "TURN_STARTED" and event.actor_id == mover.entity_id]
    since = starts[-1] if starts else 0
    moved = sum(max(0, len((event.payload or {}).get("path") or []) - 1) * engine.grid.square_size_ft for event in engine.events
                if event.sequence >= since and event.event_type == "MOVEMENT_COMMITTED" and event.actor_id == mover.entity_id
                and not (event.payload or {}).get("forced") and not (event.payload or {}).get("teleport"))
    if moved * 2 <= int(engine._effective_speed(mover) or 0):
        return
    mover.turn_flags[STEADY_USED] = True
    zone = zones_here[0]
    owner = engine.state.actors.get(zone.owner_id)
    action = engine.action_catalog.get(zone.source_definition_id)
    from .. import typed_executor

    typed = {"effects": [], "numbers": dict(((action.parameters or {}).get("typed") or {}).get("numbers") or {}), "weapon": None,
             "duration": {"kind": "instant"}, "riders": [], "source": zone.source_definition_id}
    note(engine, zone.source_definition_id, owner, f"No Steady Foot: {mover.display_name} rushes through the storm and must keep its feet.",
         (mover.entity_id,))
    # Lock6 supplies the native active intent through movement/turn callbacks.
    ctx = typed_executor.Context(engine, owner, action, getattr(engine, "_active_intent", None), typed,
                                 [mover], mover, {})
    typed_executor.run_effects(ctx, [{"type": "save", "ability": "dex", "applies_to": "target",
                                      "on_fail": [{"type": "condition", "condition": "prone", "applies_to": "target", "duration": "instant",
                                                   "evidence": "falls Prone at the end of that movement"}], "on_success": [],
                                      "evidence": "Hostile creatures that move more than half their Speed must succeed on a Dexterity saving throw or fall Prone at the end of that movement."}])


# ------------------------------------------------------------------------------------------------ Invisible Blade Current
#: Senses that notice a moving current or an incoming cut on their own, with no further qualification. Blindsight
#: reads the world without sight, so it reads the cut; tremorsense does not qualify by itself, because the printed
#: wording is "tremorsense *that can read air pressure*" -- an ordinary ground-contact Tremorsense cannot.
AIR_READING_SENSES = ("blindsight",)
#: The printed talents whose own text lists reading air as something they do. A row qualifies on this list only
#: while its own printed sense or ability is actually live, so a talent that is inactive does not.
AIR_READING_FEATURES = ("TAL_AIR_WIND_SENSE",)
#: Marker a sense row may carry to declare that this particular Tremorsense reads air pressure rather than only
#: vibrations through solid ground (combat/rules/senses.json rows, or a "sense" condition's data). A row without it
#: is ground Tremorsense and gets nothing.
AIR_SENSE_MARKER = "reads_air_pressure"


def _air_sense_rows(engine: Any, creature: Any) -> list[dict[str, Any]]:
    """This creature's live sense rows, including any granted by a sense condition."""
    bundle = next((row for row in getattr(engine, "typed_bundle_documents", ()) or ()
                   if row.get("actor_id") == creature.entity_id), {})
    rows = list((bundle.get("senses") or {}).get("rows") or [])
    from .. import senses as _senses

    for condition in creature.conditions.values():
        if condition.condition_id == _senses.SENSE:
            data = condition.data or {}
            if data.get("concentration") and not _senses.concentrating_on(creature, data.get("source")):
                continue
            rows.append({"sense": data.get("sense"), "range_ft": int(data.get("range_ft") or 0),
                         "when": "active", **({AIR_SENSE_MARKER: True} if data.get(AIR_SENSE_MARKER) else {})})
    return rows


def reads_air(engine: Any, creature: Any, sensed: dict[str, Any] | None = None) -> bool:
    """Whether this creature's own senses or printed talents notice moving air.

    A general reading of "blindsight, tremorsense that can read air pressure, Wind-Sense, or a comparable feature":
    a sense qualifies when the creature really has it, an ordinary sense whose row declares it reads air pressure
    (``AIR_SENSE_MARKER``), or a printed air-reading talent that is currently live. An earlier version granted the
    Advantage for *any* Tremorsense at all, which handed the benefit to creatures whose printed sense reads ground
    vibrations only and cannot see a cut in the air -- so it now asks the row, not the sense's name.
    """
    from .. import senses as _senses

    sensed = _senses.of(engine, creature) if sensed is None else sensed
    rows = _air_sense_rows(engine, creature)
    if any(sense in sensed for sense in AIR_READING_SENSES):
        return True
    if any(str(row.get("sense") or "") == "tremorsense" and row.get(AIR_SENSE_MARKER)
           for row in rows if (row.get("when") or "always") in ("always", "active", "martial_focus", "meld")):
        return True
    live = {str(row.get("feature_id") or "") for row in rows}
    live.update(str(row.get("feature_id") or "")
                for row in getattr(engine, "typed_passive_rows", {}).get(creature.entity_id, []))
    return any(feature in live for feature in AIR_READING_FEATURES)


def _perception_bonus(engine: Any, creature: Any) -> int:
    for action in getattr(engine, "action_catalog", {}).values():
        if action.owner_id != creature.entity_id:
            continue
        for row in ((action.parameters or {}).get("typed") or {}).get("effects") or ():
            if isinstance(row, dict) and row.get("type") == "search":
                return int(row.get("bonus") or 0)
    return 0


@hook("before_attack")
def invisible_blade(engine: Any, attacker: Any, defender: Any, intent: Any, context: dict[str, Any]) -> dict[str, Any] | None:
    rows = _rows(engine, attacker.entity_id, "invisible_blade")
    if not rows:
        return None
    action = getattr(engine, "action_catalog", {}).get(str((context or {}).get("source_id") or ""))
    typed = ((getattr(action, "parameters", None) or {}).get("typed") or {}) if action is not None else {}
    if WIND_LASH not in (typed.get("source"), typed.get("option_of")) or not in_current(engine, attacker, attacker):
        return None
    from .rider_choices import pick
    from .roll_context import described_check
    from .. import senses

    chosen = pick(engine, attacker, "invisible_blade", "Invisible Blade Current", ["use"], subject=defender, intent=intent,
                  labels={"use": f"Make the Wind Lash invisible: {defender.display_name} rolls Perception against your save DC "
                                 f"({rows[0].get('save_dc')}); on a failure the attack has Advantage"},
                  trigger=f"Wind Lash from your Air Current at {defender.display_name}")
    if not chosen:
        return None
    sensed = senses.of(engine, defender)
    mode = "ADVANTAGE" if reads_air(engine, defender, sensed) else "NORMAL"
    dc = int(rows[0].get("save_dc") or 10)
    roll = described_check(engine, description=f"Wisdom (Perception) check to notice {attacker.display_name}'s invisible Wind Lash (DC {dc})",
                         modifier=_perception_bonus(engine, defender), actor_id=defender.entity_id, reason=f"CHECK:{INVISIBLE_BLADE}:perception",
                         modes=(mode,), ability="WIS", skill="Perception", against_creature=attacker)
    engine._record_roll(roll)
    noticed = roll.total >= dc
    engine._append_event("CHECK_ROLLED", INVISIBLE_BLADE, actor_id=defender.entity_id, target_ids=(defender.entity_id,),
                         payload={"actor": roll.model_dump(mode="json"), "dc": dc, "success": noticed, "skill": "Perception"})
    note(engine, INVISIBLE_BLADE, attacker, f"Invisible Blade Current: {defender.display_name} "
                                            f"{'spots the invisible cut' if noticed else 'does not see it coming -- Advantage'} ({roll.total} against {dc}).",
         (defender.entity_id,))
    return None if noticed else {"mode": "ADVANTAGE"}


# ------------------------------------------------------------------------------------------------ Arrow-Turning Breath
def _air_check(engine: Any, actor: Any, row: dict[str, Any], against: int, what: str) -> Any:
    from .roll_context import described_check

    roll = described_check(engine, description=f"Air Check for Arrow-Turning Breath against the attack roll ({against}) on {what}",
                         modifier=int(row.get("pb") or 2) + int(row.get("key_mod") or 0), actor_id=actor.entity_id,
                         reason=f"CHECK:{ARROW_TURNING}:air")
    engine._record_roll(roll)
    engine._append_event("CHECK_ROLLED", ARROW_TURNING, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                         payload={"actor": roll.model_dump(mode="json"), "dc": against, "success": roll.total >= against, "skill": "Air Check"})
    return roll


@hook("hit_response")
def arrow_turning(engine: Any, attacker: Any, target: Any, spec: dict[str, Any], total: int, natural: int, effective_ac: int) -> Any:
    from .attack_scope import current

    scope = current(engine) or {}  # the typed attack being resolved (its source action; the spec carries none)
    if not scope.get("roll_id"):
        return None  # Only a scoped roll can own and retire a pending reduction.
    context = {"source_id": spec.get("source_definition_id") or scope.get("source"), "range_ft": spec.get("range_ft"),
               "effect": scope.get("effect") or (spec.get("checkpoint_context") or {}).get("effect")}
    kind = None
    for guard in sorted(engine.state.actors.values(), key=lambda actor: actor.entity_id):
        rows = _rows(engine, guard.entity_id, "arrow_turning")
        if not rows or not guard.active or guard.team_id != target.team_id:
            continue
        from . import states

        free = states.active(engine, guard, SOVEREIGN_STATE) and guard.turn_flags.get(SOVEREIGN_FREE) != str(engine.state.round_number)
        from .reaction_eligibility import eligible

        if not eligible(engine, guard, target, attacker=attacker, free=free):
            continue
        kind = kind if kind is not None else attack_kind(engine, attacker, context) or ""
        cl = int(rows[0].get("cl") or 1)
        if kind != "tiny" and not (kind == "thrown" and cl >= FOUNDATION_CL):
            continue  # an ordinary ranged weapon attack; thrown weapons from Foundation Realm
        if engine._distance_actor_to_actor(guard, target) > 30:
            continue
        from .rider_choices import pick

        cost = "No Reaction (Sky-Sovereign's once-per-round free use)" if free else "Use your Reaction"
        chosen = pick(engine, guard, "arrow_turning", "Arrow-Turning Breath", ["use"], subject=target,
                      labels={"use": f"{cost}; no Qi cost: roll d20 + {int(rows[0].get('pb') or 2) + int(rows[0].get('key_mod') or 0)} "
                                     f"against the attack roll ({total}) -- match it to reduce this attack's damage to {target.display_name} by "
                                     f"1d8 + {rows[0].get('pb')}, exceed it by 5 to make it miss"},
                      trigger=f"{attacker.display_name}'s ranged weapon attack hits {target.display_name}")
        if not chosen:
            continue
        from . import states

        with activation(engine, guard, ARROW_TURNING):
            if states.active(engine, guard, SOVEREIGN_STATE) and guard.turn_flags.get(SOVEREIGN_FREE) != str(engine.state.round_number):
                guard.turn_flags[SOVEREIGN_FREE] = str(engine.state.round_number)  # Sky-Sovereign: once per round without the Reaction
            else:
                guard.reaction_available = False
            engine._append_event("REACTION_WINDOW_OPENED", ARROW_TURNING, actor_id=guard.entity_id, target_ids=(attacker.entity_id, target.entity_id),
                                 payload={"checkpoint": "ATTACK_HIT_BEFORE_DAMAGE", "protects": target.entity_id})
            roll = _air_check(engine, guard, rows[0], total, f"{target.display_name}")
            if roll.total >= total + 5:
                note(engine, ARROW_TURNING, guard, f"Arrow-Turning Breath: {guard.display_name}'s current turns the projectile -- the attack on "
                                                   f"{target.display_name} misses ({roll.total} against {total}).", (attacker.entity_id, target.entity_id))
                engine._append_event("REACTION_RESOLVED", ARROW_TURNING, actor_id=guard.entity_id, target_ids=(attacker.entity_id,),
                                     payload={"checkpoint": "ATTACK_HIT_BEFORE_DAMAGE", "protects": target.entity_id, "hit_after_recheck": False})
                from ..attack_outcomes import unconditional_miss

                return unconditional_miss()
            if roll.total >= total:
                from ..gate2_runtime_models import DiceSpec

                dice = engine.roller.roll(DiceSpec(count=1, sides=8, modifier=int(rows[0].get("pb") or 2)), actor_id=guard.entity_id,
                                          reason=f"REDUCTION:{ARROW_TURNING}")
                engine._record_roll(dice)
                engine._apply_condition(target, ARROW_PENDING, ARROW_TURNING, guard.entity_id, expires_on="CONSUMED",
                                        data={"amount": int(dice.total), "attack_roll_id": str(scope["roll_id"]),
                                              "attack_source": str(scope["source"]), "attacker": attacker.entity_id,
                                              "label": f"Arrow-Turning Breath: this projectile deals {dice.total} less damage"})
                note(engine, ARROW_TURNING, guard, f"Arrow-Turning Breath: the current slows the projectile -- {dice.total} less damage to "
                                                   f"{target.display_name} ({roll.total} against {total}).", (attacker.entity_id, target.entity_id))
            else:
                note(engine, ARROW_TURNING, guard, f"Arrow-Turning Breath: the projectile keeps its line ({roll.total} against {total}).",
                     (attacker.entity_id, target.entity_id))
            engine._append_event("REACTION_RESOLVED", ARROW_TURNING, actor_id=guard.entity_id, target_ids=(attacker.entity_id,),
                                 payload={"checkpoint": "ATTACK_HIT_BEFORE_DAMAGE", "protects": target.entity_id})
            return None
    return None


@hook("damage_pending")
def arrow_turning_reduction(engine: Any, target: Any, pending: int, source_definition_id: str, source_actor_id: str) -> int | None:
    from .attack_scope import current
    from .condition_ownership import remove_instance

    scope = current(engine)
    if not scope:
        return None
    held = [c for c in target.conditions.values() if c.condition_id == ARROW_PENDING
            and c.data.get("attack_roll_id") == scope["roll_id"]
            and c.data.get("attack_source") == source_definition_id
            and c.data.get("attacker") == source_actor_id]
    amount = sum(int(c.data.get("amount") or 0) for c in held)
    for c in held:
        remove_instance(engine, target, c.instance_id, ARROW_TURNING)
    return max(0, int(pending) - int(amount)) if amount else None


@hook("attack_roll_finished")
def arrow_turning_finished(ctx: Any, target: Any, effect: dict[str, Any], roll_id: str) -> None:
    """A miss, abort or exception cannot leave this roll's benefit for a later attack."""
    from .condition_ownership import remove_instance

    for c in list(target.conditions.values()):
        if c.condition_id == ARROW_PENDING and c.data.get("attack_roll_id") == roll_id:
            remove_instance(ctx.engine, target, c.instance_id, ARROW_TURNING)


# ------------------------------------------------------------------------------------------------ Cloud-Sleeve Guard
@hook("row_allowed")
def cloud_sleeve_needs_a_current(engine: Any, actor: Any, row: dict[str, Any]) -> bool | None:
    if row.get("feature_id") != CLOUD_SLEEVE:
        return None
    return bool(currents(engine, actor))


@effect("cloud_sleeve_watch")
def cloud_sleeve_watch(ctx: Any, row: dict[str, Any]) -> None:
    if ctx.target is not None:
        ctx.actor.turn_flags[SLEEVE_PENDING] = f"{ctx.target.entity_id}|{ctx.engine.state.event_sequence}"


@hook("attack_result")
def cloud_sleeve_step(ctx: Any, target: Any, hit: bool, critical: bool) -> None:
    value = str(target.turn_flags.get(SLEEVE_PENDING) or "")
    if not value:
        return
    attacker_id, _, sequence = value.partition("|")
    if attacker_id != ctx.actor.entity_id:
        return
    target.turn_flags.pop(SLEEVE_PENDING, None)
    if hit or not target.active:
        return
    result = ctx.attack_result or {}
    penalty = next((int(e.payload.get("attack_penalty") or 0) for e in ctx.engine.events
                    if e.sequence > int(sequence) and e.event_type == "REACTION_RESOLVED"
                    and e.source_definition_id == CLOUD_SLEEVE and e.actor_id == target.entity_id
                    and ctx.actor.entity_id in e.target_ids), 0)
    total = int(result.get("modified_total", result.get("total", 0)))
    ac = int(result.get("target_ac") or 0)
    if result.get("natural_result") in (1, 20) or not (total < ac <= total + penalty):
        return
    from .rider_choices import step

    if step(ctx.engine, target, "cloud_sleeve_step", "Cloud-Sleeve Guard", ctx.actor, 5, CLOUD_SLEEVE, ctx.intent,
            trigger=f"your guard makes {ctx.actor.display_name}'s attack miss {target.display_name}; move up to 5 feet now "
                    f"without provoking an Opportunity Attack from {ctx.actor.display_name}, with no additional Reaction or Qi cost"):
        note(ctx.engine, CLOUD_SLEEVE, target, f"Cloud-Sleeve Guard: {target.display_name} moves 5 feet after making {ctx.actor.display_name}'s attack miss.",
             (ctx.actor.entity_id,))


# ------------------------------------------------------------------------------------------------ collisions
@effect("air_push")
def air_push(ctx: Any, row: dict[str, Any]) -> None:
    from ..typed_executor import block_forced_movement

    previous = ctx.damage_cache.get("_air_collision_prone")
    ctx.damage_cache["_air_collision_prone"] = str(row.get("prone_on_collision") or "")
    try:
        for push in row.get("effects") or ():  # nested under "effects": saves still read it as forced movement (_walk_rows)
            if isinstance(push, dict) and push.get("type") == "forced_movement":
                block_forced_movement(ctx, dict(push))
    finally:
        ctx.damage_cache["_air_collision_prone"] = previous


# ------------------------------------------------------------------------------------------------ Sky Road
# "Create a road of stable wind ... Other creatures treat the road as Difficult Terrain and must succeed on a
# Dexterity saving throw the first time they enter it on a turn or fall through. ... Creatures you designate
# may stand, walk, run, or fall Prone on the road as though it were solid ground." The road itself is a typed
# area (combat/rules/feature_blocks.d is not needed; the reviewed row types its shape, its Difficult Terrain and
# its crossing save). "Other" and "you designate" are the printed qualifications of those two penalties, so the
# creator is asked once, when the road is laid, which creatures it designates, and this area is left off the
# penalties for exactly those creatures and for the creator. Standing on the road is still the GM's, so it
# stays a rider on the reviewed row.
def _road_now(ctx: Any) -> Any:
    """The road this activation just laid (the zone of this source this activation's own creation made)."""
    from .. import zones

    mine = {zone.zone_id: zone for zone in zones.typed_zones(ctx.engine)
            if zone.active and zone.owner_id == ctx.actor.entity_id and zone.source_definition_id == ctx.source
            and _mechanic_of(zone) == SKY_ROAD}
    if not mine:
        return None
    created = next((event for event in reversed(ctx.engine.events)
                    if event.event_type == "ZONE_CREATED" and event.source_definition_id == ctx.source
                    and event.actor_id == ctx.actor.entity_id
                    and (ctx.intent is None or event.trigger_or_intent_id == getattr(ctx.intent, "intent_id", None))
                    and ((event.payload or {}).get("zone") or {}).get("zone_id") in mine), None)
    return mine.get(((created.payload or {}).get("zone") or {}).get("zone_id")) if created is not None else None


def _designated(zone: Any) -> tuple[str, ...]:
    """The creatures the road's creator designated, as recorded on the area (actor ids, so they survive a save)."""
    return tuple(str(value) for value in (getattr(zone, "trigger_profile", None) or {}).get(DESIGNATED) or ())


def _road_spares(engine: Any, zone: Any, actor: Any) -> bool:
    """The printed "Other creatures": the road's own creator, and the creatures it designated."""
    return (_mechanic_of(zone) == SKY_ROAD
            and (actor.entity_id == zone.owner_id or actor.entity_id in _designated(zone)))


@hook("technique_used")
def sky_road_designate(ctx: Any) -> None:
    """"Creatures you designate may stand, walk, run, or fall Prone on the road": ask who they are, once, here."""
    from .needle import CHOICE, ask, checkpoint_id

    zone = _road_now(ctx)
    if zone is None:
        return
    options = [creature.entity_id for creature in ctx.engine.state.actors.values()
               if creature.active and creature.entity_id != ctx.actor.entity_id]
    from .needle import ai_controlled
    from .equipment_armor import can_see
    if ai_controlled(ctx.engine, ctx.actor):
        options = [key for key in options if ctx.engine.state.actors[key].team_id == ctx.actor.team_id
                   and can_see(ctx.engine, ctx.actor, ctx.engine.state.actors[key])]
    chosen = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, SKY_ROAD, ctx.actor.entity_id), ctx.actor,
                 CHOICE + "sky_road_designated", options,
                 labels={key: ctx.engine.state.actors[key].display_name for key in options},
                 prompt="Choose the creatures this road is for. They may stand and walk on it as though it were "
                        "solid ground, and the road will not slow them down or ask them to save.",
                 preferred=[key for key in options if ctx.engine.state.actors[key].team_id == ctx.actor.team_id],
                 maximum=max(1, len(options)), allow_decline=True,
                 name="Sky Road", feature_id=SKY_ROAD)
    zone.trigger_profile = {**(zone.trigger_profile or {}), DESIGNATED: tuple(chosen)}
    # Re-record the area (ZONE_CREATED, as combat/zones.py and combat/ext/disease.py do), so a committed,
    # reloaded or replayed fight rebuilds the road with the same designations it was cast with.
    ctx.engine._append_event("ZONE_CREATED", zone.source_definition_id, actor_id=zone.owner_id,
                             payload={"zone": zone.model_dump(mode="json")})
    named = ", ".join(ctx.engine.state.actors[key].display_name for key in chosen)
    note(ctx.engine, SKY_ROAD, ctx.actor,
         "Sky Road: " + (f"these creatures may stand and walk on it as though it were solid ground, and it will "
                         f"neither slow them down nor ask them to save: {named}." if named else
                         "you designated no creatures, so every other creature is slowed by the road and asked "
                         "to save when it steps onto the road."))


@hook("zone_recipient_allowed")
def sky_road_exempt(engine: Any, zone: Any, actor: Any, spec: dict[str, Any]) -> bool | None:
    """"Other creatures treat the road as Difficult Terrain and must succeed on a Dexterity saving throw."

    Both of those penalties are this area's own rules (its ``difficult`` mapping and its crossing trigger), so
    one pure answer leaves the creator and the designated creatures out of both of them. Any other area, and
    every other creature, keeps the printed rule.
    """
    return False if _road_spares(engine, zone, actor) else None


@hook("collision")
def air_collision(ctx: Any, target: Any, blocked_at: Any, remaining_ft: int) -> None:
    rule = str((getattr(ctx, "damage_cache", None) or {}).get("_air_collision_prone") or "")
    if not rule or not target.active:
        return
    from .rider_support import occupant

    creature = occupant(ctx.engine, blocked_at)
    if creature is not None and rule != "obstacle_or_creature":
        return  # Gale Push: a solid obstacle, not a creature
    from ..typed_executor import run_effects

    run_effects(replace(ctx, target=target, targets=[target]),
                [{"type": "condition", "condition": "prone", "applies_to": "target", "duration": "instant",
                  "evidence": "it collides with a solid obstacle" + (" or another creature" if creature is not None else "") + " and falls Prone"}])
    note(ctx.engine, ctx.source, ctx.actor, f"{target.display_name} slams into {'another creature' if creature is not None else 'an obstacle'} "
                                            f"and falls Prone.", (target.entity_id,))


@hook('support_surface')
def sky_road_support(engine, actor, position):
    """A reviewed road is solid on its painted plane, until a crossing fails."""
    from .. import zones
    for zone in zones.typed_zones(engine):
        if not zone.active or _mechanic_of(zone) != SKY_ROAD:
            continue
        action = engine.action_catalog.get(zone.source_definition_id)
        typed = (action.parameters.get('typed') or {}) if action else {}
        if not any(row.get('air_road_support') for row in typed.get('effects', ())):
            continue
        if any(c.condition_id == 'condition:typed.sky_road_fallen'
               and c.data.get('zone_id') == zone.zone_id for c in actor.conditions.values()):
            continue
        cells = {(c.x, c.y, c.z) for c in zone.affected_cells}
        if all((x, y, position.z) in cells for x, y in engine._actor_cells(actor, position)):
            return True


@effect('air_road_fall')
def sky_road_fall(ctx, row):
    from .damage_delivery import area
    from .effect_durations import token
    from ..falling import settle
    zone_id = area(ctx.engine)
    zone = ctx.engine.state.zones.get(zone_id)
    if ctx.target is None or zone is None or _mechanic_of(zone) != SKY_ROAD:
        return
    ctx.engine._apply_condition(ctx.target, 'condition:typed.sky_road_fallen', SKY_ROAD, ctx.actor.entity_id,
        expires_on=token('end', ctx.target.entity_id, ctx.target.turns_started + 1),
        data={'zone_id': zone_id, 'label': 'Sky Road: this crossing finds no solid wind'})
    settle(ctx.engine, SKY_ROAD, ctx.intent)


@effect('air_road_stand')
def sky_road_stand(ctx, row):
    from .damage_delivery import area
    from .condition_ownership import remove_instance
    if ctx.target is None:
        return
    for held in list(ctx.target.conditions.values()):
        if held.condition_id == 'condition:typed.sky_road_fallen' and held.data.get('zone_id') == area(ctx.engine):
            remove_instance(ctx.engine, ctx.target, held.instance_id, SKY_ROAD)

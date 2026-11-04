"""Force (rider lane 10, 2026-09-29): Pressure Anchors, the origins they give, the Force Limit, Counterpressure's add-ons, and the
lasting benefits of Force Mantle, World-Bracing Incarnation and Court of the Answering World. Rules text: the owner's Sphere
Compendium, "Force" (authority/typed_mechanics/rules_text.json; the core rules -- Pressure Anchor, Set Anchor, Force Limit -- are
the compendium's "CORE FORCE RULES", LocalSources/04_spheres_talents/Tianxia_Sphere_Compendium_Latest_R0I_85Spheres.md).

  Pressure Anchor  "You always count as one of your own Pressure Anchors ... an external Pressure Anchor occupies one creature, one
                   unattended object, or one 5-foot square of solid surface; lasts for 1 hour; you may maintain a number of external
                   Pressure Anchors equal to your Proficiency Bonus; creating another ... beyond this limit ends one older anchor of
                   your choice; an anchor placed on a creature or object moves with it; an anchor placed on a surface remains where it
                   was created ... you may dismiss one of your anchors without spending an Action."
  Set Anchor       "Action. Range: 30 feet. Target: One willing creature, one unattended object, or one 5-foot square of solid surface.
                   ... If the target creature already bears one of your external Pressure Anchors, the existing anchor ends ... An
                   unwilling creature is not a legal target."  (A base ability the catalog never listed: every Force holder -- one who
                   owns Impact -- gets the action here.)
  Force Limit      "your Force talents can meaningfully move or restrain creatures up to the maximum size listed for your Cultivation
                   Level: 1-4 Large, 5-9 Huge, 10-14 Gargantuan, 15+ any ordinary creature size."

What the table does with them:
  * An anchor is a placement (combat/ext/placed.py, tag "force_anchor"): on a square, or riding an ally (a willing creature). The
    oldest ends when a new one would pass the Proficiency Bonus limit; "Dismiss anchor" is free. Anchored Passage: range 60 feet
    and a second anchor with the same Action ("Set Anchor: second anchor", free, this turn only, another target).
  * Origins -- "Choose yourself or one Pressure Anchor you can perceive within N feet as the origin": Impact (the target within 30
    feet of the origin; the push goes directly away from it), Pressure Pin (10 feet from the origin), and the areas centred on
    the origin (Shockwave, Compression Field, Invisible Mountain, Heaven-Crushing Palm, Rampart of Still Air): the ability reaches as
    far as the anchor may be and is offered only at a legal origin (``candidate_allowed``). While Court of the Answering World is up
    every square of it is an anchor.
  * Counterpressure answers a creature within 5 feet of one of your anchors within 60 feet too (the ``reaction_reach`` hook), and in
    your Court any creature standing inside it.
  * Force Limit: a push row marked ``force_limit`` does not move a creature above the limit (typed_executor block_forced_movement);
    Pressure Pin cannot choose one.
  * Immovable Anchor: a willing creature (you or an ally) within 5 feet of yourself or one of your anchors has Advantage on saves
    against forced movement and falling Prone (a Shove included).
  * Clinging Anchor (+1 CP on an Impact hit, a creature within the Force Limit): an anchor on it; a Strength save -- failure: for the
    duration (Concentration, 1 minute), success: until the start of your next turn; it repeats the save at the end of each of its
    turns, ending the anchor on a success. It counts against your anchor limit.
  * Kinetic Reservoir: when Counterpressure reduces damage, that much pressure (up to 5 x CL) is stored until the end of your next
    turn; the next Impact, Shockwave, Ground-Answering Palm or Returning Impact that damages a creature adds it as Force damage to
    one damaged target. One reservoir at a time (a new one replaces it).
  * Recoil Ward: when Counterpressure reduces damage dealt by a creature within 30 feet of the protected target, pay 1 more CP: the
    creature makes a Strength save or is pushed 5 feet directly away from the protected target (within the Force Limit).
  * Force Mantle: once per turn, +Proficiency Bonus to one Force or Bludgeoning damage roll of one of your Force talents (the
    ``damage_roll_bonus`` hook, and ``attack_damage`` for Impact's attack).
  * World-Bracing Incarnation (while it lasts): Impact deals 6d10 and pushes 10 feet farther; Counterpressure once per round and
    Pressure Step once per turn cost no CP (their CP is given back). New sealed actions also increase the HP of newly created Barriers by 5 x PB through
    force_second_pass and the shared creation-durability hook. Markerless saved actions retain their old behavior.
  * Court of the Answering World (while it lasts): Pressure Step once per turn without CP; an ally a hostile creature misses with
    a melee attack may step 5 feet without Opportunity Attacks; allies inside have Advantage on saves against forced movement and
    falling Prone; an ally inside takes that much less falling damage (the ``falling_damage`` hook), and a Hammerfall collision
    against one is reduced the same way.
  * Returning Impact: the Force damage its Strength save answers with is "equal to the damage Counterpressure reduced, to a
    maximum of 3 x CL" -- a printed amount no dice can carry, added to the source creature's own share of the reaction's damage
    packet (the ``deal_bonus`` hook). What it reflects is what Counterpressure really kept off that packet: its own Cushion the
    Blow amount, never more than the damage the packet had left (a roll of 8 against a 1-damage hit prevented 1). The printed
    "does not reflect poison, Psychic damage, ongoing damage" line is not enforced and stays a GM rider.
  * Ten Thousand Rebounds: activating Counterpressure spends the Reaction and arms it ("Until the start of your next turn, the
    first time each hostile creature deals physical damage to you or an ally within 30 feet"). Each such creature answers once
    with its printed Strength save, damage and push, and every armed owner the blow reaches answers for itself. Physical damage
    here is Bludgeoning, Piercing, Slashing or Force: the sphere's own vocabulary for a blow with a physical impact, and what its
    printed poison/Psychic exclusions leave behind. Ongoing damage is not yet distinguishable from any other packet, so that
    printed exclusion is a GM rider rather than an enforced rule.
  * Both follow-ups need a Reaction seat the printed trigger does not exempt; that reading is OPEN OWNER QUESTION Q28 in
    docs/rules/RULES_OPEN_QUESTIONS.md, not a settled rule.
"""

from __future__ import annotations

import copy
from typing import Any

from . import effect, hook, note
from .rider_support import cp_pool as _cp_pool, occupant as _occupant, refund

TAG = "force_anchor"
IMPACT, COUNTER = "TAL_FORCE_IMPACT", "TAL_FORCE_COUNTERPRESSURE"
ANCHORED_PASSAGE, IMMOVABLE = "TAL_FORCE_ANCHORED_PASSAGE", "TAL_FORCE_IMMOVABLE_ANCHOR"
CLINGING, RESERVOIR, RECOIL = "TAL_FORCE_CLINGING_ANCHOR", "TAL_FORCE_KINETIC_RESERVOIR", "TAL_FORCE_RECOIL_WARD"
MANTLE, BRACING, COURT = "TAL_FORCE_FORCE_MANTLE", "TAL_FORCE_WORLD_BRACING_INCARNATION", "TAL_FORCE_COURT_OF_THE_ANSWERING_WORLD"
PRESSURE_STEP, PRESSURE_PIN = "TAL_FORCE_PRESSURE_STEP", "TAL_FORCE_PRESSURE_PIN"
RETURNING, REBOUNDS = "TAL_FORCE_RETURNING_IMPACT", "TAL_FORCE_TEN_THOUSAND_REBOUNDS"
STORED = "condition:typed.force_stored_pressure"
CLUNG = "condition:typed.force_clinging_anchor"
REBOUND_ARM = "condition:typed.force_rebounds"
SET_ANCHOR_FLAG = "force_second_anchor"
# "Physical damage" for Ten Thousand Rebounds: the damage types this sphere calls a blow with a physical impact.
PHYSICAL_DAMAGE = frozenset({"BLUDGEONING", "PIERCING", "SLASHING", "FORCE"})
# The abilities whose origin may be an anchor: {feature id: (how far the anchor may be, what it measures from the origin)}.
ORIGINS = {
    IMPACT: (60, "target", 30), PRESSURE_PIN: (60, "target", 10),
    "TAL_FORCE_SHOCKWAVE": (60, "area", 0), "TAL_FORCE_COMPRESSION_FIELD": (60, "area", 0), "TAL_FORCE_INVISIBLE_MOUNTAIN": (90, "area", 0),
    "TAL_FORCE_HEAVEN_CRUSHING_PALM": (120, "area", 0), "TAL_FORCE_RAMPART_OF_STILL_AIR": (90, "area", 0),
}
RESERVOIR_TECHNIQUES = ("TAL_FORCE_IMPACT", "TAL_FORCE_SHOCKWAVE", "TAL_FORCE_GROUND_ANSWERING_PALM", "TAL_FORCE_RETURNING_IMPACT")


# ------------------------------------------------------------------------------------------------------------------ helpers
def _owned(engine: Any, actor: Any, feature: str) -> bool:
    """The character owns a Force mechanic: one of its compiled actions or rows names it (combat/ext rows key off the bundle)."""
    rows = (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, [])
    if any(str(row.get("feature_id") or "") == feature for row in rows):
        return True
    reactions = (getattr(engine, "typed_reaction_rows", {}) or {}).get(actor.entity_id, [])
    if any(str(row.get("feature_id") or "").split("#")[0] == feature for row in reactions):
        return True
    return any(feature in str(action_id) for action_id in actor.action_ids)


def _block_owned(engine: Any, actor: Any, kind: str) -> bool:
    rows = (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, [])
    return any(row.get("block") == "force" and row.get("kind") == kind for row in rows)


def _active(actor: Any, feature: str) -> bool:
    """A lasting Force ability is up: a condition or modifier it put on its user is still there."""
    return any(feature in str(c.source_definition_id) for c in actor.conditions.values()) or \
        any(feature in str(m.source_definition_id) for m in actor.modifiers.values())


def cl_of(engine: Any, actor: Any) -> int:
    from .needle import numbers_of

    return int(numbers_of(engine, actor).get("cl") or 1)


def pb_of(engine: Any, actor: Any) -> int:
    return int(actor.proficiency_bonus or 2)


def limit_cells(cl: int) -> int | None:
    """The Force Limit as a footprint width (Large 2, Huge 3, Gargantuan 4 squares); None: any ordinary size."""
    return 2 if cl <= 4 else 3 if cl <= 9 else 4 if cl <= 14 else None


def within_limit(engine: Any, owner: Any, creature: Any) -> bool:
    cells = limit_cells(cl_of(engine, owner))
    return cells is None or engine._footprint(creature).width_cells <= cells


@hook("effect_subject_allowed")
def force_limit(ctx: Any, row: dict[str, Any], subject: Any) -> bool | None:
    if not row.get("force_limit"):
        return None
    return None if within_limit(ctx.engine, ctx.actor, subject) else False


def _placed():
    from . import placed

    return placed


def external(engine: Any, owner: Any) -> list[Any]:
    """The owner's external anchors (placements), oldest first."""
    return _placed().of(engine, TAG, owner_id=owner.entity_id)


def anchor_cell(engine: Any, zone: Any) -> Any:
    rider = engine.state.actors.get(str(zone.trigger_profile.get("anchor_id") or ""))
    return rider.position if rider is not None and rider.active else zone.affected_cells[0]


def _court_zone(engine: Any, owner: Any) -> Any | None:
    from .. import zones

    return next((zone for zone in zones.typed_zones(engine) if zone.active and zone.owner_id == owner.entity_id
                 and COURT in str(zone.source_definition_id)), None)


def _court_for(engine: Any, subject: Any) -> Any | None:
    """The Court of the Answering World whose Domain this creature is standing in, if any ("While the Domain persists ... You
    ... Allies ...": the owner and every ally inside it)."""
    for owner in engine.state.actors.values():
        if not owner.active or owner.team_id != subject.team_id:
            continue
        court = _court_zone(engine, owner)
        if court is not None and any((c.x, c.y) == (subject.position.x, subject.position.y) for c in court.affected_cells):
            return owner
    return None


@hook("falling_damage")
def court_soft_landing(engine: Any, target: Any, defended: int, context: Any, intent: Any) -> dict[str, Any] | None:
    """Court of the Answering World: "Allies ... Reduce falling and collision damage by your Proficiency Bonus" -- the
    falling half, read on the landing itself."""
    owner = _court_for(engine, target)
    return None if owner is None else {"amount": max(0, int(defended) - pb_of(engine, owner))}


def court_collision_reduction(engine: Any, target: Any) -> int:
    """The same Proficiency Bonus off collision damage, for Force's own collisions (Hammerfall's slam into a solid
    surface): the Court does not reduce an unrelated ability's damage."""
    owner = _court_for(engine, target)
    return 0 if owner is None else pb_of(engine, owner)


def origins(engine: Any, owner: Any, within_ft: int) -> list[Any]:
    """Every legal origin: the owner itself, then its external anchors within ``within_ft`` (and, in its Court, every square of
    it: "Treat every solid surface inside the Domain as one of your Pressure Anchors")."""
    found = [owner.position]
    for zone in external(engine, owner):
        cell = anchor_cell(engine, zone)
        if engine.grid.distance_ft(owner.position, cell) <= within_ft:
            found.append(cell)
    court = _court_zone(engine, owner)
    if court is not None:
        found.extend(cell for cell in court.affected_cells if engine.grid.distance_ft(owner.position, cell) <= within_ft)
    unique = []
    for cell in found:
        if all((cell.x, cell.y) != (seen.x, seen.y) for seen in unique):
            unique.append(cell)
    return unique


def _feature_of(action: Any) -> str | None:
    source = str(getattr(action, "source_definition_id", "") or "")
    return next((feature for feature in ORIGINS if feature in source), None)


# ------------------------------------------------------------------------------------------------------------------ Set Anchor
@hook("compile_actions")
def anchor_actions(info: dict[str, Any]) -> list[Any] | None:
    owned = set(info.get("owned_ids") or ())
    if IMPACT not in owned:
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    reach = 60 if ANCHORED_PASSAGE in owned else 30
    numbers = info.get("numbers") or {}
    base = {"numbers": numbers, "duration": {"kind": "instant"}, "riders": []}
    out = [
        ActionDefinition(source_definition_id=f"action:typed.{info['short']}.force_set_anchor", display_name="Set Anchor", owner_id=info["actor_id"],
                         economy=EconomyKind.ACTION, resolution_kind="TYPED", target_kind="CELL", range_ft=reach,
                         parameters={"typed": {**base, "effects": [{"type": "force_set_anchor", "second": ANCHORED_PASSAGE in owned}]},
                                     "expected_damage": 0, "player_only": True, "force_set_anchor": True, "any_cell": True,
                                     "description": "Create an external Pressure Anchor on a willing creature or a 5-foot square within range "
                                                    "(one per Proficiency Bonus; the oldest ends past that)."}),
        ActionDefinition(source_definition_id=f"action:typed.{info['short']}.force_dismiss_anchor", display_name="Dismiss anchor",
                         owner_id=info["actor_id"], economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF",
                         parameters={"typed": {**base, "effects": [{"type": "force_dismiss_anchor"}]}, "expected_damage": 0,
                                     "player_only": True, "force_dismiss": True,
                                     "description": "Dismiss your oldest external Pressure Anchor (no Action)."}),
    ]
    if ANCHORED_PASSAGE in owned:
        out.append(ActionDefinition(
            source_definition_id=f"action:typed.{info['short']}.force_set_anchor_second", display_name="Set Anchor: second anchor",
            owner_id=info["actor_id"], economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="CELL", range_ft=reach,
            parameters={"typed": {**base, "effects": [{"type": "force_set_anchor", "second": False, "clears": SET_ANCHOR_FLAG}]},
                        "expected_damage": 0, "player_only": True, "force_set_anchor": True, "any_cell": True,
                        "requires_turn_flag": SET_ANCHOR_FLAG,
                        "description": "Anchored Passage: the same Set Anchor makes a second external anchor on another legal target."}))
    return out


def _legal_anchor_cell(engine: Any, owner: Any, cell: Any) -> bool:
    if cell is None or (cell.x, cell.y) in (getattr(engine.grid, "blocked", None) or set()):
        return False
    other = _occupant(engine, cell)
    if other is not None and (other.team_id != owner.team_id or other.entity_id == owner.entity_id):
        return False  # "An unwilling creature is not a legal target"; you always count as an anchor already
    taken = {(anchor_cell(engine, zone).x, anchor_cell(engine, zone).y) for zone in external(engine, owner)}
    return (cell.x, cell.y) not in taken


def place_anchor(engine: Any, owner: Any, cell: Any, source: str, *, on: Any = None, expires: dict[str, Any] | None = None) -> Any:
    """One external anchor on ``on`` (a creature: it rides it) or the square ``cell``; the oldest ends past the limit."""
    placed = _placed()
    if on is not None:
        for zone in external(engine, owner):
            if zone.trigger_profile.get("anchor_id") == on.entity_id:
                placed.drop(engine, zone, "a new anchor on the same creature")
    while len(external(engine, owner)) >= pb_of(engine, owner):
        from .rider_choices import pick
        old = external(engine, owner)
        chosen = pick(engine, owner, "force_anchor_limit", "Pressure Anchors", [z.zone_id for z in old],
                      labels={z.zone_id: f"End anchor at {anchor_cell(engine, z).x},{anchor_cell(engine, z).y}" for z in old},
                      subject=on or owner, trigger="creating a Pressure Anchor beyond the limit", optional=False,
                      preferred=[old[0].zone_id])
        placed.drop(engine, engine.state.zones[chosen[0]], "the anchor limit: the owner's choice")
    at = on.position if on is not None else cell
    return placed.place(engine, owner, source=source, tag=TAG, cells=[at], name="Pressure Anchor", material="force",
                        placed={"label": f"{owner.display_name}'s Pressure Anchor", **(expires or {})},
                        anchor_id=on.entity_id if on is not None else None)


@effect("force_set_anchor")
def set_anchor(ctx: Any, eff: dict[str, Any]) -> None:
    engine, owner = ctx.engine, ctx.actor
    cell = ctx.damage_cache.get("_checkpoint_aim")
    if eff.get("clears"):
        owner.turn_flags.pop(str(eff["clears"]), None)
    if not _legal_anchor_cell(engine, owner, cell):
        ctx.rider("Set Anchor: that square is not a legal target (an unwilling creature, a wall, or one of your anchors already).")
        return
    other = _occupant(engine, cell)
    place_anchor(engine, owner, cell, ctx.source, on=other)
    note(engine, ctx.source, owner, f"{owner.display_name} sets a Pressure Anchor " + (f"on {other.display_name}." if other else f"at {cell.x},{cell.y}."))
    if eff.get("second"):
        owner.turn_flags[SET_ANCHOR_FLAG] = True  # Anchored Passage: "create up to two external Pressure Anchors instead of one"


@effect("force_dismiss_anchor")
def dismiss_anchor(ctx: Any, eff: dict[str, Any]) -> None:
    rows = external(ctx.engine, ctx.actor)
    if rows:
        _placed().drop(ctx.engine, rows[0], "dismissed")


# ------------------------------------------------------------------------------------------------------------------ origins
@hook("candidate_allowed")
def force_candidates(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    params = getattr(action, "parameters", None) or {}
    if params.get("force_set_anchor"):
        if params.get("requires_turn_flag") and not actor.turn_flags.get(params["requires_turn_flag"]):
            return False  # Anchored Passage's second anchor: only right after a Set Anchor (any-square candidates skip the flag check)
        return None if _legal_anchor_cell(engine, actor, getattr(candidate, "destination", None)) else False
    if params.get("force_dismiss"):
        return None if external(engine, actor) else False
    from .force_second_pass import geometry
    if geometry(action) is not None:
        return None  # New sealed geometry uses native origin-bound range/cover.
    feature = _feature_of(action)
    if feature is None:
        return None
    reach, kind, _span = ORIGINS[feature]
    legal = origins(engine, actor, reach)
    if kind == "area":
        aim = getattr(candidate, "destination", None)
        if aim is None:
            return None
        return None if any((aim.x, aim.y) == (cell.x, cell.y) for cell in legal) else False
    target = engine.state.actors.get(next(iter(getattr(candidate, "target_ids", None) or ()), ""))
    if target is None:
        return None
    if feature == PRESSURE_PIN and not within_limit(engine, actor, target):
        return False  # "Choose one creature that does not exceed your Force Limit."
    # "within 30 feet of that origin": an origin the target is out of reach of is no origin for this target, so the cover
    # question is asked only of the origins that could actually be used from here.
    usable = _target_origins(engine, actor, feature, target)
    if not usable:
        return False
    if feature == IMPACT and _always_total_cover(engine, actor, usable, target):
        return False  # "Choose one visible creature or object within 30 feet of that origin. The target must not have Total Cover from the origin."
    return None


def _target_origins(engine: Any, owner: Any, feature: str, target: Any) -> list[Any]:
    """Every legal origin this target is within the ability's span of ("within 30 feet of that origin"). Shared by the
    candidate filter and the origin a player picks, so the two can never disagree about which origins exist for a target."""
    reach, _kind, span = ORIGINS.get(feature, (60, "target", 30))
    return [cell for cell in origins(engine, owner, reach) if engine.grid.distance_ft(cell, target.position) <= span]


def _origin_reaches(engine: Any, owner: Any, cell: Any, target: Any) -> bool:
    """Whether an open physical ray runs from that origin to the target -- the table's Total Cover for an effect
    (``combat/effect_cover.query``'s ``blocked``: no open ray at all, which is the absence of a path an attack could take).
    The +2 half-cover and +5 three-quarters-cover bonuses are not Total Cover: a target behind either one can still be hit
    from a clear ray, so it stays a legal target."""
    from ..effect_cover import query

    cells = engine._effect_cells(owner) if (cell.x, cell.y, cell.z) == (owner.position.x, owner.position.y, owner.position.z) \
        else ((cell.x, cell.y, cell.z),)
    return not query(engine, cells, owner.entity_id, target, purpose="effect").get("blocked")


def _always_total_cover(engine: Any, owner: Any, legal: list[Any], target: Any) -> bool:
    """Whether the target is in Total Cover from every one of these legal origins, so no origin makes it a legal Impact target
    ("The target must not have Total Cover from the origin"). Only a walled-off origin counts: three-quarters cover is not
    Total Cover."""
    return all(not _origin_reaches(engine, owner, cell, target) for cell in legal)


def _origin_choices(engine: Any, owner: Any, feature: str, target: Any) -> list[Any]:
    """The origins a player may pick for this target. A technique whose printed rule names a visible creature may only be used
    from an origin with an open ray to it, so the menu never offers one the target cannot be struck from."""
    usable = _target_origins(engine, owner, feature, target)
    return [cell for cell in usable if _origin_reaches(engine, owner, cell, target)] if feature == IMPACT else usable


@effect("force_origin")
def force_origin(ctx: Any, eff: dict[str, Any]) -> None:
    """The origin this use is measured from: yourself when the target is in reach of you, else the nearest anchor that reaches it. A
    push "directly away from the origin" then goes away from it (the row's ``away_center`` reads ``_area_centre``)."""
    engine, owner, target = ctx.engine, ctx.actor, ctx.target
    feature = str(eff.get("feature") or IMPACT)
    if target is None:
        return
    legal = _origin_choices(engine, owner, feature, target)
    if not legal:
        return
    origin = min(legal, key=lambda cell: (cell != legal[0], engine.grid.distance_ft(cell, target.position)))
    if len(legal) > 1:
        from .rider_choices import pick
        from .needle import cell_id, position_of
        options = [cell_id(cell) for cell in legal]
        chosen = pick(engine, owner, "force_origin", ctx.action.display_name, options,
                      labels={cell_id(cell): f"Origin at {cell.x},{cell.y}" for cell in legal}, subject=target,
                      optional=False, preferred=[cell_id(origin)], trigger=ctx.action.display_name, intent=ctx.intent)
        origin = position_of(chosen[0])
    ctx.typed["_area_centre"] = (origin.x, origin.y)
    if (origin.x, origin.y) != (owner.position.x, owner.position.y):
        note(engine, ctx.source, owner, f"{ctx.action.display_name} from the Pressure Anchor at {origin.x},{origin.y}.", (target.entity_id,))


# ------------------------------------------------------------------------------------------------------ Counterpressure's reach
@hook("reaction_reach")
def counterpressure_reach(engine: Any, reactor: Any, other: Any, row: dict[str, Any]) -> bool | None:
    """"within 5 feet of yourself or one Pressure Anchor you can perceive within 60 feet"; in the Court, "when its protected target
    is within 5 feet of any solid surface inside the Domain" (a creature standing inside it)."""
    if str(row.get("feature_id") or "").split("#")[0] != COUNTER or other is None:
        return None
    reach = int(row.get("range_ft") or 5)
    if any(engine.grid.distance_ft(cell, other.position) <= reach for cell in origins(engine, reactor, 60)[1:]):
        return True
    court = _court_zone(engine, reactor)
    if court is not None and any((c.x, c.y) == (other.position.x, other.position.y) for c in court.affected_cells):
        return True
    return None


# ------------------------------------------------------------------------------------------------------------------ saves
def _immovable_near(engine: Any, subject: Any) -> bool:
    for owner in engine.state.actors.values():
        if not owner.active or owner.team_id != subject.team_id or not _block_owned(engine, owner, "immovable_anchor"):
            continue
        if any(engine.grid.distance_ft(cell, subject.position) <= 5 for cell in origins(engine, owner, 10_000)):
            return True
    return False


def _court_ally(engine: Any, subject: Any) -> bool:
    """Court of the Answering World: "Allies ... Gain Advantage on saving throws and contested checks made to resist forced
    movement and falling Prone." (the Court's owner stands in its own Domain)."""
    return _court_for(engine, subject) is not None


@hook("save")
def steady_saves(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    """Immovable Anchor and the Court's allies: Advantage on saves against forced movement and falling Prone (a Shove too)."""
    named = set(named or ())
    if not ({"forced_movement", "prone"} & named) or subject.team_id == ctx.actor.team_id:
        return None
    if _immovable_near(ctx.engine, subject) or _court_ally(ctx.engine, subject):
        return {"bonus": 0, "modes": ["ADVANTAGE"]}
    return None


# ------------------------------------------------------------------------------------------------------------------ Clinging Anchor
@effect("force_clinging_anchor")
def clinging_anchor(ctx: Any, eff: dict[str, Any]) -> None:
    from ..typed_executor import Context, run_effects
    from .effect_durations import token, round_token

    engine, owner, target = ctx.engine, ctx.actor, ctx.target
    if target is None or not target.active or not within_limit(engine, owner, target):
        return
    before = len(engine.events)
    probe = Context(engine, owner, ctx.action, ctx.intent, ctx.typed, [target], target, {})
    run_effects(probe, [{"type": "save", "ability": "str", "on_fail": [], "on_success": []}])
    rolled = next((e for e in engine.events[before:] if e.event_type == "SAVE_ROLLED"), None)
    failed = bool(rolled) and not bool((rolled.payload or {}).get("success"))
    cast = None
    if failed:
        accepted = next((e.sequence for e in reversed(engine.events) if e.event_type == "INTENT_ACCEPTED"), engine.state.event_sequence)
        current = owner.concentration
        if current is None or current.source_definition_id != ctx.source or current.started_sequence <= accepted:
            engine._start_concentration(owner, ctx.source)
        cast = owner.concentration.started_sequence
    expires = {"until": round_token(engine, 10) if failed else token("start", owner.entity_id, int(owner.turns_started) + 1)}
    zone = place_anchor(engine, owner, target.position, ctx.source, on=target, expires=expires)
    engine._apply_condition(target, CLUNG, ctx.source, owner.entity_id, expires_on="UNTIL_REMOVED",
                            data={"label": f"Clinging Anchor ({owner.display_name}): repeats its Strength save at the end of each of its turns",
                                  "zone_id": zone.zone_id, "dc": int(ctx.numbers.get("save_dc") or 10), "concentration": failed,
                                  **({"cast_sequence": int(cast)} if cast is not None else {})})
    note(engine, ctx.source, owner, f"Clinging Anchor: a Pressure Anchor clings to {target.display_name} "
                                    f"({'for the duration' if failed else 'until the start of your next turn'}).", (target.entity_id,))


def _end_clinging(engine: Any, holder: Any, iid: str, why: str) -> None:
    condition = holder.conditions.pop(iid, None)
    if condition is None:
        return
    engine._append_event("CONDITION_REMOVED", "system:force.clinging_anchor", actor_id=condition.source_actor_id, target_ids=(holder.entity_id,),
                         payload={"condition_id": condition.condition_id, "instance_id": iid})
    zone = engine.state.zones.get(str((condition.data or {}).get("zone_id") or ""))
    if zone is not None and zone.active:
        _placed().drop(engine, zone, why)


@hook("turn_end")
def clinging_repeat_save(engine: Any, actor: Any) -> None:
    for iid, condition in list(actor.conditions.items()):
        if condition.condition_id != CLUNG or not actor.active:
            continue
        dc = int((condition.data or {}).get("dc") or 10)
        roll = engine._roll_save(actor, "STR", dc, "system:force.clinging_anchor")
        if roll is not None and roll.total >= dc:
            _end_clinging(engine, actor, iid, "the creature shook the anchor off")


@hook("event")
def anchors_expire(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """A Clinging Anchor that lasts "until the start of your next turn" ends then; one that lasts for the duration ends with its
    Concentration; an anchor on a creature that is gone ends with it."""
    if event_type not in ("TURN_STARTED", "CONCENTRATION_ENDED", "PASSIVE_TRIGGERED", "ACTOR_DEFEATED", "ENTITY_DEFEATED"):
        return
    for zone in list(_placed().of(engine, TAG)):
        data = _placed().data(zone)
        rider = zone.trigger_profile.get("anchor_id")
        if data.get("until") and _placed().deadline_due(engine, zone, str(data["until"])):
            _drop_anchor(engine, zone, "its time ran out")
        elif rider and (engine.state.actors.get(rider) is None or not engine.state.actors[rider].active):
            _drop_anchor(engine, zone, "its creature is gone")
    from .. import concentration
    for holder in engine.state.actors.values():
        for iid, condition in list(holder.conditions.items()):
            if condition.condition_id != CLUNG or not (condition.data or {}).get("concentration"):
                continue
            owner = engine.state.actors.get(condition.source_actor_id)
            held = concentration.copies(owner, condition.source_definition_id) if owner is not None else []
            cast = (condition.data or {}).get("cast_sequence")
            # Legacy saves without a cast stamp keep their source-scoped lifetime.
            if not held or cast is not None and int(cast) not in held:
                _end_clinging(engine, holder, iid, "its Concentration cast ended")


def _drop_anchor(engine: Any, zone: Any, why: str) -> None:
    for holder in engine.state.actors.values():
        for iid, condition in list(holder.conditions.items()):
            if condition.condition_id == CLUNG and (condition.data or {}).get("zone_id") == zone.zone_id:
                holder.conditions.pop(iid, None)
                engine._append_event("CONDITION_REMOVED", "system:force.anchor", actor_id=condition.source_actor_id, target_ids=(holder.entity_id,),
                                     payload={"condition_id": condition.condition_id, "instance_id": iid})
    if zone.active:
        _placed().drop(engine, zone, why)


@hook("placed_deadline_expiring")
def nominal_anchor_cleanup(engine: Any, zone: Any) -> None:
    if _placed().data(zone).get("tag") == TAG:
        _drop_anchor(engine, zone, "its time ran out")


# ------------------------------------------------------------------------------------------------ Pressure Sense
SENSE = "tianxia.talent.force.pressure_sense"


def _sense_note(engine: Any, owner: Any, what: str) -> None:
    """One plain line: which of the owner's own anchors answered, and nothing else -- no square, no creature, no other
    information, exactly as the printed limitation says."""
    note(engine, "passive:" + SENSE, owner, f"Pressure Sense: one of your Pressure Anchors {what}.")


@hook("event", nested=True)
def pressure_sense(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """Pressure Sense: "You know when one of your Pressure Anchors: is struck; is moved; is destroyed; is crossed by a creature of
    Small size or larger; becomes separated from you by a planar boundary."

    The table's anchors are a placed 5-foot marker or a rider on a creature, so three of the five printed events have something to
    happen here: the marker ends, it travels with the creature it rests on, and a creature crosses its square (every creature on
    the table is Medium or larger, so "Small size or larger" excludes nobody). An anchor is never attacked for its own sake and
    the table has no planar boundaries, so those two clauses stay printed text -- the honest remaining line.
    """
    if event_type == "ZONE_REMOVED":
        zone = engine.state.zones.get(str((kwargs.get("payload") or {}).get("zone_id") or ""))
        owner = engine.state.actors.get(str(zone.owner_id) if zone is not None else "")
        if zone is not None and _placed().data(zone).get("tag") == TAG and owner is not None and owner.active \
                and _block_owned(engine, owner, "pressure_sense"):
            _sense_note(engine, owner, "is no longer there")
        return
    if event_type != "MOVEMENT_COMMITTED":
        return
    mover = engine.state.actors.get(str(kwargs.get("actor_id") or ""))
    if mover is None or not mover.active:
        return
    for owner in engine.state.actors.values():
        if not owner.active or mover.entity_id == owner.entity_id or not _block_owned(engine, owner, "pressure_sense"):
            continue
        for zone in external(engine, owner):
            if zone.trigger_profile.get("anchor_id") == mover.entity_id:
                _sense_note(engine, owner, "has moved with the creature it rests on")
                break
            if _path_crosses((kwargs.get("payload") or {}).get("path") or [], zone.affected_cells[0]):
                _sense_note(engine, owner, "has a creature pass across it")
                break


def _path_crosses(path: Any, cell: Any) -> bool:
    """Whether a recorded movement path touched that square."""
    return any((row.get("x"), row.get("y")) == (cell.x, cell.y) for row in path if isinstance(row, dict))


# ------------------------------------------------------------------------------------------------ Counterpressure add-ons
def _counter_resolved(engine: Any, kwargs: dict[str, Any]) -> tuple[Any, Any, Any, int] | None:
    """(reactor, source creature, protected creature, damage reduced) for a Counterpressure that just reduced damage."""
    last = engine.events[-1] if getattr(engine, "events", None) else None
    payload = kwargs.get("payload") or {}
    if last is None or payload.get('carried_budget') or str(last.source_definition_id).split("#")[0] != COUNTER or payload.get("checkpoint") != "DAMAGE_APPLICATION":
        return None
    reduced = int(payload.get("reduction") or 0)
    reactor = engine.state.actors.get(str(kwargs.get("actor_id") or ""))
    source = engine.state.actors.get(next(iter(kwargs.get("target_ids") or ()), ""))
    protected = engine.state.actors.get(str(payload.get("protects") or kwargs.get("actor_id") or ""))
    if reactor is None or reduced <= 0:
        return None
    return reactor, source, protected, reduced


@hook("event")
def counterpressure_answers(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type != "REACTION_RESOLVED":
        return
    found = _counter_resolved(engine, kwargs)
    if found is None:
        return
    reactor, source, protected, reduced = found
    if _block_owned(engine, reactor, "kinetic_reservoir"):
        from .effect_durations import token
        from .rider_choices import pick

        stored = min(reduced, 5 * cl_of(engine, reactor))
        if not pick(engine, reactor, "force_store", "Kinetic Reservoir", ["store"], subject=protected or reactor,
                    trigger=f"Counterpressure reduces {source.display_name if source else 'the attacker'}'s damage",
                    labels={"store": f"Store {stored} pressure"}):
            stored = 0
        for iid, condition in list(reactor.conditions.items()):
            if stored and condition.condition_id == STORED:  # "You may maintain only one Kinetic Reservoir at a time."
                reactor.conditions.pop(iid, None)
                engine._append_event("CONDITION_REMOVED", "passive:" + RESERVOIR, actor_id=reactor.entity_id, target_ids=(reactor.entity_id,),
                                     payload={"condition_id": STORED, "instance_id": iid})
        if stored:
            engine._apply_condition(reactor, STORED, "passive:" + RESERVOIR, reactor.entity_id,
                                expires_on=token("end", reactor.entity_id, int(reactor.turns_started) + 1),  # "until the end of your next turn"
                                data={"label": f"Kinetic Reservoir: {stored} stored pressure", "amount": stored})
            note(engine, "passive:" + RESERVOIR, reactor, f"Kinetic Reservoir: {reactor.display_name} stores {stored} pressure.")
    if _block_owned(engine, reactor, "recoil_ward") and source is not None and protected is not None and source.active \
            and source.team_id != reactor.team_id and engine.grid.distance_ft(source.position, protected.position) <= 30:
        _recoil_ward(engine, reactor, source, protected)
    if _active(reactor, BRACING) and not reactor.turn_flags.get(f"force_round_bracing_counter:{engine.state.round_number}"):
        reactor.turn_flags[f"force_round_bracing_counter:{engine.state.round_number}"] = True
        _refund(engine, reactor, "World-Bracing Incarnation: Counterpressure without spending CP")


def _refund(engine: Any, actor: Any, why: str) -> None:
    refund(engine, actor, why, "passive:force")


def _current_counter_window(engine: Any, reactor: Any, source: Any) -> Any:
    """The Counterpressure reaction window this trigger just opened for ``reactor`` against ``source``: the owner's own most
    recent one at the damage checkpoint, read back-to-front. Trigger boundary: the engine opens that window and then runs its
    row's effects -- this follow-up -- inside the same call, so the newest matching window is always the current one and an
    older window from an earlier hit can never be the one that is current. Returns ``None`` when this owner has no window for
    this attacker yet.

    The creature that reaction shielded is this window's own ``protects`` field (the owner's own id on the self path,
    typed_reactions.py:1803 for an ally's damage, typed_reactions.py:2023 for its own). That field lives on the window, not on
    the follow-up context: the follow-up is opened by a fresh context (typed_reactions.py:2537) that never receives ``protects``,
    so a lookup keyed on that context could only ever match the self path and would silently read the wrong window for an ally."""
    return next((event for event in reversed(getattr(engine, "events", None) or [])
                 if event.event_type == "REACTION_WINDOW_OPENED" and event.actor_id == reactor.entity_id
                 and str(event.source_definition_id).split("#")[0] == COUNTER
                 and (event.payload or {}).get("checkpoint") == "DAMAGE_APPLICATION"
                 and event.target_ids[:1] == (source.entity_id,)), None)


def _counterpressure_caught(engine: Any, reactor: Any, source: Any) -> int:
    """The damage Counterpressure actually kept off the packet in flight, for this owner and this source creature: its own
    Cushion the Blow amount, never more than the damage that packet actually had left (the reduction path clamps a reduction
    at zero, so a large roll against a small hit prevented only the hit). Read from the engine's own current accepted reaction
    window for this owner and this source (``_current_counter_window``) and the roll that window's own row made -- never from
    a roll anywhere in the fight. The window's ``pending_damage`` is this packet's own damage, so clamping against it is what
    keeps a large roll against a small hit from being returned whole."""
    window = _current_counter_window(engine, reactor, source)
    if window is None:
        return 0
    rolled = next((int(roll.total) for roll in reversed(getattr(engine, "rolls", None) or [])
                   if str(roll.reason).startswith(f"GENERIC_AMOUNT:{COUNTER}") and roll.actor_id == reactor.entity_id), 0)
    return min(max(0, int((window.payload or {}).get("pending_damage") or 0)), rolled)


@hook("deal_bonus")
def returning_impact_deal(ctx: Any, subject: Any, amount: int) -> int | None:
    """Returning Impact: "Take Force damage equal to the damage Counterpressure reduced, to a maximum of 3 x CL" -- a printed
    amount no dice can carry, added to the source creature's own share of the reaction's damage packet (before the save
    divides it, so a successful Strength save still halves it). The caught pressure is what Counterpressure really kept off
    that packet (``_counterpressure_caught``), capped at 3 x CL, so the return never exceeds the reduction it reflects."""
    if RETURNING not in str(getattr(ctx, "source", "")) or subject is None or subject is not ctx.target:
        return None
    caught = _counterpressure_caught(ctx.engine, ctx.actor, subject)
    return None if not caught else min(caught, 3 * cl_of(ctx.engine, ctx.actor))


# ------------------------------------------------------------------------------------------------ Ten Thousand Rebounds
def _rebound_row(engine: Any, actor: Any) -> dict[str, Any] | None:
    return next((row for row in (getattr(engine, "typed_reaction_rows", {}) or {}).get(actor.entity_id, [])
                 if str(row.get("feature_id") or "").split("#")[0] == REBOUNDS), None)


def _rebound_response(row: dict[str, Any]) -> list[dict[str, Any]]:
    """The printed Strength save Ten Thousand Rebounds answers with, from the character's own compiled reaction row."""
    return next((list(effect.get("response") or []) for effect in row.get("effects") or []
                 if isinstance(effect, dict) and effect.get("type") == "force_arm_rebounds"), [])



@effect("force_arm_rebounds")
def arm_rebounds(ctx: Any, eff: dict[str, Any]) -> None:
    """Ten Thousand Rebounds: arm the printed duration. The save, damage and push run from ``rebounds_answer`` below, once
    for each hostile creature that lands a physical blow."""
    _arm(ctx.engine, ctx.actor, "")


def _arm(engine: Any, owner: Any, spent: str, expires_on: str | None = None) -> None:
    """(Re)issue the arming record. Written through the condition's own events rather than by editing the stored record, so a
    table commit and reload rebuild exactly the same state; ``spent`` is the creatures already answered, as one string."""
    from .condition_events import drop_condition
    from .effect_durations import token

    held = next((iid for iid, condition in owner.conditions.items() if condition.condition_id == REBOUND_ARM), None)
    if held is not None:
        drop_condition(engine, owner, held, "passive:" + REBOUNDS)
    engine._apply_condition(owner, REBOUND_ARM, "passive:" + REBOUNDS, owner.entity_id,
                            expires_on=expires_on or token("start", owner.entity_id, int(owner.turns_started) + 1),
                            data={"label": "Ten Thousand Rebounds (until the start of your next turn): the first physical blow "
                                           "each hostile creature lands on you or an ally within 30 feet makes that creature "
                                           "roll a Strength saving throw -- 4d8 Force damage and a 10-foot push away from the "
                                           "creature it struck on a failure, half damage and no push on a success. Each "
                                           "hostile creature is affected once during the duration.",
                                  "spent": spent})
    if not spent:
        note(engine, "passive:" + REBOUNDS, owner,
             f"Ten Thousand Rebounds: until the start of your next turn, the first physical blow each hostile creature lands on "
             f"{owner.display_name} or on an ally within 30 feet makes that creature roll a Strength saving throw. "
             f"Each hostile creature answers once.")


def _rebound_harmed(engine: Any, owner: Any, harmed: Any, source: Any) -> bool:
    """"you or an ally within 30 feet" took a physical blow from a hostile creature not yet answered."""
    if harmed is None or not harmed.active or source is None or not source.active:
        return False
    if source.team_id == owner.team_id or source.entity_id == owner.entity_id:
        return False
    if harmed.entity_id != owner.entity_id and not (harmed.team_id == owner.team_id
                                                   and engine.grid.distance_ft(owner.position, harmed.position) <= 30):
        return False
    return source.entity_id not in str((_armed(engine, owner) or {}).get("spent") or "").split()


def _armed(engine: Any, owner: Any) -> dict[str, Any] | None:
    found = next(((iid, c) for iid, c in owner.conditions.items() if c.condition_id == REBOUND_ARM), None)
    return found[1].data if found else None


@hook("event", nested=True)
def rebounds_answer(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """"Until the start of your next turn, the first time each hostile creature deals physical damage to you or an ally
    within 30 feet, it makes a Strength saving throw" -- answered as that blow lands, once per creature. Every armed owner
    the blow reaches answers for itself ("each" is per owner, not per fight), and one owner's own retaliation is not a blow
    another owner answers."""
    if event_type != "DAMAGE_COMMITTED" or engine.__dict__.get("_force_rebounding"):
        return
    payload = kwargs.get("payload") or {}
    if int(payload.get("hp_damage") or 0) + int(payload.get("temporary_hp_absorbed") or 0) <= 0:
        return
    if str(payload.get("damage_type") or "").upper() not in PHYSICAL_DAMAGE:
        return
    harmed = engine.state.actors.get(next(iter(kwargs.get("target_ids") or ()), ""))
    source = engine.state.actors.get(str(kwargs.get("actor_id") or ""))
    answering = [owner for owner in list(engine.state.actors.values())
                 if owner.active and _armed(engine, owner) is not None and _rebound_harmed(engine, owner, harmed, source)]
    if not answering:
        return
    # The guard spans the whole answer: one owner's retaliation damage must not offer itself to another armed owner.
    engine.__dict__["_force_rebounding"] = True
    try:
        for owner in answering:
            row = _rebound_row(engine, owner)
            response = _rebound_response(row) if row is not None else []
            if not response:
                continue  # a malformed or legacy row is that owner's own gap, not the end of the answer
            held = next((c for c in owner.conditions.values() if c.condition_id == REBOUND_ARM))
            _arm(engine, owner, f"{str(held.data.get('spent') or '').strip()} {source.entity_id}".strip(), held.expires_on)
            _answer(engine, owner, harmed, source, row, response)
    finally:
        engine.__dict__["_force_rebounding"] = False


def _answer(engine: Any, owner: Any, harmed: Any, source: Any, row: dict[str, Any], response: list[dict[str, Any]]) -> None:
    """One owner's printed answer to one blow: the source creature's own Strength save, the Force damage and the push away
    from the creature it struck, read from that owner's own compiled reaction row."""
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    from ..typed_executor import Context, run_effects

    action = ActionDefinition(source_definition_id=REBOUNDS, display_name="Ten Thousand Rebounds", owner_id=owner.entity_id,
                              economy=EconomyKind.REACTION, resolution_kind="TYPED", target_kind="HOSTILE_ENTITY",
                              parameters={"typed": {"effects": [], "numbers": dict(row.get("numbers") or {}),
                                                    "source": REBOUNDS, "riders": [], "duration": {"kind": "instant"}}})
    inner = Context(engine, owner, action, getattr(engine, "_active_intent", None),
                    {"effects": [], "numbers": dict(row.get("numbers") or {}), "source": REBOUNDS, "riders": [],
                     "duration": {"kind": "instant"}, "triggering_source_id": source.entity_id,
                     "_area_centre": (harmed.position.x, harmed.position.y)},
                    [source], source, {})
    on_itself = harmed.entity_id == owner.entity_id
    whose = "its own blow" if on_itself else "the blow it landed"
    note(engine, "passive:" + REBOUNDS, owner,
         f"Ten Thousand Rebounds: {source.display_name} must make a Strength saving throw after {whose} on "
         f"{harmed.display_name}; on a failure it takes 4d8 Force damage and is pushed 10 feet away from "
         f"{harmed.display_name}, and on a success it takes half that damage and is not pushed.", (source.entity_id,))
    run_effects(inner, copy.deepcopy(response))


def _recoil_ward(engine: Any, reactor: Any, source: Any, protected: Any) -> None:
    from .needle import ask, checkpoint_id, save_dc
    from .rider_choices import trigger_name

    pool = _cp_pool(reactor)
    if pool is None or reactor.resources.get(pool, 0) < 1:
        return
    picked = ask(engine, getattr(engine, "_active_intent", None), checkpoint_id(engine, "RECOIL", reactor.entity_id, source.entity_id), reactor,
                 "choice:needle.force_recoil", ["pay", "pass"], labels={"pay": "Recoil Ward: pay 1 CP", "pass": "Not now"}, preferred=["pay"],
                 prompt=f"Recoil Ward: {trigger_name(engine)} affecting {protected.display_name}; push {source.display_name} back?",
                 target_id=source.entity_id)
    if picked[:1] != ["pay"]:
        return
    engine._spend_resource(reactor, pool, 1, "passive:" + RECOIL)
    dc = save_dc(engine, reactor)
    roll = engine._roll_save(source, "STR", dc, "passive:" + RECOIL)
    if roll is None or roll.total >= dc or not within_limit(engine, reactor, source):
        note(engine, "passive:" + RECOIL, reactor, f"Recoil Ward: {source.display_name} holds its ground.", (source.entity_id,))
        return
    from ..typed_executor import Context, _push

    ctx = Context(engine, reactor, next(iter(engine.action_catalog.values())), getattr(engine, "_active_intent", None),
                  {"effects": [], "numbers": {}, "_area_centre": (protected.position.x, protected.position.y)}, [source], source)
    _push(ctx, source, 5, pull=False, centred=True)
    note(engine, "passive:" + RECOIL, reactor, f"Recoil Ward: {source.display_name} is pushed back from {protected.display_name}.", (source.entity_id,))


@hook("technique_used")
def reservoir_release(ctx: Any) -> None:
    """Kinetic Reservoir: the owner may choose a target damaged by this technique and an amount of stored pressure.
    AI preferences release all pressure on the damaged creature with the fewest Hit Points left."""
    engine, actor = ctx.engine, ctx.actor
    stored = next(((iid, c) for iid, c in actor.conditions.items() if c.condition_id == STORED), None)
    if stored is None or not any(feature in str(ctx.source) for feature in RESERVOIR_TECHNIQUES):
        return
    # Only this accepted action can release pressure, not a prior hit by the
    # same technique while the reservoir was being held.
    accepted = max((int(e.sequence) for e in engine.events if e.event_type == "INTENT_ACCEPTED"), default=0)
    damaged = [engine.state.actors.get(target_id) for event in engine.events
               if event.event_type == "DAMAGE_COMMITTED" and event.source_definition_id == ctx.source and event.actor_id == actor.entity_id
               and int((event.payload or {}).get("hp_damage") or 0) + int((event.payload or {}).get("temporary_hp_absorbed") or 0) > 0
               and int(event.sequence) > max(accepted, int(stored[1].applied_sequence)) for target_id in event.target_ids]
    damaged = [target for target in damaged if target is not None and target.active and target.entity_id != actor.entity_id]
    if not damaged:
        return
    from .rider_choices import pick
    damaged = sorted({t.entity_id: t for t in damaged}.values(), key=lambda t: (t.current_hp, t.entity_id))
    chosen = pick(engine, actor, "force_release_target", "Kinetic Reservoir", [t.entity_id for t in damaged],
                  labels={t.entity_id: f"Release pressure on {t.display_name}" for t in damaged}, subject=damaged[0],
                  trigger=ctx.action.display_name, preferred=[damaged[0].entity_id], intent=ctx.intent)
    if not chosen:
        return
    target = engine.state.actors[chosen[0]]
    iid, condition = stored
    amount = int((condition.data or {}).get("amount") or 0)
    amounts = [str(n) for n in range(1, amount + 1)]
    chosen = pick(engine, actor, "force_release_amount", "Kinetic Reservoir", amounts, subject=target,
                  labels={n: f"Expend {n} stored pressure" for n in amounts}, preferred=[str(amount)],
                  trigger=ctx.action.display_name, intent=ctx.intent)
    if not chosen:
        return
    amount = int(chosen[0])
    actor.conditions.pop(iid, None)
    engine._append_event("CONDITION_REMOVED", "passive:" + RESERVOIR, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                         payload={"condition_id": STORED, "instance_id": iid})
    if amount > 0:
        from ..typed_executor import _deal

        note(engine, "passive:" + RESERVOIR, actor, f"Kinetic Reservoir: {amount} stored pressure lands on {target.display_name} as Force damage.",
             (target.entity_id,))
        _deal(ctx, target, amount, "FORCE")


# ------------------------------------------------------------------------------------------------ Mantle, Incarnation, Court
def _force_source(source: Any) -> bool:
    text = str(source or "")
    return "TAL_FORCE_" in text or ".force." in text


def _mantle_once(ctx: Any) -> int:
    actor = ctx.actor
    if not _active(actor, MANTLE) or not _force_source(ctx.source) or actor.turn_flags.get("force_mantle_bonus"):
        return 0
    actor.turn_flags["force_mantle_bonus"] = True
    return pb_of(ctx.engine, actor)


@hook("damage_roll_bonus")
def mantle_damage(ctx: Any, effect_row: dict[str, Any] | None, kinds: list[str]) -> int | None:
    """Force Mantle: "once per turn, add your Proficiency Bonus to one Force or Bludgeoning damage roll caused by one of your Force
    talents" (a save or area damage roll)."""
    if effect_row is None or effect_row.get("weapon_damage") or not {"FORCE", "BLUDGEONING"} & {str(kind).upper() for kind in kinds or ()}:
        return None
    return _mantle_once(ctx) or None


@hook("attack_damage")
def force_attack_damage(ctx: Any, dice: Any) -> Any | None:
    """Impact's attack: World-Bracing Incarnation's 6d10, and Force Mantle's once-a-turn +PB."""
    from ..gate2_runtime_models import DiceSpec

    if not isinstance(dice, DiceSpec) or IMPACT not in str(ctx.source):
        return None
    new = dice
    if _active(ctx.actor, BRACING):
        new = DiceSpec(count=6, sides=10, modifier=new.modifier)  # "increase Impact damage to 6d10 Force or Bludgeoning damage"
    bonus = _mantle_once(ctx)
    if bonus:
        new = DiceSpec(count=new.count, sides=new.sides, modifier=new.modifier + bonus)
    return new if new is not dice else None


@effect("force_incarnation_push")
def incarnation_push(ctx: Any, eff: dict[str, Any]) -> None:
    """World-Bracing Incarnation: "increase the push caused by Impact by 10 feet" -- the push goes on, directly away from the origin."""
    from ..typed_executor import _push

    from .force_second_pass import allows_impact_push
    target = ctx.target
    if target is None or not target.active or not _active(ctx.actor, BRACING) or not within_limit(ctx.engine, ctx.actor, target) or not allows_impact_push(ctx, target):
        return
    _push(ctx, target, int(eff.get("distance_ft") or 10), pull=False, centred=bool(ctx.typed.get("_area_centre")))


@hook("technique_used")
def free_pressure_step(ctx: Any) -> None:
    """World-Bracing Incarnation / Court of the Answering World: "use Pressure Step once per turn without spending CP"."""
    actor = ctx.actor
    if PRESSURE_STEP not in str(ctx.source) or actor.turn_flags.get("force_free_step"):
        return
    why = "World-Bracing Incarnation" if _active(actor, BRACING) else "Court of the Answering World" if _court_zone(ctx.engine, actor) else None
    if why:
        actor.turn_flags["force_free_step"] = True
        _refund(ctx.engine, actor, f"{why}: Pressure Step without spending CP")


@hook("after_miss")
def court_ally_step(ctx: Any, target: Any) -> None:
    """Court of the Answering World: "After a hostile creature misses an ally with a melee attack, that ally may move 5 feet without
    provoking opportunity attacks." (An ally of the Court's owner standing in the Court; the step is the ally's choice.)"""
    engine = ctx.engine
    if target is None or not target.active or ctx.actor.team_id == target.team_id or ctx.typed.get("range_ft"):
        return
    owner = next((other for other in engine.state.actors.values() if other.active and other.team_id == target.team_id
                  and other.entity_id != target.entity_id and _court_zone(engine, other) is not None
                  and any((c.x, c.y) == (target.position.x, target.position.y) for c in _court_zone(engine, other).affected_cells)), None)
    if owner is None:
        return
    from .needle import CHOICE, ask, checkpoint_id, free_cells, position_of, step_to, cell_options as _cell_options, cell_id as _cell_id

    cells = {cell: cost for cell, cost in free_cells(engine, target, 5).items()}
    if len(cells) <= 1:
        return
    options, labels = _cell_options(engine, target, cells)
    away = max(cells, key=lambda cell: (engine.grid.distance_ft(ctx.actor.position, cell), -cell.y, -cell.x))
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "COURT_STEP", target.entity_id, ctx.actor.entity_id), target, CHOICE + "force_court_step",
                 options, labels=labels, preferred=[_cell_id(away)], allow_decline=True,
                 prompt=f"Court of the Answering World: {ctx.action.display_name} by {ctx.actor.display_name} misses {target.display_name}; step 5 feet?",
                 target_id=target.entity_id)
    if picked and picked[0] != _cell_id(target.position):
        step_to(engine, target, position_of(picked[0]), f"passive:{COURT}")
        note(engine, f"passive:{COURT}", target, f"Court of the Answering World: {target.display_name} steps away.")


@hook("compile_block")
def force_block(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    return [{**row, "block": "force", "kind": spec.get("kind")}] if block == "force" else None


# ------------------------------------------------------------------------------------------------ Impact's augments and fields
def _walk(rows: Any):
    for row in rows or []:
        if isinstance(row, dict):
            yield row
            for key in ("on_hit", "on_miss", "on_fail", "on_success", "effects"):
                yield from _walk(row.get(key))


@effect("force_marker")
def marker(ctx: Any, eff: dict[str, Any]) -> None:
    """An augment the user took for this Impact (Hammerfall, Cascading Collision): read by the collision hook below; runs nothing."""
    return None


def _once_on(ctx: Any, name: str, creature: Any) -> bool:
    key = f"force_once:{name}:{creature.entity_id}"
    if ctx.actor.turn_flags.get(key):
        return False
    ctx.actor.turn_flags[key] = True
    return True


@hook("collision")
def impact_collisions(ctx: Any, target: Any, blocked_at: Any, remaining_ft: int) -> None:
    """Hammerfall: "If the target collides with a solid surface before completing that movement, it takes additional Bludgeoning damage
    equal to your Proficiency Bonus ... only once per turn." Cascading Collision: "When Impact pushes a creature into another
    creature, both creatures make Strength saving throws. Failed Save: Take Bludgeoning damage equal to 2d8 + Path key ability
    modifier and fall Prone. Successful Save: Take half damage and remain standing. A creature can take Cascading Collision damage
    only once per turn." A push stopped by a creature is a collision with that creature; by anything else, with a solid surface."""
    from ..typed_executor import Context, _deal, run_effects

    augments = {str(row.get("augment")) for row in _walk((ctx.typed or {}).get("effects")) if row.get("type") == "force_marker"}
    if not augments or target is None or not target.active:
        return
    other = _occupant(ctx.engine, blocked_at) if blocked_at is not None else None
    if other is not None and other.entity_id == target.entity_id:
        other = None
    if other is None and "hammerfall" in augments and _once_on(ctx, "hammerfall", target):
        amount = max(0, pb_of(ctx.engine, ctx.actor) - court_collision_reduction(ctx.engine, target))
        if amount <= 0:
            return
        note(ctx.engine, ctx.source, ctx.actor, f"Hammerfall: {target.display_name} slams into a solid surface.", (target.entity_id,))
        _deal(ctx, target, amount, "BLUDGEONING")
    if other is not None and "cascading_collision" in augments:
        struck = [creature for creature in (target, other) if creature.active and _once_on(ctx, "cascading", creature)]
        if not struck:
            return
        note(ctx.engine, ctx.source, ctx.actor, f"Cascading Collision: {target.display_name} is driven into {other.display_name}.",
             tuple(c.entity_id for c in struck))
        inner = Context(ctx.engine, ctx.actor, ctx.action, ctx.intent, ctx.typed, struck, None, {})
        run_effects(inner, [{"type": "save", "ability": "str",
                             "on_fail": [{"type": "damage", "applies_to": "target", "dice": {"count": 2, "sides": 8}, "formula": "key_ability_modifier",
                                          "damage_types": ["bludgeoning"]}, {"type": "condition", "applies_to": "target", "condition": "prone"}],
                             "on_success": [{"type": "half_damage", "applies_to": "target"}]}])


@effect("force_compression_prone")
def compression_prone(ctx: Any, eff: dict[str, Any]) -> None:
    """Compression Field: "Failed Save: Its Speed is reduced by 10 feet until the start of its next turn. If it already suffers this
    reduction from Compression Field, it also falls Prone." (Checked before this failure's own reduction lands.)"""
    from ..typed_executor import run_effects

    subject = ctx.target
    if subject is None or not subject.active:
        return
    if any(m.target_field == "speed_ft" and m.source_definition_id == ctx.source and int(m.value) < 0 for m in subject.modifiers.values()):
        run_effects(ctx, [{"type": "condition", "applies_to": "target", "condition": "prone"}])

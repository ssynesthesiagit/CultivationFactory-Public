"""Law of Nonexistence (CL18) -- tianxia.subpath.qi.void_touched_cultivator.feature.law_of_nonexistence.

The whole printed record, in one plug-in. Ownership is the foundation's: the
compiled action must carry the family source and the permanent Void Scar
recorded at acquisition (combat/ext/void_touched_cultivator.py), so a character
without the Secret Law gets no action at all and every hook here returns early.

What the duration puts on the user is one real condition
(``condition:typed.void_touched_law_of_nonexistence``) whose own engine-removed
clock is the printed minute. It carries the flight capability (the native
``fly_speed_ft``/``flight_hover`` condition data combat/flight.py reads), the
damage Resistance row (``damage_resistances``; Force, Psychic and Void are not
listed, so the ordinary Resistance pipeline halves everything else and nothing
here invents a defence), and the law's Source CL. Ending it early therefore ends
every derived effect at once: the Hollow Field it placed is removed by the
CONDITION_REMOVED sweep here, and the movement, Opportunity Attack, targeting
and Empty Heart rules below all read this one condition.

The inherited Void Step and Empty Palm are extended through their public
contracts instead of being copied: ``compose_actions`` publishes a 60-foot,
0-Qi Void Step row and three Bonus Action Empty Palm option rows that keep the
inherited typed payload (same ``source``), and the inherited effect code
resolves them unchanged. Hollow Field is reused through its public
``place_field`` helper: a 30-foot sphere centered on and moving with the user,
without Concentration.

Hooks used (all documented in combat/ext/__init__.py):
  compile_action            seal the Scar, the CL gate and the state condition
  compose_actions           the Law's Void Step/Empty Palm rows and Return to Nothing
  candidate_allowed         per-turn/once-per-activation limits and inert guards
  candidate_unavailability  a plain reason beside a veto
  resolution_final          record a Return to Nothing use
  opportunity_allowed       no Opportunity Attack against the user
  pass_through              creatures' spaces are Difficult Terrain
  material_traversal        nonartifact solid material is traversable, as Difficult Terrain
  movement_begin            start one movement's 10 feet of solid-material passage
  movement_attempt          refuse a step past the printed 10 feet per movement
  movement_progress_committed  count the solid material actually crossed
  recipient_allowed         a lower-CL hostile user cannot target the user
  effect_subject_allowed    a lower-CL hostile area cannot include the user when it could be placed elsewhere
  zone_creation_profile     the same exclusion for a lasting area it lays down
  turn_end                  cannot end a turn inside a solid object
  condition_attempt         Empty Heart: no lower-CL compelled Charmed/Captivated state
  forced_movement_attempt   Empty Heart: no lower-CL compulsion that drags the user closer
  event                     derived-state cleanup and stored-object restoration
  status_description        plain words for the law's condition
"""
from __future__ import annotations

from dataclasses import replace
from typing import Any

from . import effect, hook, note

PARENT = "tianxia.subpath.qi.void_touched_cultivator"
PREFIX = PARENT + ".feature."
LAW = PREFIX + "law_of_nonexistence"
EMPTY_PALM = PREFIX + "empty_palm"
VOID_STEP = PREFIX + "void_step"
TIER = 18

LAW_CONDITION = "condition:typed.void_touched_law_of_nonexistence"
SYSTEM_CONDITION = "condition:typed.void_touched_law_suppressed_system"
ABSENT_CONDITION = "condition:typed.spatial_absence"
RETURN_CONDITION = "condition:typed.spatial_return"
NO_REGAIN = "condition:typed.no_cp_regain"
REACTION_DENIED = "condition:typed.reaction_denied"
SUPPRESSED_MANIFESTATION = "condition:typed.void_touched_law_hidden_manifestation"
RETURN_EFFECT = "void_touched_law_return"
ACTIVATE_EFFECT = "void_touched_law_activate"
RETURN_BACK_EFFECT = "void_touched_law_return_back"
MODE = "law_void_passage"
SOLID_FT = 10
SOLID_MATERIALS = ("soil", "stone", "metal", "wood", "ice", "glass", "crystal", "bone",
                   "sand", "snow", "loose earth")
RESISTED = ("ACID", "BLUDGEONING", "COLD", "FIRE", "LIGHTNING", "NECROTIC", "PIERCING",
            "POISON", "RADIANT", "SLASHING", "THUNDER")
AUTHORITY_SENSES = ("truesight", "spiritual_truesight", "spiritual_sense", "qi_sensing")
CP_POOLS = ("resource:core.qi", "resource:core.stamina", "resource:core.resonance")
POOL_NAMES = {"resource:core.qi": "Qi", "resource:core.stamina": "Stamina",
              "resource:core.resonance": "Resonance"}
_COMPELLED = ("charmed", "captivated")


# ------------------------------------------------------------------------------------------------ ownership and state
def _typed(action: Any) -> dict[str, Any]:
    return (getattr(action, "parameters", None) or {}).get("typed") or {}


def _numbers(action: Any) -> dict[str, Any]:
    return _typed(action).get("numbers") or {}


def source_of(action: Any) -> str:
    return str(_typed(action).get("source") or "")


def family_source(action: Any) -> str:
    from .void_touched_cultivator import family_source as source

    return source(action)


def owns(engine: Any, actor: Any) -> bool:
    """The actor owns the acquired record (its sealed action carries the Void Scar)."""
    from .void_touched_cultivator import composed_scar

    for action_id in getattr(actor, "action_ids", ()):
        action = engine.action_catalog.get(action_id)
        if family_source(action) == LAW and composed_scar(action):
            return True
    return False


def law_action(engine: Any, actor: Any) -> Any | None:
    from .void_touched_cultivator import composed_scar

    for action_id in getattr(actor, "action_ids", ()):
        action = engine.action_catalog.get(action_id)
        if family_source(action) == LAW and composed_scar(action):
            return action
    return None


def state(engine: Any, actor: Any) -> Any | None:
    """The law's own live condition on ``actor`` (the whole duration's real state)."""
    if actor is None:
        return None
    for condition in getattr(actor, "conditions", {}).values():
        if condition.condition_id == LAW_CONDITION and (condition.data or {}).get("law_of_nonexistence") == 1:
            return condition
    return None


def active(engine: Any, actor: Any) -> bool:
    return state(engine, actor) is not None


def law_cl(engine: Any, actor: Any) -> int:
    """The user's own Source CL: its sealed compiled numbers, else the number recorded on the state."""
    action = law_action(engine, actor)
    if action is not None and (_numbers(action).get("source_cl") or _numbers(action).get("cl")):
        return action_cl(action)
    condition = state(engine, actor)
    return int(((condition.data or {}) if condition is not None else {}).get("source_cl") or 0)


def _turn(engine: Any, actor: Any) -> str:
    return f"{engine.state.round_number}:{actor.turns_started}"


def _save_dc(engine: Any, actor: Any) -> int:
    from .end_effect import cultivation_dc

    return cultivation_dc(engine, actor) if actor is not None else 10


def action_cl(action: Any) -> int:
    numbers = _numbers(action)
    return int(numbers.get("source_cl") or numbers.get("cl") or 0)


def recorded_cl(action: Any) -> int | None:
    """The effect's own Source CL when the table records one; None for an ordinary, uncultivated effect."""
    numbers = _numbers(action)
    value = numbers.get("source_cl") or numbers.get("cl")
    return int(value) if value else None


def _label() -> str:
    return ("Law of Nonexistence: for 1 minute the user has a Fly Speed of 60 feet and Hover, Resistance to "
            "all damage except Force, Psychic and Void, can move through creatures and nonartifact objects as "
            "Difficult Terrain, crosses up to 10 feet of nonartifact non-Secret solid material in one movement, "
            "provokes no Opportunity Attacks, and lower-Source-CL hostile effects cannot target it.")


# ------------------------------------------------------------------------------------------------ admission and compilation
@hook("compile_action")
def compile_law(action: Any, info: dict[str, Any]) -> Any:
    """Seal the printed activation onto the acquired action, or leave it inert without the Scar."""
    from character_creation.acquisition_choices import recorded

    if family_source(action) != LAW:
        return None
    typed = dict(_typed(action))
    scar = str(typed.get("void_scar") or recorded(info.get("owner_sheet") or {}, PARENT).get("void_scar") or "")
    typed["min_cl"] = TIER
    if not scar:
        typed.update(void_scar="", effects=[], zone_spec=None)
        typed["riders"] = [*(typed.get("riders") or []),
                           "Acquire the Void-Touched Cultivator Secret Law through your Path progression to use this feature."]
        return action.model_copy(update={"parameters": {**action.parameters, "typed": typed, "inert": True}})
    typed["void_scar"] = scar
    numbers = dict(typed.get("numbers") or {})
    cl = int(numbers.get("source_cl") or numbers.get("cl") or TIER)
    effects = []
    for row in typed.get("effects") or []:
        if not isinstance(row, dict):
            continue
        if row.get("type") == "condition" and row.get("condition") == LAW_CONDITION:
            data = dict(row.get("condition_data") or {})
            data.update(law_of_nonexistence=1, source_cl=cl, return_used=0,
                        label=_label(), rule={"damage_resistances": list(RESISTED)})
            row = {**row, "condition_data": data}
        effects.append(row)
    typed["effects"] = effects
    typed["duration"] = {"kind": "minutes", "amount": 1, "concentration": False}
    typed.setdefault("riders", [])
    return action.model_copy(update={"target_kind": "SELF", "range_ft": None,
                                     "parameters": {**action.parameters, "typed": typed}})


@hook("compose_actions")
def compose_law_rows(info: dict[str, Any]) -> list[Any] | None:
    """Publish the Law's own rows, all reusing the inherited payloads unchanged."""
    from character_creation.acquisition_choices import recorded
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    from .void_touched_cultivator import composed_scar

    scar = recorded(info.get("owner_sheet") or {}, PARENT).get("void_scar") or ""
    if not scar:
        return None
    out: list[Any] = []
    actions = list(info.get("actions") or ())
    for action in actions:
        typed = _typed(action)
        source = family_source(action)
        if source == VOID_STEP and composed_scar(action):
            typed = dict(typed)
            typed["range_ft"] = 60
            typed["law_void_step"] = 1
            effects = []
            for row in typed.get("effects") or []:
                if isinstance(row, dict) and row.get("type") in ("teleport", "movement"):
                    row = {**row, "distance_ft": 60}
                effects.append(row)
            typed["effects"] = effects
            out.append(action.model_copy(update={
                "source_definition_id": action.source_definition_id + "#law_of_nonexistence",
                "display_name": "Void Step (Law of Nonexistence: 0 Qi, 60 feet)",
                "range_ft": 60, "costs": (),
                "parameters": {**action.parameters, "typed": typed, "law_void_step": True}}))
        elif source == EMPTY_PALM and composed_scar(action):
            typed = dict(typed)
            typed["law_empty_palm"] = 1
            option = str(typed.get("option_label") or "")
            out.append(action.model_copy(update={
                "source_definition_id": action.source_definition_id + "#law_of_nonexistence",
                "display_name": (f"{action.display_name} as a Bonus Action (Law of Nonexistence)"
                                 if not option else f"Empty Palm (Bonus Action) — {option}"),
                "economy": EconomyKind.BONUS_ACTION,
                "parameters": {**action.parameters, "typed": typed, "law_empty_palm": True}}))
    numbers = {}
    law_source = ""
    for action in actions:
        if family_source(action) == LAW and composed_scar(action):
            numbers = dict(_numbers(action))
            law_source = action.source_definition_id
            break
    if not law_source:
        return out or None
    out.append(ActionDefinition(
        source_definition_id=law_source + "#return_to_nothing",
        display_name="Return to Nothing (Law of Nonexistence)",
        owner_id=info["actor_id"], economy=EconomyKind.NONE, resolution_kind="TYPED",
        target_kind="CELL", range_ft=60, costs=(),
        parameters={"any_cell": True, "law_return": True, "ai_allow_empty_area": True, "ai_empty_area_filter": False,
                    "typed": {"source": LAW, "law_return": 1, "void_scar": scar, "numbers": numbers,
                              "duration": {"kind": "instant"}, "min_cl": TIER, "riders": [],
                              "effects": [{"type": RETURN_EFFECT, "applies_to": "target",
                                           "evidence": ("Once during the activation choose one creature bearing three of "
                                                        "your Void Marks, Cultivation Asset, active manifestation or object "
                                                        "within 60 feet")}]},
                    "expected_damage": 0}))
    return out


_UNSET = object()


@hook("candidate_allowed")
def law_entry(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    """Owned rows are offered only under their printed conditions; unowned rows stay untouched."""
    if action is None:
        return None
    params = action.parameters or {}
    typed = _typed(action)
    source = family_source(action)
    if source == LAW:
        if params.get("law_return"):
            held = state(engine, actor)
            return bool(held is not None and int((held.data or {}).get("return_used") or 0) == 0
                        and _return_candidates(engine, actor, getattr(candidate, "destination", None)))
        return None
    if params.get("law_void_step"):
        if state(engine, actor) is None:
            return False
        return None
    if source == VOID_STEP and state(engine, actor) is not None:
        return False  # the Law's own row replaces the printed 2 Qi/30 feet terms for the duration
    if params.get("law_empty_palm"):
        if state(engine, actor) is None:
            return False
        return False if actor.turn_flags.get("_law_empty_palm_turn") == _turn(engine, actor) else None
    return None


@hook("candidate_unavailability")
def law_reason(engine: Any, actor: Any, candidate: Any, action: Any) -> str | None:
    if action is None:
        return None
    params = action.parameters or {}
    if params.get("law_return"):
        held = state(engine, actor)
        if held is None:
            return "Return to Nothing is available only while Law of Nonexistence is active."
        if int((held.data or {}).get("return_used") or 0):
            return "Return to Nothing has already been used during this activation (limit: once)."
        if not _return_candidates(engine, actor, getattr(candidate, "destination", None)):
            return ("Return to Nothing needs a creature bearing three of your Void Marks, a Cultivation Asset, an "
                    "active manifestation, or an object in that space within 60 feet.")
    if params.get("law_empty_palm") and state(engine, actor) is not None \
            and actor.turn_flags.get("_law_empty_palm_turn") == _turn(engine, actor):
        return "Empty Palm has already been used as a Bonus Action this turn (limit: once per turn)."
    if params.get("law_void_step") and state(engine, actor) is None:
        return "The 0-Qi, 60-foot Void Step is available only while Law of Nonexistence is active."
    return None


@hook("resolution_final")
def record_law_use(engine: Any, actor: Any, action: Any, candidate: Any, intent: Any) -> None:
    if actor is None or action is None:
        return
    params = action.parameters or {}
    if params.get("law_empty_palm") and state(engine, actor) is not None:
        actor.turn_flags["_law_empty_palm_turn"] = _turn(engine, actor)
    elif params.get("law_return") and state(engine, actor) is not None:
        held = state(engine, actor)
        engine._update_condition_data(actor, held, {**(held.data or {}), "return_used": 1},
                                      action.source_definition_id)


# ------------------------------------------------------------------------------------------------ the duration's self-state
def _activate(ctx: Any) -> None:
    """Place the moving Hollow Field the printed duration carries."""
    engine, user = ctx.engine, ctx.actor
    from . import void_touched_hollow_field as hollow

    hollow.place_field(engine, user, ctx.source, dict(ctx.numbers), radius_ft=30, concentration=False,
                       centered_on_self=True, follows_owner=True)
    note(engine, ctx.source, user,
         f"{user.display_name} partially withdraws from reality: Fly Speed 60 feet and Hover, Resistance to all "
         "damage except Force, Psychic and Void, movement through creatures and nonartifact objects as Difficult "
         "Terrain, up to 10 feet of solid material crossed per movement, no Opportunity Attacks, a 30-foot Hollow "
         "Field that moves with it without Concentration, and lower-Source-CL hostile effects cannot target it. "
         "Duration: 1 minute.")


@effect(ACTIVATE_EFFECT)
def activate(ctx: Any, row: dict[str, Any]) -> None:
    if not owns(ctx.engine, ctx.actor):
        return
    _activate(ctx)


@hook("opportunity_allowed")
def law_no_opportunity_attack(engine: Any, reactor: Any, mover: Any) -> bool | None:
    """Nobody may make an Opportunity Attack against the user while the Law is active."""
    return False if active(engine, mover) else None


@hook("pass_through")
def law_creature_passage(engine: Any, mover: Any, occupant: Any) -> str | None:
    """Creatures' spaces are Difficult Terrain for the user; a creature is never a legal stop."""
    return "difficult" if active(engine, mover) else None


@hook("material_traversal")
def law_solid_passage(engine: Any, actor: Any) -> dict[str, Any] | None:
    """Nonartifact solid material as Difficult Terrain. Sealed matter stays blocking (terrain_materials)."""
    if not active(engine, actor):
        return None
    return {"mode": MODE, "materials": SOLID_MATERIALS, "difficult_materials": SOLID_MATERIALS}


def _solid_cells(engine: Any, actor: Any, position: Any) -> list[tuple[int, int, int]]:
    cells = []
    for cell in engine._actor_volume(actor, position):
        if engine.grid.terrain_at(cell, "BLOCKED"):
            cells.append(cell)
    return cells


def _solid_key(actor: Any) -> str:
    return f"_law_solid_ft:{actor.entity_id}"


@hook("movement_begin")
def law_begin_movement(engine: Any, mover: Any, candidate: Any, intent: Any, granted_ft: Any) -> None:
    if active(engine, mover):
        engine.__dict__[_solid_key(mover)] = 0


@hook("movement_attempt")
def law_solid_limit(engine: Any, mover: Any, previous: Any, next: Any, intent: Any) -> dict[str, Any] | None:
    """The printed 10 feet of solid material per movement, checked before the step is paid for."""
    if not active(engine, mover):
        return None
    enter = len(_solid_cells(engine, mover, next))
    if not enter:
        return None
    used = int(engine.__dict__.get(_solid_key(mover)) or 0)
    if used + enter * engine.grid.square_size_ft > SOLID_FT:
        return {"stop": True, "source_id": LAW,
                "label": ("Law of Nonexistence: it can pass through only 10 feet of solid material during one "
                          "movement, so the move stops here.")}
    return None


@hook("movement_landed")
def law_count_solid(engine: Any, mover: Any, previous: Any, destination: Any, intent: Any, forced: Any) -> None:
    """Count the solid material the mover has actually crossed this movement (5 feet per occupied cell)."""
    if not active(engine, mover):
        return
    cells = _solid_cells(engine, mover, destination)
    if not cells:
        return
    engine.__dict__[_solid_key(mover)] = int(engine.__dict__.get(_solid_key(mover)) or 0) + (
        len(cells) * engine.grid.square_size_ft)


# ------------------------------------------------------------------------------------------------ targeting protection
def _perceives_authority(engine: Any, viewer: Any, seen: Any) -> bool:
    """Void, Secret, Truesight, conceptual or equivalent authority (the senses this table keeps)."""
    from .. import senses

    for sense in AUTHORITY_SENSES:
        reach = senses.reach(engine, viewer, sense, seen)
        if reach > 0 and engine._distance_actor_to_actor(viewer, seen) <= reach:
            return True
    return False


def _harmful(action: Any) -> bool:
    kind = str(getattr(action, "target_kind", "") or "")
    return kind in {"HOSTILE_ENTITY", "HOSTILE_ENTITY_OR_SELF"} or (action.parameters or {}).get("harmful") is True


def _protected_target(engine: Any, actor: Any, target: Any, action: Any) -> bool:
    if action is None or target is None or actor is None or actor.entity_id == target.entity_id:
        return False
    if not active(engine, target) or actor.team_id == target.team_id or not _harmful(action):
        return False
    theirs = recorded_cl(action)
    if theirs is None or theirs >= law_cl(engine, target):
        return False
    return not _perceives_authority(engine, actor, target)


@hook("recipient_allowed")
def law_untargetable(engine: Any, actor: Any, target: Any, action: Any) -> bool | None:
    """A lower-Source-CL hostile effect cannot target the user without authority perception."""
    if not _protected_target(engine, actor, target, action):
        return None
    return False


def _shape_cells(engine: Any, center: Any, shape: dict[str, Any]) -> tuple[Any, ...]:
    from .. import zones

    return zones._cells(engine, center, {"shape": shape.get("shape") or "sphere",
                                         "size_ft": shape.get("size_ft"),
                                         **({"spreads": shape["spreads"]} if shape.get("spreads") else {})})


def _area_can_exclude(engine: Any, caster: Any, subject: Any, shape: dict[str, Any], reach_ft: int) -> bool:
    """Another legal placement of the same shape, within the caster's range, leaves the user's space out."""
    from ..gate2_runtime_models import Position

    if not shape.get("size_ft"):
        return False
    filled = {(cell[0], cell[1]) for cell in engine._actor_volume(subject, subject.position)}
    origin = caster.position
    span = max(1, int(reach_ft or 0) // engine.grid.square_size_ft)
    for dy in range(-span, span + 1):
        for dx in range(-span, span + 1):
            if not (0 <= origin.x + dx < engine.grid.width and 0 <= origin.y + dy < engine.grid.height):
                continue
            center = Position(x=origin.x + dx, y=origin.y + dy, z=origin.z)
            if engine.grid.distance_ft(origin, center) > int(reach_ft or 0):
                continue
            if not engine.grid.placement_legal(center, footprint=engine._footprint(caster),
                                               occupied_cells=engine._occupied_cells_except(caster.entity_id)):
                continue
            cells = {(cell[0], cell[1]) if not hasattr(cell, 'x') else (cell.x, cell.y)
                     for cell in _shape_cells(engine, center, shape)}
            if cells and not (cells & filled):
                return True
    return False


@hook("effect_subject_allowed")
def law_area_excludes_user(ctx: Any, row: dict[str, Any], subject: Any) -> bool | None:
    """A lower-CL hostile area effect cannot include the user when it could have been placed to exclude it."""
    engine, actor = ctx.engine, ctx.actor
    if subject is None or actor is None or subject.entity_id == actor.entity_id:
        return None
    if not active(engine, subject) or actor.team_id == subject.team_id:
        return None
    theirs = recorded_cl(ctx.action)
    if theirs is None or theirs >= law_cl(engine, subject):
        return None
    if _perceives_authority(engine, actor, subject):
        return None
    shape = (ctx.typed or {}).get("area") or {}
    if not shape.get("size_ft"):
        return None  # a single-target effect is the recipient_allowed contract's
    if _area_can_exclude(engine, actor, subject, shape, int(getattr(ctx.action, "range_ft", 0) or 0)):
        return False
    return None


@hook("zone_creation_profile")
def law_zone_excludes_user(zone: Any, ctx: Any) -> Any | None:
    """The same exclusion for a lasting lower-CL hostile area: a legal placement without the user wins."""
    engine = ctx.engine
    owner = engine.state.actors.get(zone.owner_id)
    if owner is None or not zone.affected_cells:
        return None
    theirs = recorded_cl(ctx.action)
    if theirs is None:
        return None
    profile = zone.trigger_profile or {}
    shape = {"shape": profile.get("shape") or "sphere", "size_ft": profile.get("size_ft")}
    covered = {(cell.x, cell.y) for cell in zone.affected_cells}
    filled: set[tuple[int, int]] = set()
    for subject in sorted(engine.state.actors.values(), key=lambda row: row.entity_id):
        if not subject.active or subject.team_id == owner.team_id or not active(engine, subject):
            continue
        if theirs >= law_cl(engine, subject) or _perceives_authority(engine, owner, subject):
            continue
        held = {(cell[0], cell[1]) for cell in engine._actor_volume(subject, subject.position)}
        if not (covered & held):
            continue
        if not _area_can_exclude(engine, owner, subject, shape, int(getattr(ctx.action, "range_ft", 0) or 0)):
            continue
        filled |= held
        note(engine, zone.source_definition_id, owner,
             f"{owner.display_name}'s {zone.source_definition_id.rsplit('.', 1)[-1].replace('_', ' ')} does not "
             f"include {subject.display_name}: its Source CL {theirs} is lower than {subject.display_name}'s, and the "
             "area could have been placed to exclude them.", (subject,))
    if not filled:
        return None
    kept = tuple(cell for cell in zone.affected_cells if (cell.x, cell.y) not in filled)
    if len(kept) == len(zone.affected_cells):
        return None
    return zone.model_copy(update={"affected_cells": kept})


# ------------------------------------------------------------------------------------------------ cannot end a turn inside a solid object
@hook("turn_end")
def law_solid_turn_end(engine: Any, actor: Any) -> None:
    """Move to the nearest legal space and take the irreducible 5d10 Force damage."""
    if not active(engine, actor):
        return
    position = actor.position
    if not _solid_cells(engine, actor, position):
        return
    from ..gate2_runtime_models import Position
    from ..typed_executor import Context, run_effects

    occupied = engine._occupied_cells_except(actor.entity_id)
    legal = []
    for y in range(engine.grid.height):
        for x in range(engine.grid.width):
            cell = Position(x=x, y=y, z=position.z)
            if engine.grid.placement_legal(cell, footprint=engine._footprint(actor), occupied_cells=occupied):
                legal.append(cell)
    if not legal:
        engine._append_event("PASSIVE_TRIGGERED", LAW, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                             payload={"log": (f"Law of Nonexistence: {actor.display_name} would end its turn inside "
                                              "solid material and no legal space is free; the table must place it.")})
        return
    destination = min(legal, key=lambda cell: (engine.grid.distance_ft(position, cell), cell.y, cell.x))
    actor.position = destination
    engine._append_event("MOVEMENT_COMMITTED", LAW, actor_id=actor.entity_id,
                         payload={"destination": destination.model_dump(mode="json"),
                                  "path": [position.model_dump(mode="json"), destination.model_dump(mode="json")],
                                  "cost_ft": 0, "teleport": True})
    from ..zones import on_moved, sync_inside

    sync_inside(engine, LAW)
    on_moved(engine, actor, position, destination, forced=True)
    action = law_action(engine, actor)
    if action is None:
        return
    ctx = Context(engine, actor, action, getattr(engine, "_active_intent", None),
                  {"numbers": dict(_numbers(action)), "duration": {"kind": "instant"},
                   "effects": [], "riders": []}, [actor], actor, {})
    note(engine, LAW, actor,
         f"Law of Nonexistence: {actor.display_name} cannot end its turn inside a solid object, so it moves to the "
         f"nearest legal space and takes 5d10 Force damage (not reduced by this Secret Law).", (actor,))
    run_effects(ctx, [{"type": "damage", "applies_to": "self", "dice": {"count": 5, "sides": 10},
                       "formula": "none", "damage_types": ["force"], "duration": "instant",
                       "evidence": "Take 5d10 Force damage that cannot be reduced by this Secret Law."}])


# ------------------------------------------------------------------------------------------------ Empty Heart
@hook("condition_attempt")
def law_empty_heart_condition(ctx: Any, subject: Any, row: dict[str, Any] | None) -> bool | None:
    """A lower-Source-CL effect cannot make the user emotionally acknowledge its source."""
    engine, actor = ctx.engine, ctx.actor
    if subject is None or actor is None:
        return None
    if not active(engine, subject):
        return None
    name = str((row or {}).get("condition") or "").lower()
    if name not in _COMPELLED:
        return None
    if actor.team_id == subject.team_id:
        return None
    theirs = recorded_cl(ctx.action)
    if theirs is None or theirs >= law_cl(engine, subject):
        return None
    ctx.rider(f"Law of Nonexistence (Empty Heart): {subject.display_name} cannot be compelled to emotionally "
              f"acknowledge a creature through a lower-Source-CL effect, so {name} does not take hold.")
    return False


@hook("forced_movement_attempt")
def law_empty_heart_approach(engine: Any, mover: Any, previous: Any, next: Any, intent: Any) -> dict[str, Any] | None:
    """A lower-Source-CL compulsion cannot drag the user closer to the creature imposing it."""
    if not active(engine, mover):
        return None
    source_id = str(getattr(engine, "_active_action_source_id", "") or "")
    action = engine.action_catalog.get(source_id)
    active_intent = getattr(engine, "_active_intent", None)
    springer = engine.state.actors.get(str(getattr(active_intent, "actor_id", "") or ""))
    if action is None or springer is None or springer.entity_id == mover.entity_id:
        return None
    theirs = recorded_cl(action)
    if theirs is None or theirs >= law_cl(engine, mover):
        return None
    if engine.grid.distance_ft(springer.position, next) >= engine.grid.distance_ft(springer.position, previous):
        return None
    return {"stop": True, "source_id": LAW,
            "label": (f"Law of Nonexistence (Empty Heart): {mover.display_name} cannot be compelled to approach "
                      f"{springer.display_name} by a lower-Source-CL effect.")}


# ------------------------------------------------------------------------------------------------ Return to Nothing
def _target_cl(engine: Any, actor: Any) -> int:
    from .void_touched_hollow_field import creature_cl

    return creature_cl(engine, actor)


def _return_candidates(engine: Any, user: Any, cell: Any) -> list[dict[str, Any]]:
    """Everything in one space Return to Nothing may name, with its printed eligibility."""
    from .void_touched_cultivator import mark_count

    if cell is None or not active(engine, user):
        return []
    if engine.grid.distance_ft(user.position, cell) > 60:
        return []
    out: list[dict[str, Any]] = []
    for actor in sorted(engine.state.actors.values(), key=lambda row: row.entity_id):
        if not actor.active or actor.entity_id == user.entity_id:
            continue
        if (actor.position.x, actor.position.y) != (cell.x, cell.y):
            continue
        summon = actor.summon or {}
        if summon and summon.get("status") == "present":
            out.append({"kind": "asset", "id": actor.entity_id, "label": f"{actor.display_name} — a Cultivation Asset",
                        "cl": _target_cl(engine, actor), "source": str(summon.get("source") or "")})
            continue
        marks = mark_count(actor, user.entity_id)
        if marks >= 3:
            out.append({"kind": "creature", "id": actor.entity_id,
                        "label": f"{actor.display_name} (bears {marks} of your Void Marks)",
                        "cl": _target_cl(engine, actor)})
    from .. import zones

    for zone in zones.typed_zones(engine):
        if not zone.active or zone.owner_id == user.entity_id:
            continue
        if not any(held.x == cell.x and held.y == cell.y for held in zone.affected_cells):
            continue
        out.append({"kind": "manifestation", "id": zone.zone_id,
                    "label": f"{_manifestation_name(engine, zone)} — an active manifestation",
                    "cl": _zone_cl(zone), "source": str(zone.source_definition_id or ""), "zone": zone})
    for obj in sorted(engine.state.objects.values(), key=lambda row: row.object_id):
        if obj.destroyed or (obj.position.x, obj.position.y) != (cell.x, cell.y):
            continue
        out.append({"kind": "object", "id": obj.object_id,
                    "label": f"{obj.object_kind.replace('_', ' ').title()} — an object",
                    "cl": _object_cl(engine, obj), "source": _object_source(obj), "object": obj})
    return out


def _manifestation_name(engine: Any, zone: Any) -> str:
    from . import ability_source

    return ability_source.source_label(engine, zone.source_definition_id) or "an area"


def _zone_cl(zone: Any) -> int:
    profile = (zone.trigger_profile or {}).get("profile") or {}
    numbers = (zone.trigger_profile or {}).get("numbers") or {}
    return int(profile.get("source_cl") or numbers.get("source_cl") or numbers.get("cl") or 0)


def _object_source(obj: Any) -> str:
    component = obj.component or {}
    return str(component.get("source_definition_id") or component.get("source") or "")


def _object_cl(engine: Any, obj: Any) -> int:
    action = engine.action_catalog.get(_object_source(obj))
    return action_cl(action) if action is not None else 0


def _power(engine: Any, source: str) -> tuple | None:
    from . import source_eligibility

    return source_eligibility.printed_power(engine.action_catalog.get(str(source or "")))


def _protected_item(engine: Any, source: str) -> bool:
    from . import source_eligibility

    power = _power(engine, source)
    return True if power is None else source_eligibility.protected_power(
        *power, extra_categories=("Secret", "Immortal", "artifact", "absolute"))


def _ask(ctx: Any, chooser: Any, name: str, options: list[str], labels: dict[str, str], preferred: list[str],
         prompt: str, *, allow_decline: bool = False) -> list[str]:
    from .needle import ask, checkpoint_id

    intent = ctx.intent if ctx.intent is not None else getattr(ctx.engine, "_active_intent", None)
    return ask(ctx.engine, intent, checkpoint_id(ctx.engine, name, ctx.actor.entity_id, chooser.entity_id),
               chooser, "choice:needle." + name, options, labels=labels, preferred=preferred,
               target_id=chooser.entity_id, prompt=prompt, name="Return to Nothing", allow_decline=allow_decline)


def _player(engine: Any, actor: Any) -> bool:
    from .teleport_steps import player_controls

    return player_controls(engine, actor)


def _cultivation_check(engine: Any, roller: Any, dc: int, label: str) -> bool:
    from . import floored
    from .ability_source import numbers_of

    numbers = numbers_of(engine, roller)
    bonus = int(numbers.get("pb") or getattr(roller, "proficiency_bonus", 0) or 0) + int(numbers.get("key_mod") or 0)
    roll = engine.roll_check(modifier=bonus, actor_id=roller.entity_id, reason=f"CHECK:{LAW}:{label}")
    engine._record_roll(roll)
    roll = floored(engine, roller, roll, dc)
    success = int(roll.total) >= dc
    engine._append_event("CHECK_ROLLED", LAW, actor_id=roller.entity_id, target_ids=(roller.entity_id,),
                         payload={"actor": roll.model_dump(mode="json"), "dc": dc, "success": success,
                                  "skill": "Cultivation Check", "effect": label})
    return success


def _expiry_for_band(engine: Any, user: Any, target: Any) -> tuple[str, bool, bool]:
    """(expiry name, repeat at the end of each of its turns, requires the user's Cultivation Check)."""
    from ..typed_executor import clock_expiry
    from .effect_durations import token

    band = _target_cl(engine, target) - law_cl(engine, user)
    if band >= 3:
        return token("start", user.entity_id, int(user.turns_started) + 1), False, True
    if band >= -2:
        return token("end", user.entity_id, int(user.turns_started) + 1), True, False
    if band >= -5:
        return clock_expiry(engine, "minutes", 1), False, False
    return "UNTIL_REMOVED", False, False


def _duration_words(engine: Any, user: Any, target: Any, expiry: str, repeat: bool) -> str:
    band = _target_cl(engine, target) - law_cl(engine, user)
    if band >= 3:
        return "until the start of your next turn"
    if band >= -2:
        return ("until the end of your next turn, with a Cultivation Check against your save DC at the end of "
                "each of its turns in the interval")
    if band >= -5:
        return "1 minute (no automatic repeat)"
    return "indefinitely, until released, rescued or restored by equal or higher authority"


def _system_choices(engine: Any, target: Any) -> list[dict[str, Any]]:
    from .void_touched_hollow_field import systems

    return systems(engine, target)


def _suppress_system(ctx: Any, target: Any, *, expires_on: str, when: str) -> None:
    """Suppress one active cultivation system through the inherited suppression contracts."""
    from .void_touched_hollow_field import take_system_rows

    engine, user = ctx.engine, ctx.actor
    options = _system_choices(engine, target)
    if not options:
        note(engine, ctx.source, user,
             f"Return to Nothing: {target.display_name} carries no cultivation system this table can suppress.",
             (target,))
        return
    keys = [row["kind"] + "|" + row["value"] for row in options]
    labels = {row["kind"] + "|" + row["value"]: row["label"] for row in options}
    chosen = keys[0]
    if _player(engine, user):
        answer = _ask(ctx, user, "law_system", keys, labels, keys[:1],
                      (f"Return to Nothing: choose one active cultivation system of {target.display_name} to "
                       f"suppress {when}. Its other systems keep working."))
        chosen = answer[0] if answer and answer[0] in labels else keys[0]
    picked = next(item for item in options if item["kind"] + "|" + item["value"] == chosen)
    rows = take_system_rows(engine, target, picked["kind"], picked["value"])
    data = {"kind": picked["kind"], "value": picked["value"], "rows": rows, "until": expires_on,
            "label": (f"Return to Nothing: {target.display_name}'s {picked['label']} is suppressed {when}."),
            "source_cl": law_cl(engine, user), "owner": user.entity_id}
    engine._apply_condition(target, SYSTEM_CONDITION, ctx.source, user.entity_id, expires_on=expires_on, data=data)
    note(engine, ctx.source, user, data["label"], (target,))


def _suppression_due(engine: Any, condition: Any, checkpoint: str, ending_id: str | None) -> bool:
    from .effect_durations import engine_due

    until = str((condition.data or {}).get("until") or "")
    if not until or until == "UNTIL_REMOVED":
        return False
    return engine_due(engine, until, checkpoint, source_id=condition.source_definition_id,
                      holder_id=condition.source_actor_id, ending_id=ending_id)


def _release_suppressions(engine: Any, checkpoint: str, actor: Any | None = None) -> None:
    """Restore a system's or an object's functions when its printed deadline comes due."""
    from . import note as _note
    from .void_touched_hollow_field import give_back_system_rows

    ending = actor.entity_id if (checkpoint == "END_OF_TURN" and actor is not None) else None
    for holder in list(engine.state.actors.values()):
        for instance_id, condition in list(holder.conditions.items()):
            if condition.condition_id != SYSTEM_CONDITION:
                continue
            if not _suppression_due(engine, condition, checkpoint, ending):
                continue
            give_back_system_rows(engine, holder, condition.data or {})
            engine._remove_condition_instance(holder, instance_id, LAW, expected=condition,
                                              payload={"condition_id": SYSTEM_CONDITION,
                                                       "instance_id": instance_id, "reason": "DEADLINE"})
            user = engine.state.actors.get(str((condition.data or {}).get("owner") or ""))
            if user is not None:
                _note(engine, LAW, user, f"Return to Nothing: {holder.display_name}'s suppressed system is no "
                                         f"longer suppressed.", (holder,))
    from .effect_durations import engine_due

    for obj in list(engine.state.objects.values()):
        until = str((obj.component or {}).get("law_suppressed_until") or "")
        if not obj.suppressed or not until:
            continue
        if not engine_due(engine, until, checkpoint, ending_id=ending):
            continue
        component = dict(obj.component or {})
        component.pop("law_suppressed_until", None)
        engine._update_object(obj.model_copy(update={"suppressed": False, "component": component}), LAW, None)


@hook("turn_boundary_start")
def law_suppression_start_boundary(engine: Any, actor: Any) -> None:
    _release_suppressions(engine, "START_OF_TURN", actor)


@hook("candidate_allowed")
def law_suppressed_system_candidates(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    """A suppressed system's own actions are not offered while the record lasts."""
    if action is None:
        return None
    from .void_touched_hollow_field import covers, sphere_of_mechanic

    typed = _typed(action)
    source = str(typed.get("source") or "")
    sphere = str(typed.get("sphere") or "") or sphere_of_mechanic(source)
    if not source and not sphere:
        return None
    for condition in actor.conditions.values():
        if condition.condition_id != SYSTEM_CONDITION:
            continue
        data = condition.data or {}
        if covers({"kind": data.get("kind"), "value": data.get("value")}, source, sphere):
            return False
    return None


@hook("row_allowed")
def law_suppressed_system_rows(engine: Any, actor: Any, row: dict[str, Any]) -> bool | None:
    from .void_touched_hollow_field import covers, sphere_of_mechanic

    source = str(row.get("feature_id") or "")
    sphere = str(row.get("sphere") or "") or sphere_of_mechanic(source)
    for condition in actor.conditions.values():
        if condition.condition_id != SYSTEM_CONDITION:
            continue
        data = condition.data or {}
        if covers({"kind": data.get("kind"), "value": data.get("value")}, source, sphere):
            return False
    return None


def _end_non_secret_manifestations(engine: Any, user: Any, target: Any, source: str) -> None:
    """Its active non-Secret manifestations outside the interval end."""
    from .. import summons
    from . import source_eligibility

    if target.concentration is not None:
        held = target.concentration
        action = engine.action_catalog.get(str(held.source_definition_id or ""))
        power = source_eligibility.printed_power(action)
        if power is None or not source_eligibility.protected_power(*power, extra_categories=("Secret", "Immortal", "absolute")):
            engine._end_concentration(target, "RETURN_TO_NOTHING")
    for asset in list(engine.state.actors.values()):
        record = asset.summon or {}
        if asset.entity_id == target.entity_id or record.get("owner") != target.entity_id \
                or record.get("status") != "present":
            continue
        power = source_eligibility.printed_power(engine.action_catalog.get(str(record.get("source") or "")))
        if power is None or not source_eligibility.protected_power(*power, extra_categories=("Secret", "Immortal", "absolute")):
            summons.dismiss(engine, asset, "RETURN_TO_NOTHING",
                            log=f"Return to Nothing: {asset.display_name}, a manifestation of {target.display_name}, ends.")


def _creature_failed(ctx: Any, target: Any) -> None:
    from ..typed_executor import run_effects

    engine, user = ctx.engine, ctx.actor
    expiry, repeat, needs_check = _expiry_for_band(engine, user, target)
    if needs_check and not _cultivation_check(engine, user, _save_dc(engine, target),
                                              "Return to Nothing (higher CL)"):
        note(engine, ctx.source, user,
             f"Return to Nothing: {target.display_name} is 3 or more Cultivation Levels higher, and your Cultivation "
             f"Check against its save DC fails, so it is not removed from reality.", (target,))
        return
    _end_non_secret_manifestations(engine, user, target, ctx.source)
    dc = int(ctx.numbers.get("save_dc") or 10)
    words = _duration_words(engine, user, target, expiry, repeat)
    label = (f"Return to Nothing: {target.display_name} is removed from ordinary reality into a featureless Void "
             f"interval {words}. It is Incapacitated relative to the outside world, cannot perceive or affect it, "
             "cannot be perceived or affected except through equal or higher Void, Secret, conceptual, Samsara or "
             "explicit interstitial authority, cannot regain Cultivation Points, and its durations keep passing.")
    own = replace(ctx, targets=[target], target=target)
    run_effects(own, [{"type": "spatial_absence", "applies_to": "target", "incapacitated": True,
                       "expires_on": expiry, "label": label,
                       "evidence": ("removed from ordinary reality and placed in a featureless Void interval; "
                                    "while removed it is Incapacitated relative to the outside world, cannot "
                                    "perceive or affect it, cannot regain Cultivation Points, and its durations "
                                    "continue to pass"),
                       "on_return": [{"type": RETURN_BACK_EFFECT, "applies_to": "target",
                                      "evidence": ("When it returns: it appears in the nearest legal space to its "
                                                   "departure point, its current Cultivation Points become 0, and "
                                                   "one active cultivation system remains suppressed until the end "
                                                   "of its next turn")}]}])
    held = next((c for c in target.conditions.values() if c.condition_id == ABSENT_CONDITION), None)
    if held is not None:
        engine._update_condition_data(target, held, {
            **(held.data or {}), "law_repeat_dc": dc, "law_repeat_check": 1 if repeat else 0,
            "law_owner": user.entity_id, "law_label": label}, ctx.source)
        engine._apply_condition(target, NO_REGAIN, ctx.source, user.entity_id, expires_on=expiry,
                                data={"label": (f"Return to Nothing: {target.display_name} cannot regain Cultivation "
                                                f"Points {_duration_words(engine, user, target, expiry, repeat)}."),
                                      "source_cl": law_cl(engine, user)})
    note(engine, ctx.source, user,
         f"Return to Nothing: {target.display_name} fails its Charisma save and is removed into a Void interval "
         f"{words}. Its active non-Secret manifestations end; its durations keep passing.", (target,))


def _creature_saved(ctx: Any, target: Any) -> None:
    from ..typed_executor import run_effects

    engine, user = ctx.engine, ctx.actor
    pb = int(ctx.numbers.get("pb") or 0)
    from .effect_durations import holder_next_turn, token

    run_effects(replace(ctx, targets=[target], target=target),
                [{"type": "damage", "applies_to": "target", "dice": {"count": 6, "sides": 8},
                  "formula": "none", "damage_types": ["void"], "duration": "instant",
                  "evidence": "Take 6d8 Void damage."}])
    take = 2 * pb
    for pool in CP_POOLS:
        if take <= 0:
            break
        held = int(target.resources.get(pool) or 0)
        amount = min(take, held)
        if amount:
            engine._spend_resource(target, pool, amount, ctx.source)
            take -= amount
    engine._apply_condition(target, REACTION_DENIED, ctx.source, user.entity_id,
                            expires_on=holder_next_turn(target, "start"),
                            data={"label": (f"Return to Nothing: {target.display_name} cannot take Reactions until "
                                            "the start of its next turn.")})
    _suppress_system(ctx, target, expires_on=holder_next_turn(target, "start"),
                     when="until the start of its next turn")
    note(engine, ctx.source, user,
         f"Return to Nothing: {target.display_name} succeeds on its Charisma save: it takes 6d8 Void damage, loses "
         f"Cultivation Points equal to twice your Proficiency Bonus ({2 * pb}), cannot take Reactions until the start "
         "of its next turn, and one of its cultivation systems is suppressed until the start of its next turn.",
         (target,))


def _erase(ctx: Any, target: dict[str, Any], kind: str) -> None:
    from .. import summons, zones
    from . import note as _note

    engine, user = ctx.engine, ctx.actor
    if kind == "manifestation":
        zone = target["zone"]
        zones.remove(engine, zone, "RETURN_TO_NOTHING")
        _note(engine, ctx.source, user, f"Return to Nothing: {target['label']} is erased from the fight.")
    elif kind == "asset":
        asset = engine.state.actors.get(target["id"])
        if asset is not None:
            summons.dismiss(engine, asset, "RETURN_TO_NOTHING",
                            log=f"Return to Nothing: {asset.display_name} is erased from the fight.")
    elif kind == "object":
        obj = target["object"]
        engine._update_object(obj.model_copy(update={"destroyed": True, "current_hp": 0}), ctx.source, user.entity_id)
        _note(engine, ctx.source, user, f"Return to Nothing: {target['label']} is erased from the fight.")


def _suppress_object(ctx: Any, target: dict[str, Any], *, expires_on: str, when: str) -> None:
    from . import note as _note

    engine, user = ctx.engine, ctx.actor
    obj = target["object"]
    component = {**(obj.component or {}), "law_suppressed_until": expires_on}
    engine._update_object(obj.model_copy(update={"suppressed": True, "component": component}), ctx.source,
                          user.entity_id)
    engine._append_event("OBJECT_UPDATED", ctx.source, actor_id=user.entity_id,
                         target_ids=(obj.object_id,),
                         payload={"log": (f"Return to Nothing: {target['label']}'s artifact or Secret functions are "
                                          f"suppressed {when}; the object itself remains.")})
    _note(engine, ctx.source, user,
          f"Return to Nothing: {target['label']}'s functions are suppressed {when}; the object itself remains.")


def _suppress_manifestation(ctx: Any, target: dict[str, Any], *, expires_on: str, when: str) -> None:
    engine, user = ctx.engine, ctx.actor
    if target["kind"] == "manifestation":
        from . import area_suppression

        area_suppression.suppress(engine, user, target["zone"], expires_on, ctx.source)
        note(engine, ctx.source, user, f"Return to Nothing: {target['label']} is suppressed {when}.")
        return
    if target["kind"] == "object":
        _suppress_object(ctx, target, expires_on=expires_on, when=when)
        return
    asset = engine.state.actors.get(target["id"])
    if asset is not None:
        engine._apply_condition(asset, SUPPRESSED_MANIFESTATION, ctx.source, user.entity_id, expires_on=expires_on,
                                data={"rule": {"no_actions": True, "no_reactions": True, "speed_zero": True},
                                      "label": (f"Return to Nothing: {asset.display_name}'s projected form is inert "
                                                f"{when}; it remains on the table.")})
        note(engine, ctx.source, user, f"Return to Nothing: {target['label']} is suppressed {when}.")


def _manifestation_tree(ctx: Any, target: dict[str, Any]) -> None:
    from ..typed_executor import clock_expiry
    from .effect_durations import token

    engine, user = ctx.engine, ctx.actor
    source = target.get("source") or ""
    protected = _protected_item(engine, source) if source else False
    if target["cl"] < law_cl(engine, user) and not protected:
        _erase(ctx, target, target["kind"])
        return
    numbers = _numbers(engine.action_catalog.get(source))
    dc = int(numbers.get("save_dc") or 15)
    if _cultivation_check(engine, user, dc, "Return to Nothing (manifestation or object)"):
        expiry = clock_expiry(engine, "minutes", 1)
        if not protected and target["kind"] != "object":
            _erase(ctx, target, target["kind"])
            return
        _suppress_manifestation(ctx, target, expires_on=expiry, when="for 1 minute")
        return
    _suppress_manifestation(ctx, target,
                            expires_on=token("start", user.entity_id, int(user.turns_started) + 1),
                            when="until the start of your next turn")


@effect(RETURN_EFFECT, harmful=True)
def return_to_nothing(ctx: Any, row: dict[str, Any]) -> None:
    """Return to Nothing: the whole printed outcome tree for every target kind."""
    engine, user = ctx.engine, ctx.actor
    if not owns(engine, user) or not active(engine, user):
        return
    destination = getattr(ctx.intent, "destination", None)
    candidates = _return_candidates(engine, user, destination)
    if not candidates:
        ctx.rider("Return to Nothing: there is no creature bearing three of your Void Marks, Cultivation Asset, "
                  "active manifestation or object in that space within 60 feet.")
        return
    by_id = {row_["id"]: row_ for row_ in candidates}
    labels = {row_["id"]: row_["label"] for row_ in candidates}
    chosen = None
    if _player(engine, user):
        answer = _ask(ctx, user, "law_return_target", list(by_id), labels, list(by_id)[:1],
                      "Return to Nothing: choose the one creature, Cultivation Asset, active manifestation or object "
                      "to erase from ordinary reality. Once during this activation.")
        chosen = answer[0] if answer else None
    else:
        chosen = list(by_id)[0]
    if chosen is None or chosen not in by_id:
        return
    target = by_id[chosen]
    known = (engine.state.actors[target["id"]],) if target["id"] in engine.state.actors else ()
    note(engine, ctx.source, user,
         f"Return to Nothing chooses {labels[chosen]} within 60 feet. This use is spent for this activation.", known)
    if target["kind"] == "creature":
        actor = engine.state.actors[target["id"]]
        save = engine._roll_save(actor, "CHA", int(ctx.numbers.get("save_dc") or 10), ctx.source)
        if save is None:
            return
        if int(save.total) >= int(ctx.numbers.get("save_dc") or 10):
            _creature_saved(ctx, actor)
        else:
            _creature_failed(ctx, actor)
        return
    _manifestation_tree(ctx, target)


@effect(RETURN_BACK_EFFECT, harmful=True)
def return_back(ctx: Any, row: dict[str, Any]) -> None:
    """When it returns: its Cultivation Points become 0, and one system stays suppressed."""
    engine, user, target = ctx.engine, ctx.actor, ctx.target
    if target is None:
        return
    for pool in CP_POOLS:
        held = int(target.resources.get(pool) or 0)
        if held:
            engine._spend_resource(target, pool, held, ctx.source)
    from .effect_durations import token

    _suppress_system(ctx, target, expires_on=token("end", target.entity_id, int(target.turns_started) + 1),
                     when="until the end of its next turn")
    note(engine, ctx.source, user,
         f"Return to Nothing: {target.display_name} returns to the nearest legal space to its departure point with "
         "0 Cultivation Points, and one of its cultivation systems remains suppressed until the end of its next turn.",
         (target,))


# ------------------------------------------------------------------------------------------------ cleanup, repeat, plain words
@hook("event")
def law_state_events(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    payload = kwargs.get("payload") or {}
    if event_type == "CONDITION_REMOVED" and payload.get("condition_id") == LAW_CONDITION:
        for actor_id in kwargs.get("target_ids") or ():
            actor = engine.state.actors.get(actor_id)
            if actor is None:
                continue
            from .. import zones
            from .void_touched_hollow_field import fields

            action = law_action(engine, actor)
            source = action.source_definition_id if action is not None else ""
            for zone in fields(engine):
                if zone.owner_id == actor.entity_id and source and zone.source_definition_id == source:
                    zones.remove(engine, zone, "LAW_ENDED")
    elif event_type == "CONDITION_REMOVED" and payload.get("condition_id") == SYSTEM_CONDITION:
        from .void_touched_hollow_field import give_back_system_rows

        for actor_id in kwargs.get("target_ids") or ():
            actor = engine.state.actors.get(actor_id)
            if actor is None:
                continue
            for condition in list(actor.conditions.values()):
                if condition.condition_id == SYSTEM_CONDITION:
                    give_back_system_rows(engine, actor, condition.data or {})
                    engine._remove_condition_instance(actor, condition.instance_id, LAW, expected=condition,
                                                      payload={"condition_id": SYSTEM_CONDITION,
                                                               "instance_id": condition.instance_id,
                                                               "reason": "REMOVED"})


@hook("turn_end")
def law_interval_repeat(engine: Any, actor: Any) -> None:
    """Deadlines due at a turn end, and the within-2-CL target's repeat Cultivation Check."""
    _release_suppressions(engine, "END_OF_TURN", actor)
    held = next((c for c in actor.conditions.values() if c.condition_id == ABSENT_CONDITION), None)
    if held is None:
        return
    data = held.data or {}
    if int(data.get("law_repeat_check") or 0) != 1:
        return
    user = engine.state.actors.get(str(data.get("law_owner") or ""))
    if user is None:
        return
    if _cultivation_check(engine, actor, int(data.get("law_repeat_dc") or 10), "Return to Nothing (escape the interval)"):
        note(engine, LAW, user, f"Return to Nothing: {actor.display_name} succeeds on its Cultivation Check and "
                                "returns from the Void interval.", (actor,))
        engine._remove_condition(actor, ABSENT_CONDITION, LAW)


@hook("status_description")
def law_status(engine: Any, holder: Any, row: Any, data: Any) -> dict[str, Any] | None:
    condition_id = str((row or {}).get("condition_id") or "")
    if condition_id == LAW_CONDITION:
        data = data or {}
        return {"text": str(data.get("label") or _label()), "display_name": "Law of Nonexistence",
                "source_ability": "Law of Nonexistence"}
    if condition_id == SYSTEM_CONDITION:
        return {"text": str((data or {}).get("label") or "One cultivation system is suppressed."),
                "display_name": "Suppressed system", "source_ability": "Return to Nothing"}
    if condition_id == SUPPRESSED_MANIFESTATION:
        return {"text": str((data or {}).get("label") or "A manifestation is inert."),
                "display_name": "Suppressed manifestation", "source_ability": "Return to Nothing"}
    return None

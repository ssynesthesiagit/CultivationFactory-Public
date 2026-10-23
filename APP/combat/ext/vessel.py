"""Puppetry vessel placements and their directed actions.

Source: rules_text.json PUPPETRY_BASE_* and tianxia.talent.puppetry.*, plus the
Puppetry chapter's vessel statistics, control threads and Tension Responses.
A placement is an object, not an independent creature/turn or granted ally.

New sealed kits opt in through vessel_native. Strike candidates bind public
activation origins without moving the owner; each vessel retains its own form.
Raise offers movement inside its paid activation. Two-Body Control shares the
highest Speed between directed routes; Incarnation gives each vessel its Speed.
Domain permits three inside threads, while outside threads retain the ordinary
limit; Incarnation replaces those pools with five total threads. Oldest threads
yield first when a pool exceeds its limit. Native minute expiry owns both buffs.

New Domain/Incarnation flags run broken-vessel choices and damage through the
strict state_event checkpoint. Native kits transfer Substitute Harm Body's
actual recorded reduction there exactly once; old sealed kits retain the event
callback and their original menus, form handling, movement and capacity.

Uses existing hooks and typed effects only. The AUTO28 report inventories the
remaining object-target bridge, recipient consent, construction/projection
provenance, shared roll-consumption and real rest-clock contracts. This module
does not certify declaration-only authority effects as complete automation.
"""

from __future__ import annotations

import hashlib
from .map_positions import map_position

import copy
from typing import Any

from . import effect, hook, placed, run_strict

SPHERE = "tianxia.sphere.puppetry"
SETUP = "condition:typed.vessel_setup"
GUARDED = "condition:typed.vessel_guarded"
MARK = "Tension Mark"

TWO_BODY, LONG_SILK, IRONWOOD = ("tianxia.talent.puppetry.two_body_control", "tianxia.talent.puppetry.long_silk_thread",
                                 "tianxia.talent.puppetry.ironwood_practice_body")
HARM_BODY = "tianxia.talent.puppetry.substitute_harm_body"
SUBSTITUTION = "tianxia.talent.puppetry.marionette_substitution_body"
SPARE_BODY = "tianxia.talent.puppetry.heaven_s_spare_body"
THEATER = "tianxia.talent.puppetry.puppet_theater_domain"
THEATER_ACTIVE = "condition:typed.vessel_theater"
INCARNATION = "tianxia.talent.puppetry.thousand_puppet_incarnation"
INCARNATION_ACTIVE = "condition:typed.vessel_incarnation"
STRIKE_BASE = "PUPPETRY_BASE_PUPPET_STRIKE"
PREPARED_ITEM = "condition:typed.puppet_prepared_item"

RAISE_RANGE_FT = 30  # Raise the Vessel: "Range: 30 feet"
TOUCH_FT = 5
ACTIVE_ROUNDS = 10  # "Duration: 1 minute"
CONTROL_FT = 60  # "your control range is 60 feet"
HARM_FT, SWAP_FT = 30, 60  # Substitute Harm Body, Marionette Substitution Body
FORMS = {"bludgeoning": "Bludgeoning", "piercing": "Piercing", "slashing": "Slashing"}
# "none" is a real choice, not a broken row: it says the vessel keeps its base statistics (CLARITYOFF1).
CONSTRUCTIONS = {"none": "none (base vessel, no construction bonus)", "guard": "Guard Body (+2 AC)", "running": "Running Body (+10 ft Speed)", "needle": "Needle Body (reach 10 ft, Piercing)",
                 "heavy": "Heavy Body (-5 ft Speed)"}
RESPONSES = {"tug": "Tug the Joint", "cross": "Cross the Limb", "guard": "Guarding Vessel", "snap": "Snap the Thread",
             "snap_last": "Snap the Thread (the vessel's last damage type)"}
# What every Tension Response COSTS, written once so the five buttons cannot drift apart.  "A Tension Response spends a
# Tension Mark" is the owner's rule, and tension() removes the mark BEFORE the target's save runs, so no response is
# free and Tug the Joint pays the mark even when the target's Strength save succeeds.
_MARK_ON_TARGET = ("No Action is required, but this spends one of your Tension Marks: the mark on the marked creature you choose. "
                   "You may use only one Tension Response per turn, and that creature must be within your control range while "
                   "you have an active control thread.")
_MARK_ON_TARGET_SPENT_ANYWAY = _MARK_ON_TARGET + " The mark is spent even if that creature's saving throw succeeds."
# Guarding Vessel protects one creature and spends a mark on another. Native kits
# choose the mark bearer; legacy sealed kits keep their nearest-bearer payment.
_MARK_ON_NEAREST = ("No Action is required, but this spends one of your Tension Marks: not on the creature you protect, but on "
                    "whichever of your own marked creatures is nearest to you. You may use only one Tension Response per turn, "
                    "and you need at least one marked creature within your control range and an active control thread.")
_MARK_ON_CHOSEN = ("No Action is required, but this spends one of your Tension Marks: not on the creature you protect; "
                   "you choose one of your marked creatures within your control range and spend its mark. "
                   "You may use only one Tension Response per turn, and you need an active control thread.")
_GUARD_BENEFIT = (" The creature you choose, within 5 feet of the vessel, gains +2 AC against its next attack roll, "
                  "until the start of your next turn.")
# The owner's printed line for each response plus that cost, so the button never reaches the table saying nothing and
# never hides what it spends. Snap's {snap_dice} is filled from SNAP_DICE at the compiled level.
RESPONSE_TEXT = {
    "tug": _MARK_ON_TARGET_SPENT_ANYWAY + " The target makes a Strength saving throw; on a failure you choose a visible, unoccupied "
           "space 5 feet away horizontally and the target is moved there. A target at least two sizes larger than your "
           "puppet vessel has Advantage on this saving throw.",
    "cross": _MARK_ON_TARGET + " The target has Disadvantage on its next attack roll, before the end of its next turn.",
    "guard": _MARK_ON_NEAREST + _GUARD_BENEFIT,
    "snap": _MARK_ON_TARGET + " The target takes {snap_dice}d6 Force damage.",
    "snap_last": _MARK_ON_TARGET + " The target takes {snap_dice}d6 damage of the type of the vessel's last Puppetry attack.",
}
# The active-vessel limit, in the words a player needs, keyed by the same number _limit() hands the engine: a Two-Body
# Control owner may keep two vessels up, so telling them a second raise deactivates the first costs them the talent.
RAISE_LIMIT_TEXT = {
    1: "You can control one active vessel at a time: raising a second makes the first inactive, and it stays where it is until you claim it again.",
    2: "With Two-Body Control you can control two active vessels at once, so raising a second one does not put the first down.",
}
# (low CL, high CL, value): the Vessel Statistics table
AC_ROWS = [(1, 4, 13), (5, 10, 14), (11, 16, 15), (17, 99, 16)]
HP_ROWS = [(1, 4, (10, 2)), (5, 10, (15, 3)), (11, 16, (20, 4)), (17, 99, (25, 5))]  # base + times CL
SPEED_ROWS = [(1, 4, 25), (5, 10, 30), (11, 16, 30), (17, 99, 35)]
SILK_ROWS = [(1, 4, 30), (5, 10, 60), (11, 99, 120)]  # Long Silk Thread: "at CL 5 ... 60 feet instead"
SNAP_DICE = [(1, 4, 1), (5, 10, 2), (11, 16, 3), (17, 99, 4)]  # d6


# ------------------------------------------------------------------------------------------------ the kit a puppeteer owns
def _kit(engine: Any, owner: Any) -> dict[str, Any] | None:
    for action in engine.action_catalog.values():
        params = action.parameters or {}
        if action.owner_id == owner.entity_id and params.get("vessel_kit"):
            typed = params.get("typed") or {}
            return {"action": action, "owned": set(params.get("vessel_owned") or ()), "numbers": typed.get("numbers") or {},
                    "pool": params.get("vessel_pool") or "resource:core.qi", "source": action.source_definition_id,
                    "body": bool(params.get("vessel_body")), "native": bool(params.get("vessel_native")),
                    "initiation": params.get("vessel_initiation")}
    return None


def _config(owner: Any) -> dict[str, Any]:
    for condition in owner.conditions.values():
        if condition.condition_id == SETUP:
            return dict(condition.data or {})
    return {}


def _prepared_item(owner: Any, kit: dict[str, Any]) -> dict[str, Any]:
    """One acquired physical item; its encounter lifecycle is evented state.

    The condition uses only primitive fields and travels through the existing
    journey encounter snapshot. Expiry ends the thread, not the physical item.
    """
    item = (kit.get("initiation") or {}).get("vessel") or {}
    stored = next((c.data for c in owner.conditions.values() if c.condition_id == PREPARED_ITEM
                   and c.data.get("item_instance_id") == item.get("item_instance_id")), None)
    return dict(stored or item)


def _item_ready(item: dict[str, Any], owner: Any) -> bool:
    """This puppeteer's own intact prepared item: the object Raise can claim as a vessel.

    A broken item, another owner's item, or an acquisition that never completed a
    rest is not a suitable vessel, but it never disables the ability for the
    puppeteer's other vessels.
    """
    return bool(item.get("item_instance_id") and item.get("owner_id") == owner.entity_id and not item.get("broken"))


def _item_square(item: dict[str, Any], cell: Any) -> bool:
    """A carried item may be set down on any free square; once placed it is claimed at its own square."""
    return cell is not None and ("x" not in item or (cell.x, cell.y, cell.z) == (item["x"], item["y"], item["z"]))


def _cl(kit: dict[str, Any]) -> int:
    return int(kit["numbers"].get("cl") or 1)


def _control(kit: dict[str, Any]) -> int:
    return CONTROL_FT + (placed.cl_row(_cl(kit), SILK_ROWS) if LONG_SILK in kit["owned"] else 0)


def _limit(kit: dict[str, Any]) -> int:
    return 2 if TWO_BODY in kit["owned"] else 1  # "You may maintain two active puppet vessels at once."


def _incarnation(owner: Any) -> Any | None:
    return next((c for c in owner.conditions.values() if c.condition_id == INCARNATION_ACTIVE
                 and c.data.get("native_incarnation") == 1), None)


def _capacity_group(engine: Any, owner: Any, owned: dict[str, Any], cell: Any = None) -> tuple[list[Any], int]:
    """Domain supplies three inside slots; outside threads keep the base limit.

    Incarnation replaces both pools with five total slots. Old saved kits retain
    their original global capacity. Oldest threads yield first in each pool.
    """
    active = _vessels(engine,owner)
    if not owned.get("native"):
        return active, _limit(owned)
    if _incarnation(owner):
        return active, 5
    theater = _theater(owner)
    if theater and theater.data.get("native_theater") == 1 and cell is not None:
        inside = _dist(engine,owner,cell) <= 30
        return [z for z in active if (_dist(engine,owner,z.center) <= 30) == inside], 3 if inside else _limit(owned)
    return active, _limit(owned)


def _raise_description(owned: set[str]) -> str:
    """The Raise the Vessel button's rule text, with the active-vessel limit the owner actually gets.

    Driven by `_limit`, the same number `raise_vessel` enforces, so a Two-Body Control owner is never told a second
    raise deactivates their first vessel (the pre-fix text said exactly that, and told them so about everyone).
    """
    return ("Costs an Action and 1 Cultivation Point. Choose a free square within 30 feet (5 feet for a Body Refiner without "
            "Long Silk Thread). You claim one puppet vessel and set a control thread to it, and it stays active for 1 minute. "
            "You may move it up to its Speed for free on the same turn. "
            + RAISE_LIMIT_TEXT[_limit({"owned": owned})])


def _stats(kit: dict[str, Any], cons: str | None) -> dict[str, int]:
    cl = _cl(kit)
    base, mult = placed.cl_row(cl, HP_ROWS)
    hp = base + mult * cl
    return {"ac": placed.cl_row(cl, AC_ROWS) + (2 if cons == "guard" else 0), "hp": hp,
            "speed": placed.cl_row(cl, SPEED_ROWS) + (10 if cons == "running" else -5 if cons == "heavy" else 0)}


def _vessels(engine: Any, owner: Any, states: tuple[str, ...] = ("active",)) -> list[Any]:
    return [zone for zone in placed.of(engine, "vessel", owner_id=owner.entity_id) if placed.data(zone).get("state") in states]


def _dist(engine: Any, owner: Any, cell: Any) -> int:
    return engine.grid.distance_ft(owner.position, cell)


def _thread(engine: Any, owner: Any, zone: Any, kit: dict[str, Any]) -> bool:
    """A live control thread: the vessel is inside the control range and in line of effect."""
    return _dist(engine, owner, zone.center) <= _control(kit) and engine._line_of_sight_actor_to_cell(owner, zone.center)


def _threaded(engine: Any, owner: Any, kit: dict[str, Any]) -> list[Any]:
    return [zone for zone in _vessels(engine, owner) if _thread(engine, owner, zone, kit)]


def kit(engine: Any, owner: Any) -> dict[str, Any] | None:
    """Owned Puppetry kit for vessel talents; shares the vessel action's compiled ownership and numbers."""
    return _kit(engine, owner)


def control_range(owned_kit: dict[str, Any]) -> int:
    """Control distance in feet, shared by vessel actions and Tension Mark spending talents."""
    return _control(owned_kit)


def threaded_vessels(engine: Any, owner: Any, owned_kit: dict[str, Any]) -> list[Any]:
    """Active vessels with a live control thread; shared by vessel actions and vessel_talents."""
    return _threaded(engine, owner, owned_kit)


def _placement_actors(engine: Any) -> Any:
    """Known current occupancy for AI previews; real occupancy at execution."""
    from ..candidate_knowledge import active
    if not active(engine):
        return engine.state.actors.values()
    from ..target_knowledge import knowledge
    viewer = engine.state.actors[engine.state.current_actor_id]
    return [other for other in engine.state.actors.values()
            if (known := knowledge(engine, viewer, other)) is not None and known.mode == "DIRECT"]


def _vessel_cells(engine: Any) -> set[tuple[int, int]]:
    """Standing vessel squares; AI previews know their own and visible objects."""
    from ..candidate_knowledge import active
    from ..senses import perceives_cell
    preview = active(engine)
    viewer = engine.state.actors[engine.state.current_actor_id]
    return {(zone.center.x, zone.center.y) for zone in placed.of(engine, "vessel")
            if placed.data(zone).get("state") in ("active", "inactive") and
            (not preview or zone.owner_id == viewer.entity_id or perceives_cell(engine, viewer, zone.center))}


def _suitable_object(engine: Any, cell: Any) -> bool:
    """PUPPETRY_BASE_RAISE_THE_VESSEL: a vessel that is not the prepared item needs a suitable object on its square.

    A live, non-structural scene object (debris, a prepared doll, loose material) must stand there; open floor is
    not a vessel. Walls, doors and destroyed objects do not count. An AI preview sees only squares its creature perceives.
    """
    from ..candidate_knowledge import active
    from ..senses import perceives_cell
    if active(engine):
        viewer = engine.state.actors[engine.state.current_actor_id]
        if not perceives_cell(engine, viewer, cell):
            return False
    return any((obj.position.x, obj.position.y) == (cell.x, cell.y) and not obj.destroyed
               and not (obj.component or {}).get("structure") for obj in engine.state.objects.values())


def _occupied(engine: Any) -> set[tuple[int, int]]:
    # Creatures and vessel objects share the directed vessel's walking route.
    cells: set[tuple[int, int]] = set()
    for other in _placement_actors(engine):
        if other.active:
            cells.update(engine._actor_cells(other))
    return cells | _vessel_cells(engine)


def _free_placement(engine: Any, cell: Any) -> bool:
    from ..candidate_knowledge import active
    if not active(engine):
        return placed.free_square(engine, cell)
    return (engine.grid.in_bounds((cell.x, cell.y)) and (cell.x, cell.y) not in engine.grid.blocked
            and not any(other.active and engine._footprint_intersects(other, (cell,)) for other in _placement_actors(engine)))


def _reach(action: Any, config: dict[str, Any]) -> int:
    params = action.parameters or {}
    reach = int(params.get("vessel_reach") or 5)
    return max(reach, 10) if config.get("cons") == "needle" else reach  # Needle Body: "its range from the vessel increases to 10 feet"


def _marked(engine: Any, owner: Any, kit: dict[str, Any]) -> list[Any]:
    from ..typed_executor import bears_mark

    return [actor for actor in engine.state.actors.values() if actor.active and bears_mark(actor, owner.entity_id, MARK)
            and _dist(engine, owner, actor.position) <= _control(kit)]


def _log(engine: Any, source: str, owner: Any, text: str, targets: Any = ()) -> None:
    placed.note(engine, source, owner, text, targets=targets)


# ------------------------------------------------------------------------------------------------------------ the buttons
@hook("compile_block")
def native_vessel_row(block: str, spec: Any, row: Any, numbers: Any) -> Any:
    return [{**row,"block":block,"native_vessel":1,"keeps_compiling":True}] if block == "vessel_native" else None


@hook("compile_actions")
def vessel_actions(info: dict[str, Any]) -> list[Any] | None:
    from ..factory_compiler import RESOURCE_IDS
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    if SPHERE not in info["spheres"]:
        return None
    short, actor_id, numbers = info["short"], info["actor_id"], info["numbers"]
    owned = set(info["owned_ids"])
    native = any(r.get("block") == "vessel_native" for r in info.get("passives", []))
    kit = {"owned": owned, "numbers": numbers}
    out: list[Any] = []

    def make(key: str, name: str, effects: list[dict[str, Any]], economy: Any = EconomyKind.NONE, target: str = "SELF",
             range_ft: int | None = None, **params: Any) -> Any:
        return ActionDefinition(
            source_definition_id=f"action:typed.{short}.{key}", display_name=name, owner_id=actor_id, economy=economy, resolution_kind="TYPED",
            target_kind=target, range_ft=range_ft,
            parameters={"typed": {"effects": effects, "numbers": numbers, "duration": {"kind": "instant"}, "riders": [], "source": SPHERE},
                        "expected_damage": 0, "player_only": True, **params})

    pool = RESOURCE_IDS.get(str(info.get("primary") or "qi"), "resource:core.qi")
    body = "body" in str(info.get("primary") or "").lower()
    initiation = copy.deepcopy(info["owner_sheet"].get("puppet_initiation"))
    if initiation and initiation.get("vessel") and not any(
            r.get("combat_item_key") == initiation["vessel"]["item_instance_id"] for r in info["kit"].get("items", [])):
        initiation.pop("vessel")  # the owner explicitly left this instance behind
    if initiation and initiation.get("vessel"):
        # New encounter setup places carried equipment anew. Durable HP and
        # breakage remain; a continued journey's encounter condition retains
        # its actual square through the existing snapshot contract.
        for key in ("x", "y", "z", "label"):
            initiation["vessel"].pop(key, None)
    out.append(make("vessel.raise", "Raise the Vessel (1 CP)", [{"type": "vessel_raise"}], EconomyKind.ACTION, "CELL", RAISE_RANGE_FT, any_cell=not native,
                    player_only=not native, **({"cell_placement": {}} if native else {}),
                    vessel_kit=True, vessel_raise=True, vessel_owned=sorted(owned), vessel_pool=pool, vessel_body=body, vessel_native=native,
                    **({"vessel_initiation": copy.deepcopy(initiation)} if initiation else {}),
                    description=_raise_description(owned).replace("for free on the same turn", "for free during this activation" if native else "for free on the same turn")
                    + (" Have a suitable prepared vessel or object ready. Body Refiners need an approved external-thread feature before controlling a vessel remotely." if native else "")
                    + (" Puppet Theater Domain allows three active vessels inside its 30-foot area; outside threads keep your normal limit. Thousand-Puppet Incarnation allows five total vessels. Excess older threads go inactive." if native and owned & {THEATER,INCARNATION} else "")))
    out.append(make("vessel.move", "Move Vessel", [{"type": "vessel_move"}], EconomyKind.BONUS_ACTION, "CELL", 600, any_cell=not native,
                    player_only=not native, **({"cell_placement": {}} if native else {}), vessel_move=True, description="Costs a Bonus Action. Move your active vessel up to its Speed, walking only: it cannot "
                    "fly, swim, burrow or climb smooth surfaces. It cannot pass through creatures, and it must end in a free square that is "
                    "inside your control range and that you have line of effect to."))
    out.append(make("vessel.move_free", "Move Vessel (as you raise it)", [{"type": "vessel_move", "free": True}], EconomyKind.NONE, "CELL", 600,
                    any_cell=True, vessel_move=True, vessel_free=True,
                    description="Free on the turn you raise the vessel: you may move it up to its Speed as part of that same turn. On later turns "
                    "moving it costs a Bonus Action."))
    out.append(make("vessel.dismiss", "Dismiss Vessel", [{"type": "vessel_dismiss"}], EconomyKind.NONE, "SELF", None, vessel_dismiss=True,
                    description="Free on your turn: you may dismiss the vessel without using an Action."))
    for value, label in (() if initiation else FORMS.items()):
        out.append(make(f"vessel.form.{value}", f"Vessel form: {label}", [{"type": "vessel_setup_pick", "field": "form", "value": value}],
                        description=f"Choose {label} as the physical form of your next puppet vessel.", setting_only=True))
    if IRONWOOD in owned:
        for value, label in CONSTRUCTIONS.items():
            description = ("Choose no construction: your next puppet vessel keeps the base statistics on the Vessel table."
                           if value == "none" else f"Choose the {label} construction for your next puppet vessel.")
            out.append(make(f"vessel.cons.{value}", f"Vessel construction: {label}", [{"type": "vessel_setup_pick", "field": "cons", "value": value}],
                            description=description, setting_only=True))
    control = CONTROL_FT + (placed.cl_row(int(numbers.get("cl") or 1), SILK_ROWS) if LONG_SILK in owned else 0)
    snap_dice = placed.cl_row(int(numbers.get("cl") or 1), SNAP_DICE)
    for name, label in RESPONSES.items():
        target = "ALLY_OR_SELF" if name == "guard" else "HOSTILE_ENTITY"
        description = RESPONSE_TEXT[name].format(snap_dice=snap_dice)
        if native and name == "guard":
            description = _MARK_ON_CHOSEN + _GUARD_BENEFIT
        if THEATER in owned:
            description += " While Puppet Theater Domain is active, you can use one extra basic Tension Response each turn."
        out.append(make(f"vessel.tension.{name}", f"Tension Response: {label}", [{"type": "vessel_tension", "response": name}], EconomyKind.NONE,
                        target, control, vessel_tension=name, player_only=not native, description=description))
    # "Puppet Strike ... from the puppet vessel's space": a copy of the compiled strike (and of each talent variant of it) whose attack
    # is run from the vessel; native kits never offer the owner-origin strike (see vessel_candidates).
    for action in info["actions"]:
        if STRIKE_BASE not in action.source_definition_id or (action.parameters or {}).get("vessel_strike"):
            continue
        typed = copy.deepcopy(dict((action.parameters or {}).get("typed") or {}))
        template = typed.get("effects") or []
        if not template:
            continue
        typed["effects"] = [{"type": "vessel_strike", "template": template}]
        params = {**(action.parameters or {}), "typed": typed, "vessel_strike": True, "player_only": True,
                  "vessel_reach": 5 if int(action.range_ft or 5) <= 5 else 30}
        if native:
            params.update(vessel_native_origin=True,player_only=False)
            if params['vessel_reach'] == 30:
                for row in _flat(template):
                    if row.get('type') == 'attack' and row.get('attack_kind') == 'cultivation_melee':
                        row['attack_kind']='cultivation_ranged'
        out.append(action.model_copy(update={"source_definition_id": f"{action.source_definition_id}.vessel", "range_ft": control + 30,
                                             "display_name": f"{action.display_name} (from the vessel)", "parameters": params}))
        if native and INCARNATION in owned:
            out.append(out[-1].model_copy(update={"source_definition_id":out[-1].source_definition_id+".free",
                "display_name":out[-1].display_name+" (Incarnation free strike)","economy":EconomyKind.NONE,
                "parameters":{**params,"vessel_incarnation_free":True,
                    "description":"While Thousand-Puppet Incarnation lasts, one Puppet Strike each turn costs no Action; no extra cultivation point or Reaction cost."}}))
    return out


@hook("effect_origins")
def vessel_origins(engine: Any, owner: Any, action: Any) -> Any:
    if not action.parameters.get("vessel_native_origin"):
        return None
    owned = _kit(engine,owner)
    if not owned or not owned.get("native"):
        return None
    return [{"id":"vessel:"+z.zone_id,"label":f"Puppet vessel at ({z.center.x}, {z.center.y})",
             "position":z.center.model_dump(mode="json")} for z in _threaded(engine,owner,owned)]


@hook("button_selection")
def setup_selection(parameters: dict[str, Any]) -> dict[str, Any] | None:
    pick = next((eff for eff in (parameters.get("typed") or {}).get("effects") or [] if eff.get("type") == "vessel_setup_pick"), None)
    return {"condition": SETUP, "equals": {pick["field"]: pick.get("value")}} if pick else None


@effect("vessel_setup_pick")
def setup_pick(ctx: Any, eff: dict[str, Any]) -> None:
    config = _config(ctx.actor)
    config[str(eff["field"])] = eff.get("value")
    config["label"] = (f"Vessel: {FORMS.get(config.get('form') or 'bludgeoning', 'Bludgeoning')} form"
                       + (f", {CONSTRUCTIONS[config['cons']]}" if config.get("cons") not in (None, "none") else ""))
    ctx.engine._remove_condition(ctx.actor, SETUP, ctx.source)
    ctx.engine._apply_condition(ctx.actor, SETUP, ctx.source, ctx.actor.entity_id, expires_on="UNTIL_REMOVED", data=config)


@hook("candidate_allowed")
def vessel_candidates(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    params = getattr(action, "parameters", None) or {}
    sid = getattr(action, "source_definition_id", "") or ""
    if STRIKE_BASE in sid and not params.get("vessel_strike"):
        # The compiled strike attacks from the puppeteer's own square (the engine cannot start it from a vessel); while a vessel is up the
        # rules' "from the puppet vessel's space" strike replaces it. Legacy kits retain their no-vessel fallback.
        owned = _kit(engine,actor)
        return False if owned and (owned.get('native') or _vessels(engine,actor)) else None
    if not any(params.get(key) for key in ("vessel_raise", "vessel_move", "vessel_dismiss", "vessel_strike", "vessel_tension")):
        return None
    kit = _kit(engine, actor)
    aim = getattr(candidate, "destination", None)
    if kit is None:
        return False
    config = _config(actor)
    if params.get("vessel_dismiss"):
        return bool(_vessels(engine, actor)) and engine.state.current_actor_id == actor.entity_id
    if params.get("vessel_raise"):
        if aim is None or actor.resources.get(kit["pool"], 0) < 1:
            return False
        reach = TOUCH_FT if kit["body"] and LONG_SILK not in kit["owned"] else RAISE_RANGE_FT
        if engine.grid.distance_ft(actor.position, aim) > reach or not engine._line_of_sight_actor_to_cell(actor, aim):
            return False
        # The item Puppet Initiation prepared is one suitable vessel, never the only
        # one this ability may claim. At the item's own square the raise keeps that
        # item's identity; every other square is an ordinary raise that reclaims or
        # adds a vessel of its own, so Two-Body Control, Puppet Theater Domain and
        # Thousand-Puppet Incarnation can fill their printed capacity and one broken
        # or left-behind item does not disable the whole ability.
        item = _prepared_item(actor, kit) if kit.get("initiation") else {}
        reclaim = [zone for zone in _vessels(engine, actor, ("inactive",))
                   if (zone.center.x, zone.center.y) == (aim.x, aim.y)]
        if _item_ready(item, actor) and _item_square(item, aim):
            # One prepared physical object cannot become two placed vessels.
            if any(placed.data(zone).get("item_instance_id") == item["item_instance_id"]
                   for zone in _vessels(engine, actor)):
                return False
            mine = [zone for zone in reclaim if placed.data(zone).get("item_instance_id") == item["item_instance_id"]]
            return bool(mine) or (_free_placement(engine, aim) and (aim.x, aim.y) not in _vessel_cells(engine))
        return bool(reclaim) or (_free_placement(engine, aim) and (aim.x, aim.y) not in _vessel_cells(engine)
                                 and _suitable_object(engine, aim))
    if params.get("vessel_move"):
        if aim is None or not _free_placement(engine, aim) or (aim.x, aim.y) in _vessel_cells(engine):
            return False
        if params.get("vessel_free") and not actor.turn_flags.get("vessel_free_move"):
            return False
        return _mover(engine, actor, kit, aim) is not None
    if params.get("vessel_strike"):
        target = engine.state.actors.get((candidate.target_ids or ("",))[0])
        if params.get("vessel_incarnation_free") and (not _incarnation(actor) or actor.turn_flags.get("vessel_incarnation_strike_used")):
            return False
        if params.get("vessel_native_origin"):
            origin = (candidate.metadata or {}).get("effect_origin")
            zone = engine.state.zones.get(str(origin.get("id", "")).removeprefix("vessel:")) if origin else None
            return bool(zone and zone in _threaded(engine,actor,kit) and target
                and engine._distance_actor_to_cell(target,zone.center) <= _reach(action,placed.data(zone)))
        return target is not None and _striker(engine, actor, kit, target, _reach(action, config)) is not None
    if params.get("vessel_tension"):
        return _response_ok(engine, actor, kit, params["vessel_tension"], engine.state.actors.get((candidate.target_ids or ("",))[0]))
    return None


@hook("ai_candidate_allowed")
def ai_raise_vessel(engine: Any, owner: Any, candidate: Any, action: Any) -> bool | None:
    """Establish and direct one connected vessel using observed enemy geometry.

    Human seats retain all placements and repeat raises. AI leaves an existing
    thread alone and spends a movement Bonus Action only to improve its reach.
    """
    owned = _kit(engine, owner)
    if owned is None or not owned.get("native") or owned["action"].parameters.get("player_only"):
        return None
    raising = action is not None and action.parameters.get("vessel_raise")
    moving = action is not None and action.parameters.get("vessel_move") and not action.parameters.get("vessel_free")
    dodging = candidate.source_definition_id == "system:combat.dodge"
    if not (raising or moving or dodging):
        return None
    from ..target_knowledge import actors_for
    from ..relations import relation, ENEMY
    from ..candidate_knowledge import query

    threaded = _threaded(engine, owner, owned)
    if raising and threaded:
        return False
    if moving and not threaded:
        return False
    from ..canonical import canonical_sha256

    # Query-only cache: full state equality, including unversioned in-memory
    # position changes, is required. Nothing is stored in the saved fight.
    key = (canonical_sha256(engine.state.model_dump(mode="json")), owned["source"])
    cached = getattr(engine, "_ai_vessel_cell_memo", None)
    if cached is not None and cached[0] == key:
        best = cached[1]
    else:
        enemies = [a for a in actors_for(engine, owner) if a.active
                   and relation(engine, owner, a) == ENEMY]
        def distance(cell: Any) -> int:
            return min((engine._distance_actor_to_cell(a, cell) for a in enemies), default=0)

        source = owned["source"] if not threaded else owned["source"].removesuffix("raise") + "move"
        # Regenerate in the same knowledge view as the AI menu, never a hidden
        # creature's live geometry. Mechanical admission remains authoritative.
        from ..placement_menu import exhaustive
        with query(engine), exhaustive():
            cells = [c.destination for c in engine.legal_candidates()
                     if c.source_definition_id == source and c.destination is not None]
        if threaded:
            current = min(distance(z.center) for z in threaded)
            cells = [cell for cell in cells if distance(cell) < current]
        best = min(cells, key=lambda cell: (distance(cell), _dist(engine, owner, cell), cell.x, cell.y)) if cells else None
        engine._ai_vessel_cell_memo = (key, best)
    if dodging:
        return False if best is not None else None  # Establish/reposition before spending the Action.
    return best is not None and candidate.destination == best


def _striker(engine: Any, owner: Any, kit: dict[str, Any], target: Any, reach: int) -> Any | None:
    """The vessel a strike is made from: one with a live thread within reach of the target ("from either vessel, not both")."""
    near = [zone for zone in _threaded(engine, owner, kit) if engine.grid.distance_ft(zone.center, target.position) <= reach]
    return min(near, key=lambda zone: (engine.grid.distance_ft(zone.center, target.position), zone.zone_id)) if near else None


def _mover(engine: Any, owner: Any, kit: dict[str, Any], cell: Any) -> Any | None:
    """The vessel that can walk to the square: a path of at most its Speed, the square inside the control range and in line of effect."""
    if _dist(engine, owner, cell) > _control(kit) or not engine._line_of_sight_actor_to_cell(owner, cell):
        return None
    config = _config(owner)
    best: tuple[int, str, Any] | None = None
    for zone in _vessels(engine, owner):
        if not _thread(engine, owner, zone, kit):
            continue
        speed = placed.data(zone).get("speed") or _stats(kit, config.get("cons"))["speed"]
        found = engine.grid.shortest_path(zone.center, cell, occupied=_occupied(engine), max_cost_ft=int(speed))
        if found is not None and (best is None or (found[1], zone.zone_id) < best[:2]):
            best = (found[1], zone.zone_id, zone)
    return best[2] if best else None


def _response_ok(engine: Any, owner: Any, kit: dict[str, Any], response: str, target: Any) -> bool:
    extra = _theater(owner) is not None and not owner.turn_flags.get("vessel_theater_response_used")
    used = (int(owner.turn_flags.get('vessel_responses_used') or 0) >= (2 if _incarnation(owner) else 1)
            if kit.get('native') else owner.turn_flags.get("vessel_response_round_used") == engine.state.round_number)
    if target is None or (used and not extra):
        return False  # "use only one Tension Response per turn"
    if not _threaded(engine, owner, kit):
        return False  # "you have an active control thread"
    if kit.get('native') and response == 'snap_last' and not any(placed.data(z).get('last_type') for z in _threaded(engine,owner,kit)):
        return False
    if response == "guard":  # Guarding Vessel: a creature within 5 feet of the vessel; the mark spent is any of yours in range
        return bool(_marked(engine, owner, kit)) and any(engine.grid.distance_ft(zone.center, target.position) <= 5 for zone in _vessels(engine, owner))
    return target in _marked(engine, owner, kit)


# -------------------------------------------------------------------------------------------------- raising and moving
@effect("vessel_raise")
def raise_vessel(ctx: Any, eff: dict[str, Any]) -> None:
    engine, owner = ctx.engine, ctx.actor
    kit, cell = _kit(engine, owner), getattr(ctx.intent, "destination", None)
    if kit is None or cell is None:
        ctx.rider("Raise the Vessel: no square was chosen.")
        return
    item = _prepared_item(owner, kit) if kit.get("initiation") else None
    reclaim = [zone for zone in _vessels(engine, owner, ("inactive",)) if (zone.center.x, zone.center.y) == (cell.x, cell.y)]
    # The item's own identity binds only the vessel that item becomes; a raise on
    # any other square is an ordinary vessel of its own (see vessel_candidates).
    bound = item if _item_ready(item or {}, owner) and _item_square(item, cell) else None
    # Refused before the Cultivation Point is spent: a square with no suitable vessel or object cannot take one.
    if bound is None and not reclaim and not _suitable_object(engine, cell):
        ctx.rider("Raise the Vessel: that square holds no suitable puppet vessel or object.")
        return
    engine._spend_resource(owner, kit["pool"], 1, ctx.source)
    config = _config(owner)
    if bound is not None:
        config["form"] = "piercing" if config.get("cons") == "needle" else bound["form"]
    stats = _stats(kit, config.get("cons"))
    old = [zone for zone in reclaim if bound is None or placed.data(zone).get("item_instance_id") == bound["item_instance_id"]]
    hp = carried_hp(placed.data(old[0]), stats["hp"]) if old else int(bound.get("hp", stats["hp"])) if bound else stats["hp"]
    if old:
        placed.drop(engine, old[0], "RECLAIMED")
    active, limit = _capacity_group(engine,owner,kit,cell)
    while len(active) >= limit:
        oldest = active.pop(0)
        placed.reshape(engine, oldest, name=_name(owner, "inactive"), state="inactive")
        _log(engine, ctx.source, owner, f"{owner.display_name}'s older puppet vessel goes inactive: the thread moves to the new one.")
    zone = placed.place(engine, owner, source=kit["source"], tag="vessel", cells=cell, numbers=kit["numbers"], duration_rounds=ACTIVE_ROUNDS, name=_name(owner, "active"),
                 color="#b98a4a", material="generic", difficult="all",  # "creatures can move through its space as difficult terrain"
                 placed={"state": "active", "hp": hp, "max_hp": stats["hp"], "ac": stats["ac"], "speed": stats["speed"], "cons": config.get("cons"),
                         **({"item_instance_id": bound["item_instance_id"], "item_source_id": bound["source_id"]} if bound else {}),
                         **({"form":config.get('form') or ('piercing' if config.get('cons') == 'needle' else 'bludgeoning')} if kit.get('native') else {})})
    owner.turn_flags["vessel_free_move"] = not kit.get('native')
    _log(engine, ctx.source, owner, f"{owner.display_name} raises a puppet vessel at ({cell.x}, {cell.y}) (AC {stats['ac']}, {hp} HP, Speed {stats['speed']} ft, control range {_control(kit)} ft).")
    if kit.get('native'):
        _choose_vessel_move(ctx,kit,zone,stats['speed'],'Raise the Vessel','vessel_raise_move')


def carried_hp(data: dict[str, Any], fallback: int) -> int:
    """Hit Points a reclaimed vessel keeps: a stored 0 is real (a broken-down vessel), only a missing value falls back."""
    value = data.get("hp")
    return int(fallback if value is None else value)


def _name(owner: Any, state: str) -> str:
    return f"{owner.display_name}'s puppet vessel ({state}; creatures move through it as difficult terrain)"


@effect("vessel_move")
def move_vessel(ctx: Any, eff: dict[str, Any]) -> None:
    engine, owner = ctx.engine, ctx.actor
    kit, cell = _kit(engine, owner), getattr(ctx.intent, "destination", None)
    zone = _mover(engine, owner, kit, cell) if kit is not None and cell is not None else None
    if zone is None:
        ctx.rider("Move Vessel: no vessel of yours can walk to that square.")
        return
    if eff.get("free"):
        owner.turn_flags["vessel_free_move"] = False
    before = zone.center
    found = engine.grid.shortest_path(before,cell,occupied=_occupied(engine),max_cost_ft=int(placed.data(zone)['speed']))
    spent = found[1] if found else 0
    active = _vessels(engine,owner)
    total = max(int(placed.data(z)['speed']) for z in active) if active else 0
    placed.reshape(engine, zone, cells=cell)
    _log(engine, ctx.source, owner, f"{owner.display_name}'s puppet vessel walks from ({before.x}, {before.y}) to ({cell.x}, {cell.y}).")
    from . import run_strict
    if before != zone.center:
        run_strict("vessel_moved", ctx, zone, before)
    if kit.get('native') and not eff.get('free'):
        incarnation = _incarnation(owner)
        if incarnation or TWO_BODY in kit['owned']:
            remaining = max(0,total-spent)
            for other in active:
                if other.zone_id==zone.zone_id or placed.data(other).get('state')!='active':continue
                allowance = int(placed.data(other)['speed']) if incarnation else min(remaining,int(placed.data(other)['speed']))
                used = _choose_vessel_move(ctx,kit,other,allowance,
                    'Thousand-Puppet Incarnation' if incarnation else 'Two-Body Control','vessel_group_move')
                if not incarnation:remaining=max(0,remaining-used)


def _choose_vessel_move(ctx: Any, kit: Any, zone: Any, allowance: int, name: str, key: str) -> int:
    """Optional directed walking route, paid by the enclosing activation only.

    Placement paths use native walls/corners/terrain and creature occupancy.
    Each follow-up recomputes occupancy after earlier vessels have moved.
    """
    from ..gate2_runtime_models import Position
    from . import needle
    engine,owner = ctx.engine,ctx.actor
    occupied = _occupied(engine)
    options = {}
    for x in range(max(0,zone.center.x-allowance//5),zone.center.x+allowance//5+1):
        for y in range(max(0,zone.center.y-allowance//5),zone.center.y+allowance//5+1):
            cell=Position(x=x,y=y)
            if (x,y) in occupied or not placed.free_square(engine,cell) or _dist(engine,owner,cell)>_control(kit):continue
            if not engine._line_of_sight_actor_to_cell(owner,cell):continue
            path=engine.grid.shortest_path(zone.center,cell,occupied=occupied,max_cost_ft=allowance)
            if path is not None:options[needle.cell_id(cell)]=(cell,path[1])
    if not options:return 0
    selected=needle.ask(engine,ctx.intent,needle.checkpoint_id(engine,key,ctx.source,zone.zone_id),owner,
        'choice:needle.'+key,list(options),labels={k:f'({cell.x}, {cell.y}): {cost} feet' for k,(cell,cost) in options.items()},
        prompt=f'{name}: move your vessel at ({zone.center.x}, {zone.center.y}) up to {allowance} feet, or leave it here',
        name=name,target_id=owner.entity_id,maximum=1,minimum=0,allow_decline=True,default='decline',
        automatic=key != 'vessel_raise_move',
        prompt_context={'cost':'Included in this activation; no additional Action, Reaction or cultivation point cost'})
    if not selected:return 0
    cell,cost=options[selected[0]]
    before = zone.center
    placed.reshape(engine,zone,cells=cell)
    _log(engine,ctx.source,owner,f'{name}: your vessel moves to ({cell.x}, {cell.y}), using {cost} feet of its allowed movement.')
    from . import run_strict
    if before != zone.center:
        run_strict("vessel_moved", ctx, zone, before)
    return cost


@effect("vessel_dismiss")
def dismiss(ctx: Any, eff: dict[str, Any]) -> None:
    for zone in _vessels(ctx.engine, ctx.actor, ("active", "inactive")):
        placed.drop(ctx.engine, zone, "DISMISSED")
    _log(ctx.engine, ctx.source, ctx.actor, f"{ctx.actor.display_name} dismisses the puppet vessel.")


def break_vessel(engine: Any, zone: Any, owner: Any, source: str) -> None:
    was_threaded = placed.data(zone).get("state") == "active"
    placed.drop(engine, zone, "BROKEN")
    if was_threaded:
        run_strict("vessel_thread_ended", engine, owner, zone, "BROKEN")
    _log(engine, source, owner, f"{owner.display_name}'s puppet vessel is broken: the control thread ends.")


def damage_vessel(engine: Any, zone: Any, amount: int, source: str) -> None:
    """A vessel takes damage (Substitute Harm Body); at 0 Hit Points it is broken and the thread ends."""
    owner = engine.state.actors.get(zone.owner_id)
    if amount <= 0 or owner is None or not zone.active:
        return
    temp_hp = int(placed.data(zone).get("temp_hp") or 0)
    absorbed = min(temp_hp, amount)
    hp = max(0, int(placed.data(zone).get("hp") or 0) - (amount - absorbed))
    if absorbed:
        _log(engine, source, owner, f"{owner.display_name}'s puppet vessel uses {absorbed} temporary HP to absorb damage "
             f"({temp_hp - absorbed} temporary HP left).")
    _log(engine, source, owner, f"{owner.display_name}'s puppet vessel takes {amount} damage ({hp} HP left).")
    if hp <= 0:
        owned = _kit(engine,owner)
        if owned and owned.get('native'):
            placed.update(engine,zone,hp=0,temp_hp=temp_hp-absorbed)
        break_vessel(engine, zone, owner, source)
    else:
        placed.update(engine, zone, hp=hp, **({"temp_hp": temp_hp - absorbed} if temp_hp else {}))


# --------------------------------------------------------------------------------------------------------- the strike
@effect("vessel_strike")
def strike(ctx: Any, eff: dict[str, Any]) -> None:
    """The compiled strike's own effects, run for the chosen creature with the damage type of the vessel's form."""
    from ..typed_executor import run_effects

    engine, owner = ctx.engine, ctx.actor
    config = _config(owner)
    chosen = None
    if ctx.action.parameters.get("vessel_native_origin"):
        from ..action_geometry import record_for
        origin = record_for(engine,owner,ctx.source)
        chosen = engine.state.zones.get(str((origin or {}).get("id","")).removeprefix("vessel:"))
        if chosen is not None:
            config = {**config,"form":placed.data(chosen).get('form'),"cons":placed.data(chosen).get('cons')}
    form = config.get("form")
    if config.get("cons") == "needle" and form is None:
        form = "piercing"  # Needle Body: "Puppet Strike may deal Piercing damage"
    template = copy.deepcopy(eff.get("template") or [])
    if form:
        _retype(template, form,alternatives_only=bool(ctx.action.parameters.get('vessel_native_origin')))
    kit = _kit(engine, owner)
    target = ctx.target
    zone = chosen or (_striker(engine, owner, kit, target, _reach(ctx.action, config)) if kit is not None and target is not None else None)
    if zone is not None:
        _log(engine, ctx.source, owner, f"{owner.display_name}'s puppet vessel at ({zone.center.x}, {zone.center.y}) strikes {target.display_name}.", targets=(target,))
    if ctx.action.parameters.get("vessel_incarnation_free"):
        owner.turn_flags["vessel_incarnation_strike_used"] = 1
    if ctx.action.parameters.get('vessel_native_origin'):
        for row in _flat(template):
            if row.get('type') == 'mark' and row.get('mark') == MARK:
                row['duration'] = {'kind':'until_end_of_your_next_turn'}
    run_effects(ctx, template)
    actual_type = next((t for row in _flat(template) for t in (row.get("damage_types") or [])), None)
    last = actual_type if ctx.action.parameters.get('vessel_native_origin') else form or actual_type
    if last:
        if chosen is not None:
            placed.update(engine,chosen,last_type=str(last).lower())
        placed_config = {**_config(owner), "last_type": str(last).lower()}
        engine._remove_condition(owner, SETUP, ctx.source)
        engine._apply_condition(owner, SETUP, ctx.source, owner.entity_id, expires_on="UNTIL_REMOVED", data=placed_config)


def _flat(rows: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for row in rows or []:
        if isinstance(row, dict):
            found.append(row)
            for key in ("on_hit", "on_miss", "on_fail", "on_success", "effects"):
                found.extend(_flat(row.get(key)))
    return found


def _retype(rows: Any, form: str, *, alternatives_only: bool = False) -> None:
    for row in _flat(rows):
        types=row.get('damage_types') or []
        if row.get("type") == "damage" and types and (not alternatives_only or len(types)>1 and set(types)<=set(FORMS)):
            row["damage_types"] = [form]


# ------------------------------------------------------------------------------------------------------ tension responses
@effect("vessel_tension")
def tension(ctx: Any, eff: dict[str, Any]) -> None:
    from ..typed_executor import bears_mark, mark_condition_id, run_effects

    engine, owner = ctx.engine, ctx.actor
    kit, target, response = _kit(engine, owner), ctx.target, eff.get("response")
    if kit is None or target is None or not _response_ok(engine, owner, kit, str(response), target):
        ctx.rider("Tension Response: it needs a Tension Mark of yours in control range and a live control thread, and only one a turn.")
        return
    spent = target if response != "guard" else min(_marked(engine, owner, kit), key=lambda actor: (_dist(engine, owner, actor.position), actor.entity_id))
    if kit.get('native') and response == 'guard':
        from .rider_choices import pick
        marked=_marked(engine,owner,kit)
        picked=pick(engine,owner,'vessel_guard_mark','Guarding Vessel',[a.entity_id for a in marked],
            subject=target,labels={a.entity_id:a.display_name for a in marked},optional=False,
            trigger=f'Protect {target.display_name} with +2 AC against the next attack before your next turn; choose whose attached thread to spend',
            prompt_context={'cost':'Spend one attached Tension Mark; no Action, Reaction or cultivation point cost'})
        spent=engine.state.actors[picked[0]]
    if not bears_mark(spent, owner.entity_id, MARK):
        return
    engine._remove_condition(spent, mark_condition_id(MARK, owner.entity_id), ctx.source)  # "A Tension Response spends a Tension Mark"
    if _theater(owner) is not None and not owner.turn_flags.get("vessel_theater_response_used"):
        owner.turn_flags["vessel_theater_response_used"] = 1
    elif kit.get('native'):
        owner.turn_flags['vessel_responses_used'] = int(owner.turn_flags.get('vessel_responses_used') or 0) + 1
    else:
        owner.turn_flags["vessel_response_round_used"] = engine.state.round_number
    name = RESPONSES[str(response)]
    _log(engine, ctx.source, owner, f"{owner.display_name} spends a Tension Mark on {spent.display_name}: {name}.", targets=(target,))
    inner = placed.context(engine, owner, ctx.source, ctx.numbers, [target], action=ctx.action)
    inner.intent = ctx.intent
    inner.typed["vessel_tension"] = response
    if response == "tug":
        run_effects(inner, [{"type": "save", "ability": "str", "on_fail": [{"type": "vessel_tug"}]}])
    elif response == "cross":  # the engine reads the modifier at the target's next attack roll and uses it up (typed_executor.block_advantage)
        run_effects(inner, [{"type": "disadvantage", "applies_to": "target", "on": "its next attack roll", "duration": "until_end_of_turn"}])
        _log(engine, ctx.source, owner, f"{target.display_name}'s next attack roll has Disadvantage until the end of its next turn.", targets=(target,))
    elif response == "guard":
        from ..typed_executor import effect_expiry
        engine._remove_condition(target, GUARDED, ctx.source)
        expires=effect_expiry(ctx,{'expires_on':'START_OF_SOURCE_NEXT_TURN'},target,condition=True) if kit.get('native') else 'START_OF_SOURCE_NEXT_TURN'
        engine._apply_condition(target, GUARDED, ctx.source, owner.entity_id, expires_on=expires,
                                data={"label": f"Guarding Vessel: +2 AC against the next attack roll ({owner.display_name}'s vessel)"})
    else:  # "1d6 Force damage or the damage type dealt by the puppet vessel's last Puppetry attack": two buttons, Force by default
        last = (_config(owner).get("last_type") if response == "snap_last" else None) or "force"
        if kit.get('native') and response == 'snap_last':
            from .rider_choices import pick
            vessels=[z for z in _threaded(engine,owner,kit) if placed.data(z).get('last_type')]
            picked=pick(engine,owner,'vessel_snap_type','Snap the Thread',[z.zone_id for z in vessels],subject=target,optional=False,
                labels={z.zone_id:f"{placed.data(z)['last_type'].title()} — vessel at ({z.center.x}, {z.center.y})" for z in vessels},
                trigger=f'Snap the attached thread on {target.display_name}; choose a vessel’s last attack damage type',
                prompt_context={'cost':'Included in this Tension Response; no additional payment'})
            last=placed.data(engine.state.zones[picked[0]])['last_type']
        count = placed.cl_row(int(ctx.numbers.get("cl") or 1), SNAP_DICE)
        run_effects(inner, [{"type": "damage", "applies_to": "target", "dice": {"count": count, "sides": 6}, "flat": 0, "formula": "none",
                             "damage_types": [last]}])


@effect("vessel_tug")
def tug(ctx: Any, eff: dict[str, Any]) -> None:
    """A failed Strength save: the owner chooses a visible legal square 5 feet away.

    The shared choice transport asks players; automatic owners retain the nearest-vessel preference.
    """
    engine, owner, target = ctx.engine, ctx.actor, ctx.target
    if target is None or not target.active:
        return
    kit = _kit(engine, owner)
    if kit is None:
        return
    vessels = _threaded(engine, owner, kit)
    goal = vessels[0].center if vessels else owner.position
    from ..gate2_runtime_models import Position

    occupied = engine._occupied_cells_except(target.entity_id) | _vessel_cells(engine)
    cells = []
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            cell = map_position(engine, target.position.x + dx, target.position.y + dy)
            if cell is None:
                continue
            if (dx or dy) and engine.grid.step_legal(target.position, cell, occupied_cells=occupied,
                    footprint=engine._footprint(target)) and engine._line_of_sight_actor_to_cell(owner, cell):
                cells.append(cell)
    if not cells:
        _log(engine, ctx.source, owner, f"{target.display_name} has no free square to be tugged into.", targets=(target,))
        return
    from . import needle

    cells.sort(key=lambda cell: (engine.grid.distance_ft(goal, cell), cell.x, cell.y))
    by_id = {needle.cell_id(cell): cell for cell in cells}
    selected = needle.ask(engine, ctx.intent,
        needle.checkpoint_id(engine, "VESSEL_TUG", ctx.source, target.entity_id), owner,
        "choice:needle.vessel_tug", list(by_id),
        labels={key: f"({cell.x}, {cell.y})" for key, cell in by_id.items()},
        prompt=f"Tug the Joint: {ctx.action.display_name} — move {target.display_name} 5 feet to which space?",
        name="Tug the Joint", target_id=target.entity_id, maximum=1)
    if not selected:
        return
    cell = by_id[selected[0]]
    shift(engine, target, cell, ctx.source)
    _log(engine, ctx.source, owner, f"{target.display_name} is tugged to ({cell.x}, {cell.y}) by the thread.", targets=(target,))


def shift(engine: Any, actor: Any, cell: Any, source: str) -> None:
    """Forced movement or a swap: the creature is set on the square (no opportunity attacks) and its zones are told."""
    from .. import zones

    before = actor.position
    actor.position = cell
    engine._append_event("MOVEMENT_COMMITTED", source, actor_id=actor.entity_id,
                         payload={"destination": cell.model_dump(mode="json"), "path": [before.model_dump(mode="json"), cell.model_dump(mode="json")],
                                  "cost_ft": 0, "forced": True})
    zones.on_moved(engine, actor, before, cell, forced=True)


@hook("save")
def tug_save(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    """"A target at least two sizes larger than your puppet vessel has Advantage on saving throws against being moved": a vessel is
    at most Medium, so a Huge (three squares wide) or bigger target."""
    if (getattr(ctx, "typed", None) or {}).get("vessel_tension") != "tug":
        return None
    return {"bonus": 0, "modes": ["ADVANTAGE"]} if ctx.engine._footprint(subject).width_cells >= 3 else None


@hook("ac")
def guarded_ac(engine: Any, target: Any) -> int | None:
    return 2 if any(condition.condition_id == GUARDED for condition in target.conditions.values()) else None


# --------------------------------------------------------------------------------------------------------- the substitutes
@hook("row_allowed")
def substitute_rows(engine: Any, actor: Any, row: dict[str, Any]) -> bool | None:
    feature = row.get("feature_id")
    if feature not in (HARM_BODY, SUBSTITUTION, SPARE_BODY):
        return None
    kit = _kit(engine, actor)
    if kit is None:
        return False
    if feature == SPARE_BODY:  # "an active puppet vessel within control range"
        return any(_dist(engine, actor, zone.center) <= _control(kit) for zone in _vessels(engine, actor))
    reach = HARM_FT if feature == HARM_BODY else SWAP_FT  # "within 30 feet" / "within 60 feet"
    return any(_dist(engine, actor, zone.center) <= reach for zone in _vessels(engine, actor))


@hook("event")
def harm_reduced(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """Substitute Harm Body: "Your puppet vessel takes the same amount of damage that was reduced"; the vessel is dented after the
    reaction resolves (the reduction is only known then).  An attack roll against a Guarded creature spends Guarding Vessel."""
    if event_type == "ATTACK_ROLLED":
        for target_id in kwargs.get("target_ids") or ():
            holder = engine.state.actors.get(target_id)
            for iid, condition in list((holder.conditions if holder else {}).items()):
                if condition.condition_id == GUARDED:
                    del holder.conditions[iid]
                    engine._append_event("CONDITION_REMOVED", condition.source_definition_id, actor_id=condition.source_actor_id, target_ids=(holder.entity_id,),
                                         payload={"condition_id": GUARDED, "instance_id": iid})
        return None
    if event_type != "REACTION_RESOLVED" or engine.events[-1].source_definition_id != HARM_BODY:
        return None
    reduction = int((kwargs.get("payload") or {}).get("reduction") or 0)
    owner = engine.state.actors.get(kwargs.get("actor_id") or "")
    owned = _kit(engine,owner) if owner is not None else None
    if owned and owned.get('native'):
        return None  # New kits transfer damage at the strict lifecycle checkpoint.
    near = [zone for zone in _vessels(engine, owner) if _dist(engine, owner, zone.center) <= HARM_FT] if owner is not None else []
    if near and reduction > 0:
        damage_vessel(engine, min(near, key=lambda zone: (_dist(engine, owner, zone.center), zone.zone_id)), reduction, HARM_BODY)
    return None


@effect("vessel_swap")
def swap(ctx: Any, eff: dict[str, Any]) -> None:
    """Marionette Substitution Body: "switch positions with one active puppet vessel within 60 feet ... the vessel moves to your former
    space".  The triggering attack is then aimed at a vessel that is not a legal target (an object the table does not attack): the row's
    Disadvantage / Advantage effects apply."""
    engine, owner = ctx.engine, ctx.actor
    kit = _kit(engine, owner)
    near = [zone for zone in _vessels(engine, owner) if _dist(engine, owner, zone.center) <= SWAP_FT] if kit is not None else []
    if not near:
        return
    zone = min(near, key=lambda z: (_dist(engine, owner, z.center), z.zone_id))
    if engine._footprint(owner).width_cells > 1:
        _log(engine, ctx.source, owner, "The vessel cannot take the place of a creature larger than one square: the swap does not happen.")
        return
    here, there = owner.position, zone.center
    shift(engine, owner, there, ctx.source)
    placed.reshape(engine, zone, cells=here)
    _log(engine, ctx.source, owner, f"{owner.display_name} swaps places with the puppet vessel: now at ({there.x}, {there.y}); the vessel is at ({here.x}, {here.y}).")


@effect("vessel_spare")
def spare_body(ctx: Any, eff: dict[str, Any]) -> None:
    """Heaven's Spare Body: the vessel is destroyed and "you are reduced to 1 Hit Point instead" (the row's hold_at_1hp); then "move to the
    destroyed vessel's space"."""
    engine, owner = ctx.engine, ctx.actor
    kit = _kit(engine, owner)
    near = [zone for zone in _vessels(engine, owner) if kit is not None and _dist(engine, owner, zone.center) <= _control(kit)]
    if not near:
        return
    zone = min(near, key=lambda z: (_dist(engine, owner, z.center), z.zone_id))
    cell = zone.center
    placed.drop(engine, zone, "SPARED")
    _log(engine, ctx.source, owner, f"{owner.display_name}'s puppet vessel shatters in their place: they stay at 1 HP and step into its square.")
    if engine._footprint(owner).width_cells <= 1 and not placed.occupied(engine, cell):
        shift(engine, owner, cell, ctx.source)


# ------------------------------------------------------------------------------------------------ Puppet Theater Domain
def _theater(owner: Any) -> Any | None:
    return next((c for c in owner.conditions.values() if c.condition_id == THEATER_ACTIVE), None)


@effect("vessel_theater")
def establish_theater(ctx: Any, eff: dict[str, Any]) -> None:
    """Printed Domain grant: existing vessels get twice PB temporary HP.

    The native minute duration owns expiry. Turn-start marks and one additional
    basic Tension Response use this retained, owned activation; casting never
    marks or restrains a creature. Replacement uses the ordinary temporary-HP
    maximum, rather than stacking two grants (D&D 5.5e default).
    """
    from .ability_source import mechanic_of
    from ..typed_executor import effect_expiry

    kit = _kit(ctx.engine, ctx.actor)
    if kit is None or THEATER not in kit["owned"] or mechanic_of(ctx.action) != THEATER:
        return
    ctx.engine._apply_condition(ctx.actor, THEATER_ACTIVE, ctx.source, ctx.actor.entity_id,
        expires_on=effect_expiry(ctx, eff, ctx.actor, condition=True), data={
            "label": ("Puppet Theater Domain (1 minute): three vessels inside 30 feet; nearby enemies gain attached threads; one extra response each turn; a broken vessel can restrain one nearby enemy" if eff.get('native_vessels') else "Puppet Theater Domain (1 minute): nearby enemies gain attached threads for your Tension Responses; one extra response each turn"),
            **({"native_theater":1} if eff.get("native_vessels") else {}),
        })
    grant = 2 * int(ctx.numbers.get("pb") or ctx.actor.proficiency_bonus)
    for zone in _vessels(ctx.engine, ctx.actor):
        placed.update(ctx.engine, zone, temp_hp=max(grant, int(placed.data(zone).get("temp_hp") or 0)))
    _log(ctx.engine, ctx.source, ctx.actor,
         f"Puppet Theater Domain: {ctx.actor.display_name}'s active vessels gain {grant} temporary HP. "
         "For 1 minute, enemies starting within 5 feet of them gain a Tension Mark (a thread attached to that enemy), "
         "and one basic Tension Response each turn does not use the normal response limit.")


@effect("vessel_incarnation")
def establish_incarnation(ctx: Any, eff: Any) -> None:
    from .ability_source import mechanic_of
    from ..typed_executor import effect_expiry
    owned = _kit(ctx.engine,ctx.actor)
    if not owned or INCARNATION not in owned['owned'] or mechanic_of(ctx.action) != INCARNATION:
        return
    ctx.engine._apply_condition(ctx.actor,INCARNATION_ACTIVE,ctx.source,ctx.actor.entity_id,
        expires_on=effect_expiry(ctx,eff,ctx.actor,condition=True),data={
            'native_incarnation':1,'label':'Thousand-Puppet Incarnation (1 minute): up to five vessels, one free strike and two Tension Responses each turn; a broken vessel explodes'})


@hook("state_event")
def vessel_native_lifecycle(engine: Any, event: Any) -> None:
    if event.event_type in ('ZONE_CREATED', 'ZONE_REMOVED'):
        zone = engine.state.zones.get(event.payload.get('zone_id') or (event.payload.get('zone') or {}).get('zone_id'))
        if zone is not None and placed.data(zone).get('item_instance_id'):
            owner = engine.state.actors.get(zone.owner_id)
            kit = _kit(engine, owner) if owner else None
            if kit and kit.get('initiation'):
                data = placed.data(zone)
                item = _prepared_item(owner, kit)
                if item.get('item_instance_id') == data['item_instance_id']:
                    item.update(hp=int(data['hp']), x=zone.center.x, y=zone.center.y, z=zone.center.z,
                                broken=int(bool(item.get('broken')) or event.payload.get('reason') in ('BROKEN', 'SPARED')))
                    state = ('broken' if item['broken'] else 'inactive') if event.event_type == 'ZONE_REMOVED' else data.get('state', 'active')
                    item['label'] = (f"Basic {item['form']} puppet vessel: {item['hp']} HP at square "
                                     f"({item['x']}, {item['y']}); {state}. "
                                     + ("It cannot be raised while broken." if item['broken'] else
                                        "Raising it costs an Action and 1 Cultivation Point; its control thread lasts 1 minute."))
                    # Each change advances the item's state revision, so a stale
                    # parallel encounter cannot replace this committed state later.
                    item['parent_lineage'] = str(item.get('lineage') or '')
                    item['state_revision'] = int(item.get('state_revision') or 0) + 1
                    # Heaven's Spare Body sacrifices the vessel for good: that removal is final, like a break.
                    item['lineage'] = hashlib.sha256(f"{item['parent_lineage']}|{item['state_revision']}|{item['hp']}|{item['broken']}|{item.get('x')},{item.get('y')},{item.get('z')}".encode()).hexdigest()[:32]
                    # Every lineage this encounter has passed through, oldest first. The durable product may be
                    # replaced only from an encounter whose ancestry contains it (see journey.update_preparation).
                    item['ancestry'] = str(item.get('ancestry') or item['parent_lineage']) + ',' + item['lineage']
                    # Only persist primitives, including the original source
                    # and owner identity; source text grants no repair benefit.
                    engine._apply_condition(owner, PREPARED_ITEM, kit['source'], owner.entity_id,
                        expires_on='UNTIL_REMOVED', data={k:v for k,v in item.items() if type(v) in (int,str)})
    if event.event_type == 'REACTION_RESOLVED' and event.source_definition_id == HARM_BODY:
        owner = engine.state.actors.get(event.actor_id)
        owned = _kit(engine,owner) if owner else None
        if owned and owned.get('native'):
            near = [z for z in _vessels(engine,owner) if _dist(engine,owner,z.center) <= HARM_FT]
            if near:
                damage_vessel(engine,min(near,key=lambda z:(_dist(engine,owner,z.center),z.zone_id)),
                    int(event.payload.get('reduction') or 0),HARM_BODY)
        return
    if event.event_type in ('CONDITION_REMOVED','MOVEMENT_COMMITTED','ZONE_CREATED'):
        if getattr(engine,'_vessel_capacity_sweeping',False):return
        engine._vessel_capacity_sweeping = True
        try:
            for owner in engine.state.actors.values():
                owned = _kit(engine,owner)
                if not owned or not owned.get('native'):continue
                active, limit = _capacity_group(engine,owner,owned)
                theater = _theater(owner)
                pools = [(active,limit)]
                if not _incarnation(owner) and theater and theater.data.get('native_theater') == 1:
                    pools = [([z for z in active if _dist(engine,owner,z.center)<=30],3),
                             ([z for z in active if _dist(engine,owner,z.center)>30],_limit(owned))]
                for group, maximum in pools:
                    for zone in group[:max(0,len(group)-maximum)]:
                        placed.reshape(engine,zone,name=_name(owner,'inactive'),state='inactive')
        finally:
            engine.__dict__.pop('_vessel_capacity_sweeping',None)
        return
    if event.event_type != 'ZONE_REMOVED' or event.payload.get('reason') != 'BROKEN':return
    zone = engine.state.zones.get(event.payload.get('zone_id'))
    if zone is None or placed.data(zone).get('tag') != 'vessel':return
    owner = engine.state.actors.get(zone.owner_id)
    owned = _kit(engine,owner) if owner else None
    if not owned:return
    targets = [a for a in engine.state.actors.values() if a.active and a.team_id != owner.team_id
               and engine._distance_actor_to_cell(a,zone.center) <= 5]
    theater, incarnation = _theater(owner), _incarnation(owner)
    from .rider_choices import pick, trigger_name
    from ..typed_executor import run_effects
    if theater and theater.data.get('native_theater') == 1 and targets:
        chosen = pick(engine,owner,'vessel_theater_broken','Puppet Theater Domain',[a.entity_id for a in targets],
            subject=owner,labels={a.entity_id:a.display_name for a in targets},optional=False,
            trigger=f'After {trigger_name(engine)}, your vessel breaks at 0 Hit Points. Choose one hostile creature '
                'within 5 feet of it to make a Dexterity saving throw; on a failure, it becomes Restrained '
                "(unable to move, easier to hit, and attacking with Disadvantage) until the end of that creature's next turn. "
                'No Action, Reaction or additional cultivation points are spent',
            prompt_context={'cost':'No Action, Reaction or additional cultivation point cost'})
        if chosen:
            ctx = placed.context(engine,owner,theater.source_definition_id,owned['numbers'],[engine.state.actors[chosen[0]]])
            run_effects(ctx,[{'type':'save','ability':'dex','on_fail':[{'type':'condition','condition':'restrained',
                'expires_on':'END_OF_HOLDER_NEXT_TURN','condition_label':'Puppet Theater Domain: collapsing threads restrain you until the end of your next turn'}]}])
    if incarnation and targets:
        chosen = pick(engine,owner,'vessel_explosion_type','Thousand-Puppet Incarnation',['piercing','force'],subject=owner,
            labels={'piercing':'3d8 Piercing damage','force':'3d8 Force damage'},optional=False,
            trigger=f'After {trigger_name(engine)}, your vessel breaks at 0 Hit Points. Choose Piercing or Force damage: '
                'each hostile creature within 5 feet of it makes a Dexterity saving throw; on a failure, '
                'it takes 3d8 Piercing or Force damage of your chosen type and gains a Tension Mark '
                'that you can spend for a Tension Response, until the end of your next turn. '
                f"Affected creatures: {', '.join(a.display_name for a in targets)}. "
                'No Action, Reaction or additional cultivation points are spent',
            prompt_context={'cost':'No Action, Reaction or additional cultivation point cost'})
        ctx = placed.context(engine,owner,incarnation.source_definition_id,owned['numbers'],targets)
        run_effects(ctx,[{'type':'save','ability':'dex','applies_to':'target','on_fail':[
            {'type':'damage','dice':{'count':3,'sides':8},'damage_types':chosen},
            {'type':'mark','mark':MARK,'duration':{'kind':'until_end_of_your_next_turn'}}]}])


@hook("turn_start")
def theater_marks(engine: Any, actor: Any) -> None:
    from ..typed_executor import bears_mark, run_effects

    if not actor.active:
        return
    for owner in engine.state.actors.values():
        active = _theater(owner) if owner.active else None
        kit = _kit(engine, owner) if active is not None else None
        if kit is None or THEATER not in kit["owned"] or actor.team_id == owner.team_id:
            continue
        if bears_mark(actor, owner.entity_id, MARK) or not any(
            engine._distance_actor_to_cell(actor, zone.center) <= 5 for zone in _vessels(engine, owner)
        ):
            continue
        ctx = placed.context(engine, owner, active.source_definition_id, kit["numbers"], [actor])
        run_effects(ctx, [{"type": "mark", "mark": MARK, "applies_to": "target",
                          "duration": {"kind": "until_end_of_your_next_turn"}}])
        _log(engine, active.source_definition_id, owner,
             f"Puppet Theater Domain: {actor.display_name} starts near {owner.display_name}'s vessel and gains a Tension Mark.", [actor])


# ---------------------------------------------------------------------------------------------------------------- turns
@hook("turn_end")
def turn_end(engine: Any, actor: Any) -> None:
    kit = _kit(engine, actor)
    if kit is None:
        return
    for zone in _vessels(engine, actor):
        if _dist(engine, actor, zone.center) > _control(kit):  # "a control thread ends if the vessel is outside your control range at the end of your turn"
            placed.reshape(engine, zone, name=_name(actor, "inactive"), state="inactive")
            run_strict("vessel_thread_ended", engine, actor, zone, "OUT_OF_RANGE")
            _log(engine, kit["source"], actor, f"{actor.display_name}'s puppet vessel is outside the {_control(kit)}-foot control range: the thread ends.")

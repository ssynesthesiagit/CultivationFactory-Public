"""The higher Formations talents (Sphere Compendium, Formations).  Built on combat/ext/formations.py (the array, its Eye and Nodes,
Pulse Array, the six Basic Patterns) and combat/ext/formation_talents.py (the setup toggles).  Owner's text first; nothing is invented.

  Sovereign Pulse     2 CP: Pulse a second, different layer of the same array in the same turn (the second Pulse)   (CL 10)
  Harmonized Pulse    1 CP with a Pulse of an array with two or more layers: strengthen one pattern's Passive until your next turn
  Elemental Killing   the Killing Line's Pulse gains a rider (fire, water, sand, lightning, radiance, shadow, blood, force)
  Spirit-Lock Array   a failed Sealing Gate save also blocks summon, dismiss, banish, possess, transport and teleport
  Eye of the Master   you are an auxiliary Eye: a Reaction and 2 CP keep the array up when its Eye would go, and mark you
  Court of the Ninefold Array      Domain: an Eye and nine Nodes, two layers, a free Pulse each turn, Node moves and their damage
  Sovereign of the World-Diagram   Domain: a 60-foot Emanation around you, three layers, a free Pulse and a paid second Pulse
  Mountain-Sealing Great Array     four Anchors, a Charisma save to teleport, a leave save for hostiles, a summoning check
  Turn the Battlefield Inside Out  keyed allies swap places with hostile creatures that fail a Wisdom save

Domains are not "arrays" for Formation Load ("Domain" talents are their own thing); each is a formations.KEY zone whose record
carries ``domain``, so everything the array does (Pulse, Passives, Eye and Node objects, collapse) works on it unchanged.
Not automated: see the notes in each function (Sovereign Nodes, planar travel, possession).


Shared helpers used by formation_riders: incapacitated checks action-denying conditions; Formation master actions retain their existing own-row guards.
"""

from __future__ import annotations

from ..paid_relocation import activation

import dataclasses
import math
from typing import Any

from . import effect, hook
from . import formations as F
from . import formation_talents as T

DOMAIN_LAYERS = {"court": 2, "sovereign": 3}
COURT_RADIUS_FT, SOVEREIGN_RADIUS_FT, MOUNTAIN_RADIUS_FT = 40, 60, 30
COURT_RANGE_FT = MOUNTAIN_RANGE_FT = 120
NODE_MOVE_FT = 10
# Elemental Killing Array: "choose one sphere you know that has a clear ... damage expression"; the rider it gives (once per turn).
ELEMENTS = {
    "fire": ("Fire or Ash", "the target cannot regain Hit Points until the start of your next turn"),
    "water": ("Water or Ice", "the target's Speed is reduced by 10 feet until the start of your next turn"),
    "sand": ("Sand or Earth", "the target cannot Dash until the start of your next turn"),
    "lightning": ("Lightning or Thunder", "the target cannot take Reactions until the start of your next turn"),
    "radiance": ("Radiance", "the target gains no benefit from being Invisible until the start of your next turn"),
    "shadow": ("Shadow or Dark", "the target has Disadvantage on its next Wisdom (Perception) check"),
    "blood": ("Blood or Poison", "the target has Disadvantage on its next Constitution saving throw"),
    "force": ("Force", "the target is pushed 5 feet along a Flow Line if it is Large or smaller"),
}
F.REPLACED.update({"court_of_the_ninefold_array", "sovereign_of_the_world_diagram", "mountain_sealing_great_array", "turn_the_battlefield_inside_out",
                   "sovereign_pulse", "harmonized_pulse", "elemental_killing_array", "eye_of_the_formation_master", "spirit_lock_array"})


def incapacitated(who: Any) -> bool:
    from ..typed_executor import condition_rules

    return any(row.get("no_actions") for row in condition_rules(who))


def _say(engine: Any, source: str, actor_id: str | None, text: str) -> None:
    F.say(engine, source, actor_id, text)


def has_pattern(numbers: dict[str, Any], pattern: str) -> bool:
    talent = F.PATTERNS[pattern].get("talent")
    return not talent or str(talent) in F.talents_of(numbers)


# ------------------------------------------------------------------------------------------------ compile
def _pulse_variants(info: dict[str, Any], numbers: dict[str, Any], pool: str, talents: set[str], cl: int) -> list[Any]:
    out: list[Any] = []
    court = "court_of_the_ninefold_array" in talents and cl >= 12
    sovereign = "sovereign_of_the_world_diagram" in talents and cl >= 15
    second = ("sovereign_pulse" in talents and cl >= 10) or sovereign
    for pattern in F.known_patterns(info):
        for mode, words, kind, whom in F.pulse_rows(pattern):
            if court or sovereign:  # "once during each of your turns, you may Pulse one Pattern Layer without using an action"
                out.append(F.pulse_action(info["short"], info["actor_id"], numbers, pattern, mode, words, kind, whom, variant="free"))
            if second:  # "you may spend 2 CP to Pulse a second Pattern Layer during the same turn"
                out.append(F.pulse_action(info["short"], info["actor_id"], numbers, pattern, mode, words, kind, whom, variant="second", costs=((pool, 2),)))
    return out


@hook("compile_actions")
def compile_actions(info: dict[str, Any]) -> list[Any] | None:
    if F.BASE_SET not in (info.get("owned_ids") or []) and F.SPHERE not in (info.get("spheres") or []):
        return None
    talents = set(F.owned_talents(info))
    cl = int(info["numbers"].get("cl") or 1)
    pool = F.pool_of(info)
    numbers = {**info["numbers"], "formation_talents": sorted(talents), "formation_pool": pool}
    out = _pulse_variants(info, numbers, pool, talents, cl)
    court, sovereign = "court_of_the_ninefold_array" in talents and cl >= 12, "sovereign_of_the_world_diagram" in talents and cl >= 15
    if court or sovereign:
        for pattern in F.known_patterns(info):
            for damage_type in (F.killing_types(info) if pattern == "killing_line" else (None,)):
                label = F.PATTERNS[pattern]["name"] + (f" ({damage_type.title()})" if damage_type else "")
                out.append(T.build_action(info, numbers, f"setup.domain.{pattern}" + (f".{damage_type}" if damage_type else ""), f"Next Domain: layer {label}", "NONE", "SELF", None,
                                     [{"type": "formation_setup", "op": "domain_layer", "pattern": pattern, "damage_type": damage_type,
                                       "evidence": "Court of the Ninefold Array and Sovereign of the World-Diagram: choose the Pattern Layers the Domain gains"}], "setup"))
    if "elemental_killing_array" in talents and cl >= 5:
        for element, (name, effect) in ELEMENTS.items():
            out.append(T.build_action(info, numbers, f"setup.element.{element}", f"Next Killing Line: {name}", "NONE", "SELF", None,
                                 [{"type": "formation_setup", "op": "element", "element": element,
                                   "evidence": "Elemental Killing Array: when you create a Killing Line Pattern, choose the sphere whose extra effect it gains"}], "setup",
                                 extra={"description": f"Give your next Killing Line the {name} sphere's extra effect — {effect}. It applies at most once per turn."}))
    if "harmonized_pulse" in talents and cl >= 5:
        for pattern in F.known_patterns(info):
            out.append(T.build_action(info, numbers, f"harmonize.{pattern}", f"Harmonized Pulse: strengthen {F.PATTERNS[pattern]['name']}", "NONE",
                                 "ALLY_OR_SELF" if pattern == "veiled_road" else "SELF", F.PULSE_RANGE_FT if pattern == "veiled_road" else None,
                                 [{"type": "formation_harmonize", "pattern": pattern,
                                   "evidence": "Harmonized Pulse: spend 1 CP to strengthen one Pattern's Passive until the start of your next turn"}],
                                 "harmonize", costs=((pool, 1),), extra={"pattern": pattern,
                                     "description": ("Spend 1 CP to strengthen this layered array until your next turn: " + {
                                         "locking_gate": "hostile creatures spend 5 extra feet of movement for each 5 feet moved inside.",
                                         "suppressing_vein": "the first hostile creature spending CP inside makes a Charisma save or loses 1 more CP.",
                                     }.get(pattern, f"enhance the {F.PATTERNS[pattern]['name']} Passive."))}))
    if court:
        out.append(_domain_action(info, numbers, pool, "court", "Court of the Ninefold Array", "ACTION", "CELL", COURT_RANGE_FT, 8, True, COURT_RADIUS_FT, "sphere"))
        out.append(T.build_action(info, numbers, "court.node", "Court: move a Node", "NONE", "CELL", F.PULSE_RANGE_FT,
                             [{"type": "formation_court_node", "evidence": "Court of the Ninefold Array: when a hostile creature fails a saving throw against one of the Court's Pulses, you may move one Node up to 10 feet"}],
                             "court_node", extra={"any_cell": True}))
    if sovereign:
        out.append(_domain_action(info, numbers, pool, "sovereign", "Sovereign of the World-Diagram", "BONUS_ACTION", "SELF", None, 10, False, SOVEREIGN_RADIUS_FT, "emanation"))
    if "mountain_sealing_great_array" in talents and cl >= 15:
        out.append(_domain_action(info, numbers, pool, "mountain", "Mountain-Sealing Great Array", "ACTION", "CELL", MOUNTAIN_RANGE_FT, 9, True, MOUNTAIN_RADIUS_FT, "sphere"))
    if "turn_the_battlefield_inside_out" in talents and cl >= 15:
        out.append(T.build_action(info, numbers, "turn", "Turn the Battlefield Inside Out", "ACTION", "CELL", F.PULSE_RANGE_FT,
                             [{"type": "formation_turn", "evidence": "Turn the Battlefield Inside Out: keyed allies swap places with hostile creatures that fail a Wisdom saving throw"}],
                             "turn", costs=((pool, 7), ("resource:uses.formation_turn", 1)), extra={"any_cell": True}))
    return out or None


def _domain_action(info: dict[str, Any], numbers: dict[str, Any], pool: str, kind: str, name: str, economy: str, target: str, range_ft: int | None,
                   cost: int, concentration: bool, radius_ft: int, shape: str) -> Any:
    """The action that sets a Domain (Court, Sovereign, Mountain-Sealing): the zone is made from ``zone_spec`` before its effect runs."""
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    spec = {"name": name, "shape": shape, "size_ft": radius_ft, "color": {"court": "#7e57c2", "sovereign": "#ffb300", "mountain": "#8d6e63"}[kind],
            "terrain": [], "difficult": "hostile" if kind == "court" else None, "triggers": [], "inside": [], "visual": {"material": "glyphs"},
            "duration": {"kind": "minutes", "amount": 1, "concentration": concentration}}
    if kind == "sovereign":
        spec.update({"centered_on_self": True, "follows_owner": True})
    typed = {"effects": [{"type": "formation_domain", "kind": kind, "evidence": f"{name}: the Domain's Eye, Nodes and layers"}], "numbers": dict(numbers),
             "duration": {"kind": "minutes", "amount": 1, "concentration": concentration}, "zone_spec": spec, "riders": [], "source": "formation_domain",
             "sphere": F.SPHERE, "typing_status": "formation_plugin", "coverage": "FULL"}
    return ActionDefinition(
        source_definition_id=f"action:typed.{info['short']}.formation.domain.{kind}", display_name=name, owner_id=info["actor_id"], economy=EconomyKind[economy],
        resolution_kind="TYPED", target_kind=target, range_ft=range_ft, costs=((pool, cost), (f"resource:uses.formation_{kind}", 1)), concentration=concentration,
        parameters={"typed": typed, "expected_damage": 0, "player_only": True, "any_cell": target == "CELL", F.TAG: "domain", "domain": kind,
                    **({"description": "Create a sealing array with four Anchors: movement out, teleportation and summoning require checks, and destroying two Anchors collapses it."} if kind == "mountain" else {})})


# ------------------------------------------------------------------------------------------------ legality
def _my_arrays(engine: Any, actor: Any) -> list[Any]:
    return F.arrays(engine, actor.entity_id)


def _pulsed_zone(engine: Any, actor: Any) -> Any:
    pulsed = actor.turn_flags.get("formation_pulsed") or {}
    zone = engine.state.zones.get(pulsed.get("zone") or "")
    return zone if zone is not None and zone.active and F.record(zone) else None


def harmonizable(engine: Any, actor: Any, pattern: str) -> Any:
    """The array Harmonized Pulse would strengthen: the one just Pulsed, else one of the actor's with two or more layers that carries the pattern
    (a Pulse is coming: the Bonus Action is free).  None when there is no such array, or the actor has Harmonized this turn."""
    if actor.turn_flags.get("formation_harmonized"):
        return None
    zone = _pulsed_zone(engine, actor)
    if zone is None and actor.bonus_action_available:
        zone = next((row for row in _my_arrays(engine, actor) if len(F.record(row).get("layers") or []) >= 2 and pattern in (F.record(row).get("layers") or [])), None)
    if zone is None or len(F.record(zone).get("layers") or []) < 2 or pattern not in (F.record(zone).get("layers") or []):
        return None
    return zone


def court_node_for(engine: Any, actor: Any, aim: Any) -> tuple[Any, Any] | None:
    """(Court, its Node) that a Node move to this square would use: a Court of the actor's holding the square, and the live Node nearest to it
    within 10 feet."""
    if aim is None:
        return None
    for zone in _my_arrays(engine, actor):
        if F.record(zone).get("domain") != "court" or (aim.x, aim.y) not in F.cells_of(zone):
            continue
        nodes = [node for node in (engine.state.objects.get(oid) for oid in F.record(zone).get("nodes") or []) if node is not None and not node.destroyed
                 and engine.grid.distance_ft(node.position, aim) <= NODE_MOVE_FT and (node.position.x, node.position.y) != (aim.x, aim.y)]
        if nodes:
            return zone, min(nodes, key=lambda node: engine.grid.distance_ft(node.position, aim))
    return None


@hook("candidate_allowed")
def candidate_allowed(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if action is None:
        return None
    tag = (action.parameters or {}).get(F.TAG)
    if tag == "harmonize":
        pattern = action.parameters["pattern"]
        zone = harmonizable(engine, actor, pattern)
        if zone is None:
            return False
        if pattern == "veiled_road":  # "one keyed ally inside gets Half Cover"
            ally = engine.state.actors.get(candidate.target_ids[0]) if candidate.target_ids else None
            return None if ally is not None and F.keyed(engine, zone, ally) and F.inside(engine, ally, zone) else False
        return None
    if tag == "court_node":
        return None if actor.turn_flags.get("formation_court_move") and court_node_for(engine, actor, candidate.destination) is not None else False
    if tag == "turn":
        zone = F.array_at(engine, actor, candidate.destination) if candidate.destination is not None else None
        return None if zone is not None and swaps_for(engine, zone) else False
    if tag == "domain":
        return None if not actor.turn_flags.get("formation_domain_blocked") else False
    return None


def swaps_for(engine: Any, zone: Any) -> list[tuple[Any, Any]]:
    """(keyed ally, hostile creature) pairs for Turn the Battlefield Inside Out: "any number of keyed allies inside the array and up to the same
    number of hostile creatures inside it".  The pairs are chosen for the owner (the hostile farthest from the Eye with the ally nearest it: the
    exchange pulls the enemy into the heart of the formation and sends the ally to the edge)."""
    owner = engine.state.actors.get(zone.owner_id)
    inside = [row for row in engine.state.actors.values() if row.active and F.inside(engine, row, zone)]
    allies = sorted((row for row in inside if row is not owner and F.keyed(engine, zone, row)), key=lambda row: engine.grid.distance_ft(row.position, zone.center))
    foes = sorted((row for row in inside if F.hostile_to(engine, zone, row)), key=lambda row: -engine.grid.distance_ft(row.position, zone.center))
    return list(zip(allies, foes))


# ------------------------------------------------------------------------------------------------ Domains
def default_layers(numbers: dict[str, Any], chosen: list[Any], count: int) -> list[tuple[str, str | None]]:
    """The layers a Domain gets: what the owner chose (``Next Domain: layer ...``), then the first patterns she knows to fill the number
    the talent grants (two, three).  Killing Line takes Force when nothing says otherwise."""
    picked: list[tuple[str, str | None]] = []
    for row in chosen:
        pattern, kind = str(row[0]), row[1] if len(row) > 1 else None
        if pattern in F.PATTERNS and pattern not in [p for p, _ in picked] and has_pattern(numbers, pattern) and len(picked) < count:
            picked.append((pattern, kind))
    for pattern in F.PATTERNS:
        if len(picked) >= count:
            break
        if pattern not in [p for p, _ in picked] and has_pattern(numbers, pattern):
            picked.append((pattern, None))
    return [(pattern, (kind or "force") if pattern == "killing_line" else None) for pattern, kind in picked]


def ring_cells(engine: Any, zone: Any, count: int, radius_cells: int, avoid: set[tuple[int, int]]) -> list[Any]:
    """``count`` squares of the zone spread evenly on a ring around its centre (the Court's nine Nodes, the four Anchors), each snapped to the nearest
    free square of the zone."""
    from ..gate2_runtime_models import Position

    free = [(cell.x, cell.y) for cell in zone.affected_cells if (cell.x, cell.y) not in avoid]
    out: list[Any] = []
    for index in range(count):
        angle = 2 * math.pi * index / count
        want = (zone.center.x + radius_cells * math.cos(angle), zone.center.y + radius_cells * math.sin(angle))
        if not free:
            break
        best = min(free, key=lambda cell: (cell[0] - want[0]) ** 2 + (cell[1] - want[1]) ** 2)
        free.remove(best)
        out.append(Position(x=best[0], y=best[1]))
    return out


def place(engine: Any, zone: Any, role: str, index: int, position: Any, ac: int, hp: int, source: str, owner_id: str) -> Any:
    """One Node, Eye or Anchor of a Domain: an object of the formation the object rules can target (AC and HP), evented."""
    from ..gate2_runtime_models import RuntimeObjectState

    obj = RuntimeObjectState(object_id=f"{F.OBJECT_PREFIX}{zone.zone_id}:{role}:{index}", object_kind=f"FORMATION_{role.upper()}", position=position, unattended=True,
                             flammable=False, owner_id=owner_id, ac=ac, current_hp=hp, maximum_hp=hp, damage_immunities=F.IMMUNE,
                             component={F.KEY: zone.zone_id, "role": role})
    engine._update_object(obj, source, owner_id)
    return obj


@effect("formation_domain")
def formation_domain(ctx: Any, eff: dict[str, Any]) -> None:
    from .. import zones

    engine, actor = ctx.engine, ctx.actor
    kind = str(eff.get("kind"))
    zone = F.fresh_zone(engine, actor, ctx.source)
    if zone is None:
        ctx.rider("The Domain did not take shape.")
        return
    cl, talents = int(ctx.numbers.get("cl") or 1), F.talents_of(ctx.numbers)
    setup = F.setup_of(actor)
    layers: list[tuple[str, str | None]] = []
    if kind in DOMAIN_LAYERS:
        layers = default_layers(ctx.numbers, setup.get("domain_layers") or [], DOMAIN_LAYERS[kind])
        for pattern, damage_type in layers:
            F.add_layer(zone, pattern, damage_type, ctx.numbers)
        zone.trigger_profile = {**zone.trigger_profile, "name": {"court": "Court of the Ninefold Array", "sovereign": "Sovereign Array"}[kind]}
    keyed_list = [str(key) for key in setup.get("keyed") or []] if "gate_keeper" in talents else []
    bonus = cl if "reinforced_nodes" in talents else 0
    profile = {"mode": "combat", "layers": [pattern for pattern, _ in layers], "damage_type": next((t for p, t in layers if p == "killing_line"), None),
               "cl": cl, "owner": actor.entity_id, "numbers": dict(ctx.numbers), "line": False, "keyed": keyed_list, "domain": kind,
               "element": setup.get("element") if "elemental_killing_array" in talents and any(p == "killing_line" for p, _ in layers) else None,
               "eye": None, "nodes": [], "no_eye": True}
    words = ""
    if kind == "court":
        eye = place(engine, zone, "eye", 0, zone.center, 13, 5 + cl + bonus, ctx.source, actor.entity_id)
        spots = ring_cells(engine, zone, 9, 6, {(zone.center.x, zone.center.y)})
        nodes = [place(engine, zone, "node", index, spot, 15, 3 * cl + bonus, ctx.source, actor.entity_id) for index, spot in enumerate(spots)]
        profile.update({"eye": eye.object_id, "no_eye": False, "nodes": [node.object_id for node in nodes], "collapse_at": min(5, len(nodes))})
        words = f" with its Eye (AC 13, {5 + cl + bonus} HP) and {len(nodes)} Nodes (AC 15, {3 * cl + bonus} HP each); destroying the Eye or five Nodes collapses it"
    elif kind == "mountain":
        spots = ring_cells(engine, zone, 4, 4, {(zone.center.x, zone.center.y)})
        anchors = [place(engine, zone, "anchor", index, spot, 15, 3 * cl + bonus, ctx.source, actor.entity_id) for index, spot in enumerate(spots)]
        profile.update({"nodes": [anchor.object_id for anchor in anchors], "collapse_at": min(2, len(anchors))})
        words = f" with {len(anchors)} visible Anchors (AC 15, {3 * cl + bonus} HP each); destroying two collapses it"
    else:
        profile["eye_actor"] = actor.entity_id  # "You are the Array Eye. If you become Incapacitated, the Sovereign Array collapses."
        words = "; you are its Eye"
    F.save_zone(engine, zone, ctx.source, profile)
    zones.sync_inside(engine, ctx.source)
    if setup:
        engine._remove_condition(actor, T.SETUP_COND, ctx.source)
    said = ", ".join(F.PATTERNS[pattern]["name"] for pattern, _ in layers)
    ctx.rider(f"{zone.trigger_profile.get('name')} set at ({zone.center.x},{zone.center.y}){words}" + (f"; layers: {said}." if said else "."))


# ------------------------------------------------------------------------------------------------ Pulse riders and Harmonized Pulse
@effect("formation_harmonize")
def formation_harmonize(ctx: Any, eff: dict[str, Any]) -> None:
    engine, actor, pattern = ctx.engine, ctx.actor, str(eff.get("pattern"))
    zone = harmonizable(engine, actor, pattern)
    if zone is None:
        ctx.rider("No array of yours with two layers to Harmonize.")
        return
    F.save_zone(engine, zone, ctx.source, {**F.record(zone), "harmonized": pattern, "harm_used": False})
    actor.turn_flags["formation_harmonized"] = True
    name = F.PATTERNS[pattern]["name"]
    said = {"locking_gate": "hostile creatures inside spend an extra 5 feet of movement for every 5 feet they move",
            "sensing_eye": "Invisible creatures inside gain no Advantage against you or your keyed allies",
            "veiled_road": "one keyed ally inside has Half Cover",
            "nourishing_cycle": "its Temporary HP add your key ability modifier",
            "suppressing_vein": "the first hostile creature to spend CP inside makes a Charisma save or loses 1 more CP",
            "killing_line": "the first damage roll from the array adds your Proficiency Bonus"}.get(pattern, "its Passive is stronger")
    if pattern == "veiled_road":
        ally = ctx.target or (ctx.targets[0] if ctx.targets else actor)
        engine._apply_condition(ally, "condition:typed.formation_half_cover", ctx.source, actor.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN", data={"zone": zone.zone_id})
        said = f"{ally.display_name} has Half Cover"
    ctx.rider(f"Harmonized Pulse: {name} is strengthened until the start of your next turn -- {said}.")


@effect("formation_harmonic_kill")
def formation_harmonic_kill(ctx: Any, eff: dict[str, Any]) -> None:
    """Harmonized Pulse, Killing Line: "the first damage roll from the array before the start of your next turn adds your Proficiency Bonus"."""
    from ..typed_executor import run_effects

    engine, victim = ctx.engine, ctx.target or (ctx.targets[0] if ctx.targets else None)
    if victim is None:
        return
    zone = next((row for row in F.arrays(engine, ctx.actor.entity_id) if F.record(row).get("harmonized") == "killing_line" and not F.record(row).get("harm_used")
                 and F.inside(engine, victim, row)), None)
    if zone is None:
        return
    F.save_zone(engine, zone, ctx.source, {**F.record(zone), "harm_used": True})
    run_effects(ctx, [{"type": "damage", "formula": "pb", "damage_types": list(eff.get("damage_types") or ["force"]), "applies_to": "target",
                       "evidence": "Harmonized Pulse: the first damage roll from the array adds your Proficiency Bonus"}])


@effect("formation_nourish")
def formation_nourish(ctx: Any, eff: dict[str, Any]) -> None:
    """Nourishing Cycle's Passive: "Temporary HP equal to your Proficiency Bonus" (plus the key ability modifier once Harmonized)."""
    engine, subject = ctx.engine, ctx.target
    if subject is None:
        return
    zone = next((row for row in F.arrays(engine, ctx.actor.entity_id) if "nourishing_cycle" in (F.record(row).get("layers") or []) and F.inside(engine, subject, row)), None)
    amount = int(ctx.numbers.get("pb") or 2)
    if zone is not None and F.record(zone).get("harmonized") == "nourishing_cycle":
        amount += max(0, int(ctx.numbers.get("key_mod") or 0))
    engine._grant_temp_hp(subject, amount, ctx.source, ctx.actor.entity_id)
    ctx.rider(f"{subject.display_name} gains {amount} Temporary HP from the Nourishing Cycle.")


@effect("formation_element")
def formation_element(ctx: Any, eff: dict[str, Any]) -> None:
    """Elemental Killing Array: the Killing Line Pulse's rider, once per turn, until the start of your next turn."""
    from ..typed_executor import run_effects

    victim, actor, element = ctx.target or (ctx.targets[0] if ctx.targets else None), ctx.actor, str(eff.get("element"))
    if victim is None or element not in ELEMENTS or actor.turn_flags.get("formation_element_used"):
        return
    actor.turn_flags["formation_element_used"] = True
    rows = {"fire": [{"type": "healing_reduction", "evidence": "cannot regain Hit Points until the start of your next turn", "applies_to": "target",
                      "expires_on": "START_OF_SOURCE_NEXT_TURN"}],
            "water": [{"type": "speed", "amount": -10, "applies_to": "target", "duration": "until_start_of_your_next_turn"}],
            "sand": [{"type": "condition", "condition": "no_dash", "applies_to": "target", "duration": "until_start_of_your_next_turn"}],
            "lightning": [{"type": "condition", "condition": "reaction_denied", "applies_to": "target", "duration": "until_start_of_your_next_turn"}],
            "radiance": [{"type": "condition", "condition": "formation_unlit", "applies_to": "target", "duration": "until_start_of_your_next_turn"}],
            "shadow": [{"type": "condition", "condition": "formation_dim", "applies_to": "target", "duration": "until_start_of_your_next_turn"}],
            "blood": [{"type": "condition", "condition": "formation_weak_con", "applies_to": "target", "duration": "until_start_of_your_next_turn"}],
            "force": [{"type": "forced_movement", "distance_ft": 5, "direction": "away", "max_size_cells": 2, "applies_to": "target"}]}[element]
    for row in rows:
        row["evidence"] = row.get("evidence") or f"Elemental Killing Array ({ELEMENTS[element][0]}): {ELEMENTS[element][1]}"
    run_effects(ctx, rows)
    ctx.rider(f"Elemental Killing Array ({ELEMENTS[element][0]}): {ELEMENTS[element][1]}.")


@effect("formation_spirit_lock")
def formation_spirit_lock(ctx: Any, eff: dict[str, Any]) -> None:
    """Spirit-Lock Array: a creature that fails a Sealing Gate Pulse save "also cannot be summoned, dismissed, banished, possessed, magically
    transported, or teleported until the start of your next turn" (its own teleporting is the Sealing Gate's).  A possessing, projecting or avatar
    creature's second Charisma save is a GM ruling."""
    from ..typed_executor import run_effects

    run_effects(ctx, [{"type": "condition", "condition": "formation_spirit_locked", "applies_to": "target", "duration": "until_start_of_your_next_turn",
                       "evidence": eff.get("evidence") or "Spirit-Lock Array"}])


# ------------------------------------------------------------------------------------------------ Court, Turn the Battlefield
@effect("formation_court_node")
def formation_court_node(ctx: Any, eff: dict[str, Any]) -> None:
    """Court of the Ninefold Array: move one Node up to 10 feet; a Node moving through a hostile creature's space deals it Force damage equal to your PB."""
    from ..typed_executor import run_effects

    engine, actor = ctx.engine, ctx.actor
    aim = getattr(ctx.intent, "destination", None)
    found = court_node_for(engine, actor, aim)
    if found is None or not actor.turn_flags.get("formation_court_move"):
        ctx.rider("No Node of yours to move there.")
        return
    zone, node = found
    actor.turn_flags["formation_court_move"] = int(actor.turn_flags.get("formation_court_move") or 0) - 1
    start = node.position
    engine._update_object(node.model_copy(update={"position": aim}), ctx.source, actor.entity_id)
    _say(engine, ctx.source, actor.entity_id, f"A Node of the Court moves from ({start.x},{start.y}) to ({aim.x},{aim.y}).")
    steps = max(abs(aim.x - start.x), abs(aim.y - start.y)) * 2 or 1
    squares = {(round(start.x + (aim.x - start.x) * i / steps), round(start.y + (aim.y - start.y) * i / steps)) for i in range(steps + 1)}
    for foe in [row for row in engine.state.actors.values() if row.active and F.hostile_to(engine, zone, row)]:
        if any(engine._footprint_intersects(foe, [_cell(x, y)]) for x, y in squares):
            sub = dataclasses.replace(ctx, target=foe, targets=[foe])
            run_effects(sub, [{"type": "damage", "formula": "pb", "damage_types": ["force"], "applies_to": "target",
                               "evidence": "Court of the Ninefold Array: a Node moving through a hostile creature's space deals it Force damage equal to your Proficiency Bonus"}])


def _cell(x: int, y: int) -> Any:
    from ..gate2_runtime_models import Position

    return Position(x=x, y=y)


@effect("formation_turn")
def formation_turn(ctx: Any, eff: dict[str, Any]) -> None:
    """Turn the Battlefield Inside Out: each hostile creature makes a Wisdom save; a failure swaps its place with a keyed ally (teleportation:
    a teleport-blocking effect stops it), a success cannot take Reactions until the start of your next turn."""
    from ..typed_executor import run_effects

    engine, actor = ctx.engine, ctx.actor
    zone = F.array_at(engine, actor, getattr(ctx.intent, "destination", None)) if getattr(ctx.intent, "destination", None) is not None else None
    pairs = swaps_for(engine, zone) if zone is not None else []
    if not pairs:
        ctx.rider("No keyed ally and hostile creature inside that array to exchange.")
        return
    dc = int(ctx.numbers.get("save_dc") or 10)
    for ally, foe in pairs:
        roll = engine._roll_save(foe, "WIS", dc, ctx.source)
        if roll is not None and int(roll.total) >= dc:
            run_effects(dataclasses.replace(ctx, target=foe, targets=[foe]), [{"type": "condition", "condition": "reaction_denied", "applies_to": "target",
                                                                              "duration": "until_start_of_your_next_turn",
                                                                              "evidence": "A creature that succeeds is not moved, but it cannot take Reactions until the start of your next turn"}])
            continue
        if not swap(engine, ally, foe, ctx.source):
            ctx.rider(f"{foe.display_name} and {ally.display_name} cannot exchange places (a teleport block, or an illegal space).")
        else:
            ctx.rider(f"{foe.display_name} exchanges places with {ally.display_name}.")


def _fits(engine: Any, who: Any, square: Any, other: Any) -> bool:
    """Whether ``who`` may stand on ``square`` once ``other`` has left it (a Large creature's larger footprint may not fit)."""
    occupied = engine._occupied_cells_except(who.entity_id) - set(engine._actor_cells(other))
    return bool(engine.grid.placement_legal(square, footprint=engine._footprint(who), occupied_cells=occupied))


def swap(engine: Any, ally: Any, foe: Any, source: str) -> bool:
    """Exchange a keyed ally and a hostile creature as teleportation: both squares must be legal for the other, and teleport-blocking stops it (the
    ally is the one who teleports, so the arrays' teleport checks are made on the ally's move)."""
    from .. import ext, zones

    if any(F.has_condition(who, name) is not None for who in (ally, foe) for name in ("cannot_teleport", "formation_spirit_locked")):
        return False
    a, b = ally.position, foe.position
    if not _fits(engine, ally, b, foe) or not _fits(engine, foe, a, ally):
        return False
    if False in ext.run("teleport_check", engine, ally, a, b):
        return False
    ally.position, foe.position = b, a
    for who, start, end in ((ally, a, b), (foe, b, a)):
        engine._append_event("MOVEMENT_COMMITTED", source, actor_id=who.entity_id, payload={
            "destination": end.model_dump(mode="json"), "path": [start.model_dump(mode="json"), end.model_dump(mode="json")], "cost_ft": 0, "teleport": True})
    for who, start, end in ((ally, a, b), (foe, b, a)):
        zones.on_moved(engine, who, start, end, forced=True)
    return True


# ------------------------------------------------------------------------------------------------ Eye of the Formation Master
def hold(engine: Any, zone: Any, source: str) -> bool:
    """"If the Eye would be disrupted or destroyed, you may use your Reaction and spend 2 CP to keep the array active until the end of your next turn."
    While it serves, the owner is Marked.  True when the array is (or now is) held."""
    record = F.record(zone)
    if record.get("held"):
        return True
    owner = engine.state.actors.get(zone.owner_id)
    numbers = record.get("numbers") or {}
    pool = str(numbers.get("formation_pool") or "resource:core.qi")
    if owner is None or "eye_of_the_formation_master" not in F.talents_of(numbers) or int(numbers.get("cl") or 1) < 10 or not owner.active \
            or incapacitated(owner) or not owner.reaction_available or owner.resources.get(pool, 0) < 2 or F.has_condition(owner, "formation_cp_locked") is not None \
            or not F.inside(engine, owner, zone):  # (an auxiliary Eye: "while inside your array")
        return False
    with activation(engine, owner, "formation:eye_of_the_formation_master"):
        owner.reaction_available = False
        engine._spend_resource(owner, pool, 2, "formation:eye_of_the_formation_master")
        turns = 2 if engine.state.current_actor_id == owner.entity_id else 1  # "the end of your next turn"
        F.save_zone(engine, zone, source, {**record, "held": {"turns": turns}})
        engine._apply_condition(owner, "condition:typed.formation_marked", "formation:eye_of_the_formation_master", owner.entity_id, expires_on="UNTIL_REMOVED", data={"zone": zone.zone_id})
        _say(engine, "formation:eye_of_the_formation_master", owner.entity_id,
             f"Eye of the Formation Master: {owner.display_name} spends a Reaction and 2 CP; the array holds until the end of their next turn, and they are Marked.")
        return True


@hook("turn_end")
def held_runs_out(engine: Any, actor: Any) -> None:
    """The hold lasts until the end of the owner's next turn; then the array falls if its Eye is still gone (it cannot be held again: the Eye is not
    "about to be" destroyed twice)."""
    for zone in F.arrays(engine, actor.entity_id):
        held = F.record(zone).get("held")
        if not held:
            continue
        left = int(held.get("turns") or 1) - 1
        if left > 0:
            F.save_zone(engine, zone, "formation:eye_of_the_formation_master", {**F.record(zone), "held": {"turns": left}})
            continue
        F.save_zone(engine, zone, "formation:eye_of_the_formation_master", {**F.record(zone), "held": None})
        iid = F.has_condition(actor, "formation_marked")
        if iid is not None:
            engine._remove_condition(actor, actor.conditions[iid].condition_id, "formation:eye_of_the_formation_master")
        eye = engine.state.objects.get(F.record(zone).get("eye") or "")
        if eye is None or eye.destroyed or eye.suppressed:
            F.collapse(engine, zone, "HELD", "formation:eye_of_the_formation_master")


@hook("attack_mode")
def marked_by_the_array(ctx: Any, target: Any) -> str | None:
    """While serving as the Eye the owner is Marked: "attacks against you have Advantage if the attacker is inside the array and can see you"."""
    iid = F.has_condition(target, "formation_marked")
    zone = ctx.engine.state.zones.get((target.conditions[iid].data or {}).get("zone") or "") if iid is not None else None
    if zone is None or not zone.active or not F.inside(ctx.engine, ctx.actor, zone):
        return None
    from .. import stealth

    return "ADVANTAGE" if stealth.sees(ctx.engine, ctx.actor, target) else None


# ------------------------------------------------------------------------------------------------ what a Domain and its riders do to creatures
@hook("turn_start")
def on_turn_start(engine: Any, actor: Any) -> None:
    """A new turn: the Pulses' once-per-turn allowances, and Harmonized Pulse "until the start of your next turn"."""
    for zone in F.arrays(engine, actor.entity_id):
        if F.record(zone).get("harmonized"):
            F.save_zone(engine, zone, "formation:harmonized_pulse", {**F.record(zone), "harmonized": None, "harm_used": False})


@hook("after_save")
def after_save(ctx: Any, subject: Any, ability: str, named: Any, failed: bool) -> None:
    """Court of the Ninefold Array: a hostile creature fails a save against one of the Court's Pulses -- the owner may move a Node."""
    zone = ctx.engine.state.zones.get(str(ctx.damage_cache.get("formation_zone") or ""))
    if failed and zone is not None and zone.active and F.record(zone).get("domain") == "court" and F.hostile_to(ctx.engine, zone, subject):
        ctx.actor.turn_flags["formation_court_move"] = int(ctx.actor.turn_flags.get("formation_court_move") or 0) + 1
        ctx.rider(f"{ctx.actor.display_name} may move a Node of the Court up to 10 feet.")


def _mask(engine: Any, who: Any, out: dict[str, set[str]]) -> None:
    from .. import senses

    hidden = set(senses.rules().get("hidden_conditions") or [])
    rows = {iid for iid, condition in who.conditions.items() if condition.condition_id in hidden}
    if rows:
        out.setdefault(who.entity_id, set()).update(rows)


@hook("masked_conditions")
def masked(engine: Any, attacker: Any, target: Any) -> dict[str, set[str]] | None:
    """The Invisible or Hidden benefit that does not count: Radiance's rider (Elemental Killing Array) takes it from the creature outright; a harmonized
    Sensing Eye takes it from a creature inside the array against the owner and the owner's keyed allies."""
    out: dict[str, set[str]] = {}
    for who, other in ((attacker, target), (target, attacker)):
        if F.has_condition(who, "formation_unlit") is not None:
            _mask(engine, who, out)
        for zone in F.arrays(engine):
            if F.record(zone).get("harmonized") == "sensing_eye" and F.inside(engine, who, zone) and (other.entity_id == zone.owner_id or F.keyed(engine, zone, other)) \
                    and F.hostile_to(engine, zone, who):
                _mask(engine, who, out)
    return out or None


@hook("cover")
def half_cover(engine: Any, attacker: Any, target: Any) -> int | None:
    """Harmonized Pulse, Veiled Road: one keyed ally inside gets Half Cover (+2 against ranged attacks)."""
    iid = F.has_condition(target, "formation_half_cover")
    zone = engine.state.zones.get((target.conditions[iid].data or {}).get("zone") or "") if iid is not None else None
    return 2 if zone is not None and zone.active and F.inside(engine, target, zone) else None


@hook("difficult_exempt")
def difficult_exempt(engine: Any, actor: Any) -> set[tuple[int, int]] | None:
    """Court of the Ninefold Array: keyed allies ignore its Difficult Terrain."""
    out: set[tuple[int, int]] = set()
    for zone in F.arrays(engine):
        if F.record(zone).get("domain") == "court" and F.keyed(engine, zone, actor) and F.inside(engine, actor, zone):
            out |= F.cells_of(zone)
    return out or None


@hook("summon_check")
def summon_check(engine: Any, owner: Any, creature: Any, spot: Any, was_active: bool, source: str) -> bool | None:
    """Spirit-Lock Array: a creature that failed the save cannot be summoned.  Mountain-Sealing Great Array: "summoning into or out of the array fails
    unless the summoner succeeds on a Formation Check against your Formation Save DC"."""
    if F.has_condition(creature, "formation_spirit_locked") is not None:
        _say(engine, "formation:spirit_lock_array", owner.entity_id, f"Spirit-Lock Array: {creature.display_name} cannot be summoned right now.")
        return False
    for zone in F.arrays(engine):
        record = F.record(zone)
        if record.get("domain") != "mountain" or owner.entity_id in (record.get("keyed") or []):
            continue
        into, out_of = (spot.x, spot.y) in F.cells_of(zone), bool(was_active and (creature.position.x, creature.position.y) in F.cells_of(zone))
        if into == out_of:
            continue
        dc = int((record.get("numbers") or {}).get("save_dc") or 10)
        bonus = int(_summoner_bonus(engine, owner))
        if not F.formation_check(engine, owner, {"attack_bonus": bonus}, dc, "formation:mountain_sealing", "summon through the Mountain-Sealing array"):
            _say(engine, "formation:mountain_sealing", owner.entity_id, f"The Mountain-Sealing Great Array holds: {owner.display_name}'s summoning fails.")
            return False
    return None


def _summoner_bonus(engine: Any, owner: Any) -> int:
    """A Formation Check's modifier for the summoner: a Formation user's own (d20 + PB + key modifier), anyone else's Proficiency Bonus."""
    row = next((row for row in engine.action_catalog.values() if row.owner_id == owner.entity_id and ((row.parameters or {}).get(F.TAG))), None)
    numbers = (((row.parameters or {}).get("typed") or {}).get("numbers") or {}) if row is not None else {}
    return int(numbers.get("attack_bonus") or getattr(owner, "proficiency_bonus", 2) or 0)


# ------------------------------------------------------------------------------------------------ movement and spending inside a Domain
@hook("event")
def on_event(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    payload = kwargs.get("payload") or {}
    if event_type == "MOVEMENT_COMMITTED" and payload.get("path") and not payload.get("formation_rewind") and not payload.get("teleport"):
        mover = engine.state.actors.get(kwargs.get("actor_id") or "")
        if mover is not None:
            _locking_tax(engine, mover, payload)
            _mountain_leave(engine, mover, payload)
    elif event_type == "RESOURCE_SPENT":
        _vein_tax(engine, kwargs)
    elif event_type == "SAVE_ROLLED":
        _consume_riders(engine, kwargs, "save")
    elif event_type == "CHECK_ROLLED":
        _consume_riders(engine, kwargs, "check")


def _path_cells(payload: dict[str, Any]) -> list[tuple[int, int]]:
    return [(int(step["x"]), int(step["y"])) for step in payload.get("path") or [] if isinstance(step, dict) and "x" in step and "y" in step]


def _locking_tax(engine: Any, mover: Any, payload: dict[str, Any]) -> None:
    """Harmonized Pulse, Locking Gate: "hostile creatures inside spend an extra 5 feet of movement for every 5 feet they move".  The move has
    been made (the engine prices a path by its squares before this plug-in sees it), so the extra is taken off what is left of its movement."""
    cells, size = _path_cells(payload)[1:], engine.grid.square_size_ft
    for zone in F.arrays(engine):
        if F.record(zone).get("harmonized") != "locking_gate" or not F.hostile_to(engine, zone, mover):
            continue
        inside = sum(1 for cell in cells if cell in F.cells_of(zone))
        extra = min(int(mover.movement_remaining_ft), inside * size)
        if extra > 0:
            mover.movement_remaining_ft -= extra
            _say(engine, "formation:harmonized_locking_gate", zone.owner_id, f"Harmonized Locking Gate: {mover.display_name} spends {extra} extra feet of movement crossing the array.")


def _mountain_leave(engine: Any, mover: Any, payload: dict[str, Any]) -> None:
    """Mountain-Sealing Great Array: "hostile creatures cannot willingly leave by ordinary movement unless they succeed on a Strength or Charisma saving
    throw, their choice".  The engine has already made the move (its movement rules are not open to a plug-in), so a failed save puts the creature
    back on the last square of the array it crossed; the movement it spent stays spent."""
    from .. import zones

    path = _path_cells(payload)
    for zone in F.arrays(engine):
        if F.record(zone).get("domain") != "mountain" or not F.hostile_to(engine, zone, mover) or len(path) < 2:
            continue
        cells = F.cells_of(zone)
        if path[0] not in cells or (mover.position.x, mover.position.y) in cells:
            continue
        dc = int((F.record(zone).get("numbers") or {}).get("save_dc") or 10)
        ability = max(("STR", "CHA"), key=lambda name: int(mover.saving_throws.get(name, 0)))  # "their choice": the better save
        roll = engine._roll_save(mover, ability, dc, "formation:mountain_sealing")
        if roll is not None and int(roll.total) >= dc:
            _say(engine, "formation:mountain_sealing", zone.owner_id, f"{mover.display_name} breaks out of the Mountain-Sealing array ({ability}).")
            continue
        last = next((cell for cell in reversed(path) if cell in cells), path[0])
        start, end = mover.position, _cell(*last)
        mover.position = end
        engine._append_event("MOVEMENT_COMMITTED", "formation:mountain_sealing", actor_id=mover.entity_id, payload={
            "destination": end.model_dump(mode="json"), "path": [start.model_dump(mode="json"), end.model_dump(mode="json")], "cost_ft": 0, "formation_rewind": True})
        zones.on_moved(engine, mover, start, end, forced=True)
        _say(engine, "formation:mountain_sealing", zone.owner_id, f"The Mountain-Sealing Great Array holds {mover.display_name} in ({ability} save failed).")


def _vein_tax(engine: Any, kwargs: dict[str, Any]) -> None:
    """Harmonized Pulse, Suppressing Vein: "the first hostile creature that spends CP inside makes a Charisma save or loses 1 more CP"."""
    payload = kwargs.get("payload") or {}
    resource = str(payload.get("resource_id") or "")
    who = engine.state.actors.get(kwargs.get("actor_id") or "")
    if who is None or int(payload.get("amount") or 0) <= 0 or not resource.endswith(F.CP_POOLS) or payload.get("formation_tax"):
        return
    for zone in F.arrays(engine):
        record = F.record(zone)
        if record.get("harmonized") != "suppressing_vein" or record.get("harm_used") or not F.hostile_to(engine, zone, who) or not F.inside(engine, who, zone):
            continue
        F.save_zone(engine, zone, "formation:harmonized_suppressing_vein", {**record, "harm_used": True})
        dc = int((record.get("numbers") or {}).get("save_dc") or 10)
        roll = engine._roll_save(who, "CHA", dc, "formation:harmonized_suppressing_vein")
        if roll is None or int(roll.total) < dc:
            if who.resources.get(resource, 0) >= 1:
                engine._spend_resource(who, resource, 1, "formation:harmonized_suppressing_vein")
            _say(engine, "formation:harmonized_suppressing_vein", zone.owner_id, f"Harmonized Suppressing Vein: {who.display_name} loses 1 more CP.")
        break


def _consume_riders(engine: Any, kwargs: dict[str, Any], kind: str) -> None:
    """Elemental Killing Array: Disadvantage on "the next" Constitution save or Perception check is used up by the roll."""
    who = engine.state.actors.get(kwargs.get("actor_id") or "")
    payload = kwargs.get("payload") or {}
    if who is None:
        return
    name = "formation_weak_con" if kind == "save" and str(payload.get("reason") or "").endswith(":CON") else \
        "formation_dim" if kind == "check" and str(payload.get("check") or "") == "Perception" else None
    iid = F.has_condition(who, name) if name else None
    if iid is not None:
        engine._remove_condition(who, who.conditions[iid].condition_id, "formation:elemental_killing_array")

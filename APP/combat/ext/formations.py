"""Formation arrays (Formations sphere; owner 2026-09-29: "formation arrays are placeable symbols on the map that can be
removed").  Source: the Sphere Compendium's Formations chapter -- Set Array (Combat Array, Prepared Array), Collapse Array,
Pulse Array, the six Basic Patterns and the Formation talents (owner's text first; nothing here is invented).

  Combat Array   an Action, 2 CP, Concentration up to 1 minute: a 10-foot-radius circle on a point you can see within 30 feet,
                 one Basic Pattern you know, one Array Eye at its centre (AC 13, 5 + CL Hit Points, immune to Poison and
                 Psychic).  It collapses when the Eye is destroyed, when Concentration is lost, or when you set another array
                 beyond your Formation Load (1; 2 at CL 10; 3 at CL 15).
  Pulse          a Bonus Action within 120 feet of the array: one of its patterns' Pulse effects on one creature inside it
                 or at its boundary; the same named Pulse touches a creature only once a round.
  Collapse       free on your turn, an array within 120 feet, harmless.
  Eye and Nodes  real objects on the map (RuntimeObjectState with component {"formation": zone id, "role": ...}); an enemy's
                 weapon attack can target one (the object_targets / object_action hooks), the AI is not offered them.

The array itself is a combat/zones.py zone: its Passive is the zone (difficult ground, a trigger, a rule for what stands
inside), so movement, saves and the table's overlays already understand it.  Its own record (the patterns, its Eye) is
``trigger_profile["formation"]``.  Everything that changes it is an event, so a saved fight replays it.

combat/ext/formation_talents.py holds the talents that build on this module.


Shared Formation-family API used by formation_riders, formation_talents and formation_masters: say records a rider event; record, arrays, inside, keyed and objects_of query array state without changing it. part_name is the player-facing name of one of the array's own objects (its Eye or a Node) and fresh_zone is the empty record a Domain layer is built into. The sibling talent plug-in adds build_action (see formation_talents.py); family members use these public names only, never an underscore-prefixed one.
"""

from __future__ import annotations

from ..paid_relocation import activation

import re
from typing import Any

from . import effect, hook
from ..resource_costs import parts as cost_parts
from .placed import notice, note

KEY = "formation"                 # zone.trigger_profile: the array's own record
SPHERE = "tianxia.sphere.formations"
BASE_SET = "FORMATIONS_BASE_SET_ARRAY"
BASE_PULSE = "FORMATIONS_BASE_PULSE_ARRAY"
BASE_COLLAPSE = "FORMATIONS_BASE_COLLAPSE_ARRAY"
TAG = "formation"                 # action parameters: what a formation action is
IMMUNE = ("POISON", "PSYCHIC")    # "Formation objects are immune to Poison and Psychic damage"
OBJECT_PREFIX = "object:formation:"
PULSE_RANGE_FT = 120
SET_RANGE_FT = 30
COMBAT_RADIUS_FT = 10
REPLACED: set[str] = set()        # talent ids whose compiled (wrongly aimed) action a formation plug-in replaces
KILLING_TYPES = ("slashing", "piercing", "force", "radiant", "necrotic", "fire", "cold", "lightning", "thunder", "acid")

# Each Basic Pattern: what stands in the zone (its Passive) and how its Pulse picks a creature.  The Pulse's own effects are in
# ``pulse_effects`` (they need the array's damage type, so they are built when it is used).
PATTERNS: dict[str, dict[str, Any]] = {
    "locking_gate": {"name": "Locking Gate", "color": "#b58b3c", "pulse_on": "hostile"},
    "sensing_eye": {"name": "Sensing Eye", "color": "#5a9bd4", "pulse_on": "any"},
    "veiled_road": {"name": "Veiled Road", "color": "#7d6bb0", "pulse_on": "ally"},
    "nourishing_cycle": {"name": "Nourishing Cycle", "color": "#5fae72", "pulse_on": "ally"},
    "suppressing_vein": {"name": "Suppressing Vein", "color": "#a4494f", "pulse_on": "hostile"},
    "killing_line": {"name": "Killing Line", "color": "#c9522e", "pulse_on": "hostile"},
    # Pattern talents: known only with the talent (Binding Array, Sealing Gate Pattern; both CL 5+).
    "binding": {"name": "Binding", "color": "#8b6b3d", "pulse_on": "hostile", "talent": "binding_array"},
    "sealing_gate": {"name": "Sealing Gate", "color": "#3f6fa5", "pulse_on": "hostile", "talent": "sealing_gate_pattern"},
}

# A Pulse that "requires a choice of mode" is one action per mode ("If the selected Pulse requires a choice of target or mode,
# make that choice when you use this Bonus Action"): Veiled Road moves a willing creature 10 feet or Hides it.
PULSE_MODES: dict[str, list[tuple[str, str]]] = {"veiled_road": [("move", "move 10 ft"), ("hide", "Hide")]}


def killing_types(info: dict[str, Any]) -> tuple[str, ...]:
    """The damage types a Killing Line may have: the ten it can always take, and Poison for Elemental Killing Array ("choose one sphere you
    know that has a ... poison ... damage expression: the Killing Line Pattern may use that sphere's appropriate damage type")."""
    return KILLING_TYPES + (("poison",) if "elemental_killing_array" in owned_talents(info) else ())


def pattern_key(name: str) -> str | None:
    """The pattern a talent's or a text's name means ("Locking Gate Pattern", "LOCKING GATE")."""
    text = re.sub(r"\bpattern\b", "", str(name or "").lower()).strip()
    for key, row in PATTERNS.items():
        if row["name"].lower() == text:
            return key
    return None


# ------------------------------------------------------------------------------------------------ what a pattern does
def passive_spec(pattern: str, damage_type: str | None, numbers: dict[str, Any]) -> dict[str, Any]:
    """The zone rows a pattern's Passive puts in the array (combat/zones.py: ``difficult``, ``triggers``, ``inside``)."""
    out: dict[str, Any] = {"difficult": None, "triggers": [], "inside": []}
    if pattern == "locking_gate":
        out["difficult"] = "hostile"   # "Hostile creatures treat the array's area as Difficult Terrain."
    elif pattern == "killing_line":
        # "The first time each turn a hostile creature enters the array or starts its turn inside it, it takes damage equal
        # to your Proficiency Bonus" (of the type chosen when the array was created).
        out["triggers"].append({"id": "formation:killing_line", "name": "Killing Line", "on": ["enter", "start"], "who": "hostile",
                                "effects": [{"type": "damage", "formula": "pb", "damage_types": [str(damage_type or "force")],
                                             "applies_to": "target", "evidence": "Killing Line: damage equal to your Proficiency Bonus"},
                                            {"type": "formation_harmonic_kill", "damage_types": [str(damage_type or "force")],
                                             "evidence": "Harmonized Pulse: the first damage roll from the array adds your Proficiency Bonus"}]})
    elif pattern == "nourishing_cycle":
        # "The first time each round an allied creature starts its turn inside the array while Bloodied, it gains Temporary HP
        # equal to your Proficiency Bonus."
        out["triggers"].append({"id": "formation:nourishing_cycle", "name": "Nourishing Cycle", "on": ["start"], "who": "ally", "per_round": True,
                                "effects": [{"type": "if_bloodied", "effects": [
                                    {"type": "formation_nourish", "evidence": "Temporary HP equal to your Proficiency Bonus (plus your key ability modifier when Harmonized)"}]}]})
    elif pattern == "suppressing_vein":
        # "Hostile creatures inside the array have Disadvantage on Constitution saving throws made to maintain Concentration
        # caused by damage from your allies" (combat/concentration.py save_mode reads ``concentration_vs_allies_of_source``: it
        # applies only when the creature that dealt the damage is on the array owner's side).
        out["inside"].append({"id": "formation:suppressing_vein", "name": "Suppressing Vein", "who": "enemy",
                              "reading": "Disadvantage on Constitution saves to keep Concentration when the array owner's allies damage it",
                              "rule": {"concentration_vs_allies_of_source": "DISADVANTAGE"}})
    elif pattern == "veiled_road":
        # "Creatures outside the array have Disadvantage on Wisdom (Perception) checks to observe details inside it through
        # ordinary sight" (stealth_search_mode below: a search for a Hidden creature inside).
        out["inside"].append({"id": "formation:veiled_road", "name": "Veiled Road", "who": "ally", "reading":
                              "Creatures outside the array have Disadvantage on Perception to observe what is inside", "rule": {}})
    elif pattern == "sensing_eye":
        # "You know when creatures enter or leave the array and how many are inside" (sensing below, log lines).
        out["triggers"].append({"id": "formation:sensing_eye_enter", "name": "Sensing Eye", "on": ["enter"], "who": "any",
                                "effects": [{"type": "formation_sense", "evidence": "Sensing Eye Passive: you know when a creature enters the array"}]})
        out["inside"].append({"id": "formation:sensing_eye", "name": "Sensing Eye", "who": "any",
                              "reading": "The array's owner knows that it is here (enters, leaves, how many)", "rule": {}})
    elif pattern == "binding":
        # "A hostile creature inside the array has Disadvantage on checks and saving throws made to escape Grappled or Restrained
        # effects caused by your allies" (the escape_mode hook; the repeat saves of a Restrained condition are the engine's own).
        out["inside"].append({"id": "formation:binding", "name": "Binding", "who": "enemy", "reading":
                              "Disadvantage on checks to escape a grip the array owner's allies put on it",
                              "rule": {"escape_vs_allies_of_source": "DISADVANTAGE"}})
    elif pattern == "sealing_gate":
        # "Teleportation into, out of, or through the array requires the teleporting creature to succeed on a Charisma saving
        # throw. On a failure, the teleport fails and any action, CP, or resource spent is wasted" (the teleport_check hook).
        out["inside"].append({"id": "formation:sealing_gate", "name": "Sealing Gate", "who": "any", "reading":
                              "Teleporting into, out of or through it takes a Charisma save; a failed one wastes the teleport", "rule": {}})
    return out


def pulse_effects(pattern: str, damage_type: str | None, mode: str | None = None, *, talents: Any = (), element: str | None = None,
                  extra_pb: bool = False) -> list[dict[str, Any]]:
    """A pattern's Pulse as typed effects (combat/typed_executor.py runs them on the chosen creature).  ``talents`` (the owner's
    Formation talents), ``element`` (Elemental Killing Array's rider) and ``extra_pb`` (Harmonized Pulse on the Killing Line) add to it."""
    if pattern == "sensing_eye":
        # "Choose one creature inside the array. You know its location, even if it is Invisible or Hidden, until the start of your next turn."
        return [{"type": "formation_locate", "evidence": "Sensing Eye Pulse: you know its location even if it is Invisible or Hidden"}]
    if pattern == "veiled_road":
        # "Choose one willing creature inside the array. It moves up to 10 feet without provoking Opportunity Attacks, or Hides if it has
        # cover or concealment."
        return [{"type": "formation_veil", "mode": mode or "move", "evidence": "Veiled Road Pulse: move 10 feet without Opportunity Attacks, or Hide"}]
    if pattern == "suppressing_vein":
        # "Choose one hostile creature inside the array. It makes a Charisma saving throw. Failed Save: it cannot spend CP on Reactions,
        # Counter effects, or defensive sphere effects until the start of your next turn. Successful Save: the next time it spends CP
        # before then, it spends 1 additional CP."
        return [{"type": "save", "ability": "cha", "evidence": "Suppressing Vein Pulse: Charisma saving throw",
                 "on_fail": [{"type": "condition", "condition": "formation_cp_locked", "applies_to": "target", "duration": "until_start_of_your_next_turn",
                              "evidence": "Failed Save: it cannot spend CP on Reactions or defensive effects until the start of your next turn"}],
                 "on_success": [{"type": "condition", "condition": "formation_cp_tax", "applies_to": "target", "duration": "until_start_of_your_next_turn",
                                 "evidence": "Successful Save: the next time it spends CP before then, it spends 1 additional CP"}]}]
    if pattern == "binding":
        return [{"type": "save", "ability": "str", "evidence": "Binding Pulse: Strength saving throw",
                 "on_fail": [{"type": "condition", "condition": "restrained", "applies_to": "target", "duration": "until_end_of_next_turn",
                              "repeat_save": {"ability": "STR", "when": "end"},
                              "evidence": "Failed Save: Restrained until the end of its next turn; at the end of that turn it repeats the save, ending the effect on a success"}],
                 "on_success": [{"type": "condition", "condition": "reaction_denied", "applies_to": "target", "duration": "until_start_of_your_next_turn",
                                 "evidence": "Successful Save: it cannot take Reactions until the start of your next turn"}]}]
    if pattern == "sealing_gate":
        rows = [{"type": "save", "ability": "cha", "evidence": "Sealing Gate Pulse: Charisma saving throw",
                 "on_fail": [{"type": "condition", "condition": "cannot_teleport", "applies_to": "target", "duration": "until_start_of_your_next_turn",
                              "evidence": "Failed Save: until the start of your next turn it cannot teleport, plane shift, enter the Ethereal Plane, possess another creature, or leave its body by spiritual projection"}],
                 "on_success": [{"type": "condition", "condition": "formation_teleport_dis", "applies_to": "target", "duration": "until_start_of_your_next_turn",
                                 "evidence": "Successful Save: Disadvantage on the next check or saving throw it makes to teleport, possess, or spiritually travel"}]}]
        if "spirit_lock_array" in talents:  # Spirit-Lock Array (combat/ext/formation_masters.py)
            rows[0]["on_fail"].append({"type": "formation_spirit_lock", "evidence": "Spirit-Lock Array: it also cannot be summoned, dismissed, banished, possessed, magically transported or teleported"})
        return rows
    if pattern == "locking_gate":
        return [{"type": "save", "ability": "str", "evidence": "Locking Gate Pulse: Strength saving throw",
                 "on_fail": [{"type": "condition", "condition": "held_fast", "applies_to": "target", "duration": "until_start_of_your_next_turn",
                              "evidence": "Failed Save: its Speed becomes 0 until the start of your next turn"}],
                 "on_success": [{"type": "formation_slow", "amount": 10, "evidence": "Successful Save: its Speed is reduced by 10 feet until the start of your next turn"}]}]
    if pattern == "killing_line":
        hit = [{"type": "damage", "dice_by_cl": [[1, 4, 1, 8], [5, 10, 2, 8], [11, 16, 3, 8], [17, 99, 4, 8]],
                "formula": "key_ability_modifier", "damage_types": [str(damage_type or "force")], "applies_to": "target",
                "evidence": "1d8 + your Formation key ability modifier, 2d8 at CL 5, 3d8 at CL 11, 4d8 at CL 17"}]
        if extra_pb:  # Harmonized Pulse, Killing Line: "the first damage roll from the array before the start of your next turn adds your Proficiency Bonus"
            hit.append({"type": "formation_harmonic_kill", "damage_types": [str(damage_type or "force")],
                        "evidence": "Harmonized Pulse: the first damage roll from the array adds your Proficiency Bonus"})
        if element:  # Elemental Killing Array: "its Pulse gains a rider ... only once per turn"
            hit.append({"type": "formation_element", "element": element, "evidence": "Elemental Killing Array: the Pulse's rider, once per turn"})
        return [{"type": "attack", "attack_kind": "cultivation", "count": 1, "evidence": "Killing Line Pulse: a Formation Attack roll", "on_hit": hit}]
    if pattern == "nourishing_cycle":
        return [{"type": "healing", "dice": {"count": 1, "sides": 6}, "formula": "key_ability_modifier", "applies_to": "target",
                 "evidence": "Nourishing Cycle Pulse: 1d6 + your Formation key ability modifier"}]
    return []


# ------------------------------------------------------------------------------------------------ small helpers
def _order(zone: Any) -> int:
    tail = str(zone.zone_id).rsplit(":", 1)[-1]
    return int(tail) if tail.isdigit() else 0


def arrays(engine: Any, owner_id: str | None = None) -> list[Any]:
    """Every active array (of one owner), oldest first."""
    return sorted((zone for zone in engine.state.zones.values() if zone.active and zone.trigger_profile.get(KEY)
                   and (owner_id is None or zone.owner_id == owner_id)), key=_order)


def record(zone: Any) -> dict[str, Any]:
    return zone.trigger_profile.get(KEY) or {}


def save_zone(engine: Any, zone: Any, source: str, profile: dict[str, Any] | None = None) -> None:
    """Replace the array's record and put the whole zone in the event log (the reducer takes the complete record)."""
    if profile is not None:
        zone.trigger_profile = {**zone.trigger_profile, KEY: profile}
    engine._append_event("ZONE_CREATED", source, actor_id=zone.owner_id, payload={"zone": zone.model_dump(mode="json")})


def load_of(numbers: dict[str, Any], extra: int = 0) -> int:
    """"Formation Load": 1 array; 2 at CL 10; 3 at CL 15 (the Formation Load table)."""
    cl = int(numbers.get("cl") or 1)
    return 1 + (cl >= 10) + (cl >= 15) + extra


def objects_of(engine: Any, zone: Any) -> list[Any]:
    profile = record(zone)
    rows = [engine.state.objects.get(oid) for oid in [profile.get("eye"), *(profile.get("nodes") or [])]]
    return [row for row in rows if row is not None]


def say(engine: Any, source: str, actor_id: str | None, text: str) -> None:
    note(engine, source, actor_id, text)




def inside(engine: Any, creature: Any, zone: Any) -> bool:
    return bool(creature.active and engine._footprint_intersects(creature, zone.affected_cells))


def inside_at(engine: Any, creature: Any, zone: Any, position: Any) -> bool:
    """:func:`inside` for a square the creature is about to step onto, with the same whole-body reading: a Large creature
    that has any of its squares under the array is inside it wherever its anchor square stands. Step questions (a boundary
    crossing, a per-step movement tax) ask membership at the square before and the square after, never at the anchor alone."""
    return bool(creature.active and engine._footprint_intersects(creature, zone.affected_cells, position=position))


def flag_key(pattern: str, owner_id: str) -> str:
    """A turn flag with "_round_" in its key survives the turn reset: the same named Pulse touches a creature once a round."""
    return f"formation_round_pulse:{owner_id}:{pattern}"


def rest_key(owner_id: str) -> str:
    return f"formation_round_rest:nourishing:{owner_id}"


# ------------------------------------------------------------------------------------------------ the actions
def owned_talents(info: dict[str, Any]) -> list[str]:
    """The Formations talents the character owns, by their last id part ("layered_pattern")."""
    return sorted({str(record_id).rsplit(".", 1)[-1] for record_id in info.get("owned_ids") or [] if ".talent.formations." in str(record_id)})


def talents_of(numbers: dict[str, Any] | None) -> set[str]:
    return set((numbers or {}).get("formation_talents") or [])


def pool_of(info: dict[str, Any]) -> str:
    from ..factory_compiler import RESOURCE_IDS

    return RESOURCE_IDS.get(str(info.get("primary") or "qi"), "resource:core.qi")


def known_patterns(info: dict[str, Any]) -> list[str]:
    """The patterns the character knows.  The owner sheet may list them (``spheres_and_talents.formation_patterns``); a sheet that
    does not (Formation Training's choice is not recorded anywhere yet) is offered all six, so nothing it may use is hidden."""
    listed = (info["owner_sheet"].get("spheres_and_talents") or {}).get("formation_patterns")
    chosen = [key for key in (pattern_key(name) or str(name) for name in listed or []) if key in PATTERNS]
    owned = [str(record_id) for record_id in info.get("owned_ids") or []]
    everyone = [key for key, row in PATTERNS.items() if not row.get("talent") or any(record_id.endswith(row["talent"]) for record_id in owned)]
    return [key for key in chosen if key in everyone] or everyone


def spec_for(pattern: str, damage_type: str | None, radius_ft: int, numbers: dict[str, Any], *, mode: str = "combat", shape: str = "sphere",
             width_ft: int | None = None) -> dict[str, Any]:
    row = PATTERNS[pattern]
    passive = passive_spec(pattern, damage_type, numbers)
    spec: dict[str, Any] = {"name": f"{row['name']} Array", "shape": shape, "size_ft": radius_ft, "color": row["color"], "terrain": [],
                            "difficult": passive["difficult"], "triggers": passive["triggers"], "inside": passive["inside"],
                            "visual": {"material": "glyphs"},
                            "duration": {"kind": "minutes", "amount": 1, "concentration": True} if mode == "combat"
                            else {"kind": "hours", "amount": 8, "concentration": False}}
    if width_ft:
        spec["width_ft"] = width_ft
    return spec


def pulse_rows(pattern: str) -> list[tuple[str | None, str, str, str]]:
    """One Pulse action per (mode, kind of creature) the pattern's Pulse can take: (mode, words for the mode, target kind, "foe"/"ally"/"")."""
    who = PATTERNS[pattern]["pulse_on"]
    kinds = [("HOSTILE_ENTITY", "foe"), ("ALLY_OR_SELF", "ally")] if who == "any" else \
        [("HOSTILE_ENTITY", "")] if who == "hostile" else [("ALLY_OR_SELF", "")]
    return [(mode, words, kind, whom) for mode, words in PULSE_MODES.get(pattern) or [(None, "")] for kind, whom in kinds]


def pulse_action(short: str, actor_id: str, numbers: dict[str, Any], pattern: str, mode: str | None, words: str, kind: str, whom: str, *,
                 variant: str | None = None, costs: tuple[Any, ...] = ()) -> Any:
    """A Pulse Array action.  ``variant`` is ``None`` for the ordinary Bonus Action Pulse; combat/ext/formation_masters.py adds the
    free Pulse (Court, Sovereign) and the second Pulse (Sovereign Pulse) as actions of their own that run the same effect."""
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    typed = {"effects": [{"type": "formation_pulse", "pattern": pattern, "mode": mode, "variant": variant, "evidence": "Pulse Array: one Pattern Layer's Pulse"}],
             "numbers": dict(numbers), "duration": {"kind": "instant"}, "riders": [], "source": "formation_pulse", "sphere": SPHERE,
             "typing_status": "formation_plugin", "coverage": "FULL"}
    label = {"free": "free ", "second": "second "}.get(variant or "", "")
    from ..action_variants import choice, cost_delta, with_variant

    base_id = f"action:typed.{short}.formation.pulse.{pattern}" + (f".{mode}" if mode else "") + (f".{whom}" if whom else "")
    axes = [choice("mode", mode, words)] if mode else []
    axes += [choice("whom", whom, whom)] if whom else []
    if variant:
        # Signed delta against the ordinary Bonus Action Pulse, which pays no extra costs.
        axes.append(choice("tempo", variant, {"free": "Free", "second": "Second"}[variant], cost_delta(costs, ())))
    action = ActionDefinition(
        source_definition_id=base_id + (f".{variant}" if variant else ""),
        display_name=f"{label.capitalize()}Pulse: {PATTERNS[pattern]['name']}" + (f" ({', '.join(x for x in (words, whom) if x)})" if mode or whom else ""),
        owner_id=actor_id, economy=EconomyKind.NONE if variant else EconomyKind.BONUS_ACTION, resolution_kind="TYPED", target_kind=kind, range_ft=None, costs=costs,
        parameters={"typed": typed, "expected_damage": 0, "player_only": True, TAG: "pulse", "pattern": pattern, "variant": variant})
    return with_variant(action, base_id, f"Pulse: {PATTERNS[pattern]['name']}", axes)


@hook("compile_actions")
def compile_actions(info: dict[str, Any]) -> list[Any] | None:
    from ..factory_compiler import RESOURCE_IDS
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    if BASE_SET not in (info.get("owned_ids") or []) and SPHERE not in (info.get("spheres") or []):
        return None
    pool = RESOURCE_IDS.get(str(info.get("primary") or "qi"), "resource:core.qi")
    from ..action_variants import choice, with_variant

    short, actor_id = info["short"], info["actor_id"]
    # What the array's record and its Pulses need to know about the owner: the talents it has, the pool its CP come from.
    numbers = {**info["numbers"], "formation_talents": owned_talents(info), "formation_pool": pool}
    out: list[Any] = []
    radius = COMBAT_RADIUS_FT + _radius_bonus(info)
    # Do not extend the legacy all-pattern fallback to AI seats: absence of a
    # recorded learning choice is not evidence that the actor knows a pattern.
    listed = (info["owner_sheet"].get("spheres_and_talents") or {}).get("formation_patterns") or []
    recorded_patterns = {pattern_key(name) or str(name) for name in listed}
    for pattern in known_patterns(info):
        # Sphere membership alone is not an acquisition receipt for Set Array.
        # Preserve sibling Pulse/Collapse providers when only Set is unowned.
        types = (killing_types(info) if pattern == "killing_line" else (None,)) if BASE_SET in (info.get("owned_ids") or []) else ()
        for damage_type in types:
            label = PATTERNS[pattern]["name"] + (f" ({damage_type.title()})" if damage_type else "")
            typed = {"effects": [{"type": "formation_set", "pattern": pattern, "damage_type": damage_type, "mode": "combat",
                                  "evidence": "Set Array, Combat Array: a 10-foot-radius circle within 30 feet, one Basic Pattern you know"}],
                     "numbers": dict(numbers), "duration": {"kind": "minutes", "amount": 1, "concentration": True},
                     "zone_spec": spec_for(pattern, damage_type, radius, numbers), "riders": [], "source": "formation_set",
                     "sphere": SPHERE, "typing_status": "formation_plugin", "coverage": "FULL"}
            out.append(with_variant(ActionDefinition(
                source_definition_id=f"action:typed.{short}.formation.set.{pattern}" + (f".{damage_type}" if damage_type else ""),
                display_name=f"Combat Array: {label}", owner_id=actor_id, economy=EconomyKind.ACTION, resolution_kind="TYPED",
                target_kind="CELL", range_ft=SET_RANGE_FT, costs=((pool, 2),), concentration=True,
                parameters={"typed": typed, "expected_damage": 0, "any_cell": True, "ai_empty_area_filter": False,
                            "player_only": pattern not in recorded_patterns, TAG: "set", "pattern": pattern}),
                                   f"action:typed.{short}.formation.set.{pattern}", f"Combat Array: {PATTERNS[pattern]['name']}",
                                   ((choice("damage_type", damage_type, damage_type.title()),) if damage_type else ())))
        for mode, words, kind, whom in pulse_rows(pattern):
            out.append(pulse_action(short, actor_id, numbers, pattern, mode, words, kind, whom))
    return out


@hook("compile_actions")
def compile_collapse(info: dict[str, Any]) -> list[Any] | None:
    """Publish Collapse independently of Set Array, for its owner and AI seats."""
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    from ..factory_compiler import RESOURCE_IDS

    if BASE_COLLAPSE not in (info.get("owned_ids") or []):
        return None
    short, actor_id = info["short"], info["actor_id"]
    numbers = {**info["numbers"], "formation_talents": owned_talents(info),
               "formation_pool": RESOURCE_IDS.get(str(info.get("primary") or "qi"), "resource:core.qi")}
    return [ActionDefinition(
        source_definition_id=f"action:typed.{short}.formation.collapse", display_name="Collapse Array", owner_id=actor_id,
        economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="CELL", range_ft=PULSE_RANGE_FT,
        parameters={"typed": {"effects": [{"type": "formation_collapse", "evidence": "Collapse Array: one array within 120 feet, no action"}],
                              "numbers": dict(numbers), "duration": {"kind": "instant"}, "riders": [], "source": "formation_collapse", "sphere": SPHERE,
                              "typing_status": "formation_plugin", "coverage": "FULL"},
                    "expected_damage": 0, "ai_allow_empty_area": True, "any_cell": True, TAG: "collapse"})]


@hook("ai_score_components")
def collapse_retention(context: Any, candidate: Any, option_ids: Any) -> tuple[Any, ...] | None:
    """Keep an established array unless an explicit tactical priority outweighs it.

    A free CELL action is published as BONUS_ACTION by the native menu. Its mere
    presence gives End Turn a -1000 sequencing score, even after all useful
    actions are spent. Retention must outweigh that bias and the -30 no-progress
    adjustment. This is valuation only: human/model choices remain legal, and
    an authored action priority can still favor an intentional collapse. Read
    only the actor's own ability, never unseen occupants or enemy statistics.
    """
    if not candidate.source_definition_id.endswith(".formation.collapse"):
        return None
    from ..gate4_models import ComponentScore
    return (ComponentScore(component="formation_retention", value=-1200,
                           explanation="Preserve your existing array unless ending it serves an explicit tactical priority."),)


def _radius_bonus(info: dict[str, Any]) -> int:
    """Expanded Geometry: "+5 feet to the radius of your Combat Arrays" for each time it is taken (owned once per record)."""
    owned = info.get("owned_ids") or []
    return 5 * sum(1 for record_id in owned if str(record_id).endswith("expanded_geometry"))


# What the compiler already made from the same texts and is replaced by the rows above (its Set Array / Pulse Array rows stay
# inert, the rest aim at the wrong thing): hidden from the menu by candidate_allowed.
def _own(action: Any) -> bool:
    return bool((getattr(action, "parameters", None) or {}).get(TAG))


def _replaced(action: Any) -> bool:
    source = str(getattr(action, "source_definition_id", ""))
    return source.endswith(f".{BASE_SET}") or source.endswith(f".{BASE_PULSE}") or \
        any(source.endswith(f".tianxia.talent.formations.{talent}") for talent in REPLACED)


@hook("candidate_allowed")
def candidate_allowed(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if action is None:
        return None
    if _replaced(action):
        return False
    kind = (action.parameters or {}).get(TAG)
    if kind == "pulse":
        victim = engine.state.actors.get(candidate.target_ids[0]) if candidate.target_ids else None
        return None if victim is not None and pulse_source(engine, actor, action.parameters["pattern"], victim, action.parameters.get("variant")) is not None else False
    if kind == "collapse":
        aim = candidate.destination
        return None if aim is not None and array_at(engine, actor, aim) is not None else False
    if kind == "set":
        return None
    return None


@hook("ai_candidate_allowed")
def ai_candidate_allowed(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    # The AI is not taught to strike a formation's Eye or Node (its scoring only understands creatures).
    if (candidate.metadata or {}).get("object_target"):
        obj = engine.state.objects.get(candidate.target_ids[0]) if candidate.target_ids else None
        if obj is not None and (obj.component or {}).get(KEY):
            return False
    return None


def array_at(engine: Any, actor: Any, aim: Any) -> Any:
    """The actor's array whose circle holds this square (and is within 120 feet of the actor)."""
    for zone in arrays(engine, actor.entity_id):
        if any((cell.x, cell.y) == (aim.x, aim.y) for cell in zone.affected_cells) and \
                engine._distance_actor_to_cell(actor, zone.center) <= PULSE_RANGE_FT:
            return zone
    return None


def pulse_array(engine: Any, actor: Any, pattern: str, victim: Any, only: str | None = None, domain: bool = False) -> Any:
    """The array a Pulse of this pattern on this creature would come from: the actor's, within 120 feet of it, carrying the
    pattern as a layer, with the creature inside it or at its boundary; not one the creature already felt this round.  ``only``
    names the one array to use (a second Pulse in the array the first came from); ``domain`` limits it to a Court or Sovereign
    Array (their free Pulse)."""
    if victim.turn_flags.get(flag_key(pattern, actor.entity_id)) == engine.state.round_number:
        return None
    if pattern == "nourishing_cycle" and victim.turn_flags.get(rest_key(actor.entity_id)):
        return None  # "A creature can benefit from this Pulse only once per short rest" (a fight is well inside one)
    for zone in arrays(engine, actor.entity_id):
        eye = engine.state.objects.get(record(zone).get("eye") or "")
        if (only is None or zone.zone_id == only) and (not domain or record(zone).get("domain")) and pattern in (record(zone).get("layers") or []) \
                and inside(engine, victim, zone) and (not disrupted(eye) or record(zone).get("held")) \
                and engine._distance_actor_to_cell(actor, zone.center) <= PULSE_RANGE_FT:
            return zone  # (a disrupted Eye "cannot be used to Pulse the array"; the Eye of the Formation Master's hold sets that aside)
    return None


def pulse_source(engine: Any, actor: Any, pattern: str, victim: Any, variant: str | None) -> Any:
    """The array an ordinary, free (Court, Sovereign) or second (Sovereign Pulse, Sovereign) Pulse would come from, or None."""
    flags = actor.turn_flags
    if variant == "free":
        return None if flags.get("formation_free_pulse") else pulse_array(engine, actor, pattern, victim, domain=True)
    if variant == "second":
        pulsed = flags.get("formation_pulsed") or {}
        zone = engine.state.zones.get(pulsed.get("zone") or "")
        if zone is None or not zone.active or flags.get("formation_second_pulse") or pattern in (pulsed.get("layers") or []):
            return None  # "Pulse two different Pattern Layers in that array"
        if "sovereign_pulse" not in talents_of(record(zone).get("numbers")) and record(zone).get("domain") != "sovereign":
            return None
        return pulse_array(engine, actor, pattern, victim, only=zone.zone_id)
    return pulse_array(engine, actor, pattern, victim)


def disrupted(obj: Any) -> bool:
    """Disrupt Node: the part is out of play until the start of its disruptor's next turn."""
    return obj is not None and bool((obj.component or {}).get("disrupted_by"))


# ------------------------------------------------------------------------------------------------ effects
def fresh_zone(engine: Any, actor: Any, source: str) -> Any:
    fresh = [zone for zone in engine.state.zones.values() if zone.active and zone.owner_id == actor.entity_id
             and zone.source_definition_id == source and not zone.trigger_profile.get(KEY)]
    return max(fresh, key=_order) if fresh else None


SETUP = "formation_setup"


def setup_of(actor: Any) -> dict[str, Any]:
    """What the owner has chosen for the next array she sets (a second layer, a line, creatures to key): the data of her
    ``formation_setup`` condition (combat/ext/formation_talents.py puts it there)."""
    iid = has_condition(actor, SETUP)
    return dict(actor.conditions[iid].data or {}) if iid is not None else {}


def line_cells(engine: Any, actor: Any, eye: Any, length_ft: int) -> tuple[Any, ...]:
    """A Line Array: it runs from its Eye ("at one end") straight away from the one who set it, one square wide."""
    from ..gate2_runtime_models import Position

    dx = (eye.x > actor.position.x) - (eye.x < actor.position.x)
    dy = (eye.y > actor.position.y) - (eye.y < actor.position.y)
    dx = dx or (0 if dy else 1)
    count = max(1, int(length_ft) // engine.grid.square_size_ft)
    cells = [(eye.x + dx * step, eye.y + dy * step) for step in range(count)]
    return tuple(Position(x=x, y=y) for x, y in cells if engine.grid.in_bounds((x, y))) or (eye,)


def add_layer(zone: Any, pattern: str, damage_type: str | None, numbers: dict[str, Any]) -> None:
    """Give an array a second Pattern Layer: its Passive joins the zone's rows."""
    extra = passive_spec(pattern, damage_type, numbers)
    profile = dict(zone.trigger_profile)
    profile["triggers"] = [*(profile.get("triggers") or []), *extra["triggers"]]
    profile["inside"] = [*(profile.get("inside") or []), *extra["inside"]]
    profile["difficult"] = profile.get("difficult") or extra["difficult"]
    profile["name"] = f"{str(profile.get('name') or 'Array').removesuffix(' Array')} + {PATTERNS[pattern]['name']} Array"
    zone.trigger_profile = profile


@effect("formation_set")
def formation_set(ctx: Any, eff: dict[str, Any]) -> None:
    from .. import zones
    from ..gate2_runtime_models import RuntimeObjectState

    engine, actor = ctx.engine, ctx.actor
    zone = fresh_zone(engine, actor, ctx.source)
    if zone is None:
        ctx.rider("The array did not take shape.")
        return
    cl = int(ctx.numbers.get("cl") or 1)
    talents = talents_of(ctx.numbers)
    pattern = str(eff.get("pattern"))
    name = PATTERNS[pattern]["name"]
    setup = setup_of(actor)
    layers, damage_type = [pattern], eff.get("damage_type")
    layer = str(setup.get("layer") or "")
    pool = str(ctx.numbers.get("formation_pool") or "resource:core.qi")
    words = []
    if layer and layer != pattern and layer in PATTERNS and "layered_pattern" in talents and cl >= 5:
        # Layered Pattern: "you may add a second Pattern Layer you know. Increase the CP cost by 2."
        if actor.resources.get(pool, 0) >= 2:
            engine._spend_resource(actor, pool, 2, ctx.source)
            layers.append(layer)
            damage_type = damage_type or setup.get("layer_type")
            add_layer(zone, layer, setup.get("layer_type"), ctx.numbers)
            name = f"{name} + {PATTERNS[layer]['name']}"
            words.append("2 more CP for the second layer")
        else:
            ctx.rider(f"Not enough CP for the second layer ({PATTERNS[layer]['name']}): the array has only {name}.")
    load = load_of(ctx.numbers, _load_bonus(actor))
    others = [row for row in arrays(engine, actor.entity_id) if row.zone_id != zone.zone_id and not record(row).get("domain")]  # (a Court or Sovereign is a Domain, not an array)
    while len(others) >= load:  # "or if you create another active array beyond your Formation Load"
        collapse(engine, others.pop(0), "LOAD", ctx.source)
    is_line = bool(setup.get("line")) and "line_array" in talents
    if is_line:
        # Line Array: "a Combat Line Array is up to 30 feet long and 5 feet wide", its Eye at one end.
        zone.affected_cells = line_cells(engine, actor, zone.center, 30)
        zone.trigger_profile = {**zone.trigger_profile, "shape": "line"}
        words.append("shaped as a line")
    bonus = cl if "reinforced_nodes" in talents else 0  # "Increase the Hit Points of your Nodes and Eyes by your CL"
    eye = RuntimeObjectState(object_id=f"{OBJECT_PREFIX}{zone.zone_id}:eye", object_kind="FORMATION_EYE", position=zone.center,
                             unattended=True, flammable=False, owner_id=actor.entity_id, ac=13, current_hp=5 + cl + bonus, maximum_hp=5 + cl + bonus,
                             damage_immunities=IMMUNE, component={KEY: zone.zone_id, "role": "eye"})
    engine._update_object(eye, ctx.source, actor.entity_id)
    keyed_list = [str(key) for key in setup.get("keyed") or []] if "gate_keeper" in talents else []
    profile = {"mode": str(eff.get("mode") or "combat"), "layers": layers, "damage_type": damage_type,
               "eye": eye.object_id, "nodes": [], "cl": cl, "owner": actor.entity_id, "numbers": dict(ctx.numbers),
               "line": is_line, "keyed": keyed_list,
               # Elemental Killing Array: the rider chosen "when you create a Killing Line Pattern" (combat/ext/formation_masters.py)
               "element": setup.get("element") if "elemental_killing_array" in talents and cl >= 5 and "killing_line" in layers else None}
    save_zone(engine, zone, ctx.source, profile)
    if is_line or len(layers) > 1:
        zones.sync_inside(engine, ctx.source)
    if setup:
        engine._remove_condition(actor, f"condition:typed.{SETUP}", ctx.source)
    notice(ctx, f"{name} Array set at ({zone.center.x},{zone.center.y}): {len(zone.affected_cells)} squares" + (f" ({', '.join(words)})" if words else "") +
              f". Its Eye has AC 13 and {5 + cl + bonus} HP; the array collapses if the Eye is destroyed, if you lose Concentration, "
              f"or if you set more arrays than your Load of {load}.")


def _load_bonus(actor: Any) -> int:
    return 0


@effect("formation_collapse")
def formation_collapse(ctx: Any, eff: dict[str, Any]) -> None:
    aim = getattr(ctx.intent, "destination", None)
    available = [zone for zone in arrays(ctx.engine, ctx.actor.entity_id)
                 if aim is not None and (aim.x, aim.y) in cells_of(zone)
                 and ctx.engine._distance_actor_to_cell(ctx.actor, zone.center) <= PULSE_RANGE_FT]
    if not available:
        ctx.rider("No array of yours there to collapse.")
        return
    zone = available[0]
    if len(available) > 1:
        from .needle import CHOICE, ask, checkpoint_id
        selected = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "COLLAPSE_ARRAY", ctx.actor.entity_id),
                       ctx.actor, CHOICE + "formation_collapse", [row.zone_id for row in available],
                       labels={row.zone_id: f"Array {index}: {row.trigger_profile.get('name') or 'Formation Array'} at ({row.center.x}, {row.center.y})"
                               for index, row in enumerate(available, 1)}, name="Collapse Array", feature_id=BASE_COLLAPSE,
                       prompt=f"Collapse Array: {ctx.actor.display_name}, choose one of your arrays at this square to end now. "
                              "This costs no action or Cultivation Points (CP) on your turn. Ending its harmful effects is harmless unless a talent says otherwise.")
        if not selected:
            return
        zone = next(row for row in available if row.zone_id == selected[0])
    collapse(ctx.engine, zone, "COLLAPSED", ctx.source)
    from . import formation_talents

    formation_talents.after_collapse(ctx, zone)


@effect("formation_pulse")
def formation_pulse(ctx: Any, eff: dict[str, Any]) -> None:
    from ..typed_executor import run_effects

    engine, actor = ctx.engine, ctx.actor
    pattern = str(eff.get("pattern"))
    victim = ctx.target or (ctx.targets[0] if ctx.targets else (actor if str(ctx.action.target_kind).endswith("ALLY_OR_SELF") else None))
    if victim is None:
        return
    variant = eff.get("variant")
    pulsed = actor.turn_flags.get("formation_pulsed") or {}
    zone = pulse_source(engine, actor, pattern, victim, variant)
    if zone is None:
        ctx.rider(f"No {PATTERNS[pattern]['name']} array of yours reaches {victim.display_name}.")
        return
    victim.turn_flags[flag_key(pattern, actor.entity_id)] = engine.state.round_number
    if pattern == "nourishing_cycle":
        victim.turn_flags[rest_key(actor.entity_id)] = True
    # What this turn's Pulses were, for the talents that build on a Pulse (combat/ext/formation_masters.py: the free Pulse, the second Pulse,
    # Harmonized Pulse).
    actor.turn_flags["formation_pulsed"] = {"zone": zone.zone_id, "layers": [*(pulsed.get("layers") or []), pattern]}
    if variant in ("free", "second"):
        actor.turn_flags[f"formation_{variant}_pulse"] = True
    say(engine, ctx.source, actor.entity_id, f"{PATTERNS[pattern]['name']} Pulse from the array at ({zone.center.x},{zone.center.y}) on {victim.display_name}.")
    ctx.damage_cache["formation_zone"] = zone.zone_id
    profile = record(zone)
    from . import formation_riders

    # Nine Palaces Killing Array: one roll against up to three creatures (combat/ext/formation_riders.py)
    if not (pattern == "killing_line" and formation_riders.nine_palaces(ctx, zone, victim)):
        run_effects(ctx, pulse_effects(pattern, profile.get("damage_type"), eff.get("mode"), talents=talents_of(profile.get("numbers")),
                                       element=profile.get("element"), extra_pb=profile.get("harmonized") == "killing_line"))
    formation_riders.release_stored(ctx, zone)  # Array That Swallows the Attack: the stored force goes out with a Pulse


@effect("formation_slow")
def formation_slow(ctx: Any, eff: dict[str, Any]) -> None:
    """A Pulse's Speed penalty.  Sovereign Pulse: "If both Pulses would impose movement penalties, use the stronger penalty rather than
    stacking them": what this owner's Pulses have already taken off the creature is noted in the owner's turn flags (which last as long as
    the penalty does, until the start of the owner's next turn), and only the part beyond it is applied."""
    from ..typed_executor import run_effects

    victim = ctx.target or (ctx.targets[0] if ctx.targets else None)
    if victim is None:
        return
    key, amount = f"formation_slow:{victim.entity_id}", int(eff.get("amount") or 10)
    have = int(ctx.actor.turn_flags.get(key) or 0)
    if have >= amount:
        notice(ctx, f"{victim.display_name} is already slowed by {have} feet from this turn's Pulses: the stronger penalty counts, they do not stack.")
        return
    ctx.actor.turn_flags[key] = amount
    run_effects(ctx, [{"type": "speed", "amount": -(amount - have), "applies_to": "target", "duration": "until_start_of_your_next_turn",
                       "evidence": eff.get("evidence") or "its Speed is reduced until the start of your next turn"}])


# ------------------------------------------------------------------------------------------------ who is keyed, checks
def keyed(engine: Any, zone: Any, creature: Any) -> bool:
    """Keyed to the array: the owner's own side (its allies pass its gates), or anyone the owner keyed (Gate Keeper)."""
    owner = engine.state.actors.get(zone.owner_id)
    return creature.entity_id in (record(zone).get("keyed") or []) or (owner is not None and owner.team_id == creature.team_id)


def hostile_to(engine: Any, zone: Any, creature: Any) -> bool:
    """A creature the array's hostile effects (difficult ground, Killing Line, a boundary) work on: not of the owner's side and not keyed."""
    owner = engine.state.actors.get(zone.owner_id)
    return owner is not None and owner.team_id != creature.team_id and creature.entity_id not in (record(zone).get("keyed") or [])


def formation_check(engine: Any, actor: Any, numbers: dict[str, Any], dc: int, source: str, label: str, mode: str = "NORMAL", *, hazards=()) -> bool:
    """A Formation Check: d20 + Proficiency Bonus + the Formation key ability modifier (the character's cultivation attack bonus)."""
    # The caller names purpose, never this helper's display label. The scope
    # carries the same facts through finalized-roll consumption and replay.
    reason = f'CHECK:{source}:{label}'
    with engine.d20_scope({'kind': 'check', 'actor_id': actor.entity_id,
                          'source_id': source, 'source_actor_id': actor.entity_id,
                          'check_kind': 'cultivation', 'reason': reason,
                          'hazards': list(hazards)}):
        roll = engine.roll_check(
            modifier=int(numbers.get('attack_bonus') or 0), actor_id=actor.entity_id,
            reason=reason, modes=(mode,), hazards=hazards)
    engine._record_roll(roll)
    success = int(roll.total) >= int(dc)
    engine._append_event("CHECK_ROLLED", source, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                         payload={"actor": roll.model_dump(mode="json"), "dc": int(dc), "success": success, "check": label})
    return success


def cells_of(zone: Any) -> set[tuple[int, int]]:
    return {(cell.x, cell.y) for cell in zone.affected_cells}


def _segment_touches(zone: Any, start: Any, end: Any) -> bool:
    """Whether the straight line from ``start`` to ``end`` passes over a square of the array."""
    cells, steps = cells_of(zone), max(abs(end.x - start.x), abs(end.y - start.y)) * 2 or 1
    return any((round(start.x + (end.x - start.x) * i / steps), round(start.y + (end.y - start.y) * i / steps)) in cells for i in range(steps + 1))


def has_condition(actor: Any, name: str) -> Any:
    return next((iid for iid, condition in actor.conditions.items() if condition.condition_id == f"condition:typed.{name}"), None)


def located(engine: Any, viewer: Any, seen: Any) -> bool:
    """Sensing Eye Pulse: the array's owner knows where the creature is while it stays inside the array."""
    marked = has_condition(seen, "formation_located")
    if marked is None or seen.conditions[marked].source_actor_id != viewer.entity_id:
        return False
    return any("sensing_eye" in (record(zone).get("layers") or []) and inside(engine, seen, zone) for zone in arrays(engine, viewer.entity_id))


# ------------------------------------------------------------------------------------------------ pattern effects and hooks
@effect("formation_locate")
def formation_locate(ctx: Any, eff: dict[str, Any]) -> None:
    from ..typed_executor import run_effects

    run_effects(ctx, [{"type": "condition", "condition": "formation_located", "applies_to": "target", "duration": "until_start_of_your_next_turn",
                       "evidence": eff.get("evidence") or "Sensing Eye Pulse"}])
    victim = ctx.target or (ctx.targets[0] if ctx.targets else None)
    if victim is not None:
        notice(ctx, f"You know where {victim.display_name} is until the start of your next turn while it stays inside the array, even if it is Invisible or Hidden.")


@effect("formation_sense")
def formation_sense(ctx: Any, eff: dict[str, Any]) -> None:
    """Sensing Eye's Passive: "you know when a creature enters or leaves the array ... the number of creatures inside, but not their identities"."""
    engine, creature = ctx.engine, ctx.target
    zone = next((zone for zone in arrays(engine, ctx.actor.entity_id) if "sensing_eye" in (record(zone).get("layers") or []) and inside(engine, creature, zone)), None)
    if zone is None:
        return
    count = sum(1 for other in engine.state.actors.values() if other.active and inside(engine, other, zone))
    notice(ctx, f"Sensing Eye: a creature enters the array at ({zone.center.x},{zone.center.y}); {count} inside now.")


@effect("formation_veil")
def formation_veil(ctx: Any, eff: dict[str, Any]) -> None:
    """Veiled Road Pulse: the chosen creature moves up to 10 feet without Opportunity Attacks, or Hides if it has cover or concealment."""
    from .. import stealth
    from ..typed_executor import run_effects

    engine = ctx.engine
    victim = ctx.target or (ctx.targets[0] if ctx.targets else ctx.actor)
    if str(eff.get("mode") or "move") == "hide":
        bonus = next((int(((row.parameters or {}).get("typed") or {}).get("effects", [{}])[0].get("bonus") or 0) for row in engine.action_catalog.values()
                      if row.owner_id == victim.entity_id and ((row.parameters or {}).get("typed") or {}).get("effects", [{}])[0].get("type") == "hide"), 0)
        if stealth.hide(engine, victim, bonus, ctx.source):
            notice(ctx, f"{victim.display_name} hides.")
        else:
            notice(ctx, f"{victim.display_name} has no cover or concealment to hide in (or is already hidden).")
        return
    if victim.entity_id == ctx.actor.entity_id:
        run_effects(ctx, [{"type": "movement", "distance_ft": 10, "no_opportunity_attacks": True, "applies_to": "self",
                           "evidence": eff.get("evidence") or "Veiled Road Pulse"}])
        return
    # An ally's move is spent on its own turn: banked as a condition until then (turn_start below grants it).
    engine._apply_condition(victim, "condition:typed.formation_free_step", ctx.source, ctx.actor.entity_id, expires_on="END_OF_HOLDER_NEXT_TURN")
    notice(ctx, f"{victim.display_name} may move up to 10 feet without provoking Opportunity Attacks on its next turn.")


@hook("stealth_search_mode")
def veiled_search(engine: Any, searcher: Any, foe: Any) -> str | None:
    """Veiled Road Passive: creatures outside the array have Disadvantage on Wisdom (Perception) to observe what is inside."""
    for zone in arrays(engine):
        if "veiled_road" in (record(zone).get("layers") or []) and inside(engine, foe, zone) and not inside(engine, searcher, zone):
            return "DISADVANTAGE"
    return None


def _cp_locked(actor: Any, row: dict[str, Any]) -> bool:
    """A reaction row that costs CP, for a creature Suppressing Vein has locked."""
    if has_condition(actor, "formation_cp_locked") is None:
        return False
    cost = row.get("cost")
    return (isinstance(cost, (int, float)) and cost > 0) or any(int(amount or 0) > 0 for _resource, amount in (cost_parts(part) for part in row.get("costs") or []))


@hook("row_allowed")
def row_allowed(engine: Any, actor: Any, row: dict[str, Any]) -> bool | None:
    """Suppressing Vein Pulse (failed save): it cannot spend CP on Reactions, Counter effects or defensive sphere effects."""
    return False if _cp_locked(actor, row) else None


@hook("reaction_subject_allowed")
def reaction_subject_allowed(engine: Any, reactor: Any, other: Any, row: dict[str, Any]) -> bool | None:
    return False if _cp_locked(reactor, row) else None


CP_POOLS = (".qi", ".stamina", ".resonance")


def _tax(engine: Any, kwargs: dict[str, Any]) -> None:
    """Suppressing Vein Pulse (successful save): the next time it spends CP before then, it spends 1 additional CP."""
    payload = kwargs.get("payload") or {}
    resource = str(payload.get("resource_id") or "")
    actor = engine.state.actors.get(kwargs.get("actor_id") or "")
    if actor is None or int(payload.get("amount") or 0) <= 0 or not resource.endswith(CP_POOLS):
        return
    iid = has_condition(actor, "formation_cp_tax")
    if iid is None:
        return
    source = "formation:suppressing_vein"
    engine._remove_condition(actor, actor.conditions[iid].condition_id, source)
    if actor.resources.get(resource, 0) >= 1:
        engine._spend_resource(actor, resource, 1, source)
        say(engine, source, actor.entity_id, f"Suppressing Vein: {actor.display_name} spends 1 additional CP.")


@hook("escape_mode")
def escape_mode(engine: Any, escaper: Any, grips: list[Any]) -> str | None:
    """Binding Passive: Disadvantage on checks to escape a grip that the array owner's allies put on it."""
    from ..typed_executor import is_active_typed_condition

    for condition in escaper.conditions.values():
        mode = (((condition.data or {}).get("rule") or {}).get("escape_vs_allies_of_source")) if is_active_typed_condition(condition) else None
        setter = engine.state.actors.get(condition.source_actor_id) if mode else None
        if setter is not None and any((holder := engine.state.actors.get(grip.source_actor_id)) is not None and holder.team_id == setter.team_id for grip in grips):
            return str(mode)
    return None


def gate_label(engine: Any, zone: Any, actor: Any, start: Any, destination: Any) -> str | None:
    """Why teleporting from ``start`` to ``destination`` is checked by this array (None: it is not).  Sealing Gate Passive: into, out of or
    through the array (a Court's keyed allies "move through its Gates safely").  Sovereign of the World-Diagram: a hostile creature inside.
    Mountain-Sealing Great Array: anyone inside or arriving, unless keyed by name."""
    profile, domain = record(zone), record(zone).get("domain")
    cells = cells_of(zone)
    was, will = (start.x, start.y) in cells, (destination.x, destination.y) in cells
    if domain == "mountain" and actor.entity_id not in (profile.get("keyed") or []) and (was or will):
        return "Mountain-Sealing Great Array"
    if domain == "sovereign" and was and hostile_to(engine, zone, actor):
        return "Sovereign Array"
    if "sealing_gate" in (profile.get("layers") or []) and not (domain == "court" and keyed(engine, zone, actor)) \
            and (was != will or (not was and _segment_touches(zone, start, destination))):
        return "Sealing Gate array"
    return None


@hook("teleport_check")
def teleport_check(engine: Any, actor: Any, start: Any, destination: Any) -> bool | None:
    """Sealing Gate Passive (and the Sovereign Array, the Mountain-Sealing Great Array): teleporting takes a Charisma saving throw; a failed one
    fails the teleport.  Spirit-Lock Array: a creature that failed the Sealing Gate's save cannot teleport at all until the start of the owner's turn."""
    verdict = None
    if has_condition(actor, "formation_spirit_locked") is not None:
        say(engine, "formation:spirit_lock_array", actor.entity_id, f"Spirit-Lock Array: {actor.display_name} cannot be teleported right now.")
        verdict = False
    for zone in arrays(engine):
        label = gate_label(engine, zone, actor, start, destination)
        if label is None:
            continue
        dc = int((record(zone).get("numbers") or {}).get("save_dc") or 10)
        weak = has_condition(actor, "formation_teleport_dis")
        roll = engine._roll_save(actor, "CHA", dc, f"formation:sealing_gate:{zone.zone_id}", extra_mode="DISADVANTAGE" if weak is not None else None)
        if weak is not None:
            engine._remove_condition(actor, actor.conditions[weak].condition_id, "formation:sealing_gate")
        if roll is not None and int(roll.total) >= dc:
            continue
        say(engine, "formation:sealing_gate", actor.entity_id, f"The {label} at ({zone.center.x},{zone.center.y}) holds: {actor.display_name}'s teleport fails and what it spent is wasted.")
        verdict = False
    return verdict


@hook("turn_start")
def free_step(engine: Any, actor: Any) -> None:
    """Veiled Road Pulse on an ally: the move banked for its next turn (10 feet, no Opportunity Attacks)."""
    if has_condition(actor, "formation_free_step") is None:
        return
    engine._remove_condition(actor, "condition:typed.formation_free_step", "formation:veiled_road")
    actor.movement_remaining_ft += 10
    actor.turn_flags["oa_free_ft"] = int(actor.turn_flags.get("oa_free_ft") or 0) + 10
    engine._append_event("MOVEMENT_GRANTED", "formation:veiled_road", actor_id=actor.entity_id, payload={"distance_ft": 10})


# ------------------------------------------------------------------------------------------------ collapse and the sweep
def collapse(engine: Any, zone: Any, reason: str, source: str) -> None:
    """End an array: its Eye and Nodes go, its Concentration ends, its zone is removed, what stood inside it is put right."""
    from .. import zones

    if not zone.active:
        return
    owner = engine.state.actors.get(zone.owner_id)
    for obj in objects_of(engine, zone):
        if not obj.destroyed:
            engine._update_object(obj.model_copy(update={"destroyed": True}), source, zone.owner_id)
    if owner is not None and owner.concentration is not None and owner.concentration.zone_id == zone.zone_id:
        engine._end_concentration(owner, "ARRAY_COLLAPSED")
    zones.remove(engine, zone, reason)
    if zone.active:  # (not reached: zones.remove clears it)
        zone.active = False
    zones.sync_inside(engine, source)
    words = {"EYE": "its Eye was destroyed", "NODES": "too many of its Nodes were destroyed", "LOAD": "another array went past your Formation Load",
             "COLLAPSED": "it was collapsed", "CONCENTRATION": "Concentration ended",
             "UNSTABLE": "it was unstable and its creator failed the Formation Check to hold it", "INCAPACITATED": "its Eye, the one who cast it, was Incapacitated",
             "HELD": "the auxiliary Eye's hold ran out", "ANCHORS": "two of its Anchors were destroyed"}
    say(engine, source, zone.owner_id, f"The {zone.trigger_profile.get('name') or 'formation array'} at ({zone.center.x},{zone.center.y}) collapses: "
                                        f"{words.get(reason, reason.lower())}.")


def sweep(engine: Any, source: str = "formation") -> None:
    """Bring every array in line with its parts: an array whose zone has ended loses its Eye and Nodes; one whose Eye is gone (or,
    for a Prepared Array, two of three Nodes) collapses."""
    for obj in list(engine.state.objects.values()):
        zone_id = (obj.component or {}).get(KEY)
        if not zone_id or obj.destroyed:
            continue
        zone = engine.state.zones.get(zone_id)
        if zone is None or not zone.active:
            engine._update_object(obj.model_copy(update={"destroyed": True}), source, obj.owner_id)
    from . import formation_masters

    for zone in arrays(engine):
        profile = record(zone)
        nodes = [engine.state.objects.get(oid) for oid in profile.get("nodes") or []]
        gone = sum(1 for node in nodes if node is None or node.destroyed)
        if profile.get("eye_actor"):  # Sovereign of the World-Diagram: "You are the Array Eye. If you become Incapacitated, the Sovereign Array collapses."
            who = engine.state.actors.get(profile["eye_actor"])
            if who is None or not who.active or formation_masters.incapacitated(who):
                collapse(engine, zone, "INCAPACITATED", source)
                continue
        if not profile.get("no_eye"):  # (the Sovereign Array and the Mountain-Sealing Great Array have no Eye object)
            eye = engine.state.objects.get(profile.get("eye") or "")
            if eye is None or eye.destroyed or eye.suppressed:
                if not formation_masters.hold(engine, zone, source):
                    collapse(engine, zone, "EYE", source)
                continue
        if nodes and gone >= int(profile.get("collapse_at") or -(-2 * len(nodes) // 3)):  # "If two of its three Nodes are destroyed"
            collapse(engine, zone, "ANCHORS" if profile.get("domain") == "mountain" else "NODES", source)


@hook("event")
def on_event(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """An array's parts and its zone stand or fall together, whoever ends one (a weapon attack on its Eye, a Concentration that
    breaks, another plug-in's object rules)."""
    payload = kwargs.get("payload") or {}
    if event_type == "ZONE_REMOVED":
        zone = engine.state.zones.get(payload.get("zone_id") or "")
        if zone is not None and zone.trigger_profile.get(KEY):
            sweep(engine, "formation")
    elif event_type == "OBJECT_UPDATED" and ((payload.get("object") or {}).get("component") or {}).get(KEY):
        sweep(engine, "formation")
    elif event_type == "RESOURCE_SPENT":
        _tax(engine, kwargs)
    elif event_type == "MOVEMENT_COMMITTED":
        _leaves(engine, kwargs)


def _leaves(engine: Any, kwargs: dict[str, Any]) -> None:
    """Sensing Eye Passive: the owner knows when a creature leaves the array (entering is its zone trigger)."""
    payload = kwargs.get("payload") or {}
    mover = engine.state.actors.get(kwargs.get("actor_id") or "")
    if mover is None or not payload.get("path") or payload.get("formation_rewind"):
        return
    for zone in arrays(engine):
        if "sensing_eye" in (record(zone).get("layers") or []) and not inside(engine, mover, zone) \
                and any((step.get("x"), step.get("y")) in cells_of(zone) for step in payload["path"][:-1] if isinstance(step, dict)):
            count = sum(1 for other in engine.state.actors.values() if other.active and inside(engine, other, zone))
            say(engine, "formation:sensing_eye", zone.owner_id, f"Sensing Eye: a creature leaves the array at ({zone.center.x},{zone.center.y}); {count} inside now.")


@hook("turn_start")
def on_turn_start(engine: Any, actor: Any) -> None:
    for obj in list(engine.state.objects.values()):  # Disrupt Node: "until the start of your next turn" (the disruptor's)
        if (obj.component or {}).get("disrupted_by") == actor.entity_id and not obj.destroyed:
            engine._update_object(obj.model_copy(update={"component": {**obj.component, "disrupted_by": None}}), "formation:disrupt_node", actor.entity_id)
            say(engine, "formation:disrupt_node", actor.entity_id, f"{part_name(engine, obj)} is no longer disrupted.")
    for zone in arrays(engine, actor.entity_id):
        unstable = record(zone).get("unstable")
        if not unstable:
            continue
        # "At the start of its creator's next turn, the creator must succeed on a Formation Check against your Formation Save DC or the array collapses."
        save_zone(engine, zone, "formation:disrupt_node", {**record(zone), "unstable": None})
        if not formation_check(engine, actor, record(zone).get("numbers") or {}, int(unstable.get("dc") or 10), "formation:disrupt_node", "hold the unstable array", hazards=('maintain:formation',)):
            collapse(engine, zone, "UNSTABLE", "formation:disrupt_node")
    sweep(engine)


# ------------------------------------------------------------------------------------------------ Eyes and Nodes as targets
def weapon_attack(action: Any) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """(typed, attack effect) for an ordinary weapon Attack action, the kind that may strike an object (the same rows combat/ext/
    docket_walls.py picks for a wall section)."""
    typed = (action.parameters or {}).get("typed") or {}
    economy = getattr(action.economy, "value", action.economy)
    attack = next((row for row in typed.get("effects") or [] if isinstance(row, dict) and row.get("type") == "attack"), None)
    if (economy == "ACTION" and action.target_kind == "HOSTILE_ENTITY" and typed.get("weapon") and attack is not None
            and not typed.get("variant_of") and not str(typed.get("source") or "").startswith("improvised") and "#" not in action.source_definition_id):
        return typed, attack
    return None


@hook("object_targets")
def object_targets(engine: Any, actor: Any, action: Any) -> list[str] | None:
    if weapon_attack(action) is None:
        return None
    out = []
    for zone in arrays(engine):
        owner = engine.state.actors.get(zone.owner_id)
        if owner is None or owner.team_id == actor.team_id:
            continue
        out.extend(obj.object_id for obj in objects_of(engine, zone) if not obj.destroyed and obj.ac is not None)
    return out or None


@hook("object_action")
def object_action(engine: Any, actor: Any, action: Any, obj: Any, candidate: Any, intent: Any) -> bool | None:
    if not (obj.component or {}).get(KEY):
        return None
    found = weapon_attack(action)
    if found is None:
        return None
    typed, attack = found
    for index in range(int(attack.get("count") or 1)):
        current = engine.state.objects.get(obj.object_id)
        if current is None or current.destroyed:
            break
        strike(engine, actor, action, current, typed, index)
    sweep(engine, action.source_definition_id)
    return True


def strike(engine: Any, actor: Any, action: Any, obj: Any, typed: dict[str, Any], index: int) -> bool:
    """One weapon attack against a formation object: the attack roll against its AC, weapon damage, its immunities."""
    from ..gate2_runtime_models import DiceSpec

    weapon = typed.get("weapon") or {}
    roll = engine.roller.d20(
        modifier=int((typed.get('numbers') or {}).get('attack_bonus') or 0),
        actor_id=actor.entity_id,
        reason=f'ATTACK:{action.source_definition_id}:{obj.object_id}:{index + 1}',
        mode=engine.direct_attack_mode(actor),
    )
    engine._record_roll(roll)
    natural = int(roll.natural_result or 0)
    hit = natural != 1 and (natural == 20 or roll.total >= int(obj.ac or 0))
    label = part_name(engine, obj)
    engine._append_event("CHECK_ROLLED", action.source_definition_id, actor_id=actor.entity_id, target_ids=(obj.object_id,),
                         payload={"actor": roll.model_dump(mode="json"), "dc": obj.ac, "success": hit, "check": f"Attack on {label}"})
    if not hit:
        return False
    dice = DiceSpec(**weapon["damage"]) if weapon.get("damage") else DiceSpec(count=1, sides=4, modifier=0)
    damage = engine.roller.roll(dice, actor_id=actor.entity_id, reason=f"DAMAGE:{action.source_definition_id}:{obj.object_id}:{index + 1}",
                                critical=natural == 20, fixed_damage=weapon.get("fixed_damage"))
    engine._record_roll(damage)
    kind = str(weapon.get("damage_type") or "UNTYPED").upper()
    hurt_object(engine, obj, int(damage.total), kind, action.source_definition_id, actor.entity_id)
    return True


def part_name(engine: Any, obj: Any) -> str:
    zone = engine.state.zones.get((obj.component or {}).get(KEY) or "")
    role = (obj.component or {}).get("role") or "part"
    return f"the {zone.trigger_profile.get('name') if zone is not None else 'formation'} {str(role).title()}"


# The symbols an array leaves on the table (owner: "formation arrays are placeable symbols on the map that can be removed"): each Eye,
# Node and Anchor is drawn where it stands and goes when the array collapses or the part is destroyed (combat/tabletop_service.py).
SYMBOLS = {"eye": ("◉", "#e0b84c"), "node": ("◆", "#6cc6d9"), "anchor": ("⚓", "#b98be0")}


def table_items(engine: Any) -> list[dict[str, Any]]:
    items = []
    for obj in engine.state.objects.values():
        component = obj.component or {}
        if not component.get(KEY) or obj.destroyed or component.get(KEY) not in engine.state.zones:
            continue
        role = str(component.get("role") or "node")
        label, color = SYMBOLS.get(role, SYMBOLS["node"])
        owner = engine.state.actors.get(obj.owner_id or "")
        hp = f"{obj.current_hp}/{obj.maximum_hp} HP, AC {obj.ac}" if obj.maximum_hp is not None else ""
        items.append({"id": f"formation:{obj.object_id}", "x": obj.position.x, "y": obj.position.y, "label": label, "color": color,
                      "name": f"{part_name(engine, obj).removeprefix('the ')}{f' ({owner.display_name})' if owner else ''}" +
                              (f" -- {hp}" if hp else ""), "owner_id": obj.owner_id, "formation": True})
    return items


def hurt_object(engine: Any, obj: Any, amount: int, kind: str, source: str, actor_id: str | None) -> int:
    """Damage to an Eye or Node; immune types do nothing.  Returns the HP it lost."""
    label = part_name(engine, obj)
    if kind.upper() in (obj.damage_immunities or ()):
        say(engine, source, actor_id, f"{label} is immune to {kind.lower()} damage.")
        return 0
    lost = min(int(obj.current_hp or 0), max(0, amount))
    left = int(obj.current_hp or 0) - lost
    if left <= 0 and last_stand(engine, obj, source):
        lost, left = int(obj.current_hp or 0) - 1, 1
    engine._update_object(obj.model_copy(update={"current_hp": left, **({"destroyed": True} if left <= 0 else {})}), source, actor_id)
    say(engine, source, actor_id, f"{label} takes {amount} {kind.lower()} damage: {left} of {obj.maximum_hp} HP left" + (" -- destroyed." if left <= 0 else "."))
    return lost


def last_stand(engine: Any, obj: Any, source: str) -> bool:
    """Reinforced Nodes: "When a Node or Eye you control within 120 feet would be destroyed, you may use your Reaction and spend 1 CP
    to leave it at 1 Hit Point instead" (taken whenever the owner can: it costs a Reaction and 1 CP, and the part is the array)."""
    zone = engine.state.zones.get((obj.component or {}).get(KEY) or "")
    if zone is None:
        return False
    owner = engine.state.actors.get(zone.owner_id)
    numbers = record(zone).get("numbers") or {}
    pool = str(numbers.get("formation_pool") or "resource:core.qi")
    if owner is None or "reinforced_nodes" not in talents_of(numbers) or not owner.active or not owner.reaction_available \
            or owner.resources.get(pool, 0) < 1 or has_condition(owner, "formation_cp_locked") is not None \
            or engine._distance_actor_to_cell(owner, obj.position) > PULSE_RANGE_FT:
        return False
    from ..typed_executor import condition_rules

    if any(row.get("no_reactions") for row in condition_rules(owner)):
        return False
    with activation(engine, owner, "formation:reinforced_nodes"):
        owner.reaction_available = False
        engine._spend_resource(owner, pool, 1, "formation:reinforced_nodes")
        say(engine, "formation:reinforced_nodes", owner.entity_id, f"Reinforced Nodes: {owner.display_name} spends a Reaction and 1 CP; {part_name(engine, obj)} stays at 1 HP.")
        return True

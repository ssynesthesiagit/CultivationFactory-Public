"""A damage row whose printed text names a damage type commits that type (hunt 84 finding 1, MMX70).

"Unmake the Answer" and "Last Inch Control" took *Ruin self-damage* and the table committed it as UNTYPED:
``typed_executor._damage_roll`` reads an empty ``damage_types`` as "no type", so the committed packet had no type
for resistances, immunities or type-triggered riders to see. The same rows in "Ruin Wave" and "Severing Wave" left
*target* damage UNTYPED even though the Unmaking sphere's own rule is that Ruin damage lands as Force.

The rows are read from the generated authority the table actually ships (built from
``authority/typed_mechanics/reviewed_final.d``), and are run through the real engine's typed executor and damage
commit, so these tests fail on the base commit and pass with the reviewed rows that carry their type.
"""

import copy
import json
import re
from pathlib import Path

import pytest

from combat import typed_executor
from combat.gate2_runtime_models import ActionDefinition, EconomyKind
from combat.gate4_engine import Gate4ControllerEngine
from tests.test_carry import KIT
from tests.test_zones import SHEET

ROOT = Path(__file__).resolve().parents[1]
AUTHORITY = ROOT / "authority/Tianxia_Typed_Mechanics_Authority_R1.json"
ME = "actor:factory.ruin"
OPP = "actor:factory.70000002"

# The printed damage types a row may name. A row whose printed text names one of these but carries no type commits
# UNTYPED, which no resistance, immunity or type-triggered rider can see.
PRINTED_TYPES = ("Acid", "Blight", "Bludgeoning", "Cold", "Fire", "Force", "Ice", "Lightning", "Necrotic",
                 "Piercing", "Poison", "Psychic", "Radiant", "Ruin", "Slashing", "Thunder", "Void")

# Rows that name a type but still carry none, as the exact ``ability_id`` + row path the walker below builds.
# Each is a defect of its own class, tracked rather than silently accepted: the first is not damage of its own
# (it adds a bonus to another roll, which keeps that roll's type), and the rest lost a *choice* between several
# printed types rather than a single one. Fixing those is separate work.
#
# The guard matches these by equality, never by prefix, so exempting one recorded row cannot quietly exempt a
# row added beside it later (MMX70r review, finding 1: the old prefix match skipped whole abilities, and its
# "/options/0" keys never matched the walker's "/options[0]" at all).
OPEN_ROWS = {
    # A modifier that adds the Proficiency Bonus to a qualifying technique's own hit: the hit keeps its own type.
    # Its printed text spells the types in lower case, so the case-sensitive matcher does not reach it today; the
    # key is still recorded so widening the matcher cannot turn a known-good row into a surprise failure.
    "foundation.taiyin_lunar_body_v0_2B.perfected_true_moon_yin_palace/modifier/effects[0]":
        "adds a bonus to another roll",
    "tianxia.subpath.qi.sigil_scribe.feature.sigil_array/effects[0]/on_fail[0]":
        "lost a choice of six printed types",
    "tianxia.subpath.qi.void_touched_cultivator.feature.erase/options[0]/effects[0]":
        "lost Void's choice of Force, Necrotic or Psychic",
    "tianxia.subpath.qi.void_touched_cultivator.feature.erase/options[1]/effects[0]/on_fail[0]":
        "lost Void's choice of Force, Necrotic or Psychic",
    "tianxia.subpath.qi.void_touched_cultivator.feature.law_of_nonexistence/effects[0]/on_success[0]":
        "lost Void's choice of Force, Necrotic or Psychic",
}

# The Unmaking rows this finding is about: self-damage is the sphere's own "RUIN" type, and Ruin damage dealt to
# another creature lands as Force (combat/unmaking.py: "Ruin damage is Force here ... Self-damage from Unmaking is
# its own type (\"RUIN\"), which nothing resists").
SELF_DAMAGE_ROWS = ("TAL_UNMAKING_UNMAKE_THE_ANSWER", "TAL_UNMAKING_LAST_INCH_CONTROL")
FORCE_ROWS = ("TAL_UNMAKING_RUIN_WAVE", "TAL_UNMAKING_THIRD_RUIN_FORM_SEVERING_WAVE")


def _mechanics():
    return json.loads(AUTHORITY.read_text(encoding="utf-8"))["mechanics"]


def _damage_rows(node, path=""):
    """Every damage row under a mechanic, as (path, row) pairs."""
    if isinstance(node, dict):
        if node.get("type") == "damage":
            yield path, node
        for key, value in node.items():
            yield from _damage_rows(value, f"{path}/{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _damage_rows(value, f"{path}[{index}]")


def _names_a_type(row) -> bool:
    evidence = str(row.get("evidence") or "")
    if re.search(r"\buntyped\b", evidence, re.I):
        return False  # the row says so itself
    return any(re.search(rf"\b{word}\b", evidence) for word in PRINTED_TYPES)


def _offender_key(ability_id, path):
    """The one string a row is known by, built the same way every time."""
    return ability_id + (path if path else "/effects")


def _untyped_damage_offenders(mechanics):
    """Every damage row whose printed text names a type but which carries none, as sorted report lines.

    ``OPEN_ROWS`` is consulted with ``in`` (equality), never ``startswith``, so an exemption covers exactly the
    recorded row and nothing else.
    """
    offenders = []
    for ability_id, mechanic in mechanics.items():
        for path, row in _damage_rows(mechanic):
            if row.get("damage_types") or not _names_a_type(row):
                continue
            if _offender_key(ability_id, path) in OPEN_ROWS:
                continue
            offenders.append(f"{_offender_key(ability_id, path)}: {row.get('evidence')!r}")
    return sorted(offenders)


def test_a_damage_row_naming_a_type_carries_it_to_the_committed_damage():
    """The general guard: no row's printed type is dropped, so nothing commits UNTYPED behind a resistance's back."""
    offenders = _untyped_damage_offenders(_mechanics())
    assert not offenders, "printed damage type not carried to the committed damage:\n" + "\n".join(offenders)


def test_every_open_row_is_a_row_that_still_exists():
    """An exemption must name a row that is really there, so a stale or misspelt key cannot become dead weight."""
    untyped = {_offender_key(ability_id, path)
               for ability_id, mechanic in _mechanics().items()
               for path, row in _damage_rows(mechanic)
               if not row.get("damage_types")}
    assert set(OPEN_ROWS) <= untyped, "open rows naming no untyped damage row: " + repr(
        sorted(set(OPEN_ROWS) - untyped))


@pytest.mark.parametrize("ability_id,sibling,why", [
    ("tianxia.subpath.qi.sigil_scribe.feature.sigil_array",
     lambda mechanic: mechanic["effects"].append(_new_damage("4 Fire damage")),
     "a new row beside an open row in the same ability"),
    ("tianxia.subpath.qi.void_touched_cultivator.feature.erase",
     lambda mechanic: mechanic["options"].append({"effects": [_new_damage("4 Void damage")]}),
     "a new option beside an open option in the same ability"),
])
def test_the_guard_exempts_only_the_exact_recorded_rows(ability_id, sibling, why):
    """A new untyped row added next to an exempt one is still caught -- the exemption is per row, not per ability."""
    mechanics = _mechanics()
    mechanic = copy.deepcopy(mechanics[ability_id])
    sibling(mechanic)
    # the open row itself stays exempt, the new sibling does not
    assert _untyped_damage_offenders({ability_id: mechanic}), f"guard ignored {why}"
    assert _untyped_damage_offenders(_mechanics()) == [], "the recorded open rows stopped being exempt"


def _new_damage(evidence):
    """A damage row in the shape the parser leaves behind when it drops the type: no ``damage_types``."""
    return {"type": "damage", "evidence": evidence, "damage_types": []}


@pytest.mark.parametrize("ability_id", SELF_DAMAGE_ROWS)
def test_unmaking_self_damage_commits_as_ruin(ability_id):
    """The reported bug: "you take Ruin self-damage" committed UNTYPED, so nothing could see its type."""
    engine, actor, action = _engine_with(ability_id)
    typed = _typed(ability_id)
    # "Last Inch Control" is a save the caster makes about itself, so the caster is the save's subject.
    typed_executor.run_effects(typed_executor.Context(engine, actor, action, None, typed, [actor], actor),
                               typed["effects"])
    committed = [e for e in engine.events if e.event_type == "DAMAGE_COMMITTED" and actor.entity_id in (e.target_ids or ())]
    assert committed, f"{ability_id} committed no self-damage"
    assert [str(e.payload.get("damage_type")) for e in committed] == ["RUIN"] * len(committed)
    assert all(int(e.payload.get("hp_damage") or 0) > 0 for e in committed)


@pytest.mark.parametrize("ability_id", FORCE_ROWS)
def test_ruin_wave_damage_lands_as_force_and_force_resistance_halves_it(ability_id):
    """A target's Ruin damage lands as Force, so a creature resistant to Force is actually protected by it."""
    plain = _run_wave(ability_id, resistant=False)
    assert plain, f"{ability_id} committed no damage to the target"
    assert {str(e.payload.get("damage_type")) for e in plain} == {"FORCE"}

    guarded = _run_wave(ability_id, resistant=True)
    assert {str(e.payload.get("damage_type")) for e in guarded} == {"FORCE"}
    # ``typed_reactions.defend`` halves with ``amount //= 2``, so the halved total is the plain total floored,
    # not merely something smaller.
    assert _hp_damage(guarded) == _hp_damage(plain) // 2, (
        f"Force resistance did not halve Ruin damage: {_hp_damage(plain)} became {_hp_damage(guarded)}")


def _hp_damage(events):
    return sum(int(event.payload.get("hp_damage") or 0) for event in events)


def test_ruin_damage_type_survives_a_table_commit_and_reload(tmp_path):
    """The real printed ability, played at the real table: the committed packet keeps the type the rules gave it."""
    from combat.factory_compiler import compile_character
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService

    ability_id = "TAL_UNMAKING_RUIN_WAVE"
    bundles = []
    for actor_id in (ME, OPP):
        sheet = {**SHEET, "equipment": [{"starting_kit": KIT}],
                 "identity": {**SHEET.get("identity", {}), "display_name": f"Fighter {actor_id[-2:]}"},
                 "spheres_and_talents": {"sphere_record_ids": ["tianxia.sphere.unmaking"],
                                         "learned_talent_record_ids": [ability_id]}}
        bundles.append(compile_character(sheet, actor_id=actor_id))

    combat = CombatService(ROOT, tmp_path)
    match_id = combat._finish_factory_match(bundles, [ME, OPP], {ME: "team:factory", OPP: "team:opponents"},
                                            {ME: {"x": 3, "y": 6}, OPP: {"x": 4, "y": 6}},
                                            combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"],
                                            [ME], [OPP], control_modes={ME: "MANUAL", OPP: "LOCAL_AUTO"},
                                            match_seed="MMX70", display_name="MMX70 Ruin damage type",
                                            maximum_rounds=3)["match_id"]
    table = TabletopService(combat, tmp_path)
    state = table.state(match_id)
    assert state["menu"]["actor_id"] == ME
    # Ruin Wave is a 30-foot line: aim it along the opponent's square, which the printed rules put in the wave.
    # Table menus defer a CELL aim since lazy placement (combat/placement_menu.py): the group carries one
    # "choose a square" option and the aim is the saved square choice the player (or phone map-pick) answers.
    group = next(g for g in state["menu"]["actions"] if ability_id in str(g.get("source_definition_id", "")))
    option = next(o for o in group["options"] if "choose a square" in str(o.get("label", "")).lower())
    menu = state["menu"]
    answers: list[dict] = []
    result = table.act(match_id, option["candidate_id"], menu["decision_id"], menu["state_version"],
                       state["last_sequence"], answers)
    assert result["status"] == "REACTION_REQUIRED", result["status"]
    placement = result["reaction"]
    assert placement["context"]["reaction_source_id"] == "choice:placement_menu.square"
    aimed = next(o for o in placement["choice"]["options"] if o.get("cell") == {"x": 4, "y": 6, "z": 0})
    assert aimed["label"].startswith("Square 4, 6")
    answers.append({**placement["context"], "selection": "USE", "option_ids": [aimed["id"]]})
    result = table.act(match_id, option["candidate_id"], menu["decision_id"], menu["state_version"],
                       state["last_sequence"], answers)
    for _ in range(10):  # the printed "choose the price you pay" question
        if result["status"] != "REACTION_REQUIRED":
            break
        prompt = result["reaction"]
        answers.append({**prompt["context"], "selection": "USE", "option_ids": ["1:self"]})
        result = table.act(match_id, option["candidate_id"], menu["decision_id"], menu["state_version"],
                           state["last_sequence"], answers)
    assert result["status"] == "COMMITTED", result["status"]

    committed = [e for e in table.events(match_id, 0)["events"]
                 if e["event_type"] == "DAMAGE_COMMITTED" and OPP in (e.get("target_ids") or ())]
    assert committed, "Ruin Wave committed no damage through the table"
    assert {str(_payload(e).get("damage_type")) for e in committed} == {"FORCE"}
    assert _table_damage(committed) > 0
    # the line the player reads says the type in words
    assert all("force" in str(e.get("summary", "")).lower() for e in committed)

    # A fresh service over the same saved fight reads the same state, and the type is still there.
    reloaded = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
    assert reloaded.state(match_id)["last_sequence"] >= state["last_sequence"]
    again = [e for e in reloaded.events(match_id, 0)["events"]
             if e["event_type"] == "DAMAGE_COMMITTED" and OPP in (e.get("target_ids") or ())]
    assert {str(_payload(e).get("damage_type")) for e in again} == {"FORCE"}


def _table_damage(events):
    return sum(int(_payload(event).get("hp_damage") or 0) for event in events)


def _payload(event):
    """The event's own payload as the table journal stores it (the feed also adds presentation around it)."""
    return (event.get("raw") or {}).get("payload") or {}


def _typed(ability_id) -> dict:
    mechanic = _mechanics()[ability_id]
    return {
        "effects": mechanic["effects"],
        "riders": mechanic.get("riders") or [],
        "numbers": {"cl": 15, "pb": 4, "save_dc": 99, "attack_bonus": 9, "key_mod": 4},  # 99: the target fails its save
        "duration": mechanic.get("duration") or {"kind": "instant"},
        "source": ability_id,
    }


def _engine_with(ability_id):
    """A real engine with a real caster and a real opponent, carrying the shipped typed row for ``ability_id``."""
    from combat.gate2_runtime_content import AN

    sheet = {**SHEET, "equipment": [{"starting_kit": KIT}],
             "spheres_and_talents": {"sphere_record_ids": ["tianxia.sphere.unmaking"],
                                     "learned_talent_record_ids": [ability_id]}}
    from combat.factory_compiler import compile_character

    bundle = compile_character(sheet, actor_id=ME)
    engine = Gate4ControllerEngine(ROOT, match_seed="RUIN", typed_bundles=(bundle,),
                                   roster_setup={"primary_actor_ids": [ME, AN],
                                                 "team_by_actor": {ME: "team:a", AN: "team:b"},
                                                 "starting_positions": {ME: {"x": 3, "y": 6},
                                                                        AN: {"x": 4, "y": 6}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    actor = engine.state.actors[ME]
    action = ActionDefinition(source_definition_id=f"action:typed.test.{ability_id}",
                              display_name=ability_id, owner_id=actor.entity_id, economy=EconomyKind.ACTION,
                              resolution_kind="TYPED", target_kind="HOSTILE_ENTITY", range_ft=60,
                              parameters={"typed": _typed(ability_id)})
    engine.action_catalog[action.source_definition_id] = action
    return engine, actor, action


def _run_wave(ability_id, *, resistant):
    engine, actor, action = _engine_with(ability_id)
    target = next(a for a in engine.state.actors.values() if a.entity_id != actor.entity_id)
    if resistant:
        engine._add_modifier(target, "fixture:force_resistance", "damage_resistance", "set", "FORCE",
                             "damage_types", expires_on="UNTIL_REMOVED")
    typed = _typed(ability_id)
    typed_executor.run_effects(
        typed_executor.Context(engine, actor, action, None, typed, [target], target), typed["effects"])
    return [e for e in engine.events
            if e.event_type == "DAMAGE_COMMITTED" and target.entity_id in (e.target_ids or ())]

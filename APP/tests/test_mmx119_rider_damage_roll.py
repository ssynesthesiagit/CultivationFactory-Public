"""MMX119: a printed "add Proficiency Bonus to the damage (roll)" raises the printed roll.

Demon Mark reads "While marked: once per turn when you damage it, add Proficiency Bonus to
the damage" and Daemonic Augment's Bonus Damage option reads "add Proficiency Bonus to one
damage roll".  Both were committed by ``block_damage`` as their OWN damage packet -- its own
roll, its own reaction window, and (with no damage_types) an "untyped" log line -- so the
bonus never reached the roll it was printed to modify, and the named bonus was invisible.

``combat/ext/roll_modifiers.py`` folds such a dice-free "add ... to ... damage" row into the
printed damage roll of the activation that damages its target, sharing the executor's
per-turn gate so it is not also fired as a packet afterwards.

Table level: two real fighters, manual control, pinned rolls, a real commit and a reload.
The marked creature's saves fail (so the mark lands) and the striker's attack rolls hit
without critting, so the totals below are exact.
"""
import json
import sys
import zipfile
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from combat import ext
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.tabletop_service import TabletopService
from combat.typed_executor import bears_mark

ROOT = APP
MAP_NAME = "MMX119 close quarters"
ARENA = f"battlefield:map.{MAP_NAME.lower().replace(' ', '-')}"
MINE = FACTORY_ACTOR_PREFIX + "left"
FOE = FACTORY_ACTOR_PREFIX + "right"
PB = 4
BASE = 3  # Unarmed Strike on a character with +2 Strength: 1 + 2


def owner_sheet():
    return {
        "identity": {"proficiency_bonus": PB, "cultivation_level": 10, "path": "Qi Cultivation"},
        "ability_scores_and_statistics": {
            "abilities": [{"ability": a, "score": 14, "modifier": 2} for a in ("STR", "DEX", "CON", "INT", "WIS", "CHA")],
            "primary_resource": {"name": "Qi", "maximum": 20}, "armor_class": {"base_value": 14},
            "hit_points": {"maximum": 60}, "speed": {"walking_ft": 30},
            "technique_save_dc": 15, "technique_attack_bonus": 7},
        "spheres_and_talents": {"learned_talent_record_ids": ["TAL_DAEMONIC_CULTIVATION_DEMON_MARK"]}}


def table_fight(tmp_path, monkeypatch):
    def rolls(engine, roll, intent):
        why = str(roll.reason).upper()
        if roll.actor_id == FOE and "SAVE" in why:
            return {"source_id": "test:mmx119.failed_save", "operation": "replace", "natural_result": 1}
        if roll.actor_id == MINE and "ATTACK" in why:
            return {"source_id": "test:mmx119.hit", "operation": "replace", "natural_result": 15}
        return None

    ext.effects()
    monkeypatch.setitem(ext._HOOKS, "d20_result", [rolls])
    for side in ("left", "right"):
        folder = tmp_path / "portable_characters" / side
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(owner_sheet()))
    combat = CombatService(ROOT, tmp_path)
    combat.tabletop_maps.save({"display_name": MAP_NAME, "width_squares": 12, "height_squares": 8,
        "walls": [], "starts": {"team1": [[3, 4]], "team2": [[4, 4]]}})
    modes = {MINE: "MANUAL", FOE: "MANUAL"}
    mid = combat.create_factory_match(project_ids=["left"], opponent_actor_ids=[FOE],
        control_modes=modes, arena_id=ARENA, match_seed="MMX119-TABLE")["match_id"]
    return combat, TabletopService(combat, tmp_path), mid


def group_for(menu, needle):
    # Parent attacks now also have free setting buttons whose IDs extend the
    # parent's ID. An exact source must select the attack, not its first setting.
    return next((g for g in menu["actions"] if needle == g["source_definition_id"]), None) or next(
        (g for g in menu["actions"] if needle in str(g["source_definition_id"])), None)


def use_button(table, mid, actor, needle, answer_reaction=True):
    for _ in range(160):
        state = table.state(mid)
        menu = state["menu"]
        if not menu or not menu.get("actions"):
            return None
        if menu["actor_id"] != actor:
            if table.act(mid, menu["end_turn"], menu["decision_id"], menu["state_version"],
                         state["last_sequence"])["status"] != "COMMITTED":
                return None
            continue
        group = group_for(menu, needle)
        if group is None:
            return None
        option = next((o for o in group["options"] if FOE in (o.get("target_ids") or [])), group["options"][0])
        answers = []
        if answer_reaction:
            context = (group.get("metadata") or {}).get("reaction_context") or {}
            if context:
                answers = [{**context, "selection": "USE"}]
        result = table.act(mid, option["candidate_id"], menu["decision_id"], menu["state_version"],
                           state["last_sequence"], answers)
        if result["status"] == "REACTION_REQUIRED" and answer_reaction:
            state = result.get("state") or {}
            menu = state.get("menu") or table.state(mid)["menu"]
            group = group_for(menu, needle) or group_for(menu, "OPPORTUNITY") or group_for(menu, "opportunity")
            if group is None:
                return result
            option = group["options"][0]
            context = (result.get("reaction") or {}).get("context") or {}
            result = table.act(mid, option["candidate_id"], menu["decision_id"], menu["state_version"],
                               state.get("last_sequence", state.get("last_sequence")),
                               [{**context, "selection": "USE"}] if context else [])
        return result
    return None


def damage_packets(combat, mid, start_seq, actor=MINE, target=FOE):
    engine = combat._load_session(mid).engine
    return [e for e in engine.events if e.sequence > start_seq and e.event_type == "DAMAGE_COMMITTED"
            and e.actor_id == actor and target in (e.target_ids or ())]


def test_mark_rider_raises_the_printed_roll_in_one_packet(tmp_path, monkeypatch):
    """A "when you damage it, add PB to the damage" rider joins the hit, as one typed packet."""
    combat, table, mid = table_fight(tmp_path, monkeypatch)
    assert use_button(table, mid, MINE, "DEMON_MARK")["status"] == "COMMITTED", "Demon Mark is a printed bonus action"
    engine = combat._load_session(mid).engine
    assert bears_mark(engine.state.actors[FOE], MINE, "Demon Mark"), "the mark must land"
    seq = engine.state.event_sequence
    result = use_button(table, mid, MINE, "unarmed_strike")
    assert result and result["status"] == "COMMITTED", result

    packets = damage_packets(combat, mid, seq)
    dealt = [int(p.payload.get("hp_damage") or 0) + int(p.payload.get("temporary_hp_absorbed") or 0)
             for p in packets]
    types = [p.payload.get("damage_type") for p in packets]
    assert len(packets) == 1 and dealt == [BASE + PB] and types == ["BLUDGEONING"], {
        "why": "Demon Mark says add PB to THE damage, so the hit is one bludgeoning packet of "
               "1+2+4=7, not a 3-point hit followed by a separate bonus packet",
        "packets": [(p.payload.get("damage_type"), dealt[i]) for i, p in enumerate(packets)],
    }
    reloaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert reloaded.mechanical.replay()["status"] == "PASS"


def test_the_rider_is_available_again_on_a_later_turn():
    """Once per turn, not once per fight: the bonus returns on the next turn's roll."""
    from combat import typed_executor as ex
    from combat.factory_compiler import compile_character
    from combat.gate2_engine import Gate2Engine
    from combat.gate2_runtime_content import AN, LEE
    from combat.gate2_runtime_models import ActionDefinition, EconomyKind

    actor_id = "actor:factory.mmx119x"
    sheet = owner_sheet()
    bundle = compile_character(sheet, actor_id=actor_id)
    foes = (AN, LEE)
    engine = Gate2Engine(APP, match_seed="MMX119X", typed_bundles=(bundle,),
                         roster_setup={"primary_actor_ids": [actor_id, *foes],
                                       "team_by_actor": {actor_id: "team:a", **{f: "team:b" for f in foes}}})
    for foe in foes:
        engine.typed_actor_ids.add(foe)
        engine.typed_reaction_rows[foe] = []
    actor = engine.state.actors[actor_id]

    # Apply the printed failed-save payload: the mark and its deferred once-per-turn rider.
    mark = next(a for a in engine.action_catalog.values() if a.owner_id == actor_id and a.display_name == "Demon Mark")
    foe = engine.state.actors[AN]
    ex.run_effects(ex.Context(engine, actor, mark, None, mark.parameters["typed"], [foe], foe),
                   mark.parameters["typed"]["effects"][0]["on_fail"])
    assert bears_mark(foe, actor_id, "Demon Mark")

    action = ActionDefinition(source_definition_id="action:mmx119x.damage", display_name="Roll damage",
                              owner_id=actor_id, economy=EconomyKind.ACTION, resolution_kind="TYPED",
                              target_kind="HOSTILE_ENTITY",
                              parameters={"typed": {"numbers": {"pb": PB}, "effects": []}})

    def hit(target):
        start = len(engine.events)
        ex.run_effects(ex.Context(engine, actor, action, None, action.parameters["typed"], [target], target),
                       [{"type": "damage", "dice": {"count": 2, "sides": 6}, "damage_types": ["force"]}])
        rolled = next((e for e in engine.events[start:] if e.event_type == "DAMAGE_ROLLED"
                       and target.entity_id in (e.target_ids or ())), None)
        committed = [e for e in engine.events[start:] if e.event_type == "DAMAGE_COMMITTED"
                     and target.entity_id in (e.target_ids or ())]
        return rolled, committed

    # A typed damage effect's own roll: the rider folds in, committed, on the same turn.
    rolled, committed = hit(foe)
    assert len(committed) == 1 and int(committed[0].payload.get("hp_damage") or 0) == int(rolled.payload.get("total") or 0), {
        "why": "one packet whose damage is exactly the printed roll, with the rider folded into that "
               "roll (its modifier carries the Proficiency Bonus) rather than a second bonus packet",
        "rolled": rolled.payload, "packets": [p.payload for p in committed],
    }
    assert int(rolled.payload.get("modifier") or 0) == PB, "the Proficiency Bonus is a modifier on the printed roll"
    assert committed[0].payload.get("damage_type") == "FORCE", "the bonus shares the roll's type"

    # A new turn for the creature whose turn the rider is counted against.
    engine.state.round_number += 1
    engine.state.actors[engine.state.current_actor_id].turns_started += 1
    rolled, committed = hit(foe)
    assert len(committed) == 1 and int(rolled.payload.get("modifier") or 0) == PB, {
        "why": "on the next turn the rider is available again: the bonus is once per turn, not once per fight",
        "rolled": rolled.payload, "packets": [p.payload for p in committed],
    }


def test_a_chosen_add_to_the_damage_roll_option_folds_into_that_roll():
    """A sibling "add PB to one damage roll" option raises the printed roll, not a 2nd packet.

    Daemonic Augment's Bonus Damage option ("add Proficiency Bonus to one damage roll") is a
    sibling of the effect it modifies, so it is added to that effect's printed roll and then
    suppressed as its own packet. This is the sibling half of the same general mechanism.
    """
    from combat import typed_executor as ex
    from combat.gate2_runtime_models import ActionDefinition, EconomyKind
    from combat.ext.roll_modifiers import is_roll_modifier

    actor_id = "actor:factory.mmx119y"
    sheet = owner_sheet()
    from combat.factory_compiler import compile_character
    from combat.gate2_engine import Gate2Engine
    from combat.gate2_runtime_content import AN
    bundle = compile_character(sheet, actor_id=actor_id)
    engine = Gate2Engine(APP, match_seed="MMX119Y", typed_bundles=(bundle,),
                         roster_setup={"primary_actor_ids": [actor_id, AN],
                                       "team_by_actor": {actor_id: "team:a", AN: "team:b"}})
    engine.typed_actor_ids.add(AN)
    engine.typed_reaction_rows[AN] = []
    actor, foe = engine.state.actors[actor_id], engine.state.actors[AN]

    action = ActionDefinition(source_definition_id="action:mmx119y.a", display_name="Struck",
                              owner_id=actor_id, economy=EconomyKind.ACTION, resolution_kind="TYPED",
                              target_kind="HOSTILE_ENTITY",
                              parameters={"typed": {"numbers": {"pb": PB}, "effects": [
                                  {"type": "damage", "dice": {"count": 2, "sides": 6}, "damage_types": ["force"]},
                                  {"type": "extra_damage", "formula": "pb", "damage_types": [],
                                   "damage_label": "Bonus Damage",
                                   "evidence": "add Proficiency Bonus to one damage roll"}]}})
    row = action.parameters["typed"]["effects"][1]
    assert is_roll_modifier(row), "the option row is a printed roll modifier"
    start = len(engine.events)
    ex.run_effects(ex.Context(engine, actor, action, None, action.parameters["typed"], [foe], foe),
                   action.parameters["typed"]["effects"])
    rolled = next(e for e in engine.events[start:] if e.event_type == "DAMAGE_ROLLED")
    committed = [e for e in engine.events[start:] if e.event_type == "DAMAGE_COMMITTED"]
    assert len(committed) == 1, {
        "why": "the option is folded into the printed roll, so the activation commits one packet",
        "packets": [p.payload for p in committed],
    }
    assert int(rolled.payload.get("modifier") or 0) == PB, "the option's Proficiency Bonus is a modifier on the roll"
    assert int(committed[0].payload.get("hp_damage") or 0) == int(rolled.payload.get("total") or 0)

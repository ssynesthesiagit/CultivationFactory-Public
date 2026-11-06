"""Damage-triggered riders require actual damage, including across a cold table load."""
import json
import zipfile
from pathlib import Path

import pytest

from combat import ext
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.typed_executor import bears_mark
from tests.hunt28_support import act, options
from tests.test_mmx97f1_relocation import _owner_turn, OWNER, FOE
from tests.test_riders_c7 import sheet

ROOT = Path(__file__).resolve().parents[1]
MARK = "Demon Mark + Daemonic Augment: Bonus Damage"
DOSE = "Deliver the Dose + Corrosive Dose"
FOCUS = "Concentrate with temporary Hit Points"
PB = 4


def _table(tmp_path, monkeypatch):
    pinned = {"attack": 2}

    def rolls(engine, roll, intent):
        why = str(roll.reason).upper()
        natural = pinned["attack"] if "ATTACK" in why else 1 if "SAVE" in why and "CONCENTRATION" not in why else 20
        return {"source_id": "test:missrider1014", "operation": "replace", "natural_result": natural}

    ext.effects()
    monkeypatch.setitem(ext._HOOKS, "d20_result", [rolls])
    spheres = {"sphere_record_ids": ["tianxia.sphere.poison", "tianxia.sphere.daemonic_cultivation"],
               "learned_talent_record_ids": ["POISON_BASE_DELIVER_THE_DOSE",
                   "tianxia.talent.poison.corrosive_dose", "TAL_DAEMONIC_CULTIVATION_DEMON_MARK",
                   "TAL_DAEMONIC_CULTIVATION_DAEMONIC_AUGMENT"]}
    bundles = []
    for actor in (OWNER, FOE):
        doc = sheet([], cl=10, dc=30, spheres=spheres if actor == OWNER else {})
        if actor == FOE:
            doc["ability_scores_and_statistics"]["armor_class"]["base_value"] = 19
        folder = tmp_path / "portable_characters" / actor.removeprefix("actor:factory.")
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(doc))
        bundle = compile_character(doc, actor_id=actor)
        if actor == FOE:
            aid = "action:test.missrider1014.focus"
            bundle["actor_template"]["action_ids"].append(aid)
            bundle["action_catalog"].append({"source_definition_id": aid, "display_name": FOCUS,
                "owner_id": actor, "economy": "ACTION", "resolution_kind": "TYPED", "target_kind": "SELF",
                "parameters": {"typed": {"effects": [{"type": "temp_hp", "applies_to": "self",
                    "flat": 100, "formula": "none"}], "numbers": {},
                    "duration": {"kind": "minutes", "amount": 1, "concentration": True}}}})
        bundles.append(bundle)
    combat = CombatService(ROOT, tmp_path)
    mid = combat._finish_factory_match(bundles, [OWNER, FOE],
        {OWNER: "team:factory", FOE: "team:opponents"},
        {OWNER: {"x": 3, "y": 6}, FOE: {"x": 6, "y": 6}},
        combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"], [OWNER], [FOE],
        control_modes={actor: "MANUAL" for actor in (OWNER, FOE)}, match_seed="MISSRIDER1014",
        display_name="Miss rider regression", maximum_rounds=10)["match_id"]
    table = TabletopService(combat, tmp_path)
    for _ in range(10):
        menu = table.state(mid)["menu"]
        if menu["actor_id"] == FOE:
            break
        assert act(table, mid, menu["end_turn"])["status"] == "COMMITTED"
    assert act(table, mid, options(table, mid, FOCUS)[0]["candidate_id"])["status"] == "COMMITTED"
    assert act(table, mid, table.state(mid)["menu"]["end_turn"])["status"] == "COMMITTED"
    _owner_turn(table, mid)
    button = next(o for o in options(table, mid, MARK) if o["target_ids"] == [FOE])
    assert act(table, mid, button["candidate_id"])["status"] == "COMMITTED"
    # Start a later turn so the printed once-per-turn rider is available again.
    assert act(table, mid, table.state(mid)["menu"]["end_turn"])["status"] == "COMMITTED"
    _owner_turn(table, mid)
    return combat, table, mid, pinned


def _cold(tmp_path, mid):
    combat = CombatService(ROOT, tmp_path)
    session = combat._load_session(mid)
    assert session.mechanical.replay()["status"] == "PASS"
    return combat, TabletopService(combat, tmp_path), session.engine


@pytest.mark.parametrize("hit", [False, True])
def test_marked_dose_miss_or_hit_after_cold_reload(tmp_path, monkeypatch, hit):
    combat, table, mid, pinned = _table(tmp_path, monkeypatch)
    combat, table, engine = _cold(tmp_path, mid)
    assert bears_mark(engine.state.actors[FOE], OWNER, "Demon Mark")
    assert engine.state.actors[FOE].concentration is not None
    hp, temp = engine.state.actors[FOE].current_hp, engine.state.actors[FOE].temporary_hp
    start = engine.state.event_sequence
    pinned["attack"] = 19 if hit else 2
    dose = next(o for o in options(table, mid, DOSE) if o["target_ids"] == [FOE])
    assert act(table, mid, dose["candidate_id"])["status"] == "COMMITTED"
    _, _, engine = _cold(tmp_path, mid)
    events = [e for e in engine.events if e.sequence > start]
    packets = [e for e in events if e.event_type == "DAMAGE_COMMITTED"]
    saves = [e for e in events if e.event_type == "SAVE_ROLLED"
             and e.source_definition_id == "system:combat.concentration"]
    if not hit:
        assert not packets, "a missed attack must not trigger a damage rider"
        assert not saves, "no damage means no Concentration save"
        assert engine.state.actors[FOE].temporary_hp == temp
    else:
        primary = next(e for e in events if e.event_type == "DAMAGE_ROLLED"
                       and "POISON_BASE_DELIVER_THE_DOSE" in e.source_definition_id)
        assert primary.payload["modifier"] == 2 + PB, "Demon Mark raises the hit's printed roll"
        assert packets and sum(e.payload["temporary_hp_absorbed"] for e in packets) > PB
        assert all(e.payload["hp_damage"] == 0 for e in packets)
        assert saves, "real damage absorbed by temporary HP still requires Concentration saves"
    assert engine.state.actors[FOE].current_hp == hp


def test_miss_keeps_the_rider_available_after_another_cold_reload(tmp_path, monkeypatch):
    combat, table, mid, pinned = _table(tmp_path, monkeypatch)
    combat, table, engine = _cold(tmp_path, mid)
    # A miss and a hit in one multiattack are covered by the existing executor regression.
    # Here the service commits the miss before a fresh service reload on the same turn.
    dose = next(o for o in options(table, mid, DOSE) if o["target_ids"] == [FOE])
    assert act(table, mid, dose["candidate_id"])["status"] == "COMMITTED"
    _, _, engine = _cold(tmp_path, mid)
    from combat.typed_executor import on_hit_turn_key

    rider = next(m for m in engine.state.actors[OWNER].modifiers.values() if m.target_field == "typed_on_hit")
    evidence = str(rider.value).split("|", 2)[1]
    key, turn = on_hit_turn_key(engine, engine.state.actors[OWNER], rider.source_definition_id, evidence)
    assert engine.state.actors[OWNER].turn_flags.get(key) != turn


@pytest.mark.parametrize("amount", [0, 5])
def test_nonattack_damage_rider_requires_positive_damage_even_with_temporary_hp(amount):
    from combat import typed_executor as te
    from tests.test_mmx119f1_rider_attempt_isolation import _engine, _action, ACTOR, AN

    engine = _engine()
    actor, foe = engine.state.actors[ACTOR], engine.state.actors[AN]
    rider = {"type": "extra_damage", "applies_to": "target", "deferred": True,
             "flat": 1, "formula": "none", "damage_types": ["acid"],
             "evidence": "once per turn when you damage it, deal extra Acid damage"}
    action = _action(ACTOR, [rider], duration={"kind": "minutes", "amount": 1})
    engine.action_catalog[action.source_definition_id] = action
    ctx = te.Context(engine, actor, action, None, action.parameters["typed"], [foe], foe)
    te.run_effects(ctx, [rider])
    engine._grant_temp_hp(foe, 20, action.source_definition_id, ACTOR)
    start = len(engine.events)
    te._deal(ctx, foe, amount, "FORCE")
    packets = [e for e in engine.events[start:] if e.event_type == "DAMAGE_COMMITTED"]
    assert all(e.payload["hp_damage"] == 0 for e in packets)
    assert sum(e.payload["temporary_hp_absorbed"] for e in packets) == (amount + 1 if amount else 0)
    assert len([e for e in packets if e.payload["damage_type"] == "ACID"]) == (1 if amount else 0)

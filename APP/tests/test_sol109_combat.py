"""Regressions for COVER2 trigger ownership, placement subjects and saved tooltips."""
import copy
from types import SimpleNamespace

import pytest

from combat import ext, status_text, typed_executor
from combat.ext import placed, persistent_areas, tabik_scoundrel
from combat.factory_compiler import compile_character
from tests import h1_support as h1

ME = h1.ME
BOJUTSU = "tianxia.subpath.body.bojutsu.feature."
STAFF = "tianxia.mortal.weapon.gun"


def bundle(ids, *, items=()):
    return h1.bundle(ids, primary="Stamina", kit={"starting_kit": {
        "items": [{"item_id": item} for item in items]}})


def engine(ids, *, items=()):
    return h1.duel(ids, primary="Stamina", kit={"starting_kit": {
        "items": [{"item_id": item} for item in items]}})


@pytest.mark.parametrize("claimed", [False, True])
def test_complete_trigger_claim_is_general_and_default_inert(monkeypatch, claimed):
    ids = ("TEST_TRIGGER_A", "TEST_TRIGGER_B")
    donor = h1.mechanics()[BOJUTSU + "sweeping_strike"]
    mechanics = {}
    for mid in ids:
        row = copy.deepcopy(donor)
        row.update(mechanic_id=mid, name=mid, effects=[{"type": "temp_hp", "flat": 1, "applies_to": "self"}])
        mechanics[mid] = row

    def claim(info):
        if claimed:
            for mid in ids:
                if mid in info["owned_ids"]:
                    info["passives"].append({"block": "test_claim", "feature_id": mid, "trigger_owner": "test"})
        return None

    ext.effects()
    monkeypatch.setitem(ext._HOOKS, "compile_actions", [*ext._HOOKS.get("compile_actions", []), claim])
    sheet = {"identity": {"proficiency_bonus": 3},
             "ability_scores_and_statistics": {"primary_resource": {"name": "Stamina", "maximum": 10},
                                               "hit_points": {"maximum": 40}},
             "path_and_subpath": {"path_feature_record_ids": list(ids)}}
    result = compile_character(sheet, actor_id=ME, typed_authority={"mechanics": mechanics})
    generic = {r["feature_id"] for r in result["typed_reactions"] if r["block"] == "generic"}
    assert generic & set(ids) == (set() if claimed else set(ids))
    assert any(r["block"] == "opportunity" for r in result["typed_reactions"])
    # A character without either feature has no claimed rows or new trigger.
    sheet["path_and_subpath"]["path_feature_record_ids"] = []
    other = compile_character(sheet, actor_id=ME, typed_authority={"mechanics": mechanics})
    assert not any(r.get("trigger_owner") for r in other["typed_passives"])


def test_sweeping_strike_has_one_trigger_delivery_owner():
    result = bundle([BOJUTSU + "sweeping_strike"], items=[STAFF])
    assert not any(r["block"] == "generic" and r["feature_id"] == BOJUTSU + "sweeping_strike"
                   for r in result["typed_reactions"])
    assert any(r.get("trigger_owner") == "bojutsu" for r in result["typed_passives"])


@pytest.mark.parametrize("count", [1, 2])
def test_placed_save_visits_every_subject_once(count):
    fight = engine([], items=[STAFF])
    owner = fight.state.actors[ME]
    targets = list(fight.state.actors.values())[:count]
    action = next(a for a in fight.action_catalog.values() if a.owner_id == ME and a.parameters.get("typed"))
    ctx = placed.context(fight, owner, action.source_definition_id, {"save_dc": 100}, targets, action=action)
    assert ctx.target is (targets[0] if count == 1 else None)
    start = len(fight.events)
    typed_executor.run_effects(ctx, [{"type": "save", "ability": "dex", "applies_to": "target",
        "on_fail": [{"type": "damage", "flat": 1, "damage_types": ["force"], "applies_to": "target"}]}])
    events = fight.events[start:]
    assert [e.actor_id for e in events if e.event_type == "SAVE_ROLLED"] == [t.entity_id for t in targets]
    assert [e.target_ids for e in events if e.event_type == "DAMAGE_COMMITTED"] == [(t.entity_id,) for t in targets]


def test_scoundrel_shared_check_uses_public_modifier():
    fight = engine([])
    actor = fight.state.actors[ME]
    target = next(a for a in fight.state.actors.values() if a.entity_id != ME)
    assert not tabik_scoundrel.check_against_dc(fight, actor, target, "test:momentum", 100)
    assert fight.events[-1].event_type == "CHECK_ROLLED"


def test_equipment_readiness_survives_reload_without_status_tooltips(tmp_path):
    from tests.hunt51_grapple_support import fight, on_turn, send
    from tests.test_hunt51_grapple_persisted import reload
    from tests.test_status_text import _rows

    user, service, table, match, ids = fight(tmp_path, "sol109-grip", equipment=("tianxia.mortal.weapon.bi_shou",))
    on_turn(table, match, ids[0])
    send(table, match, lambda option: "Stow Bi Shou" in option["label"])
    loaded = reload(user, service, match)
    text = [r for r in _rows(table, service, match) if r["condition_id"] == "condition:typed.equipment_grip"]
    assert not text  # equipment is actor state, never a status pill or historical condition
    weapon = next(key for key in loaded.state.actors[ids[0]].equipment_readiness if key.endswith(".weapon.bi_shou"))
    assert loaded.state.actors[ids[0]].equipment_readiness[weapon] == 0
    assert loaded.events[-1].event_type == "EQUIPMENT_READINESS_SET"
    assert " stows Bi Shou" in loaded.events[-1].payload["log"]
    send(table, match, lambda option: "Draw Bi Shou" in option["label"])
    loaded = reload(user, service, match)
    assert loaded.state.actors[ids[0]].equipment_readiness[weapon] == 1
    text = [r for r in _rows(table, service, match) if r["condition_id"] == "condition:typed.equipment_grip"]
    assert not text
    changes = [e for e in loaded.events if e.event_type == "EQUIPMENT_READINESS_SET"]
    assert any(" stows Bi Shou" in e.payload.get("log", "") for e in changes)
    assert " draws Bi Shou" in changes[-1].payload["log"]


def test_expired_persistent_darkness_marker_keeps_specific_reading():
    # Historical CONDITION_APPLIED records contain no data and no live marker.
    fight = SimpleNamespace(action_catalog={}, state=SimpleNamespace(actors={}))
    row = {"condition_id": persistent_areas.PERSISTENT_AREA,
           "source_definition_id": "test:old-darkness", "source_actor_id": ME}
    text = status_text.describe(fight, None, row, {}, {}, {})
    assert "without Concentration" in text["rule_text"]
    assert "2 cultivation points" in text["rule_text"]
    assert "no Action" in text["rule_text"]
    assert "one minute" in text["rule_text"]
    assert "10 rounds" in text["duration"]

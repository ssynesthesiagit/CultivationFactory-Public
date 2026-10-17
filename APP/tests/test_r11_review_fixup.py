"""Service regressions for nested hold expiry and sealed pre-fight admission."""

import json
import zipfile

import pytest

from combat import concentration
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService, CombatServiceError, FACTORY_ACTOR_PREFIX
from combat.tabletop_service import TabletopService
from tests.test_riders_lane11 import DEEP, MOON, ROOT, _sheet


def _table(tmp_path, documents, bundles):
    ids = [b["actor_id"] for b in bundles]
    for aid, doc in zip(ids, documents):
        folder = tmp_path / "portable_characters" / aid.removeprefix(FACTORY_ACTOR_PREFIX)
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(doc))
    combat = CombatService(ROOT, tmp_path)
    mid = combat._finish_factory_match(
        bundles, ids, {ids[0]: "team:factory", ids[1]: "team:opponents"},
        {ids[0]: {"x": 3, "y": 6}, ids[1]: {"x": 4, "y": 6}},
        combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"], ids[:1], ids[1:],
        control_modes={aid: "MANUAL" for aid in ids}, match_seed="R11-REVIEW",
        display_name="Review regression", maximum_rounds=20)["match_id"]
    return combat, TabletopService(combat, tmp_path), mid


def _take(table, mid, name):
    menu = table.state(mid)["menu"]
    engine = table.combat._load_session(mid).engine
    candidate = next(c for c in engine.legal_candidates() if c.display_name == name)
    result = table.act(mid, candidate.candidate_id, menu["decision_id"], menu["state_version"], 0)
    assert result["status"] == "COMMITTED", result


def test_timed_concentration_parent_releases_pin_after_table_reload(tmp_path):
    victim, wrestler = [FACTORY_ACTOR_PREFIX + p for p in ("expiry-victim", "expiry-wrestler")]
    target = _sheet(DEEP)
    target["ability_scores_and_statistics"] = {
        **target["ability_scores_and_statistics"], "hit_points": {"maximum": 10000},
        "abilities": [{**r, "modifier": -100} if r["ability"] in ("STR", "DEX") else dict(r)
                      for r in target["ability_scores_and_statistics"]["abilities"]]}
    attacker = _sheet(MOON)
    attacker["path_and_subpath"] = {"path_feature_record_ids": []}
    attacker["spheres_and_talents"] = {
        "sphere_record_ids": ["tianxia.sphere.wrestling", "tianxia.sphere.gravity"],
        "learned_talent_record_ids": ["TAL_WRESTLING_PIN_2", "tianxia.talent.gravity.black_star_grip"]}
    documents = [target, attacker]
    combat, table, mid = _table(tmp_path, documents,
        [compile_character(doc, actor_id=aid) for doc, aid in zip(documents, (victim, wrestler))])
    while table.state(mid)["menu"]["actor_id"] != wrestler:
        _take(table, mid, "End turn")
    _take(table, mid, "Black-Star Grip")
    _take(table, mid, "End turn")
    _take(table, mid, "End turn")
    _take(table, mid, "Pin")
    session = CombatService(ROOT, tmp_path)._load_session(mid)
    actor = session.engine.state.actors[victim]
    pin = next(c for c in actor.conditions.values() if c.condition_id == "condition:typed.restrained")
    parent = pin.data["parent_hold"]
    assert parent in actor.conditions and pin.expires_on == "UNTIL_REMOVED"
    deadline = next(c for c in session.engine.state.actors[wrestler].conditions.values()
                    if c.condition_id == "condition:typed.concentration_deadline")
    assert deadline.expires_on.startswith("START_OF_SLOT_AT:")
    # Every turn is a table commit; reload before/after the nested expiry sweep.
    for _ in range(24):
        _take(table, mid, "End turn")
        session = CombatService(ROOT, tmp_path)._load_session(mid)
        actor = session.engine.state.actors[victim]
        if parent not in actor.conditions:
            break
        assert pin.instance_id in actor.conditions
    else:
        pytest.fail("Timed concentration parent did not expire")
    assert pin.instance_id not in actor.conditions
    assert not concentration.sources(session.engine.state.actors[wrestler])
    assert any(e.event_type == "CONDITION_REMOVED" and e.payload.get("instance_id") == pin.instance_id
               and e.payload.get("reason") == "PARENT_HOLD_ENDED" for e in session.engine.events)
    assert session.verify()["status"] == "PASS"
    assert session.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("sealed,current", [("unlimited", "cultivation_level"), ("cultivation_level", "unlimited")])
def test_prefight_service_uses_sealed_rules_in_both_directions(tmp_path, monkeypatch, sealed, current):
    from tests.test_prefight import SHEET

    caster, foe = [FACTORY_ACTOR_PREFIX + p for p in ("sealed-caster", "sealed-foe")]
    sheet = {**SHEET, "identity": {**SHEET["identity"], "cultivation_level": 1}}
    monkeypatch.setitem(concentration.rules(), "capacity", sealed)
    bundle = compile_character(sheet, actor_id=caster)
    assert bundle["concentration_rules"]["capacity"] == sealed
    picks = [next(o["action_id"] for o in bundle["prefight"]["options"] if o["name"] == name)
             for name in ("Meld: Clearsight", "Karmic Sight")]
    monkeypatch.setitem(concentration.rules(), "capacity", current)
    combat = CombatService(ROOT, tmp_path)
    if sealed == "cultivation_level":
        with pytest.raises(CombatServiceError, match="Concentration"):
            combat._with_prefight(bundle, {caster: picks})
        picks = picks[:1]
    prepared = combat._with_prefight(bundle, {caster: picks})
    assert prepared["prefight"]["picks"] == picks
    enemy = _sheet(MOON)
    enemy["path_and_subpath"] = {"path_feature_record_ids": []}
    combat, table, mid = _table(tmp_path, [sheet, enemy],
        [prepared, compile_character(enemy, actor_id=foe)])
    _take(table, mid, "End turn")
    session = CombatService(ROOT, tmp_path)._load_session(mid)
    assert set(concentration.sources(session.engine.state.actors[caster])) == set(picks)
    assert session.verify()["status"] == "PASS"
    assert session.mechanical.replay()["status"] == "PASS"

import pytest
from combat.gate5_service import CombatService
from tests.h1_support import ROOT
from tests.r1i_service_support import fixture, candidate, OWNER, FOE


@pytest.mark.parametrize("talent,label", [
    ("TAL_LIGHTNING_COURT_OF_CHARGED_PATHS", "Court of Charged Paths"),
    ("TAL_LIGHTNING_LIGHTNING_SOVEREIGN_INCARNATION", "Lightning Sovereign Incarnation"),
])
def test_denial_expires_at_victim_start_after_commit_reload(tmp_path, talent, label):
    combat, table, mid, send, commit = fixture(tmp_path, [talent])
    commit(candidate(table, mid, label))
    commit(candidate(table, mid, "Lightning Lash: Charge", FOE))
    def denied():
        loaded = CombatService(ROOT, tmp_path)._load_session(mid)
        return [c for c in loaded.engine.state.actors[FOE].conditions.values()
                if c.condition_id == "condition:typed.reaction_denied"]
    denial, = denied()
    assert denial.expires_on.startswith("START_OF_TURN_AT:" + FOE + ":")
    while table.state(mid)["menu"]["actor_id"] != FOE:
        assert denied()
        commit(table.state(mid)["menu"]["end_turn"])
    assert not denied()
    commit(table.state(mid)["menu"]["end_turn"])
    while table.state(mid)["menu"]["actor_id"] != OWNER:
        commit(table.state(mid)["menu"]["end_turn"])
    assert not denied()
    assert CombatService(ROOT, tmp_path)._load_session(mid).mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("talent,label", [
    ("TAL_LIGHTNING_COURT_OF_CHARGED_PATHS", "Court of Charged Paths"),
    ("TAL_LIGHTNING_LIGHTNING_SOVEREIGN_INCARNATION", "Lightning Sovereign Incarnation"),
])
def test_off_turn_denial_survives_caster_start_until_victim_next_start(tmp_path, talent, label):
    combat, table, mid, send, commit = fixture(tmp_path, [talent, "TAL_LIGHTNING_STATIC_GUARD"], owner_ac=0,
                                              foe_talents=["tianxia.path.body_refining.feature.iron_fist"], foe_score=50)
    commit(candidate(table, mid, label))
    commit(table.state(mid)["menu"]["end_turn"])
    while table.state(mid)["menu"]["actor_id"] != FOE:
        commit(table.state(mid)["menu"]["end_turn"])
    cid = candidate(table, mid, "Iron Fist", OWNER)
    result = send(cid)
    answers = []
    # The reviewed Iron Fist change asks its manual attacker for damage type
    # before the defender's Static Guard; retain both answers on this action.
    while (result['status'] == 'REACTION_REQUIRED'
           and result['reaction']['context']['reaction_source_id'] == 'choice:needle.iron_fist_damage_type'):
        prompt = result['reaction']
        answers.append({**prompt['context'], 'selection': 'USE',
                        'option_ids': [prompt['choice']['options'][0]['id']]})
        result = send(cid, answers)
    assert result["status"] == "REACTION_REQUIRED", result
    p = result["reaction"]
    assert "STATIC_GUARD" in p["context"]["reaction_source_id"]
    result = send(cid, [*answers, {**p["context"], "selection": "USE"}])
    assert result["status"] == "COMMITTED", result
    def denied():
        return any(c.condition_id == "condition:typed.reaction_denied"
                   for c in CombatService(ROOT, tmp_path)._load_session(mid).engine.state.actors[FOE].conditions.values())
    assert denied()
    commit(table.state(mid)["menu"]["end_turn"])
    while table.state(mid)["menu"]["actor_id"] != OWNER:
        assert denied()
        commit(table.state(mid)["menu"]["end_turn"])
    assert denied()  # source start must not clear the affected creature's denial
    commit(table.state(mid)["menu"]["end_turn"])
    while table.state(mid)["menu"]["actor_id"] != FOE:
        assert denied()
        commit(table.state(mid)["menu"]["end_turn"])
    assert not denied()
    assert CombatService(ROOT, tmp_path)._load_session(mid).mechanical.replay()["status"] == "PASS"

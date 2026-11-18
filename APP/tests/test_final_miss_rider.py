"""Miss riders wait for the final attack result, including later corrections."""
import pytest

from tests.test_critical_damage_reactions import (
    WEAPON_GUARD, ME, FOE, fight, crits, flippable_natural,
    to_turn, ask, attack_on, reload,
)
from tests.test_lock_choices import install


@pytest.mark.parametrize("replacement", ["none", "bonus", "outcome"])
def test_weapon_guard_step_waits_for_final_miss(tmp_path, monkeypatch, replacement):
    combat, table, mid = fight(tmp_path, mids=[WEAPON_GUARD])
    natural = flippable_natural(tmp_path, ranged=False)
    crits(monkeypatch, only=FOE, natural=natural)
    if replacement == "bonus":
        install(monkeypatch, "attack_miss_correction",
                lambda *args: {"source_id": "test:correction", "label": "Correction", "bonus": 10})
    elif replacement == "outcome":
        install(monkeypatch, "attack_miss_outcome",
                lambda *args: {"source_id": "test:replacement", "label": "Replacement", "force_hit": True})
    to_turn(table, mid, FOE)
    ask(table, mid, attack_on(combat, mid, ME, ranged=False))
    engine = reload(tmp_path, mid)
    assert any(e.event_type == "REACTION_RESOLVED" and e.source_definition_id == WEAPON_GUARD
               and e.payload.get("hit_after_recheck") is False for e in engine.events)
    moved = any(e.event_type == "MOVEMENT_GRANTED" and e.actor_id == ME for e in engine.events)
    assert moved is (replacement == "none")
    assert bool([e for e in engine.events if e.event_type == "DAMAGE_COMMITTED" and ME in e.target_ids]) is (replacement != "none")


def test_black_claw_step_provokes_second_enemy_after_table_reload(tmp_path):
    from combat.gate5_service import CombatService
    from tests.h1_support import ROOT
    from tests.r1i_service_support import fixture, candidate, OWNER, FOE, SECOND

    positions = {OWNER: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 6}, SECOND: {"x": 4, "y": 7}}
    combat, table, mid, send, commit = fixture(
        tmp_path, ["TAL_DAEMONIC_CULTIVATION_DEMON_SEED", "TAL_DAEMONIC_CULTIVATION_BLACK_CLAW_MANIFESTATION"],
        foe_ac=0, seed="OAFROM4-SECOND", positions=positions)
    commit(candidate(table, mid, "Demon Seed"))
    commit(table.state(mid)["menu"]["end_turn"])
    while table.state(mid)["menu"]["actor_id"] != OWNER:
        commit(table.state(mid)["menu"]["end_turn"])
    commit(candidate(table, mid, "Black-Claw Manifestation"))
    commit(table.state(mid)["menu"]["end_turn"])
    while table.state(mid)["menu"]["actor_id"] != FOE:
        commit(table.state(mid)["menu"]["end_turn"])
    before = combat._load_session(mid).engine.state.event_sequence
    cid = next(o["candidate_id"] for o in table.state(mid)["menu"]["moves"] if o["destination"] == {"x": 4, "y": 8})
    answers = []
    for _ in range(20):
        result = send(cid, answers)
        if result["status"] == "COMMITTED":
            break
        assert result["status"] == "REACTION_REQUIRED", result
        prompt = result["reaction"]
        source = prompt["context"]["reaction_source_id"]
        answer = {**prompt["context"], "selection": "USE"}
        if prompt.get("choice"):
            options = prompt["choice"]["options"]
            selected = "move" if source.endswith("black_claw") else (
                "cell:2,6" if source.endswith("rider_step") else options[0]["id"])
            assert selected in {o["id"] for o in options}
            answer["option_ids"] = [selected]
        answers.append(answer)
    assert result["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    events = [e for e in loaded.engine.events if e.sequence > before]
    assert loaded.engine.state.actors[OWNER].position.model_dump(mode="json") == {"x": 2, "y": 6}
    assert any(e.event_type == "ATTACK_ROLLED" and e.actor_id == SECOND for e in events)
    assert not any(e.event_type == "ATTACK_ROLLED" and e.actor_id == FOE for e in events)
    assert loaded.mechanical.replay()["status"] == "PASS"

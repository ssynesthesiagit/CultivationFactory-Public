"""Eye queries are pure; committed rolls and encounter export survive cold replay."""
import pytest

from combat.gate5_service import CombatService
from tests.h1_support import ROOT
from tests.test_mgr_mantis_native import (
    DECLINE, FOE, OWNER, admit_fact, candidate, native, reload, settle, strike, turn,
)


@pytest.mark.parametrize("bad_field", [{"source_cl": 0}, {"unprinted_data": "future spells"}])
def test_eye_source_validation_rejects_invalid_admission_without_a_saved_receipt(tmp_path, bad_field):
    from tests.test_mgr_mantis_native import concealment_fact

    def invalid(combat, state):
        payload = concealment_fact()
        payload["value"].update(bad_field)
        with pytest.raises(ValueError, match="document schema"):
            admit_fact(combat, state, payload)
        stable = CombatService(ROOT, tmp_path).journey_state(state["journey_id"])
        assert CombatService(ROOT, tmp_path).journey_state(state["journey_id"]) == stable
        return state

    combat, table, mid = native(tmp_path, cl=14, before_combat=invalid)
    reload(tmp_path, mid)


def test_eye_native_roll_query_and_per_turn_receipt_survive_cold_reload(tmp_path):
    combat, table, mid = native(tmp_path, cl=14)
    settle(table, mid, candidate(combat, mid, "Eye of the Mantis", target=FOE).candidate_id)
    for occurrence in range(2):
        engine = reload(tmp_path, mid)
        prior = len([roll for roll in engine.rolls if roll.actor_id == OWNER
                     and roll.reason.startswith("ATTACK:")])
        before = engine.state.model_dump_json()
        owner, foe = engine.state.actors[OWNER], engine.state.actors[FOE]
        # Native/reaction attacks query this same resolver, not typed attack_mode.
        assert engine._attack_mode(owner, foe) == "ADVANTAGE"
        table.state(mid)
        table.state(mid)
        assert engine.state.model_dump_json() == before
        start = engine.state.event_sequence
        settle(table, mid, strike(combat, mid).candidate_id, picks=DECLINE)
        engine = reload(tmp_path, mid)
        rolls = [roll for roll in engine.rolls if roll.actor_id == OWNER
                 and roll.reason.startswith("ATTACK:")]
        modes = [roll.mode for roll in rolls]
        fresh = modes[prior:]
        # The receipt is the first committed attack of this turn; every later
        # strike in the same sequence is an ordinary roll, whatever the count,
        # and the next turn re-arms it (this loop spends one receipt per turn).
        assert fresh and fresh[0] == "ADVANTAGE" and all(mode == "NORMAL" for mode in fresh[1:])
        assert len(modes) == len([event for event in engine.events
                                   if event.event_type == "ATTACK_ROLLED" and event.actor_id == OWNER])
        receipts = [event for event in engine.events if event.sequence > start
                    and event.event_type == "CONDITION_UPDATED"
                    and event.payload.get("data", {}).get("attack_turn")]
        assert len(receipts) == 1
        eye = next(c for c in engine.state.actors[FOE].conditions.values()
                   if c.condition_id.endswith(".eye_of_the_mantis"))
        assert receipts[0].payload["data"] == eye.data
        assert engine._attack_mode(engine.state.actors[OWNER], engine.state.actors[FOE]) == "NORMAL"
        if occurrence == 0:
            turn(table, mid, FOE)
            turn(table, mid, OWNER)


def test_eye_nested_native_attack_rolls_spend_the_same_receipt(tmp_path, monkeypatch):
    from combat import ext
    from combat.gate2_runtime_models import DiceSpec

    seen = []
    def native_followups(engine, event_type, kwargs):
        if (event_type != "CONDITION_APPLIED"
                or kwargs.get("payload", {}).get("condition_id") != "condition:typed.eye_of_the_mantis"):
            return
        # Synthetic event-driven followups exercise real nested native resolver
        # rolls during a table commit; no roll or ownership receipt is forged.
        owner, foe = engine.state.actors[OWNER], engine.state.actors[FOE]
        # The fixture's unarmed strike is its own native weapon row (Iron Fist);
        # the receipt must be read on any natural strike, not one printed name.
        source = next(aid for aid in owner.action_ids
                      if ".natural." in aid and "#rapid_pincer" not in aid)
        start = len(engine.rolls)
        for index in range(2):
            engine._resolve_attack_spec(owner, foe,
                {"attack_bonus": 100, "damage": DiceSpec(count=1, sides=4, modifier=0),
                 "damage_type": "BLUDGEONING", "reach_ft": 5,
                 "parameters": {"attack_kind": "unarmed"}},
                engine._active_intent, source_definition_id=source, attack_index=index + 1, notify=False)
        seen.extend(r.mode for r in engine.rolls[start:] if r.reason.startswith("ATTACK:"))

    ext.effects()
    monkeypatch.setitem(ext._HOOKS, "event", [*ext.subscribers("event"), native_followups])
    combat, table, mid = native(tmp_path, cl=14)
    settle(table, mid, candidate(combat, mid, "Eye of the Mantis", target=FOE).candidate_id)
    engine = reload(tmp_path, mid)
    assert seen and all(seen[i:i + 2] == ["ADVANTAGE", "NORMAL"] for i in range(0, len(seen), 2))
    rolls = [r for r in engine.rolls if r.reason.startswith("ATTACK:") and r.actor_id == OWNER]
    assert [r.mode for r in rolls] == ["ADVANTAGE", "NORMAL"]
    eye = next(c for c in engine.state.actors[FOE].conditions.values()
               if c.condition_id.endswith(".eye_of_the_mantis"))
    assert eye.data.get("attack_turn")


def test_eye_terminal_export_reopens_encounter_without_refreshing_snapshot(tmp_path):
    captured = {}
    def remember(combat, state):
        captured["jid"] = state["journey_id"]
        return state

    combat, table, mid = native(tmp_path, before_combat=remember, maximum_rounds=2)
    settle(table, mid, candidate(combat, mid, "Eye of the Mantis", target=FOE).candidate_id)
    profile = combat.observer_readings(mid, OWNER)[0]["details"]["profile"]
    for _ in range(10):
        if reload(tmp_path, mid).state.terminal_result is not None:
            break
        settle(table, mid, table.state(mid)["menu"]["end_turn"])
    terminal = reload(tmp_path, mid).state.model_dump_json()
    cold = CombatService(ROOT, tmp_path)
    jid = captured["jid"]
    state = cold.journey_state(jid)
    resumed = cold.journey_resume(jid, state["revision"])
    eye = cold.journey_menu(jid, OWNER)["properties"]["mantis_private_diagnosis"]
    remaining = (eye["remaining_num"], eye["remaining_den"])
    assert 0 < remaining[0] < 60 * remaining[1]
    started = cold.journey_start_combat(jid, resumed["revision"],
        {OWNER: "team:factory", **{aid: "team:opponents" for aid in resumed["actors"] if aid != OWNER}},
        maximum_rounds=2)
    engine = reload(tmp_path, started["match_id"])
    from combat.ext.mantis_style import eye_remaining
    from fractions import Fraction
    mark = next(c for c in engine.state.actors[FOE].conditions.values()
                if c.condition_id.endswith(".eye_of_the_mantis"))
    assert eye_remaining(engine, mark) == Fraction(*remaining)
    assert cold.observer_readings(started["match_id"], OWNER)[0]["details"]["profile"] == profile
    assert not cold.observer_readings(started["match_id"], FOE)
    assert reload(tmp_path, mid).state.model_dump_json() == terminal

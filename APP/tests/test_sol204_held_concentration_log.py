"""Held-copy end events through persisted intents, ready for the reducer lock round.

Synthetic actions exercise the existing shared concentration contract, not new
ability rules. The replacement case explicitly seals the supported legacy cap.
"""
import pytest

from combat import concentration
from combat.ext.concentration_duration import DEADLINE
from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionDefinition, ActionIntent
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.test_auto_docket import ROOT, ME, _sheet
from tests.test_lock_choices import install


def _actions(info):
    return [ActionDefinition(
        source_definition_id=f"action:test.sol204.{index}",
        display_name=f"Practice {index}", owner_id=info["actor_id"],
        economy="NONE", resolution_kind="TYPED", target_kind="SELF",
        parameters={"typed": {"source": f"test:sol204.{index}",
            "numbers": info["numbers"],
            "duration": {"kind": "rounds", "amount": rounds, "concentration": True},
            "effects": [{"type": "limit_concentration_duration"}]}},
    ) for index, rounds in ((1, 1), (2, 20), (3, 20))]


def _execute(data, mid, source=None):
    service = CombatService(ROOT, data)
    session = service._load_session(mid)
    candidate = next(c for c in session.engine.legal_candidates()
                     if (c.source_definition_id == source if source else c.kind.value == "END_TURN"))
    intent = ActionIntent(intent_id=f"sol204:{session.engine.state.state_version}",
        decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
        state_version=candidate.state_version, actor_id=candidate.actor_id,
        target_ids=candidate.target_ids, destination=candidate.destination,
        option_ids=candidate.option_ids)
    session.mechanical.execute_intent(intent)
    cold = CombatService(ROOT, data)._load_session(mid)
    assert cold.mechanical.replay()["status"] == "PASS"
    return cold


@pytest.mark.parametrize("ending", ["duration", "new_concentration"])
def test_held_copy_end_is_logged_and_preserves_current_after_cold_reload(tmp_path, monkeypatch, ending):
    install(monkeypatch, "compile_actions", _actions)
    bundle = compile_character(_sheet([]), actor_id=ME)
    if ending == "new_concentration":
        bundle["concentration_rules"] = {"capacity": "cultivation_level", "limits_by_cl": [[1, 2]]}
    service = CombatService(ROOT, tmp_path)
    session = service.persistence.create_match(match_seed="SOL204-" + ending,
        typed_bundles=(bundle,), roster_setup={"primary_actor_ids": [ME, AN],
        "team_by_actor": {ME: "team:a", AN: "team:b"},
        "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": 10, "y": 6}}})
    mid = session.match_id
    while session.engine.state.current_actor_id != ME:
        session = _execute(tmp_path, mid)
    first = "action:test.sol204.1"
    session = _execute(tmp_path, mid, first)
    started = session.engine.state.actors[ME].concentration.started_sequence
    session = _execute(tmp_path, mid, "action:test.sol204.2")
    assert concentration.held(session.engine.state.actors[ME])[0][1].started_sequence == started
    if ending == "new_concentration":
        session = _execute(tmp_path, mid, "action:test.sol204.3")
        expected_current = "action:test.sol204.3"
        reason = "REPLACED"
    else:
        for _ in range(6):
            session = _execute(tmp_path, mid)
            if not concentration.held(session.engine.state.actors[ME]):
                break
        expected_current = "action:test.sol204.2"
        reason = "DURATION_ENDED"
    actor = session.engine.state.actors[ME]
    assert actor.concentration.source_definition_id == expected_current
    assert started not in [state.started_sequence for _, state in concentration.held(actor)]
    endings = [event for event in session.engine.events
               if event.event_type == "CONCENTRATION_ENDED" and event.actor_id == ME
               and event.source_definition_id == first]
    assert len(endings) == 1
    assert {key: endings[0].payload.get(key) for key in ("reason", "started_sequence", "held")} == {
        "reason": reason, "started_sequence": started, "held": True}
    assert not any(row.condition_id == DEADLINE and row.data.get("started_sequence") == started
                   for row in actor.conditions.values())
    assert any(row.condition_id == DEADLINE and row.data.get("started_sequence") == actor.concentration.started_sequence
               for row in actor.conditions.values())
    table = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
    history = table.events(mid, 0)["events"]
    assert any("began concentrating on Practice 1." in row["summary"] for row in history)
    assert any("stopped concentrating on Practice 1." in row["summary"] for row in history)

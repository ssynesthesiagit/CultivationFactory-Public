"""AI-seat command persists, reloads, then executes on an automatic summon turn."""
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from test_h47_summon_table import table_fixture, candidate, guard, OWNER as TABLE_OWNER


def test_ai_command_selects_a_directive_without_asking_a_manual_seat(tmp_path, monkeypatch):
    combat, table, mid, _, commit = table_fixture(tmp_path)
    commit(candidate(table, mid, "Bone Guard Manifestation"))
    while table.state(mid)["menu"]["actor_id"] != TABLE_OWNER:
        commit(table.state(mid)["menu"]["end_turn"])
    from combat.gate4_controller import LocalDeterministicController
    original = LocalDeterministicController.choose_primary_action
    def command_first(self, context):
        priorities = dict(context.policy.action_priorities)
        has_command = any(".command." in row.source_definition_id for row in context.legal_candidates)
        for row in context.legal_candidates:
            if ".command." in row.source_definition_id:
                priorities[row.source_definition_id] = 1000000
            elif not has_command and row.kind == "END_TURN":
                priorities[row.source_definition_id] = 1000000
        context = context.model_copy(update={"policy": context.policy.model_copy(update={"action_priorities": priorities})})
        return original(self, context)
    monkeypatch.setattr(LocalDeterministicController, "choose_primary_action", command_first)
    combat.set_controller_mode(mid, actor_id=TABLE_OWNER, controller_mode="LOCAL_AUTO")
    response = table.auto_step(mid, table.state(mid)["last_sequence"])
    assert response["status"] == "COMMITTED", response
    creature = guard(combat, mid)
    assert creature.summon["directive"]["kind"] in ("attack", "follow")

    # Reload before the next automatic step to prove the committed order survives.
    before = combat._load_session(mid).engine.state.event_sequence
    fresh = CombatService(combat.source_root, tmp_path)
    reloaded = fresh._load_session(mid).engine.state.actors[creature.entity_id]
    assert reloaded.summon["directive"] == creature.summon["directive"]
    table = TabletopService(fresh, tmp_path)
    response = table.auto_step(mid, table.state(mid)["last_sequence"])
    assert response["status"] == "COMMITTED", response
    latest = CombatService(combat.source_root, tmp_path)._load_session(mid).engine
    assert "directive" not in latest.state.actors[creature.entity_id].summon
    assert latest.state.current_actor_id != creature.entity_id
    assert any(e.sequence > before and e.event_type == "SUMMON_TURN"
               and e.actor_id == creature.entity_id and "follows its order to " in e.payload["text"]
               for e in latest.events)

"""H10-00: named traces and owner-zone sight lines gate consent and spending."""
import pytest

from combat import typed_executor as te
from combat.tabletop_service import TabletopService
from combat.reaction_triggers import classify_trigger
from tests.hunt10_support import fight, use, reload_equal
from tests.test_auto_bodya import BODY_REFINING_SHEET

SMOKE_SHEET = {**BODY_REFINING_SHEET, "path_and_subpath": {},
    "equipment": [{"starting_kit": {"items": [{"item_id": "tianxia.mortal.weapon.dao", "quantity": 1}]}}],
    "spheres_and_talents": {
    "sphere_record_ids": ["tianxia.sphere.smoke"], "learned_talent_record_ids": [
        "SMOKE_BASE_SMOKE_RESPONSES", "SMOKE_BASE_SMOKE_VEIL", "SMOKE_BASE_SMOKE_TRACE"]}}


@pytest.mark.parametrize("name", ["Smoke Trace", "Mirror Trace", "Fracture Mark"])
def test_named_subject_tokens_are_general(name):
    assert classify_trigger(f"A creature with your {name} makes an attack roll").requires_mark == name


@pytest.mark.parametrize("ask", [False, True])
@pytest.mark.parametrize("ai_turn", [False, True])
@pytest.mark.parametrize("trace,veil", [(False, False), (False, True), (True, False), (True, True)])
def test_smoke_eligibility_and_trace_spend_commit_reload_replay(tmp_path, ask, trace, veil, ai_turn):
    effects = []
    if trace:
        effects.append({"type": "mark", "mark": "Smoke Trace", "applies_to": "target",
                        "duration": {"kind": "until_end_of_your_next_turn"}})
    if veil:
        effects.append({"type": "zone", "name": "Smoke Veil", "shape": "cube", "size_ft": 10,
                        "obscured": "light", "duration": {"kind": "rounds", "rounds": 10}})
    # Less than one grid step keeps the AI focused on the adjacent attack,
    # rather than choosing a legal tactical reposition before attacking.
    plain_attacker = {**SMOKE_SHEET, "spheres_and_talents": {"sphere_record_ids": [], "learned_talent_record_ids": []},
        "ability_scores_and_statistics": {**SMOKE_SHEET["ability_scores_and_statistics"], "speed": {"walking_ft": 1}}}
    service, session = fight(tmp_path, effects=effects, sheet=SMOKE_SHEET, ask=ask, setup_target="HOSTILE_ENTITY",
                             opponent_sheet=plain_attacker)
    defender_id = session.engine.state.current_actor_id
    row = next(r for r in session.engine.typed_reaction_rows[defender_id] if r["feature_id"] == "SMOKE_BASE_SMOKE_RESPONSES")
    use(session, "Test setup")
    use(session, "End Turn")
    session = reload_equal(service, session)
    attacker_id = session.engine.state.current_actor_id
    attack = next(c for c in session.engine.legal_candidates() if defender_id in c.target_ids and
                  any(e.get("type") == "attack" for e in (session.engine.action_catalog[c.source_definition_id].parameters.get("typed") or {}).get("effects") or []))
    service.set_controller_mode(session.match_id, actor_id=attacker_id, controller_mode="LOCAL_AUTO" if ai_turn else "MANUAL")
    service.set_controller_mode(session.match_id, actor_id=defender_id, controller_mode="MANUAL" if ask else "LOCAL_AUTO")
    table = TabletopService(service, tmp_path)
    state = table.state(session.match_id)
    answers, prompts = [], []
    def act():
        if ai_turn:
            return table.auto_step(session.match_id, state["last_sequence"], answers)
        return table.act(session.match_id, attack.candidate_id, attack.decision_id, attack.state_version,
                         state["last_sequence"], answers)
    result = act()
    while result["status"] == "REACTION_REQUIRED":
        prompt = result["reaction"]
        prompts.append(prompt)
        assert "Smoke Responses" in prompt["reaction"]
        answers.append({**prompt["context"], "selection": "USE"})
        result = act()
        assert len(prompts) <= 2
    assert result["status"] == "COMMITTED"
    session = service._load_session(session.match_id)
    resolved = [e for e in session.engine.events if e.event_type == "REACTION_RESOLVED" and e.source_definition_id == "SMOKE_BASE_SMOKE_RESPONSES"]
    assert bool(resolved) == (trace and veil), [(e.event_type, e.source_definition_id) for e in session.engine.events[-3:]]
    assert row["requires_mark"] == "Smoke Trace"
    assert row["requires_zone_los"] == "Smoke Veil"
    if ask:
        assert bool(prompts) == (trace and veil)
    attacker = session.engine.state.actors[attacker_id]
    assert te.bears_mark(attacker, defender_id, "Smoke Trace") == (trace and not veil)
    assert session.engine.state.actors[defender_id].reaction_available == (not (trace and veil))
    session = reload_equal(service, session)
    assert service.verify(session.match_id)["status"] == "PASS"
    assert service.replay(session.match_id)["status"] == "PASS"

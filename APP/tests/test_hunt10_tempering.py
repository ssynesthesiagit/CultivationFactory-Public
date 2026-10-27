"""H10-02: a Core Tempering Expression is a permanent build choice."""
from types import SimpleNamespace

import pytest
from combat.factory_compiler import compile_character
from combat.tabletop import auto_buttons
from combat.tabletop_service import TabletopService
from combat.ext.bodya_body_refining import CHOICE_CONDITION, cte_choice
from tests.hunt10_support import fight, use, reload_equal
from tests.test_auto_bodya import BODY_REFINING_SHEET


@pytest.mark.parametrize("ai_turn", [False, True])
def test_once_chosen_cannot_swap_at_table_or_directly_and_reloads(tmp_path, ai_turn):
    service, session = fight(tmp_path)
    actor_id = session.engine.state.current_actor_id
    table = TabletopService(service, tmp_path)
    state = table.state(session.match_id)
    candidate = next(c for c in session.engine.legal_candidates() if c.display_name == "Core Tempering Expression: Mountain-Rending Pulse")
    assert table.act(session.match_id, candidate.candidate_id, candidate.decision_id, candidate.state_version,
                     state["last_sequence"])["status"] == "COMMITTED"
    session = service._load_session(session.match_id)
    session = reload_equal(service, session)
    actor = session.engine.state.actors[actor_id]
    assert not any(c.display_name.startswith("Core Tempering Expression:") for c in session.engine.legal_candidates())
    # Defense in depth for a duplicate effect inside an accepted typed action.
    cte_choice(SimpleNamespace(engine=session.engine, actor=actor, source="test:duplicate"), {"expression": "blood_furnace"})
    assert next(c.data["expression"] for c in actor.conditions.values() if c.condition_id == CHOICE_CONDITION) == "mountain_rending"
    if ai_turn:
        service.set_controller_mode(session.match_id, actor_id=actor_id, controller_mode="LOCAL_AUTO")
        service.local_step(session.match_id)
    else:
        use(session, "End Turn")
    session = reload_equal(service, service._load_session(session.match_id))
    assert next(c.data["expression"] for c in session.engine.state.actors[actor_id].conditions.values()
                if c.condition_id == CHOICE_CONDITION) == "mountain_rending"
    assert service.verify(session.match_id)["status"] == "PASS"
    assert service.replay(session.match_id)["status"] == "PASS"


@pytest.mark.parametrize("recorded", ["blood_furnace", "Blood-Furnace Circulation"])
def test_recorded_sheet_choice_is_sealed_and_fixed(tmp_path, recorded):
    sheet = {**BODY_REFINING_SHEET, "path_and_subpath": {
        **BODY_REFINING_SHEET["path_and_subpath"], "core_tempering_expression": recorded}}
    service, session = fight(tmp_path, sheet=sheet)
    for actor in session.engine.state.actors.values():
        assert next(c.data["expression"] for c in actor.conditions.values() if c.condition_id == CHOICE_CONDITION) == "blood_furnace"
    assert not any(c.display_name.startswith("Core Tempering Expression:") for c in session.engine.legal_candidates())
    use(session, "End Turn")
    reload_equal(service, session)
    assert service.verify(session.match_id)["status"] == "PASS"
    assert service.replay(session.match_id)["status"] == "PASS"


def test_sheet_text_explains_permanent_choice():
    bundle = compile_character(BODY_REFINING_SHEET, actor_id="actor:factory.sheet")
    choices = [b for b in auto_buttons(bundle, {}) if b["label"].startswith("Core Tempering Expression:")]
    assert len(choices) == 3
    for button in choices:
        assert "permanent until a later Realm breakthrough" in button["description"]
        assert "costs no Stamina" in button["description"]
        assert "kept until you change it" not in button["description"]

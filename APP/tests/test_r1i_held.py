from combat import concentration, typed_executor as te
from combat.ext.speech import concentration_save
from combat.gate2_runtime_models import ActionIntent, ConcentrationState
from tests.test_riders_lane1 import _rider_engine, _rider_action, _rider_use, _answers, ME, AN


def test_world_nerve_success_can_check_an_older_held_copy():
    mid = "TAL_LIGHTNING_WORLD_NERVE_JUDGMENT"
    engine = _rider_engine(mid, dc=50)
    subject = engine.state.actors[AN]
    subject.concentration = ConcentrationState(source_definition_id="test:older", started_sequence=1)
    concentration.hold_current(engine, subject)
    subject.concentration = ConcentrationState(source_definition_id="test:current", started_sequence=2)
    iid, _ = concentration.held(subject)[0]
    seen = _answers(engine, {"held_effect": [iid]})
    action = _rider_action(engine, mid)
    intent = ActionIntent(intent_id="held", actor_id=ME, decision_id="test", candidate_id="test", state_version=engine.state.state_version)
    ctx = te.Context(engine, engine.state.actors[ME], action, intent, action.parameters["typed"], [subject], subject, {})
    spec = next(row for row in te._walk_rows(action.parameters["typed"]["effects"])
                if row.get("type") == "concentration_save" and row.get("choose_held"))
    concentration_save(ctx, spec)
    assert not concentration.held(subject)
    assert subject.concentration.source_definition_id == "test:current"
    assert subject.display_name in seen[0]["choice_trigger"]["prompt"]
    saves = [e for e in engine.events if e.event_type == "SAVE_ROLLED"]
    assert len(saves) == 1 and saves[0].payload.get("mode") != "DISADVANTAGE"


def test_compiled_world_nerve_successful_branch_offers_older_held_effect():
    mid = "TAL_LIGHTNING_WORLD_NERVE_JUDGMENT"
    engine = _rider_engine(mid, dc=-40)
    subject = engine.state.actors[AN]
    subject.maximum_hp = subject.current_hp = 500
    subject.saving_throws["CON"] = 100  # pass the initial and ordinary damage-maintenance saves
    subject.concentration = ConcentrationState(source_definition_id="test:older", started_sequence=1)
    concentration.hold_current(engine, subject)
    subject.concentration = ConcentrationState(source_definition_id="test:current", started_sequence=2)
    iid, _ = concentration.held(subject)[0]
    seen = _answers(engine, {"held_effect": [iid]})
    events = _rider_use(engine, mid)
    prompt = next(r for r in seen if r["reaction_source_id"] == "choice:needle.held_effect")
    assert iid in prompt["extension_choice"]["option_ids"]
    assert "successful save" in prompt["choice_trigger"]["prompt"]
    assert "test:older" in prompt["choice_trigger"]["labels"][iid]
    assert [e for e in events if e.event_type == "SAVE_ROLLED"][-1].payload["mode"] == "NORMAL"
    assert subject.concentration.source_definition_id == "test:current"
    assert concentration.held(subject)[0][0] == iid

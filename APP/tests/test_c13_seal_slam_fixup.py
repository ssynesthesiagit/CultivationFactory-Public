"""Source Seal owner choice at table boundaries and across commit/reload."""
from types import SimpleNamespace

import pytest

from tests import test_riders_c13 as C
from tests.test_c13_review_fixup import intent, accept
from combat.gate2_runtime_models import Position, ReactionDecision
from combat.gate5_service import CombatService, _ReactionRequired
from combat.tabletop_service import TabletopService

CELLS = [(2, 5), (2, 6), (2, 7), (3, 5), (3, 7)]


def seals(engine):
    return [z for z in engine.state.zones.values() if z.active and z.trigger_profile.get("name") == "Source Seal"]


def seeded_seals():
    engine, me, foe = C._fight(C.SOURCE, foe_at=(9, 6))
    for cell in CELLS[:4]:
        C._use(engine, "Source Seal", target=None, destination=cell)
    C.t._ready(engine)
    return engine


@pytest.mark.parametrize("manual", [True, False])
def test_source_seal_table_choice_retires_non_oldest_or_automatic_oldest(tmp_path, monkeypatch, manual):
    engine = seeded_seals()
    service = CombatService(C.ROOT, tmp_path)
    session = SimpleNamespace(engine=engine, match_id=engine.state.match_id)
    metadata = {"participant_control_modes": {C.ME: "MANUAL" if manual else "LOCAL_AUTO", C.AN: "LOCAL_AUTO"}}
    action = intent(engine, "Source Seal", destination=Position(x=3, y=7))
    before = engine.state.model_dump(mode="json")
    if manual:
        with pytest.raises(_ReactionRequired) as required:
            service._run_preview(session, metadata, action, ())
        context = required.value.context
        assert context.reactor_id == C.ME and context.reaction_source_id.endswith("source_seal_end")
        existing = {z.zone_id for z in seals(engine)}
        assert set(context.choice_trigger["needle_options"]) == existing
        table = TabletopService(service, tmp_path)
        monkeypatch.setattr(table, "_names_for", lambda mid: ({a.entity_id: a.display_name for a in engine.state.actors.values()}, {}))
        prompt = table._reaction_prompt(session.match_id, context.model_dump(mode="json"), engine=engine)
        assert "Source Seal" in prompt["moment"]
        chosen = next(z.zone_id for z in seals(engine) if (z.center.x, z.center.y) == CELLS[1])
        answer = ReactionDecision(checkpoint=context.checkpoint, reactor_id=C.ME,
            reaction_source_id=context.reaction_source_id, selection="USE", option_ids=(chosen,))
        preview = service._run_preview(session, metadata, action, (answer,))
    else:
        preview = service._run_preview(session, metadata, action, ())
    assert engine.state.model_dump(mode="json") == before
    engine.set_reaction_provider(lambda request: accept(request, [chosen] if manual else request["legal_option_ids"][:1]))
    engine.execute_intent(action)
    assert len(seals(engine)) == 4
    retained = {(z.center.x, z.center.y) for z in seals(engine)}
    assert (CELLS[1] if manual else CELLS[0]) not in retained
    assert CELLS[-1] in retained
    if manual:
        assert CELLS[0] in retained


def test_source_seal_non_oldest_choice_survives_commit_reload(tmp_path):
    persistence, session = C._persisted(tmp_path, C._bundle(C.SOURCE), "C13-SEALS-PERSIST", foe_at=(9, 6))
    def provider(request):
        ids = request["legal_option_ids"]
        return accept(request, [ids[1]])
    for index, cell in enumerate(CELLS):
        if index:
            session.submit_intent(intent(session.engine, "End turn"), primary_decision_record=None, reaction_provider=None)
            while session.engine.state.current_actor_id != C.ME:
                session.submit_intent(intent(session.engine, "End turn"), primary_decision_record=None, reaction_provider=None)
        session.submit_intent(intent(session.engine, "Source Seal", destination=Position(x=cell[0], y=cell[1])),
                              primary_decision_record=None, reaction_provider=provider)
    loaded = persistence.load_match(session.match_id).engine
    assert {(z.center.x, z.center.y) for z in seals(loaded)} == set(CELLS) - {CELLS[1]}
    assert {(z.zone_id, z.center) for z in seals(loaded)} == {(z.zone_id, z.center) for z in seals(session.engine)}

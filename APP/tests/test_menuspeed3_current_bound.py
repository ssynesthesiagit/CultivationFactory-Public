"""An Air-owned empty-score proof leaves all square authority reachable."""
from combat import placement_menu
from combat.ext.air_currents import current_search_possible
from combat.candidate_knowledge import query as observed
from tests.test_menuspeed3_placement import root_for
from tests.test_menuspeed3_review import offline_menu_embeddings, drive_auto
from tests.worker2_support import OWNER, ALLY, FOE, fixture, reload


def far_fixture(tmp_path):
    return fixture(tmp_path, ['TAL_AIR_COURT_OF_THE_FOUR_WINDS'], cl=17,
        positions={OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 2, 'y': 6}, FOE: {'x': 18, 'y': 6}})


def test_far_current_rank_skips_exhaustive_work_but_commits_any_aim(tmp_path, monkeypatch):
    combat, _, mid = far_fixture(tmp_path)
    engine = combat._load_session(mid).engine
    root = root_for(combat, mid)
    native = list(placement_menu.cells(engine, root))
    assert len(native) > 1
    complete = placement_menu.cells
    def cells(e, r):
        action = e.action_catalog[r.source_definition_id]
        assert (action.parameters.get('typed') or {}).get('source') != 'AIR_BASE_GATHER_CURRENT', \
            'far current scoring must not enumerate its authority'
        return complete(e, r)
    monkeypatch.setattr(placement_menu, 'cells', cells)
    context = combat.ai_decision_context(combat._load_session(mid))
    assert any(c.metadata.get('placement_picker')
               and (engine.action_catalog[c.source_definition_id].parameters.get('typed') or {}).get('source')
               == 'AIR_BASE_GATHER_CURRENT' for c in context.legal_candidates)
    aimed = native[-1].destination
    drive_auto(combat, mid, root, monkeypatch, 'LOCAL_AUTO', aimed)
    assert any(z.center == aimed for z in reload(tmp_path, mid).state.zones.values())


def test_current_proof_is_observed_and_default_inert(tmp_path, monkeypatch):
    combat, _, mid = far_fixture(tmp_path)
    engine = combat._load_session(mid).engine
    root = root_for(combat, mid)
    actor = engine.state.actors[OWNER]
    action = engine.action_catalog[root.source_definition_id]
    context = combat.ai_decision_context(combat._load_session(mid))
    assert current_search_possible(engine, actor, action, root, context) is None
    with observed(engine):
        assert current_search_possible(engine, actor, action, root, context) is False
        allow_empty = action.model_copy(update={'parameters': {**action.parameters, 'ai_allow_empty_area': True}})
        assert current_search_possible(engine, actor, allow_empty, root, context) is None
        other = action.model_copy(update={'parameters': {**action.parameters,
            'typed': {**action.parameters['typed'], 'source': 'test:other'}}})
        assert current_search_possible(engine, actor, other, root, context) is None
    # A near unseen creature in real state cannot widen the ranking proof's roster.
    near = engine.state.actors[FOE].model_copy(update={'position': actor.position})
    from combat import candidate_knowledge
    monkeypatch.setattr(candidate_knowledge, 'roster', lambda e: (actor,))
    assert current_search_possible(engine, actor, action, root, context) is False
    monkeypatch.setattr(candidate_knowledge, 'roster', lambda e: (actor, near))
    assert current_search_possible(engine, actor, action, root, context) is None

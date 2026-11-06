"""Set Array acquisition and seat boundaries through native table transactions."""
import pytest

from combat.ext import formations as F
from combat.candidate_knowledge import aim_allowed, query as observed_query
from combat.placement_menu import cells
from combat.factory_compiler import compile_character
from combat.gate4_context import build_decision_context
from tests.h1_support import sheet
from tests.worker2_support import OWNER, ALLY, fixture, candidate, settle, turn, reload


def sets(engine):
    return [c for c in engine.legal_candidates()
            if (action := engine.action_catalog.get(c.source_definition_id)) is not None
            and action.parameters.get(F.TAG) == 'set']


@pytest.mark.parametrize('owned', [False, True])
def test_set_requires_acquired_base_not_just_sphere_membership(tmp_path, owned):
    document = sheet([F.BASE_SET])
    if not owned:
        document['spheres_and_talents']['automatic_sphere_component_record_ids'].remove(F.BASE_SET)
        document['spheres_and_talents']['learned_talent_record_ids'].remove(F.BASE_SET)
    bundle = compile_character(document, actor_id=OWNER)
    combat, table, mid = fixture(tmp_path, [F.BASE_SET], owner_bundle=bundle, seed='SET-OWNERSHIP')
    engine = reload(tmp_path, mid)
    assert bool(sets(engine)) == owned
    policy, _ = combat.policies.for_actor(OWNER)
    context = build_decision_context(engine, policy, for_ai=True)
    assert not any(c.candidate_id in {s.candidate_id for s in sets(engine)} for c in context.legal_candidates), \
        'missing learning facts must not extend the legacy all-pattern fallback to AI'
    if owned:
        settle(table, mid, candidate(combat, mid, 'Combat Array: Locking Gate', at=(5, 6)).candidate_id)
        assert len(F.arrays(reload(tmp_path, mid), OWNER)) == 1
    turn(table, mid, ALLY)
    assert not sets(reload(tmp_path, mid)), 'another actor cannot use the owner array creation ability'


def test_set_choices_survive_ai_information_context_and_commit_reload(tmp_path):
    document = sheet([F.BASE_SET])
    document['spheres_and_talents']['formation_patterns'] = ['Locking Gate']
    bundle = compile_character(document, actor_id=OWNER)
    combat, table, mid = fixture(tmp_path, [F.BASE_SET], owner_bundle=bundle, seed='SET-AI')
    engine = reload(tmp_path, mid)
    offered = sets(engine)
    assert offered and {engine.action_catalog[c.source_definition_id].display_name for c in offered} == {'Combat Array: Locking Gate'}
    assert all(engine._distance_actor_to_cell(engine.state.actors[OWNER], c.destination) <= 30 for c in offered)
    policy, _ = combat.policies.for_actor(OWNER)
    context = build_decision_context(engine, policy, for_ai=True)
    roots = [c for c in context.legal_candidates if c.metadata.get('placement_picker')
             and c.source_definition_id == offered[0].source_definition_id]
    assert roots, 'the AI must be offered the learned pattern'
    with observed_query(engine):
        ai_ids = {c.candidate_id for root in roots for c in cells(engine, root)}
        actor = engine.state.actors[OWNER]
        visible_ids = {c.candidate_id for c in offered
                       if aim_allowed(engine, actor, c.destination, engine.action_catalog[c.source_definition_id])}
    assert visible_ids and visible_ids <= ai_ids
    before = engine.state.actors[OWNER].resources['resource:core.qi']
    settle(table, mid, candidate(combat, mid, 'Combat Array: Locking Gate', at=(5, 6)).candidate_id)
    engine = reload(tmp_path, mid)
    zone, = F.arrays(engine, OWNER)
    eye = engine.state.objects[F.record(zone)['eye']]
    assert eye.position == zone.center and not eye.destroyed
    assert zone.trigger_profile['difficult'] == 'hostile'
    assert F.record(zone)['layers'] == ['locking_gate']
    assert engine.state.actors[OWNER].resources['resource:core.qi'] == before - 2
    assert not engine.state.actors[OWNER].action_available
    assert engine.state.actors[OWNER].concentration.zone_id == zone.zone_id
    zone_cells = {(c.x, c.y) for c in zone.affected_cells}
    assert (7, 6) in zone_cells and (8, 6) not in zone_cells
    assert not sets(engine), 'setting an array consumes the Action'

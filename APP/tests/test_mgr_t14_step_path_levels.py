"""Predictive Step uses the existing owning-Path effective CL sheet contract."""
import pytest
from tests.worker2_support import fixture, turn, settle, candidate, reload, OWNER, ALLY, FOE
from tests.h1_support import sheet
from combat.factory_compiler import compile_character

SOURCE = 'tianxia.subpath.qi.divination_cultivator.feature.predictive_step'


@pytest.mark.parametrize('qi_cl,target,available', [(5, OWNER, False), (6, OWNER, True),
                                                  (10, ALLY, False), (11, ALLY, True)])
def test_other_path_level_does_not_unlock_predictive_step_or_warn_another(tmp_path, qi_cl, target, available):
    doc = sheet([SOURCE], cl=18)
    doc['path_and_subpath']['paths'] = [
        {'path_id': 'tianxia.path.qi_cultivation', 'effective_cl': qi_cl, 'key_ability': 'INT'},
        {'path_id': 'tianxia.path.body_refining', 'effective_cl': 18, 'key_ability': 'STR'}]
    bundle = compile_character(doc, actor_id=OWNER, reaction_plan={'ask': True})
    combat, table, mid = fixture(tmp_path, [], owner_bundle=bundle,
        positions={OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 4, 'y': 7}, FOE: {'x': 4, 'y': 6}})
    turn(table, mid, FOE)
    before = reload(tmp_path, mid).state.actors[OWNER].resources['resource:core.qi']
    prompts = settle(table, mid, candidate(combat, mid, 'Unarmed Strike', target=target).candidate_id,
        picks={'choice:needle.predictive_step_landing': 'cell:3,6' if target == OWNER else 'cell:4,7'})
    engine = reload(tmp_path, mid)
    assert any(p['context']['reaction_source_id'] == 'choice:needle.predictive_step' for p in prompts) == available
    assert engine.state.actors[OWNER].resources['resource:core.qi'] == before - (2 if available else 0)
    # The retired unphased reaction must not bypass the lower owning-Path CL.
    if not available:
        assert not [e for e in engine.events if e.event_type == 'REACTION_RESOLVED'
                    and e.source_definition_id == SOURCE]

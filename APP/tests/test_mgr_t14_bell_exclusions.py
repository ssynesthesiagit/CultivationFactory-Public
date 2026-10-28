"""Native Ninefold and Purifying Peal possession boundaries."""
import pytest
from combat import ext, observer_information as information
from combat.ext import mgr_reserve_bell_tower_cultivator_watch_bell as bell
from combat.gate2_runtime_models import ActionDefinition
from tests.h1_support import sheet
from tests.worker2_support import fixture, candidate, settle, reload, turn, OWNER, ALLY, FOE


@pytest.mark.parametrize('feature', [bell.NINE, bell.PURIFY])
def test_possession_and_judgment_boundaries(tmp_path, monkeypatch, feature):
    def provider(info):
        if info['actor_id'] != ALLY:
            return None
        return [ActionDefinition(source_definition_id='action:test.possession',
            display_name='Test possession', owner_id=ALLY, economy='ACTION',
            resolution_kind='TYPED', target_kind='SELF',
            parameters={'typed': {'source':'test:possession', 'numbers':dict(info['numbers']),
                'duration':{'kind':'instant'}, 'riders':[], 'effects':[{
                    'type':'information_source', 'tags':['possession'], 'applies_to':'self'}]}})]
    monkeypatch.setitem(ext._HOOKS, 'compile_actions', [*ext.subscribers('compile_actions'), provider])
    foe = sheet([], cl=18, name='Mara')
    foe['identity']['creature_type'] = 'undead'
    combat, table, mid = fixture(tmp_path, [], owner_features=[feature], cl=18,
        foe_sheet=foe, named=True, seed='BELL-EXCLUSIONS')
    turn(table, mid, ALLY)
    settle(table, mid, candidate(combat, mid, 'Test possession').candidate_id)
    engine = reload(tmp_path, mid)
    source = next(s for s in information.sources(engine, ALLY) if 'possession' in s['tags'])
    turn(table, mid, OWNER)
    if feature == bell.PURIFY:
        settle(table, mid, candidate(combat, mid, 'Purifying Peal').candidate_id,
            picks={'choice:needle.bell_allies_to_purify':[ALLY],
                   'choice:needle.bell_purify_'+ALLY:source['id']})
    else:
        settle(table, mid, candidate(combat, mid, 'Ninefold Heavenly Bell').candidate_id,
            picks={'choice:needle.bell_protected_allies':[OWNER, ALLY]})
        picks={'choice:needle.bell_two_different_heavenly_tones':['returning_clarity','heavenly_judgment'],
               'choice:needle.bell_returning_clarity':[ALLY],
               'choice:needle.bell_heavenly_judgment':[FOE]}
        for _ in range(8):
            menu=table.state(mid)['menu']
            settle(table, mid, menu['end_turn'], picks=picks)
            if table.state(mid)['menu']['actor_id'] == OWNER:
                break
    engine=reload(tmp_path,mid)
    remaining=source['id'] in engine.state.actors[ALLY].conditions
    assert remaining is (feature == bell.NINE)
    assert bool(bell.held(engine.state.actors[FOE], 'cannot_possess')) is (feature == bell.PURIFY)

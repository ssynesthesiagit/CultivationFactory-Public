"""Focused native source delivery regression."""
import pytest
from tests.worker2_support import settle, candidate, reload, turn, OWNER, FOE


def test_wrestling_learning_choice_acquires_once_from_the_installed_sheet_then_plays(tmp_path):
    import json
    import zipfile
    from tests.h1_support import ROOT, sheet
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    source = 'WRESTLING_BASE_APPLYING_A_SLAM'
    docs = {OWNER: sheet([source], cl=18, primary='Stamina', key='STR', score=30),
            FOE: sheet([], cl=18, score=10)}
    docs[OWNER]['identity']['path'] = 'Body Refining'
    for aid, doc in docs.items():
        path = tmp_path / 'portable_characters' / aid.removeprefix('actor:factory.')
        path.mkdir(parents=True)
        with zipfile.ZipFile(path / 'current.zip', 'w') as z:
            z.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(doc))
    def cold():
        return CombatService(ROOT, tmp_path)
    state = cold().create_journey(project_ids=[a.removeprefix('actor:factory.') for a in docs],
        arena_id=next(iter(cold().factory_arenas())), positions={OWNER: {'x': 3, 'y': 6}, FOE: {'x': 3, 'y': 5}},
        base_paces={a: 3000 for a in docs})
    jid = state['journey_id']
    menu = cold().journey_source_choices(jid, OWNER, source)
    choice = next(o for o in menu['options'] if o['payload']['talent_id'] == 'TAL_WRESTLING_HAMMERLOCK')
    with pytest.raises(ValueError):
        cold().journey_acquire_source(jid, menu['revision'], OWNER, source, {'talent_id': 'TAL_WRESTLING_HEAVEN_LIFTING_THROW'})
    assert cold().journey_state(jid) == state
    state = cold().journey_acquire_source(jid, menu['revision'], OWNER, source, choice['payload'])
    assert any(e.get('event_type') == 'SOURCE_TALENT_LEARNED' or e.get('kind') == 'SOURCE_TALENT_LEARNED'
               for e in state['events'])
    assert cold().journey_source_choices(jid, OWNER, source)['options'] == []
    with pytest.raises(ValueError):
        cold().journey_acquire_source(jid, state['revision'], OWNER, source, choice['payload'])
    result = cold().journey_start_combat(jid, state['revision'], {OWNER: 'team:a', FOE: 'team:b'})
    mid = result['match_id']
    combat = cold()
    table = TabletopService(combat, tmp_path)
    turn(table, mid, OWNER)
    settle(table, mid, candidate(combat, mid, 'Grapple', target=FOE).candidate_id)
    settle(table, mid, candidate(combat, mid, 'Apply a Slam: Hammerlock', target=FOE).candidate_id)
    engine = reload(tmp_path, mid)
    assert any(c.data.get('hold') == 'hammerlock' for c in engine.state.actors[FOE].conditions.values())


import pytest

from combat.ext.karma_imprints import RECORD, held
from combat.factory_compiler import compile_character
from tests.h1_support import mechanics, sheet
from tests.hunt28_support import FOE, OWNER, act, fixture, options, reload, send


@pytest.mark.parametrize('auto', [False, True])
@pytest.mark.parametrize('owns_record', [False, True])
def test_borrowed_karma_does_not_grant_record_reaction(tmp_path, auto, owns_record):
    talents = ['tianxia.talent.karma.burden_of_deeds']
    if owns_record:
        talents.append(RECORD)
    combat, table, mid = fixture(tmp_path, talents, borrowed=True, foe_kit=True)
    for _ in range(3):
        if table.state(mid)['menu']['actor_id'] == FOE:
            break
        assert act(table, mid, table.state(mid)['menu']['end_turn'])['status'] == 'COMMITTED'
    cid = next(o['candidate_id'] for o in options(table, mid, 'Bi Shou (Dagger) attack') if o['target_ids'] == [OWNER])
    result = send(combat, table, mid, cid, auto, actor=FOE)
    if owns_record:
        assert result['status'] == 'REACTION_REQUIRED'
        prompt = result['reaction']
        assert prompt['reaction'] == 'Record the Deed'
        assert prompt['context']['reactor_id'] == OWNER
        assert 'Dagger' in str(prompt)
        assert not held(combat._load_session(mid).engine.state.actors[FOE], OWNER)
        result = send(combat, table, mid, cid, auto,
                      [{**prompt['context'], 'selection': 'USE'}], actor=FOE)
    assert result['status'] == 'COMMITTED'
    engine = reload(combat, mid)
    assert bool(held(engine.state.actors[FOE], OWNER, 'debt')) == owns_record


def test_each_borrowed_karma_talent_compiles_without_unowned_record():
    tested = 0
    for talent, row in mechanics().items():
        if row.get('sphere_id') != 'tianxia.sphere.karma' or row.get('kind') != 'talent':
            continue
        doc = sheet([talent])
        doc['spheres_and_talents']['sphere_record_ids'] = []
        doc['spheres_and_talents']['automatic_sphere_component_record_ids'] = []
        bundle = compile_character(doc, actor_id=OWNER)
        assert not any(r.get('feature_id') == RECORD for store in ('typed_passives', 'typed_reactions')
                       for r in bundle.get(store, [])), talent
        tested += 1
    assert tested > 10

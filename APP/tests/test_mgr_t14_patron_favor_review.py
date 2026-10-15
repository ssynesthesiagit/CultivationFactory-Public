"""Review regressions: native concealed hits, bounded registration and cost text."""
from copy import deepcopy

import pytest

from combat import target_knowledge
from combat.ext import mgr_t14_patron_favor as favor
from tests import r1i_service_support as s
from tests.test_a2_qi_subpaths8 import fixture, cold
from tests.test_mgr_t14_ling_subpath_patron_favor import fight, use, options, QI
from tests.r10_fixup_support import cast_sender, commit as cast, fixed_dice


@pytest.mark.parametrize('choice', ['Drive', 'Shelter'])
def test_automatic_concealed_hit_keeps_admitted_recipient(tmp_path, monkeypatch, choice):
    combat, table, mid, send, commit = fixture(
        tmp_path, [favor.PRAYER, favor.FAVOR], patron='air', owner_cl=17, foe_ac=1,
        foe_talents=['TAL_DARK_PURE_DARKNESS', 'TAL_DARK_PERSISTENT_DARKNESS'],
        positions={s.OWNER: {'x': 3, 'y': 6}, s.FOE: {'x': 9, 'y': 6},
                   s.SECOND: {'x': 20, 'y': 15}}, wide=True,
        seed='FAVOR-REVIEW-HIDDEN')
    commit(table.state(mid)['menu']['end_turn'])
    while table.state(mid)['menu']['actor_id'] != s.FOE:
        commit(table.state(mid)['menu']['end_turn'])
    for name in ['Augment Darkness: Persistent Darkness', 'Shape Darkness: Pure Darkness']:
        cast(cast_sender(combat, table, mid, name))
    cast(cast_sender(combat, table, mid, 'Darkness + Persistent Darkness', at=(9, 6)))
    commit(table.state(mid)['menu']['end_turn'])
    while table.state(mid)['menu']['actor_id'] != s.FOE:
        commit(table.state(mid)['menu']['end_turn'])
    fixed_dice(monkeypatch, [100] * 60)
    cast(cast_sender(combat, table, mid, 'Hide'))
    commit(table.state(mid)['menu']['end_turn'])
    while table.state(mid)['menu']['actor_id'] != s.OWNER:
        commit(table.state(mid)['menu']['end_turn'])
    engine = cold(tmp_path, mid)
    assert target_knowledge.knowledge(engine, engine.state.actors[s.OWNER],
                                      engine.state.actors[s.FOE]).mode == 'LAST_OBSERVED'
    before = engine.state.actors[s.FOE].position.x
    seen = []
    original = favor.pick
    def observe(ctx, name, ids, labels, **kwargs):
        if name in ('movement', 'shelter'):
            seen.append((name, kwargs['automatic_options']))
        return original(ctx, name, ids, labels, **kwargs)
    monkeypatch.setattr(favor, 'pick', observe)
    cid = s.candidate(table, mid, 'Patron Spirit’s Favor: ' + choice, s.FOE)
    s.force_ai_candidate(combat, mid, s.OWNER, cid)
    answers = []
    for _ in range(16):
        result = send(cid, answers, auto=True)
        if result['status'] == 'COMMITTED':
            break
        assert result['status'] == 'REACTION_REQUIRED', result
        prompt = result['reaction']
        answers.append({**prompt['context'], 'selection': 'DECLINE'})
    else:
        raise AssertionError('automatic Prayer did not commit')
    engine = cold(tmp_path, mid)
    assert seen and s.FOE in seen[-1][1]
    assert s.SECOND not in seen[-1][1]
    assert engine.state.actors[s.OWNER].resources[QI] == 27
    if choice == 'Drive':
        assert engine.state.actors[s.FOE].position.x == before + 3


@pytest.mark.parametrize('patron', ['earth', 'metal', 'water', 'wood'])
def test_enhanced_prayer_prompt_quotes_actual_cost(tmp_path, patron):
    combat, table, mid, send, commit = fight(tmp_path, patron=patron)
    prompts = use(table, mid, send, 'Empower')
    prompt = next(p for p in prompts if p['context']['reaction_source_id'] ==
                  'choice:needle.shugenja_damage')
    assert 'It costs 3 Qi and one Action.' in str(prompt)
    assert 'It costs 1 Qi' not in str(prompt)
    assert cold(tmp_path, mid).state.actors[s.OWNER].resources[QI] == 27


def test_only_verified_prayer_delivery_is_published(tmp_path):
    combat, table, mid, send, commit = fight(tmp_path)
    engine = cold(tmp_path, mid)
    prayer = next(a.model_dump(mode='json') for a in engine.action_catalog.values()
                  if a.owner_id == s.OWNER and a.source_definition_id == favor.PRAYER)
    # Contract boundary: an explicit tag cannot enable an unverified producer.
    # This synthetic action is only a compile guard, never delivery evidence.
    other = deepcopy(prayer)
    other['source_definition_id'] = 'test:tagged_area_healing'
    other['parameters']['typed'].update(source='test:tagged_area_healing', qi_powered=True,
        source_tags=['air'], area={'shape': 'sphere', 'size_ft': 20},
        effects=[{'type': 'healing', 'dice': {'count': 1, 'sides': 8}}])
    bundle = {'typed_passives': [{'block': favor.BLOCK}], 'action_catalog': [prayer, other],
              'actor_template': {'action_ids': [prayer['source_definition_id'], other['source_definition_id']]}}
    result = favor.variants(bundle, {})
    assert not any(a['parameters']['typed'].get('variant_of') == other['source_definition_id']
                   for a in result['action_catalog'])
    assert not options(table, mid, 'Widen')
    assert not hasattr(favor, 'healing_bonus'), 'unverified healing hook must remain deferred'

import pytest

from tests.hunt28_support import ALLY, FOE, OWNER, fixture, options, reload, send
from combat.ext.shadow import legacy_willing_catalog, legacy_willing_choices
from combat.gate3_storage import load_typed_bundles


@pytest.mark.parametrize('auto', [False, True])
@pytest.mark.parametrize('target', [OWNER, ALLY])
@pytest.mark.parametrize('legacy', [False, True])
def test_willing_silhouette_marks_only_willing_side_and_persists(tmp_path, auto, target, legacy):
    combat, table, mid = fixture(tmp_path, ['TAL_SHADOW_SECOND_SILHOUETTE'], legacy_shadow=legacy)
    bundles = load_typed_bundles(combat._match_dir(mid))
    before = reload(combat, mid)
    originals = {key: action.model_dump(mode='json') for key, action in before.action_catalog.items()
                 if not key.endswith('#willing_saved')}
    owned_ids = before.state.actors[OWNER].action_ids
    willing = options(table, mid, 'Second Silhouette: Willing Creature')
    opponents = options(table, mid, 'Second Silhouette: Willing Creature (willing creature)')
    assert {o['target_ids'][0] for o in willing + opponents} == {OWNER, ALLY, FOE}
    hostile = options(table, mid, 'Second Silhouette: Unwilling Creature')
    assert {o['target_ids'][0] for o in hostile} == {FOE}
    cid = next(o['candidate_id'] for o in willing if o['target_ids'] == [target])
    result = send(combat, table, mid, cid, auto)
    if result['status'] == 'REACTION_REQUIRED':
        prompt = result['reaction']
        assert 'Second Silhouette' in str(prompt)
        assert prompt['context']['reactor_id'] == target
        result = send(combat, table, mid, cid, auto, [{**prompt['context'], 'selection': 'USE', 'option_ids': ['accept']}])
    assert result['status'] == 'COMMITTED'
    engine = reload(combat, mid)
    assert any('shadow_mark' in c.condition_id for c in engine.state.actors[target].conditions.values())
    assert not any(e.event_type == 'ATTACK_ROLLED' for e in engine.events)
    assert load_typed_bundles(combat._match_dir(mid)) == bundles
    assert engine.state.actors[OWNER].action_ids == owned_ids
    assert {key: engine.action_catalog[key].model_dump(mode='json') for key in originals} == originals
    assert len(legacy_willing_choices(engine, engine.state.actors[OWNER])) == 2 * int(legacy)
    assert not legacy_willing_choices(engine, engine.state.actors[ALLY])
    assert not legacy_willing_choices(engine, engine.state.actors[FOE])
    catalog = {key: action.model_dump(mode='json') for key, action in engine.action_catalog.items()}
    legacy_willing_catalog(engine)
    assert {key: action.model_dump(mode='json') for key, action in engine.action_catalog.items()} == catalog


@pytest.mark.parametrize('auto', [False, True])
def test_unwilling_silhouette_keeps_cultivation_attack(tmp_path, auto):
    combat, table, mid = fixture(tmp_path, ['TAL_SHADOW_SECOND_SILHOUETTE'])
    cid = options(table, mid, 'Second Silhouette: Unwilling Creature')[0]['candidate_id']
    assert send(combat, table, mid, cid, auto)['status'] == 'COMMITTED'
    engine = reload(combat, mid)
    assert any(e.event_type == 'ATTACK_ROLLED' and e.actor_id == OWNER for e in engine.events)


@pytest.mark.parametrize('auto', [False, True])
@pytest.mark.parametrize('legacy', [False, True])
def test_willing_ally_can_refuse_on_manual_and_ai_turns(tmp_path, auto, legacy):
    combat, table, mid = fixture(tmp_path, ['TAL_SHADOW_SECOND_SILHOUETTE'], legacy_shadow=legacy)
    cid = next(o['candidate_id'] for o in options(table, mid, 'Second Silhouette: Willing Creature')
               if o['target_ids'] == [ALLY])
    result = send(combat, table, mid, cid, auto)
    assert result['status'] == 'REACTION_REQUIRED'
    context = result['reaction']['context']
    assert context['reactor_id'] == ALLY
    assert send(combat, table, mid, cid, auto, [{**context, 'selection': 'DECLINE'}])['status'] == 'COMMITTED'
    engine = reload(combat, mid)
    assert not any('shadow_mark' in c.condition_id for c in engine.state.actors[ALLY].conditions.values())


def test_saved_willing_silhouette_ai_recipient_accepts_without_player_prompt(tmp_path):
    combat, table, mid = fixture(tmp_path, ['TAL_SHADOW_SECOND_SILHOUETTE'], legacy_shadow=True)
    combat.set_controller_mode(mid, actor_id=ALLY, controller_mode='LOCAL_AUTO')
    cid = next(o['candidate_id'] for o in options(table, mid, 'Second Silhouette: Willing Creature')
               if o['target_ids'] == [ALLY])
    assert send(combat, table, mid, cid, True)['status'] == 'COMMITTED'
    engine = reload(combat, mid)
    assert any('shadow_mark' in c.condition_id for c in engine.state.actors[ALLY].conditions.values())


@pytest.mark.parametrize('auto', [False, True])
@pytest.mark.parametrize('accept', [False, True])
@pytest.mark.parametrize('legacy', [False, True])
def test_willing_opponent_accepts_or_refuses_and_persists(tmp_path, auto, accept, legacy):
    combat, table, mid = fixture(tmp_path, ['TAL_SHADOW_SECOND_SILHOUETTE'], legacy_shadow=legacy)
    cid = next(o['candidate_id'] for o in options(
        table, mid, 'Second Silhouette: Willing Creature (willing creature)') if o['target_ids'] == [FOE])
    result = send(combat, table, mid, cid, auto)
    assert result['status'] == 'REACTION_REQUIRED'
    context = result['reaction']['context']
    assert context['reactor_id'] == FOE
    assert 'Second Silhouette' in str(result['reaction'])
    assert send(combat, table, mid, cid, auto, [{**context, 'selection': 'USE',
                'option_ids': ['accept' if accept else 'refuse']}])['status'] == 'COMMITTED'
    engine = reload(combat, mid)
    for actor in (OWNER, ALLY, FOE):
        marked = any('shadow_mark' in c.condition_id for c in engine.state.actors[actor].conditions.values())
        assert marked == (accept and actor == FOE)
    assert not any(e.event_type == 'ATTACK_ROLLED' for e in engine.events)


@pytest.mark.parametrize('legacy', [False, True])
def test_ai_opponent_declines_willing_mark_automatically(tmp_path, legacy):
    combat, table, mid = fixture(tmp_path, ['TAL_SHADOW_SECOND_SILHOUETTE'], legacy_shadow=legacy)
    combat.set_controller_mode(mid, actor_id=FOE, controller_mode='LOCAL_AUTO')
    cid = options(table, mid, 'Second Silhouette: Willing Creature (willing creature)')[0]['candidate_id']
    assert send(combat, table, mid, cid, True)['status'] == 'COMMITTED'
    engine = reload(combat, mid)
    assert not any('shadow_mark' in c.condition_id for c in engine.state.actors[FOE].conditions.values())

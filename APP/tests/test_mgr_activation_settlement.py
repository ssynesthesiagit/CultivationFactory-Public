"""Real activation receipts and strict rollback guards for the general seam."""
import pytest
from combat import ext
from tests.worker2_support import fixture, candidate, settle, reload, OWNER, FOE


def test_native_settlement_uses_only_executed_source_and_replays(tmp_path, monkeypatch):
    ext.effects()
    seen = []
    def observe(ctx, receipt):
        seen.append(receipt)
    monkeypatch.setitem(ext._HOOKS, 'activation_settlement', [*ext._HOOKS.get('activation_settlement', ()), observe])
    combat, table, mid = fixture(tmp_path, ['FIRE_BASE_IGNITE'], cl=10, seed='SETTLEMENT')
    settle(table, mid, candidate(combat, mid, 'Ignite: Increase Burn Damage', target=FOE).candidate_id)
    engine = reload(tmp_path, mid)
    receipt = next(r for r in reversed(seen) if r['source_id'] == 'FIRE_BASE_IGNITE')
    assert receipt['source_kind'] == 'Sphere'
    assert receipt['source_cl'] == 10 and receipt['qi_powered'] == 1
    assert receipt['weapon_delivery'] == 0
    packets = [e for e in engine.events[receipt['first_sequence']:receipt['last_sequence']]
               if e.event_type == 'DAMAGE_COMMITTED' and e.source_definition_id == receipt['action_id']
               and e.actor_id == OWNER]
    assert receipt['damage_types'] == sorted({e.payload['damage_type'] for e in packets})
    assert set(receipt['recipient_ids']) == {tid for e in packets for tid in e.target_ids}
    assert not any('catalog' in key or 'unactivated' in key for key in receipt)


def test_native_settlement_failure_rolls_back_entire_table_intent(tmp_path, monkeypatch):
    combat, table, mid = fixture(tmp_path, ['FIRE_BASE_IGNITE'], cl=10)
    before = reload(tmp_path, mid).state.model_dump(mode='json')
    c = candidate(combat, mid, 'Ignite: Increase Burn Damage', target=FOE)
    ext.effects()
    def reject(ctx, receipt):
        raise ValueError('settlement rejected')
    monkeypatch.setitem(ext._HOOKS, 'activation_settlement', [*ext._HOOKS.get('activation_settlement', ()), reject])
    with pytest.raises(Exception) as rejected:
        settle(table, mid, c.candidate_id)
    assert 'settlement rejected' in str(rejected.value.__cause__)
    assert reload(tmp_path, mid).state.model_dump(mode='json') == before


def test_path_profile_consumes_native_attainment_without_borrowing_chassis():
    from combat.activation_settlement import path_numbers
    info = {'numbers': {'cl': 18, 'pb': 6, 'key_mod': 2}, 'owner_sheet': {
        'identity': {'cultivation_level': 18}, 'path_and_subpath': {'paths': [
            {'path_id': 'tianxia.path.qi_cultivation', 'attainment': 6}]}}}
    assert path_numbers(info, 'tianxia.path.qi_cultivation') == {'cl': 6, 'pb': 3, 'key_mod': 2}
    assert path_numbers(info, 'tianxia.path.body_refining') == info['numbers']
    info['owner_sheet']['path_and_subpath']['paths'][0]['effective_cl'] = 3
    assert path_numbers(info, 'tianxia.path.qi_cultivation')['pb'] == 2
    info['owner_sheet']['path_and_subpath']['paths'][0]['effective_cl'] = '3'
    with pytest.raises(ValueError, match='integer'):
        path_numbers(info, 'tianxia.path.qi_cultivation')


@pytest.mark.parametrize('pool,qi_powered', [('qi', True), ('stamina', False), ('resonance', False)])
def test_selected_paid_path_controls_sphere_provenance_through_table(tmp_path, pool, qi_powered):
    """Generic portable compiler/table contract, not assigned-row acquisition credit."""
    from combat.factory_compiler import compile_character
    from combat.activation_settlement import profile
    from tests.h1_support import sheet
    doc = sheet(['FIRE_TAL_FIREBALL_ART'], cl=10)
    doc['ability_scores_and_statistics']['primary_resource']['definitions'] = [
        {'name': name, 'maximum': 100, 'current': 100} for name in ('Qi', 'Stamina', 'Resonance')]
    first = compile_character(doc, actor_id=OWNER, reaction_plan={'ask': True})
    aid = next(action['source_definition_id'] for action in first['action_catalog'] if action['display_name'] == 'Fireball Art')
    bundle = compile_character(doc, actor_id=OWNER, reaction_plan={'ask': True}, powering={aid: pool})
    combat, table, mid = fixture(tmp_path, [], cl=10, owner_bundle=bundle)
    settle(table, mid, candidate(combat, mid, 'Fireball Art', at=(6, 6)).candidate_id)
    engine = reload(tmp_path, mid)
    actual = profile(engine, engine.state.actors[OWNER], engine.action_catalog[aid])
    assert bool(actual['qi_powered']) is qi_powered
    assert any(event.event_type == 'RESOURCE_SPENT' and event.actor_id == OWNER
        and event.payload['resource_id'] == 'resource:core.' + pool and event.payload['amount'] == 5
        for event in engine.events)


@pytest.mark.parametrize('rules,expected', [([], 18),
    ([{'effective_cl': 12}, {'cultivation_cl_cap': 6}], 6),
    ([{'cultivation_cl_cap': 0}], 0),
    ([{'effective_cl': True}, {'cultivation_cl_cap': '3'}], 18)])
def test_published_cultivation_cap_readers_agree(rules, expected):
    """Contract boundary, not native acquisition or cap-source delivery credit."""
    from types import SimpleNamespace
    from combat.cultivation_access import effective_cl
    from combat.ext.activation_requirements import effective_cl as admitted_cl
    actor = SimpleNamespace(conditions={str(i): SimpleNamespace(
        condition_id='condition:typed.cultivation_limit', data={'rule': rule})
        for i, rule in enumerate(rules)})
    assert effective_cl(None, actor, 18) == expected
    assert admitted_cl(actor, 18) == expected

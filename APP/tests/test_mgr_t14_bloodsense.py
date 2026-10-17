"""Bloodsense facts through native table perception, decisions and cold replay.

Provenance is authored at encounter creation. Damage and invisibility are real
typed actions; no test mutates a loaded engine or calls the Bloodsense helper.
"""
from copy import deepcopy
import pytest
from combat.canonical import canonical_sha256
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, settle, reload, prompt_turn

BLOOD = 'BLOOD_BASE_BLOODSENSE'


def probes(bundles):
    for bundle in bundles:
        base = next(a for a in bundle['action_catalog'] if a['parameters'].get('typed'))
        for name, effects in [
            ('Injure self', [{'type': 'hp_cost', 'amount': bundle['actor_template']['maximum_hp'] // 2 + 1}]),
            ('Become Invisible', [{'type': 'condition', 'condition': 'Invisible', 'applies_to': 'self',
                                  'duration': {'kind': 'rounds', 'rounds': 2}}]),
        ]:
            action = deepcopy(base)
            source = 'test:bloodsense.' + bundle['actor_id'] + '.' + name.replace(' ', '_')
            action.update(source_definition_id=source, display_name=name, economy='NONE', target_kind='SELF', costs=[])
            typed = action['parameters']['typed']
            typed.update(source=source, effects=effects, riders=[], area=None, zone_spec={},
                         duration={'kind': 'instant'})
            action['parameters'] = {'typed': typed, 'free_primary': True}
            bundle['action_catalog'].append(action)
            bundle['actor_template']['action_ids'].append(source)
        bundle.pop('bundle_sha256', None)
        bundle['bundle_sha256'] = canonical_sha256(bundle)


def setup(tmp_path, sources, **kwargs):
    def arena(doc):
        doc['sensory_sources'] = sources
    return fixture(tmp_path, [BLOOD], named=True, bundle_transform=probes,
                   battlefield_transform=arena, **kwargs)


def facts(table, mid, viewer=OWNER):
    state = table.state(mid, fog=True, fog_view='own', fog_actor_ids=(viewer,))
    return state['fog_perception'].get(viewer, {}).get('information', [])


def source(kind, **fields):
    return {'medium': 'blood', 'kind': kind, **fields}


def test_authored_facts_are_private_and_survive_commit_cold_reload(tmp_path):
    rows = [
        source('creature', entity_id=FOE, circulation=1, source_key='hidden-identity'),
        source('spill', position={'x': 5, 'y': 6}, exposed=1, occurred_at_seconds=-30),
        source('corpse', position={'x': 5, 'y': 7}, obvious=1, label='fallen traveller', likely_blood_loss=1),
        source('corpse', position={'x': 4, 'y': 7}, obvious=1, label='fallen guard', likely_blood_loss=0),
        source('corpse', position={'x': 3, 'y': 7}, obvious=1, label='unknown cause'),
        source('sample', position={'x': 5, 'y': 6}, obvious=1, label='new sample', source_key='hidden-identity'),
        source('sample', position={'x': 19, 'y': 6}, label='studied vial', source_key='hidden-identity', studied_by=[OWNER], expires_at_seconds=0),
        source('sample', position={'x': 19, 'y': 7}, label='other vial', source_key='other', studied_by=[OWNER]),
        source('sample', position={'x': 19, 'y': 8}, label='unstudied vial', source_key='hidden-identity'),
    ]
    combat, table, mid = setup(tmp_path, rows)
    assert {'ability': 'Bloodsense', 'kind': 'injury', 'creature_id': FOE, 'injured': 0} in facts(table, mid)
    prompt_turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Injure self').candidate_id)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[FOE].current_hp * 2 <= engine.state.actors[FOE].maximum_hp
    result = facts(table, mid)
    assert {'ability': 'Bloodsense', 'kind': 'direction', 'direction': 'east'} in result
    assert {'ability': 'Bloodsense', 'kind': 'injury', 'creature_id': FOE, 'injured': 1} in result
    assert any(r['kind'] == 'recent_spill' for r in result)
    assert {r['likely_blood_loss'] for r in result if r['kind'] == 'corpse_cause'} == {0, 1}
    matches = [r for r in result if r['kind'] == 'sample_match']
    assert {(r['studied_sample'], r['same_creature']) for r in matches} == {('studied vial', 1), ('other vial', 0)}
    assert 'hidden-identity' not in str(result)
    assert 'unknown cause' not in str(result)
    assert not facts(table, mid, ALLY) and not facts(table, mid, FOE)
    assert all('information' not in row for row in table.state(mid, fog=True)['fog_perception'].values())
    assert not any('information' in event.payload for event in engine.events)
    from combat.gate4_context import build_decision_context
    policy, _ = combat.policies.for_actor(FOE)
    assert not build_decision_context(engine, policy, for_ai=True).information
    prompt_turn(table, mid, OWNER)
    session = combat._load_session(mid)
    context = combat.ai_decision_context(session)
    assert list(context.information) == facts(table, mid)
    assert 'hidden-identity' not in str(table.state(mid)['menu'])
    assert reload(tmp_path, mid).state.state_version == session.engine.state.state_version


@pytest.mark.parametrize('spill', ['none', 'old', 'recent', 'fresh', 'expired', 'other_source', 'sealed'])
def test_invisible_requires_fresh_exposed_same_source_not_hour_old_blood(tmp_path, spill):
    rows = [source('creature', entity_id=FOE, circulation=1, source_key='one'),
            source('sample', entity_id=FOE, obvious=1, label='carried vial', source_key='one'),
            source('sample', position={'x': 19, 'y': 6}, label='studied vial', source_key='one', studied_by=[OWNER])]
    if spill != 'none':
        rows.append(source('spill', position={'x': 5, 'y': 6}, exposed=0 if spill == 'sealed' else 1,
                           source_key='other' if spill == 'other_source' else 'one',
                           occurred_at_seconds=-3601 if spill == 'old' else -30,
                           fresh_until_seconds=100 if spill in ('fresh', 'other_source', 'sealed') else 0,
                           **({'expires_at_seconds': 0} if spill == 'expired' else {})))
    combat, table, mid = setup(tmp_path, rows)
    prompt_turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Injure self').candidate_id)
    settle(table, mid, candidate(combat, mid, 'Become Invisible').candidate_id)
    engine = reload(tmp_path, mid)
    assert any(c.condition_id == 'condition:typed.invisible' for c in engine.state.actors[FOE].conditions.values())
    result = facts(table, mid)
    assert any(r['kind'] == 'direction' for r in result) == (spill == 'fresh')
    assert not any(r['kind'] == 'injury' for r in result)
    assert not any(r['kind'] == 'sample_match' for r in result)
    assert any(r['kind'] == 'recent_spill' for r in result) == (spill in ('recent', 'fresh', 'other_source'))
    from combat.target_knowledge import located
    assert not located(engine, engine.state.actors[OWNER], engine.state.actors[FOE])


@pytest.mark.parametrize('seconds, expected', [(-3594, True), (-3600, False), (100, False)])
def test_one_hour_boundary_uses_native_turn_clock_and_reload(tmp_path, seconds, expected):
    combat, table, mid = setup(tmp_path, [source('spill', position={'x': 5, 'y': 6}, exposed=1,
                                                occurred_at_seconds=seconds)])
    initial = facts(table, mid)
    assert bool(initial) == (seconds <= 0)
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    prompt_turn(table, mid, OWNER)
    assert reload(tmp_path, mid).state.round_number == 2
    assert bool(facts(table, mid)) == expected


def test_range_cover_and_source_filters_through_table(tmp_path):
    rows = [source('spill', position={'x': 16, 'y': 6}, exposed=1, occurred_at_seconds=0),
            source('spill', position={'x': 5, 'y': 6}, exposed=0, occurred_at_seconds=0),
            {'medium': 'water', 'kind': 'spill', 'position': {'x': 5, 'y': 6}, 'exposed': 1, 'occurred_at_seconds': 0},
            source('corpse', position={'x': 5, 'y': 7}, obvious=1),
            source('spill', position={'x': 11, 'y': 6}, exposed=1, occurred_at_seconds=0)]
    combat, table, mid = setup(tmp_path, rows)
    engine = reload(tmp_path, mid)
    # Arena pillar blocks the eastward source; no blood fact bypasses Total Cover.
    from combat.gate2_runtime_models import Position
    assert not engine._line_of_sight_actor_to_cell(engine.state.actors[OWNER], Position(x=11, y=6))
    assert not facts(table, mid)


@pytest.mark.parametrize('x, expected', [(15, True), (16, False)])
def test_live_range_boundary(tmp_path, x, expected):
    combat, table, mid = setup(tmp_path,
        [source('spill', position={'x': x, 'y': 2}, exposed=1, occurred_at_seconds=0)],
        positions={OWNER: {'x': 3, 'y': 2}, ALLY: {'x': 4, 'y': 2}, FOE: {'x': 6, 'y': 2}})
    assert bool(facts(table, mid)) == expected
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    reload(tmp_path, mid)
    assert bool(facts(table, mid)) == expected


def test_native_regression_detects_missing_provider(tmp_path, monkeypatch):
    """The native service regression fails with the former no-fact provider state.

    This is test-only registry configuration, never a production engine patch.
    Keep unrelated information providers enabled and execute the same table test.
    """
    from combat import ext
    providers = ext.subscribers('observer_information')
    assert any(provider.__module__ == 'combat.ext.bloodsense' for provider in providers)
    monkeypatch.setitem(ext._HOOKS, 'observer_information',
                        [provider for provider in providers if provider.__module__ != 'combat.ext.bloodsense'])
    with pytest.raises(AssertionError, match='injury'):
        test_authored_facts_are_private_and_survive_commit_cold_reload(tmp_path)


from tests import test_a2_glass_stock as stock


@pytest.mark.parametrize('seed', stock.STOCK_SEEDS)
def test_six_stock_replays_with_lane_owned_output(tmp_path, monkeypatch, seed):
    """Use the stock guard's mainline base and disposable lane-owned captures."""
    monkeypatch.setenv('CF_STOCK_EVIDENCE', str(tmp_path / 'stock-evidence'))
    stock.test_six_stock_captures_equal_main(tmp_path, seed)

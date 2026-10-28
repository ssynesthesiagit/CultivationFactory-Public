"""Native authored construction survives combat and elapsed-scene cold loads."""
import pytest
from combat.gate5_service import CombatService
from combat.journey_assets import JourneyAssetContext
from combat.object_rules import fragility, has_tag
from combat.tabletop import TabletopMapStore, to_battlefield
from tests.h1_support import ROOT
from tests.worker2_support import OWNER, ALLY, FOE, fixture, reload


def test_authored_construction_and_explicit_override_match_in_combat_and_journey(tmp_path):
    rows = [
        {'material': 'wood', 'resilient': False},
        {'material': 'glass', 'resilient': True},
        {'material': 'glass', 'resilient': False, 'fragile': False},
        {'material': 'stone', 'resilient': True, 'fragile': True},
    ]
    native_maps = CombatService(ROOT, tmp_path).tabletop_maps
    saved = native_maps.save({'display_name': 'Construction classification',
        'width_squares': 20, 'height_squares': 18, 'objects': [
            {'kind': 'custom', 'x': 8 + i, 'y': 6, 'hp': 100, 'blocks': False, **row}
            for i, row in enumerate(rows)]})
    combat, table, mid = fixture(tmp_path, [], cl=1, battlefield=to_battlefield(saved))
    engine = reload(tmp_path, mid)
    expected = [True, False, False, True]
    assert [fragility(engine.state.objects[f'object:map.{i}']) for i in range(1, 5)] == expected
    state = combat.create_journey(project_ids=[aid.removeprefix('actor:factory.') for aid in (OWNER, ALLY, FOE)],
        arena_id='battlefield:map.' + saved['map_id'],
        positions={aid: engine.state.actors[aid].position.model_dump(mode='json') for aid in (OWNER, ALLY, FOE)},
        base_paces={aid: 15840 for aid in (OWNER, ALLY, FOE)})
    cold = CombatService(ROOT, tmp_path).journeys.load(state['journey_id'])
    context = JourneyAssetContext(cold)
    assert [fragility(context.state.objects[f'object:map.{i}']) for i in range(1, 5)] == expected
    assert [has_tag(context.state.objects[f'object:map.{i}'], 'fragile') for i in range(1, 5)] == expected


@pytest.mark.parametrize('change,expected', [
    ({}, True),
    ({'destroyed': True}, False),
    ({'owner_id': 'other'}, False),
    ({'kind': 'structure'}, False),
    ({'record_owner': 'other'}, False),
    ({'record_source': 'other'}, False),
    ({'lifetime': ''}, False),
    ({'lifetime': 1}, False),
    ({'override': False}, False),
    ({'override': True, 'lifetime': ''}, True),
])
def test_lifetime_classification_contract_is_owner_source_and_type_bound(change, expected):
    """Pure public-contract guard only; this is not native acquisition proof."""
    from types import SimpleNamespace
    from combat.asset_anchor_runtime import lifetime_reference
    component = {'created_by': 'source:contract-guard', 'asset_anchor_runtime': {
        'owner': change.get('record_owner', 'owner'),
        'source': change.get('record_source', 'source:contract-guard'),
        'lifetime': change.get('lifetime', 'condition:contract-guard')}}
    if 'override' in change:
        component['temporary_barrier'] = change['override']
    obj = SimpleNamespace(component=component, object_kind=change.get('kind', 'barrier'),
        owner_id=change.get('owner_id', 'owner'), destroyed=change.get('destroyed', False))
    assert has_tag(obj, 'temporary_barrier') is expected
    if 'override' not in change and change.get('kind', 'barrier') == 'barrier':
        assert (lifetime_reference(obj) is not None) is expected

"""Open Channels composes with settled damage-reduction support after reload."""
import pytest

from tests.test_a2_foundations3 import add_action, owner_bundle, pool
from tests.worker2_support import OWNER, ALLY, FOE, candidate, fixture, reload, settle, turn


@pytest.mark.parametrize('stage,ally_x,expected', [
    ('Refined', 12, 1), ('Awakened', 12, 0), ('Refined', 16, 0),
])
def test_open_channels_keeps_native_reduction_generation(tmp_path, stage, ally_x, expected):
    """The merged receipt path credits only the owning Foundation's reach.

    The scenario's reaction independently reaches 120 feet; the Foundation
    must not widen that reaction or credit its attacker as the beneficiary.
    """
    source = 'test:open_channels.reduction'

    def delivery(bundles):
        bundles[0]['typed_reactions'].append({
            'block': 'generic', 'kind': 'ally_damaged', 'feature_id': source,
            'name': 'Protect ally', 'range_ft': 120, 'costs': [],
            'effects': [{'type': 'damage_modifier', 'flat': 3, 'applies_to': 'ally'}],
        })
        add_action(bundles[2], 'Enemy pressure', [{
            'type': 'attack', 'attack_kind': 'weapon', 'on_hit': [{
                'type': 'damage', 'flat': 10, 'damage_types': ['force'],
                'applies_to': 'target',
            }],
        }], bonus=100)

    def battlefield(arena):
        arena['terrain_regions'] = [r for r in arena['terrain_regions']
                                    if r['region_id'] != 'pillar.centre']

    combat, table, mid = fixture(
        tmp_path, [], seed='OPEN-CHANNELS-MERGE',
        owner_bundle=owner_bundle('spirit', initial=0, stage=stage),
        bundle_transform=delivery, battlefield_transform=battlefield,
        ally_position={'x': ally_x, 'y': 6}, foe_position={'x': ally_x, 'y': 8},
    )
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Enemy pressure', target=ALLY).candidate_id,
           picks={'reaction:' + source: 'first'})
    engine = reload(tmp_path, mid)
    receipt = next(e for e in engine.events if e.event_type == 'REACTION_RESOLVED'
                   and e.source_definition_id == source)
    assert receipt.actor_id == OWNER
    assert receipt.payload['protects'] == ALLY
    assert receipt.payload['pending_before'] - receipt.payload['pending_after'] == 3
    assert engine.state.actors[OWNER].resources[pool('spirit')] == expected

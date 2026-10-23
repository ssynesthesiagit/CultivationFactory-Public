"""Sanctuary entry is a live membership trigger, not an activation-only pulse."""
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, settle, turn, reload

BASE = 'tianxia.subpath.qi.hearthfire_cultivator.feature.'
WELCOME = BASE + 'flame_that_welcomes_all'



def test_late_entry_receives_one_chosen_recovery_and_reentry_does_not_repeat(tmp_path):
    from combat.tabletop import normalize_map, to_battlefield
    battlefield = to_battlefield(normalize_map({'display_name': 'Open sanctuary',
        'width_squares': 20, 'height_squares': 14, 'walls': [], 'objects': []}))
    combat, table, mid = fixture(tmp_path, [], cl=18, owner_pb=6,
        owner_features=[BASE + 'homefire_recovery', WELCOME], battlefield=battlefield,
        positions={OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 12, 'y': 6}, FOE: {'x': 15, 'y': 8}})
    choices = {'choice:needle.welcome_recipients': [OWNER, ALLY],
               'choice:needle.homefire_recovery': 'temp_hp'}
    settle(table, mid, candidate(combat, mid, 'Flame That Welcomes All').candidate_id, choices=choices)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[ALLY].temporary_hp == 0, 'a chosen ally outside receives no benefit yet'
    turn(table, mid, ALLY)
    engine = reload(tmp_path, mid)
    row = next(c for c in engine.legal_candidates() if c.kind.value == 'MOVE' and c.destination
               and (c.destination.x, c.destination.y) == (11, 6))
    from combat.spatial_areas import zone_contains
    zone = next(z for z in engine.state.zones.values() if z.active and z.trigger_profile.get('profile', {}).get('welcoming_flame'))
    assert zone_contains(engine, engine.state.actors[ALLY], zone, at=row.destination), 'the intended entry must have a clear line of effect'
    prompts = settle(table, mid, row.candidate_id, choices=choices)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[ALLY].temporary_hp == 12
    assert any(p['context']['reactor_id'] == ALLY for p in prompts)
    count = sum(e.event_type == 'PASSIVE_TRIGGERED' and e.payload.get('receipt_kind') == 'homefire_recovery'
                and ALLY in e.target_ids for e in engine.events)
    assert count == 1
    for point in ((12, 6), (11, 6)):
        engine = reload(tmp_path, mid)
        row = next(c for c in engine.legal_candidates() if c.kind.value == 'MOVE' and c.destination
                   and (c.destination.x, c.destination.y) == point)
        settle(table, mid, row.candidate_id, choices=choices)
    engine = reload(tmp_path, mid)
    assert sum(e.event_type == 'PASSIVE_TRIGGERED' and e.payload.get('receipt_kind') == 'homefire_recovery'
               and ALLY in e.target_ids for e in engine.events) == 1


def test_environmental_condition_still_applies_with_sanctuary_save_advantage(tmp_path):
    """Advantage improves an environmental save; it is not immunity to its effect."""
    from combat.canonical import canonical_sha256

    def add_environmental_probe(bundles):
        bundle = bundles[0]
        source = 'action:test.hearthfire.environmental_probe'
        bundle['action_catalog'].append({
            'source_definition_id': source, 'display_name': 'Bitter Wind', 'owner_id': OWNER,
            'economy': 'NONE', 'resolution_kind': 'TYPED', 'target_kind': 'ANY_CREATURE',
            'range_ft': 60, 'parameters': {'free_primary': True, 'typed': {
                'source': source,
                'numbers': {'save_dc': 50}, 'duration': {'kind': 'instant'},
                'effects': [{'type': 'save', 'applies_to': 'target', 'ability': 'con',
                    'save_categories': ['environmental_cold'],
                    'on_fail': [{'type': 'condition', 'condition': 'mark.cold_exposure',
                        'applies_to': 'target', 'save_categories': ['environmental_cold'], 'expires_on': 'UNTIL_REMOVED',
                        'condition_data': {'label': 'Cold exposure'}}],
                    'on_success': []}],
            }},
        })
        bundle['actor_template']['action_ids'].append(source)
        bundle.pop('bundle_sha256', None)
        bundle['bundle_sha256'] = canonical_sha256(bundle)

    combat, table, mid = fixture(tmp_path, [], cl=18, owner_features=[WELCOME],
        bundle_transform=add_environmental_probe)
    choices = {'choice:needle.welcome_recipients': [OWNER, ALLY]}
    settle(table, mid, candidate(combat, mid, 'Flame That Welcomes All').candidate_id,
           choices={**choices, 'choice:needle.welcome_center': ['self']})
    engine = reload(tmp_path, mid)
    row = candidate(combat, mid, 'Bitter Wind', target=ALLY)
    settle(table, mid, row.candidate_id)
    engine = reload(tmp_path, mid)
    assert any(c.condition_id.endswith('mark.cold_exposure')
               for c in engine.state.actors[ALLY].conditions.values()), 'the failing environmental save must apply its condition'
    save = next(e for e in reversed(engine.events) if e.event_type == 'SAVE_ROLLED' and e.actor_id == ALLY)
    assert save.payload['mode'] == 'ADVANTAGE'

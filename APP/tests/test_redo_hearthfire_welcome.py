"""Sanctuary entry is a live membership trigger, not an activation-only pulse."""
from combat.canonical import canonical_sha256
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


def add_ordinary_probes(bundles):
    """Test-only ordinary environmental hazards: one save, one direct condition.

    ``ordinary_environmental`` is the table's own marker for an ordinary exposure
    (the same key the ordinary-penalty classification stores on condition data);
    a creature ability delivering the same cold is not marked and stays supernatural.
    """
    bundle = bundles[0]
    for name, effects in {
            'Ordinary Cold Snap': [{'type': 'save', 'applies_to': 'target', 'ability': 'con',
                'save_categories': ['environmental_cold'], 'ordinary_environmental': True,
                'on_fail': [{'type': 'condition', 'condition': 'mark.cold_exposure',
                    'applies_to': 'target', 'expires_on': 'UNTIL_REMOVED',
                    'condition_data': {'label': 'Cold exposure'}}],
                'on_success': []}],
            'Ordinary Smoke': [{'type': 'condition', 'applies_to': 'target',
                'condition': 'mark.smoke_penalty', 'expires_on': 'UNTIL_REMOVED',
                'condition_data': {'ordinary_environmental': 1, 'environmental_cause': 'smoke',
                    'label': 'Smoke: movement reduced by 5 feet'}}],
    }.items():
        source = 'action:test.hearthfire.' + name.lower().replace(' ', '_')
        bundle['action_catalog'].append({
            'source_definition_id': source, 'display_name': name, 'owner_id': OWNER,
            'economy': 'NONE', 'resolution_kind': 'TYPED', 'target_kind': 'ANY_CREATURE',
            'range_ft': 60, 'parameters': {'free_primary': True, 'typed': {
                'source': source, 'numbers': {'save_dc': 50}, 'duration': {'kind': 'instant'},
                'effects': effects}}})
        bundle['actor_template']['action_ids'].append(source)
    bundle.pop('bundle_sha256', None)
    bundle['bundle_sha256'] = canonical_sha256(bundle)


def test_ordinary_environmental_hazards_do_not_affect_protected_allies(tmp_path):
    combat, table, mid = fixture(tmp_path, [], cl=18, owner_features=[BASE + 'homefire_recovery', WELCOME],
        bundle_transform=add_ordinary_probes)
    settle(table, mid, candidate(combat, mid, 'Flame That Welcomes All').candidate_id,
           choices={'choice:needle.welcome_recipients': [ALLY]})
    # The chosen ally is immune to the ordinary cold save and the ordinary smoke penalty.
    settle(table, mid, candidate(combat, mid, 'Ordinary Cold Snap', target=ALLY).candidate_id)
    settle(table, mid, candidate(combat, mid, 'Ordinary Smoke', target=ALLY).candidate_id)
    engine = reload(tmp_path, mid)
    ally = engine.state.actors[ALLY]
    assert not any(e.event_type == 'SAVE_ROLLED' and e.actor_id == ALLY for e in engine.events)
    assert not any(c.condition_id.endswith(('mark.cold_exposure', 'mark.smoke_penalty'))
                   for c in ally.conditions.values())
    # A creature outside the sanctuary is not immune: the same ordinary hazard still lands.
    settle(table, mid, candidate(combat, mid, 'Ordinary Cold Snap', target=FOE).candidate_id)
    engine = reload(tmp_path, mid)
    assert any(e.event_type == 'SAVE_ROLLED' and e.actor_id == FOE for e in engine.events)
    assert any(c.condition_id.endswith('mark.cold_exposure')
               for c in engine.state.actors[FOE].conditions.values())


def smoke_battlefield():
    """A real map with one shipped ordinary terrain row painted on the ground."""
    from combat.tabletop import normalize_map, to_battlefield
    return to_battlefield(normalize_map({'display_name': 'Smoke court', 'width_squares': 20,
        'height_squares': 14, 'materials': [{'material': 'terrain:dense wax smoke',
        'cells': [[4, 6], [5, 6], [6, 6]]}], 'starts': {'team1': [[3, 6]], 'team2': [[6, 6]]}}))


def test_shipped_ordinary_smoke_does_not_obscure_a_protected_ally(tmp_path):
    """The printed immunity reaches shipped content: Wax's dense smoke is printed
    "ordinary smoke once released" (combat/rules/terrain.json), so it does not blind
    a chosen ally, while it still blinds everyone else.
    """
    from combat import zones
    combat, table, mid = fixture(tmp_path, [], cl=18,
        owner_features=[BASE + 'homefire_recovery', WELCOME], battlefield=smoke_battlefield(),
        positions={OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 4, 'y': 6}, FOE: {'x': 6, 'y': 6}})
    engine = reload(tmp_path, mid)
    smoke = next(z for z in zones.map_zones(engine)
                 if z.trigger_profile.get('terrain') == ['dense wax smoke'])
    assert smoke.trigger_profile['obscured'] == 'heavy'
    assert (smoke.trigger_profile.get('visual') or {}).get('material') == 'smoke'
    ally, foe = engine.state.actors[ALLY], engine.state.actors[FOE]
    assert 'DISADVANTAGE' in zones.attack_modes(engine, ally, foe), 'ordinary smoke obscures everyone before the sanctuary'
    settle(table, mid, candidate(combat, mid, 'Flame That Welcomes All').candidate_id,
           choices={'choice:needle.welcome_recipients': [ALLY]})
    engine = reload(tmp_path, mid)
    ally, foe = engine.state.actors[ALLY], engine.state.actors[FOE]
    assert 'DISADVANTAGE' not in zones.attack_modes(engine, ally, foe), \
        'the printed immunity lifts ordinary smoke for the chosen ally'
    assert 'DISADVANTAGE' in zones.attack_modes(engine, foe, ally), \
        'the sanctuary does not clear the smoke for anyone else'


def add_wax_smoke_ground(bundles):
    """A table command that lays the shipped ordinary smoke terrain row."""
    bundle = bundles[0]
    # A real technique-source prefix, so the area is supernatural unless the
    # shipped terrain row's ordinary flag reaches it (combat/ext/darkness_scope.py).
    source = 'action:typed.test.wax.smoke_ground'
    bundle['action_catalog'].append({'source_definition_id': source, 'display_name': 'Smoke Puff',
        'owner_id': OWNER, 'economy': 'NONE', 'resolution_kind': 'TYPED', 'target_kind': 'SELF',
        'parameters': {'free_primary': True, 'typed': {'source': source,
            'numbers': {'save_dc': 50}, 'duration': {'kind': 'instant'},
            'effects': [{'type': 'terrain_patch', 'terrain': 'dense wax smoke', 'radius_ft': 10}]}}})
    bundle['actor_template']['action_ids'].append(source)
    bundle.pop('bundle_sha256', None)
    bundle['bundle_sha256'] = canonical_sha256(bundle)


def test_ability_made_ordinary_smoke_is_classified_ordinary(tmp_path):
    """The shipped terrain row's ordinary flag reaches the area an ability makes."""
    from combat import zones
    from combat.ext.darkness_scope import scope
    combat, table, mid = fixture(tmp_path, [], cl=18,
        owner_features=[BASE + 'homefire_recovery', WELCOME], bundle_transform=add_wax_smoke_ground)
    settle(table, mid, candidate(combat, mid, 'Smoke Puff').candidate_id)
    engine = reload(tmp_path, mid)
    zone = next(z for z in zones.typed_zones(engine)
                if z.trigger_profile.get('terrain') == ['dense wax smoke'])
    assert zone.trigger_profile['obscured'] == 'heavy'
    assert scope(engine, zone) == 'ordinary', 'printed ordinary smoke must stay ordinary when an ability makes it'


def test_environmental_condition_still_applies_with_sanctuary_save_advantage(tmp_path):
    """Advantage improves an environmental save; it is not immunity to its effect."""
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

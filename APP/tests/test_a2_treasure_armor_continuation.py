"""Armor provenance boundaries through table transactions and cold replay."""
import pytest
from combat import canonical
from tests.test_a2_treasure_armor_enhancements import kit, sealed_effects
from tests.worker2_support import fixture, reload, candidate, settle, turn, OWNER, FOE, ALLY, sealed_native_attack


@pytest.mark.parametrize('delivery,feet,exception,expected', [
    ('native', 30, None, 'DISADVANTAGE'), ('typed', 30, None, 'DISADVANTAGE'),
    ('native', 25, None, 'NORMAL'), ('typed', 25, None, 'NORMAL'),
    ('native', 30, 'siege_weapon', 'NORMAL'), ('typed', 30, 'siege_weapon', 'NORMAL'),
    ('native', 30, 'ignore_cover', 'NORMAL'), ('typed', 30, 'ignore_cover', 'NORMAL'),
    ('spell', 30, None, 'NORMAL'),
])
def test_iron_rain_actual_delivery_and_exceptions(tmp_path, delivery, feet, exception, expected):
    def transform(bundles):
        bundle = bundles[2]
        if delivery == 'native':
            source = sealed_native_attack(bundle, 'Ranged Strike', count=1, sides=2, modifier=0, attack_bonus=100)
            action = next(a for a in bundle['action_catalog'] if a['source_definition_id'] == source)
            action['parameters'] = {'attack_kind': 'weapon_ranged', **({exception: True} if exception else {})}
        else:
            effect = {'type': 'attack', 'attack_kind': 'weapon_ranged' if delivery == 'typed' else 'spell_ranged',
                      'count': 1, 'on_hit': [{'type': 'damage', 'dice': {'count': 1, 'sides': 2}, 'damage_types': ['FIRE']}],
                      **({exception: True} if exception else {})}
            sealed_effects(bundle, 'Ranged Strike', [effect])
            bundle['action_catalog'][-1]['parameters']['typed']['range_ft'] = 60
        bundle.pop('bundle_sha256', None)
        bundle['bundle_sha256'] = canonical.canonical_sha256(bundle)
    combat, table, mid = fixture(tmp_path, [], owner_kit={'starting_kit': kit('iron_rain_deflection')},
        owner_ac=10, bundle_transform=transform, foe_position={'x': 3 + feet // 5, 'y': 6},
        ally_position={'x': 3, 'y': 10}, seed='ARMOR-IRON-RAIN',
        battlefield_transform=lambda arena: arena.update(terrain_regions=[]))
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Ranged Strike', target=OWNER).candidate_id)
    engine = reload(tmp_path, mid)
    rolls = [e for e in engine.events if e.event_type == 'ATTACK_ROLLED' and e.actor_id == FOE]
    assert rolls[-1].payload['mode'] == expected


@pytest.mark.parametrize('kind,condition,categories,supernatural', [
    ('spirit_guarding_hood', 'charmed', [], False),
    ('spirit_guarding_hood', 'frightened', [], False),
    ('poison_filtering_collar', 'poisoned', ['inhalation'], False),
    ('meridian_clear_underlayer', 'dazed', ['resource_suppression'], False),
    ('anti_corrosion_temper', 'dazed', ['armor_corrosion'], False),
    ('law_resisting_seal_plates', 'dazed', [], True),
])
def test_armor_protection_survives_native_condition_repeat(tmp_path, kind, condition, categories, supernatural):
    def transform(bundles):
        sealed_effects(bundles[2], 'Repeating Save', [{'type': 'save', 'ability': 'wis', 'save_categories': categories,
            'on_fail': [{'type': 'condition', 'condition': condition, 'duration': 'one_minute',
                         'repeat_save': {'ability': 'WIS', 'when': 'end'}}]}], supernatural=supernatural)
        bundles[2]['action_catalog'][-1]['parameters']['typed']['numbers']['save_dc'] = 100
        bundles[2].pop('bundle_sha256', None)
        bundles[2]['bundle_sha256'] = canonical.canonical_sha256(bundles[2])
    combat, table, mid = fixture(tmp_path, [], owner_kit={'starting_kit': kit(kind)}, owner_ac=10,
                                bundle_transform=transform, seed='ARMOR-REPEAT')
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Repeating Save', target=OWNER).candidate_id)
    engine = reload(tmp_path, mid)
    held = next(c for c in engine.state.actors[OWNER].conditions.values() if c.condition_id.endswith('.' + condition))
    if categories:
        assert held.data['repeat_save']['named'] == ['category:' + tag for tag in categories]
    turn(table, mid, OWNER)
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    engine = reload(tmp_path, mid)
    rolls = [e for e in engine.events if e.event_type == 'SAVE_ROLLED' and e.actor_id == OWNER]
    assert len(rolls) >= 2
    assert rolls[-1].payload['mode'] == 'ADVANTAGE'


@pytest.mark.parametrize('ignore', [False, True])
def test_force_circuit_honors_actual_source_penetration(tmp_path, ignore):
    def transform(bundles):
        source = sealed_native_attack(bundles[2], 'Force Strike', damage_type='FORCE', count=1, sides=2,
                                     modifier=30, attack_bonus=100)
        action = next(a for a in bundles[2]['action_catalog'] if a['source_definition_id'] == source)
        if ignore:
            bundles[2]['typed_passives'].append({'block': 'defense', 'kind': 'ignore_resistance',
                'feature_id': 'test:force_penetration', 'damage_types': ['FORCE'], 'attack_kinds': []})
        bundles[2].pop('bundle_sha256', None)
        bundles[2]['bundle_sha256'] = canonical.canonical_sha256(bundles[2])
    combat, table, mid = fixture(tmp_path, [], owner_kit={'starting_kit': kit('force_dispersal_circuit', 'heaven_veil_imperial_robe')},
                                owner_ac=10, owner_pb=5, bundle_transform=transform, seed='ARMOR-PENETRATION')
    turn(table, mid, FOE)
    before = reload(tmp_path, mid).state.actors[OWNER].current_hp
    settle(table, mid, candidate(combat, mid, 'Force Strike', target=OWNER).candidate_id)
    engine = reload(tmp_path, mid)
    total = [e.payload['total'] for e in engine.events if e.event_type == 'DAMAGE_ROLLED' and e.actor_id == FOE][-1]
    assert before - engine.state.actors[OWNER].current_hp == (total if ignore else total // 2 - 5)


@pytest.mark.parametrize('recipient,primary,decline,attack', [
    (OWNER, 'Qi', False, True), (ALLY, 'Qi', False, True),
    (ALLY, 'Stamina', False, True), (ALLY, 'Resonance', False, True),
    (FOE, 'Qi', False, True), (ALLY, 'Qi', True, True), (ALLY, 'Qi', False, False),
])
def test_deflecting_shield_recipient_payment_and_decline(tmp_path, recipient, primary, decline, attack):
    from combat.ext.cp_pools import of
    def transform(bundles):
        attacking = bundles[0] if recipient == FOE else bundles[2]
        if attack:
            sealed_native_attack(attacking, 'Heavy Strike', count=1, sides=2, modifier=35, attack_bonus=100)
        else:
            sealed_effects(attacking, 'Heavy Strike', [{'type': 'damage', 'dice': {'count': 1, 'sides': 2},
                                                      'flat': 35, 'damage_types': ['FIRE']}])
    treasure = kit('deflecting_shield_face')
    from tests.test_a2_treasure_armor_enhancements import AUTH
    treasure['resolved_treasure_armor']['chassis'] = next(r for r in AUTH['chassis'] if r['armor_category'] == 'shield')
    combat, table, mid = fixture(tmp_path, [], owner_kit={'starting_kit': treasure}, primary=primary,
        owner_pb=5, bundle_transform=transform, seed='ARMOR-DEFLECT',
        ally_position={'x': 4, 'y': 6}, foe_position={'x': 4, 'y': 7})
    if recipient != FOE:
        turn(table, mid, FOE)
    engine = reload(tmp_path, mid)
    pool = of(engine.state.actors[OWNER])
    assert pool == {'Qi': 'resource:core.qi', 'Stamina': 'resource:core.stamina', 'Resonance': 'resource:core.resonance'}[primary]
    hp, cp = engine.state.actors[recipient].current_hp, engine.state.actors[OWNER].resources[pool]
    prompts = settle(table, mid, candidate(combat, mid, 'Heavy Strike', target=recipient).candidate_id,
                     picks={'choice:needle.armor_deflect': None} if decline else None)
    engine = reload(tmp_path, mid)
    protected = recipient != FOE and attack and not decline
    rolls = [r for r in engine.rolls if r.reason == 'TREASURE_SHIELD_REDUCTION']
    assert bool(rolls) == protected
    assert engine.state.actors[OWNER].resources[pool] == cp - int(protected)
    assert engine.state.actors[OWNER].reaction_available is not protected
    reductions = [e.payload['reduction'] for e in engine.events if e.event_type == 'REACTION_RESOLVED'
                  and e.source_definition_id.endswith('.deflecting_shield_face')]
    assert sum(reductions) == (rolls[-1].total if protected else 0)
    damage = [e.payload['total'] for e in engine.events if e.event_type == 'DAMAGE_ROLLED'
              and recipient in e.target_ids][-1]
    assert hp - engine.state.actors[recipient].current_hp == damage - sum(reductions)


@pytest.mark.parametrize('recipient', [ALLY, FOE])
def test_automatic_deflect_protects_allies_never_enemies(tmp_path, recipient):
    def transform(bundles):
        sealed_native_attack(bundles[2] if recipient == ALLY else bundles[1], 'Heavy Strike',
                             count=1, sides=2, modifier=35, attack_bonus=100)
    from tests.test_a2_treasure_armor_enhancements import AUTH
    treasure = kit('deflecting_shield_face')
    treasure['resolved_treasure_armor']['chassis'] = next(r for r in AUTH['chassis'] if r['armor_category'] == 'shield')
    combat, table, mid = fixture(tmp_path, [], owner_kit={'starting_kit': treasure},
        owner_pb=5, bundle_transform=transform, seed='ARMOR-AUTO-DEFLECT',
        ally_position={'x': 4, 'y': 6}, foe_position={'x': 4, 'y': 7})
    turn(table, mid, FOE if recipient == ALLY else ALLY)
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    prompts = settle(table, mid, candidate(combat, mid, 'Heavy Strike', target=recipient).candidate_id)
    assert not any(p['context']['reaction_source_id'] == 'choice:needle.armor_deflect' for p in prompts)
    engine = reload(tmp_path, mid)
    reductions = [e for e in engine.events if e.event_type == 'REACTION_RESOLVED'
                  and e.source_definition_id.endswith('.deflecting_shield_face')]
    assert bool(reductions) == (recipient == ALLY)
    assert all(e.target_ids == (ALLY,) for e in reductions)

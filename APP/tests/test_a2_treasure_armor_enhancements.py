"""Equipped enhancements through compiled sheets, table commits and cold replay."""
import json
from pathlib import Path
import pytest
from combat import canonical
from tests.worker2_support import (fixture, reload, candidate, settle, turn, OWNER, FOE, ALLY, sealed_native_attack)

AUTH = json.loads((Path(__file__).parents[1] / 'authority/Tianxia_Treasure_Armor_Authority_R1.json').read_text())
ENH = {r['enhancement_id'].split('.')[-1]: r for r in AUTH['enhancements']}
ARMOR = next(r for r in AUTH['chassis'] if r['armor_category'] == 'heavy' and r['armor_class'] == '18')


def kit(*kinds, choices=None):
    rows = [{**ENH[k], **((choices or {}).get(k) or {})} for k in kinds]
    grade = max((r['minimum_grade'] for r in rows), key=AUTH['grade_order'].index)
    return {'items': [], 'resolved_treasure_armor': {'name': 'Test treasure armor', 'chassis': ARMOR,
            'enhancements': rows, 'grade': grade, 'refinement_bonus': AUTH['grades'][grade]['refinement_bonus']}}


def setup(tmp_path, *kinds, dtype='FIRE', amount=30, choices=None, seed='TREASURE-ARMOR', attack_bonus=100):
    def transform(bundles):
        sealed_native_attack(bundles[2], 'Test Strike', damage_type=dtype, count=1, sides=2, modifier=amount,
                             attack_bonus=attack_bonus)
    return fixture(tmp_path, [], owner_kit={'starting_kit': kit(*kinds, choices=choices)}, owner_ac=10, owner_pb=5,
                   bundle_transform=transform, seed=seed, ask=True)


def strike(combat, table, mid, tmp_path):
    turn(table, mid, FOE)
    before = reload(tmp_path, mid).state.actors[OWNER].current_hp
    c = candidate(combat, mid, 'Test Strike', target=OWNER)
    settle(table, mid, c.candidate_id)
    engine = reload(tmp_path, mid)
    rolled = [e.payload['total'] for e in engine.events if e.event_type == 'DAMAGE_ROLLED' and e.source_definition_id.startswith('action:test.native.')][-1]
    return before - engine.state.actors[OWNER].current_hp, engine, rolled


@pytest.mark.parametrize('kind,dtype,reduction', [
    ('fire_shedding_lining', 'FIRE', 5), ('frost_shedding_lining', 'COLD', 5),
    ('lightning_grounding_mesh', 'LIGHTNING', 5), ('force_dispersal_circuit', 'FORCE', 15),
    ('heaven_veil_imperial_robe', 'FORCE', 15), ('mountain_pattern_fortress', 'FIRE', 5),
    ('elemental_resistance_weave', 'ACID', 15), ('sovereign_resistance_matrix', 'PSYCHIC', 15),
])
def test_damage_properties_table_reload(tmp_path, kind, dtype, reduction):
    choices = {kind: {'damage_types': [dtype, 'NECROTIC']}}
    combat, table, mid = setup(tmp_path, kind, dtype=dtype, choices=choices)
    damage, engine, rolled = strike(combat, table, mid, tmp_path)
    assert damage == (rolled // 2 if reduction == 15 else rolled - reduction)
    assert any(r.get('kind') == kind for r in engine.typed_passive_rows[OWNER])


def test_lining_reduces_after_resistance(tmp_path):
    combat, table, mid = setup(tmp_path, 'fire_shedding_lining', 'elemental_resistance_weave',
        choices={'elemental_resistance_weave': {'damage_types': ['FIRE']}})
    damage, _, rolled = strike(combat, table, mid, tmp_path)
    assert damage == rolled // 2 - 5


def test_fire_lining_reduction_names_source_and_amount_in_journal_and_log(tmp_path):
    from combat.history_feed import format_history_feed
    combat, table, mid = setup(tmp_path, 'fire_shedding_lining', amount=10)
    damage, engine, rolled = strike(combat, table, mid, tmp_path)
    receipt = next(e for e in engine.events if e.event_type == 'REACTION_RESOLVED'
                   and e.source_definition_id.endswith('fire_shedding_lining'))
    assert receipt.payload['reduction'] == 5
    events = [e.model_dump(mode='json') for e in engine.events]
    feed = format_history_feed(events, [], pre_state=None, post_state={'actors': {}},
        actor_names={OWNER: 'Tang'}, definition_names={receipt.source_definition_id: 'Fire-Shedding Lining'})
    assert any(row['summary'] == 'Fire-Shedding Lining reduced the fire damage by 5.' for row in feed)
    assert damage == rolled - 5


def test_non_matching_damage_type_is_not_reduced(tmp_path):
    combat, table, mid = setup(tmp_path, 'fire_shedding_lining', dtype='COLD', amount=10)
    damage, engine, rolled = strike(combat, table, mid, tmp_path)
    assert damage == rolled
    assert not [e for e in engine.events if e.event_type == 'REACTION_RESOLVED'
                and e.source_definition_id.endswith('fire_shedding_lining')]


def test_non_lining_flat_reduction_is_flattened_and_named(tmp_path, monkeypatch):
    from combat import ext
    from combat.history_feed import format_history_feed
    lining = list(ext._HOOKS['damage_reduction_sources'])
    def flat_plate(engine, target, damage_type, typed, source_actor_id):
        return [{'feature_id': 'test.flat_plate', 'amount': 3}] if str(damage_type).upper() == 'FIRE' else None
    monkeypatch.setitem(ext._HOOKS, 'damage_reduction_sources', [*lining, flat_plate])
    defenses = list(ext._HOOKS.get('damage_defenses', []))
    def coexisting_reduction(engine, target, damage_type, typed, source_actor_id):
        return [{'kind': 'reduction', 'damage_types': ['FIRE'], 'amount': 5,
                 'feature_id': 'test.unattributed_plate'}]
    monkeypatch.setitem(ext._HOOKS, 'damage_defenses', [*defenses, coexisting_reduction])
    combat, table, mid = setup(tmp_path, 'fire_shedding_lining', amount=10)
    damage, engine, rolled = strike(combat, table, mid, tmp_path)
    # A separate, unnamed defense consumes the capped reduction before the
    # lining can claim a player-facing receipt.
    assert damage == rolled - 5
    named = {e.source_definition_id: e.payload['reduction'] for e in engine.events
             if e.event_type == 'REACTION_RESOLVED' and e.payload.get('passive')}
    assert named.get('test.flat_plate') is None
    assert named.get(next(r['feature_id'] for r in engine.typed_passive_rows[OWNER]
                          if r.get('kind') == 'fire_shedding_lining')) is None


def test_fortress_retains_minimum_one_damage(tmp_path):
    combat, table, mid = setup(tmp_path, 'mountain_pattern_fortress', amount=2)
    damage, _, rolled = strike(combat, table, mid, tmp_path)
    assert damage == 1


def test_blood_seal_once_then_cold_reload(tmp_path):
    combat, table, mid = setup(tmp_path, 'blood_sealing_inner_layer', amount=70)
    damage, engine, rolled = strike(combat, table, mid, tmp_path)
    assert engine.state.actors[OWNER].current_hp == 1
    assert any(c.condition_id == 'condition:typed.treasure_blood_seal_spent' for c in engine.state.actors[OWNER].conditions.values())


def test_unattuned_armor_does_not_publish_enhancements(tmp_path):
    from combat.factory_compiler import compile_character
    from tests.h1_support import sheet
    doc = sheet([], kit={'starting_kit': kit('fire_shedding_lining')})
    bundle = compile_character(doc, actor_id=OWNER, attuned=[])
    assert not any(r.get('block') == 'treasure_armor' for r in bundle['typed_passives'])


def sealed_effects(bundle, name, effects, *, target_kind='HOSTILE_ENTITY', supernatural=False):
    from combat.gate2_runtime_models import ActionDefinition
    source = 'action:test.treasure.' + bundle['actor_id'].split('.')[-1] + '.' + name.lower().replace(' ', '_')
    action = ActionDefinition(source_definition_id=source, display_name=name, owner_id=bundle['actor_id'],
        economy='ACTION', resolution_kind='TYPED', target_kind=target_kind, range_ft=60,
        parameters={'typed': {'source': source, 'effects': effects, 'riders': [],
                             'numbers': {'pb': 5, 'save_dc': 18, 'attack_bonus': 100},
                             'supernatural': supernatural, 'duration': {'kind': 'instant'}}})
    bundle['action_catalog'].append(action.model_dump(mode='json'))
    bundle['actor_template']['action_ids'].append(source)
    bundle.pop('bundle_sha256', None)
    bundle['bundle_sha256'] = canonical.canonical_sha256(bundle)


@pytest.mark.parametrize('kind,condition,categories,supernatural', [
    ('spirit_guarding_hood', 'charmed', [], False),
    ('spirit_guarding_hood', 'frightened', [], False),
    ('poison_filtering_collar', 'poisoned', ['inhalation'], False),
    ('meridian_clear_underlayer', 'dazed', ['resource_suppression'], False),
    ('anti_corrosion_temper', 'dazed', ['armor_corrosion'], False),
    ('law_resisting_seal_plates', 'dazed', [], True),
])
def test_scoped_save_properties_table_reload(tmp_path, kind, condition, categories, supernatural):
    def transform(bundles):
        sealed_effects(bundles[2], 'Test Save', [{'type': 'save', 'ability': 'wis', 'save_categories': categories,
            'on_fail': [{'type': 'condition', 'condition': condition, 'duration': 'until_end_of_turn'}]}], supernatural=supernatural)
    combat, table, mid = fixture(tmp_path, [], owner_kit={'starting_kit': kit(kind)}, owner_ac=10,
                                bundle_transform=transform, seed='ARMOR-SAVE', ask=True)
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Test Save', target=OWNER).candidate_id)
    engine = reload(tmp_path, mid)
    rolled = [e for e in engine.events if e.event_type == 'SAVE_ROLLED' and e.actor_id == OWNER][-1]
    assert rolled.payload['mode'] == 'ADVANTAGE'


def test_poison_filter_does_not_protect_contact_poison(tmp_path):
    def transform(bundles):
        sealed_effects(bundles[2], 'Contact Poison', [{'type': 'save', 'ability': 'con',
            'on_fail': [{'type': 'condition', 'condition': 'poisoned', 'duration': 'until_end_of_turn'}]}])
    combat, table, mid = fixture(tmp_path, [], owner_kit={'starting_kit': kit('poison_filtering_collar')},
                                owner_ac=10, bundle_transform=transform, seed='ARMOR-CONTACT')
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Contact Poison', target=OWNER).candidate_id)
    engine = reload(tmp_path, mid)
    rolled = [e for e in engine.events if e.event_type == 'SAVE_ROLLED' and e.actor_id == OWNER][-1]
    assert rolled.payload['mode'] == 'NORMAL'


def test_thorns_answer_melee_hit_only(tmp_path):
    def transform(bundles):
        sealed_native_attack(bundles[2], 'Melee Strike', damage_type='SLASHING', count=1, sides=2, modifier=1,
                             range_ft=None, attack_bonus=100)
    combat, table, mid = fixture(tmp_path, [], owner_kit={'starting_kit': kit('thorn_retaliation_plates')},
        owner_ac=10, owner_pb=5, bundle_transform=transform, foe_position={'x': 4, 'y': 6}, ally_position={'x': 4, 'y': 7})
    turn(table, mid, FOE)
    before = reload(tmp_path, mid).state.actors[FOE].current_hp
    settle(table, mid, candidate(combat, mid, 'Melee Strike', target=OWNER).candidate_id)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[FOE].current_hp == before - 5
    assert engine.state.actors[ALLY].current_hp == 60


@pytest.mark.parametrize('poisoned', [False, True])
def test_silent_lacing_table_hide_and_reload(tmp_path, poisoned):
    def transform(bundles):
        effects = [{'type': 'condition', 'condition': 'blinded', 'duration': 'one_minute'}]
        if poisoned:
            effects.append({'type': 'condition', 'condition': 'poisoned', 'applies_to': 'self', 'duration': 'one_minute'})
        sealed_effects(bundles[0], 'Block Fixture Sight', effects)
    combat, table, mid = fixture(tmp_path, [], owner_kit={'starting_kit': kit('silent_lacing')},
                                owner_ac=10, bundle_transform=transform)
    settle(table, mid, candidate(combat, mid, 'Block Fixture Sight', target=FOE).candidate_id)
    turn(table, mid, OWNER)
    # Advance off the spent Action before attempting the actual Hide check.
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    turn(table, mid, OWNER)
    settle(table, mid, candidate(combat, mid, 'Hide').candidate_id)
    engine = reload(tmp_path, mid)
    check = [e for e in engine.events if e.event_type == 'CHECK_ROLLED' and e.actor_id == OWNER][-1]
    assert check.payload['actor']['mode'] == ('DISADVANTAGE' if poisoned else 'NORMAL')


def test_dark_visor_reaches_sixty_feet_after_reload(tmp_path):
    from combat import senses
    combat, table, mid = fixture(tmp_path, [], owner_kit={'starting_kit': kit('dark_sight_visor')}, owner_ac=10)
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    engine = reload(tmp_path, mid)
    owner_bundle = next(b for b in engine.typed_bundle_documents if b['actor_id'] == OWNER)
    assert any(r['sense'] == 'darkvision' and r['range_ft'] == 60 and r['or_add_ft'] == 30 for r in owner_bundle['senses']['rows'])
    assert senses.of(engine, engine.state.actors[OWNER])['darkvision']['range_ft'] == 60


def test_helmet_cancels_only_first_critical_after_reload(tmp_path):
    def transform(bundles):
        sealed_effects(bundles[0], 'Critical Setup', [{'type': 'condition', 'condition': 'paralyzed',
            'applies_to': 'self', 'duration': 'one_minute'}], target_kind='SELF')
        sealed_native_attack(bundles[2], 'Close Strike', damage_type='SLASHING', count=1, sides=2, modifier=5,
                             range_ft=None, attack_bonus=100, attacks=2)
    combat, table, mid = fixture(tmp_path, [], owner_kit={'starting_kit': kit('helmet_seal_inscription')},
        owner_ac=10, bundle_transform=transform, ask=False, seed='ARMOR-HELMET',
        foe_position={'x': 4, 'y': 6}, ally_position={'x': 4, 'y': 7})
    settle(table, mid, candidate(combat, mid, 'Critical Setup').candidate_id)
    turn(table, mid, FOE)
    prompts = settle(table, mid, candidate(combat, mid, 'Close Strike', target=OWNER).candidate_id)
    engine = reload(tmp_path, mid)
    assert len([p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.treasure_helmet']) == 1
    criticals = [e.payload for e in engine.events if e.event_type == 'ATTACK_CRITICAL_RESOLVED' and OWNER in e.target_ids]
    assert criticals[0]['cancelled'] is True
    assert criticals[-1]['critical'] is True


def test_force_circuit_adds_reduction_when_another_property_resists(tmp_path):
    combat, table, mid = setup(tmp_path, 'force_dispersal_circuit', 'heaven_veil_imperial_robe', dtype='FORCE')
    damage, _, rolled = strike(combat, table, mid, tmp_path)
    assert damage == rolled // 2 - 5


def test_weightless_harness_sheet_and_table_reload(tmp_path):
    combat, table, mid = fixture(tmp_path, [], owner_kit={'starting_kit': kit('weightless_harness')}, owner_ac=10)
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    engine = reload(tmp_path, mid)
    bundle = next(b for b in engine.typed_bundle_documents if b['actor_id'] == OWNER)
    item = next(r for r in bundle['carrying']['items'] if r['key'] == 'treasure_armor')
    assert item['weight_lb'] == '32.5'
    assert bundle['carrying']['speed_ft'] == 30
    assert engine.state.actors[OWNER].speed_ft == 30


@pytest.mark.parametrize('kind', ['featherfall_skirt', 'padded_impact_layers'])
def test_armor_falling_properties_table_reload(tmp_path, kind):
    def transform(bundles):
        bundles[0]['actor_template']['fly_speed_ft'] = 30
        sealed_effects(bundles[0], 'Lose Flight Control', [{'type': 'condition', 'condition': 'restrained',
            'applies_to': 'self', 'duration': 'one_minute'}], target_kind='SELF')
    combat, table, mid = fixture(tmp_path, [], owner_kit={'starting_kit': kit(kind)}, owner_ac=10, owner_pb=5,
        bundle_transform=transform, positions={OWNER: {'x': 3, 'y': 6, 'z': 10}, ALLY: {'x': 4, 'y': 7}, FOE: {'x': 6, 'y': 6}},
        seed='ARMOR-FALL')
    settle(table, mid, candidate(combat, mid, 'Lose Flight Control').candidate_id)
    engine = reload(tmp_path, mid)
    actor = engine.state.actors[OWNER]
    assert actor.position.z == 0
    falls = [e for e in engine.events if e.event_type == 'DAMAGE_ROLLED' and e.source_definition_id == 'system:combat.falling']
    assert len(falls) == 1
    if kind == 'featherfall_skirt':
        assert len(falls[0].payload['dice']) == 2
        assert not any(c.condition_id.endswith('.prone') for c in actor.conditions.values())
    else:
        assert actor.current_hp == 60 - max(0, falls[0].payload['total'] - 5)


def test_shield_link_protects_allies_and_never_enemies(tmp_path):
    treasure = kit('shield_link_inscription')
    treasure['resolved_treasure_armor']['chassis'] = next(r for r in AUTH['chassis'] if r['armor_category'] == 'shield')
    def transform(bundles):
        sealed_native_attack(bundles[0], 'Owner Strike', damage_type='FIRE', modifier=1, count=1, sides=2, range_ft=60, attack_bonus=100)
        sealed_native_attack(bundles[2], 'Foe Strike', damage_type='FIRE', modifier=1, count=1, sides=2, range_ft=60, attack_bonus=100)
    combat, table, mid = fixture(tmp_path, [], owner_kit={'starting_kit': treasure},
        bundle_transform=transform, foe_position={'x': 4, 'y': 6}, ally_position={'x': 4, 'y': 7})
    settle(table, mid, candidate(combat, mid, 'Owner Strike', target=FOE).candidate_id)
    engine = reload(tmp_path, mid)
    enemy_roll = [e for e in engine.events if e.event_type == 'ATTACK_ROLLED' and FOE in e.target_ids][-1]
    assert enemy_roll.payload['cover_bonus'] == 0
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Foe Strike', target=ALLY).candidate_id)
    engine = reload(tmp_path, mid)
    ally_roll = [e for e in engine.events if e.event_type == 'ATTACK_ROLLED' and ALLY in e.target_ids][-1]
    assert ally_roll.payload['cover_bonus'] == 2


@pytest.mark.parametrize('escape_save', [False, True])
def test_grasp_breaking_plates_real_escape_after_reload(tmp_path, escape_save):
    def transform(bundles):
        sealed_effects(bundles[0], 'Escape Hold', [{'type': 'escape_grapple'}], target_kind='SELF')
        sealed_effects(bundles[2], 'Test Hold', [{'type': 'condition', 'condition': 'grappled', 'until_escape': True,
            'condition_data': {'reach_ft': 5, **({'escape_save': 'STR'} if escape_save else {})}}])
    combat, table, mid = fixture(tmp_path, [], owner_kit={'starting_kit': kit('grasp_breaking_plates')}, owner_ac=10,
        bundle_transform=transform, foe_position={'x': 4, 'y': 6}, ally_position={'x': 4, 'y': 7}, seed='ARMOR-GRASP')
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Test Hold', target=OWNER).candidate_id)
    assert any(c.condition_id.endswith('.grappled') for c in reload(tmp_path, mid).state.actors[OWNER].conditions.values())
    turn(table, mid, OWNER)
    settle(table, mid, candidate(combat, mid, 'Escape Hold').candidate_id)
    engine = reload(tmp_path, mid)
    event_type = 'SAVE_ROLLED' if escape_save else 'CHECK_ROLLED'
    rolled = [e for e in engine.events if e.event_type == event_type and e.actor_id == OWNER][-1]
    payload = rolled.payload if escape_save else rolled.payload['actor']
    assert payload['mode'] == 'ADVANTAGE'


def test_immovable_shell_blocks_forced_push_and_prone(tmp_path):
    def transform(bundles):
        sealed_effects(bundles[2], 'Prone and Push', [
            {'type': 'condition', 'condition': 'prone'},
            {'type': 'forced_movement', 'distance_ft': 10, 'direction': 'away'}])
    combat, table, mid = fixture(tmp_path, [], owner_kit={'starting_kit': kit('immovable_mountain_grand_shell')},
        owner_ac=10, bundle_transform=transform, foe_position={'x': 4, 'y': 6}, ally_position={'x': 4, 'y': 7})
    turn(table, mid, FOE)
    before = reload(tmp_path, mid).state.actors[OWNER].position
    settle(table, mid, candidate(combat, mid, 'Prone and Push', target=OWNER).candidate_id)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].position == before
    assert not any(c.condition_id.endswith('.prone') for c in engine.state.actors[OWNER].conditions.values())
    owner_bundle = next(b for b in engine.typed_bundle_documents if b['actor_id'] == OWNER)
    assert owner_bundle['carrying']['capacity_lb'] == 420


def test_dark_visor_adds_thirty_to_existing_darkvision(tmp_path):
    from combat import senses
    def transform(bundles):
        bundles[0]['senses']['rows'].insert(0, {'sense': 'darkvision', 'range_ft': 90,
                                              'when': 'always', 'feature_id': 'test:innate_darkvision'})
        bundles[0].pop('bundle_sha256', None)
        bundles[0]['bundle_sha256'] = canonical.canonical_sha256(bundles[0])
    combat, table, mid = fixture(tmp_path, [], owner_kit={'starting_kit': kit('dark_sight_visor')},
                                owner_ac=10, bundle_transform=transform)
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    engine = reload(tmp_path, mid)
    assert senses.of(engine, engine.state.actors[OWNER])['darkvision']['range_ft'] == 120


def test_blood_seal_is_spent_after_cold_reload(tmp_path):
    def transform(bundles):
        sealed_native_attack(bundles[2], 'Lethal Strike', damage_type='FIRE', count=1, sides=2,
                             modifier=70, attack_bonus=100)
        sealed_native_attack(bundles[2], 'Weak Strike', damage_type='FIRE', count=1, sides=2,
                             modifier=0, attack_bonus=100)
    combat, table, mid = fixture(tmp_path, [], owner_kit={'starting_kit': kit('blood_sealing_inner_layer')},
                                owner_ac=10, bundle_transform=transform, ask=False, seed='ARMOR-BLOOD-TWICE')
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Lethal Strike', target=OWNER).candidate_id)
    assert reload(tmp_path, mid).state.actors[OWNER].current_hp == 1
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    turn(table, mid, FOE)
    prompts = settle(table, mid, candidate(combat, mid, 'Weak Strike', target=OWNER).candidate_id)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].current_hp == 0
    assert not any(p['context']['reaction_source_id'] == 'choice:needle.treasure_blood_seal' for p in prompts)


def test_blood_seal_player_can_decline(tmp_path):
    combat, table, mid = setup(tmp_path, 'blood_sealing_inner_layer', amount=70, seed='ARMOR-BLOOD-DECLINE')
    turn(table, mid, FOE)
    prompts = settle(table, mid, candidate(combat, mid, 'Test Strike', target=OWNER).candidate_id,
                     picks={'choice:needle.treasure_blood_seal': None})
    engine = reload(tmp_path, mid)
    assert prompts
    assert engine.state.actors[OWNER].current_hp == 0
    assert not any(c.condition_id == 'condition:typed.treasure_blood_seal_spent' for c in engine.state.actors[OWNER].conditions.values())


def test_created_element_choice_is_recorded_by_prefight_form(tmp_path):
    from combat import ext
    def transform(bundles):
        forms = [r for group in ext.run('prefight_setup_choices', bundles[0]) for r in group]
        form = next(r for r in forms if r['id'] == 'armor_element_treasure_armor_elemental_resistance_weave')
        assert form['default'] == [0]
        bundles[0]['prefight']['setup_choices'] = {form['id']: [3]}  # alphabetic allowed types: Fire
        bundles[0].pop('bundle_sha256', None)
        bundles[0]['bundle_sha256'] = canonical.canonical_sha256(bundles[0])
        sealed_native_attack(bundles[2], 'Test Strike', damage_type='FIRE', count=1, sides=2,
                             modifier=30, attack_bonus=100)
    combat, table, mid = fixture(tmp_path, [], owner_kit={'starting_kit': kit('elemental_resistance_weave')},
                                owner_ac=10, bundle_transform=transform, seed='ARMOR-CREATION-CHOICE')
    damage, engine, rolled = strike(combat, table, mid, tmp_path)
    assert damage == rolled // 2
    assert any(c.condition_id == 'condition:typed.treasure_armor_element_choice' and c.data['damage_types'] == ['FIRE']
               for c in engine.state.actors[OWNER].conditions.values())


def test_thorns_retaliate_on_the_killing_hit_and_can_draw(tmp_path):
    from tests.h1_support import sheet
    foe_sheet = sheet([], cl=1)
    foe_sheet['ability_scores_and_statistics']['hit_points']['maximum'] = 2
    def transform(bundles):
        sealed_effects(bundles[0], 'Defeat Fixture Ally', [{'type': 'damage',
            'dice': {'count': 1, 'sides': 2}, 'flat': 200, 'damage_types': ['FORCE']}], target_kind='ANY_CREATURE')
        sealed_native_attack(bundles[2], 'Lethal Melee Strike', damage_type='SLASHING', count=1, sides=2,
                             modifier=150, range_ft=None, attack_bonus=100, attacks=2)
    combat, table, mid = fixture(tmp_path, [], owner_kit={'starting_kit': kit('thorn_retaliation_plates')},
        owner_ac=10, owner_pb=5, bundle_transform=transform, foe_sheet=foe_sheet, seed='ARMOR-THORNS-LETHAL',
        foe_position={'x': 4, 'y': 6}, ally_position={'x': 4, 'y': 7})
    settle(table, mid, candidate(combat, mid, 'Defeat Fixture Ally', target=ALLY).candidate_id)
    assert not reload(tmp_path, mid).state.actors[ALLY].active
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Lethal Melee Strike', target=OWNER).candidate_id)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].current_hp == 0
    assert engine.state.actors[FOE].current_hp == 0
    assert engine.state.terminal_result.kind.value == 'DRAW_SIMULTANEOUS'


@pytest.mark.parametrize('kind,quantity,expected_speed,expected_over', [
    ('weightless_harness', 8, 5, True), ('immovable_mountain_grand_shell', 4, 20, False),
])
def test_armor_mass_and_capacity_keep_encumbrance_consistent(tmp_path, kind, quantity, expected_speed, expected_over):
    treasure = kit(kind)
    treasure['items'] = [{'item_id': ARMOR['item_id'], 'quantity': quantity}]
    combat, table, mid = fixture(tmp_path, [], owner_kit={'starting_kit': treasure}, owner_ac=10)
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    engine = reload(tmp_path, mid)
    owner_bundle = next(b for b in engine.typed_bundle_documents if b['actor_id'] == OWNER)
    assert owner_bundle['carrying']['over'] == expected_over
    assert engine.state.actors[OWNER].speed_ft == expected_speed


def test_thorns_use_actual_typed_melee_delivery_not_selection_range(tmp_path):
    def transform(bundles):
        attack = next(a for a in bundles[2]['action_catalog'] if a['display_name'] == 'Unarmed Strike')
        attack['parameters']['typed']['numbers']['attack_bonus'] = 100
        # A technique may select a creature within 5 feet while its actual
        # attack is melee. The confirmed native spec owns delivery provenance.
        attack['parameters']['typed']['range_ft'] = 5
        bundles[2].pop('bundle_sha256', None)
        bundles[2]['bundle_sha256'] = canonical.canonical_sha256(bundles[2])
    combat, table, mid = fixture(tmp_path, [], owner_kit={'starting_kit': kit('thorn_retaliation_plates')},
        owner_ac=10, owner_pb=5, bundle_transform=transform,
        foe_position={'x': 4, 'y': 6}, ally_position={'x': 4, 'y': 7}, seed='ARMOR-THORNS-TYPED')
    turn(table, mid, FOE)
    before = reload(tmp_path, mid).state.actors[FOE].current_hp
    settle(table, mid, candidate(combat, mid, 'Unarmed Strike', target=OWNER).candidate_id)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[FOE].current_hp == before - 5

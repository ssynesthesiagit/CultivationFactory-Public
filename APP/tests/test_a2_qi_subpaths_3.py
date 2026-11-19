"""Qi subpath automation through real table intents, saved service and replay."""
import pytest

from combat.canonical import canonical_sha256
from combat.gate2_runtime_models import ActionDefinition, EconomyKind
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, settle, turn, reload

CYCLE = 'tianxia.subpath.qi.five_elements_cultivator.feature.world_cleansing_cycle'


def controls(bundles):
    for bundle in bundles:
        bundle['actor_template']['maximum_hp'] = 500
        aid = bundle['actor_id']
        for label, effect, target in [
            ('Test healing', {'type': 'healing', 'applies_to': 'self', 'flat': 10}, 'SELF'),
            ('Test Temporary HP', {'type': 'temp_hp', 'applies_to': 'self', 'flat': 10}, 'SELF'),
            ('Test double damage', {'type': 'damage', 'applies_to': 'target', 'flat': 10, 'damage_types': ['force']}, 'HOSTILE_ENTITY'),
            ('Test Prone save', {'type': 'save', 'applies_to': 'target', 'ability': 'str', 'dc': 'technique_save_dc',
                'on_fail': [{'type': 'condition', 'condition': 'prone', 'applies_to': 'target'}], 'on_success': []}, 'HOSTILE_ENTITY'),
            ('Test shared healing', {'type': 'healing', 'applies_to': 'self', 'flat': 10}, 'SELF')]:
            source = 'action:test.' + aid + '.' + label.replace(' ', '_')
            effects = [effect]
            if label == 'Test double damage':
                effects += [dict(effect)]
            if label == 'Test shared healing':
                effects += [{'type': 'temp_hp', 'applies_to': 'self', 'flat': 10}]
            action = ActionDefinition(source_definition_id=source, owner_id=aid, display_name=label,
                economy=EconomyKind.BONUS_ACTION, resolution_kind='TYPED', target_kind=target,
                range_ft=60, parameters={'typed': {'source': source, 'numbers': {'cl': 18, 'pb': 6, 'key_mod': 4, 'save_dc': 18},
                'effects': effects, 'riders': [], 'duration': {'kind': 'instant'}}})
            bundle['action_catalog'].append(action.model_dump(mode='json'))
            bundle['actor_template']['action_ids'].append(source)
        bundle.pop('bundle_sha256', None)
        bundle['bundle_sha256'] = canonical_sha256(bundle)


def fight(tmp_path, element, *, dc=18, movement_bonus=0):
    def prepare(bundles):
        controls(bundles)
        if movement_bonus:
            owner = next(b for b in bundles if b['actor_id'] == OWNER)
            owner['typed_passives'].append({'block': 'forced_movement_bonus',
                'feature_id': 'test:push_lengthening', 'abilities': [CYCLE], 'ft': movement_bonus})
            owner.pop('bundle_sha256')
            owner['bundle_sha256'] = canonical_sha256(owner)

    combat, table, mid = fixture(tmp_path, [], cl=18, seed='QI-CYCLE-' + element,
        owner_features=[CYCLE], bundle_transform=prepare, owner_pb=6, owner_dc=dc)
    settle(table, mid, candidate(combat, mid, 'World-Cleansing Cycle', at=(6, 6)).candidate_id,
           choices={'choice:needle.qi_cycle_start': element})
    engine = reload(tmp_path, mid)
    zone = next(z for z in engine.state.zones.values() if z.trigger_profile.get('qi_world_cycle'))
    assert zone.trigger_profile['qi_world_cycle'] == element
    assert engine.state.actors[OWNER].resources['resource:core.qi'] == 92
    assert zone.trigger_profile['height_ft'] == 40
    return combat, table, mid


@pytest.mark.parametrize('dc', [1, 100])
@pytest.mark.parametrize('element,damage_type', [('wood', 'PIERCING'), ('fire', 'FIRE'),
    ('earth', 'BLUDGEONING'), ('metal', 'SLASHING'), ('water', 'BLUDGEONING')])
def test_cycle_exposes_enemies_and_preserves_allies_after_reload(tmp_path, element, damage_type, dc):
    combat, table, mid = fight(tmp_path, element, dc=dc)
    before = reload(tmp_path, mid)
    allies = {a: before.state.actors[a].current_hp for a in [OWNER, ALLY]}
    turn(table, mid, FOE)
    after = reload(tmp_path, mid)
    packets = [e for e in after.events if e.event_type == 'DAMAGE_COMMITTED'
               and 'world_cleansing_cycle' in e.source_definition_id]
    assert packets and all(e.target_ids == (FOE,) for e in packets)
    assert all(e.payload['damage_type'] == damage_type for e in packets)
    assert all(after.state.actors[a].current_hp == hp for a, hp in allies.items())
    saves = [e for e in after.events if e.event_type == 'SAVE_ROLLED' and e.actor_id == FOE
             and 'world_cleansing_cycle' in e.source_definition_id]
    assert len(saves) == 1 and saves[0].payload['success'] == (dc == 1)
    expected = {'wood': 'restrained', 'fire': 'reaction_denied', 'earth': 'prone', 'metal': 'reaction_denied'}
    if element in expected and (dc == 100 or element == 'metal'):
        assert any(c.condition_id.endswith(expected[element]) for c in after.state.actors[FOE].conditions.values())
    if dc == 1:
        if element == 'fire':
            assert not any(c.condition_id.endswith('reaction_denied') for c in after.state.actors[FOE].conditions.values())
        if element == 'wood':
            assert any(m.target_field == 'speed_ft' and int(m.value) == -10
                       for m in after.state.actors[FOE].modifiers.values())
        if element == 'metal':
            reaction = next(c for c in after.state.actors[FOE].conditions.values()
                           if c.condition_id.endswith('reaction_denied'))
            assert reaction.expires_on == f"START_OF_TURN_AT:{FOE}:{after.state.actors[FOE].turns_started + 1}"
    elif element == 'metal':
        reaction = next(c for c in after.state.actors[FOE].conditions.values()
                        if c.condition_id.endswith('reaction_denied'))
        assert reaction.expires_on == f'END_OF_TURN_AT:{FOE}:2'


@pytest.mark.parametrize('element', ['wood', 'fire', 'earth', 'metal', 'water'])
def test_successful_element_save_commits_half_damage(tmp_path, element):
    totals = []
    for dc in (1, 100):
        combat, table, mid = fight(tmp_path / str(dc), element, dc=dc)
        turn(table, mid, FOE)
        engine = reload(tmp_path / str(dc), mid)
        packets = [e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED'
                   and 'world_cleansing_cycle' in e.source_definition_id and e.target_ids == (FOE,)]
        assert packets
        totals.append(sum(int(e.payload.get('hp_damage') or 0) for e in packets))
    assert totals[0] == totals[1] // 2


@pytest.mark.parametrize(('element', 'dc', 'effect_kind'), [
    ('wood', 100, 'condition:restrained'),
    ('wood', 1, 'modifier:speed_ft'),
    ('fire', 100, 'condition:reaction_denied'),
    ('metal', 1, 'condition:reaction_denied'),
])
def test_hostile_cycle_effect_survives_source_turn_then_expires_at_target_start(tmp_path, element, dc, effect_kind):
    combat, table, mid = fight(tmp_path, element, dc=dc)
    turn(table, mid, FOE)  # The effect is applied during the victim's turn-start zone exposure.
    active = reload(tmp_path, mid).state.actors[FOE]

    def has_effect(actor):
        if effect_kind.startswith('condition:'):
            wanted = effect_kind.split(':', 1)[1]
            return any(row.condition_id.endswith(wanted) for row in actor.conditions.values())
        field = effect_kind.split(':', 1)[1]
        return any(row.target_field == field and int(row.value) == -10 for row in actor.modifiers.values())

    assert has_effect(active)
    effect_rows = (active.conditions.values() if effect_kind.startswith('condition:')
                   else active.modifiers.values())
    row = next(row for row in effect_rows if has_effect(active) and
               (row.condition_id.endswith(effect_kind.split(':', 1)[1]) if effect_kind.startswith('condition:')
                else row.target_field == effect_kind.split(':', 1)[1]))
    if effect_kind.startswith('condition:'):
        assert row.source_actor_id == OWNER
        assert row.expires_on == f"START_OF_TURN_AT:{FOE}:{active.turns_started + 1}"
    else:
        # Ordinary modifiers persist the initiative actor as source. The native
        # source-turn token therefore names this victim, not the field's caster.
        assert row.source_actor_id == FOE
        assert row.expires_on == 'START_OF_SOURCE_NEXT_TURN'

    # The caster's intervening turn must not remove an effect anchored to the target.
    settle(table, mid, table.state(mid)['menu']['end_turn'])  # end victim turn
    turn(table, mid, OWNER)
    assert has_effect(reload(tmp_path, mid).state.actors[FOE])

    # Advance through ally initiative to the victim's next start; cold reload proves persisted expiry.
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    turn(table, mid, FOE)
    expired = reload(tmp_path, mid).state.actors[FOE]
    assert not has_effect(expired)


@pytest.mark.parametrize('first', ['Test healing', 'Test Temporary HP'])
def test_wood_first_healing_or_temporary_hp_shares_allowance(tmp_path, first):
    combat, table, mid = fight(tmp_path, 'wood')
    turn(table, mid, ALLY)
    settle(table, mid, candidate(combat, mid, first).candidate_id)
    engine = reload(tmp_path, mid)
    event_type = 'HEALING_APPLIED' if first == 'Test healing' else 'TEMP_HP_GRANTED'
    receipt = [e for e in engine.events if e.event_type == event_type and e.target_ids == (ALLY,)][-1]
    assert receipt.payload['offered'] == 22
    assert engine.state.actors[FOE].temporary_hp == 0


def test_cycle_advances_in_productive_order_and_reconciles_metal_ac(tmp_path):
    combat, table, mid = fight(tmp_path, 'earth')
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    turn(table, mid, OWNER)
    engine = reload(tmp_path, mid)
    zone = next(z for z in engine.state.zones.values() if z.trigger_profile.get('qi_world_cycle'))
    assert zone.trigger_profile['qi_world_cycle'] == 'metal'
    assert engine._ac_modifier(engine.state.actors[ALLY]) == 1
    assert engine._ac_modifier(engine.state.actors[FOE]) == 0
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    turn(table, mid, OWNER)
    engine = reload(tmp_path, mid)
    zone = next(z for z in engine.state.zones.values() if z.trigger_profile.get('qi_world_cycle'))
    assert zone.trigger_profile['qi_world_cycle'] == 'water'
    assert engine._ac_modifier(engine.state.actors[ALLY]) == 0


def test_fire_addition_once_on_allied_damage_and_not_enemy_damage(tmp_path):
    combat, table, mid = fight(tmp_path, 'fire')
    settle(table, mid, candidate(combat, mid, 'Test double damage', target=FOE).candidate_id)
    engine = reload(tmp_path, mid)
    extras = [e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED'
              and e.source_definition_id.startswith('action:typed.') and e.payload.get('damage_type') == 'FIRE']
    assert len(extras) == 1 and extras[0].target_ids == (FOE,)
    assert extras[0].payload['rolled_or_pending_damage'] == 6
    originals = [e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED'
                 and 'Test_double_damage' in e.source_definition_id]
    assert len(originals) == 2
    # A hostile's damage is not an ally benefiting from the owner's Fire field.
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Test double damage', target=OWNER).candidate_id)
    engine = reload(tmp_path, mid)
    enemy_extras = [e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED'
                    and e.source_definition_id.startswith('action:typed.')
                    and e.payload.get('damage_type') == 'FIRE' and e.actor_id == FOE]
    assert enemy_extras == []


def test_wood_consumes_one_shared_allowance_for_two_grants(tmp_path):
    combat, table, mid = fight(tmp_path, 'wood')
    turn(table, mid, ALLY)
    settle(table, mid, candidate(combat, mid, 'Test shared healing').candidate_id)
    engine = reload(tmp_path, mid)
    healing = [e for e in engine.events if e.event_type == 'HEALING_APPLIED' and e.target_ids == (ALLY,)][-1]
    temporary = [e for e in engine.events if e.event_type == 'TEMP_HP_GRANTED' and e.target_ids == (ALLY,)][-1]
    assert healing.payload['offered'] == 22
    assert temporary.payload['offered'] == 10


def test_earth_grants_advantage_on_a_real_hostile_prone_save(tmp_path):
    combat, table, mid = fight(tmp_path, 'earth')
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Test Prone save', target=ALLY).candidate_id)
    engine = reload(tmp_path, mid)
    saves = [e for e in engine.events if e.event_type == 'SAVE_ROLLED' and e.actor_id == ALLY]
    assert saves[-1].payload['mode'] == 'ADVANTAGE'


def test_scene_limit_prevents_recreating_the_field_after_reload(tmp_path):
    combat, table, mid = fight(tmp_path, 'wood')
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    turn(table, mid, OWNER)
    engine = reload(tmp_path, mid)
    assert not any(getattr(engine.action_catalog.get(c.source_definition_id), 'display_name', None) == 'World-Cleansing Cycle'
                   for c in engine.legal_candidates())


def test_water_ally_chooses_its_start_turn_step_and_keeps_movement_budget(tmp_path):
    combat, table, mid = fight(tmp_path, 'water')
    for _ in range(10):
        if table.state(mid)['menu']['actor_id'] == ALLY:
            break
        settle(table, mid, table.state(mid)['menu']['end_turn'],
               choices={'choice:needle.rider_step': 'cell:4,5', 'choice:needle.effect_choices': 'Push'})
    engine = reload(tmp_path, mid)
    ally = engine.state.actors[ALLY]
    assert (ally.position.x, ally.position.y, ally.position.z) == (4, 5, 0)
    steps = [e for e in engine.events if e.event_type == 'MOVEMENT_COMMITTED' and e.actor_id == ALLY]
    assert steps
    assert ally.movement_remaining_ft == ally.speed_ft


@pytest.mark.parametrize('movement_bonus', [0, 10])
@pytest.mark.parametrize('distance,direction', [('5', 'Push'), ('0', 'Pull')])
def test_water_failed_save_source_chooses_push_distance_including_zero_during_enemy_turn(tmp_path, distance, direction, movement_bonus):
    combat, table, mid = fight(tmp_path, 'water', dc=100, movement_bonus=movement_bonus)
    # The target's turn triggers the field. The source remains a manual chooser even though the target acts now.
    combat.set_controller_mode(mid, actor_id=FOE, controller_mode='LOCAL_AUTO')
    before = reload(tmp_path, mid)
    start = before.state.actors[FOE].position
    prompts = []
    for _ in range(8):
        if table.state(mid)['menu']['actor_id'] == FOE:
            break
        prompts += settle(table, mid, table.state(mid)['menu']['end_turn'],
                          choices={'choice:needle.effect_choices': direction,
                                   'choice:needle.qi_cycle_water_distance': distance})
    assert table.state(mid)['menu']['actor_id'] == FOE
    after = reload(tmp_path, mid)
    moved = after.grid.distance_ft(start, after.state.actors[FOE].position)
    assert moved == int(distance)
    distance_prompt = next(p for p in prompts if p['context']['reaction_source_id'] ==
                           'choice:needle.qi_cycle_water_distance')
    labels = {o['id']: o['label'] for o in distance_prompt['choice']['options']}
    assert distance_prompt['context']['reactor_id'] == OWNER
    maximum = 15 + movement_bonus
    assert set(labels) == {str(n) for n in range(0, maximum + 1, 5)}
    assert labels[str(maximum)] == f'Move it up to {maximum} feet'
    assert f'up to {maximum} feet' in distance_prompt['moment']
    assert labels['0'] == 'Do not move it'
    assert 'failed its Strength save' in distance_prompt['moment']


def test_cycle_start_menu_explains_each_element_in_player_language(tmp_path):
    combat, table, mid = fixture(tmp_path, [], cl=18, seed='QI-CYCLE-TEXT', owner_features=[CYCLE],
                                 bundle_transform=controls, owner_pb=6, owner_dc=18)
    prompts = settle(table, mid, candidate(combat, mid, 'World-Cleansing Cycle', at=(6, 6)).candidate_id,
                     choices={'choice:needle.qi_cycle_start': 'water'})
    prompt = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.qi_cycle_start')
    labels = {o['id']: o['label'] for o in prompt['choice']['options']}
    expected = {
        'wood': ('Strength save', 'restrained', 'speed reduced', "affected creature's next turn", 'half damage'),
        'fire': ('Dexterity save', 'fire damage', 'reactions', "affected creature's next turn", 'half damage'),
        'earth': ('Dexterity save', 'bludgeoning damage', 'prone', 'half damage'),
        'metal': ('Dexterity save', 'slashing damage', 'reactions', "affected creature's next turn", '+1 AC', 'half damage'),
        'water': ('Strength save', 'bludgeoning damage', 'push', 'pull', '15 feet', 'half damage'),
    }
    for element, phrases in expected.items():
        assert all(phrase.lower() in labels[element].lower() for phrase in phrases), (element, labels[element])
    assert not any(key in ' '.join(labels.values()).lower() for key in ('qi_cycle', 'choice:'))


def test_native_minute_expiry_ends_field_and_all_benefits(tmp_path):
    combat, table, mid = fight(tmp_path, 'metal')
    for _ in range(35):
        engine = combat._load_session(mid).engine
        if not any(z.active and z.trigger_profile.get('qi_world_cycle') for z in engine.state.zones.values()):
            break
        settle(table, mid, table.state(mid)['menu']['end_turn'])
    engine = reload(tmp_path, mid)
    assert not any(z.active and z.trigger_profile.get('qi_world_cycle') for z in engine.state.zones.values())
    assert engine._ac_modifier(engine.state.actors[ALLY]) == 0
    assert any(e.event_type == 'ZONE_REMOVED' and e.payload.get('reason') == 'DURATION_ENDED' for e in engine.events)


@pytest.mark.parametrize('provider', ['direct', 'ordinary', 'source_owned'])
def test_off_turn_modifier_provider_expires_on_reactors_next_start_after_reload(tmp_path, provider):
    """Existing providers share expiry ownership with persisted modifiers.

    A test-only sealed generic reaction drives the production direct provider
    (resistance_next) or ordinary _modifier (AC). No runtime methods or hooks
    are replaced. The hostile's committed typed damage opens the manual prompt.
    """
    feature = 'test:off_turn_modifier.' + provider
    effect = ({'type': 'resistance_next', 'damage_types': ['FIRE']} if provider == 'direct'
              else {'type': 'ac_bonus', 'flat': 2, **({'source_owned': True} if provider == 'source_owned' else {})})
    effect.update({'applies_to': 'self', 'duration': 'until_start_of_your_next_turn'})

    def prepare(bundles):
        controls(bundles)
        owner = next(b for b in bundles if b['actor_id'] == OWNER)
        owner['typed_reactions'].append({'block': 'generic', 'kind': 'damaged',
            'feature_id': feature, 'name': 'Test off-turn protection', 'ask': True,
            'costs': [], 'range_ft': 60, 'numbers': {'cl': 18, 'pb': 6, 'key_mod': 4},
            'effects': [effect]})
        owner.pop('bundle_sha256')
        owner['bundle_sha256'] = canonical_sha256(owner)

    combat, table, mid = fixture(tmp_path, [], cl=18, seed='QI-OFF-TURN', bundle_transform=prepare)
    turn(table, mid, FOE)
    before = reload(tmp_path, mid)
    assert before.state.current_actor_id == FOE
    next_start = before.state.actors[OWNER].turns_started + 1
    prompts = settle(table, mid, candidate(combat, mid, 'Test double damage', target=OWNER).candidate_id,
                     choices={'reaction:typed.' + feature: 'first'})
    prompt = next(p for p in prompts if p['context']['reaction_source_id'] == 'reaction:typed.' + feature)
    assert prompt['context']['reactor_id'] == OWNER
    active = reload(tmp_path, mid)
    field = 'damage_resistance_next' if provider == 'direct' else 'armor_class'
    rows = [m for m in active.state.actors[OWNER].modifiers.values()
            if m.source_definition_id == feature and m.target_field == field]
    assert len(rows) == 1
    row = rows[0]
    assert row.source_actor_id == (OWNER if provider == 'source_owned' else FOE)
    assert not active.state.actors[OWNER].reaction_available
    # Retain the actual modifier until the reactor's next start, even across
    # any intervening actor and separate saved service transactions.
    for _ in range(8):
        current = reload(tmp_path, mid)
        if current.state.current_actor_id == OWNER:
            break
        assert row.modifier_id in current.state.actors[OWNER].modifiers
        settle(table, mid, table.state(mid)['menu']['end_turn'])
    expired = reload(tmp_path, mid)
    assert expired.state.current_actor_id == OWNER
    assert expired.state.actors[OWNER].turns_started == next_start
    assert row.modifier_id not in expired.state.actors[OWNER].modifiers
    assert row.expires_on == ('START_OF_SOURCE_NEXT_TURN' if provider == 'source_owned'
                              else f'START_OF_TURN_AT:{OWNER}:{next_start}')
    removals = [e for e in expired.events if e.event_type == 'MODIFIER_REMOVED'
                and e.payload.get('modifier_id') == row.modifier_id]
    assert len(removals) == 1 and removals[0].target_ids == (OWNER,)

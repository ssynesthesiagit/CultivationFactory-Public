"""Thunderbolt packet and settlement regressions through committed table intents.

Character fixtures supply portable sheets; resources and triggering receipts are
earned by ordinary attacks/movement, never inserted into the saved fight.
"""
import pytest

from combat.ext.unbroken_bolt import PREFIX, POOL
from combat.gate5_service import CombatService
from combat.tabletop import normalize_map, to_battlefield
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, settle, reload, turn
from tests.cw2_service_support import seal


def setup(bundles):
    for bundle, initiative in zip(bundles, (100, 0, -100)):
        bundle['actor_template']['initiative_bonus'] = initiative
        bundle['actor_template']['maximum_hp'] = 2000
        seal(bundle)


def game(tmp_path, features, *, objects=(), **kwargs):
    battlefield = to_battlefield(normalize_map({'display_name': 'Adamant yard',
        'width_squares': 20, 'height_squares': 14, 'walls': [], 'objects': list(objects),
        'starts': {'team1': [[3, 6]], 'team2': [[6, 6]]}}))
    return fixture(tmp_path, ['TAL_IRON_FIST_IRON_FIST_TRAINING'], cl=18,
        primary='Stamina', owner_path='Body Refining', owner_features=[PREFIX + f for f in features],
        bundle_transform=setup, named=True, battlefield=battlefield, positions={OWNER: {'x': 3, 'y': 6},
        ALLY: {'x': 9, 'y': 7}, FOE: {'x': 6, 'y': 6}}, **kwargs)


def choose_attack(combat, mid, actor=OWNER, target=FOE):
    engine = combat._load_session(mid).engine
    return next(c for c in engine.legal_candidates() if c.actor_id == actor and c.target_ids == (target,)
        and any(e.get('type') == 'attack' and e.get('attack_kind') == 'unarmed'
            for e in ((engine.action_catalog.get(c.source_definition_id).parameters.get('typed') or {}).get('effects') or [])))


def earned(combat, table, mid, tmp_path, count):
    """Earn charges with real movement and attacks, advancing rounds on misses."""
    declines = {'choice:needle.path_hit.' + PREFIX + feature: None
                for feature in ('adamant_frame', 'heaven_breaking_knuckle')}
    for _ in range(12):
        engine = reload(tmp_path, mid)
        if engine.state.actors[OWNER].resources.get(POOL, 0) >= count:
            return
        if engine.state.actors[OWNER].position.x == 5:
            move = next(c for c in engine.legal_candidates() if c.kind.value == 'MOVE'
                        and c.destination.x == 3 and c.destination.y == 6)
            settle(table, mid, move.candidate_id)
        engine = combat._load_session(mid).engine
        move = next(c for c in engine.legal_candidates() if c.kind.value == 'MOVE'
                    and c.destination.x == 5 and c.destination.y == 6)
        settle(table, mid, move.candidate_id)
        settle(table, mid, choose_attack(combat, mid).candidate_id, declines)
        turn(table, mid, FOE)
        turn(table, mid, OWNER)
    raise AssertionError('No qualifying native movement hit generated the required Charges')


def paid(combat, table, mid, tmp_path, feature, picks):
    """Natural misses spend no on-hit resource; continue through real turns."""
    for _ in range(8):
        before = len(combat._load_session(mid).engine.events)
        settle(table, mid, choose_attack(combat, mid).candidate_id, picks)
        engine = reload(tmp_path, mid)
        if any(e.event_type == 'RESOURCE_SPENT' and e.source_definition_id == PREFIX + feature
               for e in engine.events[before:]):
            return engine, engine.events[before:]
        turn(table, mid, FOE)
        turn(table, mid, OWNER)
    raise AssertionError('No native hit offered the paid rider')


def test_frame_paid_damage_is_one_packet_and_secondary_follows_hp_commit(tmp_path):
    combat, table, mid = game(tmp_path, ['adamant_frame'], owner_ac=18)
    # A movement hit earns a charge. The next turn spends that persisted charge.
    earned(combat, table, mid, tmp_path, 1)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[POOL] == 1
    engine, events = paid(combat, table, mid, tmp_path, 'adamant_frame', {
        'choice:needle.path_hit.' + PREFIX + 'adamant_frame': 'first',
        'choice:needle.path_results.' + PREFIX + 'adamant_frame': 'Temporary Hit Points'})
    # The printed single impact: the 1d8/2d8/3d8 rider rides the strike's own packet, so
    # packet-wide defenses see one packet with two typed components. (The Iron Fist
    # sphere's own "Open the Gate: Centerline Impact" rider adds its Proficiency Bonus in
    # a packet of its own; it is a different feature and never ours.)
    impact = [e for e in events if e.event_type == 'DAMAGE_COMMITTED' and FOE in e.target_ids
              and e.payload.get('components')]
    assert len(impact) == 1, [e.payload for e in events if e.event_type == 'DAMAGE_COMMITTED']
    packet = impact[0]
    parts = packet.payload['components']
    assert len(parts) == 2 and {part['damage_type'] for part in parts} == {'BLUDGEONING', 'LIGHTNING'}
    assert sum(part['applied'] for part in parts) == packet.payload['hp_damage']
    assert not any(e.event_type == 'DAMAGE_COMMITTED' and str(e.source_definition_id).startswith(PREFIX) for e in events)
    assert engine.state.actors[OWNER].resources[POOL] == 0
    assert engine.state.actors[OWNER].temporary_hp == engine.state.actors[OWNER].proficiency_bonus
    gain = next(e for e in events if e.event_type == 'TEMP_HP_GRANTED')
    assert packet.sequence < gain.sequence
    loaded = CombatService(combat.source_root, tmp_path)._load_session(mid)
    assert loaded.verify()['status'] == 'PASS'


def test_knuckle_uses_earned_charges_then_commits_one_packet_and_two_distinct_results(tmp_path):
    combat, table, mid = game(tmp_path, ['heaven_breaking_knuckle'], owner_dc=1000)
    earned(combat, table, mid, tmp_path, 2)
    engine, events = paid(combat, table, mid, tmp_path, 'heaven_breaking_knuckle', {
        'choice:needle.path_hit.' + PREFIX + 'heaven_breaking_knuckle': 'Use Heaven-Breaking Knuckle',
        'choice:needle.path_results.heaven_breaking_knuckle': ['No Reactions', 'Reduce AC']})
    impact = [e for e in events if e.event_type == 'DAMAGE_COMMITTED' and FOE in e.target_ids
              and e.payload.get('components')]
    assert len(impact) == 1, [e.payload for e in events if e.event_type == 'DAMAGE_COMMITTED']
    packet = impact[0]
    parts = packet.payload['components']
    assert len(parts) == 2 and parts[0]['damage_type'] == 'BLUDGEONING'
    assert parts[1]['damage_type'] in ('FORCE', 'THUNDER')
    assert sum(part['applied'] for part in parts) == packet.payload['hp_damage']
    target = engine.state.actors[FOE]
    assert any(c.condition_id == 'condition:typed.reaction_denied' for c in target.conditions.values())
    assert any(c.condition_id == 'condition:typed.path_ac.heaven_breaking_knuckle' for c in target.conditions.values())
    assert engine.state.actors[OWNER].resources[POOL] == 0


def test_descent_with_no_chosen_creatures_still_scales_object_damage(tmp_path):
    combat, table, mid = game(tmp_path, ['adamantine_descent'],
        objects=[{'id': 1, 'kind': 'crate', 'x': 6, 'y': 5, 'hp': 1000}])
    earned(combat, table, mid, tmp_path, 4)
    before = len(combat._load_session(mid).engine.events)
    descent = candidate(combat, mid, 'Adamantine Descent', at=(5, 5))
    settle(table, mid, descent.candidate_id, {'choice:needle.area_recipients': []})
    engine = reload(tmp_path, mid)
    events = engine.events[before:]
    assert not any(e.event_type == 'DAMAGE_COMMITTED' for e in events)
    damage = [e.payload['damage'] for e in events if e.event_type == 'OBJECT_UPDATED'
              and 'damage' in e.payload]
    assert len(damage) == 1 and damage[0]['taken'] > 0
    # 8d10 plus four actually spent Charges; the object's one packet is doubled.
    rolls = [roll for roll in engine.rolls if roll.expression.startswith('12d10')]
    assert len(rolls) == 1 and damage[0]['taken'] == 2 * rolls[0].total
    assert engine.state.actors[OWNER].resources[POOL] == 0


def test_descent_consumes_all_earned_charges_and_selected_targets_survive_reload(tmp_path):
    combat, table, mid = game(tmp_path, ['adamantine_descent'], owner_dc=1000)
    earned(combat, table, mid, tmp_path, 4)
    before = len(combat._load_session(mid).engine.events)
    descent = candidate(combat, mid, 'Adamantine Descent', at=(5, 5))
    current = combat._load_session(mid).engine
    action = current.action_catalog[descent.source_definition_id]
    assert dict(current.effective_costs(current.state.actors[OWNER], action.source_definition_id, action.costs))[POOL] == 4
    settle(table, mid, descent.candidate_id, {'choice:needle.area_recipients': [FOE]})
    engine = reload(tmp_path, mid)
    actor = engine.state.actors[OWNER]
    assert actor.resources[POOL] == 0
    assert any(c.condition_id == 'condition:typed.path_next_unarmed_damage' for c in actor.conditions.values())
    packets = [e for e in engine.events[before:] if e.event_type == 'DAMAGE_COMMITTED']
    assert packets and all(ALLY not in e.target_ids and OWNER not in e.target_ids for e in packets)
    spent = [e for e in engine.events[before:] if e.event_type == 'RESOURCE_SPENT' and e.payload.get('resource_id') == POOL]
    moved = next(e for e in engine.events[before:] if e.event_type == 'MOVEMENT_COMMITTED')
    assert sum(e.payload['amount'] for e in spent) == 4 and all(e.sequence < moved.sequence for e in spent)
    assert not any(c.display_name == 'Adamantine Descent' for c in engine.legal_candidates())


@pytest.mark.parametrize('owned', [False, True])
def test_normal_limit_is_shared_before_cl14_and_survives_reload(owned):
    from tests.test_riders_lane13 import engine, ME
    fight = engine([PREFIX + 'adamant_frame'] if owned else [], cl=3)
    actor = fight.state.actors[ME]
    if not owned:
        assert POOL not in actor.resources
        return
    fight._gain_resource(actor, POOL, 1, 'test:first-normal')
    fight._gain_resource(actor, POOL, 1, 'test:second-normal')
    assert actor.resources[POOL] == 1


def test_bone_followups_are_after_committed_zero_damage():
    from tests.test_riders_lane13 import engine, packet, ME
    fight = engine([PREFIX + 'thunder_runs_through_bone'])
    actor = fight.state.actors[ME]
    packet(fight, 1, 'THUNDER')
    assert actor.resources[POOL] == 1
    damage = next(e for e in fight.events if e.event_type == 'DAMAGE_COMMITTED')
    gain = next(e for e in fight.events if e.event_type == 'RESOURCE_GAINED')
    assert damage.payload['reduced_to'] == 0 and damage.sequence < gain.sequence
    assert any(c.condition_id == 'condition:typed.path_next_unarmed' for c in actor.conditions.values())


def test_bone_zero_before_its_own_reduction_does_not_award_followups():
    from tests.test_riders_lane13 import engine, packet, ME
    fight = engine([PREFIX + 'thunder_runs_through_bone'])
    actor = fight.state.actors[ME]
    packet(fight, 0, 'THUNDER')
    assert actor.resources[POOL] == 0
    assert not any(c.condition_id == 'condition:typed.path_next_unarmed' for c in actor.conditions.values())


def test_bone_can_combine_with_a_later_legal_flat_reduction(monkeypatch):
    """Supplementary packet-seam guard; the table fixtures own play acceptance."""
    from combat import ext
    from tests.test_riders_lane13 import engine, packet, ME
    fight = engine([PREFIX + 'thunder_runs_through_bone'])
    ext.effects()
    def later_reduction(engine, actor, pending, *args):
        return {'reduction': pending} if actor.entity_id == ME else None
    monkeypatch.setitem(ext._HOOKS, 'final_damage', [*ext._HOOKS.get('final_damage', []), later_reduction])
    packet(fight, 60, 'THUNDER')
    actor = fight.state.actors[ME]
    assert actor.resources[POOL] == 1
    assert any(c.condition_id == 'condition:typed.path_next_unarmed' for c in actor.conditions.values())


def test_declining_bone_does_not_roll_unused_reduction_dice():
    """A printed reaction asks before it spends anything, through the shared ask."""
    from tests.test_riders_lane13 import engine, packet, ME, answers
    fight = engine([PREFIX + 'thunder_runs_through_bone'], reaction_ask=True)
    answers(fight, {'thunder_runs_through_bone': None})
    asked, shared = [], fight._gate4_reaction_provider
    def provider(request):
        asked.append(request['reaction_source_id'])
        return shared(request)
    fight.set_reaction_provider(provider)
    counter = fight.roller.counter
    packet(fight, 20, 'THUNDER')
    # One question, from this feature: the source is the compiled reaction id that wraps the record id.
    assert asked and {source.rsplit('reaction:typed.', 1)[-1] for source in asked} == {
        PREFIX + 'thunder_runs_through_bone'}
    assert fight.roller.counter == counter
    assert fight.state.actors[ME].reaction_available
    assert fight.state.actors[ME].resources['resource:core.stamina'] == 60


def test_mixed_damage_reduction_is_spent_once_across_component_defenses():
    from tests.test_riders_lane13 import engine, ME, AN
    # A typed target: passive "defense" rows are read from the actor's compiled bundle.
    fight = engine([], enemy_typed=True)
    target = fight.state.actors[AN]
    fight.typed_passive_rows[target.entity_id] = [{
        'feature_id': 'test:flat-six', 'block': 'defense', 'kind': 'reduction',
        'amount': 6, 'damage_types': ['THUNDER', 'FORCE'],
    }]
    before, start = target.current_hp, len(fight.events)
    # ``components`` are pre-rolled additions to the packet's primary type, not a breakdown of it.
    fight._commit_damage(target, 10, 'THUNDER', 'test:mixed', ME, None, reaction_depth=0,
        components=[{'amount': 10, 'damage_type': 'FORCE'}])
    assert before - target.current_hp == 14
    packets = [e for e in fight.events[start:] if e.event_type == 'DAMAGE_COMMITTED']
    assert len(packets) == 1
    assert sum(part['applied'] for part in packets[0].payload['components']) == 14


def test_descent_cannot_cross_a_surviving_wall():
    from tests.test_riders_c7 import bundle, fight, use, ME
    engine = fight(bundle([PREFIX + 'adamantine_descent']), foe_at=(10, 6),
        walls=[{'shape': 'line', 'points': [[6, 0], [6, 14]]}])
    actor = engine.state.actors[ME]
    engine._gain_resource(actor, POOL, 3, 'test:boundary-setup')
    beyond = [c for c in engine.legal_candidates() if c.display_name.startswith('Adamantine Descent')
              and c.destination is not None and c.destination.x == 9 and c.destination.y == 6]
    if beyond:
        use(engine, 'Adamantine Descent', at=(9, 6))
    assert actor.position.x < 6


def test_descent_resistance_covers_new_damage_types_but_not_psychic_or_void():
    from tests.test_riders_c7 import _descent, use
    from combat import typed_reactions
    engine, actor = _descent()
    use(engine, 'Adamantine Descent', at=(9, 6))
    for kind in ('FIRE', 'RADIANT', 'NEW_DAMAGE_TYPE'):
        assert typed_reactions.defend(engine, actor, 20, kind, 'test', None) == 10
    for kind in ('PSYCHIC', 'VOID'):
        assert typed_reactions.defend(engine, actor, 20, kind, 'test', None) == 20


def test_component_types_coalesce_before_resistance_rounding_and_commit_once():
    from tests.test_riders_lane13 import engine, ME, AN
    fight = engine([])
    target = fight.state.actors[AN]
    fight._add_modifier(target, 'test:resistance', 'damage_resistance', 'SET', 'FORCE', 'ALWAYS',
                        expires_on='UNTIL_REMOVED')
    before, start = target.current_hp, len(fight.events)
    fight._commit_damage(target, 3, 'FORCE', 'test:mixed', ME, None, reaction_depth=0,
                         components=[{'amount': 3, 'damage_type': 'FORCE'}])
    assert before - target.current_hp == 3
    packets = [e for e in fight.events[start:] if e.event_type == 'DAMAGE_COMMITTED']
    assert len(packets) == 1 and packets[0].payload['components'] == [{'damage_type': 'FORCE', 'applied': 3}]


def test_mixed_packet_applies_packet_wide_resistance_once_and_keeps_each_type():
    """A once-only defense belongs to the hit, not to each typed component."""
    from tests.test_riders_lane13 import engine, ME, AN
    fight = engine([])
    target = fight.state.actors[AN]
    fight._add_modifier(target, 'test:next-force-resistance', 'damage_resistance_next', 'SET', 'FORCE', 'ALWAYS',
                        expires_on='UNTIL_REMOVED')
    before, start = target.current_hp, len(fight.events)
    fight._commit_damage(target, 10, 'THUNDER', 'test:mixed', ME, None, reaction_depth=0,
                         components=[{'amount': 10, 'damage_type': 'FORCE'}])
    packets = [e for e in fight.events[start:] if e.event_type == 'DAMAGE_COMMITTED']
    assert len(packets) == 1
    assert before - target.current_hp == 15
    assert not any(m.modifier_id == 'test:next-force-resistance' for m in target.modifiers.values())


def test_invalid_component_fails_before_resistance_is_consumed():
    from tests.test_riders_lane13 import engine, ME, AN
    fight = engine([])
    target = fight.state.actors[AN]
    before = target.model_dump(mode='json')
    with pytest.raises(ValueError, match='damage components'):
        fight._commit_damage(target, 3, 'FORCE', 'test:mixed', ME, None, reaction_depth=0,
                             components=[{'amount': -1, 'damage_type': 'FORCE'}])
    assert target.model_dump(mode='json') == before


@pytest.mark.parametrize('feature,cl', [('adamant_frame', 1), ('heaven_breaking_knuckle', 9),
                                           ('body_of_the_unbroken_bolt', 13)])
def test_feature_contributes_no_printed_row_below_its_level(feature, cl):
    """A below-level feature prints nothing; the family's bookkeeping profile row is not a printed row."""
    from tests.test_riders_lane13 import engine, ME
    fight = engine([PREFIX + feature], cl=cl)
    rows = [row for row in fight.typed_passive_rows[ME]
            if row.get('feature_id') == PREFIX + feature and row.get('block') != 'adamant_thunderbolt_profile']
    assert not rows


def test_profile_row_is_idempotent_when_compile_bundle_runs_twice():
    """A retained profile row must not keep a stale Proficiency Bonus."""
    from copy import deepcopy
    from combat.ext import unbroken_bolt
    from tests.test_riders_lane13 import bundle
    data = deepcopy(bundle([PREFIX + 'adamant_frame']))
    info = {'numbers': {'cl': 10, 'pb': 4}, 'owner_sheet': {'path_and_subpath': {'paths': [
        {'path_id': 'tianxia.path.body_refining', 'effective_cl': 7, 'key_ability': 'CON'}]}}}
    once = unbroken_bolt.family_profile(data, info)
    twice = unbroken_bolt.family_profile(once, info)
    rows = [row for row in twice['typed_passives'] if row.get('block') == 'adamant_thunderbolt_profile']
    assert len(rows) == 1 and rows[0]['cl'] == 7


def test_stamina_guard_charge_reads_its_receipt_not_the_last_event():
    """The guard's reduction and this gain are separate events; a notice between them is not a receipt."""
    from combat import pending_damage
    from combat.ext import unbroken_bolt
    from tests.test_riders_lane13 import engine, ME, AN
    fight = engine([PREFIX + 'adamant_frame'])
    actor = fight.state.actors[ME]
    with pending_damage.scope(fight, actor, 20, 'THUNDER', unbroken_bolt.STAMINA_GUARD, AN):
        fight._append_event('REACTION_WINDOW_OPENED', unbroken_bolt.STAMINA_GUARD, actor_id=actor.entity_id,
                            target_ids=(actor.entity_id,), payload={'checkpoint': 'DAMAGE_APPLICATION'})
        fight._append_event('REACTION_RESOLVED', unbroken_bolt.STAMINA_GUARD, actor_id=actor.entity_id,
                            target_ids=(AN,), payload={'checkpoint': 'DAMAGE_APPLICATION', 'reduction': 8,
                                                       'pending_before': 20, 'pending_after': 12})
        fight._append_event('DAMAGE_DEFENDED', 'test:observer', actor_id=AN, target_ids=(actor.entity_id,), payload={})
        # The receipt is 8 points, not the newest event; a +9 bonus is therefore not met, and the guard
        # Charge is refused, while the same receipt satisfies a bonus of 8.
        assert unbroken_bolt._stamina_guard_reduced(fight, actor, 9) is False
        assert unbroken_bolt._stamina_guard_reduced(fight, actor, 8) is True
        rows = fight.typed_passive_rows.setdefault(actor.entity_id, [])
        profile = next((row for row in rows if row.get('block') == 'adamant_thunderbolt_profile'), None)
        if profile is None:
            profile = {'block': 'adamant_thunderbolt_profile', 'cl': 14}
            rows.append(profile)
        profile['pb'] = 9
        # The generator reads that receipt: a short guard leaves the Charge unpaid.
        assert unbroken_bolt.charge_limit(fight, actor, POOL, 1, unbroken_bolt.STAMINA_GUARD) is False


def test_family_uses_owning_body_profile_instead_of_another_paths_level():
    from combat.factory_compiler import compile_character
    from tests.h1_support import sheet
    document = sheet([PREFIX + 'adamant_frame', PREFIX + 'heaven_breaking_knuckle',
                      PREFIX + 'adamantine_descent'], cl=20, primary='Qi')
    document['path_and_subpath']['paths'] = [
        {'path_id': 'tianxia.path.body_refining', 'effective_cl': 9, 'key_ability': 'CON'},
        {'path_id': 'tianxia.path.qi_cultivation', 'effective_cl': 11, 'key_ability': 'WIS'}]
    bundle = compile_character(document, actor_id=OWNER)
    rows = bundle['typed_passives']
    frame = next(r for r in rows if r.get('feature_id') == PREFIX + 'adamant_frame' and r.get('kind') == 'paid_hit')
    assert (frame['cl'], frame['pb']) == (9, 4)
    assert not any(r.get('feature_id') == PREFIX + 'heaven_breaking_knuckle' and r.get('kind') == 'paid_hit' for r in rows)
    pool = next(r for r in bundle['actor_template']['resources'] if r['resource_id'] == POOL)
    assert pool['maximum'] == 4
    action = next(a for a in bundle['action_catalog'] if (a['parameters'].get('typed') or {}).get('source') == PREFIX + 'adamantine_descent')
    assert action['parameters']['typed']['numbers']['cl'] == 9


def test_no_plugin_reclassifies_a_qi_primary_sheets_actions_as_qi_powered():
    """Adamant Thunderbolt spends Stamina and Charges; it owns no Qi provenance.

    A plug-in that sealed ``qi_powered`` from the sheet's primary resource alone would
    silently re-decide other lanes' actions (yin_yang_cultivator, ancestral_bloodline,
    treasure_armor treat an explicit boolean as authoritative), so this record's compile
    stamps nothing and every strike keeps whatever its own source declares.
    """
    from combat import ext
    from combat.factory_compiler import compile_character
    from tests.h1_support import sheet
    ext.effects()
    bundle = compile_character(sheet(['TAL_IRON_FIST_IRON_FIST_TRAINING'], cl=10, primary='Qi'), actor_id=OWNER)
    actions = list(bundle['action_catalog'])
    attacks = [a for a in actions if a['parameters'].get('object_attack')]
    assert attacks
    assert all((a['parameters'].get('typed') or {}).get('qi_powered') is None for a in actions)


def test_frame_next_save_bonus_applies_to_one_native_strength_or_constitution_save():
    from tests.test_riders_lane13 import engine, ME, answers, use, attack_name
    fight = engine([PREFIX + 'adamant_frame'])
    actor = fight.state.actors[ME]
    fight._gain_resource(actor, POOL, 1, 'test:setup')
    asked = []
    answers(fight, {'adamant_frame': ['Next Strength or Constitution Save']}, asked)
    use(fight, attack_name(fight))
    # Exactly one payment question: the fixture cannot absorb a silent second charge.
    assert [options for _source, options in asked if options == ('Use Adamant Frame',)] == [('Use Adamant Frame',)]
    fight._roll_save(actor, 'DEX', 10, 'test:native')
    first = fight._roll_save(actor, 'CON', 10, 'test:native')
    second = fight._roll_save(actor, 'CON', 10, 'test:native')
    assert first.modifier - second.modifier == actor.proficiency_bonus
    assert not any(c.condition_id == 'condition:typed.path_next_save' for c in actor.conditions.values())


def test_successful_hostile_native_repeat_save_earns_one_normal_charge():
    from tests.test_riders_lane13 import engine, ME, AN
    fight = engine([PREFIX + 'adamant_frame'], ability_mods={'CON': 100})
    actor = fight.state.actors[ME]
    fight._apply_condition(actor, 'condition:typed.paralyzed', 'test:hostile-paralysis', AN,
                           expires_on='UNTIL_REMOVED')
    held = next(c for c in actor.conditions.values() if c.condition_id == 'condition:typed.paralyzed')
    fight.resolve_repeat_save(actor, held.instance_id, held, {'ability': 'CON', 'dc': 1}, 'END_OF_TURN')
    assert not any(c.condition_id == held.condition_id for c in actor.conditions.values())
    assert actor.resources[POOL] == 1


def test_movement_credit_for_charge_ends_with_the_current_creatures_turn():
    from tests.test_riders_lane13 import engine, ME
    from combat.gate2_runtime_models import ActionIntent
    from combat.ext.subpath_pools import moved_on_foot
    fight = engine([PREFIX + 'adamant_frame'])
    actor = fight.state.actors[ME]
    move = next(c for c in fight.legal_candidates() if c.kind.value == 'MOVE'
                and c.destination.x == 3 and c.destination.y == 4)
    def execute(c):
        fight.execute_intent(ActionIntent(intent_id='movement-boundary:' + str(len(fight.events)),
            decision_id=c.decision_id, candidate_id=c.candidate_id, state_version=c.state_version,
            actor_id=c.actor_id, target_ids=c.target_ids, destination=c.destination))
    execute(move)
    assert moved_on_foot(fight, actor, current_turn=True) >= 10
    execute(next(c for c in fight.legal_candidates() if c.kind.value == 'END_TURN'))
    assert fight.state.current_actor_id != ME
    assert moved_on_foot(fight, actor, current_turn=True) == 0


def test_a_native_object_hit_after_movement_also_earns_a_charge(tmp_path):
    combat, table, mid = game(tmp_path, ['adamant_frame'],
        objects=[{'id': 1, 'kind': 'crate', 'x': 6, 'y': 5, 'hp': 1000}])
    for _ in range(8):
        engine = reload(tmp_path, mid)
        if engine.state.actors[OWNER].position.x == 5:
            move = next(c for c in engine.legal_candidates() if c.kind.value == 'MOVE'
                        and c.destination.x == 3 and c.destination.y == 6)
            settle(table, mid, move.candidate_id)
        engine = combat._load_session(mid).engine
        move = next(c for c in engine.legal_candidates() if c.kind.value == 'MOVE'
                    and c.destination.x == 5 and c.destination.y == 6)
        settle(table, mid, move.candidate_id)
        engine = combat._load_session(mid).engine
        strike = next(c for c in engine.legal_candidates() if c.target_ids == ('object:map.1',)
                      and '.object_attack.unarmed' in c.source_definition_id)
        weapon = engine.action_catalog[strike.source_definition_id].parameters['typed']['object_weapon']
        assert set(weapon['damage_types']) == {'BLUDGEONING', 'FORCE', 'LIGHTNING', 'THUNDER'}
        settle(table, mid, strike.candidate_id, {'choice:needle.path_unarmed_type': 'LIGHTNING'})
        engine = reload(tmp_path, mid)
        if engine.state.actors[OWNER].resources[POOL] == 1:
            assert any(e.event_type == 'OBJECT_UPDATED' and e.payload.get('damage', {}).get('kinds') == 'lightning'
                       for e in engine.events)
            return
        turn(table, mid, FOE)
        turn(table, mid, OWNER)
    raise AssertionError('No native object hit generated its printed Charge')


@pytest.mark.parametrize('spend_descent', [False, True])
def test_scene_resources_survive_combat_and_rest_then_reset_on_native_scene_end(tmp_path, spend_descent):
    import json
    import zipfile
    from combat.tabletop_service import TabletopService
    from tests.h1_support import ROOT, sheet

    ids = (OWNER, ALLY, FOE)
    projects = [aid.removeprefix('actor:factory.') for aid in ids]
    for aid, pid in zip(ids, projects):
        features = ([PREFIX + 'adamantine_descent', 'TAL_IRON_FIST_IRON_FIST_TRAINING']
                    if aid == OWNER else [])
        document = sheet(features, cl=18, primary='Stamina', name={OWNER: 'Wren', ALLY: 'Tobin', FOE: 'Mara'}[aid])
        document['identity'].update(path='Body Refining', proficiency_bonus=6)
        document['ability_scores_and_statistics']['hit_points']['maximum'] = 2000
        folder = tmp_path / 'portable_characters' / pid
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / 'current.zip', 'w') as archive:
            archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(document))
    combat = CombatService(ROOT, tmp_path)
    combat.tabletop_maps.save({'display_name': 'Adamant scene', 'width_squares': 20,
        'height_squares': 14, 'walls': [], 'starts': {'team1': [[3, 6]], 'team2': [[6, 6]]}})
    places = {OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 9, 'y': 7}, FOE: {'x': 6, 'y': 6}}
    creation = dict(project_ids=projects, arena_id='battlefield:map.adamant-scene',
                    positions=places, base_paces={aid: 3000 for aid in ids})
    journey = combat.create_journey(**creation)
    jid = journey['journey_id']
    teams = {OWNER: 'a', ALLY: 'b', FOE: 'b'}
    view = combat.journey_start_combat(jid, journey['revision'], teams, maximum_rounds=20)
    mid, table = view['match_id'], TabletopService(combat, tmp_path)
    turn(table, mid, OWNER)
    earned(combat, table, mid, tmp_path, 4 if spend_descent else 1)
    engine = combat._load_session(mid).engine
    descent = next(a for a in engine.action_catalog.values()
                   if a.owner_id == OWNER and (a.parameters.get('typed') or {}).get('source') == PREFIX + 'adamantine_descent')
    counter = next(resource for resource, amount in descent.costs if resource.startswith('resource:uses.'))
    if spend_descent:
        settle(table, mid, candidate(combat, mid, 'Adamantine Descent', at=(5, 5)).candidate_id,
               {'choice:needle.area_recipients': [FOE]})
    expected_charge, expected_use = (0, 0) if spend_descent else (1, 1)

    def finish_fight(current_mid, current_table, current_combat):
        for _ in range(80):
            if current_combat._load_session(current_mid).engine.state.terminal_result is not None:
                assert reload(tmp_path, current_mid).state.terminal_result is not None
                return
            settle(current_table, current_mid, current_table.state(current_mid)['menu']['end_turn'])
        raise AssertionError('The native round limit did not end the encounter')

    finish_fight(mid, table, combat)
    combat = CombatService(ROOT, tmp_path)
    journey = combat.journey_state(jid)
    journey = combat.journey_resume(jid, journey['revision'])
    assert journey['actors'][OWNER]['resources'][POOL] == expected_charge
    assert journey['actors'][OWNER]['resources'][counter] == expected_use
    journey = combat.journey_act(jid, journey['revision'], OWNER, 'long_rest')
    assert journey['actors'][OWNER]['resources'][POOL] == expected_charge
    assert journey['actors'][OWNER]['resources'][counter] == expected_use
    second = combat.journey_start_combat(jid, journey['revision'], teams, maximum_rounds=1, positions=places)
    second_mid = second['match_id']
    actor = reload(tmp_path, second_mid).state.actors[OWNER]
    assert actor.resources[POOL] == expected_charge and actor.resources[counter] == expected_use
    finish_fight(second_mid, TabletopService(combat, tmp_path), combat)
    journey = combat.journey_state(jid)
    journey = combat.journey_resume(jid, journey['revision'])
    journey = combat.journey_act(jid, journey['revision'], OWNER, 'finish')
    assert journey['actors'][OWNER]['resources'][POOL] == 0
    assert journey['actors'][OWNER]['resources'][counter] == 1
    newer = CombatService(ROOT, tmp_path).create_journey(**creation)
    assert newer['actors'][OWNER]['resources'][POOL] == 0
    assert newer['actors'][OWNER]['resources'][counter] == 1

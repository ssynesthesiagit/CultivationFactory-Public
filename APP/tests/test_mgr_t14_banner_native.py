"""Banner commands through native table transactions and cold mechanical replay.

The opposing probes are sealed actions, never fabricated runtime trigger receipts.
No model server is used by these tests.
"""
import pytest

from combat.ext import banner, placed
from combat.canonical import canonical_sha256
from tests.worker2_support import fixture, candidate, settle, reload, turn, OWNER, ALLY, FOE

FULL = [banner.RAISE, banner.RALLY, banner.ADVANCING, banner.FOURFOLD, banner.IMPERIAL]
MANIFEST = 'Manifest Command Banner (1 Qi)'


def raise_banner(combat, table, mid, *, stances='forward+guarded', allies=None):
    return settle(table, mid, candidate(combat, mid, MANIFEST, at=(4, 7)).candidate_id,
                  choices={'choice:needle.banner_manifest_stance': [stances],
                           'choice:needle.banner_designated_allies': [OWNER, ALLY] if allies is None else allies})


def save_probe(bundles):
    """Native signed negative saves: a legal PB contribution must not reject them."""
    bundles[1]['actor_template']['saving_throws']['WIS'] = -21
    row = {'source_definition_id': 'action:test.banner_fear', 'display_name': 'Terrifying order',
           'owner_id': FOE, 'economy': 'NONE', 'resolution_kind': 'TYPED', 'target_kind': 'HOSTILE_ENTITY',
           'range_ft': 60, 'parameters': {'expected_damage': 0, 'free_primary': True, 'typed': {
               'source': 'test:banner_fear', 'numbers': {'save_dc': 5}, 'duration': {'kind': 'instant'},
               'effects': [{'type': 'save', 'ability': 'wis', 'applies_to': 'target',
                            'on_fail': [{'type': 'condition', 'condition': 'frightened', 'applies_to': 'target',
                                         'expires_on': 'END_OF_CURRENT_TURN'}], 'on_success': []}], 'riders': []}}}
    bundles[2]['action_catalog'].append(row)
    bundles[2]['actor_template']['action_ids'].append(row['source_definition_id'])
    for bundle in bundles:
        bundle.pop('bundle_sha256', None)
        bundle['bundle_sha256'] = canonical_sha256(bundle)


def test_manifest_records_player_stances_and_designated_allies_on_reload(tmp_path):
    combat, table, mid = fixture(tmp_path, FULL, cl=18, named=True)
    prompts = raise_banner(combat, table, mid, stances='steady+signal', allies=[ALLY])
    assert {p['context']['reaction_source_id'] for p in prompts} >= {
        'choice:needle.banner_manifest_stance', 'choice:needle.banner_designated_allies'}
    engine = reload(tmp_path, mid)
    zone = placed.of(engine, 'standard')[0]
    assert placed.data(zone)['stances'] == ['steady', 'signal']
    assert placed.data(zone)['designated_allies'] == [ALLY]
    assert banner.clear_signal_passive(engine, engine.state.actors[ALLY]) == 1
    assert banner.clear_signal_passive(engine, engine.state.actors[OWNER]) is None
    assert banner.clear_signal_passive(engine, engine.state.actors[FOE]) is None
    obj = engine.state.objects['object:banner:' + zone.zone_id]
    assert (obj.ac, obj.current_hp, obj.maximum_hp) == (14, 54, 54)
    assert set(obj.damage_immunities) == {'POISON', 'PSYCHIC'}
    assert engine.state.actors[OWNER].resources['resource:core.qi'] == 99


@pytest.mark.parametrize('take', [True, False])
def test_hold_formation_signed_save_choice_payment_and_replay(tmp_path, take):
    combat, table, mid = fixture(tmp_path, FULL, cl=18, owner_pb=6,
        seed='BANNER-SIGNED-1', named=True, bundle_transform=save_probe)
    raise_banner(combat, table, mid)
    turn(table, mid, FOE)
    before = reload(tmp_path, mid).state.actors[OWNER].resources['resource:core.qi']
    prompts = []
    for _ in range(8):
        engine = combat._load_session(mid).engine
        available = [c for c in engine.legal_candidates() if c.source_definition_id == 'action:test.banner_fear']
        assert any(c.target_ids == (ALLY,) for c in available), (engine.state.current_actor_id,
            [(c.target_ids, c.display_name) for c in available], engine.state.actors[FOE].action_ids[-5:])
        prompts = settle(table, mid, next(c.candidate_id for c in available if c.target_ids == (ALLY,)),
            choices={'choice:needle.banner_hold': ['hold'] if take else None})
        if any(p['context']['reaction_source_id'] == 'choice:needle.banner_hold' for p in prompts):
            break
    else:
        pytest.fail('deterministic stream never offered a failed save')
    engine = reload(tmp_path, mid)
    hold = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.banner_hold')
    assert 'Terrifying order' in hold['moment'] and 'Hold Formation' in hold['moment']
    rewrites = [e for e in engine.events if e.event_type == 'D20_REWRITTEN' and e.source_definition_id == banner.RALLY]
    assert len(rewrites) == int(take)
    owner = engine.state.actors[OWNER]
    assert owner.resources['resource:core.qi'] == before - int(take)
    assert owner.reaction_available is (not take)
    if take:
        assert rewrites[0].payload['bonus'] == 6
        assert rewrites[0].payload['original']['total'] < 5
        assert rewrites[0].payload['result']['total'] == rewrites[0].payload['original']['total'] + 6


def test_nonowner_has_no_banner_actions_or_passive_benefit(tmp_path):
    combat, table, mid = fixture(tmp_path, [], named=True)
    engine = reload(tmp_path, mid)
    assert not any(a.parameters.get('banner_button') for a in engine.action_catalog.values())
    assert banner.clear_signal_passive(engine, engine.state.actors[OWNER]) is None
    assert banner.steady_save(engine, engine.state.actors[OWNER], 'WIS', 16, 'test', {'named': ['frightened']}) is None


@pytest.mark.parametrize('cl,allowed', [(3, {'raise', 'carry', 'dismiss', 'stance'}),
    (6, {'raise', 'carry', 'dismiss', 'stance', 'rally'}),
    (10, {'raise', 'carry', 'dismiss', 'stance', 'rally', 'advance', 'move', 'pick'}),
    (14, {'raise', 'carry', 'dismiss', 'stance', 'rally', 'advance', 'move', 'pick'})])
def test_native_catalog_cannot_publish_future_progression_rows(tmp_path, cl, allowed):
    combat, table, mid = fixture(tmp_path, FULL, cl=cl)
    engine = reload(tmp_path, mid)
    buttons = {a.parameters['banner_button'] for a in engine.action_catalog.values()
               if a.owner_id == OWNER and a.parameters.get('banner_button')}
    assert buttons == allowed


def test_banner_uses_own_qi_path_cl_key_and_proficiency_in_native_play(tmp_path):
    from combat.factory_compiler import compile_character
    from tests.h1_support import sheet
    document = sheet(FULL, cl=18)
    document['path_and_subpath']['paths'] = [{'path_id': 'tianxia.path.qi_cultivation',
        'effective_cl': 6, 'key_ability': 'WIS', 'proficiency_bonus': 3}]
    for ability in document['ability_scores_and_statistics']['abilities']:
        if ability['ability'] == 'WIS':
            ability.update(score=10, modifier=0)
    bundle = compile_character(document, actor_id=OWNER, reaction_plan={'ask': True})
    combat, table, mid = fixture(tmp_path, [], cl=18, owner_bundle=bundle)
    raise_banner(combat, table, mid, stances='forward')
    engine = reload(tmp_path, mid)
    zone = placed.of(engine, 'standard')[0]
    assert engine.state.objects['object:banner:' + zone.zone_id].maximum_hp == 18
    assert not any(a.parameters.get('banner_button') in {'advance', 'imperial'}
                   for a in engine.action_catalog.values() if a.owner_id == OWNER)
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    turn(table, mid, OWNER)
    settle(table, mid, candidate(combat, mid, 'Rally the Line (2 Qi)').candidate_id,
           choices={'choice:needle.rally_allies': [ALLY]})
    assert reload(tmp_path, mid).state.actors[ALLY].temporary_hp == 3


def test_rally_and_imperial_native_cost_aura_and_cold_replay(tmp_path):
    combat, table, mid = fixture(tmp_path, FULL, cl=18)
    raise_banner(combat, table, mid)
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    turn(table, mid, OWNER)
    settle(table, mid, candidate(combat, mid, 'Imperial Standard of Heaven (8 Qi, once per scene)').candidate_id)
    engine = reload(tmp_path, mid)
    zone = placed.of(engine, 'standard')[0]
    assert banner._aura(engine, zone) == 40 and set(banner._stances(engine, zone)) == set(banner.STANCES)
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    turn(table, mid, OWNER)
    before = reload(tmp_path, mid).state.actors[OWNER].resources['resource:core.qi']
    settle(table, mid, candidate(combat, mid, 'Rally the Line (2 Qi)').candidate_id,
           choices={'choice:needle.rally_allies': [ALLY]})
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources['resource:core.qi'] == before
    assert engine.state.actors[ALLY].temporary_hp == 6
    assert engine.state.actors[OWNER].temporary_hp == 0


def test_stance_can_change_on_another_creatures_turn_and_persists(tmp_path):
    combat, table, mid = fixture(tmp_path, [banner.RAISE], cl=3)
    raise_banner(combat, table, mid, stances='forward')
    prompts = settle(table, mid, table.state(mid)['menu']['end_turn'],
        choices={'choice:needle.banner_turn_stance': ['signal']})
    assert any(p['context']['reaction_source_id'] == 'choice:needle.banner_turn_stance' for p in prompts)
    engine = reload(tmp_path, mid)
    assert engine.state.current_actor_id != OWNER
    assert placed.data(placed.of(engine, 'standard')[0])['stances'] == ['signal']
    assert banner.clear_signal_passive(engine, engine.state.actors[ALLY]) == 1


def test_imperial_officers_command_is_affordable_with_one_qi(tmp_path):
    def twelve_qi(bundles):
        for pool in bundles[0]['actor_template']['resources']:
            if pool['resource_id'] == 'resource:core.qi':
                pool['initial'] = 12
        bundles[0].pop('bundle_sha256', None)
        bundles[0]['bundle_sha256'] = canonical_sha256(bundles[0])
    combat, table, mid = fixture(tmp_path, FULL, cl=18, ask=False, bundle_transform=twelve_qi)
    raise_banner(combat, table, mid)
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    turn(table, mid, OWNER)
    settle(table, mid, candidate(combat, mid, 'Imperial Standard of Heaven (8 Qi, once per scene)').candidate_id)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources['resource:core.qi'] == 1
    before = sum(e.event_type == 'REACTION_RESOLVED' and e.source_definition_id == banner.FOURFOLD for e in engine.events)
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    turn(table, mid, OWNER)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources['resource:core.qi'] == 0
    assert sum(e.event_type == 'REACTION_RESOLVED' and e.source_definition_id == banner.FOURFOLD for e in engine.events) == before + 1


def test_second_rally_same_round_keeps_movement_but_does_not_grant_hp_twice(tmp_path):
    def initiative_order(bundles):
        for bundle, bonus in zip(bundles, (100, 0, -100)):
            bundle['actor_template']['initiative_bonus'] = bonus
            bundle.pop('bundle_sha256', None)
            bundle['bundle_sha256'] = canonical_sha256(bundle)
    combat, table, mid = fixture(tmp_path, [banner.RAISE, banner.RALLY], cl=18,
        ally_talents=[banner.RAISE, banner.RALLY], bundle_transform=initiative_order)
    raise_banner(combat, table, mid, stances='forward')
    turn(table, mid, ALLY)
    settle(table, mid, candidate(combat, mid, MANIFEST, at=(3, 7)).candidate_id)
    turn(table, mid, OWNER)
    settle(table, mid, candidate(combat, mid, 'Rally the Line (2 Qi)').candidate_id,
           choices={'choice:needle.rally_allies': [ALLY], 'choice:needle.rider_step': ['cell:5,6']})
    turn(table, mid, ALLY)
    before = reload(tmp_path, mid)
    round_number = before.state.round_number
    assert (before.state.actors[ALLY].position.x, before.state.actors[ALLY].position.y) == (5, 6)
    grants = sum(e.event_type == 'TEMP_HP_GRANTED' and ALLY in e.target_ids for e in before.events)
    settle(table, mid, candidate(combat, mid, 'Rally the Line (2 Qi)').candidate_id,
           choices={'choice:needle.rally_allies': [ALLY], 'choice:needle.rider_step': ['cell:5,7']})
    engine = reload(tmp_path, mid)
    assert engine.state.round_number == round_number
    assert (engine.state.actors[ALLY].position.x, engine.state.actors[ALLY].position.y) == (5, 7)
    assert sum(e.event_type == 'TEMP_HP_GRANTED' and ALLY in e.target_ids for e in engine.events) == grants


@pytest.mark.parametrize('benefit', ['step', 'temp', 'push', 'deny', 'banner'])
def test_formation_maneuver_owner_chooses_after_native_damage(tmp_path, benefit):
    from tests.worker2_support import sealed_native_attack
    def attack(bundles):
        sealed_native_attack(bundles[1], 'Ally strike', attack_bonus=100, modifier=5)
    combat, table, mid = fixture(tmp_path, [banner.RAISE, banner.ADVANCING], cl=10,
                                bundle_transform=attack)
    raise_banner(combat, table, mid, stances='forward')
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    turn(table, mid, OWNER)
    settle(table, mid, candidate(combat, mid, 'Advancing Standard (4 Qi)').candidate_id)
    for _ in range(4):
        if table.state(mid)['menu']['actor_id'] == ALLY:
            break
        settle(table, mid, table.state(mid)['menu']['end_turn'], choices={
            'choice:needle.rider_step': None, 'choice:needle.banner_turn_move': None,
            'choice:needle.banner_turn_stance': None})
    before = reload(tmp_path, mid)
    assert before.state.current_actor_id == ALLY
    ally_before = before.state.actors[ALLY].position
    foe_before = before.state.actors[FOE].position
    zone_before = placed.of(before, 'standard')[0].center
    prompts = settle(table, mid, candidate(combat, mid, 'Ally strike', target=FOE).candidate_id,
        choices={'choice:needle.banner_maneuver': [benefit], 'choice:needle.rider_step': ['cell:4,5'],
                 'choice:needle.banner_destination': ['cell:3,7']})
    assert any(p['context']['reaction_source_id'] == 'choice:needle.banner_maneuver' for p in prompts)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[FOE].current_hp < before.state.actors[FOE].current_hp
    if benefit == 'step':
        assert engine.state.actors[ALLY].position != ally_before
    elif benefit == 'temp':
        assert engine.state.actors[ALLY].temporary_hp == 4
    elif benefit == 'push':
        assert engine.state.actors[FOE].position != foe_before
    elif benefit == 'deny':
        assert any(c.condition_id.endswith('reaction_denied') for c in engine.state.actors[FOE].conditions.values())
    else:
        assert placed.of(engine, 'standard')[0].center != zone_before

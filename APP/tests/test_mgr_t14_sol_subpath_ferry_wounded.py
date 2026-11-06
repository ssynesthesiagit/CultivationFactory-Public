"""Ferry: native acquisition, actual attacks, table decisions and cold replay.

No synthetic damage receipt or Passage/Formation flag is installed.
Authored barriers use the normal map serializer and Passage is created in play.
"""
from copy import deepcopy
import pytest

from tests.worker2_support import ALLY, FOE, OWNER, candidate, fixture, reload, settle, turn


PREFIX = 'tianxia.subpath.qi.riverway_cultivator.feature.'
FERRY = PREFIX + 'ferry_the_wounded'
REACTION = 'reaction:typed.' + FERRY
AXE = {'starting_kit': {'items': [
    {'item_id': 'tianxia.mortal.weapon.fu', 'name': 'Fu (Short Axe)', 'quantity': 1}
]}}


PASSAGE = PREFIX + 'flowing_passage'
QI = 'resource:core.qi'
OPPORTUNITY = 'reaction:typed.opportunity_attack'


@pytest.fixture(scope='module')
def acquired():
    # Keep this combat regression independent of the non-Sphere authority
    # package, which is not present in every public-CI source export.  The
    # parent-bound selected Subpath is synthetic; the compiler still resolves
    # its printed feature progression from the shipped public Subpath index.
    from tests.h1_support import sheet
    doc = sheet([], cl=6, primary='Qi', name='Wren')
    doc['path_and_subpath'] = {
        'paths': [{
            'path_id': 'tianxia.path.qi_cultivation',
            'attainment': 6,
            'effective_cl': 6,
            'status': 'ACTIVE',
        }],
        'subpaths': [{
            'subpath_id': 'tianxia.subpath.qi.riverway_cultivator',
            'owning_path_id': 'tianxia.path.qi_cultivation',
        }],
    }
    doc['ability_scores_and_statistics']['primary_resource']['maximum'] = 100
    return doc


def wounded_table(tmp_path, *, owned=True, distant=False, acquired=None, battlefield_transform=None,
                  ally_talents=(), owner_position=None, bundle_transform=None):
    """Compile ordinary sheet records and attack with a genuinely compiled weapon.

    This intentionally tests the combat adapter below character acquisition;
    do not describe the sheet's supplied ownership as a native acquisition receipt.
    """
    bundle = None
    if acquired is not None:
        from combat.factory_compiler import compile_character
        bundle = compile_character(acquired, actor_id=OWNER, reaction_plan={'ask': True})
    combat, table, mid = fixture(
        tmp_path, [FERRY] if owned else [], cl=6, named=True, foe_kit=AXE,
        positions={OWNER: owner_position or {'x': 11 if distant else 3, 'y': 6},
                   ALLY: {'x': 4, 'y': 6}, FOE: {'x': 5, 'y': 6}},
        owner_bundle=bundle, battlefield_transform=battlefield_transform, ally_talents=ally_talents,
        bundle_transform=bundle_transform,
        seed='MGR-T14-FERRY-SETTLEMENT')
    turn(table, mid, FOE)
    return combat, table, mid


def damage_ally(combat, table, mid, tmp_path, *, choices=None):
    """Find a real damaging attack, declining unrelated reactions along the way."""
    for _ in range(12):
        before = len(reload(tmp_path, mid).events)
        prompts = settle(table, mid,
            candidate(combat, mid, 'Fu (Short Axe) attack', target=ALLY).candidate_id,
            choices={REACTION: ['cell:4,7']} if choices is None else choices)
        engine = reload(tmp_path, mid)
        events = engine.events[before:]
        if any(e.event_type == 'DAMAGE_COMMITTED' and ALLY in e.target_ids
               and int(e.payload.get('hp_damage') or 0)
               + int(e.payload.get('temporary_hp_absorbed') or 0) > 0 for e in events):
            return engine, events, prompts
        # A miss still spends the Action. Advance the actual turn before
        # looking for another weapon attack by this same creature.
        settle(table, mid, table.state(mid)['menu']['end_turn'])
        turn(table, mid, FOE)
    pytest.fail('The bounded stock-weapon probe never dealt damage')


def test_ferry_response_follows_real_damage_commit_and_cold_replay(tmp_path, acquired):
    combat, table, mid = wounded_table(tmp_path, acquired=acquired)
    engine, events, prompts = damage_ally(combat, table, mid, tmp_path)
    assert any(p['context']['reaction_source_id'] == REACTION for p in prompts), prompts
    response_prompt = next(p for p in prompts if p['context']['reaction_source_id'] == REACTION)
    assert response_prompt['context']['reactor_id'] == OWNER
    damage = next(i for i, e in enumerate(events)
                  if e.event_type == 'DAMAGE_COMMITTED' and ALLY in e.target_ids)
    response = next(i for i, e in enumerate(events)
                    if e.event_type == 'REACTION_WINDOW_OPENED'
                    and e.source_definition_id == FERRY)
    compact = [(e.event_type, e.source_definition_id, e.actor_id, e.target_ids)
               for e in events if e.event_type in {
                   'DAMAGE_COMMITTED', 'REACTION_WINDOW_OPENED', 'REACTION_RESOLVED',
                   'RESOURCE_SPENT', 'TEMP_HP_GRANTED', 'MOVEMENT_COMMITTED'}]
    print('FERRY_SETTLEMENT_EVIDENCE', compact)
    assert not engine.state.actors[OWNER].reaction_available
    assert damage < response
    assert any(e.event_type == 'MOVEMENT_COMMITTED' and e.source_definition_id == FERRY for e in events)
    assert sum(int(e.payload['amount']) for e in events if e.event_type == 'RESOURCE_SPENT'
               and e.source_definition_id == FERRY) == 2
    assert not any(e.event_type == 'TEMP_HP_GRANTED' and e.source_definition_id == FERRY for e in events)


def test_ferry_step_out_of_reach_provokes_no_opportunity_attack(tmp_path, acquired):
    """Printed: "move the ally up to 10 feet without provoking." The passenger walks out of the foe's reach,
    so the same step taken as ordinary movement in the control test below asks for its Opportunity Attack."""
    combat, table, mid = wounded_table(tmp_path, acquired=acquired)
    engine, _, prompts = damage_ally(combat, table, mid, tmp_path, choices={REACTION: ['cell:4,8']})
    ally = engine.state.actors[ALLY]
    assert (ally.position.x, ally.position.y) == (4, 8)
    assert max(abs(ally.position.x - 5), abs(ally.position.y - 6)) == 2, 'the passenger left the foe reach'
    assert any(p['context']['reaction_source_id'] == REACTION for p in prompts)
    assert not any(OPPORTUNITY in str(p['context']['reaction_source_id']) for p in prompts), prompts
    assert not [e for e in engine.events if 'OPPORTUNITY' in e.event_type]
    assert engine.state.actors[FOE].reaction_available, "the foe never spent the Reaction the step did not provoke"


def test_ordinary_walk_from_the_same_square_does_provoke_that_foe(tmp_path, acquired):
    """The suppression above is real: this is the same 10 feet walked, not forced."""
    combat, table, mid = wounded_table(tmp_path, acquired=acquired)
    turn(table, mid, ALLY)
    assert not settle(table, mid, next(
        c.candidate_id for c in reload(tmp_path, mid).legal_candidates()
        if c.destination is not None and (c.destination.x, c.destination.y) == (4, 7)))
    prompts = settle(table, mid, next(
        c.candidate_id for c in reload(tmp_path, mid).legal_candidates()
        if c.destination is not None and (c.destination.x, c.destination.y) == (4, 8)))
    engine = reload(tmp_path, mid)
    assert (engine.state.actors[ALLY].position.x, engine.state.actors[ALLY].position.y) == (4, 8)
    assert any(p['context']['reaction_source_id'] == OPPORTUNITY for p in prompts), prompts


@pytest.mark.parametrize('owned,distant', [(False, False), (True, True)])
def test_wrong_owner_and_outside_thirty_feet_do_not_offer_ferry(tmp_path, owned, distant):
    combat, table, mid = wounded_table(tmp_path, owned=owned, distant=distant)
    engine, events, prompts = damage_ally(combat, table, mid, tmp_path)
    assert not any(p['context']['reaction_source_id'] == REACTION for p in prompts)
    assert not any(e.source_definition_id == FERRY and e.event_type in {
        'REACTION_WINDOW_OPENED', 'RESOURCE_SPENT', 'TEMP_HP_GRANTED'} for e in events)
    assert engine.state.actors[OWNER].reaction_available


def test_native_acquisition_parent_and_attainment_guards(acquired):
    from combat.factory_compiler import compile_character
    from combat.subpath_acquisition import acquired_features
    from tests.h1_support import ROOT
    assert acquired_features(acquired, ROOT)[FERRY] == {'cl': 6, 'min_cl': 6}
    bundle = compile_character(acquired, actor_id=OWNER)
    assert any(r['feature_id'] == FERRY for r in bundle['typed_reactions'])
    for mode in ('wrong-parent', 'low-attainment', 'unselected'):
        doc = deepcopy(acquired)
        qi_path = next(p for p in doc['path_and_subpath']['paths']
                       if p['path_id'] == 'tianxia.path.qi_cultivation')
        if mode == 'wrong-parent':
            qi_path['path_id'] = 'tianxia.path.body_refining'
        elif mode == 'low-attainment':
            qi_path['effective_cl'] = 3
        else:
            doc['path_and_subpath'] = {}
        bundle = compile_character(doc, actor_id=OWNER)
        assert not any(r['feature_id'] == FERRY for r in bundle['typed_reactions']), mode


def test_declined_ferry_keeps_qi_reaction_position_and_no_round_receipt(tmp_path, acquired):
    combat, table, mid = wounded_table(tmp_path, acquired=acquired)
    engine, events, prompts = damage_ally(combat, table, mid, tmp_path, choices={REACTION: None})
    assert any(p['context']['reaction_source_id'] == REACTION for p in prompts)
    assert engine.state.actors[OWNER].reaction_available
    position = engine.state.actors[ALLY].position
    assert (position.x, position.y, position.z) == (4, 6, 0)
    assert not any(e.source_definition_id == FERRY and e.event_type in
                   {'RESOURCE_SPENT', 'MOVEMENT_COMMITTED', 'TEMP_HP_GRANTED'} for e in events)
    assert engine.state.actors[OWNER].turn_flags.get('once_per_round:typed.'+FERRY) is None


def create_passage(combat, table, mid, *, owner=OWNER, at=(4, 7)):
    turn(table, mid, owner)
    settle(table, mid, candidate(combat, mid, 'Flowing Passage', at=at).candidate_id,
        choices={'choice:needle.flowing_passage_cell.1': ['end'],
                 'choice:needle.flowing_passage_allies': [OWNER, ALLY]})
    turn(table, mid, FOE)


def test_actual_arrival_in_native_owned_passage_grants_pb_after_movement(tmp_path, acquired):
    combat, table, mid = wounded_table(tmp_path, acquired=acquired)
    create_passage(combat, table, mid)
    engine, events, prompts = damage_ally(combat, table, mid, tmp_path,
                                         choices={REACTION: ['cell:4,7']})
    ally = engine.state.actors[ALLY]
    assert (ally.position.x, ally.position.y, ally.position.z) == (4, 7, 0)
    assert ally.temporary_hp == engine.state.actors[OWNER].proficiency_bonus
    damage = next(i for i, e in enumerate(events) if e.event_type == 'DAMAGE_COMMITTED' and ALLY in e.target_ids)
    movement = next(i for i, e in enumerate(events) if e.event_type == 'MOVEMENT_COMMITTED'
                    and e.source_definition_id == FERRY)
    reward = next(i for i, e in enumerate(events) if e.event_type == 'TEMP_HP_GRANTED'
                  and e.source_definition_id == FERRY)
    assert damage < movement < reward
    assert not any(e.event_type == 'REACTION_USED' and e.actor_id == FOE for e in events)
    assert engine.state.actors[OWNER].turn_flags['once_per_round:typed.'+FERRY] == engine.state.round_number


@pytest.mark.parametrize('barrier', ['spatial_lock', 'sealed_formation'])
def test_authored_barrier_blocks_all_ferry_routes_without_payment(tmp_path, acquired, barrier):
    def map_facts(arena):
        from combat.tabletop import battlefield_as_map, to_battlefield, normalize_map
        document = battlefield_as_map(arena)
        document['route_regions'] = [{'id': 'rescue-seal', 'kind': barrier,
            'cells': [{'x': x, 'y': y, 'z': z}
                      for x in range(3, 6) for y in range(5, 8) for z in range(2)
                      if (x, y, z) != (4, 6, 0)]}]
        arena.update(to_battlefield(normalize_map(document)))
    combat, table, mid = wounded_table(tmp_path, acquired=acquired, battlefield_transform=map_facts)
    engine, events, prompts = damage_ally(combat, table, mid, tmp_path, choices={REACTION: None})
    prompt = next(p for p in prompts if p['context']['reaction_source_id'] == REACTION)
    assert [o['id'] for o in prompt['choice']['options']] == ['cell:4,6']
    assert engine.state.actors[OWNER].reaction_available
    assert not any(e.source_definition_id == FERRY for e in events)


def test_vertical_ferry_choice_keeps_altitude_and_settles_fall_before_reward(tmp_path, acquired):
    combat, table, mid = wounded_table(tmp_path, acquired=acquired)
    engine, events, prompts = damage_ally(combat, table, mid, tmp_path,
                                         choices={REACTION: ['cell:4,7,2']})
    prompt = next(p for p in prompts if p['context']['reaction_source_id'] == REACTION)
    options = {o['id']: o for o in prompt['choice']['options']}
    assert 'cell:4,7,2' in options
    assert engine.state.actors[ALLY].position.z == 0
    movements = [e for e in events if e.event_type == 'MOVEMENT_COMMITTED'
                 and e.actor_id == ALLY]
    assert any(e.payload['destination']['z'] == 2 for e in movements)
    assert not any(e.event_type == 'TEMP_HP_GRANTED' and e.source_definition_id == FERRY for e in events)


def test_once_round_receipt_survives_reload_and_next_round_can_ferry_again(tmp_path, acquired):
    combat, table, mid = wounded_table(tmp_path, acquired=acquired)
    first, events, _ = damage_ally(combat, table, mid, tmp_path,
                                   choices={REACTION: ['cell:4,7']})
    first_round = first.state.round_number
    assert first.state.actors[OWNER].turn_flags['once_per_round:typed.'+FERRY] == first_round
    # The ally remains next to the real weapon user. The owner's next turn
    # refreshes its Reaction; the round receipt, rather than turn flags, gates it.
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    turn(table, mid, OWNER)
    turn(table, mid, FOE)
    second, events, prompts = damage_ally(combat, table, mid, tmp_path,
                                         choices={REACTION: ['cell:4,6']})
    assert second.state.round_number > first_round
    assert any(p['context']['reaction_source_id'] == REACTION for p in prompts)
    assert second.state.actors[OWNER].turn_flags['once_per_round:typed.'+FERRY] == second.state.round_number


def test_another_owners_native_passage_grants_no_ferry_temp_hp(tmp_path, acquired):
    combat, table, mid = wounded_table(tmp_path, acquired=acquired, ally_talents=[PASSAGE])
    create_passage(combat, table, mid, owner=ALLY)
    engine, events, _ = damage_ally(combat, table, mid, tmp_path,
                                   choices={REACTION: ['cell:4,7']})
    assert (engine.state.actors[ALLY].position.x, engine.state.actors[ALLY].position.y) == (4, 7)
    assert not any(e.event_type == 'TEMP_HP_GRANTED' and e.source_definition_id == FERRY for e in events)


def test_unaffordable_ferry_does_not_offer_or_spend(tmp_path, acquired):
    doc = deepcopy(acquired)
    doc['ability_scores_and_statistics']['primary_resource']['maximum'] = 1
    combat, table, mid = wounded_table(tmp_path, acquired=doc)
    engine, events, prompts = damage_ally(combat, table, mid, tmp_path)
    assert not any(p['context']['reaction_source_id'] == REACTION for p in prompts)
    assert engine.state.actors[OWNER].reaction_available
    assert not any(e.source_definition_id == FERRY for e in events)


@pytest.mark.parametrize('spend', [False, True])
def test_canceled_ferry_uses_native_payment_ownership_and_never_moves(tmp_path, acquired, monkeypatch, spend):
    from tests.test_lock9_interception_review import hook
    def cancel(engine, user, action, *args):
        if action.source_definition_id == FERRY:
            return {'source_id': 'test:interception', 'label': 'Rescue interrupted',
                    'cancel': True, 'spend_activation': spend}
    hook(monkeypatch, 'technique_declared', cancel)
    combat, table, mid = wounded_table(tmp_path, acquired=acquired)
    engine, events, prompts = damage_ally(combat, table, mid, tmp_path)
    assert any(p['context']['reaction_source_id'] == REACTION for p in prompts)
    assert engine.state.actors[OWNER].reaction_available is not spend
    assert not any(e.event_type in {'MOVEMENT_COMMITTED', 'TEMP_HP_GRANTED'}
                   and e.source_definition_id == FERRY for e in events)
    assert sum(e.payload['amount'] for e in events if e.event_type == 'RESOURCE_SPENT'
               and e.source_definition_id == FERRY) == (2 if spend else 0)


def test_unperceived_wounded_ally_does_not_offer_ferry_within_range(tmp_path, acquired):
    def wall(arena):
        arena['terrain_regions'].append({'terrain_type': 'BLOCKED', 'movement_cost': 5,
            'cells': [{'x': 3, 'y': y} for y in range(arena['height_squares'])]})
    combat, table, mid = wounded_table(tmp_path, acquired=acquired, owner_position={'x': 2, 'y': 6},
                                      battlefield_transform=wall)
    engine, events, prompts = damage_ally(combat, table, mid, tmp_path)
    assert engine._distance_actor_to_actor(engine.state.actors[OWNER], engine.state.actors[ALLY]) <= 30
    assert not any(p['context']['reaction_source_id'] == REACTION for p in prompts)
    assert engine.state.actors[OWNER].reaction_available


def test_local_auto_ferry_answers_off_turn_without_model_server(tmp_path, acquired):
    def reliable_attack(bundles):
        # Exercise the automatic off-turn reaction immediately, not unrelated
        # AI primary-action turns after a missed weapon attack (seed rolls 7).
        from combat.canonical import canonical_sha256
        foe = next(b for b in bundles if b['actor_id'] == FOE)
        for action in foe['action_catalog']:
            if action['display_name'] == 'Fu (Short Axe) attack':
                action['attack_bonus'] = 100
                action['parameters']['typed']['numbers']['attack_bonus'] = 100
        foe.pop('bundle_sha256', None)
        foe['bundle_sha256'] = canonical_sha256(foe)
    combat, table, mid = wounded_table(tmp_path, acquired=acquired, bundle_transform=reliable_attack)
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    engine, events, prompts = damage_ally(combat, table, mid, tmp_path)
    assert not any(p['context']['reaction_source_id'] == REACTION for p in prompts)
    assert any(e.event_type == 'REACTION_RESOLVED' and e.source_definition_id == FERRY for e in events)
    assert not engine.state.actors[OWNER].reaction_available


def test_shortened_ferry_reward_uses_settled_endpoint_inside_passage(tmp_path, acquired, monkeypatch):
    from tests.test_lock9_interception_review import hook
    hook(monkeypatch, 'forced_movement_reduction',
         lambda ctx, target: 5 if ctx.source == FERRY and target.entity_id == ALLY else None)
    combat, table, mid = wounded_table(tmp_path, acquired=acquired)
    create_passage(combat, table, mid, at=(4, 7))
    engine, events, _ = damage_ally(combat, table, mid, tmp_path,
                                    choices={REACTION: ['cell:4,8']})
    ally = engine.state.actors[ALLY]
    # The selected 10-foot destination was shortened by 5 feet; reward the
    # actual endpoint because that intermediate cell lies in the owner's Passage.
    assert (ally.position.x, ally.position.y, ally.position.z) == (4, 7, 0)
    assert ally.temporary_hp == engine.state.actors[OWNER].proficiency_bonus
    movement = next(e for e in events if e.event_type == 'MOVEMENT_COMMITTED'
                    and e.source_definition_id == FERRY)
    assert {**movement.payload['destination'], 'z': movement.payload['destination'].get('z', 0)} == {'x': 4, 'y': 7, 'z': 0}
    assert any(e.event_type == 'TEMP_HP_GRANTED' and e.source_definition_id == FERRY
               for e in events)
    # The event/state assertion is against a cold table reload from damage_ally.
    reloaded = reload(tmp_path, mid)
    assert reloaded.state.actors[ALLY].temporary_hp == engine.state.actors[OWNER].proficiency_bonus


def test_native_forced_movement_defense_prevents_arrival_and_reward(tmp_path, acquired, monkeypatch):
    from tests.test_lock9_interception_review import hook
    hook(monkeypatch, 'forced_movement_reduction',
         lambda ctx, target: 10 if ctx.source == FERRY and target.entity_id == ALLY else None)
    combat, table, mid = wounded_table(tmp_path, acquired=acquired)
    create_passage(combat, table, mid)
    engine, events, _ = damage_ally(combat, table, mid, tmp_path, choices={REACTION: ['cell:4,7']})
    assert (engine.state.actors[ALLY].position.x, engine.state.actors[ALLY].position.y) == (4, 6)
    assert not any(e.event_type == 'TEMP_HP_GRANTED' and e.source_definition_id == FERRY for e in events)
    assert not engine.state.actors[OWNER].reaction_available
    assert engine.state.actors[OWNER].turn_flags['once_per_round:typed.'+FERRY] == engine.state.round_number


def test_native_cost_refund_does_not_duplicate_ferry_or_erase_round_receipt(tmp_path, acquired, monkeypatch):
    from combat.technique_costs import refund
    from tests.test_lock9_interception_review import hook
    def refunding_payment(engine, owner, row, costs):
        if row.get('feature_id') != FERRY:
            return None
        # Isolate the existing alternate-payment/refund contract, not a new
        # Ferry entitlement: spend/refund real resources under the native scope.
        engine._spend_resource(owner, QI, 2, FERRY)
        assert refund(engine, owner, FERRY, ((QI, 2),), QI, 2, 'test:refund') == 2
        return []
    hook(monkeypatch, 'generic_reaction_payment', refunding_payment)
    combat, table, mid = wounded_table(tmp_path, acquired=acquired)
    engine, events, _ = damage_ally(combat, table, mid, tmp_path, choices={REACTION: ['cell:4,7']})
    assert len([e for e in events if e.event_type == 'RESOURCE_SPENT'
                and e.source_definition_id == FERRY]) == 1
    assert len([e for e in events if e.event_type == 'MOVEMENT_COMMITTED'
                and e.source_definition_id == FERRY]) == 1
    assert not engine.state.actors[OWNER].reaction_available
    assert engine.state.actors[OWNER].turn_flags['once_per_round:typed.'+FERRY] == engine.state.round_number


def test_up_to_ten_feet_keeps_zero_distance_choice_and_native_passage_reward(tmp_path, acquired):
    combat, table, mid = wounded_table(tmp_path, acquired=acquired)
    create_passage(combat, table, mid, at=(4, 6))
    engine, events, _ = damage_ally(combat, table, mid, tmp_path, choices={REACTION: ['cell:4,6']})
    assert (engine.state.actors[ALLY].position.x, engine.state.actors[ALLY].position.y) == (4, 6)
    assert engine.state.actors[ALLY].temporary_hp == engine.state.actors[OWNER].proficiency_bonus
    assert not any(e.event_type == 'MOVEMENT_COMMITTED' and e.source_definition_id == FERRY for e in events)
    assert any(e.event_type == 'REACTION_RESOLVED' and e.source_definition_id == FERRY
               and e.payload['arrived'] == 1 for e in events)

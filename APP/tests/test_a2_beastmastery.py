"""Second-pass Beastmastery: table transactions, session intents and cold replay."""
import pytest
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, settle, turn, reload
from tests.cw2_service_support import add_action, seal
from combat.ext import mounts

STEADY = 'TAL_BEASTMASTERY_STEADY_HANDLER'
CONNECTION = 'TAL_BEASTMASTERY_FOCUSING_CONNECTION'
SADDLE = 'TAL_BEASTMASTERY_SHARED_SADDLE_RHYTHM'
CHOICE = 'choice:needle.beastmastery.steady_handler'
FOCUS = 'resource:core.martial_focus'


def setup(tmp_path, talents=(STEADY,), *, beasts=1, mount='', ask=True, **layout):
    def prepare(bundles):
        for bundle in bundles:
            for name, ability, skill in [('Animal check', 'WIS', 'Animal Handling'),
                                          ('Other check', 'WIS', 'Perception')]:
                add_action(bundle, name, [{'type': 'contest_against',
                    'actor_check': {'kind': 'check', 'ability': ability, 'skill': skill},
                    'target_check': {'kind': 'dc', 'dc': 15}}])
            add_action(bundle, 'Spend focus', [{'type': 'spend_resource', 'resource_id': FOCUS,
                                              'flat': 1, 'applies_to': 'self'}], target='SELF')
            seal(bundle)
    return fixture(tmp_path, list(talents), primary='Body', ask=ask,
                   owner_plan={'beasts': ['wolf'] * beasts, 'mount': mount},
                   bundle_transform=prepare, seed='A2BEASTMAS', **layout)


def use(combat, table, mid, name, *, target=None, picks=None):
    return settle(table, mid, candidate(combat, mid, name, target=target).candidate_id,
                  choices=picks or {})


@pytest.mark.parametrize('accept', [False, True])
def test_steady_handler_decides_before_draw_and_reload(tmp_path, accept):
    combat, table, mid = setup(tmp_path)
    before = reload(tmp_path, mid)
    from tests.test_r9i_karma_persistence import act
    paused = act(table, mid, candidate(combat, mid, 'Animal check', target=FOE).candidate_id)
    assert paused['status'] == 'REACTION_REQUIRED'
    assert reload(tmp_path, mid).state.model_dump(mode='json') == before.state.model_dump(mode='json')
    prompts = use(combat, table, mid, 'Animal check', target=FOE,
                  picks={CHOICE: 'ten' if accept else None})
    assert any(p['context']['reaction_source_id'] == CHOICE for p in prompts)
    p = next(p for p in prompts if p['context']['reaction_source_id'] == CHOICE)
    assert 'observed d20' not in str(p).lower()
    assert p['action'] == 'Animal check'
    assert p['trigger_actor'] == before.state.actors[OWNER].display_name
    assert p['affected'] == before.state.actors[OWNER].display_name
    assert 'wisdom (animal handling)' in p['moment'].lower() and 'expend martial focus' in p['moment'].lower()
    e = reload(tmp_path, mid)
    rewritten = [ev for ev in e.events if ev.source_definition_id == STEADY and ev.event_type == 'D20_REWRITTEN']
    assert len(rewritten) == int(accept)
    if accept:
        assert rewritten[0].payload['timing'] == 'before_roll'
        assert rewritten[0].payload['result']['natural_result'] == 10
        check = [ev for ev in e.events if ev.event_type == 'CHECK_ROLLED'][-1]
        assert check.payload['actor']['natural_result'] == 10
    assert e.state.actors[OWNER].resources[FOCUS] == before.state.actors[OWNER].resources[FOCUS] - int(accept)
    use(combat, table, mid, 'Other check', target=FOE)
    assert len([ev for ev in reload(tmp_path, mid).events if ev.source_definition_id == STEADY
                and ev.event_type == 'D20_REWRITTEN']) == int(accept)


@pytest.mark.parametrize('beasts', [0, 1])
def test_connection_requires_contact_then_regains_focus(tmp_path, beasts):
    combat, table, mid = setup(tmp_path, (CONNECTION, 'TAL_BEASTMASTERY_BEAST_TAMER'), beasts=beasts)
    use(combat, table, mid, 'Spend focus')
    e = reload(tmp_path, mid)
    assert e.state.actors[OWNER].resources[FOCUS] == 0
    offered = [c for c in e.legal_candidates() if e.action_catalog.get(c.source_definition_id)
               and e.action_catalog[c.source_definition_id].display_name == 'Focusing Connection']
    assert bool(offered) == bool(beasts)
    if beasts:
        use(combat, table, mid, 'Focusing Connection')
        e = reload(tmp_path, mid)
        assert e.state.actors[OWNER].resources[FOCUS] == 1
        assert not e.state.actors[OWNER].action_available


@pytest.mark.parametrize('pick', ['focus', 'temp', 'move', 'move_disengaged'])
def test_shared_saddle_rhythm_one_choice_per_round(tmp_path, pick):
    combat, table, mid = setup(tmp_path, (SADDLE, 'BEASTMASTERY_BASE_RIDER_PACKAGE'), beasts=0, mount='warhorse')
    use(combat, table, mid, 'Spend focus')
    use(combat, table, mid, 'Mount: Disengage' if pick == 'move_disengaged' else 'Mount: Dodge')
    names = {'focus': 'Shared Saddle Rhythm: regain Martial Focus',
             'temp': 'Shared Saddle Rhythm: mount gains Temporary HP',
             'move': 'Shared Saddle Rhythm: move 5 ft, no Opportunity Attacks'}
    before = reload(tmp_path, mid)
    use(combat, table, mid, names['move' if pick == 'move_disengaged' else pick])
    e = reload(tmp_path, mid)
    owner = e.state.actors[OWNER]; mount = mounts.mount_of(e, owner)
    assert owner.turn_flags['saddle_rhythm_round_used'] == e.state.round_number
    assert not any(c.display_name.startswith('Shared Saddle Rhythm') for c in e.legal_candidates())
    if pick == 'focus': assert owner.resources[FOCUS] == 1
    if pick == 'temp': assert mount.temporary_hp == owner.proficiency_bonus
    if pick.startswith('move'):
        assert owner.movement_remaining_ft == before.state.actors[OWNER].movement_remaining_ft + 5
        assert owner.turn_flags['oa_free_ft'] == 5
        movement = next(c for c in e.legal_candidates() if c.kind == 'MOVE' and c.movement_cost_ft == 5)
        start = owner.position
        budget = owner.movement_remaining_ft
        sequence = e.state.event_sequence
        settle(table, mid, movement.candidate_id)
        e = reload(tmp_path, mid)
        assert e.state.actors[OWNER].position != start
        assert e.state.actors[OWNER].movement_remaining_ft == budget - 5
        assert e.state.actors[OWNER].turn_flags['oa_free_ft'] == (5 if pick == 'move_disengaged' else 0)
        assert not any(ev.event_type == 'REACTION_RESOLVED' and ev.sequence > sequence
                       and ev.source_definition_id == 'system:combat.opportunity_attack' for ev in e.events)

ENCIRCLE = 'TAL_BEASTMASTERY_PACK_ENCIRCLEMENT'


def pack_setup(tmp_path, count=2, *, ally_position=None, ask=True, owner_ac=14, foe_position=None,
               third_multi_attack=False):
    from tests.worker2_support import sealed_native_attack
    def prepare(bundles):
        for bundle in bundles:
            sealed_native_attack(bundle, 'Pack test attack', attack_bonus=100, modifier=0,
                                 damage_type='BLUDGEONING')
            for index, beast in enumerate(bundle.get('summons') or []):
                sealed_native_attack(beast, 'Pack test attack', attack_bonus=100, modifier=0,
                                     attacks=2 if third_multi_attack and index == 2 else 1,
                                     damage_type='BLUDGEONING')
                seal(beast)
            seal(bundle)
    return fixture(tmp_path, ['TAL_BEASTMASTERY_BEAST_TAMER', ENCIRCLE],
                   owner_plan={'beasts': ['wolf'] * count, 'mount': ''}, primary='Body',
                   bundle_transform=prepare, foe_position=foe_position or {'x': 3, 'y': 4}, ally_position=ally_position,
                   seed='A2-PACK', ask=ask, owner_ac=owner_ac)


@pytest.mark.parametrize('count', [1, 2])
def test_encirclement_disengage_applies_only_to_threatening_beasts(tmp_path, count):
    from combat.ext import beastmastery_pack as pack
    from combat.opportunity_protection import disengage_protects
    combat, table, mid = pack_setup(tmp_path, count)
    turn(table, mid, FOE)
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    use(combat, table, mid, 'Disengage')
    e = reload(tmp_path, mid)
    foe = e.state.actors[FOE]
    beasts = pack.beast_allies(e, e.state.actors[OWNER])
    assert len(pack.threatening_pack(e, e.state.actors[OWNER], foe)) == count
    assert disengage_protects(e, e.state.actors[OWNER], foe)
    assert disengage_protects(e, e.state.actors[ALLY], foe)
    for b in beasts:
        assert disengage_protects(e, b, foe) == (count == 1)
    moves = [c for c in e.legal_candidates() if c.kind == 'MOVE']
    cid = next(c.candidate_id for c in moves if any(e._distance_actor_to_actor(foe, b) <= 5
               < e._distance_actor_to_actor(foe, b, actor_position=c.destination) for b in beasts))
    settle(table, mid, cid)
    e = reload(tmp_path, mid)
    reactions = [ev for ev in e.events if ev.event_type == 'REACTION_RESOLVED'
                 and ev.source_definition_id == 'system:combat.opportunity_attack']
    assert bool(reactions) == (count == 2)
    if count == 1:
        assert not any(ev.event_type == 'REACTION_DECLINED'
                       and ev.payload.get('checkpoint') == 'LEAVE_REACH' for ev in e.events)
    assert all(ev.actor_id in {b.entity_id for b in beasts} for ev in reactions)


def test_first_pack_hit_reduces_enemy_speed_once_and_expires(tmp_path):
    from combat.ext import beastmastery_pack as pack
    combat, table, mid = pack_setup(tmp_path)
    e = reload(tmp_path, mid); baseline = e._effective_speed(e.state.actors[FOE])
    beasts = [b.entity_id for b in pack.beast_allies(e, e.state.actors[OWNER])]
    for b in beasts:
        turn(table, mid, b)
        use(combat, table, mid, 'Pack test attack', target=FOE)
        e = reload(tmp_path, mid)
        assert e._effective_speed(e.state.actors[FOE]) == baseline - 10
    turn(table, mid, FOE)
    e = reload(tmp_path, mid)
    assert e._effective_speed(e.state.actors[FOE]) == baseline


def test_non_threatening_owned_beast_can_land_first_pack_hit_at_range(tmp_path):
    from combat.ext import beastmastery_pack as pack
    combat, table, mid = pack_setup(tmp_path, count=3, third_multi_attack=True)
    e = reload(tmp_path, mid)
    owner = e.state.actors[OWNER]
    beasts = pack.beast_allies(e, owner)
    ranged_hitter = beasts[2]
    # Move the third Beast Ally outside melee reach while keeping it inside
    # its legal ranged attack and command ranges through the table service.
    turn(table, mid, ranged_hitter.entity_id)
    e = reload(tmp_path, mid)
    moves = [c for c in e.legal_candidates() if c.kind == 'MOVE' and c.destination]
    in_command_range = [c for c in moves if e._distance_actor_to_actor(
        ranged_hitter, e.state.actors[FOE], actor_position=c.destination) <= 30]
    cid = max(in_command_range, key=lambda c: e._distance_actor_to_actor(
        ranged_hitter, e.state.actors[FOE], actor_position=c.destination)).candidate_id
    settle(table, mid, cid)
    e = reload(tmp_path, mid)
    hitter = e.state.actors[ranged_hitter.entity_id]
    foe = e.state.actors[FOE]
    assert e._distance_actor_to_actor(hitter, foe) > 5
    assert e._distance_actor_to_actor(hitter, foe) <= 30
    assert len(pack.threatening_pack(e, e.state.actors[OWNER], foe)) >= 2

    baseline = e._effective_speed(foe)
    # Moving ends this fixture actor's current activation; take its next
    # scheduled turn so it can make the ranged attack with its Action.
    turn(table, mid, FOE)
    turn(table, mid, ranged_hitter.entity_id)
    use(combat, table, mid, 'Pack test attack', target=FOE)
    e = reload(tmp_path, mid)
    assert e._effective_speed(e.state.actors[FOE]) == baseline - 10
    receipt = e.state.actors[OWNER].turn_flags['_round_pack_encirclement_hits']
    assert receipt[FOE] == e.state.round_number

    # The third beast's Action is a two-strike test action: both hits land in
    # one round, but the persisted receipt remains a single round marker.
    turn(table, mid, FOE)
    e = reload(tmp_path, mid)
    assert e._effective_speed(e.state.actors[FOE]) == baseline


@pytest.mark.parametrize('auto', [False, True])
def test_attacking_pack_offers_only_another_beast_not_ordinary_allies_or_enemy(tmp_path, auto):
    from combat.ext import beastmastery_pack as pack
    combat, table, mid = pack_setup(tmp_path, ally_position={'x': 4, 'y': 4})
    e = reload(tmp_path, mid); beasts = pack.beast_allies(e, e.state.actors[OWNER])
    defender, mover = beasts
    # Both sides are inside the recipient radius, not merely on the map.
    assert e._distance_actor_to_actor(e.state.actors[FOE], e.state.actors[ALLY]) <= 5
    assert e._distance_actor_to_actor(e.state.actors[FOE], mover) <= 5
    turn(table, mid, FOE)
    if auto:
        combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    before = reload(tmp_path, mid)
    prompts = use(combat, table, mid, 'Pack test attack', target=defender.entity_id,
                  picks={'choice:needle.beastmastery.encircle_beast': mover.entity_id})
    if not auto:
        p = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.beastmastery.encircle_beast')
        assert {o['id'] for o in p['choice']['options']} == {mover.entity_id}
    e = reload(tmp_path, mid)
    moved = [ev for ev in e.events if ev.event_type == 'MOVEMENT_COMMITTED' and ev.source_definition_id == ENCIRCLE]
    assert moved and {ev.actor_id for ev in moved} == {mover.entity_id}
    assert e.state.actors[ALLY].position == before.state.actors[ALLY].position
    assert e.state.actors[FOE].position == before.state.actors[FOE].position
    assert e.state.actors[mover.entity_id].reaction_available == before.state.actors[mover.entity_id].reaction_available


def test_willing_mount_alone_is_not_contact_with_a_tame_creature(tmp_path):
    combat, table, mid = setup(tmp_path, (CONNECTION, 'BEASTMASTERY_BASE_RIDER_PACKAGE'), beasts=0, mount='warhorse')
    use(combat, table, mid, 'Spend focus')
    e = reload(tmp_path, mid)
    assert mounts.mount_of(e, e.state.actors[OWNER]) is not None
    assert not any(e.action_catalog.get(c.source_definition_id) and
                   e.action_catalog[c.source_definition_id].display_name == 'Focusing Connection'
                   for c in e.legal_candidates())


def test_steady_handler_reaches_acrobatic_mounted_overrun(tmp_path):
    combat, table, mid = setup(tmp_path, (STEADY, 'BEASTMASTERY_BASE_RIDER_PACKAGE',
            'TAL_BEASTMASTERY_RUN_DOWN', 'tianxia.talent.beastmastery.acrobatic_mount'), beasts=0, mount='warhorse', ally_position={'x': 4, 'y': 3}, foe_position={'x': 2, 'y': 6})
    prompts = use(combat, table, mid, 'Mount: Overrun (Action)', target=FOE, picks={CHOICE: 'ten'})
    assert any(p['context']['reaction_source_id'] == CHOICE for p in prompts)
    e = reload(tmp_path, mid)
    rewritten = [ev for ev in e.events if ev.event_type == 'D20_REWRITTEN' and ev.source_definition_id == STEADY]
    assert len(rewritten) == 1 and rewritten[0].payload['timing'] == 'before_roll'
    roll = [ev for ev in e.events if ev.event_type == 'CHECK_ROLLED'][-1].payload['actor']
    assert roll['natural_result'] == 10 and roll['actor_id'] == OWNER
    assert set(roll['dice']) == {10}
    assert e.state.actors[OWNER].resources[FOCUS] == 0


def test_temporary_beast_tamer_creature_supplies_connection_contact(tmp_path):
    combat, table, mid = setup(tmp_path, (CONNECTION, 'TAL_BEASTMASTERY_BEAST_TAMER'),
                              beasts=0, owner_dc=100, foe_position={'x': 3, 'y': 5})
    use(combat, table, mid, 'Beast Tamer', target=FOE)
    e = reload(tmp_path, mid)
    assert e.state.actors[OWNER].resources[FOCUS] == 0
    assert any(c.condition_id == 'condition:typed.charmed'
               and c.source_actor_id == OWNER
               and (e.action_catalog[c.source_definition_id].parameters or {}).get('typed', {}).get('source')
                   == 'TAL_BEASTMASTERY_BEAST_TAMER' for c in e.state.actors[FOE].conditions.values())
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    turn(table, mid, OWNER)
    use(combat, table, mid, 'Focusing Connection')
    assert reload(tmp_path, mid).state.actors[OWNER].resources[FOCUS] == 1


def test_hostile_relation_removes_owned_beast_from_ai_pack_recipients(tmp_path):
    from combat.ext import beastmastery_pack as pack
    combat, table, mid = pack_setup(tmp_path, ally_position={'x': 4, 'y': 4})
    e = reload(tmp_path, mid)
    defender, hostile = pack.beast_allies(e, e.state.actors[OWNER])
    combat.change_relations(mid, change={'kind': 'ACTOR_RELATION', 'subject': OWNER,
                              'other': hostile.entity_id, 'relation': 'ENEMY'},
                            expected_state_version=e.state.state_version)
    e = reload(tmp_path, mid)
    assert hostile.entity_id not in {b.entity_id for b in pack.beast_allies(e, e.state.actors[OWNER])}
    turn(table, mid, FOE)
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    before = reload(tmp_path, mid).state.event_sequence
    use(combat, table, mid, 'Pack test attack', target=defender.entity_id)
    assert not any(ev.event_type == 'MOVEMENT_COMMITTED' and ev.source_definition_id == ENCIRCLE
                   and ev.sequence > before for ev in reload(tmp_path, mid).events)


@pytest.mark.parametrize('relation', ['ALLY', 'NEUTRAL'])
def test_nonhostile_beast_does_not_threaten_for_disengage_or_speed(tmp_path, relation):
    from combat.ext import beastmastery_pack as pack
    from combat.opportunity_protection import disengage_protects
    combat, table, mid = pack_setup(tmp_path)
    e = reload(tmp_path, mid)
    beasts = pack.beast_allies(e, e.state.actors[OWNER])
    nonhostile = beasts[1]
    combat.change_relations(mid, change={'kind': 'ACTOR_RELATION', 'subject': nonhostile.entity_id,
                              'other': FOE, 'relation': relation},
                            expected_state_version=e.state.state_version)
    e = reload(tmp_path, mid)
    foe = e.state.actors[FOE]
    assert [b.entity_id for b in pack.threatening_pack(e, e.state.actors[OWNER], foe)] == [beasts[0].entity_id]
    turn(table, mid, FOE)
    use(combat, table, mid, 'Disengage')
    e = reload(tmp_path, mid)
    # The one remaining hostile beast honors Disengage; the override ally is not
    # counted as a second surrounding threat.
    assert disengage_protects(e, e.state.actors[beasts[0].entity_id], e.state.actors[FOE])
    moves = [c for c in e.legal_candidates() if c.kind == 'MOVE']
    cid = next(c.candidate_id for c in moves if any(e._distance_actor_to_actor(e.state.actors[FOE], b) <= 5
               < e._distance_actor_to_actor(e.state.actors[FOE], b, actor_position=c.destination)
               for b in pack.beast_allies(e, e.state.actors[OWNER])))
    settle(table, mid, cid)
    e = reload(tmp_path, mid)
    assert not any(ev.event_type == 'REACTION_RESOLVED' and ev.source_definition_id == 'system:combat.opportunity_attack'
                   for ev in e.events)
    baseline = e._effective_speed(e.state.actors[FOE])
    turn(table, mid, beasts[0].entity_id)
    use(combat, table, mid, 'Pack test attack', target=FOE)
    e = reload(tmp_path, mid)
    assert e._effective_speed(e.state.actors[FOE]) == baseline


def test_pack_recipient_friendly_to_attacker_is_excluded(tmp_path):
    from combat.ext import beastmastery_pack as pack
    combat, table, mid = pack_setup(tmp_path, count=3)
    e = reload(tmp_path, mid)
    defender, friendly_recipient, hostile_recipient = pack.beast_allies(e, e.state.actors[OWNER])
    combat.change_relations(mid, change={'kind': 'ACTOR_RELATION', 'subject': friendly_recipient.entity_id,
                              'other': FOE, 'relation': 'ALLY'},
                            expected_state_version=e.state.state_version)
    e = reload(tmp_path, mid)
    assert len(pack.threatening_pack(e, e.state.actors[OWNER], e.state.actors[FOE])) == 2
    turn(table, mid, FOE)
    prompts = use(combat, table, mid, 'Pack test attack', target=defender.entity_id,
                  picks={'choice:needle.beastmastery.encircle_beast': 'first'})
    p = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.beastmastery.encircle_beast')
    assert {o['id'] for o in p['choice']['options']} == {hostile_recipient.entity_id}


def test_encirclement_prompts_name_trigger_and_remain_with_owner(tmp_path):
    combat, table, mid = pack_setup(tmp_path, ally_position={'x': 4, 'y': 4})
    e = reload(tmp_path, mid); defender, mover = __import__('combat.ext.beastmastery_pack', fromlist=['beast_allies']).beast_allies(e, e.state.actors[OWNER])
    turn(table, mid, FOE)
    prompts = use(combat, table, mid, 'Pack test attack', target=defender.entity_id,
                  picks={'choice:needle.beastmastery.encircle_beast': mover.entity_id})
    choices = [p for p in prompts if p['context']['reaction_source_id'].startswith('choice:needle.beastmastery.encircle_')]
    assert len(choices) == 2
    for p in choices:
        assert p['context']['reactor_id'] == OWNER
        assert p['action'] == 'Pack test attack'
        assert p['trigger_actor'] == e.state.actors[FOE].display_name
        assert p['affected'] == defender.display_name
        assert 'attacked' in p['moment'] and 'Pack test attack' in p['moment']
        assert 'no action or reaction' in p['moment'].lower()


@pytest.mark.parametrize('decline', [False, True])
def test_enemy_ai_step_pauses_for_player_pack_decisions_without_generic_ask(tmp_path, monkeypatch, decline):
    combat, table, mid = pack_setup(tmp_path, ally_position={'x': 4, 'y': 4}, ask=False,
                                    owner_ac=30, foe_position={'x': 2, 'y': 4})
    e = reload(tmp_path, mid); defender, mover = __import__('combat.ext.beastmastery_pack', fromlist=['beast_allies']).beast_allies(e, e.state.actors[OWNER])
    combat.change_relations(mid, change={'kind': 'ACTOR_RELATION', 'subject': FOE,
                              'other': ALLY, 'relation': 'ALLY'},
                            expected_state_version=e.state.state_version)
    turn(table, mid, FOE)
    combat.set_controller_mode(mid, actor_id=FOE, controller_mode='LOCAL_AUTO')
    assert table.state(mid)['menu']['actor_id'] == FOE
    e = reload(tmp_path, mid)
    assert OWNER in combat._load_session(mid).engine.typed_ask_reactors
    attack = next(a for a in e.action_catalog.values()
                  if a.owner_id == FOE and a.display_name == 'Pack test attack')
    foe_candidates = combat._legal_candidates(combat._load_session(mid), knowledge_only=True)
    pack_attack_candidates = [c for c in foe_candidates if c.source_definition_id == attack.source_definition_id
                              and defender.entity_id in c.target_ids]
    assert pack_attack_candidates, [(c.display_name, c.source_definition_id, c.target_ids) for c in foe_candidates]
    # Keep the controller's real choice and execution path, while limiting this
    # deterministic fixture to the visible pack attack under test.
    choose_primary = combat.controller.choose_primary_action
    monkeypatch.setattr(combat.controller, 'choose_primary_action', lambda context:
        choose_primary(context.model_copy(update={'legal_candidates': (pack_attack_candidates[0],)})))
    answers = []
    prompts = []
    for _ in range(8):
        result = table.auto_step(mid, 0, answers)
        if result['status'] == 'COMMITTED':
            if prompts or table.state(mid)['menu']['actor_id'] != FOE:
                break
            continue
        if result['status'] != 'REACTION_REQUIRED':
            break
        p = result['reaction']; prompts.append(p)
        assert p['context']['reactor_id'] == OWNER
        rid = p['context']['reaction_source_id']
        selection = (None if decline else mover.entity_id) if rid.endswith('encircle_beast') else (p['choice']['options'][0]['id'] if rid.endswith('encircle_move') else None)
        answers.append({**p['context'], 'selection': 'USE' if selection else 'DECLINE',
                        **({'option_ids': [selection]} if selection else {})})
    event_summary = [(ev.event_type, ev.actor_id, ev.source_definition_id, ev.target_ids)
                     for ev in reload(tmp_path, mid).events[-12:]]
    assert len(prompts) == (1 if decline else 2), (result['status'], event_summary)
    assert result['status'] == 'COMMITTED', result
    loaded = reload(tmp_path, mid)
    moved = any(ev.event_type == 'MOVEMENT_COMMITTED' and ev.source_definition_id == ENCIRCLE
                and ev.actor_id == mover.entity_id for ev in loaded.events)
    assert moved is not decline


@pytest.mark.parametrize('accept', [False, True])
def test_enemy_ai_step_routes_off_turn_steady_handler_without_generic_ask(tmp_path, monkeypatch, accept):
    def prepare(bundles):
        for bundle in bundles:
            for name, ability, skill in [('Animal check', 'WIS', 'Animal Handling'),
                                          ('Other check', 'WIS', 'Perception')]:
                add_action(bundle, name, [{'type': 'contest_against',
                    'actor_check': {'kind': 'check', 'ability': ability, 'skill': skill},
                    'target_check': {'kind': 'dc', 'dc': 15}}])
            add_action(bundle, 'Spend focus', [{'type': 'spend_resource', 'resource_id': FOCUS,
                                              'flat': 1, 'applies_to': 'self'}], target='SELF')
            seal(bundle)
        add_action(bundles[2], 'Hostile animal contest', [{'type': 'contest_against', 'harmful': True,
            'actor_check': {'kind': 'dc', 'dc': 10},
            'target_check': {'kind': 'check', 'ability': 'WIS', 'skill': 'Animal Handling'},
            'on_success': [], 'on_fail': []}], target='HOSTILE_ENTITY')
        seal(bundles[2])

    combat, table, mid = fixture(tmp_path, [STEADY], primary='Body', ask=False,
                                 bundle_transform=prepare, seed='A2-STEADY-AI')
    turn(table, mid, FOE)
    combat.set_controller_mode(mid, actor_id=FOE, controller_mode='LOCAL_AUTO')
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    assert not any(row.get('ask') for row in engine.typed_reaction_rows.get(OWNER, []))
    assert OWNER in combat._load_session(mid).engine.typed_ask_reactors
    session = combat._load_session(mid)
    candidates = combat._legal_candidates(session, knowledge_only=True)
    source = next(a.source_definition_id for a in engine.action_catalog.values()
                  if a.owner_id == FOE and a.display_name == 'Hostile animal contest')
    candidate_row = next(c for c in candidates if c.source_definition_id == source and OWNER in c.target_ids)
    choose_primary = combat.controller.choose_primary_action
    monkeypatch.setattr(combat.controller, 'choose_primary_action', lambda context:
        choose_primary(context.model_copy(update={'legal_candidates': (candidate_row,)})))

    paused = table.auto_step(mid, 0, [])
    assert paused['status'] == 'REACTION_REQUIRED', paused
    prompt = paused['reaction']
    assert prompt['context']['reaction_source_id'] == CHOICE
    assert prompt['trigger_actor'] == engine.state.actors[FOE].display_name
    assert prompt['affected'] == owner.display_name
    assert prompt['action'] == 'Hostile animal contest'
    answer = {**prompt['context'], 'selection': 'USE' if accept else 'DECLINE',
              **({'option_ids': ['ten']} if accept else {})}
    committed = table.auto_step(mid, 0, [answer])
    assert committed['status'] == 'COMMITTED', committed
    loaded = reload(tmp_path, mid)
    rewrites = [ev for ev in loaded.events if ev.event_type == 'D20_REWRITTEN' and ev.source_definition_id == STEADY]
    assert len(rewrites) == int(accept)
    assert loaded.state.actors[OWNER].resources[FOCUS] == engine.state.actors[OWNER].resources[FOCUS] - int(accept)

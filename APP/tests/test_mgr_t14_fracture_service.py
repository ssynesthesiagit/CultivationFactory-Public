"""Fracture base responses through compiled acquisition, table commits and cold reload.

Shard Needle supplies every tested mark. Synthetic actions supply only an
independent save trigger; no fixture injects an Ice passive, mark or receipt.
"""
import pytest

from combat.ext.ice_fracture import BASE, lattice_cells, marked
from tests.cw2_service_support import add_action, seal
from tests.worker2_support import OWNER, ALLY, FOE, fixture as build_fixture, candidate, reload, settle
from tests.mgr_t14_acquisition_support import acquire_declared
from tests.test_auto116_ice import reach
from tests.test_a2_ice_service import settle_path

RESPONSE = 'choice:needle.fracture_response'
QUIET = {RESPONSE: None}
CATCH = 'condition:typed.catch_step'


def fixture(*args, **kwargs):
    return build_fixture(*args, **kwargs,
        sheet_edit=acquire_declared('tianxia.sphere.ice'))


@pytest.mark.parametrize('accept', [False, True])
@pytest.mark.parametrize('blind', [False, True])
def test_crystal_guard_uses_recipient_consent_not_team_identity(tmp_path, accept, blind):
    def setup(bundles):
        prepare(bundles)
        add_action(bundles[1], 'Guard trigger', [{'type': 'damage',
            'dice': {'count': 1, 'sides': 6, 'modifier': 0}, 'damage_types': ['FORCE'],
            'applies_to': 'target'}], target='HOSTILE_ENTITY')
        seal(bundles[1])
        add_action(bundles[2], 'Blind myself', [{'type': 'condition', 'condition': 'blinded',
            'applies_to': 'self', 'expires_on': 'UNTIL_REMOVED'}], target='SELF')
    combat, table, mid = fixture(tmp_path, [BASE], named=True, bundle_transform=setup)
    mark_with_needle(combat, table, mid)
    if blind:
        reach(table, mid, FOE, QUIET)
        settle(table, mid, candidate(combat, mid, 'Blind myself').candidate_id, QUIET)
        from combat.senses import perceives
        engine = reload(tmp_path, mid)
        assert not perceives(engine, engine.state.actors[FOE], engine.state.actors[OWNER])
    reach(table, mid, ALLY, QUIET)
    before = reload(tmp_path, mid)
    prompts = settle(table, mid, candidate(combat, mid, 'Guard trigger', target=FOE).candidate_id,
                     {'choice:willing.consent': 'accept' if accept else None, RESPONSE: 'guard'})
    after = reload(tmp_path, mid)
    offers = [p for p in prompts if p['context']['reaction_source_id'] == 'choice:willing.consent']
    assert offers and all(p['context']['reactor_id'] == FOE for p in offers)
    if blind:
        assert all('Guard trigger' not in p['moment'] and 'Wren' not in p['moment'] for p in offers)
    assert marked(after.state.actors[FOE], OWNER) == (not accept)
    assert any(r.reason == 'CRYSTAL_GUARD' for r in after.rolls[len(before.rolls):]) == accept


def prepare(bundles):
    for b, initiative in zip(bundles, [100, -100, 0]):
        b['actor_template']['initiative_bonus'] = initiative
        b['actor_template']['maximum_hp'] = 1000
        b['actor_template']['armor_class'] = 0
        seal(b)
    for ability in ('DEX', 'STR'):
        add_action(bundles[2], ability + ' trial', [
            {'type': 'save', 'ability': ability, 'applies_to': 'self',
             'on_fail': [], 'on_success': []}], target='SELF')
    seal(bundles[2])
    add_action(bundles[0], 'Blind myself', [
        {'type': 'condition', 'condition': 'blinded', 'applies_to': 'self',
         'expires_on': 'UNTIL_REMOVED'}], target='SELF')


def mark_with_needle(combat, table, mid):
    """Actual learned Ice sphere -> compiled Shard Needle -> native hit -> mark."""
    for _ in range(5):
        reach(table, mid, OWNER, QUIET)
        settle(table, mid, candidate(combat, mid, 'Shard Needle', target=FOE).candidate_id, QUIET)
        if marked(combat._load_session(mid).engine.state.actors[FOE], OWNER):
            return
        reach(table, mid, FOE, QUIET)
    raise AssertionError('Shard Needle did not hit')


@pytest.mark.parametrize('cl,feet', [(1, 10), (10, 10), (11, 20), (17, 20)])
@pytest.mark.parametrize('accept', [True, False])
def test_catch_step_waits_for_movement_and_expires_on_current_turn(tmp_path, cl, feet, accept):
    combat, table, mid = fixture(tmp_path, [BASE], cl=cl, named=True,
                                 foe_position={'x': 6, 'y': 6}, bundle_transform=prepare)
    mark_with_needle(combat, table, mid)
    prompts = reach(table, mid, FOE, {RESPONSE: 'catch'})
    assert not [p for p in prompts if p['context']['reaction_source_id'] == RESPONSE]
    before = reload(tmp_path, mid)
    foe = before.state.actors[FOE]
    assert marked(foe, OWNER) and before._effective_speed(foe) == 30
    path = [foe.position.model_dump(mode='json'), {'x': 7, 'y': 6, 'z': 0}]
    prompts = settle_path(table, mid, FOE, path, {RESPONSE: 'catch' if accept else None})
    p = next(p for p in prompts if p['context']['reaction_source_id'] == RESPONSE)
    assert p['context']['reactor_id'] == OWNER
    after = reload(tmp_path, mid)
    foe = after.state.actors[FOE]
    assert after._effective_speed(foe) == 30 - (feet if accept else 0)
    assert foe.movement_remaining_ft == 25 - (feet if accept else 0)
    assert marked(foe, OWNER) == (not accept)
    owner = after.state.actors[OWNER]
    assert owner.reaction_available and owner.resources == before.state.actors[OWNER].resources
    assert bool(owner.turn_flags.get('ice_spent_round')) == accept
    reach(table, mid, ALLY, QUIET)
    expired = reload(tmp_path, mid)
    assert expired._effective_speed(expired.state.actors[FOE]) == 30
    assert not any(c.condition_id == CATCH for c in expired.state.actors[FOE].conditions.values())


@pytest.mark.parametrize('cl,sides', [(1, 4), (11, 6)])
@pytest.mark.parametrize('ability', ['DEX', 'STR'])
def test_crack_aim_independent_enemy_save_source_and_round_limit(tmp_path, cl, sides, ability):
    combat, table, mid = fixture(tmp_path, [BASE], cl=cl, bundle_transform=prepare)
    mark_with_needle(combat, table, mid)
    reach(table, mid, FOE, QUIET)
    before = reload(tmp_path, mid)
    prompts = settle(table, mid, candidate(combat, mid, ability + ' trial').candidate_id,
                     {RESPONSE: 'crack'})
    e = reload(tmp_path, mid)
    rolls = [r for r in e.rolls[len(before.rolls):] if r.reason == 'CRACK_AIM']
    offers = [p for p in prompts if p['context']['reaction_source_id'] == RESPONSE]
    assert bool(offers) == (ability == 'DEX')
    assert bool(rolls) == (ability == 'DEX')
    if rolls:
        assert rolls[0].expression == f'1d{sides}+0'
        assert 1 <= rolls[0].total <= sides
        saves = [v for v in e.events[len(before.events):] if v.event_type == 'SAVE_ROLLED']
        assert len(saves) == 1
        # Native typed-save modifiers subtract by raising the target DC; the
        # actual committed save must include this owner's rolled penalty.
        assert saves[0].payload['dc'] == 16 + rolls[0].total
        assert offers[0]['context']['reactor_id'] == OWNER
        assert not marked(e.state.actors[FOE], OWNER)
        assert e.state.actors[OWNER].turn_flags['ice_spent_round'] == f'{e.state.round_number}:1'
    else:
        assert marked(e.state.actors[FOE], OWNER)


@pytest.mark.parametrize('cl,dice', [(1, 1), (5, 2), (11, 3), (17, 4)])
@pytest.mark.parametrize('success', [False, True])
def test_shatter_space_includes_shard_needle_key_modifier(tmp_path, cl, dice, success):
    def setup(bundles):
        prepare(bundles)
        bundles[2]['actor_template']['saving_throws']['DEX'] = 100 if success else -100
        seal(bundles[2])
    combat, table, mid = fixture(tmp_path, [BASE], cl=cl, foe_position={'x': 2, 'y': 5},
                                 bundle_transform=setup)
    settle(table, mid, candidate(combat, mid, 'Crystallize Path').candidate_id, QUIET)
    reach(table, mid, FOE, QUIET)
    mark_with_needle(combat, table, mid)
    before = reload(tmp_path, mid)
    prompts = reach(table, mid, FOE, {RESPONSE: 'shatter'})
    assert any(p['context']['reaction_source_id'] == RESPONSE for p in prompts)
    e = reload(tmp_path, mid)
    rolls = [r for r in e.rolls[len(before.rolls):] if r.reason == f'DAMAGE:{BASE}']
    damage = [v for v in e.events[len(before.events):]
              if v.event_type == 'DAMAGE_COMMITTED' and v.source_definition_id == BASE]
    assert len(damage) == 1 and len(rolls) == 1
    assert rolls[0].expression == f'{dice}d8+2'
    assert rolls[0].modifier == 2
    assert damage[0].payload['rolled_or_pending_damage'] == (rolls[0].total // 2 if success else rolls[0].total)
    assert not marked(e.state.actors[FOE], OWNER)
    assert any(c.condition_id == 'condition:typed.prone' for c in e.state.actors[FOE].conditions.values()) == (not success)
    assert (2, 5) not in lattice_cells(e, OWNER)


def test_crack_aim_requires_current_perception_of_the_marked_target(tmp_path):
    combat, table, mid = fixture(tmp_path, [BASE], bundle_transform=prepare)
    mark_with_needle(combat, table, mid)
    settle(table, mid, candidate(combat, mid, 'Blind myself').candidate_id, QUIET)
    reach(table, mid, FOE, QUIET)
    prompts = settle(table, mid, candidate(combat, mid, 'DEX trial').candidate_id, {RESPONSE: 'crack'})
    assert not [p for p in prompts if p['context']['reaction_source_id'] == RESPONSE]
    assert marked(reload(tmp_path, mid).state.actors[FOE], OWNER)


def test_only_the_actual_mark_owner_can_spend_on_an_independent_save(tmp_path):
    combat, table, mid = fixture(tmp_path, [BASE], ally_talents=[BASE], bundle_transform=prepare)
    reach(table, mid, ALLY, QUIET)
    settle(table, mid, candidate(combat, mid, 'Shard Needle', target=FOE).candidate_id, QUIET)
    assert marked(reload(tmp_path, mid).state.actors[FOE], ALLY)
    reach(table, mid, FOE, QUIET)
    prompts = settle(table, mid, candidate(combat, mid, 'DEX trial').candidate_id, {RESPONSE: 'crack'})
    owners = [p['context']['reactor_id'] for p in prompts if p['context']['reaction_source_id'] == RESPONSE]
    assert owners == [ALLY]
    e = reload(tmp_path, mid)
    assert not marked(e.state.actors[FOE], ALLY)
    assert not e.state.actors[OWNER].turn_flags.get('ice_spent_round')


@pytest.mark.parametrize('speed', [5, 30])
def test_catch_step_zero_floor_and_shortened_long_path_commit(tmp_path, speed):
    def setup(bundles):
        prepare(bundles)
        bundles[2]['actor_template']['speed_ft'] = speed
        seal(bundles[2])
    combat, table, mid = fixture(tmp_path, [BASE], cl=11, bundle_transform=setup)
    mark_with_needle(combat, table, mid)
    reach(table, mid, FOE, QUIET)
    e = reload(tmp_path, mid)
    moves = [c for c in e.legal_candidates() if str(c.kind) == 'MOVE' and c.movement_cost_ft > 0
             and c.metadata.get('movement_mode', 'walk') == 'walk']
    move = max(moves, key=lambda c: c.movement_cost_ft)
    assert move.movement_cost_ft > max(0, speed - 20)
    settle_path(table, mid, FOE, [p.model_dump(mode='json') for p in move.canonical_path], {RESPONSE: 'catch'})
    after = reload(tmp_path, mid)
    foe = after.state.actors[FOE]
    assert after._effective_speed(foe) == max(0, speed - 20)
    assert not marked(foe, OWNER)
    events = [v for v in after.events if v.event_type == 'MOVEMENT_COMMITTED' and v.actor_id == FOE]
    assert events and events[-1].payload['cost_ft'] <= max(0, speed - 20)


@pytest.mark.parametrize('mode', ['walk', 'fly'])
def test_catch_step_selects_one_speed_without_late_walk_loss_creating_flight(tmp_path, mode):
    from combat import flight
    from combat.target_knowledge import located
    def setup(bundles):
        prepare(bundles)
        bundles[2]['actor_template']['fly_speed_ft'] = 30
        seal(bundles[2])
    combat, table, mid = fixture(tmp_path, [BASE], cl=11, bundle_transform=setup)
    mark_with_needle(combat, table, mid)
    reach(table, mid, FOE, QUIET)
    e = reload(tmp_path, mid)
    # Spend most of the shared allowance on a real route, declining the first
    # opportunity. The same mark can answer a later start this turn.
    routes = [c for c in e.legal_candidates() if str(c.kind) == 'MOVE' and c.movement_cost_ft == 25
              and c.metadata.get('movement_mode', 'walk') == 'walk'
              and located(e, e.state.actors[OWNER], e.state.actors[FOE].model_copy(update={'position': c.destination}))]
    route = routes[0]
    settle_path(table, mid, FOE, [p.model_dump(mode='json') for p in route.canonical_path], QUIET)
    e = reload(tmp_path, mid)
    before = e.state.actors[FOE]
    assert flight.remaining(e, before, 'fly') == 5
    route = next(c for c in e.legal_candidates() if str(c.kind) == 'MOVE' and c.movement_cost_ft == 5
                 and c.metadata.get('movement_mode', 'walk') == 'walk')
    settle_path(table, mid, FOE, [p.model_dump(mode='json') for p in route.canonical_path],
                {RESPONSE: 'catch', 'choice:needle.catch_speed': mode})
    after = reload(tmp_path, mid)
    foe = after.state.actors[FOE]
    assert after._effective_speed(foe) == (10 if mode == 'walk' else 30)
    assert flight.profile(after, foe).speed_ft == (30 if mode == 'walk' else 10)
    # Walking loss cannot manufacture extra flying feet; Fly loss affects only
    # flying, so the attempted five-foot walk still finishes in that branch.
    assert flight.remaining(after, foe, 'fly') == (5 if mode == 'walk' else 0)
    assert not marked(foe, OWNER)

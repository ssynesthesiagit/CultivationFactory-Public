"""Shared movement, footing, passage and equipment seams (SPLITCW1 slice 1).

Every clause is driven through the real engine path with a synthetic provider,
so the seam itself is what is under test: the ability families that consume
these hooks land in later slices. None of these tests read Git history, private
fixtures or owner data.
"""
import pytest

from combat import armour, creature_passage, falling, flight, technique_costs, zones
from combat.canonical import canonical_sha256
from combat.ext.next_jump import RECEIPT
from combat.factory_compiler import compile_character
from combat.gate4_engine import Gate4ControllerEngine
from combat.space import Position
from tests.h1_support import FOE, ME, ROOT, duel, sheet
from tests.test_lock_choices import install
from tests.worker2_support import ALLY, OWNER, fixture, reload, settle

SHIELD = {"item_id": "tianxia.mortal.armor.shield", "name": "Shield", "quantity": 1}


def _flying_engine(score=18):
    """A real compiled fighter with a native Fly Speed, ME's turn open."""
    bundle = compile_character(sheet([], score=score), actor_id=ME)
    bundle['actor_template'].update(fly_speed_ft=30, hover=True)
    bundle.pop('bundle_sha256')
    bundle['bundle_sha256'] = canonical_sha256(bundle)
    engine = Gate4ControllerEngine(
        ROOT, match_seed='SEAMS', typed_bundles=(bundle,),
        roster_setup={'primary_actor_ids': [ME, FOE], 'team_by_actor': {ME: 'team:a', FOE: 'team:b'},
                      'starting_positions': {ME: {'x': 3, 'y': 6}, FOE: {'x': 9, 'y': 6}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    return engine


def _five_foot_move(engine, actor):
    return next(row for row in engine.legal_candidates()
                if row.kind.value == 'MOVE'
                and not row.metadata.get('movement_mode')
                and engine.grid.distance_ft(actor.position, row.destination) == 5)


def test_segment_surcharge_quotes_and_charges_the_same_edge_price(tmp_path, monkeypatch):
    """One edge price for both the menu and the committed movement spend."""
    (tmp_path / 'plain').mkdir()
    (tmp_path / 'surcharged').mkdir()
    combat, table, mid = fixture(tmp_path / 'plain', [], ask=False)
    engine = reload(tmp_path / 'plain', mid)
    actor = engine.state.actors[OWNER]
    walk = _five_foot_move(engine, actor)
    plain_price = walk.movement_cost_ft
    settle(table, mid, walk.candidate_id)
    plain_events = reload(tmp_path / 'plain', mid).events

    install(monkeypatch, 'movement_segment_surcharge',
            lambda engine, actor, previous, destination, mode: 5 if mode == 'walk' else None)
    combat, table, mid = fixture(tmp_path / 'surcharged', [], ask=False)
    engine = reload(tmp_path / 'surcharged', mid)
    actor = engine.state.actors[OWNER]
    priced = _five_foot_move(engine, actor)
    assert priced.movement_cost_ft == plain_price + 5, 'the offered movement price includes the source surcharge'
    settle(table, mid, priced.candidate_id)
    events = reload(tmp_path / 'surcharged', mid).events

    def committed(rows):
        return [row for row in rows if row.event_type == 'MOVEMENT_COMMITTED' and row.actor_id == OWNER][-1]
    plain_spent = committed(plain_events).payload['cost_ft']
    assert committed(events).payload['cost_ft'] == plain_spent + 5, 'the spend matches the price the menu offered'


def test_flying_route_prices_each_edge_it_actually_crosses(monkeypatch):
    """B1: a fly route is priced per real edge, so an edge-specific surcharge lands on that edge alone.

    The old search priced each destination with a zero-length (destination, destination) step_cost, so a
    segment provider could never price the edge flown. Fails before the fix (the surcharged edge is missing)."""
    engine = _flying_engine()
    actor = engine.state.actors[ME]
    plain = flight.reachable(engine, actor, grant_ft=30, mode='fly')
    target = next(cell for cell, (path, _, _) in plain.items() if len(path) == 2)
    origin = plain[target][0][0]
    install(monkeypatch, 'movement_segment_surcharge',
            lambda engine, actor, previous, destination, mode: 5 if (previous, destination) == (origin, target) and mode == 'fly' else 0)
    priced = flight.reachable(engine, actor, grant_ft=30, mode='fly')
    # Tie-proof: whichever route wins, its cost is the sum of the step prices of the edges it actually crosses.
    for destination, (path, cost, _) in priced.items():
        assert cost == sum(flight.step_cost(engine, actor, a, b, 'fly') for a, b in zip(path, path[1:])), \
            f'{destination}: the route cost is the sum of the edges it crosses'


def test_portable_step_quote_equals_the_grid_path_it_charges(monkeypatch):
    """B2: portable_steps quotes and charges one route, so an edge-specific walking surcharge is in both.

    shortest_path had no edge price, so the quote ignored segment surcharges that the committed grant charged.
    Fails before the fix (the quote omits the surcharged edge)."""
    engine = duel([], score=18)
    actor = engine.state.actors[ME]
    from combat.ext import portable_steps
    target = Position(x=actor.position.x + 2, y=actor.position.y, z=0)
    plain_path, plain_quote = portable_steps.route(engine, actor, target, feet=30)
    install(monkeypatch, 'movement_segment_surcharge',
            lambda engine, actor, previous, destination, mode: 5 if previous == actor.position and mode == 'walk' else 0)
    path, quoted = portable_steps.route(engine, actor, target, feet=30)
    assert path == plain_path, 'the surcharge changes the price of the edge, not the straight route'
    assert quoted == plain_quote + 5, 'the quote includes the surcharged edge the commit charges'


def test_step_veto_refuses_a_stale_route_edge_at_commit(monkeypatch):
    """O1: a route quoted before a boundary appears is not spent across it; the per-step gate refuses the edge.

    The commit loop calls flight.step_allowed on every committed step, so a boundary raised after the quote
    stops the step. Fails before the fix (step_allowed never consults movement_edge_allowed)."""
    engine = _flying_engine()
    actor = engine.state.actors[ME]
    origin = actor.position
    step = Position(x=origin.x + 1, y=origin.y, z=origin.z)
    assert flight.step_allowed(engine, actor, origin, step, mode='walk') is True
    install(monkeypatch, 'movement_edge_allowed', lambda *args: False)
    assert flight.step_allowed(engine, actor, origin, step, mode='walk') is False, 'a vetoed edge is refused at commit'


def test_step_veto_refuses_a_jump_ascent_edge(monkeypatch):
    """O2: a vertical jump ascent crosses one vetoed edge, so no jump route may use it.

    Fails before the fix (valid_jump's ascent path bypasses the veto in step_allowed)."""
    engine = _flying_engine()
    actor = engine.state.actors[ME]
    origin = actor.position
    up = Position(x=origin.x, y=origin.y, z=origin.z + 1)
    assert flight.step_allowed(engine, actor, origin, up, mode='jump') is True
    install(monkeypatch, 'movement_edge_allowed', lambda *args: False)
    assert flight.step_allowed(engine, actor, origin, up, mode='jump') is False, 'a vetoed ascent is refused'


@pytest.mark.parametrize('answer', [-1, True])
def test_segment_surcharge_rejects_a_negative_or_boolean_answer(monkeypatch, answer):
    engine = duel([], score=18)
    actor = engine.state.actors[ME]
    install(monkeypatch, 'movement_segment_surcharge', lambda *args: answer)
    with pytest.raises(ValueError, match='nonnegative integer feet'):
        flight.step_cost(engine, actor, actor.position, Position(x=actor.position.x + 1, y=actor.position.y))


def test_movement_edge_veto_blocks_walking_flying_and_explicit_impulse(monkeypatch):
    """A source-owned physical boundary gates every movement mode, not just walking."""
    engine = _flying_engine()
    actor = engine.state.actors[ME]
    walking = flight.reachable(engine, actor, grant_ft=15, mode='walk')
    flying = flight.reachable(engine, actor, grant_ft=15, mode='fly')
    install(monkeypatch, 'movement_step_capability',
            lambda engine, actor, previous, destination, mode: True if mode == 'impulse' else None)
    impulse = flight.reachable(engine, actor, grant_ft=15, mode='impulse')
    assert walking and flying
    assert any(destination.z >= 1 for destination in impulse), 'impulse climbs in three dimensions like flight'

    install(monkeypatch, 'movement_edge_allowed', lambda *args: False)
    assert flight.reachable(engine, actor, grant_ft=15, mode='walk') == {}
    assert flight.reachable(engine, actor, grant_ft=15, mode='fly') == {}
    assert flight.reachable(engine, actor, grant_ft=15, mode='impulse') == {}

    install(monkeypatch, 'movement_edge_allowed', lambda *args: 1)
    with pytest.raises(ValueError, match='movement_edge_allowed must return bool'):
        flight.reachable(engine, actor, grant_ft=15, mode='walk')


def test_forced_vertical_displacement_honours_the_edge_veto_and_entry_policy(monkeypatch):
    engine = duel([], score=18)
    actor = engine.state.actors[ME]
    moved = []
    monkeypatch.setattr(zones, 'on_moved', lambda *args, **kwargs: moved.append((args, kwargs)))

    actor.position = Position(x=3, y=6, z=3)
    assert falling.displace(engine, actor, -3, 'test:drop', settle_after=False) == 15
    assert actor.position.z == 0 and moved == [], 'an ordinary displacement keeps the old no-entry policy'

    actor.position = Position(x=3, y=6, z=3)
    assert falling.displace(engine, actor, -3, 'test:drop', settle_after=False, trigger_entry=True) == 15
    assert moved and moved[-1][1]['forced'] is True, 'an opted-in displacement reports its new zone entry'

    actor.position = Position(x=3, y=6, z=3)
    install(monkeypatch, 'movement_edge_allowed', lambda *args: False)
    assert falling.displace(engine, actor, -3, 'test:drop', settle_after=False) == 0
    assert actor.position.z == 3, 'the vetoed step never moves the creature'

    with pytest.raises(ValueError, match='boolean entry policy'):
        falling.displace(engine, actor, -3, 'test:drop', settle_after=False, trigger_entry=1)


def test_support_override_grants_or_withholds_only_its_own_surface(monkeypatch):
    """Featherfall's footing clause: an override answers before ordinary ground."""
    engine = duel([], score=18)
    actor = engine.state.actors[ME]
    hovering = Position(x=6, y=6, z=4)
    assert falling.supported(engine, actor, hovering) is False

    install(monkeypatch, 'support_override', lambda *args: True)
    assert falling.supported(engine, actor, hovering) is True

    install(monkeypatch, 'support_override', lambda *args: False)
    assert falling.supported(engine, actor, hovering) is False, 'withholding ground support suspends the creature'
    install(monkeypatch, 'support_surface', lambda *args: True)
    assert falling.supported(engine, actor, hovering) is True, 'an independent supporting surface still holds it'

    install(monkeypatch, 'support_override', lambda *args: 1)
    with pytest.raises(ValueError, match='support_override providers must return bool'):
        falling.supported(engine, actor, hovering)


def test_pass_through_veto_withholds_native_ally_passage(monkeypatch, tmp_path):
    combat, table, mid = fixture(tmp_path, [], ask=False)
    engine = reload(tmp_path, mid)
    owner, ally = engine.state.actors[OWNER], engine.state.actors[ALLY]
    assert creature_passage.grants(engine, owner, ally) == [('difficult', None)]
    install(monkeypatch, 'pass_through_allowed', lambda *args: False)
    assert creature_passage.grants(engine, owner, ally) == []
    assert creature_passage.permission(engine, owner, ally) is None
    install(monkeypatch, 'pass_through_allowed', lambda *args: 'yes')
    with pytest.raises(ValueError, match='pass_through_allowed must return bool'):
        creature_passage.grants(engine, owner, ally)


def test_equipment_checkpoint_vetoes_use_without_taking_the_item(monkeypatch):
    """The living-cloud form's no-weapon/no-shield clause vetoes use only."""
    items = {'starting_kit': {'items': [SHIELD]}}
    engine = duel(['SHIELD_BASE_SHIELD_TRAINING'], kit=items)
    actor = engine.state.actors[ME]
    from combat.weapon_delivery import available_weapons
    assert armour.shield_bonus_earning(engine, actor) == 2
    assert available_weapons(engine, actor), 'the fighter can use weapons by default'
    key = armour.shield_item_key(engine, actor)
    assert key is not None

    install(monkeypatch, 'equipment_use_allowed',
            lambda engine, actor, kind: False if kind == 'shield' else None)
    assert armour.shield_bonus_earning(engine, actor) == 0
    assert available_weapons(engine, actor), 'a shield veto never disarms the fighter'
    assert armour.shield_item_key(engine, actor) == key, 'the item is still carried, not dropped or destroyed'

    install(monkeypatch, 'equipment_use_allowed',
            lambda engine, actor, kind: False if kind == 'weapon' else None)
    assert available_weapons(engine, actor) == {}
    assert armour.shield_bonus_earning(engine, actor) == 2, 'a weapon veto never takes the shield bonus'

    install(monkeypatch, 'equipment_use_allowed', lambda *args: 'veto')
    with pytest.raises(ValueError, match='equipment_use_allowed must return bool'):
        armour.shield_bonus_earning(engine, actor)


def test_refund_checkpoint_vetoes_only_the_native_refund(monkeypatch):
    engine = duel([], score=18)
    actor = engine.state.actors[ME]
    listed = [('resource:core.qi', 3)]
    before = sum(1 for event in engine.events if event.event_type == 'RESOURCE_GAINED')
    assert technique_costs.refund(engine, actor, 'action:test.refund', listed, 'resource:core.qi', 2,
                                  'test:refund') == 2
    gained = sum(1 for event in engine.events if event.event_type == 'RESOURCE_GAINED')
    assert gained == before + 1

    install(monkeypatch, 'technique_refund_allowed', lambda *args: False)
    assert technique_costs.refund(engine, actor, 'action:test.refund', listed, 'resource:core.qi', 2,
                                  'test:refund') == 0
    assert sum(1 for event in engine.events if event.event_type == 'RESOURCE_GAINED') == gained


def test_jump_distance_multiplier_never_scales_additive_feet(monkeypatch):
    """The one printed jump order: score base, standing rule, multiplier, then feet."""
    engine = duel([], score=18)
    actor = engine.state.actors[ME]
    ground = (actor.position,)
    base_steps = flight.jump_steps(engine, actor, ground)
    base_long = flight.horizontal_jump_feet(engine, actor)

    install(monkeypatch, 'jump_distance_multiplier', lambda *args: 3)
    install(monkeypatch, 'jump_bonus_ft', lambda *args: 5)
    engine._apply_condition(actor, RECEIPT, 'test:credit', ME, expires_on=None,
                            data={'feet': 5, 'label': 'test receipt'})

    score, feet = flight.jump_score(engine, actor)
    assert score == 18
    assert feet == 10, 'the flat extension and the next-jump receipt stay additive feet'
    assert flight.jump_distance(engine, actor, 7, feet, running=False) == 19
    assert flight.jump_distance(engine, actor, 7, feet, running=True) == 31
    assert flight.horizontal_jump_feet(engine, actor) == 37, \
        'a standing long jump: Strength 18 halved to 9, tripled to 27, then the 10 flat feet untripled'
    assert flight.jump_steps(engine, actor, ground) == 3, '19 feet is three whole five-foot steps'
    assert flight.jump_steps(engine, actor, ground) > base_steps
    assert flight.horizontal_jump_feet(engine, actor) > base_long


@pytest.mark.parametrize('answer', [0, -2, 1.0, True])
def test_jump_distance_multiplier_rejects_anything_but_a_positive_integer(monkeypatch, answer):
    engine = duel([], score=18)
    install(monkeypatch, 'jump_distance_multiplier', lambda *args: answer)
    with pytest.raises(ValueError, match='jump distance multiplier must be a positive integer'):
        flight.jump_distance_multiplier(engine, engine.state.actors[ME])



def test_vertical_jump_height_feet_never_lengthen_a_long_jump(monkeypatch):
    """Polearm Vaulter's "jump height by 5 feet" is flat feet for high jumps but not for long jumps."""
    engine = duel([], score=18)
    actor = engine.state.actors[ME]
    ground = (actor.position,)
    long_before = flight.horizontal_jump_feet(engine, actor)

    install(monkeypatch, 'jump_bonus_ft', lambda *args: 5)
    install(monkeypatch, 'jump_height_only_ft', lambda *args: 5)
    assert flight.jump_score(engine, actor) == (18, 5)
    assert flight.horizontal_jump_feet(engine, actor) == long_before, 'vertical-only feet are not long-jump feet'
    assert flight.jump_steps(engine, actor, ground) > 0, 'the same feet still raise the high jump'


def test_horizontal_jump_bonus_error_names_the_nonnegative_rule(monkeypatch):
    engine = duel([], score=18)
    actor = engine.state.actors[ME]
    install(monkeypatch, 'jump_distance_bonus_ft', lambda *args: -2)
    with pytest.raises(ValueError, match='nonnegative integer feet'):
        flight.horizontal_jump_bonus(engine, actor)
    install(monkeypatch, 'jump_distance_bonus_ft', lambda *args: 0)
    assert flight.horizontal_jump_bonus(engine, actor) == 0, 'zero is an accepted answer'


def test_untransformed_actor_keeps_its_recorded_footprint_even_when_labelled_larger():
    """Only a recorded transformation grows the footprint; a size label alone never does."""
    engine = duel([], score=18)
    actor = engine.state.actors[ME]
    original = engine.actor_footprints[ME]
    assert max(original.width_cells, original.height_cells) == 1
    actor.size_category = 'Huge'
    assert actor.transformed_size_category is None
    assert engine._footprint(actor) == original


def test_flat_jump_feet_alone_open_no_straight_jump(monkeypatch):
    """Flowing Pursuit's "add 5 feet to one jump" (jump_bonus_ft) raises only the high jump. A fighter with no
    long-jump opt-in (jump_distance_bonus_ft or a distance multiplier) gets no straight jump from it."""
    engine = duel([], score=8)
    actor = engine.state.actors[ME]
    install(monkeypatch, 'jump_bonus_ft', lambda *args: 5)
    assert flight.horizontal_jumps(engine, actor) == {}, 'flat feet alone must not open a long jump'


def test_flat_jump_feet_join_the_long_jump_only_after_the_straight_jump_opt_in(monkeypatch):
    """The same flat feet reach the long jump once a long-jump opt-in exists (the Vaulter horizontal purchase)."""
    engine = duel([], score=8)
    actor = engine.state.actors[ME]
    install(monkeypatch, 'jump_bonus_ft', lambda *args: 5)
    install(monkeypatch, 'jump_distance_bonus_ft', lambda *args: 5)
    assert flight.horizontal_jumps(engine, actor), 'the opted-in fighter has straight jumps'
    assert flight.horizontal_jump_feet(engine, actor) >= 10, 'flat feet (5) and the long-jump increase (5) are both long-jump feet'

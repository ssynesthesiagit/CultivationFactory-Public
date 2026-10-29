"""River Without Edges (MGR-T17): the Flowing River insight's passage rule is real.

Printed: when Flowing Response grants movement, the fighter may cross liquid
surfaces, loose rubble, narrow branches, collapsing terrain or a hostile
creature's occupied space as Difficult Terrain, along a continuous physical path
no wider than its normal reach, and must end in a legal space that can support it.
Never flight, teleportation, or movement Flowing Response did not grant.
"""
import re
import pytest

from combat import factory_compiler, granted_movement
from combat.ext import flowing_river_edges as edges
from tests.auto_worker1_support import LEFT, RIGHT, fight, act, turn
from tests.test_auto2_flowing_river import P, RESPONSE, settle, decline_steps, reload

INSIGHT = edges.INSIGHT
STEP_AWAY = 'Flowing Response: step away'
STEP = 'choice:needle.river_step'
SQUARE_FT = 5
# Flowing Response's trigger (TAL_FLOWING_RIVER_FLOWING_RESPONSE). The public export replaces every long printed
# sentence with pseudo-words, and a reaction's kind is read from that sentence at compile time, so without this pin
# the public run compiles no Flowing Response reaction and offers no Step menu. This is a synthetic trigger built only
# from the classifier's vocabulary (a melee attack that targets you; a forced Strength or Dexterity save; the
# Prone / Grappled / Restrained conditions). It does not reproduce the printed sentence's wording or clause order, and
# it reads as the same reaction kind, filters and conditions (guarded by the test below).
RESPONSE_TRIGGER = ('A creature you can see targets you with a melee attack; a creature within your reach forces a '
                    'Strength or Dexterity saving throw to avoid being moved, knocked Prone, Grappled, or Restrained.')


@pytest.fixture(autouse=True)
def _printed_response_trigger(monkeypatch):
    """Compile Flowing Response from its printed trigger even where the public export has scrambled it.

    Same pin as test_body_refining_choices.pin_counter_palm_trigger: only this one mechanic's trigger sentence is
    restored; every other field stays the shipped data. Restored per test by monkeypatch.
    """
    original = factory_compiler._read_compilation_authority

    def read(path):
        authority, sha256 = original(path)
        mechanic = authority['mechanics'][RESPONSE]
        pinned = {**mechanic, 'activation': {**mechanic['activation'], 'trigger': RESPONSE_TRIGGER}}
        return {**authority, 'mechanics': {**authority['mechanics'], RESPONSE: pinned}}, sha256

    monkeypatch.setattr(factory_compiler, '_read_compilation_authority', read)


def test_pinned_response_trigger_classifies_as_the_printed_reaction():
    """The synthetic trigger must read as the same reaction kind and filters, or the Step menu tests would miss it."""
    from combat import reaction_triggers
    matches = reaction_triggers.classify_mechanic_all({'activation': {'trigger': RESPONSE_TRIGGER}})
    assert [(m.kind, m.melee_only, m.requires_sight, m.save_abilities, m.conditions) for m in matches] == [
        ('attacked', True, True, frozenset({'STR', 'DEX'}), frozenset({'grappled', 'restrained', 'prone'}))]


def surface(region_id, material, cells, *, terrain_type='DIFFICULT', material_only=True):
    """One painted surface class (a legal cell whose matter the base table cannot price)."""
    region = {'region_id': region_id, 'terrain_type': terrain_type, 'movement_cost': 2,
              'material': material, 'cells': [{'x': x, 'y': y} for x, y in cells]}
    if material_only:
        region['material_only'] = True
    return region


def sure_miss(bundle):
    for action in bundle['action_catalog']:
        if action['display_name'] == 'Cause':
            action['parameters']['typed']['numbers']['attack_bonus'] = -100
            action['parameters']['typed']['range_ft'] = None


def feet(label):
    return int(re.search(r'\((\d+) feet\)', label).group(1))


def step_menu(tmp_path, talents, surfaces=(), *, legacy=False, pick=None, fly=False):
    """Run one Flowing Response step away and answer its movement menu.

    Returns the reloaded engine and the offered Step options ({id: label}). With
    ``pick`` the step is also taken, so the committed route and its price are real.
    """
    def edit(bundle):
        sure_miss(bundle)
        if fly:  # a flyer: the same grant, priced by the flight branch
            bundle['actor_template']['fly_speed_ft'] = 30
        if legacy:  # a bundle sealed before the step was native keeps the historical automatic move
            for row in bundle['typed_reactions']:
                for effect_row in row.get('effects') or []:
                    if effect_row.get('type') == 'flowing_yield_attack':
                        effect_row['second_pass'] = False

    def arena(document):
        document['terrain_regions'] = [*(document.get('terrain_regions') or []), *surfaces]

    tmp_path.mkdir(parents=True, exist_ok=True)
    combat, table, match = fight(
        tmp_path, talents, bundle_edit=edit, left_score=50,
        cause=[{'type': 'attack', 'attack_kind': 'melee', 'no_damage': True}],
        arena_edit=arena, map_terrain=[])
    settle(lambda answers: act(table, match, STEP_AWAY, answers))
    turn(table, match, RIGHT)

    def answer(prompt):
        if prompt['context']['reaction_source_id'] == STEP:
            ids = [option['id'] for option in prompt['choice']['options']]
            return [pick] if pick in ids else []
        return decline_steps(prompt)

    _, prompts = settle(lambda answers: act(table, match, 'Cause', answers, target_id=LEFT), answer)
    step = next((prompt for prompt in prompts if prompt['context']['reaction_source_id'] == STEP), None)
    options = {option['id']: option.get('label') for option in (step or {}).get('choice', {}).get('options', [])}
    return reload(combat, match), options


def test_rubble_crossing_is_difficult_and_can_end_on_it(tmp_path):
    engine, options = step_menu(tmp_path, [RESPONSE, P + 'EMPTY_STEP', INSIGHT],
                                [surface('loose rubble', 'rubble', [(2, 6)])], pick='step:2,6,0')
    assert feet(options['step:2,6,0']) == 2 * SQUARE_FT
    left = engine.state.actors[LEFT]
    assert (left.position.x, left.position.y) == (2, 6)
    moved = [event for event in engine.events
             if event.event_type == 'MOVEMENT_COMMITTED' and event.actor_id == LEFT]
    assert moved[-1].payload['granted_cost_ft'] == 2 * SQUARE_FT


def test_liquid_is_crossable_but_never_a_legal_endpoint(tmp_path):
    engine, options = step_menu(tmp_path, [RESPONSE, P + 'EMPTY_STEP', INSIGHT],
                                [surface('rain stream', 'water', [(2, 6)], terrain_type='BLOCKED',
                                         material_only=False)])
    assert 'step:2,6,0' not in options  # the water carries no weight, so it cannot be the end
    left = engine.state.actors[LEFT]
    with edges.crossing_scope(engine, left):
        assert edges.passage(engine, left, (2, 6, 0)) == 'difficult'


def test_walkable_liquid_is_never_offered_as_a_walk_endpoint(tmp_path):
    # The water here is ordinary walkable ground (not BLOCKED, not material-only), so the native grid
    # reaches it on foot. The liquid endpoint rule must still refuse it as a Flowing Response end.
    engine, options = step_menu(tmp_path, [RESPONSE, P + 'EMPTY_STEP', INSIGHT],
                                [surface('rain stream', 'water', [(2, 6)], terrain_type='DIFFICULT',
                                         material_only=False)])
    assert 'step:2,6,0' not in options
    left = engine.state.actors[LEFT]
    with edges.crossing_scope(engine, left):  # the endpoint rule only applies inside the grant
        reach = granted_movement.routes(engine, left, 60)  # a large grant: only the endpoint rule can remove it
    assert reach  # the walk itself still works; only the liquid end is refused
    assert (2, 6, 0) not in {(cell.x, cell.y, cell.z) for cell in reach}


def test_flyer_keeps_walkable_water_as_a_legal_endpoint(tmp_path):
    # A flyer may end over ground-level water (native placement allows it), so the liquid endpoint
    # restriction, which exists only for walkers, must not remove that cell from a Flowing Response grant.
    engine, options = step_menu(tmp_path, [RESPONSE, P + 'EMPTY_STEP', INSIGHT],
                                [surface('rain stream', 'water', [(2, 6)], terrain_type='DIFFICULT',
                                         material_only=False)], fly=True)
    assert 'step:2,6,0' in options
    left = engine.state.actors[LEFT]
    with edges.crossing_scope(engine, left):
        reach = granted_movement.routes(engine, left, 60)
    assert (2, 6, 0) in {(cell.x, cell.y, cell.z) for cell in reach}


def test_without_the_insight_the_class_squares_are_not_crossable(tmp_path):
    engine, options = step_menu(tmp_path, [RESPONSE, P + 'EMPTY_STEP'],
                                [surface('loose rubble', 'rubble', [(2, 6)])])
    assert feet(options['step:2,6,0']) == SQUARE_FT  # the base table has no Difficult price for this matter
    left, right = engine.state.actors[LEFT], engine.state.actors[RIGHT]
    with edges.crossing_scope(engine, left):
        assert edges.passage(engine, left, (2, 6, 0)) is None
        assert edges.hostile_space(engine, left, right) is None
    assert edges.owns(engine, left) is False


@pytest.mark.parametrize('walled', [False, True])
def test_hostile_space_is_difficult_transit_only_with_a_continuous_path(tmp_path, walled):
    walls = [surface('sheer wall', 'stone', [(5, 6), (4, 5), (4, 7), (5, 5), (5, 7)],
                     terrain_type='BLOCKED', material_only=False)] if walled else []
    engine, options = step_menu(tmp_path, [RESPONSE, P + 'EMPTY_STEP', INSIGHT], walls)
    assert 'step:4,6,0' not in options  # an occupied space is never an endpoint
    left, right = engine.state.actors[LEFT], engine.state.actors[RIGHT]
    with edges.crossing_scope(engine, left):
        grant = edges.hostile_space(engine, left, right)
    assert (grant is None) is walled
    if not walled:
        assert grant == ('difficult', {(4, 6, 0)})


def test_legacy_reaction_step_is_unchanged_by_the_insight(tmp_path):
    surfaces = [surface('loose rubble', 'rubble', [(2, 6)])]
    owned_engine, owned = step_menu(tmp_path / 'owned', [RESPONSE, P + 'EMPTY_STEP', INSIGHT],
                                    surfaces, legacy=True)
    plain_engine, plain = step_menu(tmp_path / 'plain', [RESPONSE, P + 'EMPTY_STEP'], surfaces, legacy=True)
    assert edges.owns(owned_engine, owned_engine.state.actors[LEFT]) is True  # the insight really is compiled
    assert owned == plain  # the historical automatic step still asks nothing and offers nothing new

    def ending(engine):
        here = engine.state.actors[LEFT].position
        return (here.x, here.y)

    def paid(engine):
        return [event.payload.get('cost_ft') for event in engine.events
                if event.event_type == 'MOVEMENT_COMMITTED' and event.actor_id == LEFT]

    assert ending(owned_engine) == ending(plain_engine) != (3, 6)  # both still step, the same way
    assert paid(owned_engine) == paid(plain_engine)  # and the class matter is not priced as Difficult


def test_non_response_river_step_does_not_get_river_without_edges_scope(tmp_path):
    """Ten Thousand Edges uses the same chooser but must not inherit the Flowing Response passage scope."""
    def run(folder, with_insight):
        def edit(bundle):
            for action in bundle['action_catalog']:
                if action['display_name'] == 'Cause':
                    # Ten Thousand Edges only triggers after a real hit is converted into a miss.
                    # Make the attack certain to hit absent that feature; an ordinary miss does not step.
                    action['parameters']['typed']['range_ft'] = None
                    action['parameters']['typed']['numbers']['attack_bonus'] = 100

        talents = [P + 'TEN_THOUSAND_EDGES_FIND_NO_CENTER']
        if with_insight:
            talents.append(INSIGHT)

        def arena(document):
            document['terrain_regions'] = [surface('loose rubble', 'rubble', [(2, 6)]),
                                          *(document.get('terrain_regions') or [])]

        combat, table, match = fight(
            folder, talents, bundle_edit=edit, left_score=50,
            cause=[{'type': 'attack', 'attack_kind': 'melee', 'no_damage': True}],
            arena_edit=arena, map_terrain=[])
        settle(lambda answers: act(table, match, 'Dodge', answers))
        turn(table, match, RIGHT)

        def choose_step(prompt):
            if prompt['context']['reaction_source_id'] != STEP:
                return decline_steps(prompt)
            ids = [option['id'] for option in prompt['choice']['options']]
            return ['step:2,6,0'] if 'step:2,6,0' in ids else []

        _, prompts = settle(
            lambda answers: act(table, match, 'Cause', answers, target_id=LEFT), choose_step)
        engine = reload(combat, match)
        step_prompt = next(p for p in prompts if p['context']['reaction_source_id'] == STEP)
        offered = {option['id'] for option in step_prompt['choice']['options']}
        committed = [event.payload.get('cost_ft') for event in engine.events
                     if event.event_type == 'MOVEMENT_COMMITTED' and event.actor_id == LEFT]
        return engine, offered, committed

    plain, plain_options, plain_costs = run(tmp_path / 'plain', False)
    owner, owner_options, owner_costs = run(tmp_path / 'owner', True)
    assert edges.owns(owner, owner.state.actors[LEFT])
    assert plain_options == owner_options
    assert plain_costs == owner_costs
    assert 'step:2,6,0' not in owner_options
    assert (plain.state.actors[LEFT].position.x, plain.state.actors[LEFT].position.y) == (
        owner.state.actors[LEFT].position.x, owner.state.actors[LEFT].position.y)


def test_grant_reach_covers_liquid_ends_and_rubble_crossings_three_squares_out(tmp_path):
    """MGR-T17 review fixes 1 and 2: the area is the grant's own reach, not a 2-square reactive radius.

    A 30 ft Flowing Response grant reaches squares 3+ away. Walkable water there must never be an end (the
    liquid rule), and loose rubble there is still a crossable square the printed rule permits. With the old
    two-square neighbourhood, neither square was judged at all, so the water was offered as an end.
    """
    engine, _ = step_menu(tmp_path, [RESPONSE, P + 'EMPTY_STEP', INSIGHT],
                          [surface('rain stream', 'water', [(5, 9)], terrain_type='DIFFICULT', material_only=False),
                           surface('loose rubble', 'rubble', [(3, 9)])])
    left = engine.state.actors[LEFT]
    with edges.crossing_scope(engine, left):
        reach = granted_movement.routes(engine, left, 30)
    ends = {(cell.x, cell.y, cell.z) for cell in reach}
    assert (5, 9, 0) not in ends  # liquid three squares out is never a legal end of the grant
    assert (3, 9, 0) in ends  # rubble three squares out is still a crossing the rule permits and can end on

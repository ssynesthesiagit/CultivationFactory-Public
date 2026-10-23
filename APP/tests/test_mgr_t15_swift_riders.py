"""Swift Movement companions: Air Stunt, Dread Appetite's Speed penalty, and nested Speed reads.

Air Stunt's virtual wall answers only with Wall Stunt owned, and its provisional air support ends at the
owner's turn end. Press the Fear slows only an already-Frightened creature, by 10 feet, through the live
Speed composition that cold reload reproduces. Nested Speed reads inside one memo frame must not change the
answer an outer read gives afterwards.
"""
from combat import roof_movement, movement_speeds, ext, speed_contributions
from combat.ext import athletics
from combat.gate5_service import CombatService
from combat.tabletop import normalize_map, to_battlefield
from combat.read_queries import read_frame
from tests.hunt31_support import OWNER, FOE, fixture, reload, act
from tests.test_walkable_roofs import route

AIR = 'TAL_ATHLETICS_AIR_STUNT'
WALL = 'TAL_ATHLETICS_WALL_STUNT'
DREAD = 'TAL_DAEMONIC_CULTIVATION_DREAD_APPETITE'
AIR_SUPPORT = athletics.AIR_SUPPORT
FRIGHTENED = 'condition:typed.frightened'


def exact(table, mid, label, target=None):
    """The option a player sees by name, not the first augment variant sharing its prefix."""
    return next(o['candidate_id'] for g in table.state(mid)['menu']['actions']
                for o in g['options']
                if o['label'] == label and (target is None or o.get('target_ids') == [target]))


def commit(table, mid, cid):
    """Commit one candidate, answering every player-owned prompt the table raises on the way."""
    answers = []
    for _ in range(20):
        result = act(table, mid, cid, answers)
        if result['status'] == 'COMMITTED':
            return result
        assert result['status'] == 'REACTION_REQUIRED', result
        prompt = result['reaction']
        choice = prompt.get('choice')
        if choice and not choice.get('allow_decline', False):
            answers.append({**prompt['context'], 'selection': 'USE',
                            'option_ids': [choice['options'][0]['id']]})
        else:
            answers.append({**prompt['context'], 'selection': 'DECLINE'})
    raise AssertionError('the table never committed that candidate')


def test_air_stunt_virtual_wall_needs_owned_wall_stunt(monkeypatch, tmp_path):
    combat, table, mid = fixture(monkeypatch, tmp_path, [AIR])
    engine = reload(combat, mid)
    assert not roof_movement.profile(engine, engine.state.actors[OWNER]).virtual_wall, \
        'Air Stunt alone invented a Wall Stunt virtual wall'


def test_air_stunt_with_wall_stunt_gives_virtual_wall(monkeypatch, tmp_path):
    combat, table, mid = fixture(monkeypatch, tmp_path, [WALL, AIR])
    engine = reload(combat, mid)
    assert roof_movement.profile(engine, engine.state.actors[OWNER]).virtual_wall


def test_air_support_ends_at_owners_turn_end_and_survives_reload(monkeypatch, tmp_path):
    original = CombatService.factory_arenas
    arena = to_battlefield(normalize_map({
        'display_name': 'Swift air stunt yard', 'width_squares': 18, 'height_squares': 12,
        'walls': [], 'roofs': {'enabled': False}}))
    monkeypatch.setattr(CombatService, 'factory_arenas',
                        lambda self, **kw: {**original(self, **kw),
                                            'battlefield:factory_pillar_arena': arena})
    combat, table, mid = fixture(monkeypatch, tmp_path, [WALL, AIR])

    def answer(prompt):
        choice = prompt.get('choice')
        if choice and not choice.get('allow_decline', False):
            return {**prompt['context'], 'selection': 'USE', 'option_ids': [choice['options'][0]['id']]}
        return {**prompt['context'], 'selection': 'DECLINE'}

    # A real committed climb through the table, not a direct call to the plug-in hook.
    route(combat, table, mid, [(3, 6, 0), (3, 6, 1), (3, 6, 2)], mode='climb', answer=answer)
    engine = reload(combat, mid)
    actor = engine.state.actors[OWNER]
    assert actor.position.z == 2 and actor.climbing
    support = [c for c in actor.conditions.values() if c.condition_id == AIR_SUPPORT]
    assert len(support) == 1
    assert support[0].expires_on.startswith('END_OF_SOURCE_TURN_AT:')
    # The committed climb's provisional support survives a cold reload from the saved journal.
    engine = reload(combat, mid)
    actor = engine.state.actors[OWNER]
    support = [c for c in actor.conditions.values() if c.condition_id == AIR_SUPPORT]
    assert len(support) == 1 and support[0].expires_on.startswith('END_OF_SOURCE_TURN_AT:'), \
        'air support lost on reload'
    # A committed end turn expires it through the native turn transition and the owner falls.
    assert commit(table, mid, table.state(mid)['menu']['end_turn'])['status'] == 'COMMITTED'
    engine = reload(combat, mid)
    actor = engine.state.actors[OWNER]
    assert engine.state.current_actor_id != OWNER
    assert actor.position.z == 0 and not actor.climbing
    assert not any(c.condition_id == AIR_SUPPORT for c in actor.conditions.values()), \
        'Air Stunt air support survived the end of its owner turn'


def test_press_the_fear_slows_already_frightened_foe_by_ten(monkeypatch, tmp_path):
    combat, table, mid = fixture(monkeypatch, tmp_path, [DREAD], dc=99)
    # The foe fails its save: it becomes Frightened, and the owner's own Devour Essence
    # Reaction is offered (declined by ``commit``) before the action commits.
    assert commit(table, mid, exact(table, mid, 'Dread Appetite: Frighten', FOE))['status'] == 'COMMITTED'
    engine = reload(combat, mid)
    foe = engine.state.actors[FOE]
    assert any(c.condition_id == FRIGHTENED for c in foe.conditions.values())
    # Frighten spent the Bonus Action on the owner's current turn. End that turn and take the
    # intervening turns so the owner acts again while the foe is still Frightened.
    assert commit(table, mid, table.state(mid)['menu']['end_turn'])['status'] == 'COMMITTED'
    for _ in range(8):
        menu = table.state(mid)['menu']
        if menu['actor_id'] == OWNER:
            break
        assert commit(table, mid, menu['end_turn'])['status'] == 'COMMITTED'
    assert table.state(mid)['menu']['actor_id'] == OWNER, 'the owner never regained its turn'
    engine = reload(combat, mid)
    foe = engine.state.actors[FOE]
    assert any(c.condition_id == FRIGHTENED for c in foe.conditions.values()), \
        'the foe is no longer Frightened on the owner\'s next turn'
    before = movement_speeds.speed(engine, foe, 'walk')
    assert before > 10
    assert commit(table, mid, exact(table, mid, 'Dread Appetite: Press the Fear (already Frightened)', FOE))[
        'status'] == 'COMMITTED'
    engine = reload(combat, mid)
    foe = engine.state.actors[FOE]
    assert movement_speeds.speed(engine, foe, 'walk') == before - 10, \
        'Press the Fear did not cut 10 feet of Speed'
    engine = reload(combat, mid)
    assert movement_speeds.speed(engine, engine.state.actors[FOE], 'walk') == before - 10


def test_nested_speed_read_leaves_outer_frame_answer_unchanged(monkeypatch, tmp_path):
    combat, table, mid = fixture(monkeypatch, tmp_path, [])
    engine = reload(combat, mid)
    actor = engine.state.actors[OWNER]
    baseline = speed_contributions.effective_speed(engine, actor)
    nested = []

    def nosy_provider(engine, actor):
        nested.append(int(speed_contributions.effective_speed(engine, actor)))
        return 0

    monkeypatch.setitem(ext._HOOKS, 'speed', [*ext._HOOKS['speed'], nosy_provider])
    with read_frame(engine):
        first = speed_contributions.effective_speed(engine, actor)
        again = speed_contributions.effective_speed(engine, actor)
    assert nested and all(value <= baseline for value in nested)
    assert first == baseline == again, 'a nested Speed read changed the answer the outer frame returns'

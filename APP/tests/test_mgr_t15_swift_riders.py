"""Swift Movement companions: Air Stunt, Dread Appetite's Speed penalty, and nested Speed reads.

Air Stunt's virtual wall answers only with Wall Stunt owned, and its provisional air support ends at the
owner's turn end. Press the Fear slows only an already-Frightened creature, by 10 feet, through the live
Speed composition that cold reload reproduces. Nested Speed reads inside one memo frame must not change the
answer an outer read gives afterwards.
"""
from combat import roof_movement, movement_speeds, ext, speed_contributions
from combat.read_queries import read_frame
from combat.ext import athletics
from tests.hunt31_support import OWNER, FOE, fixture, pick, send, reload, act

AIR = 'TAL_ATHLETICS_AIR_STUNT'
WALL = 'TAL_ATHLETICS_WALL_STUNT'
DREAD = 'TAL_DAEMONIC_CULTIVATION_DREAD_APPETITE'
AIR_SUPPORT = athletics.AIR_SUPPORT


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
    from types import SimpleNamespace
    combat, table, mid = fixture(monkeypatch, tmp_path, [WALL, AIR])
    engine = reload(combat, mid)
    actor = engine.state.actors[OWNER]
    path = [SimpleNamespace(x=3, y=3, z=1)]
    candidate = SimpleNamespace(metadata={'movement_mode': 'climb'}, canonical_path=path)
    athletics.air_stunt_movement_begin(engine, actor, candidate, None, 5)
    support = [c for c in actor.conditions.values() if c.condition_id == AIR_SUPPORT]
    assert len(support) == 1
    assert support[0].expires_on.startswith('END_OF_SOURCE_TURN_AT:')
    engine = reload(combat, mid)
    actor = engine.state.actors[OWNER]
    assert any(c.condition_id == AIR_SUPPORT for c in actor.conditions.values()), 'air support lost on reload'
    athletics.air_stunt_turn_end(engine, actor)
    assert not any(c.condition_id == AIR_SUPPORT for c in actor.conditions.values()), \
        'Air Stunt air support survived the end of its owner turn'


def test_press_the_fear_slows_already_frightened_foe_by_ten(monkeypatch, tmp_path):
    combat, table, mid = fixture(monkeypatch, tmp_path, [DREAD], dc=99)
    assert send(combat, table, mid, pick(table, mid, 'Dread Appetite: Frighten', FOE), False)['status'] == 'COMMITTED'
    # Frightened lasts until the end of the owner's next turn: take turns until the owner acts again.
    for _ in range(12):
        if table.state(mid)['menu']['actor_id'] == OWNER:
            break
        assert act(table, mid, table.state(mid)['menu']['end_turn'])['status'] == 'COMMITTED'
    engine = reload(combat, mid)
    foe = engine.state.actors[FOE]
    assert any(c.condition_id == 'condition:typed.frightened' for c in foe.conditions.values())
    before = movement_speeds.speed(engine, foe, 'walk')
    assert before > 10
    assert send(combat, table, mid, pick(table, mid, 'Press the Fear', FOE), False)['status'] == 'COMMITTED'
    engine = reload(combat, mid)
    foe = engine.state.actors[FOE]
    assert movement_speeds.speed(engine, foe, 'walk') == before - 10, 'Press the Fear did not cut 10 feet of Speed'
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

"""Bound repeated anchor work without changing real table choices or commits."""
from collections import Counter

import pytest

from combat import read_queries, senses
from combat.ext import death_riders
from combat.gate2_runtime_models import Position, RuntimeObjectState
from combat.shot_geometry import scope
from tests.h1_support import ME, duel


def object_at(name, kind, x, **component):
    return RuntimeObjectState(object_id=name, object_kind=kind, position=Position(x=x, y=6),
        unattended=True, flammable=False, ac=10, current_hp=10, maximum_hp=10, component=component)


def test_anchor_snapshot_is_private_and_scoped_to_origin_revision_and_engine(monkeypatch):
    engine = duel(['TAL_DEATH_DEATHLY_PASSAGE'])
    actor = engine.state.actors[ME]
    # The stock roster also contains represented corpses; preserve their
    # legitimate anchors while isolating this object's cache invalidation.
    existing = death_riders.grave_anchors(engine, actor)
    engine.state.objects['grave'] = object_at('grave', 'corpse', 4)
    native = death_riders._grave_anchors
    calls = []
    def counted(e, a):
        calls.append((e, a.position))
        return native(e, a)
    monkeypatch.setattr(death_riders, '_grave_anchors', counted)
    with read_queries.candidate_pass(engine):
        expected = death_riders.grave_anchors(engine, actor)
        assert expected
        for _ in range(20):
            result = death_riders.grave_anchors(engine, actor)
            assert result == expected
            result.clear()
        assert len(calls) == 1
        old = actor.position
        actor.position = Position(x=old.x+1, y=old.y)
        death_riders.grave_anchors(engine, actor)
        assert len(calls) == 2
        actor.position = old
        action = engine.action_catalog[actor.action_ids[0]]
        with scope(engine, actor, action):
            death_riders.grave_anchors(engine, actor)
            assert len(calls) == 3
        engine.state.event_sequence += 1
        death_riders.grave_anchors(engine, actor)
        assert len(calls) == 4
        other = duel(['TAL_DEATH_DEATHLY_PASSAGE'])
        death_riders.grave_anchors(other, other.state.actors[ME])
        assert len(calls) == 5
        engine.state = engine.state.model_copy()
        death_riders.grave_anchors(engine, engine.state.actors[ME])
        assert len(calls) == 6
    engine.state.objects['grave'].destroyed = True
    assert death_riders.grave_anchors(engine, actor) == existing
    assert len(calls) == 7
    with read_queries.candidate_pass(engine):
        assert death_riders.grave_anchors(engine, actor) == existing
    assert len(calls) == 8


def test_anchor_errors_do_not_cache_and_frames_restore(monkeypatch):
    engine = duel(['TAL_DEATH_DEATHLY_PASSAGE'])
    actor = engine.state.actors[ME]
    def broken(e, a):
        raise ValueError('anchor probe')
    with read_queries.candidate_pass(engine):
        with monkeypatch.context() as patch:
            patch.setattr(death_riders, '_grave_anchors', broken)
            for _ in range(2):
                with pytest.raises(ValueError, match='anchor probe'):
                    death_riders.grave_anchors(engine, actor)
        assert isinstance(death_riders.grave_anchors(engine, actor), list)


def test_nonanchors_do_not_run_sight_queries(monkeypatch):
    engine = duel(['TAL_DEATH_DEATHLY_PASSAGE'])
    actor = engine.state.actors[ME]
    engine.state.objects = {}
    cells = []
    monkeypatch.setattr(senses, 'perceives', lambda *a, **kw: True)
    monkeypatch.setattr(senses, 'perceives_cell', lambda e, a, p: cells.append(p) or True)
    creature_anchors = death_riders.grave_anchors(engine, actor)
    engine.state.objects = {'crate': object_at('crate', 'crate', 4),
        'foreign': object_at('foreign', 'marker', 5, death_anchor_owner='another'),
        'grave': object_at('grave', 'corpse', 6),
        'own': object_at('own', 'marker', 7, death_anchor_owner=ME)}
    expected = [engine.state.objects[k].position for k in ('grave', 'own')]
    assert death_riders.grave_anchors(engine, actor) == creature_anchors + expected
    assert cells == expected


def test_table_menu_bounds_anchor_scans_and_survives_commit_reload(tmp_path, monkeypatch):
    from combat.gate5_service import CombatService
    from tests.h1_support import ROOT, sheet
    from tests.worker2_support import OWNER, fixture, settle
    # Owning Corpse Servant does not create a servant in this table fixture.
    # Supply a genuinely eligible, visible undead creature as the grave anchor.
    foe = sheet([])
    foe['identity']['creature_type'] = 'Undead'
    combat, table, mid = fixture(tmp_path, ['TAL_DEATH_DEATHLY_PASSAGE', 'TAL_DEATH_CORPSE_SERVANT'],
                               foe_sheet=foe)
    native = death_riders._grave_anchors
    calls = Counter()
    def counted(e, a):
        calls[(id(e), read_queries.enumeration_cache(e)['revision'], a.entity_id,
               a.position.x, a.position.y, a.position.z, id(getattr(e, '_shot_geometry', None)))] += 1
        return native(e, a)
    with monkeypatch.context() as patch:
        patch.setattr(death_riders, '_grave_anchors', counted)
        probe = combat._load_session(mid)
        first = CombatService(ROOT, tmp_path)._legal_candidates(probe)
    assert calls and max(calls.values()) == 1, 'anchor roster rebuilt for each destination'
    assert any(((probe.engine.action_catalog[c.source_definition_id].parameters or {}).get('typed') or {}).get('source')
               == 'TAL_DEATH_DEATHLY_PASSAGE' for c in first
               if c.source_definition_id in probe.engine.action_catalog)
    before = [c.model_dump(mode='json') for c in first]
    again = CombatService(ROOT, tmp_path)._legal_candidates(combat._load_session(mid))
    assert [c.model_dump(mode='json') for c in again] == before
    menu = table.state(mid)['menu']
    assert menu['actor_id'] == OWNER
    hold = next(c.candidate_id for c in first if c.source_definition_id == 'system:combat.hold_position')
    settle(table, mid, hold)
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'
    assert table.state(mid)['menu']

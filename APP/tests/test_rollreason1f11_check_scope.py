"""Review F10RSC finding 1: a nested roll-check scope keeps its caller's metadata.

``formation_check`` owns a cultivation check scope (``check_kind='cultivation'``)
and then calls ``engine.roll_check``, which opens its own scope. When the inner
frame dropped the caller's fields, ``d20_context()`` reported a bare check with
no check kind, so Furnace Motion's d20_bonus provider never matched: the
Proficiency Bonus was neither applied nor consumed. A check that needs the bonus
failed and the benefit survived for an unrelated later check.
"""
import pytest

from combat.ext import formations, furnace_core
from tests.auto_worker1_support import fight
from tests.hunt15_support import LEFT, reload

CHECK = furnace_core.CHECK
CORE = furnace_core.CORE
SOURCE = 'tianxia.subpath.qi.devil_heart_second_furnace.feature.second_furnace_core'
BONUS = 7
DC = 10
NATURAL = 5


def _hold_motion(engine, actor):
    """Furnace Motion: +PB to your next Cultivation Check, as the real row files it."""
    engine._apply_condition(actor, CHECK, CORE, actor.entity_id,
                            expires_on=f'END_OF_SOURCE_TURN_AT:{actor.turns_started + 1}',
                            data={'bonus': BONUS, 'label': 'Furnace Motion'})


def _fixed_natural(engine, monkeypatch, value=NATURAL):
    """One deterministic d20, so only the bonus can decide the threshold."""
    monkeypatch.setattr(engine.roller, '_die', lambda sides: (value, 0))


def test_formation_check_applies_furnace_motion_bonus_and_consumes_it_once(tmp_path, monkeypatch):
    combat, _table, mid = fight(tmp_path, [], left_score=50, right_score=214)
    engine = reload(combat, mid)
    actor = engine.state.actors[LEFT]
    _hold_motion(engine, actor)
    assert any(c.condition_id == CHECK for c in actor.conditions.values()), 'Furnace Motion was not filed'
    _fixed_natural(engine, monkeypatch)

    # Without the caller's check kind this d20 + 0 misses the DC and the bonus
    # survives; the retained scope applies and spends it.
    first = formations.formation_check(engine, actor, {'attack_bonus': 0}, DC, SOURCE, 'Formation Check')
    assert first is True
    roll = engine.rolls[-1]
    assert roll.natural_result == NATURAL
    assert roll.modifier == BONUS and roll.total == NATURAL + BONUS, roll.model_dump(mode='json')

    bonuses = [e for e in engine.events
               if e.event_type == 'D20_REWRITTEN' and (e.payload or {}).get('operation') == 'bonus']
    assert [e.payload['bonus'] for e in bonuses] == [BONUS], bonuses
    assert all(e.source_definition_id == CORE for e in bonuses)

    # One-time: the next Cultivation Check gets no bonus and misses the DC.
    assert not any(c.condition_id == CHECK for c in actor.conditions.values())
    second = formations.formation_check(engine, actor, {'attack_bonus': 0}, DC, CORE, 'Formation Check')
    assert second is False
    assert engine.rolls[-1].total == NATURAL, engine.rolls[-1].model_dump(mode='json')

    # Stored state stays persistence-shaped (ints/strings only) and the spent
    # condition is absent from the reloaded state model a commit carries.
    stored = engine.state.model_dump(mode='json')
    assert not any(c['condition_id'] == CHECK for c in stored['actors'][LEFT]['conditions'])
    checks = [e for e in engine.events
              if e.event_type == 'CHECK_ROLLED' and e.source_definition_id == SOURCE]
    assert checks and checks[-1].payload['actor']['natural_result'] == NATURAL


def test_unrelated_nested_check_still_starts_clean(tmp_path, monkeypatch):
    """A different reason is a different roll: no inherited check kind, so no bonus."""
    combat, _table, mid = fight(tmp_path, [], left_score=50, right_score=214)
    engine = reload(combat, mid)
    actor = engine.state.actors[LEFT]
    _hold_motion(engine, actor)
    _fixed_natural(engine, monkeypatch)

    reason = f'CHECK:{SOURCE}:Unrelated'
    with engine.d20_scope({'kind': 'check', 'actor_id': actor.entity_id, 'source_id': SOURCE,
                           'source_actor_id': actor.entity_id, 'check_kind': 'cultivation',
                           'reason': reason, 'hazards': []}):
        with engine.d20_scope({'kind': 'check', 'actor_id': actor.entity_id, 'reason': 'CHECK:OTHER:Other'}):
            assert engine.d20_context().get('check_kind') is None
    assert any(c.condition_id == CHECK for c in actor.conditions.values()), 'bonus was spent on an unrelated roll'


@pytest.mark.parametrize('kind', ['save', 'attack'])
def test_other_kinds_do_not_inherit_check_metadata(tmp_path, monkeypatch, kind):
    combat, _table, mid = fight(tmp_path, [], left_score=50, right_score=214)
    engine = reload(combat, mid)
    actor = engine.state.actors[LEFT]
    reason = 'CHECK:same:reason'
    with engine.d20_scope({'kind': 'check', 'actor_id': actor.entity_id, 'check_kind': 'cultivation',
                           'reason': reason}):
        with engine.d20_scope({'kind': kind, 'actor_id': actor.entity_id, 'reason': reason}):
            assert engine.d20_context().get('check_kind') is None
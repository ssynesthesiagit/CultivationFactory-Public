"""Moon recipients obey shared targeting after real table commits and reloads."""
import pytest

from combat.target_knowledge import knowledge
from combat.targeting import line_of_effect
from tests.r1i_service_support import OWNER, FOE, SECOND, THIRD, candidate
from tests.test_auto85f1_monkey_review import (
    M, MOON_ATTACK, _labels, _to_turn, _ranged_miss, drive, monkey_fixture,
)
from tests.test_sph_monkey_style_r2 import _invisibility, _setup
from tests.test_r1i_round3 import reload


def _move(table, mid, send, x, y):
    option = next(m for m in table.state(mid)['menu']['moves']
                  if m['destination'] == {'x': x, 'y': y})
    assert send(option['candidate_id'])['status'] == 'COMMITTED'


def _moon(table, mid, send, missed=SECOND):
    _to_turn(table, mid, FOE)
    prompts = drive(send, candidate(table, mid, 'Test longbow', missed),
        use=('Monkey Catches the Moon',),
        pick=['Stay where you are', MOON_ATTACK, 'Third'])
    return [p for p in prompts if (p.get('choice') or {}).get('options')
            and 'Choose the creature within 20 feet' in str(p.get('moment') or '')]


def _swings(engine):
    return [e for e in engine.events if e.event_type == 'ATTACK_ROLLED' and e.actor_id == OWNER]


def test_moon_does_not_offer_unknown_concealed_recipient_after_reload(tmp_path):
    def prepare(bundles):
        _ranged_miss(bundles)
        _invisibility(bundles, THIRD)
    _, table, mid, send, _ = monkey_fixture(tmp_path, [M + 'MONKEY_CATCHES_THE_MOON'],
        bundle_transform=prepare, allies=(SECOND,), extra_foe=True,
        positions={OWNER: {'x': 5, 'y': 3}, SECOND: {'x': 5, 'y': 4},
                   FOE: {'x': 3, 'y': 3}, THIRD: {'x': 8, 'y': 3}})
    held = reload(tmp_path, mid)
    assert knowledge(held, held.state.actors[OWNER], held.state.actors[THIRD]) is None
    _to_turn(table, mid, THIRD)
    drive(send, candidate(table, mid, 'Become invisible'), use=())
    _move(table, mid, send, 8, 6)
    _move(table, mid, send, 5, 6)
    held = reload(tmp_path, mid)
    assert knowledge(held, held.state.actors[OWNER], held.state.actors[THIRD]) is None
    menus = _moon(table, mid, send)
    assert not menus, [_labels(p) for p in menus]  # Only the visible attacker is legal.
    after = reload(tmp_path, mid)
    assert len(_swings(after)) == 1 and FOE in _swings(after)[0].target_ids


@pytest.mark.parametrize('start,end,offered', [(9, 10, True), (10, 9, False)])
def test_moon_uses_remembered_square_for_cap_and_label_after_reload(tmp_path, start, end, offered):
    def prepare(bundles):
        _ranged_miss(bundles)
        _invisibility(bundles, THIRD)
    _, table, mid, send, _ = monkey_fixture(tmp_path, [M + 'MONKEY_CATCHES_THE_MOON'],
        bundle_transform=prepare, allies=(SECOND,), extra_foe=True, wide=True,
        positions={OWNER: {'x': 5, 'y': 6}, SECOND: {'x': 5, 'y': 7},
                   FOE: {'x': 3, 'y': 6}, THIRD: {'x': start, 'y': 6}})
    _to_turn(table, mid, THIRD)
    drive(send, candidate(table, mid, 'Become invisible'), use=())
    _move(table, mid, send, end, 6)
    held = reload(tmp_path, mid)
    known = knowledge(held, held.state.actors[OWNER], held.state.actors[THIRD])
    assert known.mode == 'LAST_OBSERVED' and known.position.x == start
    menus = _moon(table, mid, send)
    assert bool(menus) is offered, [_labels(p) for p in menus]
    after = reload(tmp_path, mid)
    if offered:
        assert any('last saw Third' in label for label in _labels(menus[0]))
        assert not _swings(after)
        missed = [e for e in after.events if e.event_type == 'ATTACK_LOCATION_MISSED' and e.actor_id == OWNER]
        assert len(missed) == 1 and missed[0].payload['destination'] == {'x': start, 'y': 6}
    else:
        assert len(_swings(after)) == 1 and FOE in _swings(after)[0].target_ids


def test_moon_excludes_recipient_behind_solid_pillar_after_reload(tmp_path):
    _, table, mid, send, _ = monkey_fixture(tmp_path, [M + 'MONKEY_CATCHES_THE_MOON'],
        bundle_transform=_ranged_miss, allies=(SECOND,), extra_foe=True,
        positions={OWNER: {'x': 5, 'y': 3}, SECOND: {'x': 5, 'y': 5},
                   FOE: {'x': 3, 'y': 3}, THIRD: {'x': 8, 'y': 5}})
    held = reload(tmp_path, mid)
    # The ally sees Third and shares its square, but a solid pillar still blocks the owner.
    assert knowledge(held, held.state.actors[OWNER], held.state.actors[THIRD]) is not None
    assert not line_of_effect(held, held.state.actors[OWNER], target=held.state.actors[THIRD])
    menus = _moon(table, mid, send)
    assert not menus, [_labels(p) for p in menus]
    after = reload(tmp_path, mid)
    assert len(_swings(after)) == 1 and FOE in _swings(after)[0].target_ids


def test_moon_offers_large_footprint_at_printed_twenty_foot_cap_after_reload(tmp_path):
    def prepare(bundles):
        _ranged_miss(bundles)
        _setup(bundles, THIRD, 'Grow large', [
            {'type': 'size_change', 'size': 'Large', 'expires_on': 'UNTIL_REMOVED'}])
    _, table, mid, send, _ = monkey_fixture(tmp_path, [M + 'MONKEY_CATCHES_THE_MOON'],
        bundle_transform=prepare, allies=(SECOND,), extra_foe=True, wide=True,
        positions={OWNER: {'x': 5, 'y': 6}, SECOND: {'x': 5, 'y': 7},
                   FOE: {'x': 3, 'y': 6}, THIRD: {'x': 0, 'y': 6}})
    _to_turn(table, mid, THIRD)
    drive(send, candidate(table, mid, 'Grow large'), use=())
    held = reload(tmp_path, mid)
    assert held._effect_distance(held.state.actors[OWNER], held.state.actors[THIRD]) == 20
    menus = _moon(table, mid, send)
    assert menus and any('Third' in label for label in _labels(menus[0]))
    after = reload(tmp_path, mid)
    assert len(_swings(after)) == 1 and THIRD in _swings(after)[0].target_ids

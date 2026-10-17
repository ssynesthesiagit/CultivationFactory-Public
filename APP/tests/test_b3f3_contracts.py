"""General DC history and self-benefit contracts found by the B3F3 sweep."""
import pytest

from combat import ext, typed_executor as te
from tests.h1_support import ME, FOE, duel
from tests.test_p15_save_condition_duration import _shared_save_context


@pytest.mark.parametrize('named', [False, True])
def test_printed_dc_is_one_check_not_a_defending_roll(monkeypatch, named):
    engine = duel([])
    ctx = _shared_save_context(engine, [])
    calls = []
    # A test-owned named DC provider; no production resolver is replaced.
    ext.effects()
    monkeypatch.setitem(ext._HOOKS, 'check_dc', [lambda *args: 14])
    monkeypatch.setitem(ext._HOOKS, 'd20_result', [lambda e, roll, intent: calls.append(roll.actor_id)])
    target = {'kind': 'dc', **({'of': 'test:provider'} if named else {'dc': 14})}
    before = len(engine.rolls)
    result = te.resolve_opposed_check(ctx, ctx.target, {'kind': 'cultivation'}, target)
    assert result.dc == 14
    assert len(engine.rolls) - before == 1
    assert calls == [ME]
    event = next(e for e in reversed(engine.events) if e.event_type == 'CHECK_ROLLED')
    assert event.payload['roll_kind'] == 'dc_check'
    assert event.payload['check'] == 'Cultivation Check'
    assert event.payload['dc'] == 14
    if named:
        assert event.payload['target']['dice'] == []
        assert event.payload['target']['total'] == 14


def test_explicit_self_speed_benefit_survives_harmful_area_scope():
    engine = duel([])
    ctx = _shared_save_context(engine, [])
    ctx.typed['area'] = {'shape': 'sphere', 'size_ft': 20, 'recipients': 'enemies', 'exclude_self': True}
    te.block_speed(ctx, {'type': 'speed', 'applies_to': 'self', 'becomes': 40, 'duration': 'one_minute'})
    assert engine._effective_speed(engine.state.actors[ME]) == 40
    assert engine._effective_speed(engine.state.actors[FOE]) == engine.state.actors[FOE].speed_ft


@pytest.mark.parametrize('ability,name,choice', [
    ('tianxia.talent.spirit_companions.break_the_cruel_seal',
     'Break the Cruel Seal', 'Suppress the seal'),
    ('tianxia.talent.spirit_companions.exorcist_s_mercy',
     "Exorcist's Mercy", 'One layer of the Binding Seal on this creature ends'),
])
def test_named_dc_history_names_the_spirit_and_cultivation_check_after_reload(
        tmp_path, monkeypatch, ability, name, choice):
    """Render actual accepted abilities after persistence, not a synthetic roll payload."""
    from combat.history_feed import format_history_feed
    from tests.test_auto5_spirit_seals import sealer, load, LEFT
    from tests.r10_fixup_support import cast_sender, commit, fixed_dice

    combat, table, mid, spirit = sealer(tmp_path, monkeypatch, extra=[ability])
    fixed_dice(monkeypatch, [20] * 300)
    commit(cast_sender(combat, table, mid, name, contains=choice, target=spirit))
    fresh = load(combat, tmp_path, mid)
    events = [e.model_dump(mode='json') for e in fresh.engine.events]
    check = next(e for e in events if e['event_type'] == 'CHECK_ROLLED'
                 and ability in e['source_definition_id'])
    rows = format_history_feed(
        events, [], pre_state=None, post_state=fresh.engine.state.model_dump(mode='json'),
        actor_names={LEFT: 'Binder', spirit: 'Bound spirit'},
        definition_names={check['source_definition_id']: name})
    line = next(row['summary'] for row in rows if row['event_sequence'] == check['sequence'])
    assert 'Bound spirit' in line, line
    assert 'Cultivation Check' in line, line
    assert name in line and 'Binder' in line, line
    assert f"against {check['payload']['dc']} (" in line, line
    assert 'd20' not in line.split('against', 1)[1], line
    assert 'success' in line, line
    assert check['payload']['target']['dice'] == []
    assert fresh.mechanical.replay()['status'] == 'PASS'

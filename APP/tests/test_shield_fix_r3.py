"""Delayed Shield rescues at real table end-turn, including rollback/reload/replay."""
import pytest

from tests.test_auto55_shield import ME, TS, _conds
from tests.test_lock_choices import install
from tests.test_shield_fix_r1 import reload, table_action
from tests.test_shield_fix_r2 import FOCUS, advance, defense, finish, match

CRACKED = 'condition:typed.shield_cracked'
SUPPRESSED = 'condition:typed.shield_destruction_suppressed'
BROKEN = 'condition:typed.shield_broken'


@pytest.mark.parametrize('first,second', [
    ('cracked', 'destruction'), ('cracked', None),
    ('destruction', 'intact'), ('destruction', None),
    ('destruction', 'cracked'), ('cracked', 'face'),
])
def test_delayed_break_offers_other_rescue_transactionally(tmp_path, monkeypatch, first, second):
    install(monkeypatch, 'd20_result', lambda *a: {
        'source_id': 'test:crit', 'operation': 'replace', 'natural_result': 20})
    service, table, mid = match(tmp_path, [
        'TAL_SHIELD_UNBROKEN_RIM', 'TAL_SHIELD_SHIELD_SOUL_NEVER_FALLS',
        TS + 'sacrificial_shield'], packet='save')
    assert table_action(table, mid, 'end')['status'] == 'COMMITTED'

    def initial(p):
        source = p['context']['reaction_source_id']
        if 'shield_soul_never_falls' in source:
            return ['destruction'] if first == 'destruction' else None
        if 'unbroken_rim' in source:
            return ['cracked']
        if 'sacrificial_shield' in source:
            return ['break']
        return defense(p)

    finish(table, mid, 'Bi Shou (Dagger) attack', initial)
    service = reload(service, mid)
    table.combat = service
    marker = CRACKED if first == 'cracked' else SUPPRESSED
    assert marker in _conds(service._load_session(mid).engine.state.actors[ME])
    original_deadline = next(c.expires_on for c in service._load_session(mid).engine.state.actors[ME].conditions.values()
                             if c.condition_id == marker)
    advance(table, mid, ME)
    if first == 'cracked':
        # Even with Focus restored, the expiring Unbroken Rim cannot rescue itself.
        assert table_action(table, mid, 'Recover Focus')['status'] == 'COMMITTED'
    service = reload(service, mid)
    table.combat = service
    engine = service._load_session(mid).engine
    before = engine.state.model_dump(mode='json')
    events = [e.model_dump(mode='json') for e in engine.events]
    result = table_action(table, mid, 'end')
    assert result['status'] == 'REACTION_REQUIRED', result
    prompt = result['reaction']
    rescue = 'shield_soul_never_falls' if first == 'cracked' else 'unbroken_rim'
    assert rescue in prompt['context']['reaction_source_id']
    assert 'Shield Bearer' in prompt['trigger'] and 'Shield' in prompt['trigger']
    assert 'end' in prompt['trigger'] and 'temporary protection ends' in prompt['trigger']
    assert engine.state.model_dump(mode='json') == before
    assert [e.model_dump(mode='json') for e in engine.events] == events

    # A fresh service must present the same checkpoint, without expiring or paying.
    service = reload(service, mid)
    table.combat = service
    pending = table_action(table, mid, 'end')
    assert pending['reaction'] == prompt
    # The face rescue has a second owned choice; finish also checks every pause.
    prompts = finish(table, mid, 'end', lambda p: [second] if rescue in p['context']['reaction_source_id']
                     and second else [p['choice']['options'][0]['id']]
                     if 'choice:shield.edge:' in p['context']['reaction_source_id'] else None)
    assert rescue in prompts[0]['context']['reaction_source_id']
    service = reload(service, mid)
    table.combat = service
    me = service._load_session(mid).engine.state.actors[ME]
    conditions = _conds(me)
    assert marker not in conditions or (marker == CRACKED and second == 'cracked')
    assert (BROKEN in conditions) == (second is None or second == 'face')
    if BROKEN in conditions:
        assert all(c.expires_on == 'UNTIL_REMOVED' for c in me.conditions.values() if c.condition_id == BROKEN)
    assert (SUPPRESSED in conditions) == (second == 'destruction')
    assert (CRACKED in conditions) == (second == 'cracked')
    assert me.resources[FOCUS] == (0 if second in ('intact', 'cracked') else 1)
    assert not any(e.event_type == 'GM_RIDER' and 'effect_expir' in str(e.payload)
                   for e in service._load_session(mid).engine.events)
    if second in ('cracked', 'destruction'):
        renewed = CRACKED if second == 'cracked' else SUPPRESSED
        assert next(c.expires_on for c in me.conditions.values() if c.condition_id == renewed) != original_deadline
        advance(table, mid, ME)
        later = finish(table, mid, 'end', lambda p: None)
        assert not any('shield_soul_never_falls' in p['context']['reaction_source_id'] for p in later)
        service = reload(service, mid)
        conditions = _conds(service._load_session(mid).engine.state.actors[ME])
        assert BROKEN in conditions and CRACKED not in conditions and SUPPRESSED not in conditions


@pytest.mark.parametrize('kind', ['condition', 'modifier'])
def test_expiry_choice_errors_roll_back_through_observational_turn_hook(monkeypatch, kind):
    from combat.ext import CheckpointError, effect_durations
    from tests.test_effect_durations import _fight

    engine, me, _ = _fight('EXPIRY-CHOICE-ROLLBACK')
    deadline = effect_durations.token('end', me.entity_id, me.turns_started)
    if kind == 'condition':
        engine._apply_condition(me, 'condition:typed.test_expiry', 'test:expiry', me.entity_id,
                                expires_on=deadline)
    else:
        engine._add_modifier(me, 'test:expiry', 'armor_class', 'ADD', 1, 'ALL', expires_on=deadline)
    before = engine.state.model_dump(mode='json')
    events = [e.model_dump(mode='json') for e in engine.events]

    def fail(engine, holder, row):
        holder.current_hp -= 1  # A partial expiry mutation must not survive.
        raise ValueError('test expiry failure')

    install(monkeypatch, 'effect_expiring_choice', fail)
    with pytest.raises(CheckpointError, match='test expiry failure'):
        engine.end_turn()
    assert engine.state.model_dump(mode='json') == before
    assert [e.model_dump(mode='json') for e in engine.events] == events

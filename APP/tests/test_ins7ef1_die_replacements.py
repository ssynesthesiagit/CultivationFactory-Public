"""Composed rerolls through real table commits, cold reload and mechanical replay."""
import pytest

from combat.ext import red_execution as red
from tests.auto_worker1_support import LEFT, RIGHT, act, resolve
from tests.test_a2_ins7e_batch4 import fixture, fresh, mark

EMPOWER = 'choice:needle.insights_empowered'
QI = 'resource:core.qi'


@pytest.mark.parametrize('delivery,order', [('headsman', 'empower_first'), ('headsman', 'red_first'),
    ('rending', 'empower_first'), ('rending', 'red_first'), ('attached', 'empower_first')])
@pytest.mark.parametrize('keep', ['new', 'original'])
def test_composed_rerolls_commit_effective_dice_and_show_current_result(tmp_path, monkeypatch, delivery, order, keep):
    # Imports can register either native provider first. Exercise both orders
    # through a scoped test dispatch adapter; do not impose an invented rules
    # priority or replace any engine/ability implementation.
    from combat import ext
    registered = ext.subscribers

    def providers(point):
        rows = registered(point)
        if point == 'confirmed_damage_roll_adjustment':
            first = 'insights_four' if order == 'empower_first' else 'red_execution'
            return tuple(sorted(rows, key=lambda row: row.__module__.rsplit('.', 1)[-1] != first))
        return rows

    monkeypatch.setattr(ext, 'subscribers', providers)
    c, t, mid = fixture(tmp_path, empowered=True, real=delivery != 'attached',
                        attached=delivery == 'attached', fixed_primary=delivery == 'attached')
    mark(c, t, mid)
    before = fresh(c, mid)
    if delivery == 'attached':
        source = 'Strike'
    elif delivery == 'headsman':
        source = next(a.source_definition_id for a in before.action_catalog.values()
                      if a.owner_id == LEFT and (a.parameters.get('typed') or {}).get('source')
                      == 'TAL_AXES_HEADSMAN_S_MANDATE')
    else:
        source = next(a.source_definition_id for a in before.action_catalog.values()
                      if a.owner_id == LEFT and ((a.parameters.get('typed') or {}).get('modifier') or {}).get('id')
                      == 'TAL_AXES_RENDING_HEW' and 'Focus' not in a.display_name)
    _, prompts = resolve(lambda answers: act(t, mid, source, answers, target_id=RIGHT),
                         {EMPOWER: [QI], red.DIE: ['0'], red.RESULT: [keep]})
    after = fresh(c, mid)
    receipt = next(ev.payload for ev in after.events if ev.source_definition_id == red.FEATURE
                   and 'damage_adjustment' in ev.payload)
    original = next(r for r in after.rolls if r.roll_id == receipt['original_roll_id'] and r.dice)
    empower = next(r for r in after.rolls if r.reason.startswith('DAMAGE_REROLL:')
                   and r.reason != 'DAMAGE_REROLL:' + red.FEATURE)
    replacement = next(r for r in after.rolls if r.reason == 'DAMAGE_REROLL:' + red.FEATURE)
    effective = list(original.dice)
    empower_first = empower.counter_start < replacement.counter_start
    assert empower_first == (order == 'empower_first')
    for step in (('empower', 'red') if empower_first else ('red', 'empower')):
        if step == 'empower':
            indices = sorted(range(len(effective)), key=lambda i: (effective[i], i))[:len(empower.dice)]
            for index, value in zip(indices, empower.dice):
                effective[index] = value
        else:
            current = effective[0]
            if keep == 'new':
                effective[0] = replacement.total
    expected = original.total - sum(original.dice) + sum(effective)
    assert receipt['damage_adjustment'] == (replacement.total - current if keep == 'new' else 0)
    die_prompt = next(p for p in prompts if p['context']['reaction_source_id'] == red.DIE)
    assert {o['id'] for o in die_prompt['choice']['options']} == {str(i) for i in range(len(effective))}
    assert f'currently {current} on' in die_prompt['choice']['options'][0]['label']
    result_prompt = next(p for p in prompts if p['context']['reaction_source_id'] == red.RESULT)
    assert f'({current})' in result_prompt['choice']['options'][0]['label']
    packet = next(ev for ev in after.events if ev.event_type == 'DAMAGE_ROLLED'
                  and ev.payload.get('roll_id') == original.roll_id
                  and ev.payload.get('reason') == original.reason
                  and tuple(ev.payload.get('dice') or ()) == original.dice)
    if delivery == 'attached':
        assert original.reason == 'DAMAGE:' + packet.source_definition_id
        assert len(original.dice) == 2
    committed = [ev for ev in after.events if ev.event_type == 'DAMAGE_COMMITTED'
                 and ev.target_ids == (RIGHT,) and ev.sequence > before.state.event_sequence]
    assert committed
    assert next(ev for ev in committed if ev.sequence > packet.sequence).payload['hp_damage'] == expected, \
        'Committed damage must reflect sequential die replacements'
    assert packet.payload.get('combined_total', packet.payload.get('adjusted_total', original.total)) == expected
    assert before.state.actors[RIGHT].current_hp - after.state.actors[RIGHT].current_hp == sum(
        ev.payload['hp_damage'] for ev in committed)
    payments = [ev for ev in after.events if ev.event_type == 'RESOURCE_SPENT'
                and ev.actor_id == LEFT and ev.payload.get('resource_id') == QI
                and ev.sequence > before.state.event_sequence]
    assert sum(ev.payload['amount'] for ev in payments
               if ev.source_definition_id == 'insight.legacy-empowered-technique') == 1
    gains = [ev for ev in after.events if ev.event_type == 'RESOURCE_GAINED'
             and ev.actor_id == LEFT and ev.payload.get('resource_id') == QI
             and ev.sequence > before.state.event_sequence]
    assert after.state.actors[LEFT].resources[QI] == before.state.actors[LEFT].resources[QI] - sum(
        ev.payload['amount'] for ev in payments) + sum(ev.payload['gained'] for ev in gains)
    assert any(row.condition_id == red.USED for row in after.state.actors[LEFT].conditions.values())


def test_original_die_adjustments_negative_control_reaches_committed_damage(tmp_path, monkeypatch):
    """Recreate the old independent-delta contract, without changing production files.

    Indexed replies are converted to the same original-die deltas the old
    settlement summed. The real table must expose the error at committed HP,
    rather than fail merely because a fixture assumed a provider order.
    """
    from combat import ext, damage_roll_replacements as replacements

    def independent(point, *args, roll):
        delta = sum(replacements.apply(roll, provider(*args, roll)).total - roll.total
                    for provider in ext.subscribers(point))
        return roll.model_copy(update={'total': roll.total + delta})

    monkeypatch.setattr(replacements, 'settle', independent)
    with pytest.raises(AssertionError, match='Committed damage must reflect sequential die replacements'):
        test_composed_rerolls_commit_effective_dice_and_show_current_result(
            tmp_path, monkeypatch, 'headsman', 'red_first', 'new')

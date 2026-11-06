"""Public synthetic regressions for independent roll-reason receipts and target scope."""
from types import SimpleNamespace

from combat.roll_reasons import later_source, standing, text, unique_sources


def test_later_source_cancellation_keeps_both_explanations():
    engine = SimpleNamespace()
    earlier = {'effect': 'Poisoned', 'owner': 'Mira', 'kind': 'disadvantage',
               'why': 'the attacker is Poisoned'}
    later = later_source(engine, {'mode': 'ADVANTAGE', 'effect': 'Rallying Standard',
                                  'why': 'the banner grants Advantage'})
    rows = unique_sources([earlier, later])
    assert {row['effect'] for row in rows} == {'Poisoned', 'Rallying Standard'}
    explanation = text('NORMAL', rows)
    assert 'Advantage' in explanation and 'Disadvantage' in explanation and 'cancels' in explanation


def test_same_kind_sources_are_not_collapsed_by_mode():
    rows = unique_sources([
        {'effect': 'Poisoned', 'owner': 'Mira', 'kind': 'disadvantage', 'why': 'the attacker is Poisoned'},
        {'effect': 'Steady Stance', 'owner': 'Oren', 'kind': 'disadvantage', 'why': 'the stance hinders the attack'},
    ])
    assert [row['effect'] for row in rows] == ['Poisoned', 'Steady Stance']


def test_attack_mode_vs_standing_text_is_target_specific():
    target = SimpleNamespace(entity_id='target-1', display_name='Oren')
    actor = SimpleNamespace(entity_id='actor-1', conditions={}, modifiers={
        'vex': SimpleNamespace(consumed=False, target_field='attack_mode_vs',
                               value='ADVANTAGE:target-1', source_definition_id='test:vex'),
    })
    engine = SimpleNamespace(state=SimpleNamespace(actors={'target-1': target, 'actor-1': actor}, zones={}),
                             action_catalog={})
    rows = standing(engine, actor)
    assert any('Your attacks against Oren only' in row and 'Advantage' in row for row in rows)
    assert not any(row.startswith('Your attacks:') and 'Advantage' in row for row in rows)

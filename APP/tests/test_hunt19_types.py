"""Printed target eligibility at the table, including unknown creature types."""
import pytest

from tests.hunt19_support import fight, send, reload, LEFT, RIGHT
from tests.test_lock2_persistence import act


@pytest.mark.parametrize('types,allowed', [((), False), (('beast',), False), (('undead',), False),
    (('ghost',), True), (('possessing spirit',), True), (('incorporeal undead',), True),
    (('undead', 'incorporeal'), True), (('soul-bound creature',), True)])
def test_soul_hook_only_offers_printed_types_and_reloads(tmp_path, types, allowed):
    combat, table, mid = fight(tmp_path, ['TAL_DEATH_SOUL_HOOK'], right_types=types)
    targets = [o['target_ids'] for g in table.state(mid)['menu']['actions'] if g['label'] == 'Soul Hook' for o in g['options']]
    assert ([RIGHT] in targets) is allowed
    if allowed:
        sender = send(table, mid, 'Soul Hook', target=RIGHT)
        answers = []
        for _ in range(10):
            result = sender(answers)
            if result['status'] == 'COMMITTED':
                break
            answers.append({**result['reaction']['context'], 'selection': 'DECLINE'})
        assert result['status'] == 'COMMITTED'
    else:
        assert act(table, mid, 'system:combat.hold_position')['status'] == 'COMMITTED'
    engine = reload(combat, tmp_path, mid)
    assert engine.state.actors[RIGHT].creature_types == types


@pytest.mark.parametrize('label,key,good', [('Command the Unquiet', 'TAL_DEATH_COMMAND_THE_UNQUIET', 'undead'),
                                         ('Soul Funeral', 'TAL_DEATH_SOUL_FUNERAL', 'ghost')])
@pytest.mark.parametrize('qualifies', [False, True])
def test_other_printed_type_targets_use_the_same_guard(tmp_path, label, key, good, qualifies):
    combat, table, mid = fight(tmp_path, [key], right_types=(good,) if qualifies else ('beast',))
    targets = [o['target_ids'] for g in table.state(mid)['menu']['actions'] if g['label'] == label for o in g['options']]
    assert ([RIGHT] in targets) is qualifies
    assert act(table, mid, 'system:combat.hold_position')['status'] == 'COMMITTED'
    reload(combat, tmp_path, mid)


def test_local_ai_never_immobilizes_unknown_or_beast_targets(tmp_path):
    combat, table, mid = fight(tmp_path, ['TAL_DEATH_SOUL_HOOK'], right_types=('beast',), mode='LOCAL_AUTO', ask=False)
    result = table.auto_step(mid, table.state(mid)['last_sequence'])
    assert result['status'] == 'COMMITTED'
    engine = reload(combat, tmp_path, mid)
    assert not any(e.source_definition_id.endswith('TAL_DEATH_SOUL_HOOK') and e.event_type == 'INTENT_ACCEPTED' for e in engine.events)


def test_soul_hook_excludes_an_ordinary_persisted_warhorse(tmp_path):
    combat, table, mid = fight(tmp_path, ['TAL_DEATH_SOUL_HOOK'], right_rider=True)
    engine = combat._load_session(mid).engine
    horse = next(a for a in engine.state.actors.values() if a.owner_id == RIGHT and (a.summon or {}).get('mountable'))
    assert not any(horse.entity_id in o['target_ids'] for g in table.state(mid)['menu']['actions']
                   if g['label'] == 'Soul Hook' for o in g['options'])
    assert act(table, mid, 'system:combat.hold_position')['status'] == 'COMMITTED'
    assert not any(c.condition_id.endswith('death_soul_hook') for c in reload(combat, tmp_path, mid).state.actors[horse.entity_id].conditions.values())

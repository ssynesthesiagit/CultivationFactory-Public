"""Plain protection amounts at table commit/reload boundaries."""
import pytest

from tests.test_tabletop_hunt6 import table_fight, LEFT, RIGHT
from tests.test_lock2_persistence import act
from tests.test_carry import KIT
from tests.r10_fixup_support import cast_sender, fixed_dice
from tests.hunt19_support import reload


@pytest.mark.parametrize('key,label', [('TAL_FLOWERS_PETAL_WARD', 'Petal Ward'),
                                      ('tianxia.talent.ash.ash_ward', 'Ash Ward')])
@pytest.mark.parametrize('cl,dice', [(5, 1), (15, 2), (17, 3)])
def test_protection_summary_shows_current_reduction(tmp_path, monkeypatch, key, label, cl, dice):
    combat, table, mid = table_fight(tmp_path, [key], cl=cl, kit={'starting_kit': KIT}, ask=True, ally_talents=[])
    while table.state(mid)['menu']['actor_id'] != RIGHT:
        assert act(table, mid, 'end')['status'] == 'COMMITTED'
    fixed_dice(monkeypatch, [20, 20] + [4] * 40)
    sender = cast_sender(combat, table, mid, 'Bi Shou (Dagger) thrown', target=LEFT)
    prompts, answers = [], []
    for _ in range(12):
        result = sender(answers)
        if result['status'] == 'COMMITTED':
            break
        prompt = result['reaction']
        prompts.append(prompt)
        answers.append({**prompt['context'], 'selection': 'DECLINE'})
    ward = next(p for p in prompts if p['reaction'] == label)
    assert f'{dice}d8 + 2' in ward['summary']
    assert '|' not in ward['summary'] and 'triggering damage' in ward['summary']
    assert 'Reaction' in ward['cost'] and '1' in ward['cost']
    if label == 'Ash Ward':
        assert '4' in ward['summary'] and 'Smoke' in ward['summary']
    else:
        assert 'Poison' in ward['summary'] and 'next saving throw' in ward['summary']
    assert result['status'] == 'COMMITTED'
    reload(combat, tmp_path, mid)

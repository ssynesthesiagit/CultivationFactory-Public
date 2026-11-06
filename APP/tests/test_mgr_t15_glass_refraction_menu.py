"""Glass Heart Refraction: a turn-start scene answer rebuilds the bearer's menu in the same turn.

Review F12R blocking finding: after the owner answers "Major combat" at the bearer's
turn start, the paid state must be listed in the table menu the bearer then acts from,
both live and after a cold reload that replays the saved fight.

Synthetic table fixtures only: no live models, private inputs or GUI.
"""
import pytest

from combat.ext.foundation_combat import held
from combat.ext.glass_heart_refraction import CHOICE
from tests.glass_refraction_support import _asked, _glass_fight, _to_next_owner_turn, available
from tests.test_a2_foundations_two import use
from tests.worker2_support import OWNER, reload

PAID = 'Perfected — Glass Heart Refraction'


def _menu_labels(table, mid):
    return [group['label'] for group in table.state(mid)['menu']['actions']]


@pytest.mark.parametrize('match_seed', [None, 'GLASS-TURN-0'])
def test_major_combat_answer_is_in_the_live_menu_on_the_same_turn(tmp_path, match_seed):
    combat, table, mid = _glass_fight(tmp_path, match_seed=match_seed)
    prompts = _to_next_owner_turn(table, mid, {CHOICE: ['Major combat']})
    assert len(_asked(prompts)) == 1
    menu = table.state(mid)['menu']
    assert menu['actor_id'] == OWNER
    assert any(PAID in label for label in _menu_labels(table, mid)), \
        f'the paid state must be in the bearer menu right after the scene answer: {_menu_labels(table, mid)}'


@pytest.mark.parametrize('match_seed', [None, 'GLASS-TURN-0'])
def test_major_combat_answer_is_in_the_replayed_menu_after_reload(tmp_path, match_seed):
    combat, table, mid = _glass_fight(tmp_path, match_seed=match_seed)
    _to_next_owner_turn(table, mid, {CHOICE: ['Major combat']})
    assert available(reload(tmp_path, mid)), 'the replayed engine must offer the paid state'
    assert any(PAID in label for label in _menu_labels(table, mid)), \
        f'the live menu after reload must list the paid state: {_menu_labels(table, mid)}'


def test_full_prompt_answer_offer_use_sequence_with_cold_reloads(tmp_path):
    combat, table, mid = _glass_fight(tmp_path)
    prompts = _to_next_owner_turn(table, mid, {CHOICE: ['Major combat']})
    assert len(_asked(prompts)) == 1, 'the bearer turn start must ask the scene question once'
    assert reload(tmp_path, mid).state.current_actor_id == OWNER
    assert any(PAID in label for label in _menu_labels(table, mid))
    before_qi = reload(tmp_path, mid).state.actors[OWNER].resources['resource:core.qi']
    use(combat, table, mid, PAID)
    owner = reload(tmp_path, mid).state.actors[OWNER]
    assert held(owner, 'glass_refraction')
    assert owner.resources['resource:core.qi'] == before_qi - 2
    assert not owner.bonus_action_available


def test_turn_start_answer_offers_and_pays_without_pre_recording(tmp_path):
    """The bdiff route: the scene answer rides the same turn advance that asks it.

    No owner form is recorded first, so the menu can only list the paid state if
    the turn-start answer itself rebuilds it in the same turn.
    """
    combat, table, mid = _glass_fight(tmp_path)
    prompts = _to_next_owner_turn(table, mid, {CHOICE: ['Major combat']})
    asked = _asked(prompts)
    assert len(asked) == 1
    assert 'Major combat' in {option['id'] for option in asked[0]['choice']['options']}
    facts = [e for e in reload(tmp_path, mid).events if e.event_type == 'TABLE_FACT_RECORDED']
    assert len(facts) == 1 and 'glass_refraction' in str(facts[0].payload), 'only the scene answer is recorded'
    menu = table.state(mid)['menu']
    assert menu['actor_id'] == OWNER
    assert any(PAID in label for label in _menu_labels(table, mid))
    before_qi = reload(tmp_path, mid).state.actors[OWNER].resources['resource:core.qi']
    use(combat, table, mid, PAID)
    owner = reload(tmp_path, mid).state.actors[OWNER]
    assert held(owner, 'glass_refraction')
    assert owner.resources['resource:core.qi'] == before_qi - 2
    assert not owner.bonus_action_available

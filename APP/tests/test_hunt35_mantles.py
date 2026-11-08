"""Hunt35: scene activation never permits learning new Mantles in combat."""
import pytest

from combat.ext import mantles
from tests.hunt15_support import act, fight, LEFT, reload, turn
from tests.test_hunt25_mantle_setup import send


@pytest.mark.parametrize('ai', [False, True])
def test_hunt35_known_mantles_cannot_be_replaced_midfight(tmp_path, ai):
    combat, table, mid = fight(tmp_path, [mantles.FEATURE], seed='HUNT35-MANTLE')
    if ai:
        combat.set_controller_mode(mid, actor_id=LEFT, controller_mode='LOCAL_AUTO')
    response = send(table, mid)
    if not ai:
        assert response['status'] == 'REACTION_REQUIRED'
        prompt = response['reaction']
        assert not mantles.active(combat._load_session(mid).engine.state.actors[LEFT])
        answer = {**prompt['context'], 'selection': 'USE', 'option_ids': ['Wandering Sword-Saint']}
        response = send(table, mid, [answer])
    assert response['status'] == 'COMMITTED'
    engine = reload(combat, mid)
    expected = ['Warrior of a Fallen Age'] if ai else ['Wandering Sword-Saint']
    assert mantles.active(engine.state.actors[LEFT]) == expected
    original = mantles.known(engine, engine.state.actors[LEFT])
    combat.set_controller_mode(mid, actor_id=LEFT, controller_mode='MANUAL')
    turn(table, mid, LEFT)
    labels = [g['label'] for g in table.state(mid)['menu']['actions']]
    assert not any(label.startswith('Choose Former-Life Mantles:') for label in labels)
    assert 'Turn the Memory: Court Diplomat' not in labels
    assert act(table, mid, 'system:combat.hold_position')['status'] == 'COMMITTED'
    engine = reload(combat, mid)
    assert mantles.known(engine, engine.state.actors[LEFT]) == original
    assert mantles.active(engine.state.actors[LEFT]) == expected

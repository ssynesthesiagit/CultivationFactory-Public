"""A Bend the Blade + Return the Mountain pair spends 1 Martial Focus per talent, so it must not be offered at 1 Focus.

Before this gate the pair was offered at 1 Focus; the first talent spent the Focus and the second silently did nothing.
"""
from combat.ext.flowing_river import NAMES
from tests.auto_worker1_support import LEFT, RIGHT, act, fight, turn
from tests.test_auto2_flowing_river import FOCUS, RESPONSE, decline_steps, reload, settle
from tests.test_double_current_method import CHOICE, acquired

BEND_NAME = "Bend the Blade"
RETURN_NAME = "Return the Mountain to the Mountain"


def test_bend_and_return_pair_not_offered_at_one_martial_focus(tmp_path):
    c, t, m = fight(tmp_path, [RESPONSE, *NAMES], left_score=50, sheet_edit=acquired,
                    spheres=['tianxia.sphere.flowing_river'], extra_witness=True)
    turn(t, m, RIGHT)
    assert reload(c, m).state.actors[LEFT].resources[FOCUS] == 1

    def decline(prompt):
        return [] if prompt['context']['reaction_source_id'] == CHOICE else decline_steps(prompt)

    _, prompts = settle(lambda a: act(t, m, '.weapon.bi_shou', a, target_id=LEFT), decline)
    offer = next(p for p in prompts if p['context']['reaction_source_id'] == CHOICE)
    labels = [o['label'].split(' + ') for o in offer['choice']['options']]
    assert labels, 'pairs that need only one Martial Focus must still be offered'
    assert not any({BEND_NAME, RETURN_NAME} <= set(label) for label in labels), labels
    assert any(RETURN_NAME in label for label in labels), 'Return the Mountain with a Focus-free talent stays offered'

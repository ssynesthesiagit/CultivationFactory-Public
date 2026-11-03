"""Double Current pair text must name every Martial Focus cost in the pair (Return the Mountain spends 1 Focus)."""
from combat.ext.flowing_river import NAMES
from tests.auto_worker1_support import LEFT, RIGHT, act, fight, turn
from tests.test_auto2_flowing_river import RESPONSE, settle, decline_steps
from tests.test_double_current_method import CHOICE, acquired

RETURN_NAME = "Return the Mountain to the Mountain"
BEND_NAME = "Bend the Blade"


def test_return_mountain_pairs_do_not_claim_no_resource_cost(tmp_path):
    # Focus stays at its starting 1: a Bend + Return pair needs 2 (one per talent), so it is not offered here.
    c, t, m = fight(tmp_path, [RESPONSE, *NAMES], left_score=50, sheet_edit=acquired,
                    spheres=['tianxia.sphere.flowing_river'], extra_witness=True)
    turn(t, m, RIGHT)
    def decline(prompt):
        return [] if prompt['context']['reaction_source_id'] == CHOICE else decline_steps(prompt)
    _, prompts = settle(lambda a: act(t, m, '.weapon.bi_shou', a, target_id=LEFT), decline)
    offer = next(p for p in prompts if p['context']['reaction_source_id'] == CHOICE)
    options = offer['choice']['options']
    with_return = [o for o in options if RETURN_NAME in o['label'].split(' + ')]
    assert with_return, 'a Return the Mountain pair must be offered for this regression to mean anything'
    for option in with_return:
        description = option['description']
        assert 'No separate resource cost' not in description, (option['label'], description)
        assert RETURN_NAME + ' still costs its own 1 Martial Focus' in description, (option['label'], description)
    plain = [o for o in options if not {RETURN_NAME, BEND_NAME} & set(o['label'].split(' + '))]
    assert plain and all('No separate resource cost' in o['description'] for o in plain)
    both = [o for o in options if set(o['label'].split(' + ')) == {RETURN_NAME, BEND_NAME}]
    assert not both, 'Bend + Return needs 2 Martial Focus and must not be offered at 1'

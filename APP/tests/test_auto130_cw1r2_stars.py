"""CW1r2's Stars regressions, kept runnable on a branch without the Earth or Metal lanes' test modules.

The upstream ``test_cw1r2_review.py`` also carries "Burden the Blade" (Earth, auto/earth) cases that
import ``tests.test_auto45_metal`` and ``combat.ext.elements_earth``'s newer review state; those two
suites are not on this branch, so the module could not even be collected. The current gameplay cases below are
the ones this Sphere owns and they assert the same behaviour.
"""

from tests.auto_worker1_support import LEFT, RIGHT, act, fight, reload
from tests.test_auto130_stars import resolve as settle


def test_starbolt_choice_explains_actual_mark_benefits_without_losing_deadline_or_cost(tmp_path):
    """The mark prompt tells a player what the mark actually does, in plain words (checklist item 13)."""
    combat, table, mid = fight(tmp_path, ['STARS_BASE_STARBOLT'], left_attack_bonus=100)
    _, prompts = settle(lambda a: act(table, mid, 'Starbolt', a, target_id=RIGHT))
    prompt = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.starbolt_mark')
    text = str(prompt)
    for phrase in ['Visitor', 'next turn starts', '30 feet', 'Half Cover', 'ordinary Invisibility', 'Once per turn',
                   'no extra cost']:
        assert phrase in text
    assert any(v.condition_id.endswith('stellar_mark.' + LEFT)
               for v in reload(combat, mid).state.actors[RIGHT].conditions.values())

"""A rider is worded for whoever plays the ability (fight audit 2026-09-28, hunt item 6b).

authority/typed_mechanics/reviewed_final.d/wenxue.json turned the Sabers/Radiance reviewer's notes into riders, and seven of them were
written for the first playtest character: Hard Draw Cut's said "Wen Xue does not have Cruel Edge Method, so this branch never applies
to her", and H1-06 (190-192) showed it on Lu Bo's turn. combat/ext/wenxue_sabers.py acts on the acting character's own state and
needed no change; only the printed lines did.
"""

import json
from functools import cache

from combat.factory_compiler import TYPED_AUTHORITY
from tests.test_auto_support import _bundle

PLAYTEST_CHARACTERS = ("Wen Xue", "Lu Bo", "Li Wei")
HARD_DRAW_CUT = "tianxia.talent.sabers.hard_draw_cut"


@cache
def _authority() -> dict:
    return json.loads(TYPED_AUTHORITY.read_bytes())["mechanics"]


def test_no_rider_of_any_ability_names_a_playtest_character():
    named = [(key, rider) for key, mechanic in _authority().items()
             for rider in [*(mechanic.get("riders") or []), *(line for option in mechanic.get("options") or [] for line in option.get("riders") or [])]
             if any(name in rider for name in PLAYTEST_CHARACTERS)]
    assert not named, named[:3]


def test_hard_draw_cuts_wound_rider_is_worded_for_any_character_and_reaches_the_action():
    bundle = _bundle([HARD_DRAW_CUT], _authority()[HARD_DRAW_CUT]["sphere_id"])
    action = next(row for row in bundle["action_catalog"] if row["display_name"] == "Hard Draw Cut")
    riders = action["parameters"]["typed"]["riders"]
    assert len(riders) == 1 and riders[0].startswith("If you practice Cruel Edge Method")
    assert "Wen Xue" not in riders[0] and " her" not in riders[0]
    assert "GM call" in riders[0]  # the table tracks no Saber Wounds or Method, so the branch is left to the GM

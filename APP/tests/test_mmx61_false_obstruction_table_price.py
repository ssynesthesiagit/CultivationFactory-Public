"""Hunt 79 (MMX61 review fix 2): False Obstruction's table menu must show the price it really charges.

The earlier fix (85cf9b3e) corrected the option labels from a bare "(1 CP)" to the real price, but
only proved it by reading the compiled action catalogue. That cannot see the two ways this goes
wrong at the table: a menu that advertises one price while the executor charges another, and an
executor that charges the augment twice.

So these tests drive the real thing. A character builds False Obstruction, the table shows its menu,
the player picks each option through ``TabletopService.act``, and a *second* service reads the stored
fight back. Each option is checked twice: the price the menu printed against the number of Qi that
actually left the character.

The charge itself is correct and these tests exist to keep it that way. The printed text is

    Cost: 1 CP                                    <- the ability
    Augment 1 CP: The area becomes Heavily Obscured ...   <- one more, on top

so 1 CP plain and 2 CP for either augment.
"""

from __future__ import annotations

import re

import pytest

from combat.gate5_service import CombatService
from tests.h1_support import ROOT
from tests.test_tabletop_hunt8 import PLAYER, fight, send

FALSE_OBSTRUCTION = "TAL_ILLUSION_FALSE_OBSTRUCTION"
QI = "resource:core.qi"

PLAIN = "False Obstruction: Lightly Obscured"
HEAVY = "False Obstruction: Heavily Obscured (1 extra CP, 2 CP in total)"
MUFFLED = "False Obstruction: Muffled (1 extra CP, 2 CP in total)"

# (the words that pick the option out of the menu, the total the printed rules charge)
OPTIONS = [(PLAIN, 1), (HEAVY, 2), (MUFFLED, 2)]


def _menu(tmp_path):
    """The player's own menu, with False Obstruction in it."""
    combat, table, mid = fight(tmp_path, [FALSE_OBSTRUCTION])
    state = table.state(mid)
    for _ in range(6):
        if state["menu"]["actor_id"] == PLAYER:
            break
        state = send(table, mid, state)["state"]
    assert state["menu"]["actor_id"] == PLAYER, state["menu"]["actor_id"]
    return combat, table, mid, state


def _qi(tmp_path, mid):
    """Qi as a second service reads it back off disk, not the one that just played the turn."""
    return CombatService(ROOT, tmp_path)._load_session(mid).engine.state.actors[PLAYER].resources[QI]


def _advertised(label):
    """The total the menu's own label states, or None when it states no surcharge.

    An augmented option prints its whole price in the label ("... (1 extra CP, 2 CP in total)"). The
    plain option prints no price there at all -- it has no surcharge, and its "Cost: 1 CP" is in the
    option's own description -- so None means "the base price, and nothing added on top".
    """
    stated = re.findall(r"(\d+)\s*CP(?:\s+in total)?", label)
    return int(stated[-1]) if stated else None


def _take(table, mid, state, label):
    """Pick one named False Obstruction option and commit it."""
    group = next(g for g in state["menu"]["actions"] if g["label"] == label)
    result = send(table, mid, state, group["options"][0]["candidate_id"])
    while result["status"] == "REACTION_REQUIRED":
        prompt = result["reaction"]
        result = send(table, mid, state, group["options"][0]["candidate_id"],
                      [{**prompt["context"], "selection": "DECLINE"}])
    assert result["status"] == "COMMITTED", result
    return result["state"]


def test_every_option_in_the_menu_prices_itself_honestly(tmp_path):
    """No option may advertise a bare "N CP" while charging the base on top of it.

    Checked over every False Obstruction option the menu offers, so a new option with a surcharge is
    covered too, and against the cost the table's own action row carries.
    """
    _combat, _table, _mid, state = _menu(tmp_path)
    seen = 0
    for group in state["menu"]["actions"]:
        if "False Obstruction" not in group["label"]:
            continue
        seen += 1
        for option in group["options"]:  # every destination for this option
            assert option["label"].startswith(group["label"]), (group["label"], option["label"])
    assert seen == len(OPTIONS), [g["label"] for g in state["menu"]["actions"] if "False Obstruction" in g["label"]]
    for label, charged in OPTIONS:
        advertised = _advertised(label)
        if advertised is None:
            # No surcharge named means the player pays the printed base and nothing on top of it.
            assert charged == 1, f"{label!r} states no price but costs {charged} CP"
        else:
            assert advertised == charged, f"{label!r} states {advertised} CP but costs {charged}"


@pytest.mark.parametrize("label,charged", OPTIONS, ids=["plain", "heavily-obscured", "muffled"])
def test_the_table_charges_exactly_the_price_the_menu_prints(tmp_path, label, charged):
    """Play the option, reload the stored fight, and count the Qi that actually left."""
    combat, table, mid, state = _menu(tmp_path)
    before = _qi(tmp_path, mid)
    _take(table, mid, state, label)
    assert _qi(tmp_path, mid) == before - charged, (
        f"{label!r} advertised {_advertised(label)} CP and cost {before - _qi(tmp_path, mid)}")
    # Charged once, and only for what the menu printed. The base CP and the augmenting CP are two
    # separate spends of 1; a third, or a total of 3, is the augment being charged twice.
    spent = [e for e in combat._load_session(mid).engine.events
             if e.event_type == "RESOURCE_SPENT" and e.actor_id == PLAYER]
    assert sum(int(e.payload["amount"]) for e in spent) == charged, [e.payload for e in spent]
    assert all(int(e.payload["amount"]) == 1 for e in spent), [e.payload for e in spent]


def test_the_plain_option_is_not_made_to_cost_more_than_it_prints(tmp_path):
    """Guard against over-correcting: a label fix must not quietly start charging the augment twice."""
    combat, table, mid, state = _menu(tmp_path)
    before = _qi(tmp_path, mid)
    _take(table, mid, state, PLAIN)
    assert _qi(tmp_path, mid) == before - 1
    assert combat._load_session(mid).mechanical.replay()["status"] == "PASS"

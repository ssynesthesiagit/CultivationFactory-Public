"""Hunt 79 #3 (MMX57): False Obstruction's option must not advertise a price the table does not charge.

H79-I01 seq 148-150 showed one activation, one INTENT_ACCEPTED and two RESOURCE_SPENT of 1 each,
with the option named "False Obstruction: Heavily Obscured (1 CP)". The player read "1 CP" and paid 2.

The charge is right and must stay right. The printed text is:

    Cost: 1 CP                                     <- the ability itself
    Augment 1 CP: The area becomes Heavily Obscured ...   <- one more, on top

so base 1 CP + augment 1 CP = 2 CP in total. The defect was never the arithmetic; it was the
option label telling the player the whole thing cost 1 CP. These tests pin both halves: the label
states the true total, and the table still charges the true total.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from combat.factory_compiler import compile_character
from tests.h1_support import ROOT, sheet

FALSE_OBSTRUCTION = "TAL_ILLUSION_FALSE_OBSTRUCTION"
RULES = ROOT / "authority" / "typed_mechanics" / "rules_text.json"


@pytest.fixture(scope="module")
def options():
    bundle = compile_character(sheet([FALSE_OBSTRUCTION], cl=10), actor_id="actor:factory.illusion")
    return {a["display_name"]: a for a in bundle["action_catalog"] if "False Obstruction" in a.get("display_name", "")}


def test_printed_text_says_one_cp_plus_one_augmenting_cp():
    """The authority: the ability costs 1 CP and the augmenting option costs 1 more."""
    text = json.loads(RULES.read_text())[FALSE_OBSTRUCTION]
    assert "Cost: 1 CP" in text
    assert text.count("Augment 1 CP:") >= 1


def test_heavily_obscured_option_charges_two_cp_in_total(options):
    """Base 1 CP + Augment 1 CP. If this ever reads 1, the printed rules are being broken."""
    action = options["False Obstruction: Heavily Obscured (1 extra CP, 2 CP in total)"]
    assert sum(amount for _resource, amount in action["costs"]) == 2


def test_muffled_option_charges_two_cp_in_total(options):
    action = options["False Obstruction: Muffled (1 extra CP, 2 CP in total)"]
    assert sum(amount for _resource, amount in action["costs"]) == 2


def test_the_plain_option_still_costs_only_the_base_cp(options):
    """The option with no Augment must not be made to look more expensive than it is."""
    action = options["False Obstruction: Lightly Obscured"]
    assert sum(amount for _resource, amount in action["costs"]) == 1


def test_every_option_label_states_the_price_the_table_actually_charges(options):
    """No option may advertise a bare 'N CP' while charging the base on top of it.

    This is the general shape of the bug, and it is checked over every compiled option of the
    ability rather than one hard-coded name, so a new option with a surcharge is covered too.
    """
    for name, action in options.items():
        charged = sum(amount for _resource, amount in action["costs"])
        if "(" not in name:
            continue
        advertised = name.rsplit("(", 1)[1].rstrip(")")
        if "in total" in advertised:
            stated = advertised.split("CP in total")[0].rsplit(",", 1)[-1].strip()
            assert stated == str(charged), f"{name!r} charges {charged} CP"
        else:
            # A bare "N CP" is only honest when the base is not charged on top of it.
            assert charged == int(advertised.split()[0]), f"{name!r} charges {charged} CP"

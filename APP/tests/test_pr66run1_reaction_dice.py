"""PR66RUN1 review Blocking 1: an accepted reaction rolls the action reader's full dice vocabulary.

combat/typed_reactions.py _generic_amount reads a reaction's dice through typed_amounts.effect_dice/dice_terms,
the same reader typed actions use. Before PR66 it read only dice.count/dice.sides (CL-scaled), so a formula
count ("PB d6") rolled nothing and a dice bonus was dropped. One accepted damage-reduction reaction, a real
table commit and a cold reload: the committed hit is smaller by exactly the rolled amount plus the kept bonus.
"""
import pytest

from tests.h1_support import script
from tests.test_tabletop_hunt6 import HOLD, on_hold
from tests.worker2_support import FOE, OWNER, fixture, reload, settle

INCOMING = 30
CASES = {
    # A formula count: PB 3 -> 3d6, plus the dice's own +2.
    "formula_count": ({"dice": {"count_formula": "pb", "sides": 6, "bonus": 2}}, [4, 5, 6], 4 + 5 + 6 + 2),
    # CL 15 selects 2d6 from the CL table; the base dice's +2 is kept across that selection.
    "cl_scaled_keeps_bonus": ({"dice": {"count": 1, "sides": 4, "bonus": 2},
                               "dice_by_cl": [[1, 10, 1, 4], [11, 20, 2, 6]]}, [4, 5], 4 + 5 + 2),
}


def run_hold(monkeypatch, tmp_path, callback, **kwargs):
    """Hold, fire the callback inside the held turn, settle through the real table, then cold-reload (replay PASS)."""
    combat, table, mid = fixture(tmp_path, [], ask=False, **kwargs)
    on_hold(monkeypatch, callback)
    settle(table, mid, next(c.candidate_id for c in combat._load_session(mid).engine.legal_candidates()
                            if c.source_definition_id == HOLD), choices={})
    return reload(tmp_path, mid)


@pytest.mark.parametrize("case", sorted(CASES))
def test_accepted_reaction_reduces_by_its_full_dice_terms_and_reloads(monkeypatch, tmp_path, case):
    from tests.cw2_service_support import seal

    dice, faces, amount = CASES[case]

    def bundles(packets):
        packets[2]["typed_reactions"].append({"feature_id": "test:dice_guard", "block": "generic",
            "name": "Test dice guard", "kind": "damaged",
            "effects": [{"type": "damage_modifier", "applies_to": "self", **dice}],
            "numbers": {"pb": 3, "cl": 15}, "free": False, "costs": [], "range_ft": 60})
        seal(packets[2])

    def hit(e):
        reactor = e.state.actors[FOE]
        script(e, faces)
        e._commit_damage(reactor, INCOMING, "FORCE", "test:damage", OWNER, e._active_intent, reaction_depth=0)

    e = run_hold(monkeypatch, tmp_path, hit, bundle_transform=bundles)  # cold reload, replay PASS
    resolved = [x for x in e.events if x.event_type == "REACTION_RESOLVED" and x.source_definition_id == "test:dice_guard"]
    assert len(resolved) == 1, "the reaction must be accepted once"
    roll = next(r for r in e.rolls if r.reason == "GENERIC_AMOUNT:test:dice_guard")
    assert (list(roll.dice), roll.modifier, roll.total) == (faces, 2, amount)
    committed = next(x for x in e.events if x.event_type == "DAMAGE_COMMITTED" and x.source_definition_id == "test:damage")
    assert committed.payload["hp_damage"] == INCOMING - amount

"""Origin ownership and authored roll contracts through a persisted native table.

The test check/save producers explicitly author their hazard metadata. These
regressions establish the execution contract, not a shipped street/foraging/
prison/object scenario producer; those inventory clauses remain partial.
"""
import pytest

from tests.auto_worker1_support import fight, LEFT, RIGHT, act, reload, resolve, turn
from tests.test_save_reload_equivalence import STOCK_SEEDS

PREFIX = "tianxia.origin_insight."
BACKGROUND = "tianxia.background.abandoned_orphan"


def selection(kind, *, native=False, background=BACKGROUND, inconsistent=False):
    def edit(doc, aid):
        if aid != LEFT or kind is None:
            return
        doc["background_and_origin"] = {
            "background_record_id": background,
            "background": {"background_id": background},
            "origin_record_id": PREFIX + kind,
            "origin_insight": {"origin_insight_id": (
                background + ".origin_insight." + kind if native else PREFIX + kind)},
        }
        if inconsistent:
            doc["background_and_origin"]["origin_insight"]["origin_insight_id"] = PREFIX + "hunger_memory"
    return edit


CHECKS = [
    ("street_hardened", "WIS", "Perception", ["place:market", "ordinary_ambush"]),
    ("hunger_memory", "CON", None, ["hunger"]),
    ("no_one_saves_you", "WIS", "Perception", ["notice", "weak_restraints"]),
    ("quick_hands", "DEX", "Sleight of Hand", ["hide_on_body", "hand_sized_object"]),
]


def check_action(ability, skill, hazards, *, disadvantage=False):
    return {"type": "contest_against", "applies_to": "target", "harmful": True,
            "actor_check": {"kind": "check", "ability": ability, "skill": skill, "hazards": hazards,
                            **({"mode": "DISADVANTAGE"} if disadvantage else {})},
            "target_check": {"kind": "dc", "dc": 15},
            "on_success": [{"type": "temp_hp", "flat": 3, "applies_to": "self"}], "on_fail": []}


def checked(tmp_path, kind, ability, skill, hazards, *, disadvantage=False, **selection_args):
    c, t, m = fight(tmp_path, sheet_edit=selection(kind, **selection_args),
                    prepare=[check_action(ability, skill, hazards, disadvantage=disadvantage)])
    # Cold load the sealed acquisition before the roll, then use its native
    # table candidate; neither ownership nor roll modes are patched at runtime.
    reload(c, m)
    resolve(lambda answers: act(t, m, "Prepare", answers, target_id=RIGHT))
    e = reload(c, m)
    assert c.verify(m)["status"] == "PASS"
    assert c.replay(m)["status"] == "PASS"
    return e, next(roll for roll in e.rolls if roll.reason.startswith("CHECK:"))


@pytest.mark.parametrize("kind,ability,skill,hazards", CHECKS)
@pytest.mark.parametrize("native", [False, True])
def test_canonical_background_check_contract_and_cold_reload(tmp_path, kind, ability, skill, hazards, native):
    e, roll = checked(tmp_path, kind, ability, skill, hazards, native=native)
    assert roll.mode == "ADVANTAGE"
    rows = [r for r in e.typed_passive_rows[LEFT] if r.get("block") == "background_origin"]
    assert len(rows) == 1
    assert rows[0]["feature_id"] == PREFIX + kind
    assert rows[0]["background_id"] == BACKGROUND
    assert len(rows[0]["section_sha256"]) == 64
    assert not any(r.get("block") == "background_origin" for r in e.typed_passive_rows.get(RIGHT, []))


@pytest.mark.parametrize("kind,ability,skill,hazards", CHECKS)
def test_independent_disadvantage_cancels(tmp_path, kind, ability, skill, hazards):
    _, roll = checked(tmp_path, kind, ability, skill, hazards, disadvantage=True)
    assert roll.mode == "NORMAL"


@pytest.mark.parametrize("kind,ability,skill,hazards", CHECKS)
def test_missing_context_is_inert(tmp_path, kind, ability, skill, hazards):
    _, roll = checked(tmp_path, kind, ability, skill, [])
    assert roll.mode == "NORMAL"


@pytest.mark.parametrize("kind,kwargs", [
    (None, {}),
    ("street_hardened", {"background": "tianxia.background.village_child"}),
    ("street_hardened", {"inconsistent": True}),
])
def test_nonowner_wrong_background_or_conflicting_selection(tmp_path, kind, kwargs):
    e, roll = checked(tmp_path, kind, "WIS", "Perception", ["place:market", "ordinary_ambush"], **kwargs)
    assert roll.mode == "NORMAL"
    assert not any(r.get("block") == "background_origin" for r in e.typed_passive_rows.get(LEFT, []))


@pytest.mark.parametrize("ability,skill,hazards", [
    ("WIS", "Perception", ["ordinary_ambush"]),
    ("WIS", "Perception", ["place:market", "supernatural_ambush"]),
    ("INT", "Investigation", ["place:market", "ordinary_ambush"]),
])
def test_street_perception_requires_the_printed_context(tmp_path, ability, skill, hazards):
    _, roll = checked(tmp_path, "street_hardened", ability, skill, hazards)
    assert roll.mode == "NORMAL"


@pytest.mark.parametrize("category,kind,expected", [
    ("hunger", "hunger_memory", "ADVANTAGE"),
    ("thirst", "hunger_memory", "ADVANTAGE"),
    ("exposure", "hunger_memory", "ADVANTAGE"),
    ("forced_march", "hunger_memory", "ADVANTAGE"),
    ("sleep_deprivation", "hunger_memory", "ADVANTAGE"),
    ("ordinary_deprivation", "hunger_memory", "ADVANTAGE"),
    ("poison", "hunger_memory", "NORMAL"),
    ("hunger", None, "NORMAL"),
])
def test_deprivation_save_categories_through_native_table_and_reload(tmp_path, category, kind, expected):
    effect = {"type": "save", "ability": "CON", "save_categories": [category],
              "on_fail": [{"type": "damage", "flat": 1, "damage_types": ["force"], "applies_to": "target"}],
              "on_success": []}
    c, t, m = fight(tmp_path, sheet_edit=selection(kind), cause=[effect])
    reload(c, m)
    turn(t, m, RIGHT)
    resolve(lambda answers: act(t, m, "Cause", answers, target_id=LEFT))
    e = reload(c, m)
    assert next(roll for roll in e.rolls if roll.reason.startswith("SAVE:")).mode == expected
    assert c.verify(m)["status"] == "PASS"
    assert c.replay(m)["status"] == "PASS"


@pytest.mark.parametrize("seed", STOCK_SEEDS)
def test_six_stock_captures_use_lane_scratch(tmp_path, monkeypatch, seed):
    """Run the required stock guard without writing another lane's evidence."""
    from tests import test_a2_glass_stock as stock
    monkeypatch.setattr(stock, "EVIDENCE", tmp_path / "stock-evidence")
    stock.test_six_stock_captures_equal_main(tmp_path, seed)

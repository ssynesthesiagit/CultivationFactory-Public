"""Repeated Armor Ease purchases cross the real sheet/preparation/table boundary."""
from copy import deepcopy

import pytest

from combat.gate5_service import CombatService
from tests.h1_support import ROOT
from tests.test_mgr_t14_fitted_armor import ACTOR, PROJECT, LAMELLAR, fight, support
from tests.test_mgr_t14_armor_consumers import HEAVY
from tests.test_mgr_t14_equipment_review import install
from tests.test_mgr_t14_equipment_fix_round7 import published_training, FIXTURE_INPUTS

PADDED = "tianxia.mortal.armor.padded_battle_robes"
CHECK = "action:test.mgr-t14.repeated-armor-ease-check"
EASE = "tianxia.talent.equipment.armor_ease"


def stealth_checks(bundle):
    """Roll once with only armor, then with an independent check penalty too."""
    if bundle["actor_id"] != ACTOR:
        return
    check = {"type": "contest_against",
             "actor_check": {"kind": "check", "ability": "DEX", "skill": "Stealth"},
             "target_check": {"kind": "dc", "dc": 15}, "applies_to": "target",
             "on_success": [], "on_fail": []}
    support._bundle_action(bundle, CHECK, "Check Stealth before and after a separate penalty", {
        "typed": {"numbers": {}, "duration": {"kind": "instant"}, "riders": [],
                  "effects": [check, {"type": "disadvantage", "applies_to": "self",
                                      "on": "Dexterity (Stealth) checks"}, deepcopy(check)]}},
        target_kind="HOSTILE_ENTITY", range_ft=60)
    support._seal(bundle)


@pytest.mark.parametrize("route", ["training", "advancement"])
@pytest.mark.parametrize("armor_item, category", [(PADDED, "light"), (LAMELLAR, "medium"), (HEAVY, "heavy")])
def test_two_published_purchases_keep_both_choices_and_only_armor_penalty_exemptions(
        tmp_path, route, armor_item, category):
    doc = published_training(tmp_path, 3, route, ease_count=2, armor_item=armor_item)
    block = doc["spheres_and_talents"]
    assert block["learned_talent_record_ids"].count(EASE) == 1
    # The repeated rows come from the producer, never duplicate display IDs.
    history = (block["trained_choices"] if route == "training" else
               doc["advancement_history"]["canonical_allocations"])
    assert sum(row.get("record_id") == EASE for row in history) == 2
    install(tmp_path, doc)

    def menu():
        return CombatService(ROOT, tmp_path).character_preparation_options(PROJECT)

    def offered(current):
        return {c["parameters"]["category"] for c in current["commands"]
                if c["operation"] == "armor.ease.choose"}

    def choose(category):
        current = menu()
        option = next(c for c in current["commands"] if c["operation"] == "armor.ease.choose"
                      and c["parameters"]["category"] == category)
        return CombatService(ROOT, tmp_path).character_preparation(PROJECT, option["operation"],
            parameters=option["parameters"], expected_revision=current["state"]["revision"])

    assert offered(menu()) == {"light", "medium", "heavy"}
    choose("light")
    assert offered(menu()) == {"medium", "heavy"}  # F7 hid this purchased second choice.
    choose("medium")
    current = menu()
    assert current["state"]["armor"]["ease_categories"] == ["light", "medium"]
    assert offered(current) == set()  # Mirrored cards/history must not grant a third purchase.
    for denied in ("light", "heavy"):
        with pytest.raises(ValueError, match="different category"):
            CombatService(ROOT, tmp_path).character_preparation(PROJECT, "armor.ease.choose",
                parameters={"category": denied}, expected_revision=current["state"]["revision"])

    combat, table, mid = fight(tmp_path, doc, prepare=stealth_checks)
    cold = support._reload(tmp_path, mid)
    bundle = next(b for b in cold.typed_bundle_documents if b["actor_id"] == ACTOR)
    assert bundle["armor_subject"]["armor_ease_count"] == 2
    assert bundle["armor_subject"]["ease_categories"] == ["light", "medium"]
    worn = next(i for i in bundle["carrying"]["items"] if i.get("worn") and i.get("armor_category"))
    assert worn["armor_category"] == category and worn["armor_stealth"] == 1
    support._commit(combat, table, mid, CHECK, actor=ACTOR)
    reloaded = support._reload(tmp_path, mid)
    rolls = [r for r in reloaded.rolls if r.reason == f"CHECK:{CHECK}"]
    assert [r.mode for r in rolls] == ["DISADVANTAGE" if category == "heavy" else "NORMAL", "DISADVANTAGE"]
    assert [len(r.dice) for r in rolls] == [2 if category == "heavy" else 1, 2]
    subject = next(b for b in reloaded.typed_bundle_documents if b["actor_id"] == ACTOR)["armor_subject"]
    assert subject["ease_categories"] == ["light", "medium"]

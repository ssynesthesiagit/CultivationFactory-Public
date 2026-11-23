"""Reviewed campaign Insight acquisitions, using public CAT3 and sealed synthetic sheets.

These regressions exercise the table service and durable growth record, not
just the prerequisite helper. No private data, history, browsers or model calls.
"""
import pytest

from combat.tabletop import TabletopError
from tests.test_grow2_campaign import (
    PID, digest, install, service, sheet, synthetic_art_authority,
)

COMPANION = "insight.burden-bearing-companion"
BOND = "insight.legacy-beast-tamers-bond"
ELEMENTAL = "insight.elemental-mastery"


def owner(cl=8, *spheres):
    result = sheet(cl=cl)
    result["spheres_and_talents"]["sphere_record_ids"] = list(spheres)
    return result


def test_mixed_typed_and_story_prerequisites_need_recorded_gm_confirmation(tmp_path):
    package = install(tmp_path, source=owner(8, "tianxia.sphere.earth"))
    sealed_hash = digest(package)
    s = service(tmp_path)
    option = next(row for row in s.advancement(PID)["insights"] if row["id"] == COMPANION)
    assert not option["legal"] and option["gm"]
    assert any("companion" in reason.lower() for reason in option["reasons"])
    with pytest.raises(TabletopError, match="GM confirmation.*companion"):
        s.add_insight(PID, COMPANION, note="A mountain quest")
    assert not s.buttons.get(PID).get("advancement")

    s.add_insight(PID, COMPANION, note="A mountain quest", gm=True)
    cold = service(tmp_path)
    saved = cold.buttons.get(PID)["advancement"]["insights"]
    assert len(saved) == 1 and saved[0]["gm"] is True
    assert saved[0]["id"] == COMPANION
    projected = cold.combat._factory_owner_sheet(PID)
    assert projected["spheres_and_talents"]["cultivation_insight_record_ids"] == [COMPANION]
    assert digest(package) == sealed_hash


@pytest.mark.parametrize("cl,spheres,reason", [
    (7, ["tianxia.sphere.earth"], "level 8"),
    (8, [], "(?i)earth"),
])
def test_gm_story_confirmation_does_not_waive_typed_prerequisites(tmp_path, cl, spheres, reason):
    install(tmp_path, source=owner(cl, *spheres))
    s = service(tmp_path)
    with pytest.raises(TabletopError, match=reason):
        s.add_insight(PID, COMPANION, note="From play", gm=True)
    assert not s.buttons.get(PID).get("advancement")


def test_companion_bond_allows_the_same_pair_on_repeated_acquisitions(tmp_path):
    package = install(tmp_path, source=owner(8, "tianxia.sphere.beastmastery"))
    sealed_hash = digest(package)
    s = service(tmp_path)
    s.add_insight(PID, BOND, note="First companion lesson", choice="Strength/Wisdom", gm=True)
    # The second selection still needs its printed eligibility confirmed.
    cold = service(tmp_path)
    with pytest.raises(TabletopError, match="GM confirmation"):
        cold.add_insight(PID, BOND, note="Second companion lesson", choice="Strength/Wisdom")
    cold.add_insight(PID, BOND, note="Second companion lesson", choice="Strength/Wisdom", gm=True)
    reloaded = service(tmp_path)
    saved = reloaded.buttons.get(PID)["advancement"]["insights"]
    assert [row["choice"] for row in saved] == ["Strength/Wisdom", "Strength/Wisdom"]
    assert all(row["gm"] for row in saved)
    occurrences = reloaded.combat._factory_owner_sheet(PID)["spheres_and_talents"]["cultivation_insight_occurrences"]
    assert [row["insight_id"] for row in occurrences] == [BOND, BOND]
    assert [row["choice"] for row in occurrences] == ["Strength/Wisdom", "Strength/Wisdom"]
    assert all(not row["ability_change_applied"] for row in occurrences)
    assert digest(package) == sealed_hash


def test_elemental_mastery_still_requires_a_different_type_even_with_gm_confirmation(tmp_path):
    install(tmp_path, source=owner())
    s = service(tmp_path)
    s.add_insight(PID, ELEMENTAL, note="Fire training", choice="Fire", gm=True)
    cold = service(tmp_path)
    with pytest.raises(TabletopError, match="different option"):
        cold.add_insight(PID, ELEMENTAL, note="More fire training", choice=" fire ", gm=True)
    assert len(cold.buttons.get(PID)["advancement"]["insights"]) == 1
    cold.add_insight(PID, ELEMENTAL, note="Cold training", choice="Cold", gm=True)
    assert [row["choice"] for row in service(tmp_path).buttons.get(PID)["advancement"]["insights"]] == ["Fire", "Cold"]


def test_repeated_companion_bond_still_requires_an_explicit_pair(tmp_path):
    install(tmp_path, source=owner(8, "tianxia.sphere.beastmastery"))
    s = service(tmp_path)
    with pytest.raises(TabletopError, match="Record the choice"):
        s.add_insight(PID, BOND, note="Companion training", gm=True)
    assert not s.buttons.get(PID).get("advancement")

"""BLOODAFF1: the Bloodline lineage and affinity are one build pick recorded on the sheet.

The pick is offered when Ancestral Bloodline Awakening is gained (CL3), a level with no pick is refused,
a recorded pick sets the single affinity condition with no combat action, a character that gained the
feature before the pick is pending until answered, and an affinity the lineage does not allow is refused.
"""
import pytest

from app.core import FoundryError
from character_creation.feature_choices import contracts, resolve
from combat.ext import ancestral_bloodline as bloodline
from combat.table_levelup import pending_feature_choices
from tests.test_grow3_levelup import PID, QI, baseline, choices, service

FEATURE = bloodline.BLOODLINE
OPTIONS = contracts()[FEATURE]["options"]


def _option(lineage, affinity):
    return next(o["id"] for o in OPTIONS
                if o["grants"] == {"bloodline_lineage": lineage, "bloodline_affinity": affinity})


def _bloodline_sheet(recorded=None):
    """A Qi Cultivator who owns Ancestral Bloodline Awakening, with or without a recorded pick."""
    sheet = baseline(QI)
    sheet["path_and_subpath"]["path_feature_record_ids"] = list(
        sheet["path_and_subpath"]["path_feature_record_ids"]) + [FEATURE]
    if recorded is not None:
        sheet["path_and_subpath"]["feature_build_choices"] = {FEATURE: dict(recorded)}
    return sheet


def _pending_ids(svc):
    return [row["feature_id"] for row in svc.advancement(PID)["level_up"]["pending_feature_choices"]]


def test_granting_level_offers_the_pick_and_an_unanswered_level_is_refused(tmp_path):
    # (a) The CL3 grant shows the lineage-and-affinity pick; a level-up without it is refused.
    svc = service(tmp_path, QI)
    svc.level_up(PID, choices(svc.advancement(PID)))
    view = svc.advancement(PID)
    assert view["level_up"]["cl"] == 3
    subpath = next(r for r in view["level_up"]["subpaths"] if r["path_id"] == QI)
    offered = [b for b in subpath["build_choices"] if b["feature_id"] == FEATURE]
    assert offered and [o["id"] for o in offered[0]["options"]] == [o["id"] for o in OPTIONS]
    unanswered = choices(view)
    unanswered["feature_choices"] = {}
    with pytest.raises(FoundryError):
        svc.level_up(PID, unanswered)


def test_a_recorded_pick_leaves_no_combat_rows_and_sets_that_affinity(tmp_path):
    # (b) One pick sets the affinity condition; no "Bloodline affinity: X" combat rows exist.
    sheet = _bloodline_sheet({"bloodline_lineage": "vermilion_phoenix", "bloodline_affinity": "radiant",
                              "choice": _option("vermilion_phoenix", "radiant")})
    compiled = bloodline_bundle(sheet)
    rows = [r for r in compiled["action_catalog"] if ".bloodline_affinity." in r["source_definition_id"]]
    assert rows == []
    passive = next(r for r in compiled["passive_rows"] if r.get("kind") == "bloodline_strike")
    assert passive["lineage"] == "vermilion_phoenix"
    assert passive["affinity"] == "radiant"


def test_a_character_gained_before_the_pick_is_pending_then_records_and_reloads(tmp_path):
    # (c) Owned with no pick yet: the feature is pending; the recorded pick survives a cold reload.
    svc = service_with_sheet(tmp_path, _bloodline_sheet())
    assert FEATURE in _pending_ids(svc)
    option = _option("azure_dragon", "fire")
    svc.set_feature_picks(PID, {FEATURE: option})
    assert FEATURE not in _pending_ids(svc)
    reloaded = service_with_sheet(tmp_path, _bloodline_sheet(), reload=True).combat._factory_owner_sheet(PID)
    recorded = reloaded["path_and_subpath"]["feature_build_choices"][FEATURE]
    assert recorded["choice"] == option
    assert recorded["bloodline_lineage"] == "azure_dragon"
    assert recorded["bloodline_affinity"] == "fire"


def test_a_lineage_cannot_record_an_affinity_it_does_not_allow():
    # (d) A pick outside the lineage's permitted affinities is not an offered option, so it is refused.
    sheet = _bloodline_sheet()
    with pytest.raises(FoundryError):
        resolve([{"canonical_id": FEATURE, "display_name": "Ancestral Bloodline Awakening"}],
                {FEATURE: "vermilion_phoenix_cold"}, required=False)
    assert not bloodline.compatible("vermilion_phoenix", "cold")
    assert sheet["path_and_subpath"].get("feature_build_choices") is None


def service_with_sheet(root, sheet, reload=False):
    """A TabletopService whose character archive holds this sheet; reload rebuilds it cold from disk."""
    import json
    import zipfile
    archive = root / "portable_characters" / PID / "current.zip"
    if not reload:
        archive.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive, "w") as z:
            z.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(sheet))
    return service(root, QI)


def bloodline_bundle(sheet):
    from combat.factory_compiler import compile_character
    from tests.worker2_support import OWNER
    return compile_character(sheet, actor_id=OWNER)

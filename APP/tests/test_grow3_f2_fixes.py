"""GROW3 fix round F2: planner prerequisite membership and the First Molt acquisition choice.

Synthetic installs and public authority only; no models, no owner data.
"""
from copy import deepcopy

import pytest

from app.core import FoundryError
from combat import table_advance as ta
from tests.test_grow3_levelup import service, choices, baseline, PID, BODY, TALENTS
from tests.test_grow3_review_fixes import install
from tests.test_grow3_review_fixes import INSIGHT

IRON = "tianxia.subpath.body.iron_shirt"
SERAPHIC = "tianxia.tradition.spirit.seraphic_molter"
FIRST_MOLT = SERAPHIC + ".feature.first_molt"
SPIRIT_PATH = "tianxia.path.spirit_awakening"


def _payload(view, prefer, talent_index=1):
    # Like the harness choices(), but may pick a GM-confirmed Subpath (the Seraphic Tradition needs the GM's confirmation).
    level = view["level_up"]
    subs, feats = {}, {}
    for group in level["subpaths"]:
        pid = group["path_id"]
        row = next((r for r in group["options"] if r["id"] == prefer.get(pid)), None) or next(r for r in group["options"] if r["legal"])
        subs[pid] = row["id"]
        for prog in level["subpath_progressions"].get(row["id"], []):
            if prog["cl"] == level["cl"]:
                for b in prog["build_choices"]:
                    feats[b["feature_id"]] = b["options"][0]["id"]
    return {"cl": level["cl"], "talent_ids": [TALENTS[talent_index]["canonical_talent_id"]], "subpaths": subs,
            "access_confirmed": True, "feature_choices": feats}


def test_owned_subpath_is_in_the_loaded_planner_known_set(tmp_path):
    # Finding 1: an existing Subpath must reach the planner's known set on load, not only one picked in this draft.
    sheet = baseline(BODY)
    sheet["path_and_subpath"]["subpath_record_ids"] = [IRON]
    install(tmp_path, sheet)
    s = service(tmp_path, BODY)
    record = deepcopy(INSIGHT)
    record["prerequisites"] = [{"kind": "subpath_or_tradition", "target_id": IRON}]
    s._insights_cache = [record]
    info = s.advancement(PID)["level_up"]
    assert IRON in info["known"]["subpaths"]


def test_owned_insight_is_in_the_loaded_planner_known_set(tmp_path):
    sheet = baseline(BODY)
    sheet["spheres_and_talents"]["cultivation_insight_record_ids"] = ["synthetic.owned"]
    install(tmp_path, sheet)
    s = service(tmp_path, BODY)
    info = s.advancement(PID)["level_up"]
    assert "synthetic.owned" in info["known"]["insights"]


def test_first_molt_asks_for_the_minor_sign_and_persists_it(tmp_path):
    # Finding 2: First Molt says "Choose one Minor Seraphic Sign when you gain this feature."
    s = service(tmp_path, SPIRIT_PATH)
    s.level_up(PID, choices(s.advancement(PID)))
    view = s.advancement(PID)
    rows = view["level_up"]["subpath_progressions"][SERAPHIC]
    cl3 = next(r for r in rows if r["cl"] == 3)
    assert FIRST_MOLT in {f["id"] for f in cl3["features"]}
    assert {b["feature_id"] for b in cl3["build_choices"]} == {FIRST_MOLT}
    payload = _payload(view, {SPIRIT_PATH: SERAPHIC})
    payload["feature_choices"] = {k: v for k, v in payload["feature_choices"].items() if k != FIRST_MOLT}
    with pytest.raises(FoundryError, match="required build"):
        s.level_up(PID, payload)
    payload["feature_choices"] = {FIRST_MOLT: "not-a-sign"}
    with pytest.raises(FoundryError, match="offered option"):
        s.level_up(PID, payload)
    payload["feature_choices"] = {FIRST_MOLT: "glass-eye"}
    s.level_up(PID, payload)
    cold = service(tmp_path, SPIRIT_PATH)
    sheet = cold.combat._factory_owner_sheet(PID)
    assert sheet["path_and_subpath"]["feature_build_choices"][FIRST_MOLT] == {
        "choice": "glass-eye", "minor_sign": "Glass-Eye Sign"}


def test_acquired_minor_sign_is_the_combat_default_until_changed():
    from combat.ext import seraphic_molter as sm

    def menu_default(sheet):
        info = {"owned_ids": (sm.FIRST,), "short": "t", "actor_id": "a", "numbers": {}, "mechanics": {}, "owner_sheet": sheet}
        rows = [a.parameters["menu_row"] for a in sm.seraphic_buttons(info) if (a.parameters or {}).get("menu_row")]
        return rows[0]["default"]

    acquired = {"path_and_subpath": {"feature_build_choices": {FIRST_MOLT: {"choice": "glass-eye", "minor_sign": "Glass-Eye Sign"}}}}
    assert menu_default(acquired) == ["Glass-Eye Sign"]
    assert menu_default({}) == ["Feather-Scar Sign"]

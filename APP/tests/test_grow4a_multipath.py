"""GROW4A: a second Path is added at the current cultivation level, with a recorded access source."""
import hashlib
from copy import deepcopy
from pathlib import Path

import pytest

from app.core import FoundryError
from combat import table_advance as ta
from combat import table_levelup as lu
from stage2.ability_changes import published_path_records
from tests.test_grow3_levelup import BODY, PID, QI, SCORES, TALENTS, baseline, choices, service

SPIRIT = "tianxia.path.spirit_awakening"
PHB = "PHB Chapter 3"


def _feature_pick(view, sub_id):
    """Build choices for one Subpath, taken only from that Subpath's own build_choices."""
    group = next(g for g in view["level_up"]["subpaths"] if any(r["id"] == sub_id for r in g["options"]))
    row = next(r for r in group["options"] if r["id"] == sub_id)
    return {b["feature_id"]: b["options"][0]["id"] for b in row.get("build_choices") or []}


def _add_payload(view, path_id, access="phb", source=PHB, index=3, confirmed=False):
    base = choices(view, index)
    tmpl = view["level_up"]["add_templates"][path_id]
    sub = next(r for g in tmpl["subpaths"] for r in g["options"] if not r["requires_confirmation"])
    feature_choices = {b["feature_id"]: b["options"][0]["id"] for b in sub.get("build_choices") or []}
    feature_choices.update({b["feature_id"]: b["options"][0]["id"] for b in tmpl.get("feature_choices") or []})
    payload = {**base, "subpaths": {**base["subpaths"], path_id: sub["id"]},
               "feature_choices": {**base["feature_choices"], **feature_choices},
               "add_path_id": path_id, "add_access": access, "add_source_id": source, "access_confirmed": confirmed}
    if view["level_up"]["advancement_choice"]:
        payload.update(advancement="ability", changes={"CON": 2})
    return payload


def _reach(s, cl):
    """Commit levels until the next level to plan is cl (talent i per committed level)."""
    for i in range(cl - 2):
        view = s.advancement(PID)
        assert view["level_up"]["cl"] == i + 2
        payload = choices(view, i)
        if view["level_up"]["advancement_choice"]:
            payload.update(advancement="ability", changes={"CON": 2})
        s.level_up(PID, payload)


def _sheet(root, path=BODY):
    return service(root, path).combat._factory_owner_sheet(PID)


def test_add_qi_at_cl5_grants_both_paths_and_asks_qi_choices(tmp_path):
    s = service(tmp_path, BODY)
    _reach(s, 5)
    view = s.advancement(PID)
    assert view["level_up"]["cl"] == 5
    assert QI in [c["id"] for c in view["level_up"]["add_candidates"]]
    assert view["level_up"]["add_templates"][QI]["subpaths"]
    s.level_up(PID, _add_payload(view, QI))
    cold = _sheet(tmp_path)
    assert cold["identity"]["cultivation_level"] == 5
    assert sorted(cold["identity"]["path_ids"]) == sorted([BODY, QI])
    assert cold["identity"]["path_levels"] == {BODY: 5, QI: 5}
    entries = cold["path_and_subpath"]["path_progression_entries_by_cl"]
    assert entries["5"] == [BODY, QI]
    qi_auth = published_path_records()[QI]["compatibility"]["factory"]["stage2_authority"]
    for feature in qi_auth["progression_by_cl"]["1"]["feature_record_ids"]:
        assert feature in cold["path_and_subpath"]["path_feature_record_ids"]
    # One CL: the add gives no extra level talent, ASI, or Insight beyond CL5's own.
    assert len([r for r in cold["spheres_and_talents"]["learned_talent_record_ids"]]) == 4


def test_later_level_up_advances_both_paths(tmp_path):
    s = service(tmp_path, BODY)
    _reach(s, 5)
    s.level_up(PID, _add_payload(s.advancement(PID), QI))
    view = service(tmp_path, BODY).advancement(PID)
    assert view["level_up"]["cl"] == 6
    s2 = service(tmp_path, BODY)
    s2.level_up(PID, choices(view, 5))
    cold = _sheet(tmp_path)
    assert cold["identity"]["cultivation_level"] == 6
    assert cold["identity"]["path_levels"] == {BODY: 6, QI: 6}
    assert cold["path_and_subpath"]["path_progression_entries_by_cl"]["6"] == [BODY, QI]


def test_duplicate_universal_feature_is_granted_once_with_note(tmp_path):
    s = service(tmp_path, BODY)
    _reach(s, 4)
    view = s.advancement(PID)
    assert view["level_up"]["cl"] == 4
    s.level_up(PID, _add_payload(view, QI, index=3))
    cold = _sheet(tmp_path)
    granted = cold["path_and_subpath"]["path_feature_record_ids"]
    asi = "tianxia.path.qi_cultivation.feature.ability_score_improvement_or_cultivation_insight"
    body_asi = "tianxia.path.body_refining.feature.ability_score_improvement_or_cultivation_insight"
    assert sum(1 for f in granted if f.endswith("ability_score_improvement_or_cultivation_insight")) == 1
    assert (asi in granted) or (body_asi in granted)
    assert any("granted once" in note for note in cold["path_and_subpath"]["duplicate_feature_notes"])


def test_primary_method_grant_must_match_recorded_method(tmp_path):
    s = service(tmp_path, BODY)
    _reach(s, 5)
    view = s.advancement(PID)
    sheet = s.combat._factory_owner_sheet(PID)
    saved = s.buttons.get(PID).get("advancement") or {}
    bad = _add_payload(view, QI, access="primary_method", source="some-other-method")
    with pytest.raises(FoundryError, match="Primary Method grant"):
        lu.prepare(sheet, saved, bad, TALENTS, [], primary_method_id=BODY)
    good = _add_payload(view, QI, access="primary_method", source=BODY)
    lu.prepare(sheet, saved, good, TALENTS, [], primary_method_id=BODY)


def test_primary_method_access_commits_with_the_method_the_level_view_names(tmp_path):
    # Regression (GROW4F3R): the level view exposed no display name or id, so the player had to type the internal
    # Method id to use a Primary Method grant. The view now names the recorded Method and carries the id to send.
    s = service(tmp_path, BODY)
    _reach(s, 5)
    view = s.advancement(PID, primary_method_id="METHOD-002")
    recorded = view["level_up"]["primary_method"]
    assert recorded == {"id": "METHOD-002", "name": "Ash-Breath Furnace Method"}
    payload = _add_payload(view, QI, access="primary_method", source=recorded["id"])
    s.level_up(PID, payload, primary_method_id=recorded["id"])
    cold = _sheet(tmp_path)
    assert sorted(cold["identity"]["path_ids"]) == sorted([BODY, QI])
    assert cold["path_and_subpath"]["path_progression_entries_by_cl"]["5"] == [BODY, QI]
    assert cold["identity"]["path_levels"] == {BODY: 5, QI: 5}


def test_committed_primary_method_grant_reloads_and_advances(tmp_path):
    # Regression: replay (apply/advance_sheet) passed no primary_method_id, so a committed grant was rejected on reload.
    s = service(tmp_path, BODY)
    _reach(s, 5)
    s.level_up(PID, _add_payload(s.advancement(PID), QI, access="primary_method", source=BODY), primary_method_id=BODY)
    cold = _sheet(tmp_path)
    assert sorted(cold["identity"]["path_ids"]) == sorted([BODY, QI])
    assert cold["path_and_subpath"]["path_progression_entries_by_cl"]["5"] == [BODY, QI]
    reloaded = service(tmp_path, BODY)
    view = reloaded.advancement(PID)
    assert view["level_up"]["cl"] == 6
    reloaded.level_up(PID, choices(view, 5))
    later = _sheet(tmp_path)
    assert later["identity"]["cultivation_level"] == 6
    assert later["identity"]["path_levels"] == {BODY: 6, QI: 6}


def test_add_requires_access_source_and_gm_confirmation(tmp_path):
    s = service(tmp_path, BODY)
    _reach(s, 5)
    view = s.advancement(PID)
    no_source = _add_payload(view, QI, source="")
    with pytest.raises(FoundryError, match="Name the access source"):
        s.level_up(PID, no_source)
    unconfirmed = _add_payload(view, QI, access="gm", source="GM ruling")
    with pytest.raises(FoundryError, match="confirm the GM override"):
        s.level_up(PID, unconfirmed)
    assert _sheet(tmp_path)["identity"]["path_ids"] == [BODY]


def test_primary_method_preserved_through_undo_level(tmp_path):
    # Regression (GROW4F4R): undo_level dropped the recorded Primary Method from the level view. The service only
    # shows the Method it is handed, so every call in the sequence must carry the recorded id (the API always does).
    s = service(tmp_path, BODY)
    _reach(s, 5)
    view = s.advancement(PID, primary_method_id="METHOD-002")
    recorded = view["level_up"]["primary_method"]
    assert recorded == {"id": "METHOD-002", "name": "Ash-Breath Furnace Method"}
    after_undo = s.undo_level(PID, primary_method_id="METHOD-002")
    assert after_undo["cl"] == 3  # undo removes the last committed level (CL 4); CL 3 is now committed
    assert after_undo["level_up"]["primary_method"] == recorded
    assert s.advancement(PID, primary_method_id="METHOD-002")["level_up"]["primary_method"] == recorded


def test_primary_method_preserved_through_add_ability(tmp_path):
    # Regression (GROW4F4R): add_ability dropped the recorded Primary Method from the level view.
    # A GM respec (gm=True) is used so the test does not depend on which CL's ability increase is still open.
    s = service(tmp_path, BODY)
    _reach(s, 4)
    view = s.advancement(PID, primary_method_id="METHOD-002")
    recorded = view["level_up"]["primary_method"]
    assert recorded == {"id": "METHOD-002", "name": "Ash-Breath Furnace Method"}
    after_ability = s.add_ability(PID, {"reason": "gm_respec", "cl": 3, "changes": dict(SCORES)}, gm=True,
                                  primary_method_id="METHOD-002")
    assert after_ability["level_up"]["primary_method"] == recorded
    assert s.advancement(PID, primary_method_id="METHOD-002")["level_up"]["primary_method"] == recorded


def test_add_is_atomic_on_invalid_subpath(tmp_path):
    s = service(tmp_path, BODY)
    _reach(s, 5)
    view = s.advancement(PID)
    before = s.buttons.get(PID).get("advancement")
    payload = _add_payload(view, QI)
    payload["subpaths"][QI] = "tianxia.subpath.body.flesh_crucible"
    with pytest.raises(FoundryError):
        s.level_up(PID, payload)
    assert s.buttons.get(PID).get("advancement") == before
    assert _sheet(tmp_path)["identity"]["path_ids"] == [BODY]

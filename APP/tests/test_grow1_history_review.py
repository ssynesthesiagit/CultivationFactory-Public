"""Chronological Grow-history regressions; synthetic installs and offline IO only."""
from copy import deepcopy
import hashlib

import pytest

from app.core import FoundryError
from combat import table_advance as ta
from combat.tabletop import TabletopError
from tests.test_grow1_abilities import PID, ROOT, growth_service, installed_sheet
from tests.test_grow1_respec_review import history, seal, selection
from tests.test_grow1_f10_review import RESET, sealed_con_character


def increase(cl, **changes):
    return {"reason": "level_increase", "cl": cl, "changes": changes}


def test_add_reset_remove_reload_sequence_checks_the_whole_history(tmp_path):
    package = sealed_con_character(tmp_path)  # CL8, sealed CL4 +2 CON, current CON19.
    base = growth_service(tmp_path).combat._factory_owner_sheet(PID, apply_table=False)
    # operation, entry/index, expected rejection, final CON, row count
    steps = [
        ("add", RESET, None, 12, 1),
        ("add", increase(8, CON=2), None, 14, 2),
        ("reload", None, None, 14, 2),
        ("level", 12, None, 14, 2),
        ("add", {**RESET, "cl": 12}, None, 14, 3),
        ("remove", "0", "cap", 14, 3),  # later reset cannot excuse illegal CL8
        ("add", increase(12, WIS=1), "budget", 14, 3),
        ("grant", increase(12, CON=9), None, 23, 4),
        ("reload", None, None, 23, 4),
        ("remove", "3", None, 14, 3),
        ("add", increase(12, WIS=2), None, 14, 4),
        ("remove", "3", None, 14, 3),
        ("remove", "2", None, 14, 2),
        ("remove", "1", None, 12, 1),
        ("remove", "0", None, 19, 0),
    ]
    for operation, value, rejection, con, count in steps:
        service = growth_service(tmp_path)
        before = deepcopy(service.buttons.get(PID).get("advancement"))
        if operation == "level":
            base["identity"]["cultivation_level"] = value
            package = seal(tmp_path, base)
        digest = hashlib.sha256(package.read_bytes()).hexdigest()

        def act():
            if operation in {"add", "grant"}:
                return service.add_ability(PID, value, gm=operation == "grant")
            if operation == "remove":
                return service.remove_advancement(PID, "ability", value)
            return growth_service(tmp_path).advancement(PID)

        if rejection:
            with pytest.raises(TabletopError, match=rejection):
                act()
            assert growth_service(tmp_path).buttons.get(PID).get("advancement") == before
        else:
            act()
        cold = growth_service(tmp_path)
        saved = cold.buttons.get(PID).get("advancement")
        verdict = ta.validate_ability_history(base, saved)
        assert verdict["legal"], (operation, value, verdict)
        assert len(verdict["entries"]) == count
        assert verdict["scores"]["CON"] == con
        assert ta.current_scores(cold.combat._factory_owner_sheet(PID))["CON"] == con
        assert cold.advancement(PID)["added"]["abilities"] == verdict["entries"]
        assert all(row["status"]["legal"] for row in verdict["entries"] if not row["gm"])
        assert hashlib.sha256(package.read_bytes()).hexdigest() == digest


def test_cross_level_status_is_historical_but_new_acquisitions_are_current(tmp_path):
    service = growth_service(tmp_path)
    service.add_ability(PID, increase(4, CON=2))
    base = installed_sheet()
    base["identity"]["cultivation_level"] = 8
    seal(tmp_path, base)
    cold = growth_service(tmp_path)
    assert cold.advancement(PID)["added"]["abilities"][0]["status"]["legal"]
    with pytest.raises(TabletopError, match="currently CL 8"):
        cold.add_ability(PID, increase(4, WIS=2))
    cold.add_ability(PID, increase(8, WIS=2))
    assert all(row["status"]["legal"] for row in growth_service(tmp_path).advancement(PID)["added"]["abilities"])


@pytest.mark.parametrize("early_duplicate", [False, True])
def test_history_merges_sealed_bonuses_at_their_cl_not_before(tmp_path, early_duplicate):
    base = installed_sheet()
    old = ta.current_scores(base)
    base = ta.recompute_from_abilities(base, old, {**old, "CON": 17})
    package = seal(tmp_path, base)
    growth_service(tmp_path).add_ability(PID, increase(4, CON=2))  # CON19, legal at CL4
    base["identity"]["cultivation_level"] = 6
    seal(tmp_path, base)
    growth_service(tmp_path).add_ability(PID, {**RESET, "cl": 6})  # CON10
    # A later sealed +2 is included in the installed scores, not in the earlier
    # CL4 allocation. The CL6 reset and all final views retain both earned +2s.
    base = ta.recompute_from_abilities(base, ta.current_scores(base), {**ta.current_scores(base), "CON": 19})
    base["identity"]["cultivation_level"] = 8
    selected = selection("sealed-cl8", "ability_score_change", deltas={"CON": 2})
    base["advancement_history"] = history([(8, selected)])
    if early_duplicate:
        base["advancement_history"] = {
            "typed_choice_snapshot": [deepcopy(selected)], **base["advancement_history"]}
    package = seal(tmp_path, base)
    digest = hashlib.sha256(package.read_bytes()).hexdigest()
    cold = growth_service(tmp_path)
    rows = cold.advancement(PID)["added"]["abilities"]
    assert all(row["status"]["legal"] for row in rows)
    assert ta.current_scores(cold.combat._factory_owner_sheet(PID))["CON"] == 12
    assert hashlib.sha256(package.read_bytes()).hexdigest() == digest


def test_storage_order_cannot_hide_an_illegal_earlier_allocation(tmp_path):
    base = installed_sheet()
    base["identity"]["cultivation_level"] = 8
    old = ta.current_scores(base)
    base = ta.recompute_from_abilities(base, old, {**old, "CON": 19})
    seal(tmp_path, base)
    # Stored backwards: a later reset must not legalize the earlier over-cap ASI.
    doc = {"abilities": [{**RESET, "cl": 8}, increase(4, CON=2)]}
    verdict = ta.validate_ability_history(base, doc)
    assert not verdict["legal"]
    assert not verdict["entries"][1]["status"]["legal"]
    assert "cap" in "; ".join(verdict["entries"][1]["status"]["reasons"])
    with pytest.raises(FoundryError, match="cap"):
        ta.apply(base, doc)


def test_valid_replay_uses_cl_order_for_multiple_resets_without_mutating_storage(tmp_path):
    base = installed_sheet()
    base["identity"]["cultivation_level"] = 12
    seal(tmp_path, base)
    low = {**RESET, "cl": 4}
    high = {"reason": "gm_respec", "cl": 8, "changes": ta.default_spread("CON")}
    saved = ta.normalized({"abilities": [high, low]})
    original = deepcopy(saved)
    service = growth_service(tmp_path)
    service.buttons.save_advancement(PID, saved)
    assert ta.current_scores(growth_service(tmp_path).combat._factory_owner_sheet(PID))["CON"] == 15
    assert all(row["status"]["legal"] for row in growth_service(tmp_path).advancement(PID)["added"]["abilities"])
    assert service.buttons.get(PID)["advancement"] == original


def test_later_sealed_cap_conflict_is_not_erased_by_a_still_later_reset():
    base = installed_sheet()
    base["identity"]["cultivation_level"] = 12
    base["advancement_history"] = history([
        (8, selection("sealed-cl8", "ability_score_change", deltas={"CON": 2})),
    ])
    scores = ta.current_scores(base)
    base = ta.recompute_from_abilities(base, scores, {**scores, "CON": 19})
    doc = {"abilities": [increase(4, CON=2), {**RESET, "cl": 12}]}
    with pytest.raises(FoundryError, match="later recorded ability increase.*cap"):
        ta.apply(base, doc)
    verdict = ta.validate_ability_history(base, doc)
    assert not verdict["entries"][0]["status"]["legal"]
    # Explicit GM authority belongs to that entry only and survives replay.
    doc["abilities"][0]["gm"] = True
    assert ta.validate_ability_history(base, doc)["legal"]
    assert ta.current_scores(ta.apply(base, doc))["CON"] == 12


@pytest.mark.parametrize("defect", ["budget", "cap", "sealed-asi", "sealed-insight", "duplicate", "malformed"])
@pytest.mark.parametrize("surface", ["table", "factory", "gm", "add", "remove"])
def test_all_saved_growth_consumers_reject_the_same_invalid_history(tmp_path, monkeypatch, defect, surface):
    from fastapi.testclient import TestClient
    from app.api import create_app
    from app.core import Settings
    from combat.tabletop_service import TabletopService
    from gm2_contract.adapter import apply_table_growth

    base = installed_sheet()
    base["identity"]["cultivation_level"] = 8
    bad = increase(4, CON=2)
    if defect == "budget":
        bad = increase(4, CON=1)
    elif defect == "cap":
        old = ta.current_scores(base)
        base = ta.recompute_from_abilities(base, old, {**old, "CON": 19})
    elif defect.startswith("sealed"):
        kind = "ability_score_change" if defect == "sealed-asi" else "cultivation_insight_acquisition"
        base["advancement_history"] = {"canonical_allocations": [
            {"target_cl": 4, "advancement_kind": kind},
        ]}
    elif defect == "malformed":
        bad["changes"] = {"CON": True}
        bad["gm"] = True  # GM authority cannot turn a boolean into score arithmetic.
    rows = [bad, {**RESET, "cl": 8}]
    if defect == "duplicate":
        rows.insert(1, increase(4, WIS=2))
    package = seal(tmp_path, base)
    service = growth_service(tmp_path)
    service.buttons.save_advancement(PID, {"abilities": rows})
    saved = deepcopy(service.buttons.get(PID)["advancement"])
    digest = hashlib.sha256(package.read_bytes()).hexdigest()

    def no_recompute(*args, **kwargs):
        raise AssertionError("invalid growth reached derived-stat recomputation")
    monkeypatch.setattr(ta, "recompute_from_abilities", no_recompute)
    if surface == "factory":
        # Exercise the actual Factory HTTP overlay without character-creation IO.
        monkeypatch.setattr(TabletopService, "_sphere_names", lambda self: {})
        monkeypatch.setattr(TabletopService, "_catalog_talents", lambda self: [])
        from character_sheet.service import CharacterSheetService
        from character_creation.service import CharacterCreationExecutionService
        monkeypatch.setattr(CharacterSheetService, "sheet", lambda *args, **kwargs: {
            "owner_character_sheet": deepcopy(base), "display_owner_character_sheet": deepcopy(base)})
        monkeypatch.setattr(CharacterCreationExecutionService, "recovery", lambda *args: {})
        with TestClient(create_app(Settings.from_env(ROOT, tmp_path))) as client:
            response = client.get(f"/api/characters/{PID}/sheet")
        assert response.status_code == 409, response.text
    else:
        with pytest.raises((FoundryError, TabletopError)):
            if surface == "table":
                growth_service(tmp_path).combat._factory_owner_sheet(PID)
            elif surface == "gm":
                apply_table_growth({}, base, saved)
            elif surface == "add":
                service.add_ability(PID, increase(8, WIS=2))
            else:
                service.remove_advancement(PID, "ability", str(len(rows) - 1))
    assert not ta.validate_ability_history(base, saved)["legal"]
    assert growth_service(tmp_path).buttons.get(PID)["advancement"] == saved
    assert hashlib.sha256(package.read_bytes()).hexdigest() == digest

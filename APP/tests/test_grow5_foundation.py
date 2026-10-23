"""Public synthetic table installs: Foundation acquisition, sheet/combat and undo."""
from copy import deepcopy

import pytest

from app.core import FoundryError
from combat import table_advance as ta, table_levelup as lu
from non_sphere_authority import foundation_mechanics as fm
from tests.grow5_support import PID, QI, BODY, TALENTS, service, choices, _reach, _add_payload, baseline, install

ANCHOR = "FOUNDATION_03_EMPTY_BOWL_SOUL_ANCHOR"
SACRED = "ancient_desolate_sacred_body_v0_2C"


def pick(view, index=3, **extra):
    payload = choices(view, index)
    if view["level_up"]["advancement_choice"]:
        payload.update(advancement="ability", changes={"CON": 2})
    return {**payload, **extra}


def foundation_rows(view):
    return view["level_up"]["foundation"]["options"]


def test_acquire_stage_preview_commit_cold_reload_sheet_combat_and_undo(tmp_path):
    s = service(tmp_path)
    _reach(s, 5)
    view = s.advancement(PID)
    assert {r["id"] for r in foundation_rows(view)} == set(fm.verified_foundation_records())
    row = next(r for r in foundation_rows(view) if r["id"] == ANCHOR)
    assert row["legal"] and row["stage_options"] == ["Awakened", "Unstable"]
    base = s.combat._factory_owner_sheet(PID, apply_table=False)
    saved = ta.normalized(s.buttons.get(PID).get("advancement"))
    payload = pick(view, foundation_id=ANCHOR, foundation_initial_stage="Awakened")
    proposed = lu.prepare(s.combat._factory_owner_sheet(PID), saved, payload, TALENTS)
    preview = ta.apply(base, proposed)
    control = ta.apply(base, lu.prepare(s.combat._factory_owner_sheet(PID), saved, pick(view), TALENTS))
    assert not control.get("foundation")
    foundation = preview["foundation"]
    assert foundation["record_id"] == foundation["foundation_id"] == ANCHOR
    assert foundation["stage"] == "Awakened"
    assert foundation["display_name"] == row["name"]
    assert foundation["resource"]["current"] == 0
    assert foundation["resource"]["maximum"] == 1
    assert foundation["mechanics"] == fm.resolve_initial_foundation_mechanics(
        fm.verified_foundation_records()[ANCHOR], [QI], stage="Awakened")
    resource = preview["ability_scores_and_statistics"]["primary_resource"]
    plain = control["ability_scores_and_statistics"]["primary_resource"]
    assert resource["maximum"] == plain["maximum"] + 3
    assert resource["maximum"] - resource["build_state_current"] == plain["maximum"] - plain["build_state_current"]
    assert not s.combat._factory_owner_sheet(PID).get("foundation")  # preview does not save
    committed = s.level_up(PID, payload)
    assert committed["level_up"]["foundation"] is None
    assert committed["level_up"]["history"][-1]["foundation"]["name"] == row["name"]
    cold = service(tmp_path)
    assert cold.combat._factory_owner_sheet(PID) == preview
    # The combat sheet exposes the same stage and pool to the existing compiler.
    from non_sphere_authority.foundation_features import features_for_stage
    assert features_for_stage(foundation["foundation_id"], foundation["stage"])
    before = deepcopy(preview)
    cold.level_up(PID, pick(cold.advancement(PID), 4))
    cold = service(tmp_path)
    assert cold.combat._factory_owner_sheet(PID)["foundation"]["stage"] == "Awakened"
    cold.undo_level(PID)
    assert service(tmp_path).combat._factory_owner_sheet(PID) == before
    service(tmp_path).undo_level(PID)
    assert not service(tmp_path).combat._factory_owner_sheet(PID).get("foundation")


def test_not_yet_reoffers_at_cl6_and_below_gate_refuses_atomically(tmp_path):
    s = service(tmp_path)
    view = s.advancement(PID)
    assert view["level_up"]["foundation"] is None
    s.level_up(PID, choices(view))
    view = s.advancement(PID)
    assert view["level_up"]["cl"] == 3 and view["level_up"]["foundation"] is None
    saved = deepcopy(s.buttons.get(PID).get("advancement"))
    with pytest.raises(FoundryError, match="cultivation level 5") as error:
        s.level_up(PID, pick(view, 1, foundation_id=ANCHOR, foundation_initial_stage="Awakened"))
    assert error.value.code == "TABLETOP_LEVEL_NOT_LEGAL" and error.value.status_code == 409
    assert s.buttons.get(PID).get("advancement") == saved
    s.level_up(PID, pick(view, 1))
    s.level_up(PID, pick(s.advancement(PID), 2))
    view = s.advancement(PID)
    assert view["level_up"]["cl"] == 5 and foundation_rows(view)
    s.level_up(PID, pick(view, foundation_id=""))
    view = service(tmp_path).advancement(PID)
    assert view["level_up"]["cl"] == 6 and foundation_rows(view)
    service(tmp_path).level_up(PID, pick(view, 4, foundation_id=ANCHOR, foundation_initial_stage="Unstable"))
    sheet = service(tmp_path).combat._factory_owner_sheet(PID)
    assert sheet["foundation"]["stage"] == "Unstable"
    assert sheet["foundation"]["mechanics"]["resource_modifiers"] == []


@pytest.mark.parametrize("extra", [
    {"foundation_id": ANCHOR},
    {"foundation_id": ANCHOR, "foundation_initial_stage": "Perfected"},
    {"foundation_initial_stage": "Awakened"},
    {"foundation_id": "not-published"},
])
def test_bad_initial_choices_do_not_commit(tmp_path, extra):
    s = service(tmp_path)
    _reach(s, 5)
    saved = deepcopy(s.buttons.get(PID).get("advancement"))
    with pytest.raises(FoundryError):
        s.level_up(PID, pick(s.advancement(PID), **extra))
    assert s.buttons.get(PID).get("advancement") == saved


def test_unique_stage_defaults_and_flat_hp_tracks_pb_without_stacking(tmp_path):
    s = service(tmp_path)
    _reach(s, 5)
    view = s.advancement(PID)
    before = s.combat._factory_owner_sheet(PID)
    saved = ta.normalized(s.buttons.get(PID).get("advancement"))
    control = ta.apply(s.combat._factory_owner_sheet(PID, apply_table=False), lu.prepare(before, saved, pick(view), TALENTS))
    s.level_up(PID, pick(view, foundation_id=SACRED))
    first = service(tmp_path).combat._factory_owner_sheet(PID)
    assert first["foundation"]["stage"] == "Awakened"
    assert first["ability_scores_and_statistics"]["hit_points"]["maximum"] == control["ability_scores_and_statistics"]["hit_points"]["maximum"] + 6
    assert first["ability_scores_and_statistics"]["hit_points"]["table_foundation_delta"] == 6
    s.level_up(PID, pick(s.advancement(PID), 4))
    assert service(tmp_path).combat._factory_owner_sheet(PID)["ability_scores_and_statistics"]["hit_points"]["table_foundation_delta"] == 6
    grown = lu.advance_sheet(first, [{"cl": cl} for cl in (6, 7, 8, 9)], preview=True)
    assert grown["ability_scores_and_statistics"]["hit_points"]["table_foundation_delta"] == 8
    assert grown["foundation"]["stage"] == "Awakened"  # CL alone never advances its stage.
    # Reprojection is deterministic and does not add the flat bonus repeatedly.
    assert service(tmp_path).combat._factory_owner_sheet(PID) == service(tmp_path).combat._factory_owner_sheet(PID)


def test_incompatible_method_is_visible_disabled_and_server_refuses(tmp_path, monkeypatch):
    s = service(tmp_path)
    _reach(s, 5)
    authority = lu.source()
    method = next(iter(authority.methods))
    original = authority.resolve_compatibility

    def compatibility(mid, fid, paths):
        if fid == ANCHOR:
            return {"state": "INCOMPATIBLE"}
        return original(mid, fid, paths)

    monkeypatch.setattr(authority, "resolve_compatibility", compatibility)
    view = s.advancement(PID, primary_method_id=method)
    row = next(r for r in foundation_rows(view) if r["id"] == ANCHOR)
    assert not row["legal"]
    assert authority.methods[method]["name"] in row["reasons"][0]
    with pytest.raises(FoundryError, match="incompatible with your Primary Method"):
        s.level_up(PID, pick(view, foundation_id=ANCHOR, foundation_initial_stage="Awakened"), primary_method_id=method)


def test_active_path_incompatibility_and_multipath_acquisition(tmp_path):
    s = service(tmp_path, BODY)
    _reach(s, 5)
    view = s.advancement(PID)
    unsupported = next(f for f in fm.verified_foundation_records().values() if "BODY_REFINING" not in f["compatible_path_ids"])
    row = next(r for r in foundation_rows(view) if r["id"] == unsupported["foundation_id"])
    assert not row["legal"] and "Body Refining" in row["reasons"][0]
    with pytest.raises(FoundryError, match="does not support your active Paths"):
        s.level_up(PID, pick(view, foundation_id=row["id"], foundation_initial_stage=row["stage_options"][0]))
    payload = _add_payload(view, QI)
    payload.update(foundation_id=SACRED)
    s.level_up(PID, payload)
    sheet = service(tmp_path, BODY).combat._factory_owner_sheet(PID)
    assert set(sheet["foundation"]["active_expression_path_ids"]) == {BODY, QI}


def test_explicit_none_baseline_becomes_a_foundation_and_undo_restores_none(tmp_path):
    sheet = baseline(QI)
    absent = {"state": "none", "source_backed": True}
    sheet["foundation"] = deepcopy(absent)
    sheet["explicit_none_systems"] = {"foundation": deepcopy(absent)}
    install(tmp_path, sheet)
    s = service(tmp_path)
    _reach(s, 5)
    s.level_up(PID, pick(s.advancement(PID), foundation_id=SACRED))
    current = service(tmp_path).combat._factory_owner_sheet(PID)
    assert current["foundation"]["record_id"] == SACRED
    assert "foundation" not in current["explicit_none_systems"]
    service(tmp_path).undo_level(PID)
    current = service(tmp_path).combat._factory_owner_sheet(PID)
    assert current["foundation"] == absent
    assert current["explicit_none_systems"]["foundation"] == absent


def test_later_campaign_gain_blocks_destructive_undo(tmp_path):
    s = service(tmp_path)
    _reach(s, 5)
    s.level_up(PID, pick(s.advancement(PID), foundation_id=SACRED))
    s.add_advancement(PID, "talent", TALENTS[5]["canonical_talent_id"])
    with pytest.raises(FoundryError, match="after this level"):
        s.undo_level(PID)
    assert service(tmp_path).combat._factory_owner_sheet(PID)["foundation"]["foundation_id"] == SACRED

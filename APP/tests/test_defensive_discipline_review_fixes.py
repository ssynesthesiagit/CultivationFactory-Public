"""DEFDISC1 review fixes: stored levels replay without a pick (finding 2), no stale rider assertions or GM-agree
wording for recorded picks (findings 3-4), and the level-up grant reaches the sheet (finding 5)."""
import pytest

from app.core import FoundryError
from character_creation.feature_choices import menu, resolve
from tests.test_auto3_foundations import NASCENT_SOUL, TEMPERED

INDOMITABLE = "tianxia.path.body_refining.feature.indomitable_body"
NASCENT = "tianxia.path.qi_cultivation.feature.nascent_soul"
IMMORTAL = "tianxia.path.qi_cultivation.feature.immortal_of_qi"
CULTIVATED = "tianxia.path.qi_cultivation.feature.cultivated_response"


def _feature(canonical_id):
    return {"canonical_id": canonical_id, "display_name": canonical_id.rsplit(".", 1)[-1]}


# Finding 2: a CL13/CL15/CL20 level stored before the choice existed has no pick. Replaying that history must not
# raise; a new level must still be answered in full.
def test_a_stored_level_without_its_pick_replays_without_raising():
    assert resolve([_feature(INDOMITABLE)], {}, required=False) == {}


def test_a_stored_level_keeps_the_picks_it_has_on_replay():
    out = resolve([_feature(INDOMITABLE)], {INDOMITABLE: "dex"}, required=False)
    assert out == {INDOMITABLE: {"choice": "dex", "defensive_discipline": "DEX"}}


def test_a_new_level_still_requires_every_pick():
    with pytest.raises(FoundryError):
        resolve([_feature(NASCENT)], {})


def test_a_replayed_level_still_rejects_an_unknown_pick():
    with pytest.raises(FoundryError):
        resolve([_feature(INDOMITABLE)], {INDOMITABLE: "int"}, required=False)


# Finding 5: the level-up pick reaches the sheet as the grant the compiler reads (path_and_subpath.feature_build_choices).
def test_a_level_up_pick_grants_the_discipline_the_compiler_reads():
    out = resolve([_feature(NASCENT)], {NASCENT: "int"})
    assert out == {NASCENT: {"choice": "int", "defensive_discipline": "INT"}}


def test_the_level_up_menu_offers_the_two_player_picks_and_not_the_automatic_grant():
    """F12 finding 4: Immortal of Qi's printed "learn all three" is a grant, not a pick (feature_build_choices.json
    "automatic"), so the menu shows the two choices and the third arrives with the feature itself."""
    assert [row["feature_id"] for row in menu([_feature(CULTIVATED), _feature(NASCENT), _feature(IMMORTAL)])] == [
        CULTIVATED, NASCENT]


# F12 finding 3: pending_feature_choices is reported from every menu() return. A character that has run out of levels
# (the old characters this path is for are usually already CL20) must still see the pick panel, or the only way to
# record the pick is unreachable from the UI.
def test_a_finished_cl20_sheet_still_reports_its_missing_pick():
    from combat import table_levelup as lu
    from tests.test_grow3_levelup import QI, baseline

    sheet = baseline(QI)
    sheet["identity"]["cultivation_level"] = 20
    sheet["identity"]["paths"] = [{"path_id": QI, "effective_cl": 20}]
    sheet["path_and_subpath"]["path_feature_record_ids"] = [CULTIVATED]  # gained at CL1, chosen before the pick existed
    view = lu.menu(sheet, [], {"levels": []})
    assert view["available"] is False and "level 20" in view["reason"]
    assert [row["feature_id"] for row in view["pending_feature_choices"]] == [CULTIVATED]
    sheet["path_and_subpath"]["feature_build_choices"] = {CULTIVATED: {"choice": "dex", "defensive_discipline": "DEX"}}
    assert lu.menu(sheet, [], {"levels": []})["pending_feature_choices"] == []



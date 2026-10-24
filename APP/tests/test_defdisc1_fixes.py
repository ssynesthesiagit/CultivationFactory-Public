"""DEFDISC1 review fixes: stored levels replay without a pick (finding 2), no stale rider assertions or GM-agree
wording for recorded picks (findings 3-4), and the level-up grant reaches the sheet (finding 5)."""
import pytest

from app.core import FoundryError
from character_creation.feature_choices import menu, resolve
from tests.test_auto3_foundations import NASCENT_SOUL, TEMPERED, _gm_lines

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


def test_the_level_up_menu_offers_the_second_discipline_at_cl15_and_the_third_at_cl20():
    assert [row["feature_id"] for row in menu([_feature(CULTIVATED), _feature(NASCENT), _feature(IMMORTAL)])] == [
        CULTIVATED, NASCENT, IMMORTAL]


# Findings 3-4: the stale assertion is gone; no GM rider asks the owner to agree a pick the sheet records.
@pytest.mark.parametrize("feature", [NASCENT_SOUL, TEMPERED])
def test_no_gm_line_asks_the_owner_to_agree_a_recorded_discipline(feature):
    lines = _gm_lines(feature)
    assert not any("agree" in line.lower() and "saving" in line.lower() for line in lines), lines


def test_the_second_and_third_discipline_are_not_described_as_asked_later():
    lines = _gm_lines(NASCENT_SOUL)
    assert not any("not asked for yet" in line for line in lines), lines

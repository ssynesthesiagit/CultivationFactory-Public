"""DEFDISC1 finding 2: a character levelled before a Defensive Discipline pick existed sees the pick as unchosen,
can record it at the table, and the record survives reload. Invalid or non-owned picks are rejected before saving,
and a second pick must be a different Defensive Discipline (F12 finding 2: both table callers check the sheet)."""
import types

import pytest

from app.core import FoundryError
from character_creation.feature_choices import contracts
from tests.test_grow3_levelup import BODY, PID, QI, baseline, service

TEMPERED = "tianxia.path.body_refining.feature.tempered_response"
CULTIVATED = "tianxia.path.qi_cultivation.feature.cultivated_response"
NASCENT = "tianxia.path.qi_cultivation.feature.nascent_soul"


def _owned_pick_feature(path):
    owned = baseline(path)["path_and_subpath"]["path_feature_record_ids"]
    return next(row for row in owned if row in contracts() and row in (TEMPERED, CULTIVATED))


@pytest.mark.parametrize("path", [BODY, QI])
def test_unchosen_pick_is_offered_and_settable_and_survives_reload(tmp_path, path):
    feature = _owned_pick_feature(path)
    option = contracts()[feature]["options"][0]["id"]
    svc = service(tmp_path, path)
    pending = svc.advancement(PID)["level_up"]["pending_feature_choices"]
    assert feature in [row["feature_id"] for row in pending]
    svc.set_feature_picks(PID, {feature: option})
    sheet = svc.combat._factory_owner_sheet(PID)
    assert sheet["path_and_subpath"]["feature_build_choices"][feature]["choice"] == option
    assert feature not in [row["feature_id"] for row in svc.advancement(PID)["level_up"]["pending_feature_choices"]]
    reloaded = service(tmp_path, path).combat._factory_owner_sheet(PID)
    assert reloaded["path_and_subpath"]["feature_build_choices"][feature]["choice"] == option


def test_invalid_or_non_owned_pick_is_rejected_and_not_saved(tmp_path):
    feature = _owned_pick_feature(QI)
    svc = service(tmp_path, QI)
    with pytest.raises(FoundryError):
        svc.set_feature_picks(PID, {feature: "not-an-option"})
    with pytest.raises(FoundryError):
        svc.set_feature_picks(PID, {NASCENT: contracts()[NASCENT]["options"][0]["id"]})
    sheet = service(tmp_path, QI).combat._factory_owner_sheet(PID)
    assert feature not in (sheet["path_and_subpath"].get("feature_build_choices") or {})


def _sheet_with_two_choices(recorded=CULTIVATED):
    """A CL15 Qi Cultivator: Cultivated Response already recorded, Nascent Soul still unanswered."""
    sheet = baseline(QI)
    sheet["path_and_subpath"]["path_feature_record_ids"] = [CULTIVATED, NASCENT]
    if recorded:
        sheet["path_and_subpath"]["feature_build_choices"] = {recorded: {"choice": "dex", "defensive_discipline": "DEX"}}
    return sheet


def test_the_table_pick_action_will_not_repeat_a_recorded_discipline():
    """F12 finding 2: set_feature_picks validates against what the sheet already records, so the old-character path
    cannot end up with two picks of the same save (the compiler then keeps one and the character covers neither
    Intelligence nor Charisma)."""
    from combat.tabletop_service import TabletopService

    sheet = _sheet_with_two_choices()
    fake = types.SimpleNamespace(
        buttons=types.SimpleNamespace(get=lambda project_id: {"advancement": {}},
                                      save_advancement=lambda project_id, document: None),
        combat=types.SimpleNamespace(_factory_owner_sheet=lambda project_id, apply_table=True: sheet),
        advancement=lambda project_id, primary_method_id="": {"level_up": {"pending_feature_choices": []}})
    with pytest.raises(FoundryError, match="different Defensive Discipline"):
        TabletopService.set_feature_picks(fake, PID, {NASCENT: "dex"})
    assert NASCENT not in (sheet["path_and_subpath"]["feature_build_choices"] or {})


def test_replaying_a_table_pick_checks_the_disciplines_the_sheet_already_has():
    """The other caller: a stored feature_picks entry replayed through table_advance.apply."""
    from combat import table_advance

    with pytest.raises(FoundryError, match="different Defensive Discipline"):
        table_advance.apply(_sheet_with_two_choices(), {"feature_picks": {NASCENT: "dex"}})
    accepted = table_advance.apply(_sheet_with_two_choices(), {"feature_picks": {NASCENT: "int"}})
    assert accepted["path_and_subpath"]["feature_build_choices"][NASCENT]["choice"] == "int"

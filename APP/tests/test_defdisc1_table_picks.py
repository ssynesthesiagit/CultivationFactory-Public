"""DEFDISC1 finding 2: a character levelled before a Defensive Discipline pick existed sees the pick as unchosen,
can record it at the table, and the record survives reload. Invalid or non-owned picks are rejected before saving."""
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

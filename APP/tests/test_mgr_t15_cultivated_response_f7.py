"""Public regressions for the Cultivated Response review repairs."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FEATURE = "tianxia.path.qi_cultivation.feature.cultivated_response"


def test_failed_plus_pb_must_be_able_to_succeed_before_payment():
    blocks = json.loads((ROOT / "combat/rules/feature_blocks.json").read_text())["features"]
    row = blocks[FEATURE]
    assert row["block"] == "save_rescue"
    assert "allow_insufficient" not in row


def test_unapproved_paid_miss_is_not_marked_applied():
    status = json.loads((ROOT / "combat/rules/feature_status.d/spirit.json").read_text())["features"][FEATURE]
    assert status["status"] == "partial"
    assert "PENDING OWNER SIGN-OFF" not in status["why"]


def test_nascent_soul_points_to_second_discipline_and_timing_is_only_a_table_note():
    data = json.loads((ROOT / "authority/typed_mechanics/reviewed_final.d/auto3_foundations.json").read_text())["mechanics"]
    assert any("Second Defensive Discipline" in x and "Cultivated Response" in x
               for x in data["tianxia.path.qi_cultivation.feature.nascent_soul"]["riders"])
    cultivated = " ".join(data[FEATURE]["riders"])
    assert "TABLE NOTE" in cultivated and "failed save" in cultivated
    assert "does not add a combat trigger" not in cultivated


def test_map_hazard_save_reaches_the_shared_save_rescue_consumer():
    source = (ROOT / "combat/gate2_engine.py").read_text()
    section = source.split("def _resolve_qi_hazard", 1)[1].split("# Action resolution", 1)[0]
    assert "from .typed_reactions import on_save" in section
    assert 'on_save(self, actor, "DEX", 12, roll, SYSTEM_HAZARD)' in section

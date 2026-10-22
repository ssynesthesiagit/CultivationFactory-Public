import json
from pathlib import Path


def test_flame_that_welcomes_all_keeps_original_review_provenance():
    path = (
        Path(__file__).resolve().parents[1]
        / "authority/typed_mechanics/reviewed_final.d/zz_a2_qi_subpaths_7.json"
    )
    records = json.loads(path.read_text())["mechanics"]
    record = records[
        "tianxia.subpath.qi.hearthfire_cultivator.feature.flame_that_welcomes_all"
    ]
    assert record["text_sha256"] == "39b7f82283487784f76277785fc096cb53b9210f99a79205c9256ecd357953e1"
    assert record["reviewed_by"] == "Codex riders/lane11 2026-09-29"


def test_flame_that_welcomes_all_keeps_every_structured_field():
    """Moving the record between reviewer files must not drop its typed economy."""
    path = (
        Path(__file__).resolve().parents[1]
        / "authority/typed_mechanics/reviewed_final.d/zz_a2_qi_subpaths_7.json"
    )
    record = json.loads(path.read_text())["mechanics"][
        "tianxia.subpath.qi.hearthfire_cultivator.feature.flame_that_welcomes_all"
    ]
    assert record["activation"] == {
        "economy": "action",
        "trigger": None,
        "requirement": None,
        "source": "printed_action_type",
    }
    assert record["cost"] == [[{"resource": "qi", "amount": 8, "amount_formula": None}]]
    assert record["range"] is None
    assert record["area"] == {
        "shape": "cylinder",
        "size_ft": 40,
        "evidence": "40-foot-radius, 40-foot-high cylinder",
        "source": "text",
    }
    assert record["target"] is None
    assert record["options"] is None
    assert record["duration"] == {"kind": "minutes", "amount": 1, "concentration": True}
    assert record["use_limit"] == "once_per_scene"
    assert record["min_cl"] == 18
    assert record["effects"] == [{"type": "qi_welcome", "applies_to": "self"}]
    # The old record's four prose entries stay recorded, but as the native
    # sanctuary's notes: clauses the table applies are never GM riders.
    assert record["riders"] == []
    assert len(record["notes"]) == 4
    assert all(note.endswith("Applied by the native sanctuary.") for note in record["notes"])

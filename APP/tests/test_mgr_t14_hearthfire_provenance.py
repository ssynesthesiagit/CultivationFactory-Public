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

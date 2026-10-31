"""Public synthetic regression for native Subpath Realm suppression."""

from combat.subpath_acquisition import acquired_features


FERRY = "tianxia.subpath.qi.riverway_cultivator.feature.ferry_the_wounded"
PATH = "tianxia.path.qi_cultivation"
SUBPATH = "tianxia.subpath.qi.riverway_cultivator"


def test_acquired_subpath_uses_validated_identity_effective_level(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "combat.subpath_acquisition.progression_index",
        lambda _app: {
            SUBPATH: {
                "owning_path_id": PATH,
                "feature_progression": [{"canonical_id": FERRY, "granted_at_cl": 6}],
            }
        },
    )
    sheet = {
        "identity": {
            "cultivation_level": 6,
            "effective_cultivation_level": 3,
            # Deliberately retain the stale field to prove it cannot mask suppression.
            "effective_cl": 6,
        },
        "path_and_subpath": {
            "paths": [{"path_id": PATH, "attainment": 6, "effective_cl": 6}],
            "subpaths": [{"subpath_id": SUBPATH, "owning_path_id": PATH}],
        },
    }
    assert acquired_features(sheet, tmp_path) == {}

    sheet["identity"]["effective_cultivation_level"] = 6
    assert acquired_features(sheet, tmp_path)[FERRY] == {"cl": 6, "min_cl": 6}

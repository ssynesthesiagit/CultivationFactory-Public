"""Choice-reactor admission is limited to owners of the applicable Spirit features."""
from types import SimpleNamespace

from combat.ext.spiritual_state import spirit_save_targets


THREADED = "tianxia.tradition.spirit.soulstring_dancer.feature.threaded_step"
RECOMPENSE = "tianxia.tradition.spirit.equal_measure_scripture.feature.threefold_recompense"


def test_spirit_probe_enrolls_only_actual_feature_owners():
    engine = SimpleNamespace(
        state=SimpleNamespace(actors={"dancer": object(), "scripture": object(), "bystander": object()}),
        typed_passive_rows={
            "dancer": [{"feature_id": THREADED}],
            "scripture": [{"feature_id": RECOMPENSE}],
            "bystander": [{"feature_id": "unrelated.feature"}],
        },
    )

    assert set(spirit_save_targets(engine)) == {"dancer", "scripture"}


def test_spirit_probe_is_inert_without_owner_rows_or_for_missing_actors():
    engine = SimpleNamespace(
        state=SimpleNamespace(actors={"present": object()}),
        typed_passive_rows={
            "missing": [{"feature_id": THREADED}],
            "present": [{"feature_id": "unrelated.feature"}],
        },
    )

    assert spirit_save_targets(engine) == ()

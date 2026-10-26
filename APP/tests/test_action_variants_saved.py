"""Structured variant metadata survives the saved-fight format and cold reload (F4).

`ActionDefinition.variant` is presentation metadata. It is excluded from serialization
when absent, so every non-variant action keeps its exact prior serialized form, and it
round-trips unchanged when present. These checks use synthetic fights in pytest tmp_path.
"""
from combat.gate2_runtime_models import ActionDefinition
from tests.worker2_support import OWNER, fixture, reload


def test_variant_metadata_round_trips_through_saved_format_and_cold_reload(tmp_path):
    combat, table, mid = fixture(tmp_path, ["TAL_DARK_DARKVISION", "TAL_DARK_PERSISTENT_MELD"])
    engine = reload(tmp_path, mid)
    variant_rows = [a for a in engine.action_catalog.values() if a.owner_id == OWNER and a.variant]
    plain_rows = [a for a in engine.action_catalog.values() if a.owner_id == OWNER and a.variant is None]
    assert variant_rows and plain_rows
    for action in variant_rows:
        dumped = action.model_dump(mode="json")
        assert dumped["variant"] == action.variant.model_dump(mode="json")
        assert ActionDefinition.model_validate(dumped).variant == action.variant
    for action in plain_rows:
        # exclude_if keeps non-variant serialization byte-identical to the pre-variant format.
        assert "variant" not in action.model_dump(mode="json")
        assert "variant" not in action.model_dump(mode="json", by_alias=True)
        assert ActionDefinition.model_validate(action.model_dump(mode="json")).variant is None
    # Cold reload after the round trip still restores the same metadata and replays cleanly.
    after = reload(tmp_path, mid)
    reloaded = {a.source_definition_id: a.variant for a in after.action_catalog.values() if a.variant}
    assert reloaded == {a.source_definition_id: a.variant for a in variant_rows}

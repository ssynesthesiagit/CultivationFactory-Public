from tests.h49_fog_support import assert_roundtrip
from tests.r1i_service_support import FOE, OWNER, SECOND, candidate, fixture


def test_blinded_viewer_has_no_ordinary_fog_vision(tmp_path):
    combat, table, mid, _send, commit = fixture(
        tmp_path, ["RADIANCE_TAL_BLINDING_FLASH"],
        foe_talents=["tianxia.subpath.body.heaven_thunder_drum_body.feature.heaven_drum_circulation"],
        wide=True,
        positions={OWNER: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 6}, SECOND: {"x": 5, "y": 6}},
    )
    commit(candidate(table, mid, "Blinding Flash"))
    state = table.state(mid, fog=True)
    foe = next(actor for actor in state["presentation"]["actors"] if actor["entity_id"] == FOE)
    assert any(row["condition_id"] == "condition:typed.blinded" for row in foe["conditions"])
    assert OWNER in state["fog_perception"][FOE]["creatures"]  # Tremorsense pinpoints a creature, not nearby squares.
    assert [x for x, y in state["fog_perception"][FOE]["cells"] if (x, y) != (4, 6)] == []
    assert_roundtrip(combat, tmp_path, mid)

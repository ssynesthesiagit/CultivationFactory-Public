from tests.h49_fog_support import assert_roundtrip
from tests.r1i_service_support import FOE, OWNER, SECOND, candidate, fixture


def test_blinded_viewer_has_no_ordinary_fog_vision(tmp_path):
    combat, table, mid, send, _commit = fixture(
        tmp_path, ["RADIANCE_TAL_BLINDING_FLASH"],
        foe_talents=["tianxia.subpath.body.heaven_thunder_drum_body.feature.heaven_drum_circulation"],
        wide=True,
        positions={OWNER: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 6}, SECOND: {"x": 5, "y": 6}},
    )
    # Establish blindness on the viewer, not whichever recipient the setup
    # helper picks first. The emanation includes this adjacent creature.
    cid = candidate(table, mid, "10-Foot Emanation")
    pending = send(cid)
    assert pending["status"] == "REACTION_REQUIRED"
    context = pending["reaction"]["context"]
    assert context["reaction_source_id"] == "choice:needle.area_recipients"
    assert FOE in [row["id"] for row in pending["reaction"]["choice"]["options"]]
    assert send(cid, [{**context, "selection": "USE", "option_ids": [FOE]}])["status"] == "COMMITTED"
    state = table.state(mid, fog=True)
    foe = next(actor for actor in state["presentation"]["actors"] if actor["entity_id"] == FOE)
    assert any(row["condition_id"] == "condition:typed.blinded" for row in foe["conditions"])
    assert OWNER in state["fog_perception"][FOE]["creatures"]  # Tremorsense pinpoints a creature, not nearby squares.
    assert [x for x, y in state["fog_perception"][FOE]["cells"] if (x, y) != (4, 6)] == []
    assert_roundtrip(combat, tmp_path, mid)

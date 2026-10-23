from tests.h49_fog_support import assert_roundtrip, option
from tests.r1i_service_support import FOE, OWNER, SECOND, fixture


def test_darkness_fog_matches_engine_endpoint_policy(tmp_path):
    combat, table, mid, _send, commit = fixture(
        tmp_path, ["DARK_BASE_DARKNESS"], allies=(SECOND,), wide=True,
        positions={OWNER: {"x": 3, "y": 6}, FOE: {"x": 8, "y": 6}, SECOND: {"x": 12, "y": 6}},
    )
    commit(option(table, mid, "Darkness", {"x": 6, "y": 6})["candidate_id"])
    perception = table.state(mid, fog=True)["fog_perception"][SECOND]
    assert FOE not in perception["creatures"]
    assert [3, 6] not in perception["cells"]
    assert [2, 6] in perception["cells"]  # outside-to-outside matches the engine's endpoint policy
    assert_roundtrip(combat, tmp_path, mid)

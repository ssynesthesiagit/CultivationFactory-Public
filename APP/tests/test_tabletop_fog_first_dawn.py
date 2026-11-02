from tests.h49_fog_support import assert_roundtrip, option, turn_to
from tests.r1i_service_support import FOE, OWNER, SECOND, fixture


FIRST_DAWN = "tianxia.talent.radiance.first_dawn_before_falsehood"


def test_first_dawn_suppression_is_used_by_fog(tmp_path):
    combat, table, mid, _send, commit = fixture(
        tmp_path, [FIRST_DAWN], foe_talents=["DARK_BASE_DARKNESS"], owner_dc=1, wide=True,
        positions={OWNER: {"x": 3, "y": 6}, FOE: {"x": 8, "y": 6}, SECOND: {"x": 9, "y": 6}},
    )
    commit(option(table, mid, "First Dawn Before Falsehood")["candidate_id"])
    turn_to(table, mid, commit, FOE)
    commit(option(table, mid, "Darkness", {"x": 6, "y": 6})["candidate_id"])
    assert FOE in table.state(mid, fog=True)["fog_perception"][OWNER]["creatures"]
    assert [6, 6] in table.state(mid, fog=True)["fog_perception"][OWNER]["cells"]
    from combat.tabletop_service import TabletopService
    from combat.gate5_service import CombatService
    fresh = TabletopService(CombatService(combat.source_root, tmp_path), tmp_path)
    assert fresh.state(mid, fog=True)["fog_perception"] == table.state(mid, fog=True)["fog_perception"]
    assert_roundtrip(combat, tmp_path, mid)

from combat.gate5_service import CombatService
from tests.h1_support import ROOT
from tests.r1i_service_support import fixture, candidate, OWNER, FOE
from tests.test_riders_lane1 import BLACK_SUN


def test_nested_black_sun_damage_uses_native_committed_packet(tmp_path):
    combat, table, mid, send, commit = fixture(tmp_path, [BLACK_SUN], foe_talents=["WATER_BASE_SHAPE_CURRENT"])
    commit(candidate(table, mid, "Black Sun Over the Dantian", FOE))
    commit(table.state(mid)["menu"]["end_turn"])
    while table.state(mid)["menu"]["actor_id"] != FOE:
        commit(table.state(mid)["menu"]["end_turn"])
    before = combat._load_session(mid).engine.state.event_sequence
    commit(candidate(table, mid, "Shape Current: Cleansing Basin"))
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    damage = [e for e in loaded.engine.events if e.sequence > before and e.event_type == "DAMAGE_COMMITTED"
              and str(e.source_definition_id).endswith(BLACK_SUN) and FOE in (e.target_ids or ())]
    packet, = damage
    assert packet.actor_id == OWNER and packet.target_ids == (FOE,)
    assert packet.payload["damage_type"] in {"PSYCHIC", "NECROTIC"}
    assert packet.payload["hp_damage"] + packet.payload.get("temporary_hp_absorbed", 0) > 0
    assert loaded.mechanical.replay()["status"] == "PASS"

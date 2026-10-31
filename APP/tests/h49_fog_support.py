from combat.gate5_service import CombatService
from tests.r1i_service_support import OWNER, candidate, fixture


def option(table, mid, label, destination=None):
    group = next(row for row in table.state(mid)["menu"]["actions"] if label == row["label"])
    return next(row for row in group["options"] if destination is None or row.get("destination") == destination)


def turn_to(table, mid, commit, actor_id):
    for _ in range(8):
        menu = table.state(mid)["menu"]
        if menu["actor_id"] == actor_id:
            return
        commit(menu["end_turn"])
    raise AssertionError(f"{actor_id} did not receive a turn")


def assert_roundtrip(combat, tmp_path, mid):
    loaded = combat._load_session(mid)
    state = loaded.engine.state.model_dump(mode="json")
    fresh = CombatService(combat.source_root, tmp_path)._load_session(mid)
    assert fresh.engine.state.model_dump(mode="json") == state
    assert loaded.verify()["status"] == "PASS"
    assert loaded.mechanical.replay()["status"] == "PASS"

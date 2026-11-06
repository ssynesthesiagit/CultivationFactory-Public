"""SOL179: real concentration casts, table commits, disk reload, and expiry."""
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h48_table_support import OWNER, fixture, assert_reload_verify_replay
from tests.test_riders_lane11 import MOON


def test_concentration_names_survive_commit_reload_and_disappear_on_expiry(tmp_path):
    combat, table, mid, _, commit = fixture(tmp_path, [MOON], seed="SOL179-concentration")

    def fresh_effects():
        fresh = TabletopService(CombatService(combat.source_root, tmp_path), tmp_path)
        return next(a for a in fresh.state(mid)["presentation"]["actors"]
                    if a["entity_id"] == OWNER)["concentration_effects"]

    assert fresh_effects() == []
    for count in (1, 2):
        action = next(a for a in table.state(mid)["menu"]["actions"] if MOON in a["source_definition_id"])
        option = next(o for o in action["options"] if o.get("destination") == {"x": 3, "y": 6})
        commit(option["candidate_id"])
        assert fresh_effects() == [action["label"]] * count
        if count == 1:
            commit(table.state(mid)["menu"]["end_turn"])
            while table.state(mid)["menu"]["actor_id"] != OWNER:
                commit(table.state(mid)["menu"]["end_turn"])

    # The earlier copy expires independently. Each observation loads disk state.
    observed_counts = []
    for _ in range(40):
        commit(table.state(mid)["menu"]["end_turn"])
        observed_counts.append(len(fresh_effects()))
        if observed_counts[-1] == 0:
            break
    assert 1 in observed_counts
    assert observed_counts[-1] == 0
    feed = combat.presentation(mid)["feed"]
    assert any("stopped concentrating on" in row["summary"] for row in feed)
    assert_reload_verify_replay(combat, mid, tmp_path)

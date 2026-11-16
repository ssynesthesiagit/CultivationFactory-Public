"""The fight feed reports travelled distance, not movement allowance spent."""
from combat.canonical import canonical_sha256
from combat.history_feed import format_history_feed
from tests.test_c2_review import table_fixture, until_turn, action, send, reload
from tests.test_riders_c2 import _sheet, ME, ATK, ALLY

PURSUER = "tianxia.tradition.spirit.black_current_walker.feature.turn_the_pursuer"


def test_table_feed_reports_walk_and_pursuer_distance(tmp_path):
    defender = _sheet(["TAL_ALCHEMY_CALMING_HEART_PILL"])
    defender["path_and_subpath"]["path_feature_record_ids"] = [PURSUER]
    defender["ability_scores_and_statistics"]["primary_resource"] = {"name": "Resonance", "maximum": 30}

    def configure(bundles):
        for bundle in bundles:
            bundle["actor_template"]["maximum_hp"] = 500
            bundle.pop("bundle_sha256", None)
            bundle["bundle_sha256"] = canonical_sha256(bundle)

    _, table, mid = table_fixture(tmp_path, {
        ME: defender,
        ATK: _sheet(["TAL_ALCHEMY_CALMING_HEART_PILL"], weapon="tianxia.mortal.weapon.dao"),
        ALLY: _sheet(["TAL_ALCHEMY_CALMING_HEART_PILL"]),
    }, {ME: (3, 6), ATK: (4, 5), ALLY: (3, 7)}, seed="FEED-MOVE", configure=configure)
    until_turn(table, mid, ME)
    engine = reload(tmp_path, mid)
    move = next(c for c in engine.legal_candidates()
                if c.kind.value == "MOVE" and (c.destination.x, c.destination.y) == (3, 5))
    assert send(table, mid, move.candidate_id)["status"] == "COMMITTED"
    assert send(table, mid, table.state(mid)["menu"]["end_turn"])["status"] == "COMMITTED"
    until_turn(table, mid, ATK)
    cid = action(table, mid, "Dao (Saber / Broadsword) attack", ME)
    answers = []
    for _ in range(16):
        result = send(table, mid, cid, answers)
        if result["status"] == "COMMITTED":
            break
        prompt = result["reaction"]
        answer = {**prompt["context"], "selection": "DECLINE"}
        if prompt["reaction"] == "Turn the Pursuer":
            answer.update(selection="USE", option_ids=["cell:2,5"])
        answers.append(answer)
    else:
        assert False, "unending reaction prompts"
    events = table.events(mid, 0)["events"]
    moves = [row for row in events if row["event_type"] == "MOVEMENT_COMMITTED"
             and row["raw"]["actor_id"] == ME]
    assert any("(3, 5) (5 ft)" in row["summary"] for row in moves)
    assert any("(2, 5) (5 ft)" in row["summary"] for row in moves)
    raw = [row["raw"]["payload"] for row in moves]
    assert any(p["cost_ft"] == 5 and p["distance_ft"] == 5 for p in raw)
    assert any(p["cost_ft"] == 0 and p["distance_ft"] == 5 for p in raw)


def test_forced_movement_feed_uses_recorded_distance():
    event = {"sequence": 1, "event_type": "MOVEMENT_COMMITTED", "actor_id": "a",
             "source_definition_id": "push", "target_ids": [],
             "payload": {"destination": {"x": 2, "y": 1}, "forced": True,
                         "cost_ft": 0, "distance_ft": 5}}
    rows = format_history_feed([event], [], pre_state=None, post_state={},
                               actor_names={"a": "Mira"}, definition_names={})
    assert rows[0]["summary"] == "Mira was moved by force to (2, 1) (5 ft)."

"""No-action hit preferences use the existing persisted table composition path."""
from combat.ext import shi_pressure_points, tabik_ninpo
from tests.hunt36_support import HIDDEN, LEFT, RIGHT, fight, reload, turn

POINTS = [
    "PRESSURE_POINTS_BASE_PRESSURE_POINTS_TRAINING",
    "PRESSURE_POINTS_BASE_NUMBING_POINT",
    "tianxia.talent.pressure_points.breath_seal",
]


def test_hidden_strike_and_pressure_points_nest_draft_and_commit_with_attack(tmp_path, monkeypatch):
    monkeypatch.setenv("CF_EMBED_MENU", "0")
    combat, table, mid = fight(tmp_path, [HIDDEN, tabik_ninpo.PPS, *POINTS],
                               seed="NOACTRELOAD1")
    turn(combat, table, mid)
    state = table.state(mid)
    menu = state["menu"]
    engine = combat._load_session(mid).engine
    selected = {}
    for cid, spec in menu["composition"].items():
        action = engine.action_catalog[spec["source"]]
        row = action.parameters["typed"]["effects"][0]
        if (row["type"] == "hidden_strike_choice" and row["choice"] == "sever"
                or row["type"] == "pressure_point_choice" and row["choice"] == "off"
                or row["type"] == "shi_pp_pick_point" and row["key"] == "numb_leg"
                or row["type"] == "shi_pp_pick_seal"):
            selected[row["type"]] = (cid, spec)
    assert set(selected) == {"hidden_strike_choice", "pressure_point_choice",
                             "shi_pp_pick_point", "shi_pp_pick_seal"}, menu["composition"]
    attack = next(g for g in menu["actions"] if g["economy"] == "ACTION"
                  and any(c["candidate_id"] == selected["shi_pp_pick_point"][0]
                          for entry in state["shapes"].get(LEFT, []) if entry["base"] == g["source_definition_id"]
                          for c in entry.get("choices", []))
                  and any(o["target_ids"] == [RIGHT] for o in g["options"]))
    nested = next(entry for entry in state["shapes"][LEFT] if entry["base"] == attack["source_definition_id"])
    assert {selected[key][0] for key in ("hidden_strike_choice", "shi_pp_pick_point", "shi_pp_pick_seal")} <= {
        c["candidate_id"] for c in nested["choices"]}
    assert all(not row.get("choices") for row in state["shapes"].get(RIGHT, []))
    # The same independent key cannot accumulate two alternatives.
    point_specs = [spec for spec in menu["composition"].values() if spec["key"] == ["shi_pp_pick_point"]]
    assert len(point_specs) >= 4

    payload = {"actor_id": LEFT, "decision_id": menu["decision_id"], "state_version": menu["state_version"],
               "sources": [spec["source"] for _cid, spec in selected.values()],
               "source_definition_id": attack["source_definition_id"], "request_id": "noaction-attack"}
    journal = combat._load_session(mid).store.journal_path
    before = journal.read_bytes()
    preview = table.preview_composition(mid, payload)
    assert journal.read_bytes() == before, "Selecting/aiming must not commit a preference"
    option = next(o for g in preview["menu"]["actions"] for o in g["options"] if o["target_ids"] == [RIGHT])
    answers = []
    for _ in range(20):
        result = table.commit_composition(mid, payload, option["candidate_id"], 0, answers)
        if result["status"] == "COMMITTED":
            break
        assert result["status"] == "REACTION_REQUIRED", result
        prompt = result["reaction"]
        answer = {**prompt["context"], "selection": "DECLINE"}
        answers.append(answer)
    else:
        raise AssertionError("Composition did not finish")
    engine = reload(combat, mid)
    held = list(engine.state.actors[LEFT].conditions.values())
    for _cid, spec in selected.values():
        assert any(c.source_definition_id == spec["source"] for c in held)
    assert any(c.condition_id == tabik_ninpo.CHOICE and c.data["choice"] == "sever" for c in held)
    assert any(c.condition_id == shi_pressure_points.POINT_PICK for c in held)
    assert engine.state.state_version > menu["state_version"]

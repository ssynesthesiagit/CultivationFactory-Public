"""Spark Step acquisition and recipient choices through native table commits."""
import pytest
import json
from pathlib import Path

from combat.gate5_service import CombatService
from tests.r1i_service_support import OWNER, FOE, SECOND, candidate, fixture
from tests.h1_support import ROOT

SPARK = "TAL_LIGHTNING_SPARK_STEP"
GATHER = "TAL_LIGHTNING_GATHER_CHARGE"
AUTHORITY = Path(__file__).resolve().parents[1] / "authority/Tianxia_Typed_Mechanics_Authority_R1.json"


def _run_gather(table, mid, cid, *, selected=None, decline_spark=False):
    answers, prompts = [], []
    for _ in range(8):
        menu = table.state(mid)["menu"]
        result = table.act(mid, cid, menu["decision_id"], menu["state_version"], 0, answers)
        if result["status"] == "COMMITTED":
            return prompts
        assert result["status"] == "REACTION_REQUIRED", result
        prompt = result["reaction"]
        prompts.append(prompt)
        choice = prompt.get("choice")
        available = [o["id"] for o in choice["options"]] if choice else []
        is_spark = "Spark Step" in str(prompt)
        option_ids = [selected] if selected in available else ((choice.get("preferred") or available[:1]) if choice else [])
        answers.append({**prompt["context"], "selection": "DECLINE" if decline_spark and is_spark else "USE",
                        "option_ids": [] if decline_spark and is_spark else option_ids})
    raise AssertionError("Spark Step did not resolve")


@pytest.mark.parametrize("cl,feet", [(4, 5), (5, 10)])
def test_compiled_owner_chooses_visible_ally_and_commits_spark_step(tmp_path, cl, feet):
    combat, table, mid, send, commit = fixture(tmp_path, [GATHER, SPARK], owner_cl=cl,
                                                allies=[SECOND], positions={OWNER: {"x": 3, "y": 6},
                                                FOE: {"x": 7, "y": 6}, SECOND: {"x": 4, "y": 7}})
    engine = combat._load_session(mid).engine
    assert any(row.get("feature_id") == SPARK for row in engine.typed_passive_rows[OWNER])
    gather = candidate(table, mid, "Gather Charge", OWNER)
    source_id = next(g["source_definition_id"] for g in table.state(mid)["menu"]["actions"]
                     if "Gather Charge" in g["label"] and any(OWNER in o.get("target_ids", [])
                                                               for o in g["options"]))
    assert engine.action_catalog[source_id].parameters["typed"]["source"] == GATHER
    authority = json.loads(AUTHORITY.read_text())["mechanics"][SPARK]
    assert authority["source"]["text_sha256"] == "d409e4af61961b046cced3d466f8d97c2fa8822c67c8ed5bfe900da0867e635e"
    assert authority["effects"][0]["distance_ft"] == 5
    assert not authority["riders"]
    assert authority["modifier"]["add_range_ft"] == 10
    before = engine.state.actors[OWNER].position
    prompts = _run_gather(table, mid, gather, selected=SECOND)
    spark_choices = [p for p in prompts if p.get("choice") and "Spark Step" in str(p)]
    assert len(spark_choices) == 2
    assert SECOND in {o["id"] for o in spark_choices[1]["choice"]["options"]}
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    actor = loaded.engine.state.actors[OWNER]
    assert actor.position != before
    assert loaded.engine.grid.distance_ft(before, actor.position) <= feet
    assert "spark_step_ignore_oa_from" not in actor.turn_flags
    assert loaded.verify()["status"] == loaded.mechanical.replay()["status"] == "PASS"


def test_spark_step_allows_visible_creature_without_enemy_and_unowned_character_is_inert(tmp_path):
    combat, table, mid, send, commit = fixture(tmp_path, [GATHER, SPARK], owner_cl=4,
                                                allies=[FOE, SECOND])
    engine = combat._load_session(mid).engine
    assert any(row.get("feature_id") == SPARK for row in engine.typed_passive_rows[OWNER])
    gather = candidate(table, mid, "Gather Charge", OWNER)
    prompts = _run_gather(table, mid, gather, selected=FOE)
    assert FOE in {o["id"] for p in prompts if p.get("choice") for o in p["choice"]["options"]}
    assert CombatService(ROOT, tmp_path)._load_session(mid).verify()["status"] == "PASS"

    other_combat, other_table, other_mid, _, _ = fixture(tmp_path / "unowned", [GATHER], owner_cl=4)
    other_engine = other_combat._load_session(other_mid).engine
    assert not any(row.get("feature_id") == SPARK for row in other_engine.typed_passive_rows[OWNER])
    before = other_engine.state.actors[OWNER].position
    prompts = _run_gather(other_table, other_mid, candidate(other_table, other_mid, "Gather Charge", OWNER))
    assert not any("Spark Step" in str(prompt) for prompt in prompts)
    assert other_combat._load_session(other_mid).engine.state.actors[OWNER].position == before


def test_other_gather_target_and_declined_step_do_not_move_owner(tmp_path):
    combat, table, mid, _, _ = fixture(tmp_path, [GATHER, SPARK], owner_cl=4, allies=[SECOND])
    engine = combat._load_session(mid).engine
    before = engine.state.actors[OWNER].position
    target_gather = candidate(table, mid, "Gather Charge", SECOND)
    prompts = _run_gather(table, mid, target_gather)
    assert not any("Spark Step" in str(prompt) for prompt in prompts)
    reloaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert reloaded.engine.state.actors[OWNER].position == before

    # A fresh table ensures this is a real player decline, not a state reset.
    other = tmp_path / "declined"
    combat2, table2, mid2, _, _ = fixture(other, [GATHER, SPARK], owner_cl=4)
    before2 = combat2._load_session(mid2).engine.state.actors[OWNER].position
    prompts = _run_gather(table2, mid2, candidate(table2, mid2, "Gather Charge", OWNER), decline_spark=True)
    assert any("Spark Step" in str(prompt) for prompt in prompts)
    assert CombatService(ROOT, other)._load_session(mid2).engine.state.actors[OWNER].position == before2

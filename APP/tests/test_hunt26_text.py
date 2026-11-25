"""Choice explanations at the table, including saved Feint benefits."""
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT
from tests.test_hunt26 import FOE, ME, candidate, fight, reload, submit
from tests.test_hunt26_exploit import resolve
import pytest


def test_analyze_approach_and_court_characteristics_explain_choices(tmp_path):
    combat, table, mid = fight(tmp_path, ["TAL_THE_HIDDEN_EYE_COURT_OF_THE_HIDDEN_EYE"], skilled=True,
                               foe_talents=["tianxia.path.spirit_awakening.feature.spiritual_sense"])
    cid = candidate(table, mid, "Court of the Hidden Eye", ME)
    resolve(combat, table, mid, cid)
    cid = candidate(table, mid, "Analyze", FOE)
    answers = []
    for _ in range(4):
        result = submit(combat, table, mid, cid, answers=answers)
        if result["status"] == "COMMITTED":
            break
        prompt = result["reaction"]
        assert "No printed rule summary" not in prompt["summary"]
        assert "Analyze" in prompt["rules"] and "Enemy" in prompt["moment"]
        for option in prompt["choice"]["options"]:
            assert option["description"] != option["label"]
            assert "spiritual_sense" not in option["label"]
            assert not option["label"].startswith("GM information")
        if prompt["context"]["reaction_source_id"].endswith("eye_learn"):
            assert prompt["choice"]["minimum"] == 2
            assert "Court of the Hidden Eye" in prompt["summary"] and "additional" in prompt["summary"]
        ids = [o["id"] for o in prompt["choice"]["options"]]
        picked = (["spiritual_sense Sense", "GM information 1"] if "spiritual_sense Sense" in ids
                  else ids[:prompt["choice"]["minimum"]])
        answers.append({**prompt["context"], "selection": "USE", "option_ids": picked})
    assert result["status"] == "COMMITTED" and len(answers) == 2
    engine = reload(combat, mid)
    assert any(c.data.get("name") == "spiritual_sense Sense" for c in engine.state.actors[ME].conditions.values())


@pytest.mark.parametrize("greater", [False, True])
def test_feint_choice_describes_advantage_beneficiary_cost_and_expiry(tmp_path, greater):
    combat, table, mid = fight(tmp_path, ["TAL_FENCING_EXPERT_FEINT", *(["TAL_FENCING_GREATER_FEINT"] if greater else [])])
    cid = candidate(table, mid, "Feint (Bonus Action)", FOE)
    result = submit(combat, table, mid, cid)
    assert result["status"] == "REACTION_REQUIRED"
    prompt = result["reaction"]
    assert "Advantage" in prompt["summary"] and "Enemy" in prompt["moment"]
    assert "end of your next turn" in prompt["choice"]["options"][0]["description"]
    assert "Bonus Action" in prompt["cost"] and "no additional" in prompt["cost"].lower()
    assert "Feint" in prompt["rules"]
    _, prompts = resolve(combat, table, mid, cid)
    if greater:
        extra = next(p for p in prompts if p["context"]["reaction_source_id"].endswith("greater_feint"))
        assert "Wisdom save" in extra["summary"] and "end of your next turn" in extra["limits"]
        assert "Martial Focus" in extra["cost"]
    engine = reload(combat, mid)
    assert any(m.target_field == "attack_mode_vs" and m.value == f"ADVANTAGE:{FOE}"
               for m in engine.state.actors[ME].modifiers.values())
    fresh = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
    assert fresh.state(mid)["presentation"] == table.state(mid)["presentation"]


def test_feint_ally_choice_explains_earlier_expiry_and_reloads(tmp_path):
    from tests.test_tabletop_hunt6 import table_fight, LEFT, ALLY, RIGHT

    combat, table, mid = table_fight(tmp_path, ["TAL_FENCING_EXPERT_FEINT"], ally_talents=[])
    cid = candidate(table, mid, "Feint (Bonus Action)", RIGHT)
    result = submit(combat, table, mid, cid)
    prompt = result["reaction"]
    option = next(o for o in prompt["choice"]["options"] if o["id"] == ALLY)
    assert "Ally" in option["description"] and "Right" in option["description"]
    assert "start of your next turn" in option["description"]
    assert submit(combat, table, mid, cid, answers=[{**prompt["context"], "selection": "USE", "option_ids": [ALLY]}])["status"] == "COMMITTED"
    engine = reload(combat, mid)
    modifier = next(m for m in engine.state.actors[ALLY].modifiers.values() if m.value == f"ADVANTAGE:{RIGHT}")
    from combat.ext.effect_durations import token
    assert modifier.expires_on == token("start", LEFT, engine.state.actors[LEFT].turns_started + 1)

"""Spark Step's chosen-creature exemption and AI choice through native table actions."""
from combat.gate5_service import CombatService
from tests.h1_support import ROOT
from tests.r1i_service_support import OWNER, FOE, SECOND, THIRD, candidate, fixture, force_ai_candidate

GATHER = "TAL_LIGHTNING_GATHER_CHARGE"
SPARK = "TAL_LIGHTNING_SPARK_STEP"


def _act_gather(table, mid, cid, *, exempt=None, destination=None):
    answers = []
    for _ in range(12):
        menu = table.state(mid)["menu"]
        result = table.act(mid, cid, menu["decision_id"], menu["state_version"], 0, answers)
        if result["status"] == "COMMITTED":
            return
        assert result["status"] == "REACTION_REQUIRED", result
        prompt = result["reaction"]
        choices = prompt.get("choice")
        ids = [o["id"] for o in choices["options"]] if choices else []
        if destination in ids:
            selected = destination
        elif exempt in ids:
            selected = exempt
        else:
            selected = ((choices.get("preferred") or ids[:1]) if choices else [])
        answers.append({**prompt["context"], "selection": "USE", "option_ids": [selected] if isinstance(selected, str) else selected})
    raise AssertionError("Gather Charge with Spark Step did not finish")


def test_selected_hostile_is_exempt_but_other_hostile_still_gets_opportunity_attack(tmp_path):
    positions = {OWNER: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 6},
                 SECOND: {"x": 10, "y": 10}, THIRD: {"x": 3, "y": 7}}
    combat, table, mid, _, _ = fixture(tmp_path, [GATHER, SPARK], owner_cl=4,
                                       extra_foe=True, positions=positions)
    _act_gather(table, mid, candidate(table, mid, "Gather Charge", OWNER),
                exempt=FOE, destination="cell:2,5")
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    destination = loaded.engine.state.actors[OWNER].position
    assert (destination.x, destination.y) == (2, 5)
    attacks = [event.actor_id for event in loaded.engine.events if event.event_type == "ATTACK_ROLLED"]
    assert THIRD in attacks
    assert FOE not in attacks
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_ai_owner_automatically_resolves_owned_spark_step(tmp_path):
    combat, table, mid, _, _ = fixture(tmp_path, [GATHER, SPARK], owner_cl=4)
    cid = candidate(table, mid, "Gather Charge", OWNER)
    force_ai_candidate(combat, mid, OWNER, cid)
    result = table.auto_step(mid, 0, [])
    assert result["status"] == "COMMITTED", result
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.actors[OWNER].position.model_dump(mode="json") != {"x": 3, "y": 6, "z": 0}
    assert loaded.mechanical.replay()["status"] == "PASS"

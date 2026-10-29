"""Spark Step's optional per-attack range uses committed current-turn movement."""
import pytest

from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT
from tests.r1i_service_support import OWNER, FOE, SECOND, fixture, force_ai_candidate

SPARK = "TAL_LIGHTNING_SPARK_STEP"
LASH = "TAL_LIGHTNING_LIGHTNING_LASH"


def _options(table, mid, *, extended, target):
    return [o for g in table.state(mid)["menu"]["actions"]
            if "Lightning Lash" in g["label"] and ("Spark Step" in g["label"]) == extended
            for o in g["options"] if target in o.get("target_ids", [])]


def _commit(table, mid, cid):
    answers = []
    for _ in range(16):
        menu = table.state(mid)["menu"]
        result = table.act(mid, cid, menu["decision_id"], menu["state_version"], 0, answers)
        if result["status"] == "COMMITTED":
            return result
        assert result["status"] == "REACTION_REQUIRED", result
        prompt = result["reaction"]
        answer = {**prompt["context"], "selection": "DECLINE"}
        if prompt.get("choice") and not prompt["choice"].get("allow_decline"):
            answer.update(selection="USE", option_ids=[o["id"] for o in prompt["choice"]["options"]]
                          [:prompt["choice"].get("minimum_selections", 1)])
        answers.append(answer)
    raise AssertionError("attack did not resolve")


def _move(table, mid, x):
    move = next(o for o in table.state(mid)["menu"]["moves"]
                if o["destination"] == {"x": x, "y": 6})
    _commit(table, mid, move["candidate_id"])


@pytest.mark.parametrize("owned,automatic", [(True, False), (True, True), (False, False)])
def test_lash_range_after_ten_feet_survives_reload_and_expires_with_turn(tmp_path, owned, automatic):
    combat, table, mid, _, _ = fixture(
        tmp_path, [LASH, *([SPARK] if owned else [])], wide=True,
        positions={OWNER: {"x": 3, "y": 6}, FOE: {"x": 18, "y": 6},
                   SECOND: {"x": 10, "y": 10}})
    assert not _options(table, mid, extended=True, target=FOE)
    _move(table, mid, 4)
    assert not _options(table, mid, extended=True, target=FOE)  # five feet is insufficient
    _move(table, mid, 5)

    # A cold service reload must recover the movement history, not a transient flag.
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    choices = _options(table, mid, extended=True, target=FOE)
    assert bool(choices) == owned  # foe is 65 feet away; normal Lash reaches only 60
    assert not _options(table, mid, extended=False, target=FOE)
    assert _options(table, mid, extended=False, target=SECOND)  # declining stays reachable
    engine = combat._load_session(mid).engine
    base = [a for a in engine.action_catalog.values() if a.owner_id == OWNER
            and a.parameters.get("typed", {}).get("source") == LASH
            and not a.parameters.get("typed", {}).get("modifier")]
    assert base and all(a.range_ft == 60 for a in base)
    if not owned:
        return
    cid = choices[0]["candidate_id"]
    if automatic:
        force_ai_candidate(combat, mid, OWNER, cid)
        result = table.auto_step(mid, 0, [])
        assert result["status"] == "COMMITTED", result
        combat.set_controller_mode(mid, actor_id=OWNER, controller_mode="MANUAL")
    else:
        _commit(table, mid, cid)
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert any(e.event_type == "ATTACK_ROLLED" and e.actor_id == OWNER and FOE in e.target_ids
               for e in loaded.engine.events)
    assert loaded.verify()["status"] == loaded.mechanical.replay()["status"] == "PASS"

    # No turn-wide range mutation: a new turn with no movement offers no extension.
    _commit(table, mid, table.state(mid)["menu"]["end_turn"])
    for _ in range(6):
        if table.state(mid)["menu"]["actor_id"] == OWNER:
            break
        _commit(table, mid, table.state(mid)["menu"]["end_turn"])
    assert table.state(mid)["menu"]["actor_id"] == OWNER
    assert not _options(table, mid, extended=True, target=FOE)

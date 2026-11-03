"""Blood rider choice text must report the same CP pool and cost the table commits."""

from combat.gate5_service import CombatService
from tests.r1i_service_support import OWNER, ROOT, fixture
from tests.r10_fixup_support import answer, cast_sender


def test_bloodletting_prompt_names_cost_and_commits_that_cost_after_reload(tmp_path):
    talent = "tianxia.talent.blood.bloodletting_strike"
    combat, table, match, _send, _commit = fixture(tmp_path, [talent], owner_dc=50)
    session = combat._load_session(match)
    before = session.engine.state.actors[OWNER].resources["resource:core.qi"]

    send = cast_sender(combat, table, match, "Blood Thread", target="actor:factory.r1i-foe")
    result = send()
    assert result["status"] == "REACTION_REQUIRED", result
    prompt = result["reaction"]
    assert prompt["reaction"] == "Bloodletting Strike"
    assert "1 Qi" in prompt["cost"]
    assert "paying Path pool not recorded" not in prompt["cost"]
    assert "table does not charge that cost automatically" not in prompt["table_note"]

    committed = send([answer(prompt, "bloodletting")])
    assert committed["status"] == "COMMITTED", committed
    fresh = CombatService(ROOT, tmp_path)._load_session(match)
    actor = fresh.engine.state.actors[OWNER]
    assert actor.resources["resource:core.qi"] == before - 1
    assert fresh.mechanical.replay()["status"] == "PASS"

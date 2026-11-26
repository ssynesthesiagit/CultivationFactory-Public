"""Secondary Destructive Blast targets respect isolation through table commits."""
import pytest

from tests.test_hunt32_edge import FOE, act, match, reload
from tests.test_hunt32_prison import ALLY, PRISON

CHAIN = "tianxia.talent.destruction.calamity_chain_reaction"
BLAST = "TAL_DESTRUCTION_DESTRUCTIVE_BLAST"
DROPPED = "actor:factory.h32-chain-trigger"
OTHER = "actor:factory.h32-chain-other"


@pytest.mark.parametrize("mode", ["MANUAL", "LOCAL_AUTO"])
@pytest.mark.parametrize("imprisoned", [True, False])
@pytest.mark.parametrize("other_target", [False, True])
def test_chain_secondary_target_respects_fold_prison(tmp_path, mode, imprisoned, other_target):
    foes = [(DROPPED, 1), *([(OTHER, 120)] if other_target else [])]
    combat, table, mid = match(
        tmp_path, [PRISON] if imprisoned else [], allies=True,
        ally_mode=mode, ally_mids=[CHAIN], extra_foes=foes, ally_attack_bonus=100)
    if imprisoned:
        assert act(table, mid, "Fold Prison", FOE)["status"] == "COMMITTED"
    assert act(table, mid)["status"] == "COMMITTED"
    before = reload(combat, tmp_path, mid)
    assert before.state.current_actor_id == ALLY
    hp = before.state.actors[FOE].current_hp
    pools = dict(before.state.actors[ALLY].resources)
    start = len(before.events)
    options = ([] if imprisoned else [FOE]) + ([OTHER] if other_target else [])
    expected = options[0] if options else None
    if mode == "MANUAL":
        answers = []
        result = act(table, mid, "Destructive Blast", DROPPED)
        while result["status"] == "REACTION_REQUIRED":
            prompt = result["reaction"]
            assert reload(combat, tmp_path, mid).state.model_dump(mode="json") == before.state.model_dump(mode="json")
            assert options, "An isolated secondary target must not be offered"
            assert prompt["context"]["reaction_source_id"] == "choice:needle.destruction_chain"
            assert [o["id"] for o in prompt["choice"]["options"]] == options
            assert "Calamity Chain Reaction" in str(prompt) and "Destructive Blast" in str(prompt)
            answers.append({**prompt["context"], "selection": "USE", "option_ids": [expected]})
            result = act(table, mid, "Destructive Blast", DROPPED, answers)
        assert result["status"] == "COMMITTED"
    else:
        for _ in range(12):
            result = table.auto_step(mid, table.state(mid)["last_sequence"])
            assert result["status"] == "COMMITTED"
            if not reload(combat, tmp_path, mid).state.actors[DROPPED].active:
                break
    engine = reload(combat, tmp_path, mid)
    assert not engine.state.actors[DROPPED].active, "The real blast must trigger the secondary burst"
    events = engine.events[start:]
    secondary = [e for e in events if e.event_type == "DAMAGE_COMMITTED"
                 and BLAST in e.source_definition_id and DROPPED not in e.target_ids]
    payments = [e for e in events if e.event_type == "RESOURCE_SPENT"
                and e.source_definition_id == f"passive:{CHAIN}"]
    if imprisoned:
        assert engine.state.actors[FOE].current_hp == hp
        assert not any(FOE in e.target_ids for e in secondary)
    if expected is None:
        assert not secondary and not payments
        assert engine.state.actors[ALLY].resources == pools
        assert not any(r.reason.endswith(":chain") for r in engine.rolls[len(before.rolls):])
    else:
        assert engine.state.actors[expected].current_hp < before.state.actors[expected].current_hp
        assert len(secondary) == len(payments) == 1
        assert secondary[0].target_ids == (expected,)
        assert payments[0].payload["amount"] == 1
        pool = payments[0].payload["resource_id"]
        assert engine.state.actors[ALLY].resources[pool] == pools[pool] - 1

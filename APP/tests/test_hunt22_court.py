"""Court respects the defender's weapon reach through saved table actions."""
import pytest

from combat.canonical import canonical_sha256
from tests.test_c2_review import table_fixture, until_turn, action, send, auto_send, reload
from tests.test_riders_c2 import _sheet, ME, ATK, ALLY


@pytest.mark.parametrize("auto", [False, True])
@pytest.mark.parametrize("defender_weapon,steps", [
    ("tianxia.mortal.weapon.dao", False),
    ("tianxia.mortal.weapon.qiang", True),
])
def test_court_uses_defender_reach(tmp_path, auto, defender_weapon, steps):
    def configure(bundles):
        for bundle in bundles:
            bundle["actor_template"]["maximum_hp"] = 500
            if bundle["actor_id"] == ME:
                bundle["actor_template"]["armor_class"] = 1000
            bundle.pop("bundle_sha256", None)
            bundle["bundle_sha256"] = canonical_sha256(bundle)

    combat, table, mid = table_fixture(tmp_path, {
        ME: _sheet(["TAL_WRESTLING_COURT_OF_THE_CLOSED_DISTANCE"], cl=17, weapon=defender_weapon),
        ATK: _sheet(["TAL_ALCHEMY_CALMING_HEART_PILL"], weapon="tianxia.mortal.weapon.qiang"),
        ALLY: _sheet(["TAL_ALCHEMY_CALMING_HEART_PILL"]),
    }, {ME: (3, 6), ATK: (5, 6), ALLY: (3, 7)}, seed="H22-COURT", configure=configure)
    until_turn(table, mid, ME)
    assert send(table, mid, action(table, mid, "Court of the Closed Distance", ME))["status"] == "COMMITTED"
    reload(tmp_path, mid)
    until_turn(table, mid, ATK)
    cid = action(table, mid, "Qiang (Spear) attack", ME)
    answers, prompts = [], []
    for _ in range(16):
        result = auto_send(combat, table, mid, cid, answers) if auto else send(table, mid, cid, answers)
        if result["status"] == "COMMITTED":
            break
        prompt = result["reaction"]
        prompts.append(prompt)
        answer = {**prompt["context"], "selection": "DECLINE"}
        if prompt.get("choice"):
            answer.update(selection="USE", option_ids=[prompt["choice"]["options"][0]["id"]])
        answers.append(answer)
    else:
        pytest.fail("unending Court prompts")
    engine = reload(tmp_path, mid)
    assert any(p["context"]["reaction_source_id"] == "choice:needle.wrestling_court_step" for p in prompts) == steps
    if steps:
        court = next(p for p in prompts if p["context"]["reaction_source_id"] == "choice:needle.wrestling_court_step")
        assert "Qiang (Spear) attack" in court["moment"] and "no action or resource" in court["moment"]
    assert (engine.state.actors[ME].position.x != 3) == steps

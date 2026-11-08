"""Hollow Path Step prices its actual paying pool before table consent/payment."""
import pytest

from combat.canonical import canonical_sha256
from combat.factory_compiler import compile_character
from tests.h1_support import sheet
from tests.r1i_service_support import fixture, candidate, force_ai_candidate, OWNER, FOE
from tests.test_r1i_round3 import reload
from tests.test_c4_protection_review import inherited_prompt_loader

PATH = "TAL_VOID_HOLLOW_PATH_STEP"
TALENTS = [PATH, "TAL_VOID_EMPTY_STEP"]


def scenario(pool, points, hollowed):
    """Compile a real Stamina or Qi paying row; bound only starting pools/attack."""
    def prepare(bundles):
        doc = sheet(TALENTS, cl=17, primary=pool)
        other_pool = "Stamina" if pool == "Qi" else "Qi"
        doc["ability_scores_and_statistics"]["primary_resource"] = {
            "name": pool, "maximum": 30, "definitions": [{"name": other_pool, "max": 30}]}
        compiled = compile_character(doc, actor_id=OWNER, reaction_plan={"ask": True})
        owner, foe = bundles[:2]
        owner["typed_reactions"] = compiled["typed_reactions"]
        owner["actor_template"]["resources"] = compiled["actor_template"]["resources"]
        paying = "resource:core." + ("qi" if pool == "Qi" else "stamina")
        for resource in owner["actor_template"]["resources"]:
            resource["initial"] = points if resource["resource_id"] == paying else min(5, resource["maximum"])
        assert next(r for r in owner["typed_reactions"] if r["feature_id"] == PATH)["costs"] == [
            {"resource_id": paying, "amount": 2}]
        for action in foe["action_catalog"]:
            if action["display_name"].startswith("Void Needle"):
                typed = action["parameters"]["typed"]
                typed["numbers"]["attack_bonus"] = -100
                typed["effects"] = ([{"type": "condition", "condition": "hollowed", "applies_to": "self",
                                      "expires_on": "UNTIL_REMOVED"}] if hollowed else []) + [
                    {"type": "attack", "attack_kind": "cultivation_ranged", "on_hit": []}]
        for bundle in bundles:
            bundle.pop("bundle_sha256", None)
            bundle["bundle_sha256"] = canonical_sha256(bundle)
    return prepare


@pytest.mark.parametrize("pool", ["Qi", "Stamina"])
@pytest.mark.parametrize("hollowed,points,eligible", [(True, 1, True), (True, 3, True),
    (True, 0, False), (False, 1, False), (False, 2, True)])
@pytest.mark.parametrize("mode", ["manual", "ai_attacker", "ai_both", "decline"])
def test_path_step_price_pause_payment_and_reload_table(tmp_path, pool, hollowed, points, eligible, mode):
    combat, table, mid, send, commit = fixture(tmp_path, TALENTS, owner_ac=500,
        foe_talents=["TAL_VOID_VOID_NEEDLE"], seed="C4-PATH-STEP",
        bundle_transform=scenario(pool, points, hollowed))
    while table.state(mid)["menu"]["actor_id"] != FOE:
        commit(table.state(mid)["menu"]["end_turn"])
    if mode == "ai_both":
        combat.set_controller_mode(mid, actor_id=OWNER, controller_mode="LOCAL_AUTO")
    cid = candidate(table, mid, "Void Needle", OWNER)
    auto = mode in ("ai_attacker", "ai_both")
    if auto:
        force_ai_candidate(combat, mid, FOE, cid)
    before = reload(tmp_path, mid).state.model_dump(mode="json")
    start = len(reload(tmp_path, mid).events)
    answers, prompts = [], []
    for _ in range(5):
        result = send(cid, answers, auto=auto)
        if result["status"] == "COMMITTED":
            break
        assert result["status"] == "REACTION_REQUIRED", result
        p = result["reaction"]
        prompts.append(p)
        assert reload(tmp_path, mid).state.model_dump(mode="json") == before
        assert send(cid, answers, auto=auto)["reaction"] == p
        source = p["context"]["reaction_source_id"]
        assert source in ("reaction:typed." + PATH, "choice:needle.reaction_teleport")
        assert "Hollow Path Step" in str(p)
        answer = {**p["context"], "selection": "DECLINE" if mode == "decline" else "USE"}
        if p.get("choice") and mode != "decline":
            answer["option_ids"] = p["choice"]["preferred"][:1]
        answers.append(answer)
    else:
        pytest.fail("reaction failed to commit")
    engine = reload(tmp_path, mid)
    events = engine.events[start:]
    assert any(e.event_type == "ATTACK_ROLLED" and e.actor_id == FOE and not e.payload["provisional_hit"] for e in events)
    used = eligible and mode != "decline"
    cost = 1 if hollowed else 2
    paying = "resource:core." + ("qi" if pool == "Qi" else "stamina")
    bearer = engine.state.actors[OWNER]
    original = before["actors"][OWNER]
    assert bearer.resources[paying] == points - (cost if used else 0)
    for key, value in original["resources"].items():
        if key != paying:
            assert bearer.resources[key] == value
    assert (bearer.position.model_dump(mode="json") != original["position"]) == used
    assert bearer.reaction_available == (not used)
    payments = [e.payload for e in events if e.event_type == "RESOURCE_SPENT" and e.source_definition_id == PATH]
    assert [(e["resource_id"], e["amount"]) for e in payments] == ([(paying, cost)] if used else [])
    assert not any(e.event_type == "RESOURCE_GAINED" and e.source_definition_id == PATH for e in events)
    assert len(prompts) == (0 if not eligible or mode == "ai_both" else 1 if mode == "decline" else 2)
    # Price is checkpoint-local; the persisted compiled row still costs two.
    assert next(r for r in engine.typed_reaction_rows[OWNER] if r["feature_id"] == PATH)["costs"][0]["amount"] == 2

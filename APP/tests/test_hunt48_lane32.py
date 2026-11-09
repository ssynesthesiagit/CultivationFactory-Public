"""Hunt 48 table-level regressions for persisted combat behavior."""

from combat.canonical import canonical_sha256
from tests.h48_table_support import ESSENCE, FOE, OWNER, assert_reload_verify_replay, candidate, fixture


def test_one_daemonic_defeat_notifies_own_kill_once_through_table(tmp_path):
    retainer = "TAL_DAEMONIC_CULTIVATION_DEMON_COURT_RETAINER"

    def initial(bundles):
        for resource in bundles[0]["actor_template"]["resources"]:
            if resource["resource_id"] == ESSENCE:
                resource["initial"] = 8
        # Augment deals 4 damage; Demon Mark's bonus defeats this 5 HP target.
        bundles[1]["actor_template"]["maximum_hp"] = 5
        for bundle in bundles:
            bundle.pop("bundle_sha256", None)
            bundle["bundle_sha256"] = canonical_sha256(bundle)

    combat, table, match_id, send, _commit = fixture(
        tmp_path, [retainer, "TAL_DAEMONIC_CULTIVATION_DEMON_MARK"], seed="H48-RETAINER",
        extra_foe=True, bundle_transform=initial,
    )
    candidate_id = candidate(table, match_id, "Demon Mark + Daemonic Augment: Bonus Damage", FOE)
    answers = []
    for _ in range(20):
        result = send(candidate_id, answers)
        if result["status"] == "COMMITTED":
            break
        assert result["status"] == "REACTION_REQUIRED", result
        prompt = result["reaction"]
        answer = {**prompt["context"], "selection": "USE"}
        if prompt.get("choice"):
            answer["option_ids"] = (prompt["choice"].get("preferred") or
                                    [prompt["choice"]["options"][0]["id"]])[:1]
        answers.append(answer)
    else:
        raise AssertionError("reaction loop")

    engine = combat._load_session(match_id).engine
    payments = [event for event in engine.events if event.event_type == "RESOURCE_SPENT"
                and event.source_definition_id == retainer]
    assert len(payments) == 1, "one defeat caused repeated Retainer payments"
    assert_reload_verify_replay(combat, match_id, tmp_path)


def test_retainer_cannot_activate_with_only_one_essence_through_table(tmp_path):
    retainer = "TAL_DAEMONIC_CULTIVATION_DEMON_COURT_RETAINER"

    def initial(bundles):
        for resource in bundles[0]["actor_template"]["resources"]:
            if resource["resource_id"] == ESSENCE:
                resource["initial"] = 1
                resource["maximum"] = 1
        bundles[1]["actor_template"]["maximum_hp"] = 1
        for bundle in bundles:
            bundle.pop("bundle_sha256", None)
            bundle["bundle_sha256"] = canonical_sha256(bundle)

    combat, table, match_id, send, _commit = fixture(
        tmp_path, [retainer, "TAL_DAEMONIC_CULTIVATION_DEMON_MARK"], seed="H48-RETAINER-ONE",
        extra_foe=True, bundle_transform=initial,
    )
    candidate_id = candidate(table, match_id, "Demon Mark + Daemonic Augment: Bonus Damage", FOE)
    answers = []
    for _ in range(20):
        result = send(candidate_id, answers)
        if result["status"] == "COMMITTED":
            break
        assert result["status"] == "REACTION_REQUIRED", result
        prompt = result["reaction"]
        answer = {**prompt["context"], "selection": "USE"}
        if prompt.get("choice"):
            answer["option_ids"] = (prompt["choice"].get("preferred") or
                                    [prompt["choice"]["options"][0]["id"]])[:1]
        answers.append(answer)
    else:
        raise AssertionError("reaction loop")

    engine = combat._load_session(match_id).engine
    payments = [event for event in engine.events if event.event_type == "RESOURCE_SPENT"
                and event.source_definition_id == retainer]
    assert not payments, "Retainer activated without its full 2 Essence cost"
    assert engine.state.actors[OWNER].resources[ESSENCE] == 1
    assert_reload_verify_replay(combat, match_id, tmp_path)


def test_reservoir_table_description_matches_its_scene_limit(tmp_path):
    golden_core = "tianxia.path.qi_cultivation.feature.golden_core_form"
    combat, table, match_id, _send, commit = fixture(
        tmp_path, [], seed="H48-RESERVOIR-TEXT", path_features=[golden_core],
    )
    commit(candidate(table, match_id, "Golden Core Form: Golden Core Reservoir"))
    group = next(group for group in table.state(match_id)["menu"]["actions"]
                 if group["label"] == "Golden Core Reservoir")
    assert "once per scene" in group["description"]
    assert "once per round" not in group["description"]
    assert_reload_verify_replay(combat, match_id, tmp_path)

"""Turn the Pursuer's attack branch must not execute its Soulwake-entry save."""
import pytest

from combat.canonical import canonical_sha256
from tests.test_c2_review import table_fixture, until_turn, action, send, auto_send, reload
from tests.test_riders_c2 import _sheet, ME, ATK, ALLY

PURSUER = "tianxia.tradition.spirit.black_current_walker.feature.turn_the_pursuer"


@pytest.mark.parametrize("auto,stay,ai_defender", [
    (False, False, False), (True, False, False),
    (False, True, False), (True, True, False),
    (False, False, True), (True, False, True),
])
def test_pursuer_attack_branch_table(tmp_path, auto, stay, ai_defender):
    defender = _sheet(["TAL_ALCHEMY_CALMING_HEART_PILL"])
    defender["path_and_subpath"]["path_feature_record_ids"] = [PURSUER]
    defender["ability_scores_and_statistics"]["primary_resource"] = {"name": "Resonance", "maximum": 30}
    def configure(bundles):
        for b in bundles:
            b["actor_template"]["maximum_hp"] = 500
            b.pop("bundle_sha256", None)
            b["bundle_sha256"] = canonical_sha256(b)
    combat, table, mid = table_fixture(tmp_path, {
        ME: defender,
        ATK: _sheet(["TAL_ALCHEMY_CALMING_HEART_PILL"], weapon="tianxia.mortal.weapon.dao"),
        ALLY: _sheet(["TAL_ALCHEMY_CALMING_HEART_PILL"]),
    }, {ME: (3, 6), ATK: (4, 6), ALLY: (3, 7)}, seed="H22-PURSUER", configure=configure)
    until_turn(table, mid, ATK)
    if ai_defender:
        combat.set_controller_mode(mid, actor_id=ME, controller_mode="LOCAL_AUTO")
    before = reload(tmp_path, mid)
    resonance = before.state.actors[ME].resources["resource:core.resonance"]
    start = before.state.event_sequence
    cid = action(table, mid, "Dao (Saber / Broadsword) attack", ME)
    answers, prompts = [], []
    for _ in range(16):
        result = auto_send(combat, table, mid, cid, answers) if auto else send(table, mid, cid, answers)
        if result["status"] == "COMMITTED":
            break
        p = result["reaction"]
        prompts.append(p)
        answer = {**p["context"], "selection": "DECLINE"}
        if "Turn the Pursuer" in p["reaction"]:
            answer["selection"] = "USE"
            if p.get("choice"):
                choices = p["choice"]["options"]
                chosen = next((c for c in choices if c["id"] == "cell:3,6"), choices[0]) if stay else next(
                    (c for c in choices if c["id"] == "cell:2,6"), choices[0])
                answer["option_ids"] = [chosen["id"]]
        answers.append(answer)
    else:
        pytest.fail("unending Pursuer prompts")
    engine = reload(tmp_path, mid)
    events = [e for e in engine.events if e.sequence > start]
    assert any("Turn the Pursuer" in p["reaction"] for p in prompts) == (not ai_defender)
    assert not any(e.event_type == "SAVE_ROLLED" and e.source_definition_id == PURSUER for e in events)
    assert not any(m.source_definition_id == PURSUER for m in engine.state.actors[ATK].modifiers.values())
    # C8 automates the printed optional Carry the Reed; this AI carries its ally.
    assert engine.state.actors[ME].resources["resource:core.resonance"] == resonance - (3 if ai_defender else 2)
    if ai_defender:
        assert engine.grid.distance_ft(before.state.actors[ALLY].position, engine.state.actors[ALLY].position) == 5
    assert not engine.state.actors[ME].reaction_available
    assert not any(m.source_definition_id == PURSUER for m in engine.state.actors[ME].modifiers.values())
    assert not any(c.condition_id == "condition:typed.pursuer_attack_guard" for c in engine.state.actors[ME].conditions.values())
    attacks = [e for e in events if e.event_type == "ATTACK_ROLLED" and e.actor_id == ATK]
    if stay:
        assert attacks and attacks[-1].payload["target_ac"] == before.state.actors[ME].armor_class + 2
    else:
        if not ai_defender:
            assert engine.state.actors[ME].position.x == 2
        assert engine._distance_actor_to_actor(engine.state.actors[ME], engine.state.actors[ATK]) > 5
        assert not attacks


@pytest.mark.parametrize("auto", [False, True])
@pytest.mark.parametrize("scenario", ["tremorsense", "blindsight", "unperceived", "friendly"])
def test_pursuer_perception_and_friendly_attack_table(tmp_path, auto, scenario):
    from combat.stealth import sees
    from combat.senses import pinpoints, perceives_without_sight
    defender = _sheet(["TAL_ALCHEMY_CALMING_HEART_PILL"])
    defender["path_and_subpath"]["path_feature_record_ids"] = [PURSUER]
    defender["ability_scores_and_statistics"]["primary_resource"] = {"name": "Resonance", "maximum": 30}

    def configure(bundles):
        for b in bundles:
            b["actor_template"]["maximum_hp"] = 500
            if b["actor_id"] == ME:
                b["senses"] = {"rows": ([{"sense": scenario, "range_ft": 30, "when": "always"}]
                                       if scenario in ("tremorsense", "blindsight") else [])}
            if scenario == "friendly" and b["actor_id"] == ATK:
                # A controlled friendly-fire action, through the same table resolver.
                for a in b["action_catalog"]:
                    if a["display_name"] == "Dao (Saber / Broadsword) attack":
                        a["target_kind"] = "ALLY_OR_SELF"
            b.pop("bundle_sha256", None)
            b["bundle_sha256"] = canonical_sha256(b)
    combat, table, mid = table_fixture(tmp_path, {
        ME: defender,
        ATK: _sheet(["DARK_BASE_DARKNESS"], weapon="tianxia.mortal.weapon.dao"),
        ALLY: _sheet(["TAL_ALCHEMY_CALMING_HEART_PILL"]),
    }, {ME: (3, 6), ATK: (4, 6), ALLY: (3, 7)}, seed="H22-PERCEPTION",
        foes=(ALLY,) if scenario == "friendly" else (ATK,), configure=configure)
    until_turn(table, mid, ATK)
    if scenario != "friendly":
        engine = reload(tmp_path, mid)
        cid = next(c.candidate_id for c in engine.legal_candidates() if c.display_name == "Darkness at 4,6")
        assert send(table, mid, cid)["status"] == "COMMITTED"
        # Darkness uses the action; next turn provides the actual attack.
        assert send(table, mid, table.state(mid)["menu"]["end_turn"])["status"] == "COMMITTED"
        until_turn(table, mid, ATK)
    engine = reload(tmp_path, mid)
    if scenario == "tremorsense":
        assert not sees(engine, engine.state.actors[ME], engine.state.actors[ATK])
        assert pinpoints(engine, engine.state.actors[ME], engine.state.actors[ATK])
    elif scenario == "blindsight":
        assert perceives_without_sight(engine, engine.state.actors[ME], engine.state.actors[ATK])
    elif scenario == "unperceived":
        assert not sees(engine, engine.state.actors[ME], engine.state.actors[ATK])
        assert not pinpoints(engine, engine.state.actors[ME], engine.state.actors[ATK])
        assert not perceives_without_sight(engine, engine.state.actors[ME], engine.state.actors[ATK])
    else:
        assert engine.state.actors[ME].team_id == engine.state.actors[ATK].team_id
    resource = engine.state.actors[ME].resources["resource:core.resonance"]
    cid = action(table, mid, "Dao (Saber / Broadsword) attack", ME)
    run = lambda answers: auto_send(combat, table, mid, cid, answers) if auto else send(table, mid, cid, answers)
    result = run([])
    if scenario == "unperceived":
        assert result["status"] == "COMMITTED"
    else:
        assert result["status"] == "REACTION_REQUIRED"
        p = result["reaction"]
        assert p["reaction"] == "Turn the Pursuer"
        assert p["context"]["reactor_id"] == ME
        answers = [{**p["context"], "selection": "USE", "option_ids": ["cell:2,6"]}]
        result = run(answers)
        assert result["status"] == "REACTION_REQUIRED"
        carry = result["reaction"]
        assert carry["reaction"] == "Carry the Reed"
        assert carry["context"]["reactor_id"] == ME
        answers.append({**carry["context"], "selection": "DECLINE"})
        assert run(answers)["status"] == "COMMITTED"
    engine = reload(tmp_path, mid)
    assert engine.state.actors[ME].resources["resource:core.resonance"] == resource - (0 if scenario == "unperceived" else 2)

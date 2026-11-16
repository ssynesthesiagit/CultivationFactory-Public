"""Real attacks, manual consent and automatic defense at the saved table boundary."""
import pytest

from combat.gate5_service import CombatService
from tests.test_tabletop_hunt6 import table_fight, LEFT, RIGHT, ALLY
from tests.test_lock2_persistence import act
from tests.test_carry import KIT
from tests.r10_fixup_support import cast_sender

TEAMWORK = "TAL_BEASTMASTERY_DEFENSIVE_TEAMWORK"


@pytest.mark.parametrize("owner_distance", [10, 15])
def test_extended_beast_reach_after_spending_reaction_at_table(tmp_path, monkeypatch, owner_distance):
    import json
    from combat import summons

    # Supported summon data extension, confined to this scratch fight.
    rules = summons.rules()
    rules["beasts"]["wolf"]["attacks"][0]["reach_ft"] = 10
    rules_path = tmp_path / "summons.json"
    rules_path.write_text(json.dumps(rules))
    monkeypatch.setattr(summons, "RULES_PATH", rules_path)
    combat, table, mid = table_fight(tmp_path, [TEAMWORK], kit={"starting_kit": KIT},
                                     ask=True, ally_talents=[])
    engine = combat._load_session(mid).engine
    beast_id = next(a.entity_id for a in engine.state.actors.values()
                    if a.owner_id == LEFT and ".summon.beast" in a.entity_id)
    beast = engine.state.actors[beast_id]
    move = next(c for c in engine.legal_candidates()
                if c.display_name.startswith("Move") and c.destination
                and engine._distance_actor_to_cell(beast, c.destination) == owner_distance)
    commit(cast_sender(combat, table, mid, "Move", at=(move.destination.x, move.destination.y)),
           use_teamwork=False)
    while table.state(mid)["menu"]["actor_id"] != RIGHT:
        assert act(table, mid, "end")["status"] == "COMMITTED"
    engine = combat._load_session(mid).engine
    beast = engine.state.actors[beast_id]
    assert engine._distance_actor_to_actor(engine.state.actors[LEFT], beast) == owner_distance
    assert engine._distance_actor_to_actor(engine.state.actors[RIGHT], beast) <= 10
    move = next(c for c in engine.legal_candidates()
                if c.display_name.startswith("Move") and c.destination
                and engine._distance_actor_to_cell(beast, c.destination) > 10)
    # Reviewed manual consent now includes a summoned creature's opportunity
    # attack. Spend the beast's Reaction explicitly, keeping its owner's free.
    commit(cast_sender(combat, table, mid, "Move", at=(move.destination.x, move.destination.y)),
           opportunity_actor=beast_id)
    loaded = CombatService(combat.source_root, tmp_path)._load_session(mid)
    assert not loaded.engine.state.actors[beast_id].reaction_available
    assert loaded.engine.state.actors[LEFT].reaction_available
    assert loaded.mechanical.replay()["status"] == "PASS"
    prompts = commit(cast_sender(combat, table, mid, "Bi Shou (Dagger) thrown", target=beast_id))
    loaded = CombatService(combat.source_root, tmp_path)._load_session(mid)
    engine = loaded.engine
    bonuses = [e for e in engine.events if e.event_type == "MODIFIER_APPLIED"
               and e.source_definition_id == TEAMWORK]
    if owner_distance == 10:
        assert any(p["reaction"] == "Defensive Teamwork" for p in prompts)
        assert bonuses and all(e.target_ids == (beast_id,) for e in bonuses)
        rolled = next(e for e in engine.events if e.event_type == "ATTACK_ROLLED"
                      and e.actor_id == RIGHT and beast_id in e.target_ids)
        assert rolled.payload["target_ac"] == engine.state.actors[beast_id].armor_class + 2
        assert not engine.state.actors[LEFT].reaction_available
    else:
        assert not bonuses
        assert not any(p["reaction"] == "Defensive Teamwork" for p in prompts)
        assert engine.state.actors[LEFT].reaction_available
    assert not any(m.source_definition_id == TEAMWORK for a in engine.state.actors.values()
                   for m in a.modifiers.values())
    assert loaded.mechanical.replay()["status"] == "PASS"


def commit(send, *, use_teamwork=True, opportunity_actor=None):
    answers, prompts = [], []
    for _ in range(20):
        result = send(answers)
        if result["status"] == "COMMITTED":
            return prompts
        assert result["status"] == "REACTION_REQUIRED", result
        p = result["reaction"]
        prompts.append(p)
        use = ((use_teamwork and p["reaction"] == "Defensive Teamwork")
               or (p["context"]["reaction_source_id"] == "reaction:typed.opportunity_attack"
                   and p["context"]["reactor_id"] == opportunity_actor))
        answer = {**p["context"], "selection": "USE" if use else "DECLINE"}
        if use and p.get("choice"):
            answer["option_ids"] = [p["choice"]["options"][0]["id"]]
        answers.append(answer)
    raise AssertionError("reaction loop")


@pytest.mark.parametrize("automatic", [False, True])
@pytest.mark.parametrize("attacker_ai", [False, True])
@pytest.mark.parametrize("victim", ["beast", "self", "ordinary_ally"])
def test_teamwork_recipient_and_single_attack_lifetime(tmp_path, monkeypatch, automatic, attacker_ai, victim):
    combat, table, mid = table_fight(tmp_path, [TEAMWORK], kit={"starting_kit": KIT},
                                     ask=not automatic, ally_talents=[])
    while table.state(mid)["menu"]["actor_id"] != RIGHT:
        assert act(table, mid, "end")["status"] == "COMMITTED"
    if automatic:
        combat.set_controller_mode(mid, actor_id=LEFT, controller_mode="LOCAL_AUTO")
    engine = combat._load_session(mid).engine
    beast = next(a.entity_id for a in engine.state.actors.values()
                 if a.owner_id == LEFT and ".summon.beast" in a.entity_id)
    target = {"beast": beast, "self": LEFT, "ordinary_ally": ALLY}[victim]
    send = cast_sender(combat, table, mid, "Bi Shou (Dagger) thrown", target=target)
    if attacker_ai:
        combat.set_controller_mode(mid, actor_id=RIGHT, controller_mode="LOCAL_AUTO")
        engine = combat._load_session(mid).engine
        candidate = next(c for c in engine.legal_candidates()
                         if "Bi Shou (Dagger) thrown" in c.display_name and target in c.target_ids)
        original = combat.controller.choose_primary_action
        def choose(context):
            choice = original(context)
            c = next(c for c in context.legal_candidates if c.candidate_id == candidate.candidate_id)
            return choice.model_copy(update={
                "intent": choice.intent.model_copy(update={"candidate_id": c.candidate_id, "target_ids": c.target_ids,
                                                            "option_ids": c.option_ids, "destination": c.destination}),
                "record": choice.record.model_copy(update={"selected_candidate_id": c.candidate_id,
                                                            "selected_option_ids": c.option_ids})})
        monkeypatch.setattr(combat.controller, "choose_primary_action", choose)
        sequence = table.state(mid)["last_sequence"]
        send = lambda answers=(): table.auto_step(mid, sequence, list(answers))
    prompts = commit(send)
    loaded = CombatService(combat.source_root, tmp_path)._load_session(mid)
    engine = loaded.engine
    bonuses = [e for e in engine.events if e.event_type == "MODIFIER_APPLIED"
               and e.source_definition_id == TEAMWORK]
    if victim == "ordinary_ally":
        assert not bonuses
        assert not any(p["reaction"] == "Defensive Teamwork" for p in prompts)
    else:
        assert bonuses and all(e.target_ids == (target,) for e in bonuses)
        assert all(e.payload["expires_on"] == "CONSUMED" for e in bonuses)
        rolled = next(e for e in engine.events if e.event_type == "ATTACK_ROLLED" and target in e.target_ids)
        assert rolled.payload["target_ac"] == engine.state.actors[target].armor_class + 2
        assert not any(m.source_definition_id == TEAMWORK for a in engine.state.actors.values()
                       for m in a.modifiers.values())
        if not automatic:
            assert any(p["reaction"] == "Defensive Teamwork" for p in prompts)
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_attack_ac_scopes_suspend_parents_and_unwind_on_error():
    from combat.ext.attack_defenses import grant, resolving_defenses
    from tests.test_forced_movement_reactions import _engine, REACTOR
    engine = _engine([])
    actor = engine.state.actors[REACTOR]
    parent, child, grandchild = {}, {}, {}
    grant(parent, actor, "test:parent", 2)
    grant(child, actor, "test:child", 3)
    with resolving_defenses(engine, parent):
        assert engine._ac_modifier(actor) == 2
        with resolving_defenses(engine, child):
            assert engine._ac_modifier(actor) == 3
            with resolving_defenses(engine, grandchild):
                assert engine._ac_modifier(actor) == 0
            assert engine._ac_modifier(actor) == 3
        assert engine._ac_modifier(actor) == 2
        with pytest.raises(RuntimeError):
            with resolving_defenses(engine, {}):
                assert engine._ac_modifier(actor) == 0
                raise RuntimeError("resolver aborted")
        assert engine._ac_modifier(actor) == 2
    assert not actor.modifiers

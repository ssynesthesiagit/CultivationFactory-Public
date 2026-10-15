"""C14 F1: real seal/reuse transactions, saved watches, and genesis replay (no live data or browser)."""
import pytest

from combat.ext import ability_lockout
from combat.gate2_runtime_models import ActionIntent
from combat.gate4_context import build_decision_context
from combat.gate4_controller import LocalDeterministicController
from combat.gate4_persistence import Gate4Persistence
from combat.gate4_policy import PolicyLibrary
from tests import test_riders_c2 as C2
from tests.test_riders_c14 import CLOSING, ROOT


def submit(session, name):
    candidate = next(c for c in session.engine.legal_candidates() if c.display_name == name)
    intent = ActionIntent(intent_id=f"review-{candidate.state_version}-{name}", decision_id=candidate.decision_id,
                          candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                          actor_id=candidate.actor_id, target_ids=candidate.target_ids, destination=candidate.destination)
    before = len(session.engine.events)
    session.submit_intent(intent, primary_decision_record=None, reaction_provider=None)
    return session.engine.events[before:]


def turn(session, actor_id):
    for _ in range(4):
        if session.engine.state.current_actor_id == actor_id:
            return
        submit(session, "End turn")
    raise AssertionError("Actor did not get a turn")


def watched_session(tmp_path, attacking=False, attack_count=1):
    """Use an ability, take a Pressure Point, then close its seal on the next turn. All state is committed normally."""
    talent = "TAL_CHAINS_CHAIN_LASH_BASE" if attacking else "TAL_ALCHEMY_CALMING_HEART_PILL"
    ability = "Chain Lash: Reduce Speed" if attacking else "Calming Heart Pill"
    me = C2._pp([CLOSING], dc=-40)
    foe = C2._bundle([talent], actor_id=C2.ATK, weapon="tianxia.mortal.weapon.dao")
    if attacking and attack_count != 1:
        # A compiled two-strike fixture exercises the shared watch contract without changing authority data.
        for action in foe["action_catalog"]:
            if action["display_name"].startswith("Chain Lash:"):
                action["parameters"]["typed"]["effects"][0]["count"] = attack_count
    for bundle in (me, foe):
        bundle["actor_template"]["maximum_hp"] = 500
        bundle["actor_template"]["armor_class"] = 0
    foe["actor_template"]["initiative_bonus"] = 100
    foe["actor_template"]["saving_throws"].update(CON=100, WIS=100)
    persistence = Gate4Persistence(ROOT, tmp_path)
    session = persistence.create_match(match_seed="C14-F1", typed_bundles=(me, foe), roster_setup={
        "primary_actor_ids": [C2.ME, C2.ATK], "team_by_actor": {C2.ME: "team:a", C2.ATK: "team:b"},
        "starting_positions": {C2.ME: {"x": 3, "y": 6}, C2.ATK: {"x": 4, "y": 6}}})
    turn(session, C2.ATK)
    submit(session, ability)
    submit(session, "End turn")
    submit(session, "Touch the Point: Technique-Closing Point")
    submit(session, "Fu (Short Axe) attack")  # apply the first Pressure Point
    submit(session, "End turn")
    submit(session, "End turn")
    submit(session, "Fu (Short Axe) attack")  # now close its seal
    assert ability_lockout.records(session.engine.state.actors[C2.ATK])[0].data["mode"] == "watch"
    assert session.mechanical.verify()["status"] == "PASS"
    session = persistence.load_match(session.match_id)
    submit(session, "End turn")
    assert session.engine.state.current_actor_id == C2.ATK
    if attacking:
        submit(session, "Move to 6,6")  # ranged attack outside melee: no unrelated proximity Disadvantage
    return persistence, session, ability


def modes(events):
    return [e.payload["mode"] for e in events if e.event_type == "ATTACK_ROLLED" and e.actor_id == C2.ATK]


@pytest.mark.parametrize("ai", [False, True], ids=["manual", "automatic-ai"])
def test_attacking_reuse_penalizes_its_first_roll_only_after_reload(tmp_path, ai):
    persistence, session, ability = watched_session(tmp_path, attacking=True)
    if ai:
        engine = session.engine
        policy = PolicyLibrary(ROOT).for_actor(C2.ATK)[0]
        choice = LocalDeterministicController().choose_primary_action(build_decision_context(engine, policy, for_ai=True))
        picked = next(c for c in engine.legal_candidates() if c.candidate_id == choice.intent.candidate_id)
        assert picked.display_name.startswith("Chain Lash:")
        before = len(engine.events)
        session.submit_intent(choice.intent, primary_decision_record=choice.record, reaction_provider=None)
        events = engine.events[before:]
    else:
        events = submit(session, ability)
    assert modes(events) == ["DISADVANTAGE"]
    assert not ability_lockout.records(session.engine.state.actors[C2.ATK])
    assert not [c for c in session.engine.state.actors[C2.ATK].conditions.values()
                if c.condition_id == ability_lockout.ACTIVATION]
    assert session.mechanical.verify()["status"] == "PASS"
    session = persistence.load_match(session.match_id)
    submit(session, "End turn")
    submit(session, "End turn")
    target = session.engine.state.actors[C2.ME].position
    submit(session, f"Move to {target.x + 1},{target.y}")
    assert modes(submit(session, "Dao (Saber / Broadsword) attack")) == ["NORMAL"]
    assert session.mechanical.verify()["status"] == "PASS"


def test_only_first_roll_of_a_multi_attack_reuse_is_penalized(tmp_path):
    _, session, ability = watched_session(tmp_path, attacking=True, attack_count=2)
    assert modes(submit(session, ability)) == ["DISADVANTAGE", "NORMAL"]
    assert session.mechanical.verify()["status"] == "PASS"


def test_non_attacking_reuse_cleans_up_before_commit_reload_and_later_attack(tmp_path):
    persistence, session, ability = watched_session(tmp_path)
    events = submit(session, ability)
    assert not modes(events)
    assert any(e.event_type == "MODIFIER_REMOVED" and e.payload.get("reason") == "ACTIVATION_ENDED" for e in events)
    assert session.mechanical.verify()["status"] == "PASS"
    session = persistence.load_match(session.match_id)
    assert not ability_lockout.records(session.engine.state.actors[C2.ATK])
    assert modes(submit(session, "Dao (Saber / Broadsword) attack")) == ["NORMAL"]
    assert session.mechanical.verify()["status"] == "PASS"


def test_saved_watch_expires_without_penalizing_a_later_activation(tmp_path):
    persistence, session, ability = watched_session(tmp_path, attacking=True)
    submit(session, "End turn")  # start of the seal owner's next turn ends the watch
    assert not ability_lockout.records(session.engine.state.actors[C2.ATK])
    session = persistence.load_match(session.match_id)
    submit(session, "End turn")
    assert modes(submit(session, ability)) == ["NORMAL"]
    assert session.mechanical.verify()["status"] == "PASS"


def test_reuse_cleanup_preserves_an_unrelated_next_attack_modifier():
    from tests.test_riders_c14 import closing_fight

    engine, actor, _ = closing_fight(40)
    engine._add_modifier(actor, "test:independent-penalty", "attack_mode", "SET", "DISADVANTAGE", "NEXT_ATTACK",
                         expires_on="CONSUMED")
    (existing,) = [mid for mid, m in actor.modifiers.items() if m.source_definition_id == "test:independent-penalty"]
    C2._ready(engine, C2.ATK)
    C2._act(engine, "Calming Heart Pill", actor_id=C2.ATK)
    assert set(actor.modifiers) == {existing}
    assert modes(C2._act(engine, "Dao (Saber / Broadsword) attack", actor_id=C2.ATK)) == ["DISADVANTAGE"]

"""Recovery consumers of fallible healing, through service preview/commit/reload.

Compiled setup actions create the zero-HP state and, for stable recovery, an
already-due deadline. They also provide a one-point deferred packet. The actual
death roll, Burial Drum, healing assignment and recovery callers are unmodified.
"""
import copy

import pytest

from combat.ext import life_state, spirit_traditions as st
from combat.gate5_service import CombatService
from test_auto_h3_life import _bundle, DEATHLESS
from test_riders_c8 import ROOT, ME, TG_ALL, MIND_SPIKE, bundle, held
from test_riders_c8_review import service_commit

ENEMY = "actor:factory.c8_recovery_enemy"


@pytest.mark.parametrize("recovery", ["natural20", "stable"])
@pytest.mark.parametrize("restriction,control", [
    (restriction, control) for restriction in ("none", "denied", "halved", "assigned")
    for control in ("MANUAL", "LOCAL_AUTO")
] + [("assignment_declined", "MANUAL")])
def test_recovery_requires_actual_hp_gain_commit_reload(tmp_path, control, recovery, restriction):
    _recovery_case(tmp_path, control, recovery, restriction)


@pytest.mark.parametrize("control", ["MANUAL", "LOCAL_AUTO"])
@pytest.mark.parametrize("failures", [1, 2])
def test_denied_early_natural20_preserves_intervening_damage_or_death_commit_reload(tmp_path, control, failures):
    _recovery_case(tmp_path, control, "natural20", "denied", failures=failures, early=True)


def _recovery_case(tmp_path, control, recovery, restriction, *, failures=1, early=False):
    mine = _bundle(ME, "tianxia.sphere.berserker", [DEATHLESS])
    other = bundle(TG_ALL, actor_id=ENEMY, dc=40 if restriction == "denied" else -40)
    setup = copy.deepcopy(next(a for a in other["action_catalog"] if a["display_name"] == "Mind Spike"))
    setup["source_definition_id"] = "test:c8.recovery_setup"
    setup["display_name"] = "Test recovery setup"
    setup["economy"] = "BONUS_ACTION"
    effects = [{"type": "damage", "flat": mine["actor_template"]["maximum_hp"],
                "damage_types": ["necrotic"], "applies_to": "target"}]
    if recovery == "stable":
        # An already-due persisted deadline isolates the caller without advancing
        # 1d4 minutes (which would let the one-minute Drum expire first).
        effects.extend([
            {"type": "condition", "condition": "deathless_recovery", "applies_to": "target",
             "expires_on": "UNTIL_REMOVED", "condition_data": {"round": 1, "slot": 0}},
            {"type": "stabilize", "applies_to": "target"}])
    if restriction in ("assigned", "assignment_declined"):
        effects.append({"type": "condition", "condition": "deferred_consequence", "applies_to": "target",
                        "expires_on": "UNTIL_REMOVED",
                        "condition_data": {"kind": "damage", "packets": [[1, "NECROTIC"]], "turn": 0,
                                           "source": MIND_SPIKE, "source_actor": ENEMY}})
    setup["parameters"]["typed"]["effects"] = effects
    other["action_catalog"].append(setup)
    other["actor_template"]["action_ids"].append(setup["source_definition_id"])
    if early:
        immediate = copy.deepcopy(setup)
        immediate.update(source_definition_id="test:c8.early_save", display_name="Test early death save", economy="NONE", costs=[])
        immediate["parameters"]["typed"]["effects"] = [{"type": "death_save_now", "applies_to": "target"}]
        other["action_catalog"].append(immediate)
        other["actor_template"]["action_ids"].append(immediate["source_definition_id"])
    service = CombatService(ROOT, tmp_path)
    session = service.persistence.create_match(
        match_seed="C8-RECOVERY-24", maximum_rounds=20, typed_bundles=(mine, other),
        roster_setup={"primary_actor_ids": [ME, ENEMY],
                      "team_by_actor": {ME: "team:a", ENEMY: "team:b"},
                      "starting_positions": {ME: {"x": 6, "y": 6}, ENEMY: {"x": 8, "y": 6}}})
    metadata = {"participant_control_modes": {ME: control, ENEMY: "MANUAL"}}

    def act(name, target=None):
        return service_commit(service, session, metadata, name, target,
                              assign=restriction != "assignment_declined")

    while session.engine.state.current_actor_id != ENEMY:
        act("End turn")
    if restriction in ("denied", "halved"):
        act("Burial Drum")
        act("End turn")
        act("End turn")
    act("Test recovery setup", ME)
    actor = session.engine.state.actors[ME]
    assert actor.current_hp == 0 and actor.life_state == ("STABLE" if recovery == "stable" else "DYING")
    # Compatibility input with accumulated death saves, carried by the existing
    # runtime-control snapshot; no engine class/function or roller is replaced.
    actor.turn_flags[life_state.RECORD] = {"ok": 1, "bad": failures} if recovery == "natural20" else {"ok": 0, "bad": 0}
    # Commit/reload the zero-HP setup before the resolving start-of-turn intent.
    act("Dodge")
    session = service.persistence.load_match(session.match_id)
    assert session.verify()["status"] == "PASS"
    assert session.engine.state.actors[ME].turn_flags[life_state.RECORD]["bad"] == (failures if recovery == "natural20" else 0)
    events, prompts, choices = act("Test early death save", ME) if early else act("End turn")
    success = restriction in ("none", "assignment_declined")
    # Reviewed H86 keeps the recovery boundary but passes a creature that still
    # cannot decide. Successful recovery must retain the player's actual turn.
    assert session.engine.state.current_actor_id == (ENEMY if early or not success else ME)
    if not early and not success:
        assert any(e.event_type == "TURN_STARTED" and e.actor_id == ME for e in events)
        assert any(e.event_type == "TURN_ENDED" and e.actor_id == ME for e in events)
    if recovery == "natural20":
        [save] = [e for e in events if e.event_type == "CHECK_ROLLED" and e.actor_id == ME
                  and e.payload.get("skill") == "Death Saving Throw"]
        assert save.payload["actor"]["natural_result"] == 20
    dead = early and failures == 2
    actor = session.engine.state.actors[ME]
    assert actor.current_hp == int(success)
    assert actor.active is not dead
    assert actor.life_state == (None if success or dead else "DYING" if recovery == "natural20" else "STABLE")
    assert (actor.action_available, actor.bonus_action_available, actor.reaction_available) == (success,) * 3
    assert actor.movement_remaining_ft == (session.engine._effective_speed(actor) if success else 0)
    expected_record = {"ok": 0, "bad": 0} if success or recovery == "stable" else {
        "ok": 1, "bad": failures + int(restriction == "denied")}
    # Actual healing clears the record; denied healing's nested damage adds a failure.
    if success:
        assert life_state.RECORD not in actor.turn_flags
    else:
        assert actor.turn_flags[life_state.RECORD] == expected_record
    if recovery == "stable":
        assert bool(held(actor, life_state.RECOVERY)) is not success
    if restriction in ("denied", "halved"):
        [save] = [e for e in events if e.event_type == "SAVE_ROLLED" and e.actor_id == ME]
        assert save.payload["success"] is (restriction == "halved")
    if restriction in ("assigned", "assignment_declined"):
        [choice] = [r for r in choices if r["reaction_source_id"].endswith("well.deferred_healing")]
        assert choice["reactor_id"] == ME
        assert choice["selection"] == ("USE" if restriction == "assigned" else "DECLINE")
        packets = held(actor, "condition:typed.deferred_consequence")
        if restriction == "assigned" and not early:
            # H86 also runs the skipped turn's end boundary: the fully paid
            # packet arrives and is removed, without dealing damage again.
            assert not packets
            assert any(e.event_type == "CONDITION_REMOVED" and ME in e.target_ids
                       and e.payload.get("condition_id") == "condition:typed.deferred_consequence"
                       and e.payload.get("reason") == "ARRIVED" for e in events)
            assert not any(e.event_type == "DAMAGE_COMMITTED" and ME in e.target_ids
                           and e.source_definition_id == MIND_SPIKE for e in events)
        else:
            [packet] = packets
            assert int(st.data_of(actor, packet).get("paid") or 0) == int(restriction == "assigned")
        assert bool(prompts) is (control == "MANUAL")
    after = actor.model_dump(mode="json")
    session = service.persistence.load_match(session.match_id)
    assert session.engine.state.actors[ME].model_dump(mode="json") == after
    assert session.verify()["status"] == "PASS"

"""Lane probe (MUTUALKO1F27): why does the assigned deferred packet change the
LOCAL_AUTO c8 recovery case? Dumps the fight journal of each step."""
import copy
import traceback

import pytest

from combat.ext import life_state
from combat.gate5_service import CombatService
from test_auto_h3_life import _bundle, DEATHLESS
from test_riders_c8 import ROOT, ME, TG_ALL, MIND_SPIKE, bundle, held
from test_riders_c8_review import service_commit

ENEMY = "actor:factory.c8_recovery_enemy"


def _run(tmp_path, control, recovery, log):
    mine = _bundle(ME, "tianxia.sphere.berserker", [DEATHLESS])
    other = bundle(TG_ALL, actor_id=ENEMY, dc=-40)
    setup = copy.deepcopy(next(a for a in other["action_catalog"] if a["display_name"] == "Mind Spike"))
    setup["source_definition_id"] = "test:c8.recovery_setup"
    setup["display_name"] = "Test recovery setup"
    setup["economy"] = "BONUS_ACTION"
    effects = [{"type": "damage", "flat": mine["actor_template"]["maximum_hp"],
                "damage_types": ["necrotic"], "applies_to": "target"}]
    if recovery == "stable":
        effects.extend([
            {"type": "condition", "condition": "deathless_recovery", "applies_to": "target",
             "expires_on": "UNTIL_REMOVED", "condition_data": {"round": 1, "slot": 0}},
            {"type": "stabilize", "applies_to": "target"}])
    effects.append({"type": "condition", "condition": "deferred_consequence", "applies_to": "target",
                    "expires_on": "UNTIL_REMOVED",
                    "condition_data": {"kind": "damage", "packets": [[1, "NECROTIC"]], "turn": 0,
                                       "source": MIND_SPIKE, "source_actor": ENEMY}})
    setup["parameters"]["typed"]["effects"] = effects
    other["action_catalog"].append(setup)
    other["actor_template"]["action_ids"].append(setup["source_definition_id"])
    service = CombatService(ROOT, tmp_path)
    session = service.persistence.create_match(
        match_seed="C8-PROBE", maximum_rounds=20, typed_bundles=(mine, other),
        roster_setup={"primary_actor_ids": [ME, ENEMY],
                      "team_by_actor": {ME: "team:a", ENEMY: "team:b"},
                      "starting_positions": {ME: {"x": 6, "y": 6}, ENEMY: {"x": 8, "y": 6}}})
    metadata = {"participant_control_modes": {ME: control, ENEMY: "MANUAL"}}

    def act(name, target=None):
        before = len(session.engine.events)
        try:
            events, prompts, choices = service_commit(service, session, metadata, name, target, assign=True)
        except BaseException as exc:  # noqa: BLE001 - probe
            log.append(f"  act {name!r} RAISED {type(exc).__name__}: {exc}")
            log.append(traceback.format_exc())
            raise
        new = session.engine.events[before:]
        log.append(f"  act {name!r}: {[(e.event_type, e.actor_id, (e.payload or {}).get('rider') or '') for e in new]}")
        log.append(f"    choices={[(c['reaction_source_id'], c['selection'], c['option_ids']) for c in choices]}"
                   f" prompts={[p.reaction_source_id for p in prompts]}")
        me = session.engine.state.actors[ME]
        log.append(f"    ME hp={me.current_hp} life={me.life_state} active={me.active}"
                   f" conds={sorted(c.condition_id for c in me.conditions.values())}"
                   f" terminal={session.engine.state.terminal_result}"
                   f" current={session.engine.state.current_actor_id}")
        return events, prompts, choices

    log.append(f"== control={control} recovery={recovery} ==")
    try:
        while session.engine.state.current_actor_id != ENEMY:
            act("End turn")
        act("Test recovery setup", ME)
        session.engine.state.actors[ME].turn_flags[life_state.RECORD] = {"ok": 1, "bad": 1}
        act("Dodge")
        session = service.persistence.load_match(session.match_id)
        act("End turn")
        me = session.engine.state.actors[ME]
        log.append(f"  FINAL ME hp={me.current_hp} life={me.life_state} active={me.active}"
                   f" flags={me.turn_flags.get(life_state.RECORD)}"
                   f" conds={sorted(c.condition_id for c in me.conditions.values())}"
                   f" terminal={session.engine.state.terminal_result}")
    except BaseException as exc:  # noqa: BLE001 - probe
        log.append(f"  SCENARIO ABORTED: {type(exc).__name__}: {exc}")


@pytest.mark.parametrize("control,recovery", [("LOCAL_AUTO", "natural20"), ("MANUAL", "natural20"),
                                              ("LOCAL_AUTO", "stable"), ("MANUAL", "stable")])
def test_probe_team_actions(tmp_path, control, recovery):
    log = []
    _run(tmp_path, control, recovery, log)
    pytest.fail("\n".join(log), pytrace=False)

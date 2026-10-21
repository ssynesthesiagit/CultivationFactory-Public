"""Wake uses the same rest-recoverable resource as other limited abilities.

The synthetic action records the use recovery from an already completed rest;
it is not an instant rest command or a new production combat option.
"""
import copy

import pytest

from combat.ext import foundation_sacred_body as body
from tests.test_a2r11_foundations import (
    FIGHTER, SACRED_BARE, _sacred, _service_fight, _until, _play, _engine,
)


def _offered(engine, source):
    return next((c.candidate_id for c in engine.legal_candidates()
                 if c.source_definition_id == source), None)


@pytest.mark.parametrize("rest_kind", ["short", "long"])
def test_wake_native_rest_use_recovers_on_same_creature_after_table_reload(
        tmp_path, monkeypatch, rest_kind):
    rest_source = "action:test.completed_" + rest_kind + "_rest"

    def prepare(bundles):
        owner = next(b for b in bundles if b["actor_id"] == FIGHTER)
        wake = next(a for a in owner["action_catalog"]
                    if a["source_definition_id"] == body.WAKE_ACTION)
        recovery = copy.deepcopy(wake)
        recovery.update(source_definition_id=rest_source, costs=[],
                        display_name="Record completed rest", economy="ACTION")
        recovery["parameters"] = {"typed": {
            "source": rest_source, "numbers": {}, "effects": [{
                "type": "gain_resource", "applies_to": "self",
                "resource_id": body.WAKE_USES, "flat": 1,
            }],
        }}
        owner["action_catalog"].append(recovery)
        owner["actor_template"]["action_ids"].append(rest_source)

    combat, table, mid = _service_fight(
        tmp_path, monkeypatch, _sacred("Perfected"), SACRED_BARE, prepare=prepare)
    _until(table, mid, FIGHTER)
    cold = _engine(combat, mid)
    actor = cold.state.actors[FIGHTER]
    assert actor.resources[body.WAKE_USES] == actor.resource_maximums[body.WAKE_USES] == 1
    _play(table, mid, _offered(cold, body.WAKE_ACTION))
    assert _engine(combat, mid).state.actors[FIGHTER].resources[body.WAKE_USES] == 0

    # More Pulse and a refreshed Bonus Action do not reset a spent rest use.
    _play(table, mid, table.state(mid)["menu"]["end_turn"])
    _until(table, mid, FIGHTER)
    cold = _engine(combat, mid)
    assert cold.state.actors[FIGHTER].resources[body.PULSE] >= 1
    assert not _offered(cold, body.WAKE_ACTION)

    # Commit the completed rest's native use recovery, then cold-load the
    # same match and same creature. No fresh fight or turn-flag deletion.
    _play(table, mid, _offered(cold, rest_source))
    cold = _engine(combat, mid)
    assert cold.state.actors[FIGHTER].resources[body.WAKE_USES] == 1
    assert _offered(cold, body.WAKE_ACTION)
    _play(table, mid, _offered(cold, body.WAKE_ACTION))
    cold = _engine(combat, mid)
    assert cold.state.actors[FIGHTER].resources[body.WAKE_USES] == 0
    assert not _offered(cold, body.WAKE_ACTION)
    payments = [e for e in cold.events if e.event_type == "RESOURCE_SPENT"
                and e.actor_id == FIGHTER
                and e.payload.get("resource_id") == body.WAKE_USES]
    assert len(payments) == 2

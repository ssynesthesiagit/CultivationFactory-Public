"""Internal Echo detonates after the target's first cumulative 10 feet of willing movement."""
from tests.test_riders_c7 import FOE, ME, _typed_foe, bundle, fight, turn, use
from combat import ext
from combat.ext import drum_body
from combat.gate2_runtime_models import Position

DRUM = "tianxia.subpath.body.heaven_thunder_drum_body.feature."
ECHOING = "condition:typed.echoing"


def _echoed():
    engine = fight(bundle([DRUM + "internal_echo"]), foe=_typed_foe(), foe_at=(10, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    engine._apply_condition(foe, ECHOING, DRUM + "internal_echo", ME, expires_on="UNTIL_REMOVED",
                            data={"pb": 4, "save_dc": 50, "cl": 18})
    turn(engine, FOE)
    return engine, foe


def _echo(foe):
    return any(c.condition_id == ECHOING for c in foe.conditions.values())


def _thunder(engine):
    return [e for e in engine.events if e.event_type == "DAMAGE_COMMITTED" and e.payload.get("damage_type") == "THUNDER"]


def test_ten_feet_of_willing_movement_detonates_the_echo():
    engine, foe = _echoed()
    hp = foe.current_hp
    use(engine, "Move to 12,6", actor_id=FOE)  # 10 feet
    assert not _echo(foe) and len(_thunder(engine)) == 1 and foe.current_hp < hp


def test_less_than_ten_feet_leaves_the_echo_and_a_second_step_completes_it():
    engine, foe = _echoed()
    use(engine, "Move to 11,6", actor_id=FOE)  # 5 feet
    assert _echo(foe) and not _thunder(engine)
    use(engine, "Move to 12,6", actor_id=FOE)  # 5 more: ten in all
    assert not _echo(foe) and len(_thunder(engine)) == 1


def test_forced_movement_does_not_count():
    engine, foe = _echoed()
    path = [{"x": 10, "y": 6, "z": 0}, {"x": 11, "y": 6, "z": 0}, {"x": 12, "y": 6, "z": 0}]
    engine._append_event("MOVEMENT_COMMITTED", "test:shove", actor_id=FOE, payload={"path": path, "forced": True})
    assert _echo(foe) and not _thunder(engine)  # ten feet, but pushed: it does not count
    use(engine, "Move to 11,6", actor_id=FOE)  # the same ten feet, walked, counts: 5 ft
    use(engine, "Move to 12,6", actor_id=FOE)  # 5 more
    assert not _echo(foe) and len(_thunder(engine)) == 1

def test_movement_counter_is_recorded_as_a_condition_update_for_replay():
    # Finding 1: the running 10-ft total must be a recorded CONDITION_UPDATED, or Gate 3 replay cannot reproduce the post-state.
    engine, foe = _echoed()
    use(engine, "Move to 11,6", actor_id=FOE)  # 5 ft
    updates = [e for e in engine.events if e.event_type == "CONDITION_UPDATED" and FOE in (e.target_ids or ())]
    assert updates and updates[-1].payload["data"]["moved_ft"] == 5
    held = next(c for c in foe.conditions.values() if c.condition_id == ECHOING)
    assert held.data["moved_ft"] == 5  # the live instance matches the recorded data


def test_movement_detonation_damage_is_a_top_level_packet_not_nested_in_an_event_hook(monkeypatch):
    # Finding 2: the 3d8 Thunder must not be resolved inside an event hook, where its own riders do not run.
    seen = []

    def probe(engine, event_type, kwargs):
        if event_type == "DAMAGE_COMMITTED" and (kwargs.get("payload") or {}).get("damage_type") == "THUNDER":
            seen.append(bool(getattr(engine, "_ext_in_event", False)))

    monkeypatch.setitem(ext._HOOKS, "event", [*ext._HOOKS.get("event", []), probe])
    engine, foe = _echoed()
    use(engine, "Move to 12,6", actor_id=FOE)  # 10 ft detonates
    assert seen == [False]


def test_taking_a_reaction_detonates_the_echo_and_leaves_no_gm_rider():
    # Finding 3: the Reaction trigger is automated (reaction_spend, at commit), not a GM rider in riders_c7.json.
    from pathlib import Path
    engine, foe = _echoed()
    hp = foe.current_hp
    drum_body.echo_detonates_on_reaction(engine, foe, {}, True)
    assert not _echo(foe) and len(_thunder(engine)) == 1 and foe.current_hp < hp
    assert any(e.event_type == "CONDITION_REMOVED" and (e.payload or {}).get("reason") == "DETONATED" for e in engine.events)
    assert drum_body.echo_detonates_on_reaction in ext._HOOKS["reaction_spend"]
    riders = Path(__file__).resolve().parents[1] / "authority/typed_mechanics/reviewed_final.d/riders_c7.json"
    assert "Internal Echo (GM)" not in riders.read_text()

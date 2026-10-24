"""End-to-end regression: a real recurring typed damage tick is not a fresh blow.

The Force plug-in's Ten Thousand Rebounds answers the first physical blow each hostile creature lands. A
recurring typed effect (``combat/ext/ongoing_effects.py``) delivers its turn-start damage through the same
typed executor, so this test drives that actual path: a typed ongoing condition is applied to the armed
owner, the engine's turn-start hook delivers its damage, and the damage packet is read *while it is being
committed* (an event subscriber, the same place the Force hook runs). A tick must carry
``damage_origin: "ongoing"`` at delivery time, leave the armed response untouched and cause no retaliation;
a fresh typed blow from the same creature must then answer and spend that creature's one response.
"""

from combat import ext
from combat.ext import force
from combat.typed_executor import Context, run_effects
from tests.test_riders_lane10 import _rebounds_table

ONGOING = "condition:typed.test_ongoing_burn"


def test_a_real_recurring_tick_does_not_spend_rebounds_and_a_fresh_blow_still_answers(tmp_path, monkeypatch):
    combat, table, mid, send, commit, enemy, second, owner_id, candidate = _rebounds_table(tmp_path)
    engine = combat._load_session(mid).engine
    owner = engine.state.actors[owner_id]
    foe = engine.state.actors[enemy]
    # The hostile creature's own compiled action is the recurring effect's source, exactly as an
    # applied ongoing row records it.
    source_id = next(action_id for action_id in engine.action_catalog if enemy in action_id)
    action = engine.action_catalog[source_id]

    force._arm(engine, owner, "")
    armed = force._armed(engine, owner)
    assert armed is not None and armed["spent"] == "", "Ten Thousand Rebounds is armed and nothing has answered"

    engine._apply_condition(owner, ONGOING, source_id, foe.entity_id, expires_on="UNTIL_REMOVED",
                            data={"rule": {}, "speed_delta": 0, "numbers": {"save_dc": 10},
                                  "ongoing_effects": [{"type": "damage", "applies_to": "target",
                                                       "dice": {"count": 2, "sides": 8},
                                                       "damage_types": ["slashing"]}]})

    # Watch the packet from inside event delivery, which is where combat/ext/force.py reads it.
    delivered = []

    def record(engine, event_type, kwargs):
        payload = kwargs.get("payload") or {}
        if event_type == "DAMAGE_COMMITTED" and payload.get("damage_origin") == "ongoing":
            delivered.append(dict(payload))

    monkeypatch.setitem(ext._HOOKS, "event", [*ext._HOOKS.get("event", []), record])

    owner_hp = owner.current_hp
    foe_hp = foe.current_hp
    before = len(engine.events)
    ext.run("turn_start", engine, owner)

    ticks = [event for event in engine.events[before:]
             if event.event_type == "DAMAGE_COMMITTED" and event.actor_id == foe.entity_id
             and owner.entity_id in event.target_ids]
    assert ticks, "the recurring effect really dealt physical damage"
    assert owner.current_hp < owner_hp, "the tick landed on the armed owner"
    assert delivered, "the DAMAGE_COMMITTED packet carried damage_origin to its subscribers at delivery time"
    assert delivered[0]["damage_type"].upper() == "SLASHING"
    assert foe.current_hp == foe_hp, "a recurring tick is not a fresh blow, so it causes no retaliation"
    assert force._armed(engine, owner)["spent"] == "", "and it does not spend the once-per-creature response"

    # A fresh typed blow from the same creature is a fresh blow and must answer.
    fresh = Context(engine, foe, action, None,
                    {"numbers": {}, "duration": {"kind": "instant"}, "effects": []}, [owner], owner, {})
    run_effects(fresh, [{"type": "damage", "applies_to": "target", "flat": 4,
                         "damage_types": ["slashing"]}])
    assert foe.current_hp < foe_hp, "the fresh blow is answered"
    assert foe.entity_id in force._armed(engine, owner)["spent"].split(), \
        "and only the fresh blow spends that creature's one response"

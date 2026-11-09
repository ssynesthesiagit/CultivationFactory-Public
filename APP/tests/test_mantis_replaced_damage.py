"""A replaced hit suppresses generic attached damage, not its other hit effects."""
from copy import deepcopy

import pytest

from combat import ext
from tests.mantis_native_support import DECLINE, FOE, OWNER, hit, native, reload


@pytest.mark.parametrize("light", [False, True])
def test_generic_attached_riders_follow_each_hits_normal_damage_policy(tmp_path, monkeypatch, light):
    # Synthetic public action data exercises ordinary typed dispatch, not an
    # ability-specific callback or a fabricated runtime ownership receipt.
    def attach_riders(action, info):
        if action.owner_id != OWNER or ".natural." not in action.source_definition_id:
            return None
        typed = deepcopy(action.parameters.get("typed") or {})
        typed["duration"] = {"kind": "minutes", "value": 1}
        for attack in typed.get("effects", []):
            if attack.get("type") == "attack":
                attack.setdefault("on_hit", []).extend([
                    {"type": "damage", "damage_bonus_packet": True, "dice": "1d4", "damage_types": ["FIRE"],
                     "damage_label": "Attached normal damage"},
                    {"type": "condition", "condition": "poisoned", "applies_to": "target",
                     "expires_on": "END_OF_SOURCE_NEXT_TURN"},
                    {"type": "damage", "damage_bonus_packet": True, "dice": "1d4", "damage_types": ["COLD"],
                     "damage_label": "Explicit replacement exception",
                     "applies_without_normal_damage": True},
                ])
        typed["effects"].insert(0, {
            "type": "extra_damage", "deferred": True, "dice": "1d4",
            "damage_types": ["LIGHTNING"], "damage_label": "Registered hit bonus",
            "evidence": "Once per turn when you hit with an unarmed strike, deal extra damage.",
        })
        return action.model_copy(update={"parameters": {**action.parameters, "typed": typed}})

    ext.effects()
    monkeypatch.setitem(ext._HOOKS, "compile_action",
                        [*ext.subscribers("compile_action"), attach_riders])
    combat, table, mid = native(tmp_path, cl=6)
    picks = {**DECLINE, "choice:needle.mantis_hooks_light": "light" if light else None}
    hit(combat, table, mid, picks=picks)
    engine = reload(tmp_path, mid)
    attacks = [event for event in engine.events
               if event.event_type == "ATTACK_ROLLED" and event.actor_id == OWNER
               and event.payload["provisional_hit"]]
    damage = [event for event in engine.events
              if event.event_type == "DAMAGE_COMMITTED" and event.actor_id == OWNER
              and event.target_ids == (FOE,)]
    assert attacks and any(c.condition_id.endswith(".poisoned")
                          for c in engine.state.actors[FOE].conditions.values())
    assert sum(e.payload["damage_type"] == "COLD" for e in damage) == len(attacks)
    assert sum(e.payload["damage_type"] == "FIRE" for e in damage) == len(attacks) - int(light)
    assert sum(e.payload["damage_type"] == "LIGHTNING" for e in damage) == int(len(attacks) > int(light))
    if light:
        # Later strikes in this same Attack action regain their normal riders.
        assert next(e.payload["reduced_to"] for e in damage) == 10
        assert sum(not roll.dice for roll in engine.rolls
                   if roll.actor_id == OWNER and roll.reason.startswith("DAMAGE:")) == 1

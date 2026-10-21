"""Regressions for afflictions applied by native carrier effects."""
from types import SimpleNamespace

from combat.ext import adaptations as adaptive


def test_new_affliction_carrier_can_differ_from_failed_save_source():
    carrier = SimpleNamespace(condition_id="condition:typed.poisoned", applied_sequence=12,
                              source_definition_id="tianxia.subpath.qi.poison_cultivator.feature.poison_touch",
                              source_actor_id="attacker")
    stale = SimpleNamespace(condition_id="condition:typed.blinded", applied_sequence=8,
                             source_definition_id="save", source_actor_id="attacker")
    foreign = SimpleNamespace(condition_id="condition:typed.frightened", applied_sequence=13,
                              source_definition_id="other", source_actor_id="other-actor")
    subject = SimpleNamespace(conditions={"carrier": carrier, "stale": stale, "foreign": foreign})
    # The failed save's own printed effects must name the affliction; the carrier
    # that actually applies it may still be a different feature.
    typed = {"effects": [{"type": "save", "ability": "con",
                          "on_fail": [{"type": "condition", "condition": "poisoned"}]}]}
    ctx = SimpleNamespace(damage_cache={"adapt_save_start": 10}, source="save", typed=typed,
                          actor=SimpleNamespace(entity_id="attacker"))

    assert adaptive._new_affliction_carriers(ctx, subject) == [carrier]


def test_affliction_ending_bonus_is_scoped_to_recorded_carrier(monkeypatch):
    actor = SimpleNamespace(entity_id="owner", proficiency_bonus=4)
    engine = SimpleNamespace(state=SimpleNamespace(actors={"owner": actor}))
    condition = SimpleNamespace(condition_id="condition:typed.poisoned",
                                source_definition_id="poison-touch-carrier",
                                source_actor_id="attacker",
                                data={"origin_save": {}}, instance_id="condition-1")
    row = {"condition": "poisoned", "source": "poison-touch-carrier", "by": "attacker"}
    monkeypatch.setattr(adaptive, "active_records", lambda *_args: [row])
    roll = SimpleNamespace(actor_id="owner", reason="SAVE:CONSTITUTION")

    with adaptive.ending_save_scope(engine, actor, condition):
        assert adaptive.end_the_affliction(engine, roll, None) == {
            "source_id": adaptive.PREFIX + "meridians_remember_affliction", "bonus": 4
        }
        # Same condition name from a different carrier is not this record.
        monkeypatch.setattr(adaptive, "active_records", lambda *_args: [
            {"condition": "poisoned", "source": "different-carrier", "by": "attacker"}
        ])
        assert adaptive.end_the_affliction(engine, roll, None) is None


def test_repeat_candidates_retain_carrier_source_and_allow_paid_repeat():
    condition = SimpleNamespace(condition_id="condition:typed.poisoned",
                                source_definition_id="poison-touch-carrier",
                                source_actor_id="attacker", data={"origin_save": {"ability": "CON", "dc": 15}})
    row = {"condition": "poisoned", "source": "poison-touch-carrier", "by": "attacker"}
    actor = SimpleNamespace(conditions={"poison": condition})
    assert adaptive._repeatable_afflictions(actor, [row]) == [("poison", condition, row)]
    assert adaptive._repeatable_afflictions(actor, [
        {"condition": "poisoned", "source": "save-action", "by": "attacker"}
    ]) == []
    condition.data["repeat_save"] = {"ability": "CON", "when": "end"}
    assert adaptive._repeatable_afflictions(actor, [row]) == []

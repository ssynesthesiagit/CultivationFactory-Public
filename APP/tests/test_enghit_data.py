"""Relevant-only contract checks for authored later-hit data, not ability rules."""
from copy import deepcopy
from dataclasses import dataclass
from types import SimpleNamespace as NS

import pytest

from combat import typed_executor as te
from combat.factory_compiler import _does_something, _expected_damage
from combat.on_hit_data import seal_on_hit

SOURCE = "synthetic:later_hit"
TEXT = "Display description without a trigger."


def grammar(**changes):
    return {"trigger": "damage", "limit": "next", "bound": True,
            "named": False, "clause": "", "attach_to_attack": False, **changes}


def context(effect):
    actor = NS(entity_id="owner", modifiers={}, turn_flags={}, turns_started=1)
    target = NS(entity_id="target")
    typed = {"effects": [effect], "duration": {"kind": "rounds", "amount": 1}}
    action = NS(source_definition_id=SOURCE, display_name="Synthetic bonus", parameters={"typed": typed})
    engine = NS(state=NS(actors={"owner": actor}, current_actor_id="owner",
                         round_number=1, current_slot_index=0),
                action_catalog={SOURCE: action}, events=[])
    engine._append_event = lambda *args, **kwargs: engine.events.append((args, kwargs))
    def add_modifier(subject, source, field, operation, value, scope, **kwargs):
        subject.modifiers["bonus"] = NS(source_definition_id=source, target_field=field, value=value, **kwargs)
    engine._add_modifier = add_modifier
    return te.Context(engine, actor, action, None, typed, [target], target)


def test_seal_preserves_authored_objects_and_null_in_all_containers():
    authored = grammar()
    explicit = {"type": "extra_damage", "deferred": True, "evidence": TEXT, "on_hit_bonus": authored}
    disabled = {"type": "extra_damage", "deferred": True,
                "evidence": "The next time you hit, add damage.", "on_hit_bonus": None}
    immediate = {"type": "extra_damage"}
    rows = {"synthetic": {"effects": [{"type": "attack", "on_hit": [explicit]}],
                          "options": [{"effects": [disabled]}],
                          "modifier": {"effects": [immediate]}}}
    seal_on_hit(rows)
    assert explicit["on_hit_bonus"] is authored
    assert disabled["on_hit_bonus"] is None
    assert immediate["on_hit_bonus"] is None
    before = deepcopy(rows)
    seal_on_hit(rows)
    assert rows == before


@pytest.mark.parametrize("consumer", ["damage", "register", "later_hit", "menu", "estimate"])
def test_missing_field_fails_loud_with_type_and_source(consumer):
    effect = {"type": "extra_damage", "deferred": True, "evidence": TEXT}
    ctx = context(effect)
    ctx.actor.modifiers["bonus"] = NS(source_definition_id=SOURCE, target_field="typed_on_hit", value="|" + TEXT)
    calls = {
        "damage": lambda: te.block_damage(ctx, effect),
        "register": lambda: te._register_on_hit(ctx, effect),
        "later_hit": lambda: te._on_hit_bonuses(ctx, ctx.target, {}, ""),
        "menu": lambda: _does_something([effect], source=SOURCE),
        "estimate": lambda: _expected_damage([effect], {}, source=SOURCE),
    }
    with pytest.raises(ValueError, match=f"extra_damage missing required on_hit_bonus field.*{SOURCE}"):
        calls[consumer]()


@dataclass
class DamageContext:
    source_id: str


@pytest.mark.parametrize("trigger,limit,named,attached,damage_only,method,expected", [
    ("damage", "next", False, False, True, "", 1),
    ("hit", None, False, True, True, "", 0),
    ("hit", "once_per_turn", False, True, False, "", 1),
    ("hit", "once_per_own_turn", True, True, False, "Synthetic method", 1),
    ("hit", None, False, True, False, "Synthetic method", 0),
    ("damage", None, False, False, True, "", 2),
])
def test_registration_compilation_and_later_hits_use_authored_data(
        monkeypatch, trigger, limit, named, attached, damage_only, method, expected):
    effect = {"type": "extra_damage", "deferred": True, "flat": 7, "evidence": TEXT,
              "on_hit_bonus": grammar(trigger=trigger, limit=limit, named=named, attach_to_attack=attached)}
    ctx = context(effect)
    monkeypatch.setattr(te.Context, "expires_on", lambda self: "END_OF_CURRENT_TURN")
    te._register_on_hit(ctx, effect)
    assert ctx.actor.modifiers["bonus"].value == "target|" + TEXT
    assert _does_something([effect], source=SOURCE)
    assert _expected_damage([effect], {}, source=SOURCE) == 7

    packets = []
    monkeypatch.setattr(te, "block_damage", lambda child, row: packets.append((child, row)))
    ctx.attack_damage_context = DamageContext("strike")
    # Binding is data-driven even though the display description names no target.
    te._on_hit_bonuses(ctx, NS(entity_id="bystander"), {}, "", damage_only=damage_only, method_name=method)
    assert not packets
    for _ in range(2):
        te._on_hit_bonuses(ctx, ctx.target, {}, "", damage_only=damage_only, method_name=method)
    assert len(packets) == expected
    for child, row in packets:
        assert bool(child.attack_damage_context) is attached
        assert row["deferred"] is False and row["flat"] == 7
    if limit == "once_per_own_turn":
        ctx.actor.turn_flags.clear()
        ctx.engine.state.current_actor_id = "someone_else"
        te._on_hit_bonuses(ctx, ctx.target, {}, "", method_name=method)
        assert len(packets) == expected
    # An authored null opts out even if the prose looks like a trigger.
    disabled = {**effect, "on_hit_bonus": None, "evidence": "Once per turn when you hit, deal extra damage."}
    assert not _does_something([disabled], source=SOURCE)
    assert _expected_damage([disabled], {}, source=SOURCE) == 0

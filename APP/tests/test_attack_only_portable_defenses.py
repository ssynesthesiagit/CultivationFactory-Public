"""Portable attacks share declaration benefits without a turn-wide defense."""
import pytest

from combat.ext.attack_defenses import grant_resistance
from tests.test_lock_choices import install
from tests.test_c3ar_runtime_executability import adapter, bundle, runtime_package, runtime_engine, req, SOURCE_ACTOR_ID


@pytest.mark.parametrize("action", ["action:core.unarmed_strike", "action:fire.flame_lash", "action:fire.ignite"])
@pytest.mark.parametrize("hit", [False, True])
def test_portable_declared_resistance_ends_with_its_attack(monkeypatch, bundle, action, hit):
    engine = runtime_engine(bundle, seed="LOCK4-PORTABLE")
    target = engine.state.actors["dummy:target"]
    target.armor_class = 0 if hit else 1000
    engine.typed_actor_ids = {target.entity_id}
    engine.typed_passive_rows = {target.entity_id: []}
    engine.typed_reaction_rows = {}

    def defense(engine, attacker, target, intent, context):
        grant_resistance(context["attack_spec"], target, "test:attack_defense")
        return {"source_id": "test:attack_defense", "target_id": target.entity_id, "cover_bonus": 0}

    install(monkeypatch, "retarget_attack", defense)
    options = {"action:fire.flame_lash": ("NO_MOVEMENT",), "action:fire.ignite": ("INCREASE_BURN",)}.get(action, ())
    before, hp = len(engine.events), target.current_hp
    engine.execute_action(req(action, target_id=target.entity_id, option_ids=options))
    events = engine.events[before:]
    rolls = [e for e in events if e.event_type == "ATTACK_ROLLED"]
    assert len(rolls) == 1 and rolls[0].payload["provisional_hit"] == hit
    damage = [e for e in events if e.event_type == "DAMAGE_COMMITTED"]
    if hit:
        total = 2 if action == "action:core.unarmed_strike" else next(e.payload["total"] for e in events if e.event_type == "DAMAGE_ROLLED") + 3
        assert len(damage) == 1 and damage[0].payload["hp_damage"] == total // 2
        assert hp - target.current_hp == total // 2
    else:
        assert not damage and target.current_hp == hp
    hp = target.current_hp
    engine._commit_damage(target, 7, "PIERCING", action, SOURCE_ACTOR_ID, None, reaction_depth=0)
    assert hp - target.current_hp == 7

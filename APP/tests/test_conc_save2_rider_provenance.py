"""CONCSAVE2: a rider added to a confirmed hit keeps that hit's attack provenance.

Bloodletting Strike (combat/ext/blood_riders.py) adds its damage to the triggering hit. The
child Context must carry the hit's AttackDamage so the packet joins that attack's one
Concentration save instead of making a separate immediate save.
"""

from combat.damage_context import AttackDamage
from combat.gate2_runtime_models import ActionDefinition, EconomyKind
from combat.typed_executor import Context
from tests.test_concsave1_attached_concentration import ME, _engine


def test_hit_child_keeps_the_hit_roll_identity_and_action_source():
    engine, me, foe = _engine()
    action = ActionDefinition(source_definition_id="action:iron_fist", display_name="Iron Fist", owner_id=me.entity_id,
                              economy=EconomyKind.ACTION, resolution_kind="TYPED", target_kind="HOSTILE_ENTITY")
    ctx = Context(engine, me, action, None, {}, [foe], foe, {})
    ctx.attack_damage_context = AttackDamage(source_id="action:iron_fist", attacker_id=me.entity_id, target_id=foe.entity_id,
                                             attack_index=1, roll_id="roll:hit", natural_result=15, total=15, critical=False)
    child = ctx.on_hit_context(foe, damage_cache={})
    assert child.attack_damage_context is not None
    assert child.attack_damage_context.roll_id == "roll:hit"
    assert child.attack_damage_context.source_id == child.damage_source == "action:iron_fist"
    assert child.attack_damage_context.attacker_id == me.entity_id
    assert child.attack_damage_context.target_id == foe.entity_id


def test_standalone_context_has_no_hit_provenance_to_inherit():
    engine, me, foe = _engine()
    action = ActionDefinition(source_definition_id="action:iron_fist", display_name="Iron Fist", owner_id=me.entity_id,
                              economy=EconomyKind.ACTION, resolution_kind="TYPED", target_kind="HOSTILE_ENTITY")
    ctx = Context(engine, me, action, None, {}, [foe], foe, {})
    assert ctx.attack_damage_context is None
    assert ctx.on_hit_context(foe, damage_cache={}).attack_damage_context is None

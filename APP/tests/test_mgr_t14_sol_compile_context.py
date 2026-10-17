"""Compilation hooks tolerate the documented compile_action context."""
from combat.ext.mgr_t14_poison_touch import receipts
from combat.ext.mantra_foundation import provenance
from combat.gate2_runtime_models import ActionDefinition, EconomyKind


def action():
    return ActionDefinition(
        source_definition_id="action:test.typed",
        display_name="Test technique",
        owner_id="actor:test",
        economy=EconomyKind.ACTION,
        resolution_kind="TYPED",
        target_kind="ANY_CREATURE",
        parameters={"typed": {"source": "test.technique", "effects": [], "riders": []}},
    )


def test_poison_touch_compile_hook_accepts_documented_context_without_activation_rows():
    compiled = receipts(action(), {
        "owned_ids": ["tianxia.subpath.qi.poison_cultivator.feature.poison_touch"],
        "powering": {},
        "primary": "qi",
    })
    assert compiled.parameters["typed"]["known_damage_features"] == []


def test_foundation_mantra_compile_hook_accepts_documented_context_without_activation_rows():
    compiled = provenance(action(), {
        "owned_ids": ["tianxia.subpath.qi.mantra_cultivator.feature.three_foundation_mantras"],
    })
    assert compiled.parameters["typed"]["known_damage_features"] == []

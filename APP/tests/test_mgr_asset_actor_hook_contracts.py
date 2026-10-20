"""Public contract guard for shared source-profiled asset actor hooks."""
from combat import ext


def test_asset_actor_shared_hooks_document_arguments_returns_and_default_behavior():
    contract = ext.__doc__ or ""
    hooks = {
        "activation_effects_resolved": "(ctx, receipt) -> None",
        "activation_settlement": "(ctx, receipt) -> None",
        "summon_catalog": "(table, context) -> replacement table | None",
        "summon_source_numbers": "(numbers, context) -> replacement numbers | None",
        "journey_combat_setup": "(session, actor_id) -> dict | None",
        "attack_damage_type_override": "(ctx, effect, target, kinds, strike_index)",
    }
    for name, signature in hooks.items():
        assert name in contract
        assert signature in contract
    section = contract.split("Asset actor runtime seams", 1)[1].split(
        "Background acquisition transport", 1
    )[0]
    assert "No subscribers means no changes" in section
    assert "No provider" in section
    assert "None leaves" in section

"""Attack-action continuation text is distinct from free attacks."""
from combat.ext.special_attacks import replacement_actions
from combat.gate2_runtime_models import ActionDefinition
from combat.tabletop import auto_buttons
from tests.test_factory_combat_compiler import _weapons_of


def test_thrown_remaining_attack_button_names_attack_action():
    bundle, weapons = _weapons_of(["tianxia.mortal.weapon.bi_shou"])
    base = ActionDefinition.model_validate(weapons["bi_shou#thrown"])
    info = {"actor_id": base.owner_id, "actions": [base], "passives": [{"block": "extra_attack", "attacks": 2}]}
    rows = replacement_actions(info)
    remaining = next(a for a in rows if a.parameters.get("attack_action_rest"))
    buttons = auto_buttons({"action_catalog": [remaining.model_dump(mode="json")]}, {})
    text = buttons[0]["description"]
    assert "part of" in text and "Attack action" in text and "Throw it" in text
    free = remaining.model_copy(update={"parameters": {**base.parameters}, "economy": remaining.economy})
    free_text = auto_buttons({"action_catalog": [free.model_dump(mode="json")]}, {})[0]["description"]
    assert "part of the Attack action" not in free_text

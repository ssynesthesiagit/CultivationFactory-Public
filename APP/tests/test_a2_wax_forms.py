"""Paid Living Wax Form transitions use real service commits and cold reloads."""
import pytest

from combat.ext.states import PREFIX, active
from tests.test_r5i_integration import PLAYER, act, candidate, check_reload, fixture, turn

FEATURE = "TAL_WAX_LIVING_WAX_FORM"
NAMES = tuple("living_wax_form_" + name for name in ("soft_body", "set_body", "wick_body"))


def current(engine, actor):
    return active(engine, actor, *NAMES)


@pytest.mark.parametrize("first,second", [("Soft Body", "Set Body"), ("Set Body", "Wick Body"), ("Wick Body", "Soft Body")])
def test_paid_change_is_exclusive_and_does_not_refresh_lifetime(tmp_path, first, second):
    combat, table, mid = fixture(tmp_path, [FEATURE])
    turn(table, mid, PLAYER)
    engine = combat._load_session(mid).engine
    assert not any(c.display_name.startswith("Change Living Wax Form:") for c in engine.legal_candidates())
    before = engine.state.actors[PLAYER].resources["resource:core.qi"]
    assert act(table, mid, candidate(combat, mid, "Living Wax Form: " + first))["status"] == "COMMITTED"
    engine = check_reload(combat, mid, tmp_path)
    assert not any(z.active and FEATURE in z.source_definition_id for z in engine.state.zones.values()), \
        "Wick Body creates candlelight only after its hit reaction"
    deadline = current(engine, engine.state.actors[PLAYER]).expires_on
    assert act(table, mid, table.state(mid)["menu"]["end_turn"])["status"] == "COMMITTED"
    turn(table, mid, PLAYER)
    assert not any(c.display_name == "Change Living Wax Form: " + first
                   for c in combat._load_session(mid).engine.legal_candidates())
    assert act(table, mid, candidate(combat, mid, "Change Living Wax Form: " + second))["status"] == "COMMITTED"
    engine = check_reload(combat, mid, tmp_path)
    actor = engine.state.actors[PLAYER]
    states = [c for c in actor.conditions.values() if c.condition_id in {PREFIX + name for name in NAMES}]
    assert len(states) == 1 and states[0].data["name"] == "living_wax_form_" + second.lower().replace(" ", "_")
    assert states[0].expires_on == deadline
    assert actor.resources["resource:core.qi"] == before - 3
    owned = [m for m in actor.modifiers.values() if FEATURE in m.source_definition_id]
    assert all(m.expires_on == deadline for m in owned)
    # The expiry token is the same for every transition. Advance its complete
    # lifetime once rather than running the same thirty-turn sweep three times.
    if first == "Soft Body":
        for _ in range(10):
            assert act(table, mid, table.state(mid)["menu"]["end_turn"])["status"] == "COMMITTED"
            turn(table, mid, PLAYER)
        engine = check_reload(combat, mid, tmp_path)
        assert current(engine, engine.state.actors[PLAYER]) is None
        assert not any(c.display_name.startswith("Change Living Wax Form:") for c in engine.legal_candidates())


def test_form_change_buttons_are_absent_without_the_talent(tmp_path, caplog):
    combat, table, mid = fixture(tmp_path, [])
    turn(table, mid, PLAYER)
    assert not any(c.display_name.startswith("Change Living Wax Form:") for c in check_reload(combat, mid, tmp_path).legal_candidates())
    assert not any("wax_forms.change_allowed" in record.message for record in caplog.records)


def test_form_changes_preserve_added_modifier_costs():
    from combat.ext.wax_forms import changes, FEATURE
    from combat.factory_compiler import compile_character
    from combat.gate2_runtime_models import ActionDefinition
    from tests.test_r5i_integration import sheet

    bundle = compile_character(sheet([FEATURE], cl=15), actor_id=PLAYER)
    original = next(a for a in bundle["action_catalog"] if a["display_name"] == "Living Wax Form: Soft Body")
    action = ActionDefinition.model_validate(original).model_copy(update={
        "costs": (("resource:core.qi", 3), ("resource:named.test_fee", 2))})
    result = changes({"owned_ids": [FEATURE], "mechanics": {FEATURE: {"effects": [{"type": "wax_form_lifecycle"}]}},
                      "actions": [action], "primary": "qi"})
    assert result[0].costs == (("resource:core.qi", 2), ("resource:named.test_fee", 2))


def test_change_descriptions_explain_the_selected_form_and_actual_cost():
    from combat.ext.wax_forms import description
    from combat.factory_compiler import compile_character
    from tests.test_r5i_integration import sheet

    bundle = compile_character(sheet([FEATURE], cl=15), actor_id=PLAYER)
    changes = [a for a in bundle["action_catalog"] if a["display_name"].startswith("Change Living Wax Form:")]
    assert len(changes) == 3
    for action, words in zip(changes, ("escape Grappled", "30 Temporary Hit Points", "4 fire damage")):
        text = description(action)
        assert words in text and "Bonus Action" in text and "Cost: 1" in text
        assert "time left" in text and "one-minute" in text
        assert "condition:" not in text and "TAL_" not in text

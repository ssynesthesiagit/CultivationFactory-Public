"""Effect ownership survives modifier composition and history formatting."""
import copy

from tests.test_attack_abilities import sheet, natural, SPHERE, compile_character


def test_composed_damage_keeps_each_effect_source_and_explicit_label():
    from combat.ext.damage_labels import label_riders
    from combat.factory_compiler import apply_modifiers
    from combat.gate2_runtime_models import ActionDefinition
    from combat.history_feed import format_history_feed
    from combat.typed_executor import Context, run_effects
    from tests.test_iron_fist import _engine

    bundle = compile_character(sheet(), actor_id="actor:factory.fist")
    base = natural(bundle)
    built = {"strike": {"action_id": base["source_definition_id"], "name": "Mixed strike", "costs": [],
                         "typed": copy.deepcopy(base["parameters"]["typed"]), "modifiers": [],
                         "mechanic": {"sphere_id": SPHERE}}}
    mechanics = {}
    for key, name, label in [("first", "First rider", None), ("second", "Second rider", "Effect-owned name")]:
        effect = {"type": "extra_damage", "dice": {"count": 1, "sides": 6}, "damage_types": ["force"]}
        if label:
            effect["damage_label"] = label
        mechanics[key] = {"name": name, "sphere_id": SPHERE, "activation": {"economy": "passive"},
                          "modifier": {"targets": ["Mixed strike"], "when": "hit", "effects": [effect]}}
    original = copy.deepcopy(mechanics)
    apply_modifiers(built, list(mechanics), mechanics, "qi", ["qi"])
    action = ActionDefinition.model_validate({**base, "display_name": "Mixed strike",
                                             "parameters": {**base["parameters"], "typed": built["strike"]["typed"]}})
    fallback = {"type": "damage", "deferred": True, "dice": {"count": 1, "sides": 4}, "damage_types": ["force"]}
    action.parameters["typed"]["effects"][0]["on_hit"].append(fallback)
    action = label_riders(action, {}) or action
    engine = _engine(bundle)
    actor = engine.state.actors[action.owner_id]
    foe = next(a for a in engine.state.actors.values() if a.team_id != actor.team_id)
    ctx = Context(engine, actor, action, None, action.parameters["typed"], [foe], foe, {})
    # Run the composed hit's damage, avoiding an unrelated attack's random hit/miss.
    rows = action.parameters["typed"]["effects"][0]["on_hit"]
    run_effects(ctx, [{**row, "deferred": False} for row in rows])
    events = [e.model_dump(mode="json") for e in engine.events if e.event_type == "DAMAGE_ROLLED"]
    assert [e["payload"].get("damage_label") for e in events] == [None, "First rider", "Effect-owned name", "Mixed strike"]
    feed = format_history_feed(events, [], pre_state=None, post_state={}, actor_names={}, definition_names={})
    for name in ("First rider", "Effect-owned name", "Mixed strike"):
        assert any(name in row["summary"] for row in feed)
    assert mechanics == original

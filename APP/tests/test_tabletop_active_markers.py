from types import SimpleNamespace

import pytest

from combat.ext import flowing_river, foundation_sacred_body
from combat.gate2_runtime_models import ActionDefinition, ConditionInstance, EconomyKind
from combat.tabletop_service import TabletopService


def test_one_server_flag_covers_shapes_augments_and_plugin_choices():
    actor = SimpleNamespace(entity_id="actor:a", conditions={})
    info = {"actor_id": actor.entity_id, "short": "a", "numbers": {},
            "owned_ids": [foundation_sacred_body.REBUKE, flowing_river.RESPONSE, *flowing_river.NAMES]}
    rebukes = foundation_sacred_body.rebuke_choices(info)
    flows = flowing_river.flowing_choices(info)
    choices = rebukes + flows
    frame = next(row for row in choices if row.display_name == "Saint-Body Rebuke: Frame Advantage")
    flow = next(row for row in flows if "Empty Step" in row.display_name)
    shape = ActionDefinition(source_definition_id="shape", display_name="Shape", owner_id=actor.entity_id,
                             economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF",
                             parameters={"zone_shape": "dark", "shape_of": "base", "shape_talents": ["hungry"]})
    augment = shape.model_copy(update={"source_definition_id": "augment", "parameters": {"augment_toggle": "base", "augment_key": "directional"}})
    base = shape.model_copy(update={"source_definition_id": "base", "economy": EconomyKind.ACTION, "parameters": {}})
    engine = SimpleNamespace(state=SimpleNamespace(actors={actor.entity_id: actor}),
                             action_catalog={row.source_definition_id: row for row in [*choices, shape, augment, base]})

    class Conditions:
        def _remove_condition(self, actor, condition_id, source):
            actor.conditions = {key: row for key, row in actor.conditions.items() if row.condition_id != condition_id}

        def _apply_condition(self, actor, condition_id, source, owner, **kwargs):
            actor.conditions[condition_id] = ConditionInstance(instance_id=condition_id, condition_id=condition_id,
                source_definition_id=source, source_actor_id=owner, target_id=owner, applied_sequence=1, **kwargs)

    ctx = SimpleNamespace(engine=Conditions(), actor=actor, source=frame.source_definition_id)
    foundation_sacred_body.rebuke_choice(ctx, {"choice": "frame"})
    ctx.source = flow.source_definition_id
    flowing_river.flowing_choice(ctx, flow.parameters["typed"]["effects"][0])
    shapes = {actor.entity_id: [{"base": "base", "options": [{"talents": ["hungry"], "active": True}],
                               "augments": [{"key": "directional", "on": True}]}]}
    flags = TabletopService._button_states(engine, shapes)[actor.entity_id]
    for action in (frame, flow, shape, augment):
        assert flags[f"act:{action.source_definition_id}"] == {"active": True}
    push = next(row for row in rebukes if row.display_name == "Saint-Body Rebuke: Push 5 ft")
    assert flags[f"act:{push.source_definition_id}"] == {"active": False}
    ctx.source = push.source_definition_id
    foundation_sacred_body.rebuke_choice(ctx, {"choice": "push"})
    shapes[actor.entity_id][0]["augments"][0]["on"] = False
    flags = TabletopService._button_states(engine, shapes)[actor.entity_id]
    assert not flags[f"act:{frame.source_definition_id}"]["active"]
    assert flags[f"act:{push.source_definition_id}"]["active"]
    assert not flags["act:augment"]["active"]
    assert flags["act:base"]["active"]  # selected talent remains visible with the Options panel closed
    shapes[actor.entity_id][0]["options"][0]["active"] = False
    assert not TabletopService._button_states(engine, shapes)[actor.entity_id]["act:base"]["active"]
    assert TabletopService._button_states(None, {}) == {}


@pytest.mark.parametrize("module", ["trap", "vessel", "blossom"])
def test_independent_plugin_fields_remain_active_after_another_pick(module):
    from combat.ext import blossom, trap, vessel
    from combat.factory_compiler import compile_character
    from tests.test_zones import SHEET

    plugin = {"trap": trap, "vessel": vessel, "blossom": blossom}[module]
    talents = [vessel.IRONWOOD] if module == "vessel" else [blossom.SEED] if module == "blossom" else []
    sheet = {**SHEET, "spheres_and_talents": {"sphere_record_ids": [plugin.SPHERE], "learned_talent_record_ids": talents}}
    bundle = compile_character(sheet, actor_id="actor:a")
    actions = [ActionDefinition.model_validate(row) for row in bundle["action_catalog"]]
    picked = {}
    selected = []
    for action in actions:
        selector = plugin.setup_selection(action.parameters) or {}
        if selector.get("condition") != plugin.SETUP:
            continue
        field, value = next(iter(selector["equals"].items()))
        if field not in picked:
            picked[field] = value
            selected.append(action)
    assert len(selected) >= 2
    condition = ConditionInstance(instance_id="setup", condition_id=plugin.SETUP,
        source_definition_id=selected[-1].source_definition_id, source_actor_id="actor:a", target_id="actor:a",
        applied_sequence=2, data=picked)
    actor = SimpleNamespace(entity_id="actor:a", conditions={"setup": condition})
    engine = SimpleNamespace(state=SimpleNamespace(actors={actor.entity_id: actor}),
                             action_catalog={action.source_definition_id: action for action in actions})
    flags = TabletopService._button_states(engine, {})[actor.entity_id]
    for action in selected:
        assert flags[f"act:{action.source_definition_id}"]["active"]
    condition.data = {}
    flags = TabletopService._button_states(engine, {})[actor.entity_id]
    assert not any(flags[f"act:{action.source_definition_id}"]["active"] for action in selected)


def test_two_menu_picks_and_two_domain_layers_use_one_generic_selector():
    from combat.ext import menus, formation_talents

    info = {"short": "a", "actor_id": "actor:a", "numbers": {}}
    rows = menus.toggle_actions(info, {"id": "menu:a", "name": "A", "options": ["first", "second", "third"]})
    for pattern in ("locking_gate", "suppressing_vein"):
        rows.append(formation_talents.build_action(info, {}, pattern, pattern, "NONE", "SELF", None,
            [{"type": "formation_setup", "op": "domain_layer", "pattern": pattern, "damage_type": None}], "setup"))
    actor = SimpleNamespace(entity_id="actor:a", conditions={})
    for condition_id, source, data in [
        (menus.MENU, rows[1].source_definition_id, {"menu": "menu:a", "picks": ["first", "second"]}),
        (formation_talents.SETUP_COND, rows[-1].source_definition_id,
         {"domain_layers": [["locking_gate", None], ["suppressing_vein", None]]}),
    ]:
        actor.conditions[condition_id] = ConditionInstance(instance_id=condition_id, condition_id=condition_id,
            source_definition_id=source, source_actor_id=actor.entity_id, target_id=actor.entity_id, applied_sequence=1, data=data)
    engine = SimpleNamespace(state=SimpleNamespace(actors={actor.entity_id: actor}),
                             action_catalog={row.source_definition_id: row for row in rows})
    flags = TabletopService._button_states(engine, {})[actor.entity_id]
    assert [flags[f"act:{row.source_definition_id}"]["active"] for row in rows] == [True, True, False, True, True]

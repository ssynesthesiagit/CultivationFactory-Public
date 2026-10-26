"""Source-discovered edge scans, exercised on a real engine at each corner.

Choice doubles select the first legal option; ownership/setup doubles only
isolate the particular scan. No production engine methods are patched.
"""
from types import SimpleNamespace
import pytest
from combat.gate2_runtime_models import Position
from combat.ext import (ash_core, axes_falling_tree, banner, exorcist, magma_crust,
                        mercy_flayer, needle, placed, rider_choices, seraphic_molter,
                        thread_object, trap, vessel, warleader_shouts)
from tests import test_auto43_smoke_veil as s


@pytest.fixture
def scene(monkeypatch):
    engine, owner, target = s._fight(cl=4)
    engine._active_intent = s._intent(engine)
    source = engine._active_intent.candidate_id
    action = next(a for a in engine.action_catalog.values() if a.owner_id == owner.entity_id)
    ctx = placed.context(engine, owner, action.source_definition_id,
                         {"cl": 20, "pb": 3, "key_mod": 2, "save_dc": 30}, [target], action=action)
    monkeypatch.setattr(rider_choices, "pick", lambda engine, owner, key, name, options, **kw: options[:1])
    monkeypatch.setattr(needle, "ask", lambda engine, intent, checkpoint, owner, key, options, **kw: options[:1])
    return engine, owner, target, ctx


@pytest.mark.parametrize("corner", [(0, 0), (19, 0), (0, 13), (19, 13)])
@pytest.mark.parametrize("scan", ["seal", "flayer", "thread", "banner", "falling_tree", "glob", "crust",
                                  "remnant", "hundred_traps", "trap_within", "tug", "cast_off", "shed_name"])
def test_extension_scans_do_not_construct_negative_or_offer_off_map_squares(scene, monkeypatch, corner, scan):
    engine, owner, target, ctx = scene
    x = 0 if corner[0] == 0 else engine.grid.width - 1
    y = 0 if corner[1] == 0 else engine.grid.height - 1
    target.position = Position(x=x, y=y)
    owner.position = Position(x=1 if x == 0 else x - 1, y=1 if y == 0 else y - 1)
    if scan == "seal":
        p = exorcist._anchor_square(engine, target)
        assert engine.grid.in_bounds((p.x, p.y)) and p != target.position
    elif scan == "flayer":
        obj = mercy_flayer._place_anchor(engine, target, "test:flayer:", "TEST", 10, "test anchor")
        assert obj.position != target.position
    elif scan == "thread":
        obj = SimpleNamespace(object_id="test:bell", position=target.position)
        cells = thread_object._destinations(engine, obj)
        assert cells and all(engine.grid.in_bounds((p.x, p.y)) for p in cells)
    elif scan == "banner":
        assert not banner._push_from(engine, owner, target, ctx.source)
        assert target.position == Position(x=x, y=y)
    elif scan == "falling_tree":
        next(e for e in engine.events if e.event_type == "MATCH_CREATED").payload["axes_push_bounds_policy"] = 1
        ctx.typed["anchor"] = {"x": owner.position.x, "y": owner.position.y, "name": "the fallen tree"}
        axes_falling_tree.push(ctx, {"distance_ft": 10})
        assert target.position == Position(x=x, y=y)
    elif scan == "glob":
        magma_crust.magma_patch(ctx, {"terrain": "molten"})
        assert magma_crust.patches(engine, owner, "molten")
    elif scan == "crust":
        magma_crust._place(ctx, target.position, "molten", None)
        ctx.intent = ctx.intent.model_copy(update={"destination": target.position})
        magma_crust.shape(ctx, {"op": "move"})
        assert magma_crust.patches(engine, owner, "molten")[0].center != target.position
    elif scan == "remnant":
        ash_core._place(ctx, target.position)
        ash_core.move_remnant(ctx, {})
        assert ash_core.remnants(engine, owner)[0].center != target.position
    elif scan in ("hundred_traps", "trap_within"):
        # The geometry under test hands legal squares to the existing setter.
        spots = []
        monkeypatch.setattr(trap, "_set", lambda engine, owner, action, intent, kit, spot, config: spots.append(spot))
        if scan == "hundred_traps":
            owner.position = target.position
            ctx.action = ctx.action.model_copy(update={"parameters": {"hundred": True}})
            trap._after_variant(ctx, {}, target.position, {}, None)
        else:
            monkeypatch.setattr(trap, "_kit", lambda *args: {"owned": [trap.T + "TRAP_WITHIN_THE_TRAP"], "action": ctx.action})
            # Batch 3 asks the owner for the square (AUTO131); its checkpoint names the original zone.
            trap._trap_within(ctx, SimpleNamespace(center=target.position, zone_id="zone:test:trap"), {})
        assert spots and all(engine.grid.in_bounds((p.x, p.y)) for p in spots)
    elif scan == "tug":
        monkeypatch.setattr(vessel, "_kit", lambda *args: {})
        monkeypatch.setattr(vessel, "_threaded", lambda *args: [])
        vessel.tug(ctx, {})
        assert target.position != Position(x=x, y=y)
    elif scan == "cast_off":
        owner.position = target.position
        engine._apply_condition(owner, "condition:core.frightened", ctx.source, target.entity_id, expires_on="UNTIL_REMOVED")
        seraphic_molter.burn(ctx, {"burden": "frightened"})
        assert seraphic_molter.cast_off_of(engine, owner) is not None
    elif scan == "shed_name":
        engine._apply_condition(target, seraphic_molter.FORM, ctx.source, target.entity_id, expires_on="UNTIL_REMOVED")
        assert seraphic_molter.shed_name(engine, target, target.current_hp, owner.entity_id) is not None
        assert any(o.object_id.startswith(seraphic_molter.HUSK) for o in engine.state.objects.values())
    assert all(engine.grid.in_bounds((o.position.x, o.position.y)) for o in engine.state.objects.values())
    assert all(engine.grid.in_bounds((p.x, p.y)) and (p.x, p.y) not in engine.grid.blocked
               for z in engine.state.zones.values() for p in z.affected_cells)


def test_echo_preserves_a_cones_direction_when_its_virtual_end_is_outside_the_map(scene):
    engine, owner, _, ctx = scene
    owner.position = Position(x=0, y=0)
    ally = owner.model_copy(deep=True, update={"entity_id": "test:ally", "position": Position(x=0, y=1)})
    engine.state.actors[ally.entity_id] = ally
    engine._apply_condition(owner, warleader_shouts.ECHO, ctx.source, owner.entity_id, expires_on="UNTIL_REMOVED",
                            data={"echo": {"benefit": "temp_hp", "area": {"shape": "cone", "size_ft": 15}, "aim_delta": [-1, 4]}})
    warleader_shouts.war_drum_echo(engine, owner)
    assert ally.temporary_hp == owner.proficiency_bonus
    assert not warleader_shouts._held(owner, warleader_shouts.ECHO)


def test_legacy_positive_edge_push_keeps_its_reaction_route_length(scene, monkeypatch):
    from combat import movement_paths
    engine, owner, target, ctx = scene
    target.position = Position(x=engine.grid.width - 2, y=7)
    ctx.typed["anchor"] = {"x": engine.grid.width - 3, "y": 7}
    lengths = []
    monkeypatch.setattr(movement_paths, "resolve", lambda engine, target, path, source, **kw: lengths.append(len(path)))
    assert not axes_falling_tree.bounded_push_route(engine)
    axes_falling_tree.push(ctx, {"distance_ft": 10})
    next(e for e in engine.events if e.event_type == "MATCH_CREATED").payload["axes_push_bounds_policy"] = 1
    axes_falling_tree.push(ctx, {"distance_ft": 10})
    assert lengths == [3, 2]


def test_push_bounds_policy_is_recorded_only_for_a_falling_tree_owner():
    from tests import test_auto53_axes as a
    engine = a._three([a.LAW], dc=30)
    assert axes_falling_tree.bounded_push_route(engine)
    assert next(e for e in engine.events if e.event_type == "MATCH_CREATED").payload["axes_push_bounds_policy"] == 1


def test_axes_policy_survives_a_real_table_commit_and_cold_reload(tmp_path):
    from combat.gate5_service import CombatService
    from tests import test_auto43r1f1_smoke_table as table_tests
    combat, table, mid = table_tests._fight(tmp_path, [axes_falling_tree.TALENT])
    assert axes_falling_tree.bounded_push_route(combat._load_session(mid).engine)
    table_tests._commit(table, mid, table.state(mid)["menu"]["end_turn"])
    fresh = CombatService(table_tests.ROOT, tmp_path)._load_session(mid)
    assert axes_falling_tree.bounded_push_route(fresh.engine)
    assert fresh.verify()["status"] == fresh.mechanical.replay()["status"] == "PASS"

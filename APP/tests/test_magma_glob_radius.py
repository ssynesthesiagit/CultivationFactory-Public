"""Regression checks for the terrain-patch engine used by Magma Glob."""

from combat import typed_executor, zones
from tests.test_auto_docket import AN, ME, _ctx, _fight, _sheet


def test_obsidian_patch_is_difficult_only_for_hostiles():
    # Owner asks that the cooled Glob patch obey Obsidian Terrain's hostile-only difficulty.
    engine = _fight(_sheet([]), foe_at=(10, 6))
    typed_executor.run_effects(_ctx(engine), [{"type": "terrain_patch", "terrain": "obsidian terrain", "radius_ft": 5}])
    assert (10, 6) in zones.difficult_cells(engine, engine.state.actors[AN])
    assert (10, 6) not in zones.difficult_cells(engine, engine.state.actors[ME])


import pytest
from combat.gate5_service import CombatService
from tests.auto_worker1_support import LEFT, RIGHT, ALLY, fight, reload, settle, turn, cell_send
from tests.hunt15_support import act

GLOB = "TAL_MAGMA_MAGMA_GLOB"
SHAPE = "TAL_MAGMA_SHAPE_THE_CRUST"
SOVEREIGN = "TAL_MAGMA_VOLCANO_SOVEREIGN_INCARNATION"
MAGMA = "tianxia.sphere.magma"
CENTER = (8, 6)
RADIUS = {(8, 6), (7, 6), (9, 6), (8, 5), (8, 7)}


def clear_arena(arena):
    arena["terrain_regions"] = []
    arena["map_terrain"] = []
    arena["map_objects"] = []
    arena["tabletop"] = {"walls": [], "trees": [], "floors": [], "ambient": {"level": "bright"}}


def table(tmp_path, talents=(), **kwargs):
    return fight(tmp_path, [GLOB, *talents], spheres=[MAGMA], left_attack_bonus=100,
                 positions={LEFT: {"x": 3, "y": 6}, RIGHT: {"x": 8, "y": 6}},
                 arena_edit=clear_arena, maximum_rounds=18, **kwargs)


def ground(engine, kind):
    return [z for z in zones.typed_zones(engine)
            if z.owner_id == LEFT and kind + " terrain" in z.trigger_profile.get("terrain", [])]


def squares(zone):
    return {(p.x, p.y) for p in zone.affected_cells}


def glob(combat, tabletop, mid, kind="Molten"):
    label = kind + " Terrain Patch"
    def choose(prompt):
        if prompt["context"]["reaction_source_id"].endswith("magma_glob_expression"):
            return [label]
        return [prompt["choice"]["options"][0]["id"]]
    return settle(lambda answers: act(tabletop, mid, "Magma Glob: " + label, answers, target_id=RIGHT), choose)


def move(combat, tabletop, mid, at):
    def send(answers):
        state = tabletop.state(mid)
        candidate = next(c for c in combat._load_session(mid).engine.legal_candidates()
                         if c.kind.value == "MOVE" and c.destination
                         and (c.destination.x, c.destination.y) == at)
        return tabletop.act(mid, candidate.candidate_id, state["menu"]["decision_id"],
                            state["menu"]["state_version"], state["last_sequence"], answers)
    return settle(send)


def test_molten_option_covers_target_radius_without_square_choice(tmp_path):
    # Owner: all Glob ground is a 5-foot radius centered on the target, including occupied spaces.
    c, t, m = table(tmp_path, ally=[], extra_witness=True, witness_position={"x": 9, "y": 6})
    _, prompts = glob(c, t, m)
    patch, = ground(reload(c, m), "molten")
    assert squares(patch) == RADIUS and patch.duration_rounds == 1
    assert (patch.center.x, patch.center.y) == CENTER and patch.radius_cells == 1
    assert not any(p["context"]["reaction_source_id"].endswith("magma_patch") for p in prompts)
    assert patch.trigger_profile["triggers"][0]["effects"][0]["on_fail"]


def test_molten_cools_to_permanent_obsidian_with_its_own_rules(tmp_path):
    # Owner: next owner start cools the same squares permanently, with Obsidian's hazards, not Molten's.
    c, t, m = table(tmp_path)
    glob(c, t, m)
    original, = ground(reload(c, m), "molten")
    turn(t, m, RIGHT)
    turn(t, m, LEFT)
    engine = reload(c, m)
    patch, = ground(engine, "obsidian")
    assert not ground(engine, "molten") and squares(patch) == RADIUS
    assert patch.duration_rounds is None
    assert (patch.owner_id, patch.source_definition_id, patch.center, patch.radius_cells) == (
        original.owner_id, original.source_definition_id, original.center, original.radius_cells)
    assert patch.trigger_profile["numbers"] == original.trigger_profile["numbers"]
    assert patch.trigger_profile["triggers"] == []
    assert patch.trigger_profile["move_through"]["on_fail"][0]["damage_types"] == ["slashing"]
    assert CENTER in zones.difficult_cells(engine, engine.state.actors[RIGHT])
    assert CENTER not in zones.difficult_cells(engine, engine.state.actors[LEFT])
    hp = engine.state.actors[RIGHT].current_hp
    for _ in range(12):
        turn(t, m, RIGHT)
        turn(t, m, LEFT)
    engine = reload(c, m)
    assert ground(engine, "obsidian")[0].duration_rounds is None
    assert squares(ground(engine, "obsidian")[0]) == RADIUS
    assert engine.state.actors[RIGHT].current_hp == hp, "cooled terrain retained Molten's start damage"
    turn(t, m, RIGHT)
    start = len(reload(c, m).events)
    for at in [(9, 6), (8, 6), (8, 7)]:
        move(c, t, m, at)
    engine = reload(c, m)
    saves = [e for e in engine.events[start:] if e.event_type == "SAVE_ROLLED"]
    assert len(saves) == 1 and not saves[0].payload["success"]
    assert engine.state.actors[RIGHT].current_hp == hp - patch.trigger_profile["numbers"]["pb"]
    commits = [e for e in engine.events[start:] if e.event_type == "DAMAGE_COMMITTED"]
    assert commits and all(e.payload["damage_type"] == "SLASHING" for e in commits)
    cold = CombatService(c.source_root, c.userdata_root)._load_session(m)
    assert cold.mechanical.replay()["status"] == "PASS"


def test_obsidian_option_is_a_permanent_target_centered_radius(tmp_path):
    # Owner: choosing Obsidian directly also makes a permanent 5-foot-radius patch.
    c, t, m = table(tmp_path)
    _, prompts = glob(c, t, m, "Obsidian")
    patch, = ground(reload(c, m), "obsidian")
    assert squares(patch) == RADIUS and patch.duration_rounds is None
    assert (patch.center.x, patch.center.y) == CENTER
    assert not any(p["context"]["reaction_source_id"].endswith("magma_patch") for p in prompts)


@pytest.mark.parametrize("op,label,kind", [
    ("cool", "Cool Molten Patch", "molten"),
    ("move", "Move Molten Patch", "molten"),
    ("crack", "Crack Obsidian Patch", "obsidian"),
])
def test_shape_the_crust_edits_one_square_of_a_glob_radius(tmp_path, op, label, kind):
    # Owner: Shape the Crust still edits one square, without changing the rest of a Glob radius.
    c, t, m = table(tmp_path, [SHAPE])
    glob(c, t, m, kind.title())
    before, = ground(reload(c, m), kind)
    at = (9, 6)
    settle(cell_send(t, m, "Shape the Crust: " + label, at))
    engine = reload(c, m)
    parent = engine.state.zones[before.zone_id]
    assert squares(parent) == RADIUS - {at}
    if op == "cool":
        cooled, = ground(engine, "obsidian")
        assert squares(cooled) == {at} and cooled.duration_rounds == 10
    elif op == "move":
        moved, = [z for z in ground(engine, "molten") if z.zone_id != parent.zone_id]
        assert len(squares(moved)) == 1 and not squares(moved) & RADIUS
    else:
        assert not any(at in squares(z) for z in ground(engine, "obsidian"))


def test_sovereign_molten_patch_snapshots_actual_glob_dice_for_entry(tmp_path):
    # Owner: the shared from_ability save must retain active Volcano-Sovereign's 6d10.
    c, t, m = table(tmp_path, [SOVEREIGN])
    settle(lambda answers: act(t, m, "Volcano-Sovereign Incarnation", answers))
    glob(c, t, m)
    patch, = ground(reload(c, m), "molten")
    damage = patch.trigger_profile["triggers"][0]["effects"][0]["on_fail"]
    assert damage[0]["dice"]["count"] == 6 and damage[0]["dice"]["sides"] == 10
    assert "dice_by_cl" not in damage[0]
    turn(t, m, RIGHT)
    engine = reload(c, m)
    assert any(e.event_type == "SAVE_ROLLED" and e.actor_id == RIGHT and not e.payload["success"]
               for e in engine.events)
    assert [e for e in engine.events if e.event_type == "DAMAGE_ROLLED"][-1].payload["expression"] == "6d10+2"


def test_generic_non_magma_terrain_becomes_rebuilds_destination_rules(tmp_path):
    # Owner: becomes is reusable engine data, not another ability-specific cooling add-on.
    effect = {"type": "terrain_patch", "terrain": "fire terrain", "radius_ft": 5,
              "duration": {"kind": "until_start_of_next_turn"},
              "becomes": {"terrain": "loose rubble"}}
    c, t, m = fight(tmp_path, prepare=[effect], left_attack_bonus=100,
                    positions={LEFT: {"x": 3, "y": 6}, RIGHT: {"x": 8, "y": 6}},
                    arena_edit=clear_arena)
    settle(lambda answers: act(t, m, "Prepare", answers, target_id=RIGHT))
    engine = reload(c, m)
    original, = [z for z in zones.typed_zones(engine) if z.owner_id == LEFT]
    assert original.trigger_profile["triggers"]
    turn(t, m, RIGHT)
    turn(t, m, LEFT)
    engine = reload(c, m)
    patch, = [z for z in zones.typed_zones(engine) if z.owner_id == LEFT]
    assert patch.trigger_profile["terrain"] == ["loose rubble"]
    assert patch.trigger_profile["triggers"] == [] and patch.trigger_profile["move_through"] is None
    assert patch.trigger_profile["difficult"] == "all" and patch.duration_rounds is None
    assert squares(patch) == squares(original) == RADIUS
    assert (patch.owner_id, patch.source_definition_id, patch.center, patch.radius_cells,
            patch.trigger_profile["numbers"]) == (
        original.owner_id, original.source_definition_id, original.center, original.radius_cells,
        original.trigger_profile["numbers"])
    assert any(e.event_type == "ZONE_REMOVED" and e.payload["zone_id"] == original.zone_id
               for e in engine.events)

"""The overnight engine docket (owner 2026-09-28: "implement all the other list we had for overnight"): senses, areas that
stop at walls, breakable walls and cover, terrain made by a hit or a kill, auras, and the rest (combat/senses.py,
combat/ext/docket_*.py)."""

from pathlib import Path

from combat import senses, stealth, zones
from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN, LEE
from combat.gate2_runtime_models import ActionIntent, Position
from combat.gate4_engine import Gate4ControllerEngine
from tests.test_zones import SHEET

ROOT = Path(__file__).resolve().parents[1]
ME = "actor:factory.docket"
QI = "resource:core.qi"
FOCUS = "resource:core.martial_focus"
DARK = ["DARK_BASE_DARKNESS", "TAL_DARK_MELD", "TAL_DARK_RAPID_MELD", "TAL_DARK_PERSISTENT_MELD"]


def _sheet(talents: list[str], spheres: list[str] | None = None, **extra) -> dict:
    return {**SHEET, "spheres_and_talents": {"sphere_record_ids": spheres or ["tianxia.sphere.dark"], "learned_talent_record_ids": talents}, **extra}


def _fight(sheet: dict, me_at=(3, 6), foe_at=(10, 6), seed="DOCKET", second_foe=None) -> Gate4ControllerEngine:
    extra = {LEE: "team:b"} if second_foe else {}
    engine = Gate4ControllerEngine(ROOT, match_seed=seed, typed_bundles=(compile_character(sheet, actor_id=ME),),
                                   roster_setup={"primary_actor_ids": [ME, AN, *extra], "team_by_actor": {ME: "team:a", AN: "team:b", **extra},
                                                 "starting_positions": {ME: {"x": me_at[0], "y": me_at[1]}, AN: {"x": foe_at[0], "y": foe_at[1]},
                                                                        **({LEE: {"x": second_foe[0], "y": second_foe[1]}} if second_foe else {})}})
    _my_turn(engine)
    return engine


def _my_turn(engine) -> None:
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()


def _do(engine, name, at=None):
    candidate = next(c for c in engine.legal_candidates() if c.display_name.split(" at ")[0] == name
                     and (at is None or (c.destination is not None and (c.destination.x, c.destination.y) == at)))
    engine.execute_intent(ActionIntent(intent_id=name, decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=candidate.actor_id, target_ids=candidate.target_ids,
                                       destination=candidate.destination))


def _names(engine) -> set[str]:
    return {c.display_name.split(" at ")[0] for c in engine.legal_candidates()}


def _move(engine, actor, to):
    start, actor.position = actor.position, Position(x=to[0], y=to[1])
    zones.on_moved(engine, actor, start, actor.position)


# ------------------------------------------------------------------------------------------------ 1. senses
def test_darkvision_sees_through_plain_darkness_but_only_five_feet_into_pure_darkness():
    engine = _fight(_sheet([*DARK, "TAL_DARK_DARKVISION", "TAL_DARK_PURE_DARKNESS", "TAL_DARK_PITCH_BLACK"]))
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    assert senses.of(engine, me) == {"darkvision": {"range_ft": 60}}
    assert senses.of(engine, foe) == {}
    _do(engine, "Shape Darkness: plain Darkness")
    _do(engine, "Darkness", at=(10, 6))
    assert zones.hidden_from(engine, foe, me) is False  # it sees out
    assert zones.hidden_from(engine, me, foe) is False  # Darkvision sees in: "A creature with Darkvision can see through this Darkness"
    assert zones.attack_mode(engine, me, foe) is None
    _move(engine, me, (9, 6))  # both inside: it still sees the foe, the foe can't see it
    assert zones.attack_mode(engine, me, foe) == "ADVANTAGE"
    assert zones.attack_mode(engine, foe, me) == "DISADVANTAGE"
    # The same Darkness made Pure: Darkvision reaches 5 feet inside it.
    engine2 = _fight(_sheet([*DARK, "TAL_DARK_DARKVISION", "TAL_DARK_PURE_DARKNESS", "TAL_DARK_PITCH_BLACK"]))
    me2, foe2 = engine2.state.actors[ME], engine2.state.actors[AN]
    _do(engine2, "Shape Darkness: Pure Darkness")
    _do(engine2, "Darkness", at=(10, 6))
    assert zones.hidden_from(engine2, me2, foe2) is True
    assert zones.attack_mode(engine2, me2, foe2) == "DISADVANTAGE"
    _move(engine2, me2, (9, 6))  # 5 feet away, both inside
    assert zones.hidden_from(engine2, me2, foe2) is False and zones.hidden_from(engine2, foe2, me2) is True


def test_without_darkvision_the_darkness_blinds_its_own_maker_too():
    engine = _fight(_sheet([*DARK, "TAL_DARK_DARK_SLAUGHTER", "TAL_DARK_DARKVISION"]))  # Dark Slaughter is the starting Meld
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    assert senses.meld_of(engine, me) == "TAL_DARK_DARK_SLAUGHTER"
    assert senses.of(engine, me) == {}
    _do(engine, "Darkness", at=(10, 6))
    assert zones.attack_mode(engine, me, foe) == "DISADVANTAGE"


def test_melds_stack_as_actions_without_cp_or_with_persistent_cp():
    engine = _fight(_sheet([*DARK, "TAL_DARK_DARK_SLAUGHTER", "TAL_DARK_DARKVISION"]))
    me = engine.state.actors[ME]
    assert "Meld: Dark Slaughter" not in _names(engine)  # it already benefits from that one
    qi = me.resources[QI]
    _do(engine, "Meld: Darkvision")
    assert me.resources[QI] == qi and me.concentration is not None
    # Owner 2026-09-29 struck "only one Meld talent granted by the same cultivator": both at once.
    assert senses.melds_of(engine, me) == ["TAL_DARK_DARK_SLAUGHTER", "TAL_DARK_DARKVISION"]
    assert senses.meld_active(engine, me, "TAL_DARK_DARK_SLAUGHTER") is True
    assert senses.of(engine, me).get("darkvision") == {"range_ft": 60}
    engine._end_concentration(me, "BROKEN")  # this Meld ends with its Concentration; the other stays
    assert senses.melds_of(engine, me) == ["TAL_DARK_DARK_SLAUGHTER"] and "darkvision" not in senses.of(engine, me)
    _my_turn(engine)
    _do(engine, "Meld: Darkvision (Persistent)")
    assert senses.meld_of(engine, me) == "TAL_DARK_DARKVISION" and me.concentration is None


def test_meld_is_offered_as_an_action_without_owning_rapid_meld():
    talents = ["TAL_DARK_MELD", "TAL_DARK_DARK_SLAUGHTER", "TAL_DARK_DARKVISION"]
    sheet = _sheet(talents)
    engine = _fight(sheet)
    assert "Meld: Darkvision" in _names(engine)
    action = next(row for row in compile_character(sheet, actor_id=ME)["action_catalog"]
                  if row["display_name"] == "Meld: Darkvision")
    assert action["economy"] == "ACTION" and action["costs"] == []


def test_meld_catalog_and_persistent_cost_survive_table_commit_reload(tmp_path):
    import json
    import zipfile
    from combat.gate4_models import DecisionContext
    from combat.gate5_service import CombatService

    talents = ["TAL_DARK_MELD", "TAL_DARK_DARK_SLAUGHTER", "TAL_DARK_DARKVISION", "TAL_DARK_PERSISTENT_MELD"]
    sheet = _sheet(talents)
    bundle = compile_character(sheet, actor_id=ME)
    catalog = bundle["action_catalog"]
    ordinary = [row for row in catalog if row["display_name"].startswith("Meld") and "Persistent" not in row["display_name"]]
    assert [row["display_name"] for row in ordinary] == ["Meld: Dark Slaughter", "Meld: Darkvision"]
    assert sum(row["display_name"] == "Meld" for row in catalog) == 0
    persistent = next(row for row in catalog if row["display_name"] == "Meld: Darkvision (Persistent)")
    assert persistent["costs"] == [[QI, 2]]

    for project in ("left", "right"):
        folder = tmp_path / "portable_characters" / project
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(sheet))
    actors = ["actor:factory.left", "actor:factory.right"]
    service = CombatService(ROOT, tmp_path)
    match_id = service.create_factory_match(
        project_ids=["left"], opponent_actor_ids=[actors[1]], match_seed="MELD-COMMIT-RELOAD",
        control_modes={actor: "MANUAL" for actor in actors},
    )["match_id"]
    session = service._load_session(match_id)
    context = DecisionContext.model_validate(service.decision(match_id, session=session)["context"])
    # Commit a real table decision, then reload its saved match; the full
    # compiled action catalog above is the same catalog the match stores.
    candidate = next(c for c in context.legal_candidates if c.kind.value == "END_TURN")
    actor_id = context.active_actor_id
    service.submit_intent(match_id, {
        "intent_id": "meld-catalog-persistence", "decision_id": context.decision_id,
        "candidate_id": candidate.candidate_id, "state_version": context.state_version,
        "actor_id": actor_id, "target_ids": list(candidate.target_ids),
    }, [], None, session=session)
    committed = session.engine.state.model_dump(mode="json")
    reloaded_engine = CombatService(ROOT, tmp_path)._load_session(match_id).engine
    restored = reloaded_engine.state.model_dump(mode="json")
    assert restored == committed
    reloaded_bundle = next(row for row in reloaded_engine.typed_bundle_documents if row["actor_id"] == actor_id)
    reloaded_catalog = reloaded_bundle["action_catalog"]
    assert [row["display_name"] for row in reloaded_catalog if row["display_name"].startswith("Meld")
            and "Persistent" not in row["display_name"]] == ["Meld: Dark Slaughter", "Meld: Darkvision"]
    reloaded_persistent = next(row for row in reloaded_catalog if row["display_name"] == "Meld: Darkvision (Persistent)")
    assert reloaded_persistent["costs"] == [[QI, 2]]


def test_blindsight_from_sight_beyond_sight_sees_the_hidden_and_through_darkness_and_ends_next_turn():
    sheet = _sheet(["TAL_THE_HIDDEN_EYE_SIGHT_BEYOND_SIGHT"], ["tianxia.sphere.the_hidden_eye"])
    engine = _fight(sheet, foe_at=(6, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    names = _names(engine)
    assert {"Sight Beyond Sight: Tremorsense", "Sight Beyond Sight: Blindsight (expend Martial Focus)"} <= names
    assert me.resources[FOCUS] == 1
    engine._apply_condition(foe, stealth.HIDDEN, "test", AN, expires_on="UNTIL_REMOVED", data={"stealth_total": 30})
    assert engine._attack_mode(me, foe) == "DISADVANTAGE"
    _do(engine, "Sight Beyond Sight: Blindsight (expend Martial Focus)")
    assert me.resources[FOCUS] == 0
    assert senses.of(engine, me) == {"blindsight": {"range_ft": 30}}  # CL 10-14: 30 feet
    assert engine._attack_mode(me, foe) == "NORMAL"  # it sees the hidden creature: no Disadvantage
    assert engine._attack_mode(foe, me) == "NORMAL"  # nor does the hidden one gain Advantage against it
    assert stealth.search(engine, me, 0, "test") == [AN]  # found with no roll
    assert stealth.hidden(foe) is None
    # At the start of its next turn the sense is gone.
    engine.state.round_number += 1
    _my_turn(engine)
    assert senses.of(engine, me) == {}
    assert "Sight Beyond Sight: Blindsight (expend Martial Focus)" not in _names(engine) or me.resources[FOCUS] >= 1


def test_tremorsense_pinpoints_a_hidden_creature_for_a_search_but_is_not_sight():
    sheet = _sheet(["TAL_THE_HIDDEN_EYE_SIGHT_BEYOND_SIGHT"], ["tianxia.sphere.the_hidden_eye"])
    engine = _fight(sheet, foe_at=(6, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    _do(engine, "Sight Beyond Sight: Tremorsense")
    engine._apply_condition(foe, stealth.HIDDEN, "test", AN, expires_on="UNTIL_REMOVED", data={"stealth_total": 30})
    assert engine._attack_mode(me, foe) == "DISADVANTAGE"  # "does not count as sight"
    assert stealth.search(engine, me, 0, "test") == [AN]
    far = _fight(sheet, foe_at=(12, 6))
    _do(far, "Sight Beyond Sight: Tremorsense")
    far._apply_condition(far.state.actors[AN], stealth.HIDDEN, "test", AN, expires_on="UNTIL_REMOVED", data={"stealth_total": 99})
    assert far.state.actors[AN].entity_id not in stealth.search(far, far.state.actors[ME], 0, "test")  # out of range: a roll, and 99 is not met


def test_senses_come_from_spheres_path_features_and_martial_focus():
    sheet = _sheet(["BLOOD_BASE_BLOODSENSE", "TAL_THE_HIDDEN_EYE_TRUE_SIGHT"], ["tianxia.sphere.blood", "tianxia.sphere.the_hidden_eye"],
                   path_and_subpath={"path_feature_record_ids": ["tianxia.path.qi_cultivation.feature.qi_sensing",
                                                                 "tianxia.path.spirit_awakening.feature.spiritual_sense"]})
    engine = _fight(sheet)
    me = engine.state.actors[ME]
    assert senses.of(engine, me) == {"bloodsense": {"range_ft": 60}, "qi_sensing": {"range_ft": 30}, "spiritual_sense": {"range_ft": 10},
                                     "truesight": {"range_ft": 120}}
    me.resources[FOCUS] = 0  # True Sight: "While you hold Martial Focus"
    assert "truesight" not in senses.of(engine, me)
    # A sense that depends on a state the table does not track stays a GM note. (Hundred Eyes Open was the example until rider lane
    # C7 tracked Open Eyes -- combat/ext/calamity_eyes.py grants its Blindsight -- so a still-untracked one is used.)
    assert senses.compile_grants(["tianxia.subpath.qi.abyssal_depths_cultivator.feature.tidal_resilience"], 14)["gm"]


# ------------------------------------------------------------------------------------------------ 2. areas stop at walls
def _wall(engine, cells):
    """A wall drawn on the map (the grid's own blocked squares)."""
    engine.grid.blocked |= set(cells)
    engine.grid.opaque |= set(cells)
    engine._wall_base = None  # combat/zones.py sync_walls takes the map's walls from the grid again


def test_darkness_flows_around_a_corner_but_never_through_a_wall():
    def darkness(gap):
        engine = _fight(_sheet([*DARK]), foe_at=(14, 6))
        _wall(engine, [(12, y) for y in range(0, 20) if y != gap])  # a wall at x=12, with a gap at y=gap
        _do(engine, "Darkness", at=(10, 6))
        [zone] = zones.typed_zones(engine)
        return engine, zone, {(cell.x, cell.y) for cell in zone.affected_cells}

    engine, zone, cells = darkness(gap=None)
    assert zone.trigger_profile.get("spreads") is True
    assert (10, 6) in cells and (11, 6) in cells and (12, 6) not in cells and (13, 6) not in cells  # 15 feet, but through the wall
    engine, zone, cells = darkness(gap=7)
    assert (12, 7) in cells and (13, 6) in cells  # through the gap and round the corner, still within 15 feet of the center
    assert (12, 6) not in cells and not zones._inside(engine, engine.state.actors[AN], zone)


def test_a_sphere_does_not_reach_a_creature_behind_a_wall():
    from combat.typed_executor import _area_targets, area_cells

    engine = _fight(_sheet([*DARK]), foe_at=(12, 6))
    area = {"shape": "sphere", "size_ft": 20}
    foe = engine.state.actors[AN]
    assert [row.entity_id for row in _area_targets(engine, engine.state.actors[ME], Position(x=10, y=6), area)] == [AN]
    _wall(engine, [(11, y) for y in range(0, 20)])
    assert _area_targets(engine, engine.state.actors[ME], Position(x=10, y=6), area) == []
    cells = {(cell.x, cell.y) for cell in area_cells(engine, engine.state.actors[ME].position, Position(x=10, y=6), area)}
    assert (9, 6) in cells and (11, 6) not in cells and (12, 6) not in cells and foe.position.x == 12


# ------------------------------------------------------------------------------------------------ 3. walls
WEAPON = {"equipment": [{"starting_kit": {"items": [{"item_id": "tianxia.mortal.weapon.dao"}, {"item_id": "tianxia.mortal.weapon.shortbow"}]}}],
          "path_and_subpath": {"path_record_ids": ["tianxia.path.body_refining"]}}


def _earth_fight(**kw):
    return _fight(_sheet(["TAL_EARTH_RAISE_THE_LOAD_BEARING_WALL"], ["tianxia.sphere.earth"], **WEAPON), **kw)


def _cast_wall(engine, name, at):
    _do(engine, name, at=at)
    return next(zone for zone in zones.typed_zones(engine) if zone.trigger_profile.get("wall"))


def test_a_wall_section_has_the_texts_ac_and_hit_points_and_breaks_open():
    from combat.ext import docket_walls

    engine = _earth_fight(me_at=(3, 6), foe_at=(12, 6))
    me = engine.state.actors[ME]
    zone = _cast_wall(engine, "Raise the Load-Bearing Wall", (4, 6))  # its range is 5 feet
    row = docket_walls.stats(zone)
    assert row == {"ac": 15, "hp": 40, "scope": "section", "immune": ["POISON", "PSYCHIC"], "vulnerable": [], "resist_mundane": []}  # 20 + 2 x CL 10
    section = next(cell for cell in zone.affected_cells if (cell.x, cell.y) == (4, 6))
    engine.state.round_number += 1
    _my_turn(engine)
    names = [c.display_name for c in engine.legal_candidates() if c.display_name.startswith("Attack a wall section")]
    assert names and all(" at 4," in name for name in names)  # only the sections within its reach
    docket_walls._damage(engine, zone, section, 39, "test", "SLASHING")
    assert docket_walls.hit_points_left(zone, section) == 1 and (4, 6) in engine.grid.blocked
    docket_walls._damage(engine, zone, section, 1, "test", "SLASHING")
    assert (4, 6) not in {(cell.x, cell.y) for cell in zone.affected_cells} and (4, 6) not in engine.grid.blocked  # broken open
    assert zone.active and len(zone.affected_cells) == 5


def test_attacking_a_wall_rolls_against_its_ac_and_a_whole_wall_ends_at_zero():
    from combat.ext import docket_walls

    engine = _fight(_sheet(["TAL_MAGMA_LAVA_WALL"], ["tianxia.sphere.magma"], **WEAPON), me_at=(3, 6), foe_at=(14, 6))
    zone = _cast_wall(engine, "Lava Wall", (5, 6))
    row = docket_walls.stats(zone)
    assert (row["ac"], row["hp"], row["scope"]) == (15, 100, "wall") and "FIRE" in row["immune"]
    engine.state.round_number += 1
    _my_turn(engine)
    engine.state.actors[ME].position = Position(x=4, y=6)
    before = len(engine.events)
    _do(engine, "Attack a wall section", at=(5, 6))
    rolled = [event for event in engine.events[before:] if event.event_type == "CHECK_ROLLED"]
    assert rolled and rolled[0].payload["check"] == "Attack on a wall section" and rolled[0].payload["dc"] == 15
    taken = int(zone.trigger_profile.get("wall_damage") or 0)
    if rolled[0].payload["success"]:
        assert taken > 0  # halved: "Resistance to nonmagical damage" (a mundane dao)
    docket_walls._damage(engine, zone, zone.affected_cells[0], 100, "test", "BLUDGEONING")
    assert not zone.active  # the wall is destroyed: it ends (and leaves Obsidian Terrain)
    assert any(row_.trigger_profile.get("name") == "Obsidian Terrain" for row_ in zones.typed_zones(engine))


def test_three_quarters_cover_behind_a_dune_wall_and_half_behind_a_humble_wall():
    engine = _fight(_sheet(["TAL_SAND_DUNE_WALL", "TAL_EARTH_HUMBLE_WALL"], ["tianxia.sphere.sand", "tianxia.sphere.earth"], **WEAPON),
                    me_at=(3, 6), foe_at=(10, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    assert engine._cover_bonus_actor_to_actor(me, foe) == 0
    _cast_wall(engine, "Dune Wall", (6, 6))
    assert engine._cover_bonus_actor_to_actor(me, foe) == 5
    assert engine._cover_bonus_actor_to_actor(foe, me) == 5


def test_the_player_lays_out_a_walls_direction_and_bend():
    engine = _earth_fight(me_at=(3, 6), foe_at=(14, 6))
    me = engine.state.actors[ME]
    assert "Clear wall points" not in _names(engine)
    _do(engine, "Wall point", at=(4, 9))   # from the aim point down to (4,9) ...
    _do(engine, "Wall point", at=(9, 9))   # ... then along to (9,9)
    assert zones.wall_plan(me) == [(4, 9), (9, 9)]
    zone = _cast_wall(engine, "Raise the Load-Bearing Wall", (4, 6))
    cells = [(cell.x, cell.y) for cell in zone.affected_cells]
    assert cells == [(4, 6), (4, 7), (4, 8), (4, 9), (5, 9), (6, 9)]  # six sections, bending at (4,9)
    assert zones.wall_plan(me) == []  # used up


def test_the_ai_raises_a_wall_between_itself_and_enemies_when_hurt():
    engine = _fight(_sheet(["TAL_MAGMA_LAVA_WALL"], ["tianxia.sphere.magma"], **WEAPON), me_at=(3, 6), foe_at=(12, 6))
    me = engine.state.actors[ME]
    walls = lambda: [c for c in engine.legal_candidates() if c.display_name.startswith("Lava Wall")]  # noqa: E731
    assert not any(c.metadata.get("tactical_wall") for c in walls())  # healthy, one enemy: it fights
    me.current_hp = me.maximum_hp // 2
    tactical = [c for c in walls() if c.metadata.get("tactical_wall")]
    assert 1 <= len(tactical) <= 3 and all(not c.metadata.get("empty_area") and c.metadata["expected_damage"] == 8 for c in tactical)
    from combat.gate4_context import build_decision_context
    from combat.gate4_policy import PolicyLibrary

    context = build_decision_context(engine, PolicyLibrary(ROOT).fallback(), for_ai=True)
    assert {c.candidate_id for c in tactical} <= {c.candidate_id for c in context.legal_candidates}


# ------------------------------------------------------------------------------------------------ 4. ground from a blow, auras
def _ctx(engine, action_name=None):
    from combat import typed_executor

    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    action = next(row for row in engine.action_catalog.values() if row.owner_id == ME and (action_name is None or row.display_name == action_name))
    return typed_executor.Context(engine, me, action, None, dict(action.parameters.get("typed") or {}), [foe], foe, {})


def test_hungry_flame_is_an_augment_on_ignite_against_a_kindled_target_and_a_kill_leaves_fire_terrain():
    from combat import typed_executor

    engine = _fight(_sheet(["FIRE_BASE_IGNITE", "tianxia.talent.fire.hungry_flame"], ["tianxia.sphere.fire"]), foe_at=(6, 6), second_foe=(15, 15))
    variant = next(row for row in engine.action_catalog.values() if row.display_name == "Ignite: Bonus vs Kindled + Hungry Flame")
    base = next(row for row in engine.action_catalog.values() if row.display_name == "Ignite: Bonus vs Kindled")
    assert dict(variant.costs).get(QI, 0) == dict(base.costs).get(QI, 0) + 1  # "Cost: +1 CP"
    on_hit = next(e for e in variant.parameters["typed"]["effects"] if e["type"] == "attack")["on_hit"]
    assert any(e["type"] == "if_target" and e["condition"] == "kindled" for e in on_hit)
    foe = engine.state.actors[AN]
    ctx = _ctx(engine, "Ignite: Bonus vs Kindled + Hungry Flame")
    hungry = next(e for e in on_hit if e["type"] == "if_target")
    hp = foe.current_hp
    typed_executor.run_effects(ctx, [hungry])
    assert foe.current_hp == hp  # not Kindled: nothing
    engine._apply_condition(foe, "condition:typed.kindled", "test", ME, expires_on="UNTIL_REMOVED")
    foe.current_hp = 1
    typed_executor.run_effects(ctx, [hungry])
    assert foe.current_hp == 0
    [fire] = [zone for zone in zones.typed_zones(engine) if zone.trigger_profile.get("name") == "Fire Terrain"]
    assert [(c.x, c.y) for c in fire.affected_cells] == [(6, 6)] and fire.duration_rounds == 1


def test_a_patch_of_difficult_terrain_made_by_a_blow_stops_at_walls():
    from combat import typed_executor

    engine = _fight(_sheet(["TAL_BERSERKER_BATTER", "TAL_BERSERKER_HEAVEN_SHAKING_BATTER"], ["tianxia.sphere.berserker"], **WEAPON), foe_at=(10, 6))
    _wall(engine, [(12, y) for y in range(0, 20)])
    typed_executor.run_effects(_ctx(engine), [{"type": "terrain_patch", "difficult": "all", "radius_ft": 10, "name": "Shaken ground"}])
    [patch] = [zone for zone in zones.typed_zones(engine) if zone.trigger_profile.get("name") == "Shaken ground"]
    cells = {(c.x, c.y) for c in patch.affected_cells}
    assert (10, 6) in cells and (8, 6) in cells and (11, 6) in cells and (12, 6) not in cells and patch.duration_rounds is None
    assert (8, 6) in zones.difficult_cells(engine, engine.state.actors[ME])


def test_yokozuna_presence_is_an_aura_while_rooted_that_ends_when_it_moves_too_far():
    sheet = {**SHEET, "path_and_subpath": {"path_feature_record_ids": ["tianxia.subpath.body.sumo.feature.rooted_stance",
                                                                       "tianxia.subpath.body.sumo.feature.yokozuna_presence"]}}
    engine = _fight(sheet, foe_at=(9, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    assert not [z for z in zones.typed_zones(engine) if z.trigger_profile.get("aura")]
    _do(engine, "Rooted Stance")
    [aura] = [z for z in zones.typed_zones(engine) if z.trigger_profile.get("aura")]
    assert (5, 6) in zones.difficult_cells(engine, foe) and (5, 6) not in zones.difficult_cells(engine, me)
    assert (9, 6) not in zones.difficult_cells(engine, foe)  # 30 feet away
    engine._append_event("MOVEMENT_COMMITTED", "test", actor_id=ME, payload={"path": [{"x": 3, "y": 6}, {"x": 4, "y": 6}, {"x": 5, "y": 6}]})
    assert any(c.condition_id == "condition:typed.stance.rooted_stance" for c in me.conditions.values())  # 10 of 30 feet
    engine._append_event("MOVEMENT_COMMITTED", "test", actor_id=ME, payload={"path": [{"x": 5, "y": 6}, {"x": 6, "y": 6}]})
    assert any(c.condition_id == "condition:typed.stance.rooted_stance" for c in me.conditions.values())  # 15: not more than half
    engine._append_event("MOVEMENT_COMMITTED", "test", actor_id=ME, payload={"path": [{"x": 6, "y": 6}, {"x": 7, "y": 6}]})
    assert not any(c.condition_id == "condition:typed.stance.rooted_stance" for c in me.conditions.values())  # 20 > 15
    assert not [z for z in zones.typed_zones(engine) if z.trigger_profile.get("aura")]


# ------------------------------------------------------------------------------------------------ 5. Reaction Forged Techniques
def _forged(name, form, talent, augments=(), trigger=None):
    return {"name": name, "technique_id": f"forged.{name}", "action_type": "reaction", "base_form": {"form_id": form, "display_name": form.title()},
            "primary_sphere_effect": {"talent_id": talent}, "augments": [{"augment_id": row} for row in augments], "drawbacks": [],
            "cp_cost": {"final": 3}, **({"trigger": trigger} if trigger else {})}


def test_a_counter_expressing_a_reaction_runs_on_that_reactions_trigger_and_others_wait_for_a_trigger():
    sheet = _sheet(["TAL_AIR_ARROW_TURNING_BREATH", "TAL_DEATH_CORPSE_EXPLOSION"], ["tianxia.sphere.air", "tianxia.sphere.death"],
                   forged_techniques=[_forged("Arrow-Turning Counter", "counter", "TAL_AIR_ARROW_TURNING_BREATH", ["minor_hindrance"]),
                                      _forged("Death Counter", "counter", "TAL_DEATH_CORPSE_EXPLOSION"),
                                      _forged("Written Counter", "counter", "TAL_DEATH_CORPSE_EXPLOSION", trigger="When a creature within 60 feet of you hits you with an attack")])
    bundle = compile_character(sheet, actor_id=ME)
    rows = {row["name"]: row for row in bundle["typed_reactions"]}
    counter = rows["Arrow-Turning Counter"]
    assert counter["kind"] == "ally_hit" and counter.get("forged") and counter["costs"] == [{"resource_id": QI, "amount": 3}]
    assert [e["type"] for e in counter["effects"]][:1] == ["damage_modifier"]  # what Arrow-Turning Breath prints
    assert any(e["type"] == "save" for e in counter["effects"])  # the Minor Hindrance augment, behind its save
    assert "Death Counter" in bundle["diagnostics"]["skipped"]["reaction"]  # no trigger on the record: the GM's
    assert rows["Written Counter"]["kind"] == "hit"  # a trigger written on the record


# ------------------------------------------------------------------------------------------------ 6. gear dropped mid-turn
def test_dropping_or_picking_up_gear_mid_turn_changes_the_movement_left_at_once():
    from tests import test_carry

    bundle = compile_character(test_carry._sheet(), actor_id=test_carry.ME)
    engine = test_carry._fight(bundle)
    me = engine.state.actors[test_carry.ME]
    assert me.movement_remaining_ft == 5  # over capacity: 5 feet
    test_carry._do(engine, "Drop Explorer's Pack")
    assert me.movement_remaining_ft == 30  # 25 more at once, not from next turn
    assert engine.events[-1].event_type == "MOVEMENT_GRANTED" and engine.events[-1].payload["distance_ft"] == 25
    me.movement_remaining_ft = 10  # it walks 20 feet ...
    test_carry._do(engine, "Pick up Explorer's Pack")
    assert me.movement_remaining_ft == 0  # ... and picking the pack up again leaves none (never below zero)


# ------------------------------------------------------------------------------------------------ 7. Dreamscape and Fragrance
def test_dreamscape_is_an_area_its_talents_shape():
    engine = _fight(_sheet(["DREAMS_BASE_DREAMSCAPE", "TAL_DREAM_HALF_WAKING_HAZE", "TAL_DREAM_LUCID_VEIL"], ["tianxia.sphere.dreams"]))
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    assert {"Shape Dreamscape: Half-Waking Haze", "Shape Dreamscape: Lucid Veil", "Shape Dreamscape: plain Dreamscape"} <= _names(engine)
    _do(engine, "Shape Dreamscape: Half-Waking Haze")
    qi = me.resources[QI]
    before = len(engine.events)
    _do(engine, "Dreamscape", at=(10, 6))
    [zone] = zones.typed_zones(engine)
    assert zone.trigger_profile["name"] == "Dreamscape" and zone.trigger_profile["talents"] == ["Half-Waking Haze"] and zone.concentration_link
    assert me.resources[QI] == qi - 1  # "Cost: 1 CP"
    assert zones._inside(engine, foe, zone)
    engine.state.round_number += 1
    zones.on_turn_start(engine, foe)  # "starting its turn inside makes a Wisdom saving throw"
    assert any(e.event_type == "SAVE_ROLLED" for e in engine.events[before:])


def test_the_flower_spheres_fragrance_exists_its_talents_shape_it_it_moves_and_only_one_stands():
    engine = _fight(_sheet(["TAL_FLOWERS_FRAGRANT_VEIL", "TAL_FLOWERS_LINGERING_FRAGRANCE", "TAL_FLOWERS_SOPORIFIC_POLLEN"], ["tianxia.sphere.flowers"]))
    me = engine.state.actors[ME]
    assert {"Fragrance", "Move Fragrance", "Shape Fragrance: Fragrant Veil", "Shape Fragrance: Soporific Pollen"} <= _names(engine) | {"Move Fragrance"}
    _do(engine, "Shape Fragrance: Fragrant Veil")
    _do(engine, "Fragrance + Lingering Fragrance", at=(10, 6))
    [zone] = zones.typed_zones(engine)
    assert zone.trigger_profile["obscured"] == "light" and not zone.concentration_link  # Lightly Obscured; no Concentration
    _do(engine, "Move Fragrance", at=(12, 6))
    [zone] = zones.typed_zones(engine)
    assert (zone.center.x, zone.center.y) == (12, 6)
    engine.state.round_number += 1
    _my_turn(engine)
    me.resources[QI] = 30
    _do(engine, "Fragrance + Lingering Fragrance", at=(6, 12))
    [zone] = zones.typed_zones(engine)  # "you may maintain only one Fragrance at a time"
    assert (zone.center.x, zone.center.y) == (6, 12)


# ------------------------------------------------------------------------------------------------ 8. core maneuvers
ARCHER = {"equipment": [{"starting_kit": {"items": [{"item_id": "tianxia.mortal.weapon.dao"}, {"item_id": "tianxia.mortal.weapon.gong_jian"}]}}],
          "path_and_subpath": {"path_record_ids": ["tianxia.path.body_refining"]}}


def _hit_for_sure(engine):
    engine.state.actors[AN].armor_class = -50  # every roll but a natural 1 hits


def test_batter_is_a_special_attack_that_batters_and_its_exertion_talents_ride_it():
    engine = _fight(_sheet(["TAL_BERSERKER_BATTER", "TAL_BERSERKER_HEAVEN_SHAKING_BATTER"], ["tianxia.sphere.berserker"], **ARCHER), foe_at=(4, 6))
    names = _names(engine)
    assert {"Batter: Dao (Saber / Broadsword)", "Batter: Dao (Saber / Broadsword) + Heaven-Shaking Batter: Knock Prone",
            "Batter: Dao (Saber / Broadsword) + Heaven-Shaking Batter: Difficult Terrain"} <= names
    assert not any(name.startswith("Batter: Gong Jian") for name in names)  # a bow is not a melee or thrown weapon
    _hit_for_sure(engine)
    _do(engine, "Batter: Dao (Saber / Broadsword) + Heaven-Shaking Batter: Difficult Terrain")
    foe = engine.state.actors[AN]
    assert [e for e in engine.events if e.event_type == "ATTACK_ROLLED" and e.payload.get("provisional_hit")]
    assert any(c.condition_id == "condition:typed.battered" for c in foe.conditions.values())
    assert any(z.trigger_profile.get("name") == "Shaken ground" for z in zones.typed_zones(engine))
    bundle = compile_character(_sheet(["TAL_BERSERKER_BATTER", "TAL_BERSERKER_HEAVEN_SHAKING_BATTER"], ["tianxia.sphere.berserker"], **ARCHER), actor_id=ME)
    assert {row["status"] for row in bundle["modifiers"] if row["id"] == "TAL_BERSERKER_HEAVEN_SHAKING_BATTER"} == {"applied"}


def test_snipe_shot_applies_one_snipe_talent_and_is_not_offered_bare():
    engine = _fight(_sheet(["TAL_SNIPER_SNIPER_TRAINING", "TAL_SNIPER_DEADLY_SHOT"], ["tianxia.sphere.sniper"], **ARCHER))
    _do(engine, next(name for name in _names(engine) if name.startswith("Stow Dao")))
    names = _names(engine)
    assert "Snipe Shot: Gong Jian (Bow and Arrow) + Deadly Shot" in names
    assert "Snipe Shot: Gong Jian (Bow and Arrow)" not in names and not any(n.startswith("Snipe Shot: Dao") for n in names)


def test_barrage_opens_a_bonus_action_follow_up_with_the_same_weapon():
    engine = _fight(_sheet(["TAL_BARRAGE_HAMMERING_SHOTS"], ["tianxia.sphere.barrage"], **ARCHER))
    _do(engine, next(name for name in _names(engine) if name.startswith("Stow Dao")))
    assert "Barrage: Gong Jian (Bow and Arrow)" in _names(engine)
    assert "Barrage follow-up: Gong Jian (Bow and Arrow)" not in _names(engine)
    follow = next(row for row in engine.action_catalog.values() if row.display_name == "Barrage follow-up: Gong Jian (Bow and Arrow)")
    assert follow.parameters["typed"]["weapon"]["damage"]["modifier"] == 0  # no positive ability modifier on the follow-up
    _do(engine, "Barrage: Gong Jian (Bow and Arrow)")
    assert "Barrage follow-up: Gong Jian (Bow and Arrow)" in _names(engine)
    _do(engine, "Barrage follow-up: Gong Jian (Bow and Arrow)")
    assert "Barrage follow-up: Gong Jian (Bow and Arrow)" not in _names(engine)


# ------------------------------------------------------------------------------------------------ 8. one of a kind, and two for Focus
def test_counter_talents_are_one_per_counterstrike_not_all_at_once():
    bundle = compile_character(_sheet(["RETRIBUTION_BASE_COUNTERSTRIKE", "TAL_RETRIBUTION_HAYMAKER", "TAL_RETRIBUTION_TERRIFYING_HOOK"],
                                      ["tianxia.sphere.retribution"], **WEAPON), actor_id=ME)
    names = {row["display_name"] for row in bundle["action_catalog"] if row["display_name"].startswith("Counterstrike")}
    assert {"Counterstrike", "Counterstrike + Haymaker", "Counterstrike + Terrifying Hook"} <= names
    rows = {row["name"]: row for row in bundle["modifiers"]}
    assert rows["Haymaker"]["applied"] == [] and rows["Terrifying Hook"]["applied"] == []  # a choice each, never both at once


def test_layered_bouquet_offers_two_fragrance_talents_at_both_costs_plus_its_own():
    engine = _fight(_sheet(["TAL_FLOWERS_FRAGRANT_VEIL", "TAL_FLOWERS_SOPORIFIC_POLLEN", "TAL_FLOWERS_BEGUILING_PERFUME", "TAL_FLOWERS_LAYERED_BOUQUET"],
                           ["tianxia.sphere.flowers"]))
    shapes = {row.display_name: row.parameters.get("shape_costs") for row in engine.action_catalog.values() if row.display_name.startswith("Shape Fragrance")}
    pair = next(name for name in shapes if "Beguiling Perfume" in name and "Soporific Pollen" in name)
    assert shapes[pair] == {QI: 8}  # 4 + 2 + Layered Bouquet's 2
    assert not any("+ Layered Bouquet" in row.display_name for row in engine.action_catalog.values())
    me = engine.state.actors[ME]
    _do(engine, pair)
    qi = me.resources[QI]
    _do(engine, "Fragrance", at=(10, 6))
    [zone] = zones.typed_zones(engine)
    assert sorted(zone.trigger_profile["talents"]) == ["Beguiling Perfume", "Soporific Pollen"] and me.resources[QI] == qi - 8


def test_double_dip_adds_a_second_dirty_trick_effect_for_martial_focus():
    sheet = _sheet(["TAL_SCOUNDREL_DIRTY_TRICK", "TAL_SCOUNDREL_DOUBLE_DIP"], ["tianxia.sphere.scoundrel"], **WEAPON)
    engine = _fight(sheet, foe_at=(4, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    names = _names(engine)
    assert "Double Dip: also Ears Ringing" in names and "DIRTY TRICK: Eyes Spoiled" in names
    _do(engine, "Double Dip: also Ears Ringing")
    for seed_try in range(12):  # a Scoundrel Check can fail; try a few fights until it succeeds
        engine = _fight(sheet, foe_at=(4, 6), seed=f"DIP{seed_try}")
        me, foe = engine.state.actors[ME], engine.state.actors[AN]
        _do(engine, "Double Dip: also Ears Ringing")
        _do(engine, "DIRTY TRICK: Eyes Spoiled")
        if any(c.condition_id == "condition:typed.blinded" for c in foe.conditions.values()):
            break
    assert any(c.condition_id == "condition:typed.blinded" for c in foe.conditions.values())
    assert any(c.condition_id == "condition:typed.deafened" for c in foe.conditions.values()) and me.resources[FOCUS] == 0


# ------------------------------------------------------------------------------------------------ 9. reviewed category rows
def test_reviewed_snipe_talents_ride_the_snipe_shot_hit_and_a_penalty_rides_its_roll():
    bundle = compile_character(_sheet(["TAL_SNIPER_SNIPER_TRAINING", "TAL_SNIPER_DEADLY_SHOT", "TAL_SNIPER_PUSH_SHOT", "TAL_SNIPER_TARGETED_ASSAULT",
                                       "TAL_SNIPER_MERIDIAN_GRAZING_SHOT"], ["tianxia.sphere.sniper"], **ARCHER), actor_id=ME)
    rows = {row["display_name"]: row for row in bundle["action_catalog"] if row["display_name"].startswith("Snipe Shot")}
    typed = rows["Snipe Shot: Gong Jian (Bow and Arrow) + Deadly Shot"]["parameters"]["typed"]
    deadly = next(e for e in typed["effects"] if e["type"] == "attack")
    assert deadly["first_roll_bonus"] == -5 and typed["sniper_deadly_bonus"] == 10
    assert not any(h["type"] == "extra_damage" and h["flat"] == 10 for h in deadly["on_hit"])
    assert rows["Snipe Shot: Gong Jian (Bow and Arrow) + Targeted Assault"]["costs"] == [["resource:core.martial_focus", 1]]
    assert {"Snipe Shot: Gong Jian (Bow and Arrow) + Meridian-Grazing Shot: No Reactions",
            "Snipe Shot: Gong Jian (Bow and Arrow) + Meridian-Grazing Shot: No Healing"} <= set(rows)  # "choose one": one each
    push = next(e for e in rows["Snipe Shot: Gong Jian (Bow and Arrow) + Push Shot"]["parameters"]["typed"]["effects"] if e["type"] == "attack")
    # no Prone unless it hits a wall; the Strength save is the one for a creature more than one size larger (riders lane 4)
    assert [h["type"] for h in push["on_hit"] if h.get("source_modifier")] == ["forced_movement", "save"]


def test_distracting_blades_stops_opportunity_attacks_instead_of_making_another_attack():
    from combat import typed_reactions

    bundle = compile_character(_sheet(["TAL_FENCING_DISTRACTING_BLADES", "TAL_FENCING_ANKLE_STRIKE"], ["tianxia.sphere.the_piercing_needle"], **WEAPON), actor_id=ME)
    exploits = next(row for row in bundle["typed_passives"] if row["block"] == "exploits")["options"]
    blades = next(row for row in exploits if row["name"] == "Distracting Blades")
    assert [e["type"] for e in blades["effects"]] == ["condition"] and blades["effects"][0]["condition"] == "no_opportunity_attacks"

"""Void-Touched Cultivator: native acquisition and the whole CL3 Void Step record.

Every ownership fact here comes from a recorded native acquisition (NS1R
evidence + subpath selection) compiled through combat/authority_projection.py.
No test injects a feature id, a mark, a hit or a Scar into a fight.

Void Step's printed clauses are exercised at the level each one can fail:
native admission, the table commit and cold replay, the destination query, the
crossing prohibitions, the post-payment fallbacks, Trace of Nonexistence (keyed
on the receiving creature), the untouched Grapple, and the default-inert guards.
"""
from pathlib import Path

import pytest

from app.core import Database, FoundryError, Settings
from combat import ext
from combat.authority_projection import compile_project_character, project_sheet
from combat.ext import void_touched_cultivator as void
from combat.ext.teleport_steps import destination_allowed
from combat.factory_compiler import compile_character
from combat.gate2_runtime_models import Position, RuntimeObjectState, ZoneState
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.typed_executor import Context, teleport_subject
from non_sphere_authority import NonSphereAuthorityService
from tests.h1_support import ROOT, sheet
from tests.ns1r_evidence_helpers import ap_award, commit_authority_event, install_authority_test_pack
from tests.test_ns1r_non_sphere_authority import insert_project
from tests.worker2_support import ALLY, FOE, OWNER, candidate, fixture, reload, settle

QI = "tianxia.path.qi_cultivation"
PARENT = "tianxia.subpath.qi.void_touched_cultivator"
STEP = PARENT + ".feature.void_step"
SCAR = "My reflection no longer appears."
VOID_SPHERE = "tianxia.sphere.void"
MARK_PREFIX = "condition:typed.mark.void_mark."


def _build_acquisition(root: Path, cl: int = 3):
    """A real NS1R project with the Secret Law acquired and its Scar recorded."""
    settings = Settings.from_env(ROOT, root / "data")
    settings.ensure_dirs()
    db = Database(settings)
    db.migrate()
    service = NonSphereAuthorityService(db)
    install_authority_test_pack(db, service)
    project = f"void-step-native-{cl}"
    insert_project(db, project, cl)
    service.initialize_for_project(project, target_cl=cl, path_ids=[QI], method_id="METHOD-001")
    service.allocate_advancement(project, {QI: cl - 1},
                                 evidence_id=ap_award(db, service, project, "METHOD-001", cl, cl - 1),
                                 idempotency_key=project + "-advance")
    access = commit_authority_event(db, service, project, "subpath_access",
                                    {"selection_id": PARENT, "path_id": QI})
    state = service.get_state(project)
    state["owned_sphere_record_ids"] = [VOID_SPHERE]
    service.save_state(project, state, operation="record_owned_spheres")
    service.select_subpath(project, QI, PARENT, [access],
                           acquisition_choices={"void_scar": SCAR}, spheres=[VOID_SPHERE])
    service.set_resource(project, QI, current=30, maximum=30)
    return service, project


@pytest.fixture(scope="module")
def acquired(tmp_path_factory):
    return _build_acquisition(tmp_path_factory.mktemp("void-step-acquisition"))


def owner_sheet(service, project, cl=3, *, spheres=(VOID_SPHERE,), name="Void cultivator"):
    state = service.get_state(project)
    doc = sheet([], cl=cl, name=name, dc=50)
    doc.setdefault("spheres_and_talents", {})["sphere_record_ids"] = list(spheres)
    doc["path_and_subpath"] = {"paths": state["paths"]}
    return doc


def bundle(service, project, actor_id, cl=3):
    return compile_project_character(service, project, owner_sheet(service, project, cl),
                                     actor_id=actor_id, reaction_plan={"ask": True})


def step_action(engine, owner_id):
    for action_id in engine.state.actors[owner_id].action_ids:
        action = engine.action_catalog.get(action_id)
        if void.family_source(action) == STEP:
            return action
    raise AssertionError("the owner has no Void Step action")


def marks(actor, owner_id):
    return void.mark_count(actor, owner_id)


# ------------------------------------------------------------------------------------------------ native admission
def test_acquisition_requires_void_sphere_then_records_a_permanent_scar(acquired):
    service, project = acquired
    # A separate project so this test can inspect every refusal on a clean row.
    pid = "void-step-refusals"
    insert_project(service.db, pid, 3)
    service.initialize_for_project(pid, target_cl=3, path_ids=[QI], method_id="METHOD-001")
    service.allocate_advancement(pid, {QI: 2},
                                 evidence_id=ap_award(service.db, service, pid, "METHOD-001", 3, 2),
                                 idempotency_key="void-step-refusals-advance")
    access = commit_authority_event(service.db, service, pid, "subpath_access",
                                    {"selection_id": PARENT, "path_id": QI})
    with pytest.raises(FoundryError) as error:
        service.select_subpath(pid, QI, PARENT, [access])
    assert error.value.code == "NS1R_SUBPATH_PREREQUISITE_UNMET"
    with pytest.raises(FoundryError) as error:
        service.select_subpath(pid, QI, PARENT, [access],
                               acquisition_choices={"void_scar": SCAR},
                               spheres=[VOID_SPHERE])
    assert error.value.code == "NS1R_SUBPATH_PREREQUISITE_UNMET"
    with pytest.raises(FoundryError) as error:
        service.select_subpath(pid, QI, PARENT, [access],
                               acquisition_choices={"void_scar": SCAR},
                               spheres=["tianxia.sphere.fire"])
    assert error.value.code == "NS1R_SUBPATH_PREREQUISITE_UNMET"
    state = service.get_state(pid)
    state["owned_sphere_record_ids"] = [VOID_SPHERE]
    service.save_state(pid, state, operation="record_owned_spheres")
    with pytest.raises(FoundryError) as error:
        service.select_subpath(pid, QI, PARENT, [access], spheres=[VOID_SPHERE])
    assert error.value.code == "ACQUISITION_CHOICE_REQUIRED"
    service.select_subpath(pid, QI, PARENT, [access],
                           acquisition_choices={"void_scar": SCAR}, spheres=[VOID_SPHERE])
    # Cold reload: the choice is persisted, not a caller's tag.
    fresh = NonSphereAuthorityService(service.db)
    state = fresh.get_state(pid)
    row = next(item for item in state["paths"] if item["path_id"] == QI)
    assert row["acquisition_choices"] == {"void_scar": SCAR}
    assert state["permanent_acquisition_choices"][PARENT] == {"void_scar": SCAR}
    with pytest.raises(FoundryError) as error:
        fresh.select_subpath(pid, QI, PARENT, acquisition_choices={"void_scar": "A different scar"},
                             spheres=[VOID_SPHERE])
    assert error.value.code == "ACQUISITION_CHOICE_ALREADY_ESTABLISHED"
    kept = fresh.select_subpath(pid, QI, PARENT)
    path = next(item for item in kept["paths"] if item["path_id"] == QI)
    assert path["acquisition_choices"] == {"void_scar": SCAR}


def test_projection_refuses_a_character_without_the_void_sphere(acquired):
    service, project = acquired
    with pytest.raises(FoundryError) as error:
        project_sheet(service, project, owner_sheet(service, project, spheres=()))
    assert error.value.code == "COMBAT_SUBPATH_PREREQUISITE_UNMET"


def test_native_compile_seals_the_scar_and_only_the_void_step_row(acquired):
    service, project = acquired
    doc = owner_sheet(service, project)
    projected = project_sheet(service, project, doc)
    assert (projected["path_and_subpath"]["acquisition_choices"][PARENT]
            == {"void_scar": SCAR})
    row = bundle(service, project, OWNER)["action_catalog"]
    row = next(action for action in row
               if (action.get("parameters", {}).get("typed") or {}).get("source") == STEP)
    typed = row["parameters"]["typed"]
    assert row["target_kind"] == "SELF" and row["range_ft"] == 30
    assert row["economy"] == "BONUS_ACTION" and list(row["costs"]) == [["resource:core.qi", 2]]
    assert typed["void_scar"] == SCAR and typed["min_cl"] == 3
    assert [effect["type"] for effect in typed["effects"]] == ["teleport"]


# ------------------------------------------------------------------------------------------------ the table flow
def test_void_step_commit_and_cold_reload_spends_qi_and_traces(acquired, tmp_path):
    service, project = acquired
    combat, table, mid = fixture(tmp_path, [], cl=3, owner_bundle=bundle(service, project, OWNER),
                                 named=True, seed="VOID-STEP-TABLE")
    before = reload(tmp_path, mid)
    assert before.state.actors[OWNER].resources["resource:core.qi"] == 30
    action = candidate(combat, mid, "Void Step", at=(3, 4))
    prompts = settle(table, mid, action.candidate_id,
                     picks={"choice:needle.teleport_destination": ["cell:3,4"],
                            "choice:needle.void_step_trace": [ALLY]})
    engine = reload(tmp_path, mid)
    owner, ally = engine.state.actors[OWNER], engine.state.actors[ALLY]
    assert (owner.position.x, owner.position.y) == (3, 4)
    assert owner.resources["resource:core.qi"] == 28
    assert marks(ally, OWNER) == 1
    mark = next(c for c in ally.conditions.values() if c.condition_id.startswith(MARK_PREFIX))
    assert mark.data["count"] == 1 and mark.data["ends_with_scene"] == 1 and mark.expires_on is None
    assert [prompt["context"]["reaction_source_id"] for prompt in prompts] == [
        "choice:needle.teleport_destination", "choice:needle.void_step_trace"]
    assert owner.turn_flags.get(void.USE_FLAG) == void._turn(engine, owner)


def test_void_step_is_refused_once_per_turn_without_spending(acquired, tmp_path):
    service, project = acquired
    combat, table, mid = fixture(tmp_path, [], cl=3, owner_bundle=bundle(service, project, OWNER),
                                 seed="VOID-STEP-ONCE")
    settle(table, mid, candidate(combat, mid, "Void Step", at=(3, 4)).candidate_id,
           picks={"choice:needle.teleport_destination": ["cell:3,4"]})
    engine = reload(tmp_path, mid)
    qi = engine.state.actors[OWNER].resources["resource:core.qi"]
    engine.state.actors[OWNER].bonus_action_available = True  # isolate the printed limit from the Bonus Action
    assert not [row for row in engine.legal_candidates()
                if void.family_source(engine.action_catalog.get(row.source_definition_id)) == STEP]
    assert engine.state.actors[OWNER].resources["resource:core.qi"] == qi


def test_void_step_range_and_occupancy(acquired, tmp_path):
    service, project = acquired
    _, _, mid = fixture(tmp_path, [], cl=3, owner_bundle=bundle(service, project, OWNER), seed="VOID-STEP-RANGE")
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    action = step_action(engine, OWNER)
    occupied = engine.state.actors[ALLY].position
    assert destination_allowed(engine, owner, occupied, 30, action=action) is False
    assert destination_allowed(engine, owner, Position(x=owner.position.x + 7, y=owner.position.y), 30,
                               action=action) is False
    assert destination_allowed(engine, owner, Position(x=owner.position.x, y=owner.position.y - 2), 30,
                               action=action) is True


def test_blindness_and_hidden_destinations_are_refused(acquired, tmp_path):
    """Sight still governs a visible-only destination.

    A blinded traveller, or one whose destination is hidden from it, cannot land
    on a square it can only see. The precisely known alternative is tested apart.
    """
    from combat import zones as zone_rules

    service, project = acquired
    _, _, mid = fixture(tmp_path, [], cl=3, owner_bundle=bundle(service, project, OWNER),
                        positions={OWNER: {"x": 3, "y": 6}, ALLY: {"x": 12, "y": 12}, FOE: {"x": 14, "y": 6}},
                        seed="VOID-STEP-SIGHT")
    engine = reload(tmp_path, mid)
    # An AI seat (the path the printed rule bypassed): no player answers its
    # destination question, so the shared query's own perception checks decide.
    engine.typed_control_modes[OWNER] = "LOCAL_AUTO"
    owner = engine.state.actors[OWNER]
    action = step_action(engine, OWNER)
    target = Position(x=3, y=4)
    # Match start already recorded perceived squares; forget this one so it is visible-only.
    _forget(engine, owner)
    assert void._visible(engine, owner, target) is True
    assert destination_allowed(engine, owner, target, 30, action=action) is True

    engine._apply_condition(owner, "condition:typed.blinded", "action:test.blind", FOE,
                            expires_on=None, data={})
    assert destination_allowed(engine, owner, target, 30, action=action) is False
    engine._remove_condition(owner, "condition:typed.blinded", "action:test.blind")
    assert destination_allowed(engine, owner, target, 30, action=action) is True

    _zone(engine, "zone:test:fog", [target], {"obscured": "heavy"})
    seen = owner.model_copy(update={"position": target, "conditions": {}})
    assert zone_rules.hidden_from(engine, owner, seen) is True
    assert destination_allowed(engine, owner, target, 30, action=action) is False


def test_precisely_known_square_survives_blindness_and_fog(acquired, tmp_path):
    """Void Step's printed "precisely known" alternative is knowledge of the space, not sight of it.

    A square the traveller knows (line of sight from its committed position)
    stays a legal Void Step landing while it is blinded or the square is hidden
    in fog. An ordinary teleport keeps the shared sight rules and is still refused.
    """
    from combat import zones as zone_rules

    service, project = acquired
    _, _, mid = fixture(tmp_path, [], cl=3, owner_bundle=bundle(service, project, OWNER),
                        positions={OWNER: {"x": 3, "y": 6}, ALLY: {"x": 12, "y": 12}, FOE: {"x": 14, "y": 6}},
                        seed="VOID-STEP-KNOWN")
    engine = reload(tmp_path, mid)
    engine.typed_control_modes[OWNER] = "LOCAL_AUTO"
    owner = engine.state.actors[OWNER]
    action = step_action(engine, OWNER)
    target = Position(x=3, y=4)
    assert void.precisely_known(engine, owner, target) is True

    _zone(engine, "zone:test:smoke", [target], {"obscured": "heavy"})
    seen = owner.model_copy(update={"position": target, "conditions": {}})
    assert zone_rules.hidden_from(engine, owner, seen) is True
    engine._apply_condition(owner, "condition:typed.blinded", "action:test.blind", FOE,
                            expires_on=None, data={})
    assert destination_allowed(engine, owner, target, 30, action=action) is True
    # An ordinary teleport (no Void Step action) keeps the shared sight rules.
    assert destination_allowed(engine, owner, target, 30) is False


# ------------------------------------------------------------------------------------------------ crossing prohibitions
def _zone(engine, zone_id, cells, profile, owner=FOE):
    from combat import zones as zone_rules

    engine.state.zones[zone_id] = ZoneState(
        zone_id=zone_id, source_definition_id="action:test.crossing", owner_id=owner,
        center=cells[0], radius_cells=0, affected_cells=tuple(cells), concentration_link=False,
        duration_rounds=10, created_round=engine.state.round_number,
        trigger_profile={"kind": zone_rules.KIND, **profile})
    return engine.state.zones[zone_id]


def test_crossing_prohibitions_use_the_engines_own_facts(acquired, tmp_path):
    service, project = acquired
    _, _, mid = fixture(tmp_path, [], cl=3, owner_bundle=bundle(service, project, OWNER),
                        positions={OWNER: {"x": 2, "y": 6}, ALLY: {"x": 2, "y": 8}, FOE: {"x": 14, "y": 6}},
                        seed="VOID-STEP-CROSS")
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    action = step_action(engine, OWNER)
    start, destination = owner.position, Position(x=5, y=6)

    assert void.crossing_problem(engine, owner, start, destination, action) is None
    # A sealed Formation whose Source CL equals the traveller's.
    _zone(engine, "zone:test:formation", [Position(x=4, y=6)],
          {"formation": {"layers": ["sealing_gate"], "cl": 3, "numbers": {"save_dc": 10}}})
    assert "Formation" in void.crossing_problem(engine, owner, start, destination, action)
    engine.state.zones["zone:test:formation"].trigger_profile["formation"]["cl"] = 2
    assert void.crossing_problem(engine, owner, start, destination, action) is None
    _zone(engine, "zone:test:formation", [Position(x=40, y=40)],
          {"formation": {"layers": ["sealing_gate"], "cl": 3, "numbers": {}}})
    # A sealed barrier / planar boundary expressed as an active zone rule.
    _zone(engine, "zone:test:sealed", [Position(x=4, y=6)], {"rule": {"no_teleport": True}})
    assert "barrier" in void.crossing_problem(engine, owner, start, destination, action)
    engine.state.zones.pop("zone:test:sealed")
    _zone(engine, "zone:test:planar", [Position(x=4, y=6)], {"rule": {"no_extradimensional_movement": True}})
    assert "planar boundary" in void.crossing_problem(engine, owner, start, destination, action)
    engine.state.zones.pop("zone:test:planar")
    # An explicit Secret anti-Void barrier uses its stored Source CL; lower
    # authority does not block, equal authority does.
    anti_void = _zone(engine, "zone:test:anti-void", [Position(x=4, y=6)],
                      {"rule": {"anti_void": True, "source_cl": 2}})
    assert void.crossing_problem(engine, owner, start, destination, action) is None
    anti_void.trigger_profile["rule"]["source_cl"] = 3
    assert "anti-Void" in void.crossing_problem(engine, owner, start, destination, action)
    engine.state.zones.pop("zone:test:anti-void")
    # Artifact prisons are runtime objects, not terrain walls.
    engine.state.objects["object:test:artifact-prison"] = RuntimeObjectState(
        object_id="object:test:artifact-prison", object_kind="ARTIFACT_PRISON",
        position=Position(x=4, y=6), unattended=True, flammable=False,
        destroyed=False, component={"artifact": True, "kind": "prison"})
    assert "artifact prison" in void.crossing_problem(engine, owner, start, destination, action)
    engine.state.objects.pop("object:test:artifact-prison")
    # A spatial lock and an ordinary seal on the traveller.
    engine._apply_condition(owner, "condition:typed.chains_spatial_lock", "action:test.crossing", FOE,
                            expires_on=None, data={"dc": 10, "label": "spatial lock"})
    assert "spatial lock" in void.crossing_problem(engine, owner, start, destination, action)
    engine._remove_condition(owner, "condition:typed.chains_spatial_lock", "action:test.crossing")
    engine._apply_condition(owner, "condition:typed.cannot_teleport", "action:test.crossing", FOE,
                            expires_on=None, data={})
    assert "seal" in void.crossing_problem(engine, owner, start, destination, action)


def test_up_to_five_feet_of_solid_material_is_the_limit(acquired, tmp_path):
    service, project = acquired

    def arena_with(cells):
        def transform(arena):
            arena["terrain_regions"].append({"region_id": "test.wall", "terrain_type": "BLOCKED",
                                             "movement_cost": 0, "description": "test wall",
                                             "cells": [{"x": x, "y": y} for x, y in cells]})
        return transform

    places = {OWNER: {"x": 2, "y": 6}, ALLY: {"x": 12, "y": 12}, FOE: {"x": 14, "y": 6}}
    one = fixture(tmp_path / "one", [], cl=3, owner_bundle=bundle(service, project, OWNER), positions=places,
                  battlefield_transform=arena_with([(4, 6)]), seed="VOID-STEP-WALL-5")
    engine = reload(tmp_path / "one", one[2])
    owner = engine.state.actors[OWNER]
    action = step_action(engine, OWNER)
    # One blocked cell = 5 feet: crossable when the space is precisely known.
    assert void.crossing_problem(engine, owner, owner.position, Position(x=6, y=6), action) is None

    two = fixture(tmp_path / "two", [], cl=3, owner_bundle=bundle(service, project, OWNER), positions=places,
                  battlefield_transform=arena_with([(4, 6), (5, 6)]), seed="VOID-STEP-WALL-10")
    engine = reload(tmp_path / "two", two[2])
    owner = engine.state.actors[OWNER]
    action = step_action(engine, OWNER)
    # Two blocked cells = 10 feet: beyond the printed 5 feet.
    assert "more than 5 feet" in void.crossing_problem(
        engine, owner, owner.position, Position(x=6, y=6), action)


def test_cultivated_walls_are_not_solid_material_void_step_can_cross(acquired, tmp_path):
    """Up to 5 feet of nonartifact, noncultivated solid material (the printed rule).

    A wall an ability raised is cultivated: one blocked square of it, with the
    destination known, still refuses Void Step. Ordinary authored stone is not.
    """
    from combat import zones as zone_rules

    service, project = acquired
    _, _, mid = fixture(tmp_path, [], cl=3, owner_bundle=bundle(service, project, OWNER),
                        positions={OWNER: {"x": 2, "y": 6}, ALLY: {"x": 12, "y": 12}, FOE: {"x": 14, "y": 6}},
                        seed="VOID-STEP-CULTIVATED")
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    action = step_action(engine, OWNER)
    destination = Position(x=6, y=6)
    assert void.crossing_problem(engine, owner, owner.position, destination, action) is None

    _zone(engine, "zone:test:cultivated-wall", [Position(x=4, y=6)],
          {"wall": {"blocks_movement": True, "height_ft": 10, "base_altitude_ft": 0}}, owner=FOE)
    zone_rules.sync_walls(engine)
    assert engine.grid.terrain_at((4, 6, 0), "BLOCKED") is True
    problem = void.crossing_problem(engine, owner, owner.position, destination, action)
    assert problem is not None and "cultivated" in problem
    assert void.void_step_landing(engine, owner, destination, 30, action) is False


def test_anchored_material_blocks_only_equal_or_higher_authority(acquired, tmp_path):
    service, project = acquired

    def arena_with_anchored_stone(anchor):
        def transform(arena):
            arena["terrain_regions"].append({"region_id": "test.anchored-stone", "terrain_type": "OPEN",
                                             "material_only": True, "material": "stone", "movement_cost": 0,
                                             "description": "stone bearing a conceptual anchor",
                                             "cells": [{"x": 4, "y": 6}], "anchor": anchor})
        return transform

    places = {OWNER: {"x": 2, "y": 6}, ALLY: {"x": 12, "y": 12}, FOE: {"x": 14, "y": 6}}
    destination = Position(x=6, y=6)
    lower = fixture(tmp_path / "lower", [], cl=3, owner_bundle=bundle(service, project, OWNER), positions=places,
                    battlefield_transform=arena_with_anchored_stone({"kind": "anti_void", "source_cl": 2}),
                    seed="VOID-STEP-ANCHOR-LOW")
    engine = reload(tmp_path / "lower", lower[2])
    owner = engine.state.actors[OWNER]
    action = step_action(engine, OWNER)
    # Lower-authority anchoring (CL 2) does not stop a CL 3 Void Step.
    assert void.crossing_problem(engine, owner, owner.position, destination, action) is None
    assert void.void_step_landing(engine, owner, destination, 30, action) is True

    equal = fixture(tmp_path / "equal", [], cl=3, owner_bundle=bundle(service, project, OWNER), positions=places,
                    battlefield_transform=arena_with_anchored_stone({"kind": "conceptual_anchoring", "source_cl": 3}),
                    seed="VOID-STEP-ANCHOR-EQ")
    engine = reload(tmp_path / "equal", equal[2])
    owner = engine.state.actors[OWNER]
    action = step_action(engine, OWNER)
    # Equal-authority anchoring in the crossed material blocks the step and the destination.
    assert "anti-Void or conceptual anchor" in void.crossing_problem(
        engine, owner, owner.position, destination, action)
    assert void.void_step_landing(engine, owner, destination, 30, action) is False


# ------------------------------------------------------------------------------------------------ post-payment fallbacks
def _context(engine, actor, action):
    from combat.gate2_runtime_models import ActionIntent

    intent = ActionIntent(intent_id="void-step-test", decision_id="", candidate_id="",
                          state_version=engine.state.state_version, actor_id=actor.entity_id)
    return Context(engine, actor, action, intent, dict(action.parameters["typed"]), [])


def test_nearest_legal_space_and_qis_already_spent(acquired, tmp_path):
    service, project = acquired
    _, _, mid = fixture(tmp_path, [], cl=3, owner_bundle=bundle(service, project, OWNER), seed="VOID-STEP-FALLBACK")
    engine = reload(tmp_path, mid)
    owner, ally = engine.state.actors[OWNER], engine.state.actors[ALLY]
    action = step_action(engine, OWNER)
    # Acceptance pays before resolution; the landing fallback neither refunds nor charges again.
    engine._spend_resource(owner, "resource:core.qi", 2, action.source_definition_id)
    spent = owner.resources["resource:core.qi"]
    teleport_subject(_context(engine, owner, action), owner, ally.position)
    assert owner.resources["resource:core.qi"] == spent
    assert owner.position != ally.position
    assert engine.grid.placement_legal(owner.position, footprint=engine._footprint(owner),
                                       occupied_cells=engine._occupied_cells_except(OWNER))
    assert engine.grid.distance_ft(ally.position, owner.position) <= 10


def test_stays_put_when_no_legal_space_exists_within_ten_feet(acquired, tmp_path):
    service, project = acquired

    def block(arena):
        arena["terrain_regions"].append({"region_id": "test.block", "terrain_type": "BLOCKED", "movement_cost": 0,
                                         "description": "test block",
                                         "cells": [{"x": x, "y": y} for x in range(5, 10) for y in range(4, 9)]})

    _, _, mid = fixture(tmp_path, [], cl=3, owner_bundle=bundle(service, project, OWNER),
                        positions={OWNER: {"x": 2, "y": 6}, ALLY: {"x": 15, "y": 10}, FOE: {"x": 15, "y": 12}},
                        battlefield_transform=block, seed="VOID-STEP-STAY")
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    action = step_action(engine, OWNER)
    start = owner.position
    engine._spend_resource(owner, "resource:core.qi", 2, action.source_definition_id)
    spent = owner.resources["resource:core.qi"]
    teleport_subject(_context(engine, owner, action), owner, Position(x=7, y=6))
    assert owner.position == start
    assert owner.resources["resource:core.qi"] == spent


def test_recovery_lands_only_on_the_destination_side(acquired, tmp_path):
    """The printed fallback is "the nearest legal space on the destination side"."""
    service, project = acquired

    def arena_with(cells):
        def transform(arena):
            arena["terrain_regions"].append({"region_id": "test.far_wall", "terrain_type": "BLOCKED",
                                             "movement_cost": 0, "description": "test wall",
                                             "cells": [{"x": x, "y": y} for x, y in cells]})
        return transform

    walls = ([(5, 4), (5, 5), (5, 7), (5, 8)]
             + [(x, y) for x in (6, 7) for y in range(4, 9)])
    places = {OWNER: {"x": 2, "y": 6}, ALLY: {"x": 5, "y": 6}, FOE: {"x": 15, "y": 12}}

    def spent_mid(path, cells, seed):
        _, _, mid = fixture(path, [], cl=3, owner_bundle=bundle(service, project, OWNER), positions=places,
                            battlefield_transform=arena_with(cells), seed=seed)
        engine = reload(path, mid)
        owner = engine.state.actors[OWNER]
        action = step_action(engine, OWNER)
        engine._spend_resource(owner, "resource:core.qi", 2, action.source_definition_id)
        return engine, owner, action, owner.resources["resource:core.qi"]

    # Every legal square within 10 ft of the occupied destination is nearer the
    # departure space than the destination is: the printed "destination side"
    # refuses them, and Void Step stays put with its Qi already spent.
    engine, owner, action, spent = spent_mid(tmp_path / "near", walls, "VOID-STEP-RECOVERY-NEAR")
    start, destination = owner.position, engine.state.actors[ALLY].position
    assert void.void_step_recovery(_context(engine, owner, action), owner, start, destination) is None
    teleport_subject(_context(engine, owner, action), owner, destination)
    assert owner.position == start
    assert owner.resources["resource:core.qi"] == spent

    # The same destination with one square beyond it free lands there.
    engine, owner, action, _ = spent_mid(tmp_path / "far", [c for c in walls if c != (6, 6)],
                                         "VOID-STEP-RECOVERY-FAR")
    teleport_subject(_context(engine, owner, action), owner, engine.state.actors[ALLY].position)
    assert (owner.position.x, owner.position.y) == (6, 6)


# ------------------------------------------------------------------------------------------------ Trace of Nonexistence
def test_trace_limit_is_keyed_on_the_receiving_creature_only(acquired, tmp_path):
    service, project = acquired
    second = compile_project_character(service, project, owner_sheet(service, project, name="Second Void"),
                                       actor_id=ALLY, reaction_plan={"ask": True})
    plain = compile_character(sheet([], cl=3, name="Target"), actor_id=FOE)
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    bundles = [bundle(service, project, OWNER), second, plain]
    ids = [OWNER, ALLY, FOE]
    arena = combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"]
    places = {OWNER: {"x": 3, "y": 6}, ALLY: {"x": 4, "y": 6}, FOE: {"x": 6, "y": 6}}
    mid = combat._finish_factory_match(
        bundles, ids, {OWNER: "team:factory", ALLY: "team:factory", FOE: "team:opponents"}, places, arena,
        [OWNER, ALLY], [FOE], control_modes={actor: "LOCAL_AUTO" for actor in ids},
        match_seed="VOID-STEP-TWO-USERS", display_name="VOID-STEP-TWO-USERS", maximum_rounds=15)["match_id"]
    engine = combat._load_session(mid).engine
    # Both users act in the same turn interval around the same receiving creature.
    for user, previous, arrival in ((OWNER, Position(x=5, y=6), Position(x=5, y=7)),
                                    (ALLY, Position(x=7, y=6), Position(x=7, y=7))):
        action = step_action(engine, user)
        context = _context(engine, engine.state.actors[user], action)
        ext.run_strict("teleport_settled", context, engine.state.actors[user], previous, arrival, False)
    target = engine.state.actors[FOE]
    assert marks(target, OWNER) == 1
    assert marks(target, ALLY) == 0
    assert len([c for c in target.conditions.values() if c.condition_id.startswith(MARK_PREFIX)]) == 1


def test_trace_stamp_resets_with_each_turn_of_the_user(acquired, tmp_path):
    """One Trace mark per creature per turn: the turn in progress, not the marked creature's clock.

    Within one turn a second Void Step does not mark the same creature again;
    once the user's next turn begins it may.
    """
    service, project = acquired
    _, _, mid = fixture(tmp_path, [], cl=3, owner_bundle=bundle(service, project, OWNER),
                        positions={OWNER: {"x": 3, "y": 6}, ALLY: {"x": 12, "y": 12}, FOE: {"x": 6, "y": 6}},
                        seed="VOID-STEP-TRACE-TURN")
    engine = reload(tmp_path, mid)
    engine.typed_control_modes[OWNER] = "LOCAL_AUTO"
    engine.state.current_actor_id = OWNER
    owner = engine.state.actors[OWNER]
    target = engine.state.actors[FOE]
    context = _context(engine, owner, step_action(engine, OWNER))

    def step():
        ext.run_strict("teleport_settled", context, owner, Position(x=5, y=6), Position(x=5, y=7), False)

    step()
    assert marks(target, OWNER) == 1
    step()
    assert marks(target, OWNER) == 1
    owner.turns_started += 1
    step()
    assert marks(target, OWNER) == 2


def test_void_marks_cap_at_three_per_source_and_end_with_the_scene(acquired, tmp_path):
    service, project = acquired
    from combat.ext.source_records import scene_conditions_end

    _, _, mid = fixture(tmp_path, [], cl=3, owner_bundle=bundle(service, project, OWNER), seed="VOID-STEP-MARKS")
    engine = reload(tmp_path, mid)
    owner, target = engine.state.actors[OWNER], engine.state.actors[FOE]
    action = step_action(engine, OWNER)
    context = _context(engine, owner, action)
    for _ in range(5):
        assert ext.run("mark_apply", context, {"mark": "Void Mark"}, target, None, None)[0] is True
    assert marks(target, OWNER) == 3
    assert len([c for c in target.conditions.values() if c.condition_id.startswith(MARK_PREFIX)]) == 1
    assert marks(target, FOE) == 0
    scene_conditions_end(engine)
    assert marks(target, OWNER) == 0


# ------------------------------------------------------------------------------------------------ Empty Passage
def test_void_step_does_not_carry_a_grappled_creature(acquired, tmp_path):
    service, project = acquired

    def helpless(bundles):
        for row in bundles:
            if row["actor_id"] != OWNER:
                row["actor_template"]["saving_throws"] = {ability: -60 for ability in
                                                          ("STR", "DEX", "CON", "INT", "WIS", "CHA")}

    combat, table, mid = fixture(tmp_path, [], cl=3, owner_bundle=bundle(service, project, OWNER),
                                 bundle_transform=helpless,
                                 positions={OWNER: {"x": 3, "y": 6}, ALLY: {"x": 3, "y": 8}, FOE: {"x": 4, "y": 6}},
                                 seed="VOID-STEP-GRAPPLE")
    settle(table, mid, candidate(combat, mid, "Grapple", target=FOE).candidate_id)
    engine = reload(tmp_path, mid)
    held = next(c for c in engine.state.actors[FOE].conditions.values()
                if c.condition_id == "condition:typed.grappled")
    assert held.source_actor_id == OWNER
    foe_position = engine.state.actors[FOE].position
    settle(table, mid, candidate(combat, mid, "Void Step", at=(3, 4)).candidate_id,
           picks={"choice:needle.teleport_destination": ["cell:3,4"],
                  "choice:needle.void_step_trace": None})
    engine = reload(tmp_path, mid)
    assert (engine.state.actors[OWNER].position.x, engine.state.actors[OWNER].position.y) == (3, 4)
    assert engine.state.actors[FOE].position == foe_position  # the step carried nobody
    # Void Step itself releases nothing. A reach-limited hold may still end by
    # the table's independent Grappled reach rule once the pair separates.
    reasons = {(event.payload or {}).get("reason") for event in engine.events
               if event.event_type == "CONDITION_REMOVED"
               and (event.payload or {}).get("condition_id") == "condition:typed.grappled"}
    assert reasons <= {"OUT_OF_REACH"}


def test_void_step_does_not_release_a_seal_that_blocks_teleportation(acquired, tmp_path):
    service, project = acquired
    _, _, mid = fixture(tmp_path, [], cl=3, owner_bundle=bundle(service, project, OWNER), seed="VOID-STEP-SEAL")
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    action = step_action(engine, OWNER)
    start = owner.position
    engine._apply_condition(owner, "condition:typed.cannot_teleport", "action:test.seal", FOE,
                                   expires_on=None, data={})
    assert void.crossing_problem(engine, owner, start, Position(x=start.x, y=start.y - 2), action)
    teleport_subject(_context(engine, owner, action), owner, Position(x=start.x, y=start.y - 2))
    assert owner.position == start
    assert any(c.condition_id == "condition:typed.cannot_teleport" for c in owner.conditions.values())


# ------------------------------------------------------------------------------------------------ default-inert guards
def test_wrong_owner_and_unrecorded_scar_are_inert(acquired, tmp_path):
    service, project = acquired
    combat, table, mid = fixture(tmp_path, [], cl=3, owner_bundle=bundle(service, project, OWNER),
                                 seed="VOID-STEP-INERT")
    engine = reload(tmp_path, mid)
    ally_actions = [engine.action_catalog[key] for key in engine.state.actors[ALLY].action_ids
                    if key in engine.action_catalog]
    assert not any(void.family_source(action) == STEP for action in ally_actions)
    assert void.family_admission(engine, engine.state.actors[ALLY], None, ally_actions[0]) is None
    # A loose feature id plus a loose top-level scar is not an acquisition.
    loose = sheet([STEP], cl=3)
    loose["path_and_subpath"]["void_scar"] = SCAR
    loose_bundle = compile_character(loose, actor_id=OWNER)
    row = next(action for action in loose_bundle["action_catalog"]
               if (action.get("parameters", {}).get("typed") or {}).get("source") == STEP)
    assert row["parameters"]["typed"]["void_scar"] == ""
    assert row["parameters"]["typed"]["effects"] == []


def test_scar_and_mark_are_visible_through_the_printed_channels(acquired, tmp_path):
    service, project = acquired
    _, _, mid = fixture(tmp_path, [], cl=3, owner_bundle=bundle(service, project, OWNER),
                        ally_talents=("tianxia.path.qi_cultivation.feature.qi_sensing",),
                        positions={OWNER: {"x": 3, "y": 6}, ALLY: {"x": 4, "y": 6}, FOE: {"x": 6, "y": 6}},
                        seed="VOID-STEP-SIGN")
    engine = reload(tmp_path, mid)
    owner, ally, foe = (engine.state.actors[key] for key in (OWNER, ALLY, FOE))
    ext.run("mark_apply", _context(engine, owner, step_action(engine, OWNER)),
            {"mark": "Void Mark"}, foe, None, None)
    facts = ext.run_strict("observer_information", engine, ally)
    text = " ".join(row.get("text") or "" for rows in facts for row in rows)
    assert "Void Scar" in text and SCAR in text
    assert "Void Mark" in text or "Void absence" in text
    assert not any("Void Scar" in (row.get("text") or "")
                   for rows in ext.run_strict("observer_information", engine, foe) for row in rows)


# ------------------------------------------------------------------------------------------------ knowledge record (finding 1)
def _forget(engine, owner):
    """Drop this traveller's remembered squares, leaving only what it perceives from now on."""
    for held in [c for c in owner.conditions.values() if c.condition_id == void.KNOWLEDGE]:
        engine._remove_condition_instance(owner, held.instance_id, void.VOID_STEP, expected=held)


def test_unseen_destination_is_not_precisely_known(acquired, tmp_path):
    """A square never perceived is not "precisely known", whatever the geometry says.

    The square is geometrically clear. Blinded before perceiving it, the traveller
    must not know it; once it can perceive it, it does; a fogged square first
    perceived in fog stays unknown until it is actually seen.
    """
    from combat import zones as zone_rules

    service, project = acquired
    _, _, mid = fixture(tmp_path, [], cl=3, owner_bundle=bundle(service, project, OWNER),
                        positions={OWNER: {"x": 3, "y": 6}, ALLY: {"x": 12, "y": 12}, FOE: {"x": 14, "y": 6}},
                        seed="VOID-STEP-UNSEEN")
    engine = reload(tmp_path, mid)
    engine.typed_control_modes[OWNER] = "LOCAL_AUTO"
    owner = engine.state.actors[OWNER]
    action = step_action(engine, OWNER)
    target = Position(x=3, y=4)
    _forget(engine, owner)

    engine._apply_condition(owner, "condition:typed.blinded", "action:test.blind", FOE,
                            expires_on=None, data={})
    void.record_perception(engine, owner)
    assert void.precisely_known(engine, owner, target) is False
    assert destination_allowed(engine, owner, target, 30, action=action) is False
    engine._remove_condition(owner, "condition:typed.blinded", "action:test.blind")
    void.record_perception(engine, owner)
    assert void.precisely_known(engine, owner, target) is True
    assert destination_allowed(engine, owner, target, 30, action=action) is True

    _forget(engine, owner)
    _zone(engine, "zone:test:unseen-fog", [target], {"obscured": "heavy"})
    seen = owner.model_copy(update={"position": target, "conditions": {}})
    assert zone_rules.hidden_from(engine, owner, seen) is True
    void.record_perception(engine, owner)
    assert void.precisely_known(engine, owner, target) is False
    assert destination_allowed(engine, owner, target, 30, action=action) is False


def test_perceived_square_stays_known_after_occlusion_and_reload(acquired, tmp_path):
    """A square once perceived stays precisely known when a wall later blocks the sight line.

    The knowledge lives in the traveller's record, so it survives the occlusion
    and a cold reload of the saved fight.
    """
    service, project = acquired
    _, _, mid = fixture(tmp_path, [], cl=3, owner_bundle=bundle(service, project, OWNER),
                        positions={OWNER: {"x": 3, "y": 6}, ALLY: {"x": 12, "y": 12}, FOE: {"x": 14, "y": 6}},
                        seed="VOID-STEP-RETAIN")
    engine = reload(tmp_path, mid)
    engine.typed_control_modes[OWNER] = "LOCAL_AUTO"
    owner = engine.state.actors[OWNER]
    action = step_action(engine, OWNER)
    target = Position(x=3, y=4)
    _forget(engine, owner)
    void.record_perception(engine, owner)
    assert void.precisely_known(engine, owner, target) is True

    engine.grid.opaque.add((3, 5))  # a wall now stands between the two squares
    assert void._visible(engine, owner, target) is False
    void.record_perception(engine, owner)
    assert void.precisely_known(engine, owner, target) is True
    assert destination_allowed(engine, owner, target, 30, action=action) is True

    # The match-start record was saved with the fight, so a cold reload still knows the square.
    reloaded = reload(tmp_path, mid)
    assert void.precisely_known(reloaded, reloaded.state.actors[OWNER], target) is True


def test_precisely_known_destination_includes_altitude(acquired, tmp_path):
    """Seeing one elevation must not make the unseen space above/below it precisely known."""
    service, project = acquired
    _, _, mid = fixture(tmp_path, [], cl=3, owner_bundle=bundle(service, project, OWNER),
                        positions={OWNER: {"x": 3, "y": 6}, ALLY: {"x": 12, "y": 12}, FOE: {"x": 14, "y": 6}},
                        seed="VOID-STEP-KNOWN-ALTITUDE")
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    owner.position = Position(x=3, y=6, z=10)
    _forget(engine, owner)
    void.record_perception(engine, owner)

    seen = Position(x=3, y=4, z=10)
    unseen_altitude = Position(x=3, y=4, z=20)
    assert void.precisely_known(engine, owner, seen) is True
    assert void.precisely_known(engine, owner, unseen_altitude) is False


# ------------------------------------------------------------------------------------------------ elevated crossings (finding 2)
def test_elevated_crossing_checks_the_teleport_route_altitude(acquired, tmp_path):
    """Solid matter and anchors are judged at the altitude the traveller crosses, not at ground level.

    Two blocked cells 10-20 feet up are a forbidden crossing for a traveller at
    15 feet. A short ground wall (5 feet) does not touch that route, so the same
    crossing is allowed. An elevated anchored stone of equal authority blocks too.
    """
    service, project = acquired

    def arena_with_region(cells, base, height, material_only=False, anchor=None):
        def transform(arena):
            region = {"region_id": f"test.z{base}.{height}", "terrain_type": "BLOCKED" if not material_only else "OPEN",
                      "movement_cost": 0, "description": "test altitude region", "height_ft": height,
                      "base_altitude_ft": base, "cells": [{"x": x, "y": y} for x, y in cells]}
            if material_only:
                region.update({"material_only": True, "material": "stone", "anchor": anchor})
            arena["terrain_regions"].append(region)
        return transform

    places = {OWNER: {"x": 2, "y": 6}, ALLY: {"x": 12, "y": 12}, FOE: {"x": 14, "y": 6}}
    elevated_start = Position(x=2, y=6, z=3)
    elevated_end = Position(x=6, y=6, z=3)

    def traveller(name, transform):
        _, _, mid = fixture(tmp_path / name, [], cl=3, owner_bundle=bundle(service, project, OWNER),
                            positions=places, battlefield_transform=transform, seed=f"VOID-STEP-{name.upper()}")
        engine = reload(tmp_path / name, mid)
        owner = engine.state.actors[OWNER]
        owner.position = elevated_start
        return engine, owner, step_action(engine, OWNER)

    # Two elevated blocked cells (10-20 ft) on the 15-ft route: more than 5 feet of solid matter.
    engine, owner, action = traveller("high", arena_with_region([(4, 6), (5, 6)], 10, 10))
    assert "more than 5 feet" in void.crossing_problem(engine, owner, elevated_start, elevated_end, action)

    # Two cells of a short ground wall (0-5 ft) do not reach the 15-ft route: the crossing is legal.
    engine, owner, action = traveller("low", arena_with_region([(4, 6), (5, 6)], 0, 5))
    assert void.crossing_problem(engine, owner, elevated_start, elevated_end, action) is None

    # An elevated anchored stone of equal authority (CL 3) on the route blocks the passage.
    engine, owner, action = traveller("anchored", arena_with_region(
        [(4, 6)], 10, 10, material_only=True, anchor={"kind": "anti_void", "source_cl": 3}))
    assert "anti-Void or conceptual anchor" in void.crossing_problem(
        engine, owner, elevated_start, elevated_end, action)

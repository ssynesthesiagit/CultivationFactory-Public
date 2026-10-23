"""Law of Nonexistence (CL18): the whole printed record on the table.

Ownership is a recorded native acquisition (NS1R evidence and the Subpath
selection, with its permanent Void Scar, compiled through
combat/authority_projection.py); no test injects the feature id, a Scar, a mark
or a save result into a fight. Void Marks come from the family's own producer
(``mark_apply`` and Void Step's Trace of Nonexistence through the table).

Covered where each printed clause can fail: the real acquisition, the real Bonus
Action / 8 Qi / once-per-scene activation with a table commit and cold replay,
the 1-minute state (flight and Hover, the all-but-Force/Psychic/Void Resistance
through the real defence pipeline, no Opportunity Attacks, creature space as
Difficult Terrain, the 10 feet of solid material per movement and the turn-end
rule), the inherited Void Step and Empty Palm extended through their public
contracts, the lower-Source-CL targeting and area-placement protection, Return
to Nothing's three target trees and four authority bands with the return
consequences, Empty Heart where the engine models a compelled state, and the
default-inert guards.
"""
import copy
from pathlib import Path

import pytest

from app.core import Database, Settings
from combat import ext, terrain_materials, typed_executor, zones
from combat.authority_projection import compile_project_character, project_sheet
from combat.ext import void_touched_cultivator as void
from combat.ext import void_touched_hollow_field as hf
from combat.ext import void_touched_law as law
from combat.factory_compiler import compile_character
from combat.gate2_runtime_models import ActionDefinition, ActionIntent, EconomyKind, Position, ZoneState
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from non_sphere_authority import NonSphereAuthorityService
from tests import worker2_support as W
from tests.h1_support import ROOT, sheet
from tests.ns1r_evidence_helpers import ap_award, commit_authority_event, install_authority_test_pack
from tests.test_ns1r_non_sphere_authority import insert_project

QI = "tianxia.path.qi_cultivation"
PARENT = "tianxia.subpath.qi.void_touched_cultivator"
LAW = PARENT + ".feature.law_of_nonexistence"
STEP = PARENT + ".feature.void_step"
EMPTY_PALM = PARENT + ".feature.empty_palm"
SCAR = "My reflection no longer appears."
VOID = "tianxia.sphere.void"
NEEDLE = "TAL_VOID_VOID_NEEDLE"
RETURN_NAME = "Return to Nothing (Law of Nonexistence)"
STEP_NAME = "Void Step (Law of Nonexistence"
LAW_NAME = "Law of Nonexistence"
DESTINATION = "choice:needle.teleport_destination"
TRACE = "choice:needle.void_step_trace"
RETURN_PICK = "choice:needle.law_return_target"
SYSTEM_PICK = "choice:needle.law_system"
HOLLOW_FIELD_PICK = "choice:needle.hollow_field"


# ------------------------------------------------------------------------------------------------ a real acquisition
def _build_acquisition(root: Path, cl: int = 18):
    settings = Settings.from_env(ROOT, root / "data")
    settings.ensure_dirs()
    db = Database(settings)
    db.migrate()
    service = NonSphereAuthorityService(db)
    install_authority_test_pack(db, service)
    project = f"law-nonexistence-native-{cl}"
    insert_project(db, project, cl)
    service.initialize_for_project(project, target_cl=cl, path_ids=[QI], method_id="METHOD-001")
    service.allocate_advancement(project, {QI: cl - 1},
                                 evidence_id=ap_award(db, service, project, "METHOD-001", cl, cl - 1),
                                 idempotency_key=project + "-advance")
    access = commit_authority_event(db, service, project, "subpath_access",
                                    {"selection_id": PARENT, "path_id": QI})
    service.select_subpath(project, QI, PARENT, [access],
                           acquisition_choices={"void_scar": SCAR}, spheres=[VOID])
    service.set_resource(project, QI, current=60, maximum=60)
    return service, project


@pytest.fixture(scope="module")
def acquired(tmp_path_factory):
    return _build_acquisition(tmp_path_factory.mktemp("law-nonexistence-acquisition"))


def owner_doc(service, project, cl=18, *, name="Void cultivator"):
    state = service.get_state(project)
    doc = sheet([], cl=cl, name=name, dc=20)
    doc.setdefault("spheres_and_talents", {})["sphere_record_ids"] = [VOID]
    doc["path_and_subpath"] = {"paths": state["paths"]}
    return doc


def owner_bundle(service, project, actor_id=W.OWNER, cl=18):
    return compile_project_character(service, project, owner_doc(service, project, cl),
                                     actor_id=actor_id, reaction_plan={"ask": True})


def duel(tmp_path, service, project, *, foe_cl=18, cha=-50, foe_talents=(), positions=None, owner_speed=30,
         wall=None, seed="LAW-DUEL"):
    """A real match: the acquired CL18 cultivator and a compiled foe at its own printed CL."""
    owner = owner_bundle(service, project)
    foe = compile_character(sheet(list(foe_talents), cl=foe_cl, name="Mara", dc=16), actor_id=W.FOE)
    ally = compile_character(sheet([], cl=18, name="Tobin", dc=16), actor_id=W.ALLY)
    foe["actor_template"]["saving_throws"]["CHA"] = cha
    foe["actor_template"]["maximum_hp"] = 400
    owner["actor_template"]["speed_ft"] = owner_speed
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    arena = copy.deepcopy(combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"])
    if wall:
        arena["terrain_regions"] = [{"region_id": "test.wall", "terrain_type": "BLOCKED", "movement_cost": 0,
                                     "material": "stone", "description": "test wall",
                                     "cells": [{"x": x, "y": y} for x, y in wall]}]
    places = positions or {W.OWNER: {"x": 3, "y": 6}, W.ALLY: {"x": 12, "y": 12}, W.FOE: {"x": 6, "y": 6}}
    mid = combat._finish_factory_match(
        [owner, ally, foe], [W.OWNER, W.ALLY, W.FOE],
        {W.OWNER: "team:factory", W.ALLY: "team:factory", W.FOE: "team:opponents"},
        places, arena, [W.OWNER, W.ALLY], [W.FOE],
        control_modes={actor: "MANUAL" for actor in (W.OWNER, W.ALLY, W.FOE)},
        match_seed=seed, display_name=seed, maximum_rounds=15)["match_id"]
    W.turn(table, mid, W.OWNER)
    return combat, table, mid


def action_of(engine, actor, source):
    return next(engine.action_catalog[key] for key in actor.action_ids
                if law.family_source(engine.action_catalog[key]) == source)


def mark_context(engine, owner, target):
    action = action_of(engine, owner, LAW)
    typed = action.parameters["typed"]
    return typed_executor.Context(engine, owner, action, None,
                                  {"numbers": dict(typed.get("numbers") or {}), "effects": [],
                                   "duration": {"kind": "instant"}, "riders": []}, [target], target, {})


def put_marks(engine, owner, target, number=3):
    ctx = mark_context(engine, owner, target)
    for _ in range(number):
        assert ext.run("mark_apply", ctx, {"mark": "Void Mark"}, target, None, None)[0] is True
    return void.mark_count(target, owner.entity_id)


def return_context(engine, owner, *, target=None, cell=None):
    action = next(engine.action_catalog[key] for key in owner.action_ids if "return_to_nothing" in key)
    destination = cell or Position(x=target.position.x, y=target.position.y, z=target.position.z)
    intent = ActionIntent(intent_id="law-return-test", decision_id="", candidate_id="",
                          state_version=engine.state.state_version, actor_id=owner.entity_id,
                          destination=destination)
    return typed_executor.Context(engine, owner, action, intent, dict(action.parameters["typed"]),
                                  [] if target is None else [target], target, {})


def settle_law(table, combat, mid):
    W.settle(table, mid, W.candidate(combat, mid, LAW_NAME).candidate_id)


def advance_to(table, mid, actor):
    """End turns until ``actor`` is up. The Hollow Field's own choice is declined after its first use so its
    spent Void Marks do not eat the three this test needs."""
    for _ in range(12):
        if table.state(mid)["menu"]["actor_id"] == actor:
            return
        W.settle(table, mid, table.state(mid)["menu"]["end_turn"], decline_after=1)
    raise AssertionError("no turn")


def hosted_action(engine, cl=9, *, source="action:test.law.hostile", area=None, range_ft=120, owner=W.FOE):
    action = ActionDefinition(
        source_definition_id=source, display_name="Hostile effect", owner_id=owner,
        economy=EconomyKind.ACTION, resolution_kind="TYPED", target_kind="HOSTILE_ENTITY", range_ft=range_ft,
        parameters={"harmful": True,
                    "typed": {"effects": [], "numbers": {"cl": cl, "source_cl": cl, "save_dc": 15},
                              "area": area, "duration": {"kind": "instant"}, "riders": []}})
    engine.action_catalog[source] = action
    return action


# ------------------------------------------------------------------------------------------------ what is offered
def test_native_acquisition_compiles_the_whole_record(acquired):
    service, project = acquired
    projected = project_sheet(service, project, owner_doc(service, project))
    assert projected["path_and_subpath"]["acquisition_choices"][PARENT] == {"void_scar": SCAR}
    rows = [(row.get("parameters", {}).get("typed") or {})
            for row in owner_bundle(service, project)["action_catalog"]]
    main = [row for row in rows if row.get("source") == LAW and not row.get("law_return")]
    assert len(main) == 1
    row = main[0]
    assert row["void_scar"] == SCAR and row["min_cl"] == 18
    assert [item["type"] for item in row["effects"]] == ["condition", law.ACTIVATE_EFFECT]
    state = row["effects"][0]["condition_data"]
    assert state["law_of_nonexistence"] == 1 and state["fly_speed_ft"] == 60 and state["flight_hover"] == 1
    assert state["source_cl"] == 18
    assert "FORCE" not in state["rule"]["damage_resistances"] and "FIRE" in state["rule"]["damage_resistances"]
    step_variant = [item for item in rows if item.get("law_void_step")]
    assert len(step_variant) == 1 and step_variant[0]["range_ft"] == 60 and step_variant[0]["void_scar"] == SCAR
    palm = [item for item in rows if item.get("law_empty_palm")]
    assert sorted(item["option_label"] for item in palm) == ["Empty the Meridian", "Hollow the Weapon",
                                                            "Unravel Manifestation"]
    returns = [item for item in rows if item.get("law_return") == 1]
    assert len(returns) == 1 and returns[0]["void_scar"] == SCAR


def test_without_the_acquisition_there_is_no_law_record(acquired):
    service, project = acquired
    loose = sheet([LAW], cl=18, name="Not acquired")
    loose["path_and_subpath"]["void_scar"] = SCAR
    bundle = compile_character(loose, actor_id=W.OWNER)
    typed = [(row.get("parameters", {}).get("typed") or {}) for row in bundle["action_catalog"]]
    law_rows = [item for item in typed if item.get("source") == LAW]
    assert law_rows and all(item["void_scar"] == "" and item["effects"] == [] for item in law_rows)
    assert not [item for item in typed if item.get("law_void_step") or item.get("law_empty_palm")
                or item.get("law_return")]


# ------------------------------------------------------------------------------------------------ the duration's real state
def test_activation_costs_eight_qi_and_commits_the_whole_state(acquired, tmp_path):
    service, project = acquired
    combat, table, mid = duel(tmp_path, service, project)
    before = W.reload(tmp_path, mid)
    assert before.state.actors[W.OWNER].resources["resource:core.qi"] == 60
    settle_law(table, combat, mid)
    engine = W.reload(tmp_path, mid)
    owner = engine.state.actors[W.OWNER]
    # 8 Qi, less the owner's own Golden Core Efficiency refund of 1 for a Qi spend.
    spend = [event for event in engine.events if event.event_type == "RESOURCE_SPENT"
             and event.actor_id == W.OWNER and (event.payload or {}).get("resource_id") == "resource:core.qi"
             and LAW in str(event.source_definition_id)]
    assert spend and int(spend[0].payload.get("amount") or 0) == 8
    refunds = sum(int((event.payload or {}).get("gained") or 0) for event in engine.events
                  if event.event_type == "RESOURCE_GAINED" and event.actor_id == W.OWNER
                  and (event.payload or {}).get("resource_id") == "resource:core.qi")
    assert owner.resources["resource:core.qi"] == 60 - 8 + refunds
    held = law.state(engine, owner)
    assert held is not None and held.expires_on.startswith("START_OF_SLOT_AT:")
    assert law.law_cl(engine, owner) == 18
    from combat import flight
    profile = flight.profile(engine, owner)
    assert (profile.speed_ft, profile.hover) == (60, True)
    rules = [row for row in typed_executor.condition_rules(owner) if row.get("damage_resistances")]
    assert rules and "FORCE" not in rules[0]["damage_resistances"]
    assert "PSYCHIC" not in rules[0]["damage_resistances"] and "VOID" not in rules[0]["damage_resistances"]
    assert "FIRE" in rules[0]["damage_resistances"] and "RADIANT" in rules[0]["damage_resistances"]
    fields = hf.fields(engine)
    assert len(fields) == 1
    field = fields[0]
    assert field.owner_id == W.OWNER and field.trigger_profile["size_ft"] == 30
    assert field.trigger_profile["follows_owner"] is True
    assert (field.center.x, field.center.y) == (owner.position.x, owner.position.y)
    assert field.active is True and not field.concentration_link and owner.concentration is None
    # The table's own defence pipeline halves every printed type and leaves the three exceptions whole.
    from combat import typed_reactions
    assert typed_reactions.defend(engine, owner, 20, "FIRE", LAW, W.FOE) == 10
    assert typed_reactions.defend(engine, owner, 20, "RADIANT", LAW, W.FOE) == 10
    assert typed_reactions.defend(engine, owner, 20, "FORCE", LAW, W.FOE) == 20
    assert typed_reactions.defend(engine, owner, 20, "PSYCHIC", LAW, W.FOE) == 20
    assert typed_reactions.defend(engine, owner, 20, "VOID", LAW, W.FOE) == 20


def test_once_per_scene_is_spent_even_on_a_later_turn(acquired, tmp_path):
    service, project = acquired
    combat, table, mid = duel(tmp_path, service, project)
    settle_law(table, combat, mid)
    engine = W.reload(tmp_path, mid)
    owner = engine.state.actors[W.OWNER]
    owner.action_available = owner.bonus_action_available = True
    qi = owner.resources["resource:core.qi"]
    assert not [c for c in engine.legal_candidates() if c.display_name == LAW_NAME]
    assert owner.resources["resource:core.qi"] == qi


def test_ending_the_law_early_ends_every_derived_effect(acquired, tmp_path):
    service, project = acquired
    combat, table, mid = duel(tmp_path, service, project)
    settle_law(table, combat, mid)
    engine = W.reload(tmp_path, mid)
    owner = engine.state.actors[W.OWNER]
    assert hf.fields(engine)
    engine._remove_condition(owner, law.LAW_CONDITION, LAW)
    from combat import flight
    assert hf.fields(engine) == []
    assert flight.profile(engine, owner).speed_ft == 0
    assert not [row for row in typed_executor.condition_rules(owner) if row.get("damage_resistances")]
    assert law.active(engine, owner) is False
    assert law.law_creature_passage(engine, owner, engine.state.actors[W.FOE]) is None


# ------------------------------------------------------------------------------------------------ inherited records extended
def test_void_step_becomes_free_and_sixty_feet_through_the_inherited_provider(acquired, tmp_path):
    service, project = acquired
    combat, table, mid = duel(tmp_path, service, project)
    settle_law(table, combat, mid)
    engine = W.reload(tmp_path, mid)
    owner = engine.state.actors[W.OWNER]
    engine.state.current_slot_index = engine.state.initiative_order.index(W.OWNER)
    engine.state.current_actor_id = W.OWNER
    owner.bonus_action_available = True
    offers = [c for c in engine.legal_candidates() if "Void Step" in c.display_name]
    assert offers and all(c.display_name.startswith(STEP_NAME) for c in offers)
    variant = next(a for key, a in engine.action_catalog.items() if key in owner.action_ids
                   and (a.parameters or {}).get("law_void_step"))
    assert list(variant.costs) == [] and variant.range_ft == 60
    assert variant.parameters["typed"]["source"] == STEP
    from combat.typed_executor import teleport_reach
    assert teleport_reach(engine, owner, variant) == 60
    printed = next(a for key, a in engine.action_catalog.items() if key in owner.action_ids
                   and (a.parameters or {}).get("typed", {}).get("source") == STEP
                   and not (a.parameters or {}).get("law_void_step"))
    assert list(printed.costs) == [("resource:core.qi", 2)] and teleport_reach(engine, owner, printed) == 30
    # Without the Law the printed 2 Qi / 30 feet row is the one offered.
    engine._remove_condition(owner, law.LAW_CONDITION, LAW)
    owner.bonus_action_available = True
    plain = [c.display_name for c in engine.legal_candidates() if "Void Step" in c.display_name]
    assert plain and all(name.startswith("Void Step to ") for name in plain)


def test_empty_palm_is_offered_as_a_bonus_action_once_per_turn(acquired, tmp_path):
    service, project = acquired
    combat, table, mid = duel(tmp_path, service, project)
    settle_law(table, combat, mid)
    engine = W.reload(tmp_path, mid)
    owner = engine.state.actors[W.OWNER]
    owner.bonus_action_available = True
    variant = next(a for key, a in engine.action_catalog.items() if key in owner.action_ids
                   and (a.parameters or {}).get("law_empty_palm"))
    assert variant.economy.value == "BONUS_ACTION" and variant.parameters["typed"]["source"] == EMPTY_PALM
    inherited = next(a for key, a in engine.action_catalog.items() if key in owner.action_ids
                     and (a.parameters or {}).get("typed", {}).get("source") == EMPTY_PALM
                     and not (a.parameters or {}).get("law_empty_palm"))
    assert inherited.parameters["typed"]["effects"] == variant.parameters["typed"]["effects"]
    assert law.law_entry(engine, owner, None, variant) is None
    owner.turn_flags["_law_empty_palm_turn"] = law._turn(engine, owner)
    assert law.law_entry(engine, owner, None, variant) is False
    # An ordinary Empty Palm row is never vetoed by the bonus-action flag.
    assert law.law_entry(engine, owner, None, inherited) is None


def test_creature_space_is_difficult_and_no_opportunity_attack_is_made(acquired, tmp_path):
    service, project = acquired
    combat, table, mid = duel(tmp_path, service, project)
    settle_law(table, combat, mid)
    engine = W.reload(tmp_path, mid)
    owner, foe = engine.state.actors[W.OWNER], engine.state.actors[W.FOE]
    assert law.law_creature_passage(engine, owner, foe) == "difficult"
    assert law.law_creature_passage(engine, foe, owner) is None
    assert ext.any_false("opportunity_allowed", engine, foe, owner) is True
    assert ext.any_false("opportunity_allowed", engine, owner, foe) is False


# ------------------------------------------------------------------------------------------------ solid material and the turn end
def test_solid_material_caps_at_ten_feet_per_movement(acquired, tmp_path):
    service, project = acquired
    wall = [(x, y) for x in (4, 5, 6) for y in range(14)]
    combat, table, mid = duel(tmp_path, service, project, owner_speed=60, wall=wall, seed="LAW-WALL",
                              positions={W.OWNER: {"x": 3, "y": 6}, W.ALLY: {"x": 12, "y": 12},
                                         W.FOE: {"x": 14, "y": 6}})
    engine = W.reload(tmp_path, mid)
    owner = engine.state.actors[W.OWNER]
    assert terrain_materials.profile(engine, owner, law.MODE) is None
    settle_law(table, combat, mid)
    engine = W.reload(tmp_path, mid)
    owner = engine.state.actors[W.OWNER]
    assert terrain_materials.profile(engine, owner, law.MODE) is not None
    assert law.law_solid_passage(engine, engine.state.actors[W.FOE]) is None
    assert law.law_solid_limit(engine, owner, Position(x=3, y=6), Position(x=4, y=6), None) is None
    engine.__dict__[law._solid_key(owner)] = 10
    stop = law.law_solid_limit(engine, owner, Position(x=5, y=6), Position(x=6, y=6), None)
    assert stop and stop["stop"] is True
    # The authored band is crossable only through the material, and the real move stops at ten feet.
    through = [c for c in engine.legal_candidates()
               if "MOVE" in str(getattr(c.kind, "value", c.kind)) and c.destination
               and (c.destination.x, c.destination.y, c.destination.z) == (6, 6, 0)]
    assert through, "the printed passage is offered"
    W.settle(table, mid, through[0].candidate_id)
    engine = W.reload(tmp_path, mid)
    owner = engine.state.actors[W.OWNER]
    assert law._solid_cells(engine, owner, owner.position), "the move ends inside the material it crossed"


def test_turn_end_inside_solid_material_moves_out_and_deals_force(acquired, tmp_path):
    service, project = acquired
    wall = [(x, y) for x in (4, 5, 6) for y in range(14)]
    combat, table, mid = duel(tmp_path, service, project, owner_speed=60, wall=wall, seed="LAW-TURNEND",
                              positions={W.OWNER: {"x": 3, "y": 6}, W.ALLY: {"x": 12, "y": 12},
                                         W.FOE: {"x": 14, "y": 6}})
    settle_law(table, combat, mid)
    engine = W.reload(tmp_path, mid)
    owner = engine.state.actors[W.OWNER]
    through = [c for c in engine.legal_candidates()
               if "MOVE" in str(getattr(c.kind, "value", c.kind)) and c.destination
               and (c.destination.x, c.destination.y, c.destination.z) == (6, 6, 0)]
    W.settle(table, mid, through[0].candidate_id)
    engine = W.reload(tmp_path, mid)
    owner = engine.state.actors[W.OWNER]
    assert law._solid_cells(engine, owner, owner.position)
    inside = owner.position
    hp = owner.current_hp
    W.settle(table, mid, table.state(mid)["menu"]["end_turn"])
    engine = W.reload(tmp_path, mid)
    owner = engine.state.actors[W.OWNER]
    assert not law._solid_cells(engine, owner, owner.position)
    assert owner.position != inside
    assert owner.current_hp < hp
    damage = [event for event in engine.events
              if event.event_type == "DAMAGE_COMMITTED" and W.OWNER in (event.target_ids or ())]
    assert damage and damage[-1].payload.get("damage_type", "").upper() == "FORCE"
    assert 5 <= hp - owner.current_hp  # 5d10 has no resistance here (Force is not on the law's list)


# ------------------------------------------------------------------------------------------------ targeting and placement
def test_equal_authority_can_discover_and_select_absent_target(acquired, tmp_path):
    service, project = acquired
    combat, table, mid = duel(tmp_path, service, project)
    settle_law(table, combat, mid)
    engine = W.reload(tmp_path, mid)
    owner, foe, ally = (engine.state.actors[key] for key in (W.OWNER, W.FOE, W.ALLY))
    assert put_marks(engine, owner, foe) == 3
    law.return_to_nothing(return_context(engine, owner, target=foe), {})

    # Authority is a capability of an owned action, not a generic hidden-target
    # bypass. The discovered target remains selectable only by that same tier.
    access = hosted_action(engine, 18, source="action:test.law.authority", owner=W.OWNER)
    access.parameters["typed"].update(authority_categories=["void"])
    owner.action_ids.append(access.source_definition_id)
    ordinary = hosted_action(engine, 18, source="action:test.law.ordinary", owner=W.ALLY)
    from combat import senses, recipients
    assert foe.entity_id not in senses.perception(engine, ally)["creatures"]
    assert foe.entity_id in senses.perception(engine, owner)["creatures"]
    assert recipients.allowed(engine, owner, foe, access) is True
    assert recipients.allowed(engine, ally, foe, ordinary) is False

    low = hosted_action(engine, 17, source="action:test.law.lower", owner=W.OWNER)
    low.parameters["typed"].update(authority_categories=["void"])
    assert foe.entity_id in senses.perception(engine, owner)["creatures"]
    assert recipients.allowed(engine, owner, foe, low) is False


def test_lower_source_cl_cannot_target_the_user(acquired, tmp_path):
    service, project = acquired
    combat, table, mid = duel(tmp_path, service, project)
    settle_law(table, combat, mid)
    engine = W.reload(tmp_path, mid)
    owner, foe = engine.state.actors[W.OWNER], engine.state.actors[W.FOE]
    from combat import recipients
    low = hosted_action(engine, 9)
    equal = hosted_action(engine, 18, source="action:test.law.equal")
    assert recipients.allowed(engine, foe, owner, low) is False
    assert recipients.allowed(engine, foe, owner, equal) is True
    assert law.law_untargetable(engine, owner, foe, low) is None       # allies' and own actions are untouched
    assert law.law_untargetable(engine, foe, owner, None) is None
    engine._remove_condition(owner, law.LAW_CONDITION, LAW)
    assert law.law_untargetable(engine, foe, owner, low) is None


def test_lower_cl_hostile_area_can_be_placed_elsewhere_so_it_excludes_the_user(acquired, tmp_path):
    service, project = acquired
    combat, table, mid = duel(tmp_path, service, project)
    settle_law(table, combat, mid)
    engine = W.reload(tmp_path, mid)
    owner, foe = engine.state.actors[W.OWNER], engine.state.actors[W.FOE]
    action = hosted_action(engine, 9, area={"shape": "sphere", "size_ft": 20})
    ctx = typed_executor.Context(engine, foe, action, None, dict(action.parameters["typed"]), [], None)
    zone = zones.prospective_zone(ctx, {"name": "Hostile area", "shape": "sphere", "size_ft": 20,
                                        "triggers": [], "visual": {}},
                                  Position(x=owner.position.x, y=owner.position.y), zone_id="zone:test:hostile")
    assert any((cell.x, cell.y) == (owner.position.x, owner.position.y) for cell in zone.affected_cells)
    refined = law.law_zone_excludes_user(zone, ctx)
    assert refined is not None
    assert not any((cell.x, cell.y) == (owner.position.x, owner.position.y) for cell in refined.affected_cells)
    row = {"type": "damage", "applies_to": "enemies_in_area"}
    assert law.law_area_excludes_user(ctx, row, owner) is False
    # With no other legal placement (range 0) the printed protection cannot apply.
    fixed = action.model_copy(update={"range_ft": 0})
    fixed_ctx = typed_executor.Context(engine, foe, fixed, None, dict(fixed.parameters["typed"]), [], None)
    assert law.law_zone_excludes_user(zone, fixed_ctx) is None


# ------------------------------------------------------------------------------------------------ Return to Nothing
def test_return_to_nothing_through_the_table_commits_and_reloads(acquired, tmp_path):
    service, project = acquired
    combat, table, mid = duel(tmp_path, service, project, foe_talents=(NEEDLE,), seed="LAW-RETURN",
                              positions={W.OWNER: {"x": 3, "y": 6}, W.ALLY: {"x": 12, "y": 12},
                                         W.FOE: {"x": 3, "y": 8}})
    settle_law(table, combat, mid)
    W.settle(table, mid, table.state(mid)["menu"]["end_turn"], decline_after=1)
    # Three real Void Steps with Trace of Nonexistence place the three printed marks.
    for index, at in enumerate(((3, 7), (3, 6), (3, 7))):
        advance_to(table, mid, W.OWNER)
        engine = W.reload(tmp_path, mid)
        steps = [c for c in engine.legal_candidates() if c.display_name.startswith(STEP_NAME)
                 and c.destination and (c.destination.x, c.destination.y) == at]
        assert steps
        W.settle(table, mid, steps[0].candidate_id,
                 picks={DESTINATION: [f"cell:{at[0]},{at[1]}"], TRACE: [W.FOE]})
        W.settle(table, mid, table.state(mid)["menu"]["end_turn"], decline_after=1)
    advance_to(table, mid, W.OWNER)
    engine = W.reload(tmp_path, mid)
    owner, foe = engine.state.actors[W.OWNER], engine.state.actors[W.FOE]
    assert void.mark_count(foe, W.OWNER) == 3
    offers = [c for c in engine.legal_candidates() if c.display_name.startswith(RETURN_NAME)]
    assert [(c.destination.x, c.destination.y) for c in offers] == [(foe.position.x, foe.position.y)]
    prompts = W.settle(table, mid, offers[0].candidate_id, picks={RETURN_PICK: [W.FOE]})
    assert [p["context"]["reaction_source_id"] for p in prompts] == [RETURN_PICK]
    engine = W.reload(tmp_path, mid)
    owner, foe = engine.state.actors[W.OWNER], engine.state.actors[W.FOE]
    absent = next(c for c in foe.conditions.values() if c.condition_id == "condition:typed.spatial_absence")
    assert absent.expires_on.startswith("END_OF_TURN_AT:")
    assert absent.data["law_repeat_check"] == 1 and absent.data["law_repeat_dc"] == 20
    assert any(c.condition_id == "condition:typed.no_cp_regain" for c in foe.conditions.values())
    assert any(c.condition_id == "condition:typed.spatial_return" for c in foe.conditions.values())
    assert (law.state(engine, owner).data or {}).get("return_used") == 1
    assert not [c for c in foe.conditions.values() if c.condition_id == law.SYSTEM_CONDITION]


def test_return_to_nothing_returns_with_zero_cp_and_one_suppressed_system(acquired, tmp_path):
    service, project = acquired
    combat, table, mid = duel(tmp_path, service, project, foe_talents=(NEEDLE,), seed="LAW-RETURN-BACK")
    settle_law(table, combat, mid)
    engine = W.reload(tmp_path, mid)
    owner, foe = engine.state.actors[W.OWNER], engine.state.actors[W.FOE]
    assert put_marks(engine, owner, foe) == 3
    foe.resources["resource:core.qi"] = 15
    law.return_to_nothing(return_context(engine, owner, target=foe), {})
    # The interval ends: the inherited spatial_absence return path runs the printed consequences.
    engine._remove_condition(foe, "condition:typed.spatial_absence", "test:expiry")
    assert foe.resources["resource:core.qi"] == 0
    suppressed = [c for c in foe.conditions.values() if c.condition_id == law.SYSTEM_CONDITION]
    assert len(suppressed) == 1
    assert suppressed[0].data["kind"] in {"sphere", "subpath", "method"}
    assert suppressed[0].data["rows"]
    assert suppressed[0].expires_on.startswith("END_OF_TURN_AT:")
    # Its other systems keep working: only the chosen one's candidates are withheld.
    from combat.ext import ability_lockout
    assert not ability_lockout.barred(engine, foe, None, None)


def test_return_to_nothing_successful_save_is_the_printed_package(acquired, tmp_path):
    service, project = acquired
    combat, table, mid = duel(tmp_path, service, project, foe_talents=(NEEDLE,), cha=80, seed="LAW-RETURN-SAVE")
    settle_law(table, combat, mid)
    engine = W.reload(tmp_path, mid)
    owner, foe = engine.state.actors[W.OWNER], engine.state.actors[W.FOE]
    assert put_marks(engine, owner, foe) == 3
    foe.resources["resource:core.qi"] = 20
    hp = foe.current_hp
    law.return_to_nothing(return_context(engine, owner, target=foe), {})
    assert 6 <= hp - foe.current_hp <= 48  # 6d8 Void
    assert foe.resources["resource:core.qi"] == 20 - 2 * int(foe.proficiency_bonus)
    assert any(c.condition_id == "condition:typed.reaction_denied" for c in foe.conditions.values())
    assert any(c.condition_id == law.SYSTEM_CONDITION for c in foe.conditions.values())


@pytest.mark.parametrize("foe_cl,prefix", [(20, "END_OF_TURN_AT:"), (15, "START_OF_SLOT_AT:"),
                                           (12, "UNTIL_REMOVED"), (21, "START_OF_TURN_AT:")])
def test_return_to_nothing_duration_follows_the_authority_bands(acquired, tmp_path, foe_cl, prefix):
    service, project = acquired
    combat, table, mid = duel(tmp_path, service, project, foe_cl=foe_cl, seed=f"LAW-BAND-{foe_cl}")
    settle_law(table, combat, mid)
    engine = W.reload(tmp_path, mid)
    owner, foe = engine.state.actors[W.OWNER], engine.state.actors[W.FOE]
    assert put_marks(engine, owner, foe) == 3
    law.return_to_nothing(return_context(engine, owner, target=foe), {})
    absent = [c for c in foe.conditions.values() if c.condition_id == "condition:typed.spatial_absence"]
    assert absent and absent[0].expires_on.startswith(prefix), absent and absent[0].expires_on


def test_return_to_nothing_erases_a_lower_cl_manifestation_and_object(acquired, tmp_path):
    service, project = acquired
    combat, table, mid = duel(tmp_path, service, project, seed="LAW-MANIFEST")
    settle_law(table, combat, mid)
    engine = W.reload(tmp_path, mid)
    owner = engine.state.actors[W.OWNER]
    weak = compile_character(sheet([NEEDLE], cl=9, name="Weak"), actor_id=W.FOE)
    weak_row = next(row for row in weak["action_catalog"]
                    if (row.get("parameters", {}).get("typed") or {}).get("source") == NEEDLE)
    source = weak_row["source_definition_id"]
    engine.action_catalog[source] = ActionDefinition.model_validate(weak_row)
    zone = ZoneState(zone_id="zone:test:manifestation", source_definition_id=source, owner_id=W.FOE,
                     center=Position(x=owner.position.x, y=owner.position.y + 2), radius_cells=1,
                     affected_cells=(Position(x=owner.position.x, y=owner.position.y + 2),), concentration_link=False,
                     duration_rounds=10, created_round=engine.state.round_number,
                     trigger_profile={"kind": zones.KIND, "shape": "sphere", "size_ft": 5,
                                      "numbers": {"cl": 9, "source_cl": 9}})
    engine.state.zones[zone.zone_id] = zone
    law.return_to_nothing(return_context(engine, owner, cell=zone.affected_cells[0]), {})
    assert engine.state.zones[zone.zone_id].active is False
    from combat.gate2_runtime_models import RuntimeObjectState
    obj = RuntimeObjectState(object_id="object:law-test", object_kind="BARRIER",
                             position=Position(x=owner.position.x, y=owner.position.y + 3),
                             unattended=True, flammable=False, ac=10, current_hp=5, maximum_hp=5,
                             component={"source_definition_id": source})
    engine.state.objects[obj.object_id] = obj
    law.return_to_nothing(return_context(engine, owner, cell=obj.position), {})
    assert engine.state.objects[obj.object_id].destroyed is True


def test_empty_heart_refuses_a_lower_cl_compelled_state(acquired, tmp_path):
    service, project = acquired
    combat, table, mid = duel(tmp_path, service, project)
    settle_law(table, combat, mid)
    engine = W.reload(tmp_path, mid)
    owner = engine.state.actors[W.OWNER]
    action = hosted_action(engine, 9)
    ctx = typed_executor.Context(engine, engine.state.actors[W.FOE], action, None,
                                  dict(action.parameters["typed"]), [owner], owner, {})
    assert law.law_empty_heart_condition(ctx, owner, {"condition": "charmed"}) is False
    assert law.law_empty_heart_condition(ctx, owner, {"condition": "grappled"}) is None
    action.parameters["typed"]["numbers"].update(cl=18, source_cl=18)
    assert law.law_empty_heart_condition(ctx, owner, {"condition": "charmed"}) is None
    assert law.law_empty_heart_condition(ctx, engine.state.actors[W.FOE], {"condition": "charmed"}) is None


def test_default_inert_for_another_creature(acquired, tmp_path):
    service, project = acquired
    combat, table, mid = duel(tmp_path, service, project)
    settle_law(table, combat, mid)
    engine = W.reload(tmp_path, mid)
    foe, owner = engine.state.actors[W.FOE], engine.state.actors[W.OWNER]
    assert law.active(engine, foe) is False and law.owns(engine, foe) is False
    assert law.law_creature_passage(engine, foe, owner) is None
    assert law.law_no_opportunity_attack(engine, owner, foe) is None
    assert law.law_untargetable(engine, owner, foe, None) is None
    assert law.law_solid_passage(engine, foe) is None
    assert law.law_empty_heart_condition(typed_executor.Context(engine, owner, None, None, {}, [foe], foe, {}),
                                         foe, {"condition": "charmed"}) is None

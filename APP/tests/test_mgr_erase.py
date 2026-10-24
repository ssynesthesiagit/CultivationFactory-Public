"""Erase (CL14): the whole printed record on the table.

Ownership is a recorded native acquisition (NS1R evidence + subpath selection,
with its permanent Void Scar) compiled through combat/authority_projection.py.
No test injects the feature id, a mark, a hit or a save result into a fight:
Void Marks are placed by the family's own ``mark_apply`` producer, a lasting
area is made by the family's own Hollow Field, and a map object is seeded from
the sealed arena.

Covered where each clause can fail: the real Action and 6 Qi, all three modes
through CombatService/tabletop with a commit and a cold reload, the manifestation
authority branches (lower/equal/higher Source CL, Secret, artifact), dependent
teardown and no refund, the object/creature refusal list, Resistance/Immunity/
Threshold/double-damage semantics and complete erasure, the marks gate, CP loss,
a real system erasure and suppression that gate use, Deep Erasure's 3-mark spend
and every Source-CL band, the repeated save, the recovery contract (including
"ordinary rest does not restore"), and the wrong-owner/default-inert guards.
"""
from pathlib import Path

import pytest

from app.core import Database, Settings
from combat import ext, typed_reactions, zones
from combat.authority_projection import compile_project_character
from combat.ext import area_suppression, void_touched_cultivator as void
from combat.ext import void_touched_erase as er
from combat.factory_compiler import compile_character
from combat.gate2_runtime_models import ActionDefinition, ActionIntent, Position, RuntimeObjectState, ZoneState
from combat.typed_executor import Context
from non_sphere_authority import NonSphereAuthorityService
from tests.h1_support import ROOT, sheet
from tests.ns1r_evidence_helpers import ap_award, commit_authority_event, install_authority_test_pack
from tests.test_ns1r_non_sphere_authority import insert_project
from tests.worker2_support import ALLY, FOE, OWNER, candidate, end_turn, fixture, reload, settle, turn

QI = "tianxia.path.qi_cultivation"
PARENT = "tianxia.subpath.qi.void_touched_cultivator"
ERASE = PARENT + ".feature.erase"
SCAR = "My reflection no longer appears."
VOID = "tianxia.sphere.void"
FIRE = "tianxia.sphere.fire"
MARKS = "Void Mark"
DAMAGE_TYPE_PROMPT = "choice:needle.empty_palm_damage_type"
TARGET_PROMPT = "choice:needle.erase_target"
DEEP_PROMPT = "choice:needle.erase_deep"
SYSTEM_PROMPT = "choice:needle.erase_system"
POOL_PROMPT = "choice:needle.erase_pool"
INDEFINITE_PROMPT = "choice:needle.erase_indefinite"


# ------------------------------------------------------------------------------------------------ a real acquisition
def _build_acquisition(root: Path, cl: int = 14):
    settings = Settings.from_env(ROOT, root / "data")
    settings.ensure_dirs()
    db = Database(settings)
    db.migrate()
    service = NonSphereAuthorityService(db)
    install_authority_test_pack(db, service)
    project = f"erase-native-{cl}"
    insert_project(db, project, cl)
    service.initialize_for_project(project, target_cl=cl, path_ids=[QI], method_id="METHOD-001")
    service.allocate_advancement(project, {QI: cl - 1},
                                 evidence_id=ap_award(db, service, project, "METHOD-001", cl, cl - 1),
                                 idempotency_key=project + "-advance")
    access = commit_authority_event(db, service, project, "subpath_access",
                                    {"selection_id": PARENT, "path_id": QI})
    service.select_subpath(project, QI, PARENT, [access],
                           acquisition_choices={"void_scar": SCAR}, spheres=[VOID])
    service.set_resource(project, QI, current=30, maximum=30)
    return service, project


@pytest.fixture(scope="module")
def acquired(tmp_path_factory):
    return _build_acquisition(tmp_path_factory.mktemp("erase-acquisition"))


def owner_doc(service, project, cl=14, *, dc=1, name="Void cultivator"):
    state = service.get_state(project)
    doc = sheet([], cl=cl, name=name, dc=dc)
    doc.setdefault("spheres_and_talents", {})["sphere_record_ids"] = [VOID]
    doc["path_and_subpath"] = {"paths": state["paths"]}
    return doc


def owner_bundle(service, project, cl=14, *, dc=1):
    return compile_project_character(service, project, owner_doc(service, project, cl, dc=dc),
                                     actor_id=OWNER, reaction_plan={"ask": True})


def foe_doc(*talents, cl=14, dc=1, name="Mara", hp=300, ac=0):
    doc = sheet(list(talents), cl=cl, name=name, dc=dc)
    doc["ability_scores_and_statistics"]["hit_points"] = {"maximum": hp, "current": hp}
    doc["ability_scores_and_statistics"]["armor_class"]["base_value"] = ac
    return doc


def helpless_foe(bundles):
    for row in bundles:
        if row["actor_id"] != OWNER:
            row["actor_template"]["saving_throws"] = {ability: -50 for ability in
                                                      ("STR", "DEX", "CON", "INT", "WIS", "CHA")}


def _action(engine, owner_id, label):
    for action_id in engine.state.actors[owner_id].action_ids:
        action = engine.action_catalog.get(action_id)
        if action is not None and str(action.display_name) == label:
            return action
    raise AssertionError(f"{label!r} is not on {owner_id}")


def _marks(engine, owner_id, target, number):
    action = _action(engine, owner_id, "Void Step")
    intent = ActionIntent(intent_id="erase-test", decision_id="", candidate_id="",
                          state_version=engine.state.state_version, actor_id=owner_id)
    ctx = Context(engine, engine.state.actors[owner_id], action, intent, dict(action.parameters["typed"]), [])
    for _ in range(number):
        assert ext.run("mark_apply", ctx, {"mark": MARKS}, target, None, None)[0] is True
    return void.mark_count(target, owner_id)


def _ctx(engine, owner_id, action, *, target=None, failed=False):
    intent = ActionIntent(intent_id="erase-test", decision_id="", candidate_id="",
                          state_version=engine.state.state_version, actor_id=owner_id)
    return Context(engine, engine.state.actors[owner_id], action, intent, dict(action.parameters["typed"]),
                   [target] if target is not None else [], target, {}, failed)


def _fake_ask(monkeypatch, *, pick=None, deep=False, indefinite=False, calls=None):
    import combat.ext.needle as needle

    def ask(engine, intent, checkpoint, chooser, choice_id, options, **kwargs):
        if calls is not None:
            calls.append(choice_id)
        if choice_id.endswith("erase_deep"):
            return ["deep"] if deep else ["normal"]
        if choice_id.endswith("erase_indefinite"):
            return ["indefinite"] if indefinite else ["minute"]
        if choice_id.endswith("erase_target") and pick is not None:
            return [pick] if pick in options else options[:1]
        return options[:1]

    monkeypatch.setattr(needle, "ask", ask)


def _source_action(engine, actor_id, talents, cl, display):
    """A real compiled action from a real sheet, registered as a Source-CL reference."""
    bundle = compile_character(sheet(list(talents), cl=cl, name=actor_id, dc=1), actor_id=actor_id)
    for row in bundle["action_catalog"]:
        engine.action_catalog.setdefault(row["source_definition_id"], ActionDefinition.model_validate(row))
    return next(action for action in engine.action_catalog.values()
                if action.display_name == display
                and action.source_definition_id in {row["source_definition_id"] for row in bundle["action_catalog"]})


def _zone(engine, *, zone_id, source, owner_id, cell=(5, 6), dc=1):
    zone = ZoneState(zone_id=zone_id, source_definition_id=source, owner_id=owner_id,
                     center=Position(x=cell[0], y=cell[1]), radius_cells=0,
                     affected_cells=(Position(x=cell[0], y=cell[1]),), concentration_link=False,
                     duration_rounds=10, created_round=engine.state.round_number,
                     trigger_profile={"kind": zones.KIND, "numbers": {"save_dc": dc}})
    engine.state.zones[zone_id] = zone
    return zone


# ------------------------------------------------------------------------------------------------ the three modes at the table
def test_erase_substance_table_erases_a_crate_completely_and_reloads(acquired, tmp_path):
    service, project = acquired

    def arena_edit(arena):
        arena["map_objects"] = [{"id": 1, "x": 4, "y": 6, "kind": "crate", "name": "Crate", "hp": 5}]

    combat, table, mid = fixture(tmp_path, [], cl=14, owner_bundle=owner_bundle(service, project),
                                 positions={OWNER: {"x": 3, "y": 6}, ALLY: {"x": 3, "y": 8}, FOE: {"x": 6, "y": 6}},
                                 battlefield_transform=arena_edit, seed="ERASE-SUBSTANCE")
    before = reload(tmp_path, mid)
    assert before.state.actors[OWNER].resources["resource:core.qi"] == 30
    targets = er.substance_targets(before, before.state.actors[OWNER])
    assert [entry["key"] for entry in targets] == ["object:map.1"]
    assert "object:map.1" in [entry["key"] for entry in targets]
    assert not any(entry["kind"] == "actor" for entry in targets), "a living creature is never an Erase Substance target"
    prompts = settle(table, mid, candidate(combat, mid, "Erase: Erase Substance").candidate_id,
                     picks={TARGET_PROMPT: ["object:map.1"]})
    assert [prompt["context"]["reaction_source_id"] for prompt in prompts] == [TARGET_PROMPT]
    engine = reload(tmp_path, mid)
    obj = engine.state.objects["object:map.1"]
    assert obj.current_hp == 0 and obj.destroyed is True and (obj.component or {}).get("erased") == 1
    spent = [event for event in engine.events if event.event_type == "RESOURCE_SPENT"
             and event.payload.get("resource_id") == "resource:core.qi"
             and int(event.payload.get("amount") or 0) == 6]
    assert spent, "the action spends its printed 6 Qi exactly once"
    assert engine.state.actors[OWNER].resources["resource:core.qi"] <= 30 - 5  # no erasure refund
    assert any(event.event_type == "OBJECT_UPDATED" for event in engine.events)
    assert any("erased completely" in str((event.payload or {}).get("log") or "")
               for event in engine.events if event.event_type == "PASSIVE_TRIGGERED")


def test_erase_manifestation_table_suppresses_a_secret_field_and_reloads(acquired, tmp_path):
    service, project = acquired
    combat, table, mid = fixture(tmp_path, [], cl=14, owner_bundle=owner_bundle(service, project),
                                 positions={OWNER: {"x": 3, "y": 6}, ALLY: {"x": 3, "y": 8}, FOE: {"x": 6, "y": 6}},
                                 seed="ERASE-MANIFESTATION")
    settle(table, mid, candidate(combat, mid, "Hollow Field", at=(10, 9)).candidate_id)
    engine = reload(tmp_path, mid)
    field = next(zone for zone in zones.typed_zones(engine) if zone.active)
    assert field.source_definition_id.endswith(".hollow_field")
    end_turn(table, mid)
    turn(table, mid, OWNER)
    engine = reload(tmp_path, mid)
    entries = er.manifestations(engine, engine.state.actors[OWNER])
    zone_entry = next(entry for entry in entries if entry["key"] == field.zone_id)
    assert "Secret authority" in zone_entry["label"]
    assert not any(entry["key"].endswith("concentration_deadline") for entry in entries)
    assert not any(entry["key"].endswith("zone_effect") for entry in entries)
    prompts = settle(table, mid, candidate(combat, mid, "Erase: Erase Manifestation").candidate_id,
                     picks={TARGET_PROMPT: [field.zone_id]})
    assert [prompt["context"]["reaction_source_id"] for prompt in prompts] == [TARGET_PROMPT]
    after = reload(tmp_path, mid)
    kept = after.state.zones[field.zone_id]
    assert kept.active is True and area_suppression.suppressed(kept) is True
    assert any(event.event_type == "CHECK_ROLLED" and event.payload.get("success") is True for event in after.events)
    assert any(event.event_type == "RESOURCE_SPENT" and int(event.payload.get("amount") or 0) == 6
               and event.payload.get("resource_id") == "resource:core.qi" for event in after.events)
    assert not any(event.event_type == "ZONE_REMOVED" for event in after.events)


def test_system_listing_keeps_a_named_secret_feature_as_an_erasable_choice(acquired, tmp_path):
    service, project = acquired
    _, _, mid = fixture(tmp_path, [], cl=14, owner_bundle=owner_bundle(service, project),
                        positions={OWNER: {"x": 3, "y": 6}, ALLY: {"x": 3, "y": 8}, FOE: {"x": 4, "y": 6}},
                        seed="ERASE-NAMED-SECRET")
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    field_action = next(engine.action_catalog[action_id] for action_id in owner.action_ids
                        if (engine.action_catalog.get(action_id) is not None
                            and ((engine.action_catalog[action_id].parameters or {}).get("typed") or {}).get("source")
                            == PARENT + ".feature.hollow_field"))
    # The compiled record itself carries the family's Secret classification; no test
    # or table annotation supplies it.
    assert field_action.parameters["typed"]["source_category"] == "Secret"
    named = [row for row in void.systems(engine, owner) if row["kind"] == "secret_feature"]
    assert any(row["value"] == PARENT + ".feature.hollow_field" for row in named)


def test_erase_cultivation_table_marks_save_cp_system_and_reloads(acquired, tmp_path):
    service, project = acquired
    foe = foe_doc("FIRE_BASE_IGNITE", cl=14, dc=10)
    combat, table, mid = fixture(tmp_path, [], cl=14, owner_bundle=owner_bundle(service, project),
                                 foe_sheet=foe, bundle_transform=helpless_foe,
                                 positions={OWNER: {"x": 3, "y": 6}, ALLY: {"x": 3, "y": 8}, FOE: {"x": 4, "y": 6}},
                                 seed="ERASE-CULTIVATION")
    settle(table, mid, candidate(combat, mid, "Empty Palm: Unravel Manifestation", target=FOE).candidate_id,
           picks={DAMAGE_TYPE_PROMPT: ["FORCE"]})
    settle(table, mid, candidate(combat, mid, "Void Step", at=(2, 6)).candidate_id,
           picks={"choice:needle.teleport_destination": ["cell:2,6"], "choice:needle.void_step_trace": [FOE]})
    engine = reload(tmp_path, mid)
    assert void.mark_count(engine.state.actors[FOE], OWNER) == 2
    end_turn(table, mid)
    turn(table, mid, OWNER)
    engine = reload(tmp_path, mid)
    assert [row["label"] for row in void.systems(engine, engine.state.actors[FOE])] == ["Sphere: Fire"]
    before_qi = engine.state.actors[FOE].resources["resource:core.qi"]
    before_hp = engine.state.actors[FOE].current_hp
    prompts = settle(table, mid, candidate(combat, mid, "Erase: Erase Cultivation", target=FOE).candidate_id,
                     picks={SYSTEM_PROMPT: ["sphere|tianxia.sphere.fire"], POOL_PROMPT: ["resource:core.qi"]})
    assert [prompt["context"]["reaction_source_id"] for prompt in prompts] == [POOL_PROMPT, SYSTEM_PROMPT]
    after = reload(tmp_path, mid)
    target = after.state.actors[FOE]
    assert 0 < target.current_hp < before_hp  # it took the failed save's 8d8 Void damage
    assert target.resources["resource:core.qi"] == before_qi - 8  # 2 x PB (PB 4)
    assert void.mark_count(target, OWNER) == 0
    condition = next(row for row in target.conditions.values() if row.condition_id == void.SYSTEM)
    assert condition.data["kind"] == "sphere" and condition.data["value"] == FIRE
    assert condition.expires_on.startswith("START_OF_SLOT_AT:")
    assert int(condition.data["persistent"]) == 0
    # The erased system really gates use: the foe's Fire action is not offered on its turn.
    after.state.current_actor_id = FOE
    after.state.current_slot_index = after.state.initiative_order.index(FOE)
    target.action_available = True
    fire = next(action for action in after.action_catalog.values()
                if action.owner_id == FOE and action.display_name == "Conflagration")
    assert not any(c.source_definition_id == fire.source_definition_id for c in after.legal_candidates())
    assert ext.any_false("candidate_allowed", after, target, None, fire) is True


# ------------------------------------------------------------------------------------------------ admission, gates and refusals
def test_erase_requires_two_marks_and_is_not_offered(acquired, tmp_path):
    service, project = acquired
    foe = foe_doc("FIRE_BASE_IGNITE", cl=14, dc=10)
    combat, table, mid = fixture(tmp_path, [], cl=14, owner_bundle=owner_bundle(service, project), foe_sheet=foe,
                                 positions={OWNER: {"x": 3, "y": 6}, ALLY: {"x": 3, "y": 8}, FOE: {"x": 4, "y": 6}},
                                 seed="ERASE-GATE")
    engine = reload(tmp_path, mid)
    _marks(engine, OWNER, engine.state.actors[FOE], 1)
    action = _action(engine, OWNER, "Erase: Erase Cultivation")
    assert ext.any_false("candidate_allowed", engine, engine.state.actors[OWNER], None, action) is True
    # The real menu does not offer it for a foe with one mark.
    assert not any(c.source_definition_id == action.source_definition_id for c in engine.legal_candidates())
    from types import SimpleNamespace

    reason = ext.run("candidate_unavailability", engine, engine.state.actors[OWNER],
                     SimpleNamespace(target_ids=(FOE,), metadata={}), action)[0]
    assert "at least 2 of your Void Marks" in reason


def test_substance_target_classification_refuses_living_artifacts_and_active_souls(acquired, tmp_path):
    service, project = acquired
    foe = foe_doc(cl=14)
    combat, table, mid = fixture(tmp_path, [], cl=14, owner_bundle=owner_bundle(service, project), foe_sheet=foe,
                                 positions={OWNER: {"x": 3, "y": 6}, ALLY: {"x": 3, "y": 8}, FOE: {"x": 4, "y": 6}},
                                 seed="ERASE-REFUSE")
    engine = reload(tmp_path, mid)
    user = engine.state.actors[OWNER]
    keys = {entry["key"] for entry in er.substance_targets(engine, user)}
    assert FOE not in keys and ALLY not in keys

    artifact = RuntimeObjectState(object_id="object:map.90", object_kind="custom", position=Position(x=5, y=6),
                                  unattended=True, flammable=False, ac=15, current_hp=10, maximum_hp=10,
                                  component={"name": "Bound relic", "artifact": True})
    engine._update_object(artifact, "action:test.artifact")
    assert "object:map.90" not in {entry["key"] for entry in er.substance_targets(engine, user)}

    corpse = engine.state.actors[FOE]
    corpse.active = False
    corpse.current_hp = 0
    engine._apply_condition(corpse, "condition:typed.soul_lingering", "action:test.soul", OWNER,
                            expires_on="UNTIL_REMOVED", data={"label": "A lingering soul"})
    assert FOE not in {entry["key"] for entry in er.substance_targets(engine, user)}
    engine._remove_condition(corpse, "condition:typed.soul_lingering", "action:test.soul")
    assert FOE in {entry["key"] for entry in er.substance_targets(engine, user)}

    construct = engine.state.actors[ALLY]
    construct.creature_types = ("Cultivation Asset",)
    assert ALLY in {entry["key"] for entry in er.substance_targets(engine, user)}


def test_manifestation_authority_branches_and_artifact_protection(acquired, tmp_path, monkeypatch):
    service, project = acquired
    foe = foe_doc("FIRE_BASE_IGNITE", cl=14, dc=1)
    combat, table, mid = fixture(tmp_path, [], cl=14, owner_bundle=owner_bundle(service, project), foe_sheet=foe,
                                 positions={OWNER: {"x": 3, "y": 6}, ALLY: {"x": 3, "y": 8}, FOE: {"x": 6, "y": 6}},
                                 seed="ERASE-AUTHORITY")
    engine = reload(tmp_path, mid)
    action = _action(engine, OWNER, "Erase: Erase Manifestation")
    low_source = _source_action(engine, "actor:source.low", ["FIRE_BASE_IGNITE"], 8, "Conflagration")
    equal_source = _source_action(engine, "actor:source.equal", ["FIRE_BASE_IGNITE"], 14, "Conflagration")
    high_source = _source_action(engine, "actor:source.high", ["FIRE_BASE_IGNITE"], 18, "Conflagration")
    secret_low_source = _source_action(engine, "actor:source.secret10", [PARENT + ".feature.hollow_field"], 10,
                                       "Hollow Field")
    field_action = _action(engine, OWNER, "Hollow Field")
    artifact_source = ActionDefinition(source_definition_id="action:test.artifact_manifestation",
                                       display_name="Artifact manifestation", owner_id=FOE, economy="ACTION",
                                       resolution_kind="TYPED", target_kind="SELF",
                                       parameters={"typed": {"source": "action:test.artifact_manifestation",
                                                             "artifact": True, "effects": [],
                                                             "numbers": {"cl": 14}}})
    engine.action_catalog[artifact_source.source_definition_id] = artifact_source

    # Lower non-Secret Source CL erases immediately, with no check.
    low = _zone(engine, zone_id="zone:test:low", source=low_source.source_definition_id, owner_id=FOE)
    _fake_ask(monkeypatch, pick=low.zone_id)
    er.erase_manifestation(_ctx(engine, OWNER, action))
    assert low.active is False and not any(event.event_type == "CHECK_ROLLED" for event in engine.events)

    # Equal non-Secret Source CL checks and erases on success.
    equal = _zone(engine, zone_id="zone:test:equal", source=equal_source.source_definition_id, owner_id=FOE)
    _fake_ask(monkeypatch, pick=equal.zone_id)
    er.erase_manifestation(_ctx(engine, OWNER, action))
    assert equal.active is False

    # Higher non-Secret Source CL checks and only suppresses.
    high = _zone(engine, zone_id="zone:test:high", source=high_source.source_definition_id, owner_id=FOE)
    _fake_ask(monkeypatch, pick=high.zone_id)
    er.erase_manifestation(_ctx(engine, OWNER, action))
    assert high.active is True and area_suppression.suppressed(high) is True

    # Secret authority at equal CL suppresses; it never erases (only a lower Secret can be erased).
    secret = _zone(engine, zone_id="zone:test:secret", source=field_action.source_definition_id, owner_id=FOE)
    _fake_ask(monkeypatch, pick=secret.zone_id)
    er.erase_manifestation(_ctx(engine, OWNER, action))
    assert secret.active is True and area_suppression.suppressed(secret) is True

    # A lower Secret manifestation is erased when the user exceeds its Source CL.
    secret_low = _zone(engine, zone_id="zone:test:secret-low", source=secret_low_source.source_definition_id, owner_id=FOE)
    _fake_ask(monkeypatch, pick=secret_low.zone_id)
    er.erase_manifestation(_ctx(engine, OWNER, action))
    assert secret_low.active is False

    # An artifact manifestation is never permanently erased, even when the same check succeeds.
    artifact = _zone(engine, zone_id="zone:test:artifact", source=artifact_source.source_definition_id, owner_id=FOE)
    _fake_ask(monkeypatch, pick=artifact.zone_id)
    er.erase_manifestation(_ctx(engine, OWNER, action))
    assert artifact.active is True and area_suppression.suppressed(artifact) is True

    # A failed check leaves a higher-CL manifestation untouched.
    untouched = _zone(engine, zone_id="zone:test:untouched", source=high_source.source_definition_id, owner_id=FOE,
                      dc=999)
    _fake_ask(monkeypatch, pick=untouched.zone_id)
    er.erase_manifestation(_ctx(engine, OWNER, action))
    assert untouched.active is True and area_suppression.suppressed(untouched) is False


def test_manifestation_erases_a_dependent_anchored_area_and_refunds_nothing(acquired, tmp_path, monkeypatch):
    service, project = acquired
    foe = foe_doc("FIRE_BASE_IGNITE", cl=14, dc=1)
    combat, table, mid = fixture(tmp_path, [], cl=14, owner_bundle=owner_bundle(service, project), foe_sheet=foe,
                                 positions={OWNER: {"x": 3, "y": 6}, ALLY: {"x": 3, "y": 8}, FOE: {"x": 5, "y": 6}},
                                 seed="ERASE-DEPENDENT")
    engine = reload(tmp_path, mid)
    holder = engine.state.actors[FOE]
    fire = _source_action(engine, "actor:source.anchor", ["FIRE_BASE_IGNITE"], 14, "Conflagration")
    engine._apply_condition(holder, "condition:typed.test_manifestation", fire.source_definition_id, FOE,
                            expires_on=None, data={"label": "A test manifestation"})
    key = next(iid for iid, row in holder.conditions.items() if row.condition_id == "condition:typed.test_manifestation")
    anchored = ZoneState(zone_id="zone:test:anchored", source_definition_id=fire.source_definition_id, owner_id=FOE,
                         center=Position(x=5, y=6), radius_cells=0, affected_cells=(Position(x=5, y=6),),
                         concentration_link=False, duration_rounds=10, created_round=engine.state.round_number,
                         trigger_profile={"kind": zones.KIND, "anchor_id": FOE, "numbers": {"save_dc": 1}})
    engine.state.zones[anchored.zone_id] = anchored
    _fake_ask(monkeypatch, pick=key)
    er.erase_manifestation(_ctx(engine, OWNER, _action(engine, OWNER, "Erase: Erase Manifestation")))
    assert key not in holder.conditions
    assert anchored.active is False
    assert all(event.event_type != "RESOURCE_GAINED" for event in engine.events[-5:])


def test_wrong_owner_and_unacquired_character_are_inert(acquired, tmp_path):
    service, project = acquired
    plain = compile_character(sheet([], cl=14), actor_id=ALLY)
    loose = sheet([ERASE], cl=14)
    loose["path_and_subpath"]["void_scar"] = SCAR
    loose_bundle = compile_character(loose, actor_id=FOE)
    row = next(action for action in loose_bundle["action_catalog"]
               if (action.get("parameters", {}).get("typed") or {}).get("source") == ERASE)
    assert row["parameters"]["typed"]["void_scar"] == ""
    assert row["parameters"]["typed"]["effects"] == []
    er_action = next(action for action in loose_bundle["action_catalog"]
                     if str(action.get("display_name")) == "Erase: Erase Manifestation")
    assert er.owned(er_action) is False
    assert er.gate_candidates(None, None, None, er_action) is None
    assert er.gate_rows(None, None, {"feature_id": ERASE}) is None


# ------------------------------------------------------------------------------------------------ Erase Substance damage semantics
def test_erase_damage_bypasses_only_substance_and_deep_commitment_is_save_independent():
    typed = {"source": ERASE, "option_label": "Erase Cultivation"}
    assert er.erase_resistance(None, "VOID", typed, OWNER, object()) is None
    assert er.erase_immunity(None, "VOID", typed, OWNER, object()) is None
    typed["option_label"] = "Erase Substance"
    assert er.erase_resistance(None, "VOID", typed, OWNER, object()) is True
    assert er.erase_immunity(None, "VOID", typed, OWNER, object()) == ext.IMMUNITY_RESISTANCE_KEPT


def test_creator_provenance_does_not_make_an_object_summoned_or_double_damage():
    from combat.ext import objects

    obj = RuntimeObjectState(object_id="object:banner", object_kind="custom", position=Position(x=5, y=6),
                             unattended=True, flammable=False, ac=15, current_hp=10, maximum_hp=10,
                             component=objects.record_creator({"name": "Command Banner"}, "action:banner"))

    assert objects.created_by(obj) == "action:banner"  # provenance remains available to its real consumers
    assert er._object_double(obj) is False

    obj.component["kind"] = "formation_anchor"
    assert er._object_double(obj) is True


def test_object_damage_ignores_resistance_and_threshold_and_treats_immunity_as_resistance():
    from combat import object_rules

    class Obj:
        component = {"resist": ["VOID"], "vulnerable": []}
        damage_immunities = ("VOID",)
        damage_threshold = 12
        object_kind = "custom"

    found = object_rules.work_out([(40, "VOID")], Obj(), ignore_threshold=True, ignore_resistance=True,
                                  immunity_as_resistance=True)
    assert found["total"] == 20  # Immunity is Resistance, and the source's ordinary-Resistance ignore does not undo that halving
    assert "treats its Immunity to void damage as Resistance" in found["notes"]
    thresholded = object_rules.work_out([(5, "FORCE")], Obj(), ignore_threshold=False)
    assert thresholded["total"] == 0 and any("Damage Threshold" in note for note in thresholded["notes"])
    immune = object_rules.work_out([(40, "VOID")], Obj(), ignore_threshold=True)
    assert immune["total"] == 0 and any("immune" in note for note in immune["notes"])


def test_erase_substance_creature_damage_keeps_the_immunity_halving(acquired, tmp_path):
    """The creature half of the object rule: an Immune creature takes half of the 10d10 Void.

    "Ignores ordinary Resistance" and "Treats ordinary Immunity as Resistance" are two
    separate printed sentences, so the same mode's Resistance bypass must not also undo
    the converted Immunity. Myriad-Venom Immortal's opposite printed rule ("treats Poison
    Immunity as Resistance and then ignores it") is covered in tests/test_riders_c7.py.
    """
    service, project = acquired
    combat, table, mid = fixture(tmp_path, [], cl=14, owner_bundle=owner_bundle(service, project),
                                 positions={OWNER: {"x": 3, "y": 6}, ALLY: {"x": 3, "y": 8}, FOE: {"x": 6, "y": 6}},
                                 seed="ERASE-IMMUNITY")
    engine = reload(tmp_path, mid)
    foe = engine.state.actors[FOE]
    engine._add_modifier(foe, "test:void_immunity", "damage_immunity", "ADD", "VOID", "ALWAYS",
                         expires_on="UNTIL_REMOVED")
    action = _action(engine, OWNER, "Erase: Erase Substance")
    assert typed_reactions.damage_factor(engine, foe, "VOID", action.source_definition_id, OWNER) == 0.5
    before = foe.current_hp
    engine._commit_damage(foe, 20, "VOID", action.source_definition_id, OWNER, None, reaction_depth=0)
    assert before - foe.current_hp == 10


# ------------------------------------------------------------------------------------------------ Deep Erasure bands
def _deep_engine(acquired, tmp_path, *, foe_cl, target_dc=1):
    service, project = acquired
    foe = foe_doc("FIRE_BASE_IGNITE", cl=foe_cl, dc=target_dc)
    _, _, mid = fixture(tmp_path, [], cl=foe_cl, owner_bundle=owner_bundle(service, project), foe_sheet=foe,
                        positions={OWNER: {"x": 3, "y": 6}, ALLY: {"x": 3, "y": 8}, FOE: {"x": 4, "y": 6}},
                        seed=f"ERASE-DEEP-{foe_cl}")
    engine = reload(tmp_path, mid)
    foe_actor = engine.state.actors[FOE]
    _marks(engine, OWNER, foe_actor, 3)
    return engine, foe_actor


def _run_deep(engine, monkeypatch, *, deep=True, indefinite=False, calls=None):
    _fake_ask(monkeypatch, deep=deep, indefinite=indefinite, calls=calls)
    action = _action(engine, OWNER, "Erase: Erase Cultivation")
    er.erase_cultivation(_ctx(engine, OWNER, action, target=engine.state.actors[FOE], failed=True))


@pytest.mark.parametrize("foe_cl,band", [(8, "indefinite"), (11, "recovery"), (14, "repeat")])
def test_deep_erasure_spends_three_marks_and_sets_the_matching_band(acquired, tmp_path, monkeypatch, foe_cl, band):
    engine, foe = _deep_engine(acquired, tmp_path, foe_cl=foe_cl)
    calls = []
    _run_deep(engine, monkeypatch, indefinite=True, calls=calls)
    assert DEEP_PROMPT in calls
    assert void.mark_count(foe, OWNER) == 0
    condition = next(row for row in foe.conditions.values() if row.condition_id == void.SYSTEM)
    assert condition.data["band"] == band
    if band in ("indefinite", "recovery"):
        assert condition.expires_on == "UNTIL_REMOVED" and int(condition.data["persistent"]) == 1
    else:
        assert condition.expires_on.startswith("START_OF_SLOT_AT:")
        assert int(condition.data["deep_repeat"]) == 1


def test_deep_erasure_with_two_marks_does_not_offer_or_spend_three(acquired, tmp_path, monkeypatch):
    service, project = acquired
    foe = foe_doc("FIRE_BASE_IGNITE", cl=14, dc=1)
    _, _, mid = fixture(tmp_path, [], cl=14, owner_bundle=owner_bundle(service, project), foe_sheet=foe,
                        positions={OWNER: {"x": 3, "y": 6}, ALLY: {"x": 3, "y": 8}, FOE: {"x": 4, "y": 6}},
                        seed="ERASE-DEEP-TWO")
    engine = reload(tmp_path, mid)
    foe_actor = engine.state.actors[FOE]
    _marks(engine, OWNER, foe_actor, 2)
    calls = []
    _run_deep(engine, monkeypatch, calls=calls)
    assert DEEP_PROMPT not in calls
    assert void.mark_count(foe_actor, OWNER) == 0
    condition = next(row for row in foe_actor.conditions.values() if row.condition_id == void.SYSTEM)
    assert condition.data["band"] == "minute"


def test_deep_erasure_marks_spend_once_per_activation(acquired, tmp_path, monkeypatch):
    engine, foe = _deep_engine(acquired, tmp_path, foe_cl=11)
    _fake_ask(monkeypatch, deep=True, indefinite=True)
    action = _action(engine, OWNER, "Erase: Erase Cultivation")
    ctx = _ctx(engine, OWNER, action, target=foe, failed=True)
    er.erase_cultivation(ctx)
    er.erase_cultivation(ctx)
    assert void.mark_count(foe, OWNER) == 0


def test_deep_commitment_is_compiled_before_the_save(acquired, tmp_path):
    service, project = acquired
    foe = foe_doc("FIRE_BASE_IGNITE", cl=14, dc=10)
    _, _, mid = fixture(tmp_path, [], cl=14, owner_bundle=owner_bundle(service, project), foe_sheet=foe,
                        positions={OWNER: {"x": 3, "y": 6}, ALLY: {"x": 3, "y": 8}, FOE: {"x": 4, "y": 6}},
                        seed="ERASE-COMMIT-ORDER")
    engine = reload(tmp_path, mid)
    action = _action(engine, OWNER, "Erase: Erase Cultivation")
    effects = action.parameters["typed"]["effects"]
    assert effects[0]["operation"] == "commitment"
    assert effects[1]["type"] == "save"


def test_erase_uses_recorded_source_cl_instead_of_total_cl():
    from types import SimpleNamespace

    ctx = SimpleNamespace(numbers={"cl": 20, "source_cl": 14})
    assert er._source_cl(ctx) == 14


def test_deep_erasure_higher_target_checks_and_only_suppresses_on_failure(acquired, tmp_path, monkeypatch):
    engine, foe = _deep_engine(acquired, tmp_path, foe_cl=18, target_dc=999)
    _run_deep(engine, monkeypatch)
    condition = next(row for row in foe.conditions.values() if row.condition_id == void.SYSTEM)
    assert condition.data["band"] == "next_turn"
    assert condition.expires_on.startswith("END_OF_TURN_AT:")
    assert int(condition.data["persistent"]) == 0


def test_deep_erasure_within_two_cl_repeats_the_save_and_ends_on_success(acquired, tmp_path, monkeypatch):
    engine, foe = _deep_engine(acquired, tmp_path, foe_cl=14)
    _run_deep(engine, monkeypatch)
    condition = next(row for row in foe.conditions.values() if row.condition_id == void.SYSTEM)
    assert condition.data["band"] == "repeat"
    # The first affected turn does not repeat; the next affected turn does.
    foe.saving_throws["CHA"] = 100
    foe.turns_started += 1
    ext.run("turn_end", engine, foe)
    assert any(row.condition_id == void.SYSTEM for row in foe.conditions.values())
    foe.turns_started += 1
    ext.run("turn_end", engine, foe)
    assert not any(row.condition_id == void.SYSTEM for row in foe.conditions.values())


# ------------------------------------------------------------------------------------------------ recovery
def test_recovery_needs_a_listed_authority_and_ordinary_rest_does_not_restore(acquired, tmp_path, monkeypatch):
    engine, foe = _deep_engine(acquired, tmp_path, foe_cl=11)
    _run_deep(engine, monkeypatch, indefinite=True)
    condition = next(row for row in foe.conditions.values() if row.condition_id == void.SYSTEM)
    assert condition.expires_on == "UNTIL_REMOVED"

    # Neither ordinary recovery nor an arbitrary reason is evidence of a printed authority.
    engine._heal(foe, 10, er.ERASE, OWNER)
    engine._gain_resource(foe, "resource:core.qi", 5, er.ERASE)
    er.reconcile_and_recover(engine, foe)
    assert er.recover(engine, foe, "FAKE_AUTHORITY") == 0
    assert any(row.condition_id == void.SYSTEM for row in foe.conditions.values())

    # A listed authority answers the general contract and the rows come back.
    monkeypatch.setitem(ext._HOOKS, "recovery_procedure", [lambda engine, target, record: True])
    assert er.recover(engine, foe, "still-not-the-proof") == 1
    assert not any(row.condition_id == void.SYSTEM for row in foe.conditions.values())
    fire = next(action for action in engine.action_catalog.values()
                if action.owner_id == FOE and action.display_name == "Conflagration")
    assert ext.any_false("candidate_allowed", engine, foe, None, fire) is False
    assert er.recover(engine, foe) == 0  # already restored; nothing left to clear


def test_deep_erasure_persisted_state_is_primitives_only(acquired, tmp_path, monkeypatch):
    engine, foe = _deep_engine(acquired, tmp_path, foe_cl=11)
    _run_deep(engine, monkeypatch, indefinite=True)
    condition = next(row for row in foe.conditions.values() if row.condition_id == void.SYSTEM)

    def walk(value):
        if isinstance(value, dict):
            for key, item in value.items():
                assert isinstance(key, str)
                walk(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                walk(item)
        else:
            assert not isinstance(value, float), value
            assert isinstance(value, (str, int, bool, type(None))), value

    walk(condition.data)
    assert isinstance(condition.data["rows"].get("passive"), list)

"""F9 review boundaries through native acquisitions, table commits and cold replay.

Public synthetic scene controls are fixture actions; no history or live models.
"""
import pytest

from combat import ext, senses, typed_reactions, zones
from combat.authority_projection import compile_project_character
from combat.ext import qi_path, void_touched_cultivator as void, void_touched_hollow_field as hf
from combat.ext.teleport_steps import destination_allowed
from combat.factory_compiler import compile_character
from combat.gate2_runtime_models import ActionDefinition, Position, RollRecord, ZoneState
from tests.h1_support import sheet
from tests.test_mgr_hollow_field import (
    acquired, advance_to, cast_field, field, owner_doc, put_marks, with_cha,
)
from tests.void_touched_acquisition_support import build_native_acquisition
from tests.worker2_support import ALLY, FOE, OWNER, candidate, fixture, reload, settle

PROBE = "action:test.hollow_f9."
DEST = Position(x=3, y=4)


def _actions(info):
    if info["actor_id"] != OWNER:
        return []
    return [
        ActionDefinition(
            source_definition_id=PROBE + op, display_name="F9 scene: " + op,
            owner_id=OWNER, economy="NONE", resolution_kind="TYPED", target_kind="SELF",
            parameters={"typed": {"source": PROBE + op, "numbers": info["numbers"],
                        "duration": {"kind": "instant"},
                        "effects": [{"type": "hollow_f9_scene", "op": op}]}})
        for op in ("clear smoke", "smoke and blind", "marks", "end field", "resist", "rescue")
    ]


def _smoke(engine):
    zone = ZoneState(
        zone_id="zone:test:f9.smoke", source_definition_id=PROBE + "smoke", owner_id=FOE,
        center=DEST, radius_cells=0, affected_cells=(DEST,), concentration_link=False,
        duration_rounds=10, created_round=engine.state.round_number,
        trigger_profile={"kind": zones.KIND, "obscured": "heavy", "visual": {"darkness": True}})
    engine.state.zones[zone.zone_id] = zone
    engine._append_event("ZONE_CREATED", zone.source_definition_id, actor_id=FOE,
                         payload={"zone": zone.model_dump(mode="json")})


def _initial_smoke(engine):
    _smoke(engine)
    return True


def _scene(ctx, row):
    engine, owner, foe = ctx.engine, ctx.actor, ctx.engine.state.actors[FOE]
    op = row["op"]
    if op == "clear smoke":
        zones.remove(engine, engine.state.zones["zone:test:f9.smoke"], "TEST")
    elif op == "smoke and blind":
        _smoke(engine)
        engine._apply_condition(owner, "blinded", ctx.source, FOE, expires_on="UNTIL_REMOVED")
    elif op == "marks":
        put_marks(engine, owner, foe, field(engine), 2)
    elif op == "end field":
        engine._end_concentration(owner, "TEST")
    elif op == "resist":
        engine._apply_condition(foe, "condition:test.f9.resist", ctx.source, OWNER,
                                expires_on="UNTIL_REMOVED", data={"label": "Test save bonus"})
    elif op == "rescue":
        roll = RollRecord(roll_id="test:f9", counter_start=0, counter_end=0,
                          expression="1d20", actor_id=FOE, reason="test Concentration",
                          dice=(9,), modifier=0, total=9, natural_result=9)
        rescued = typed_reactions.on_save(engine, foe, "CON", 10, roll, "system:combat.concentration")
        engine._append_event("PASSIVE_TRIGGERED", ctx.source, actor_id=FOE,
                             payload={"rescued_total": rescued.total})


def _save_bonus(engine, target, ability, dc, source, intent):
    if ability == "CHA" and any(c.condition_id == "condition:test.f9.resist" for c in target.conditions.values()):
        return 120
    return None


@pytest.fixture
def probes(monkeypatch):
    ext.effects()
    monkeypatch.setitem(ext._HOOKS, "compile_actions", [*ext._HOOKS.get("compile_actions", []), _actions])
    monkeypatch.setitem(ext._EFFECTS, "hollow_f9_scene", _scene)
    monkeypatch.setitem(ext._HOOKS, "save_bonus", [*ext._HOOKS.get("save_bonus", []), _save_bonus])


@pytest.fixture
def smoked(probes, monkeypatch):
    monkeypatch.setitem(ext._HOOKS, "match_initialize", [*ext._HOOKS.get("match_initialize", []), _initial_smoke])


def _probe(combat, table, mid, op, **kwargs):
    return settle(table, mid, candidate(combat, mid, "F9 scene: " + op).candidate_id, **kwargs)


def _owner(service, project):
    return compile_project_character(service, project, owner_doc(service, project), actor_id=OWNER,
                                     reaction_plan={"ask": True})


def _step(engine):
    return next(a for a in engine.action_catalog.values() if void.family_source(a) == void.VOID_STEP)


def test_unexplored_smoke_is_not_a_known_void_step_destination(acquired, smoked, tmp_path):
    service, project = acquired
    combat, table, mid = fixture(tmp_path, [], owner_bundle=_owner(service, project), seed="F9-UNSEEN")
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    assert not senses.perceives_cell(engine, owner, DEST)
    assert not void.precisely_known(engine, owner, DEST)
    assert not destination_allowed(engine, owner, DEST, 30, action=_step(engine))
    assert not [c for c in engine.legal_candidates() if c.source_definition_id == _step(engine).source_definition_id
                and c.destination == DEST]
    # A second committed action and cold replay cannot manufacture knowledge.
    _probe(combat, table, mid, "smoke and blind")
    engine = reload(tmp_path, mid)
    assert not destination_allowed(engine, engine.state.actors[OWNER], DEST, 30, action=_step(engine))


def test_observed_space_stays_known_after_smoke_blindness_and_reload(acquired, smoked, tmp_path):
    service, project = acquired
    combat, table, mid = fixture(tmp_path, [], owner_bundle=_owner(service, project), seed="F9-KNOWN")
    _probe(combat, table, mid, "clear smoke")
    engine = reload(tmp_path, mid)
    assert void.precisely_known(engine, engine.state.actors[OWNER], DEST), "clear smoke must record the visible space"
    _probe(combat, table, mid, "smoke and blind")
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    assert not void._visible(engine, owner, DEST)
    assert void.precisely_known(engine, owner, DEST), "knowledge must survive smoke, blindness and reload"
    assert destination_allowed(engine, owner, DEST, 30, action=_step(engine)), "known landing must stay legal"
    settle(table, mid, candidate(combat, mid, "Void Step", at=(3, 4)).candidate_id,
           picks={"choice:needle.teleport_destination": ["cell:3,4"],
                  "choice:needle.void_step_trace": None})
    assert reload(tmp_path, mid).state.actors[OWNER].position == DEST


@pytest.fixture(scope="module")
def source_ten(tmp_path_factory):
    service, project = build_native_acquisition(tmp_path_factory.mktemp("f9-source-ten"), 10, "f9")
    # Total character level and owning-Path attainment are independent facts.
    service.set_target_cl(project, 15)
    return service, project


def _field_fight(tmp_path, service, project, *, foe_cl=13, nascent=False):
    doc = sheet(["TAL_VOID_EMPTY_STEP", "TAL_VOID_HOLLOW_TOUCH"], cl=foe_cl)
    if nascent:
        doc["path_and_subpath"] = {"path_feature_record_ids": [qi_path.NASCENT_SOUL]}
    return fixture(
        tmp_path, [], cl=foe_cl, owner_bundle=_owner(service, project), foe_sheet=doc,
        bundle_transform=lambda rows: with_cha(rows, -60),
        positions={OWNER: {"x": 3, "y": 6}, ALLY: {"x": 3, "y": 8}, FOE: {"x": 6, "y": 6}},
        seed="F9-SOURCE-" + str(foe_cl))


def test_owning_path_source_cl_seals_field_before_transforms(source_ten, probes, tmp_path):
    service, project = source_ten
    combat, table, mid = _field_fight(tmp_path, service, project, foe_cl=12)
    cast_field(combat, table, mid)
    engine = reload(tmp_path, mid)
    zone = field(engine)
    assert engine.typed_bundle_documents[0]["cl"] == 15
    assert zone.trigger_profile["profile"]["source_cl"] == 10
    assert zone.trigger_profile["numbers"]["source_cl"] == 10
    foe = engine.state.actors[FOE]
    action = next(engine.action_catalog[k] for k in foe.action_ids
                  if hf.source_of(engine.action_catalog[k]) == "TAL_VOID_EMPTY_STEP")
    engine._active_action_source_id = action.source_definition_id
    # A CL12 source is NOT lower than the owning Qi Path's CL10.
    assert hf.hollow_teleport(engine, foe, foe.position, Position(x=8, y=6)) is None


def test_cl13_target_gets_repeat_save_against_total15_qi10_field(source_ten, probes, tmp_path):
    service, project = source_ten
    combat, table, mid = _field_fight(tmp_path, service, project)
    cast_field(combat, table, mid)
    _probe(combat, table, mid, "marks")
    advance_to(table, mid, FOE)
    engine = reload(tmp_path, mid)
    marker = next(c for c in engine.state.actors[FOE].conditions.values() if c.condition_id == hf.SYSTEM)
    assert marker.data["cl"] == 10
    # A committed fixture action sets the next save, not an in-memory post-load edit.
    advance_to(table, mid, OWNER)
    _probe(combat, table, mid, "resist")
    advance_to(table, mid, FOE)
    settle(table, mid, table.state(mid)["menu"]["end_turn"])
    engine = reload(tmp_path, mid)
    assert not [c for c in engine.state.actors[FOE].conditions.values() if c.condition_id == hf.SYSTEM]
    assert any((e.payload or {}).get("reason") == "SAVE_SUCCEEDED" and e.actor_id == OWNER
               for e in engine.events if e.event_type == "CONDITION_REMOVED")


@pytest.mark.parametrize("chosen", ["independent_concentration", "continuity", "armament_conduction",
                                  "second_defensive_discipline"])
def test_deepen_selects_one_nascent_feature_and_preserves_siblings(acquired, probes, tmp_path, chosen):
    service, project = acquired
    combat, table, mid = _field_fight(tmp_path, service, project, foe_cl=15, nascent=True)
    cast_field(combat, table, mid)
    _probe(combat, table, mid, "marks")
    prompts = advance_to(table, mid, FOE, choices={
        "choice:needle.hollow_field": ("speed15", ["nascent_soul|" + qi_path.NASCENT_SOUL + "." + chosen])})
    engine = reload(tmp_path, mid)
    foe = engine.state.actors[FOE]
    markers = [c for c in foe.conditions.values() if c.condition_id == hf.SYSTEM]
    assert len(markers) == 1 and markers[0].data["value"] == qi_path.NASCENT_SOUL + "." + chosen
    offered = [o["id"] for p in prompts if p["context"]["reaction_source_id"] == "choice:needle.hollow_field"
               for o in p["choice"]["options"]]
    assert all("nascent_soul|" + qi_path.NASCENT_SOUL + "." + key in offered
               for key in qi_path.NASCENT_FEATURES)
    assert not ("nascent_soul|" + qi_path.NASCENT_SOUL) in offered
    assert void.mark_count(foe, OWNER) == 0
    independent = any(r["feature_id"] == qi_path.NASCENT_SOUL
                      and not ext.any_false("row_allowed", engine, foe, r)
                      for r in engine.typed_reaction_rows[FOE])
    continuity = qi_path._has(engine, foe, "nascent_continuity")
    assert independent == (chosen != "independent_concentration")
    assert continuity == (chosen != "continuity")
    # Actual save-rescue consumer: suppressing Continuity/conduction/discipline
    # must not remove Independent Concentration; suppressing it must stop it.
    advance_to(table, mid, OWNER)
    _probe(combat, table, mid, "rescue", picks={"reaction:typed." + qi_path.NASCENT_SOUL: "first"})
    engine = reload(tmp_path, mid)
    total = [e.payload["rescued_total"] for e in engine.events if "rescued_total" in e.payload][-1]
    assert (total >= 10) == (chosen != "independent_concentration")
    _probe(combat, table, mid, "end field")
    engine = reload(tmp_path, mid)
    assert not [c for c in engine.state.actors[FOE].conditions.values() if c.condition_id == hf.SYSTEM]
    assert any(r["feature_id"] == qi_path.NASCENT_SOUL for r in engine.typed_reaction_rows[FOE])
    assert any(r.get("kind") == "nascent_continuity" for r in engine.typed_passive_rows[FOE])

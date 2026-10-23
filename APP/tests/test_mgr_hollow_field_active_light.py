"""F5 review: active system suspension and spatial, live lighting via table commits.

All characters and lamp actions are synthetic/public. Void Shell and Hollow
Field are the acquired native abilities; only lamp controls/mark setup are
fixture actions. No model service or repository history is consulted.
"""
import pytest

from combat import ext, zones
from combat.ext import benefit_suppression, void_touched_hollow_field as hf
from combat.gate2_runtime_models import ActionDefinition, Position
from tests.test_mgr_hollow_field import (
    acquired, action_of, advance_to, cast_field, field, fight, put_marks,
)
from tests.worker2_support import ALLY, FOE, OWNER, candidate, reload, settle

SHELL = "TAL_VOID_VOID_SHELL"
PROBE = "action:test.hollow_review."


def _actions(info):
    if info["actor_id"] != OWNER:
        return []
    return [
        ActionDefinition(
            source_definition_id=PROBE + op, display_name="Review fixture: " + op,
            owner_id=OWNER, economy="NONE", resolution_kind="TYPED", target_kind="SELF",
            parameters={"typed": {"source": PROBE + op, "numbers": info["numbers"],
                        "duration": {"kind": "instant"},
                        "effects": [{"type": "hollow_review_fixture", "op": op}]}})
        for op in ("marks", "end field", "dim lamp", "bright lamp", "remove bright", "remove dim",
                   "provenance", "release first", "end stacked field")
    ]


def _fixture_effect(ctx, row):
    engine = ctx.engine
    op = row["op"]
    if op == "marks":
        put_marks(engine, ctx.actor, engine.state.actors[FOE], field(engine), 2)
    elif op in ("end field", "end stacked field"):
        engine._end_concentration(ctx.actor, "TEST")
        if op == "end stacked field":
            assert any(r["feature_id"] == "TAL_VOID_NO_PURCHASE_BODY"
                       for r in engine.typed_passive_rows[FOE]), "live rows must return without needing a reload"
    elif op == "release first":
        foe = engine.state.actors[FOE]
        marker = next(c for c in foe.conditions.values() if c.condition_id == hf.SYSTEM)
        hf._release_system(engine, foe, marker, "TEST")
        assert not any(r["feature_id"] == "TAL_VOID_NO_PURCHASE_BODY"
                       for r in engine.typed_passive_rows[FOE]), "the remaining binding still suppresses live rows"
    elif op == "provenance":
        foe, ally = engine.state.actors[FOE], engine.state.actors[ALLY]
        action = action_of(engine, foe, SHELL)
        # A remote grant by the suppressed producer, an unrelated producer's
        # grant using the same source, and a short-lived active condition.
        engine._add_modifier(ally, action.source_definition_id, "armor_class", "ADD", 3, "ALWAYS",
                             expires_on="CONCENTRATION_END", source_actor_id=FOE)
        engine._add_modifier(foe, action.source_definition_id, "armor_class", "ADD", 7, "ALWAYS",
                             expires_on="UNTIL_REMOVED", source_actor_id=ALLY)
        from combat.ext.effect_durations import token
        engine._apply_condition(foe, "condition:typed.invisible", action.source_definition_id, FOE,
                                expires_on=token("end", FOE, foe.turns_started + 1))
    elif op.startswith("remove"):
        level = op.split()[-1]
        zones.remove(engine, engine.state.zones["zone:test:hollow:" + level], "TEST")
    else:
        level = op.split()[0]
        spec = {"name": "Test " + level + " lamp", "shape": "sphere", "size_ft": 5,
                "duration": {"kind": "rounds", "amount": 10}, "triggers": [], "inside": [],
                "visual": {"light": {"level": level, "radius_ft": 5}}}
        zone = zones.prospective_zone(ctx, spec, Position(x=6, y=6),
                                     zone_id="zone:test:hollow:" + level)
        engine.state.zones[zone.zone_id] = zone
        engine._append_event("ZONE_CREATED", ctx.source, actor_id=OWNER,
                             payload={"zone": zone.model_dump(mode="json")})


@pytest.fixture
def probes(monkeypatch):
    ext.effects()
    monkeypatch.setitem(ext._HOOKS, "compile_actions", [*ext._HOOKS.get("compile_actions", []), _actions])
    monkeypatch.setitem(ext._EFFECTS, "hollow_review_fixture", _fixture_effect)


def _probe(combat, table, mid, op):
    settle(table, mid, candidate(combat, mid, "Review fixture: " + op).candidate_id)


def _shell_modifiers(engine, holder, producer=FOE):
    source = action_of(engine, engine.state.actors[FOE], SHELL).source_definition_id
    return [m for m in engine.state.actors[holder].modifiers.values()
            if m.source_definition_id == source and m.source_actor_id == producer]


def test_deepen_suspends_an_already_active_native_system_and_restores_live_contributions(
        acquired, probes, tmp_path):
    service, project = acquired
    combat, table, mid = fight(tmp_path, service, project, foe_talents=(SHELL,), cha=-50)
    advance_to(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, "Void Shell").candidate_id)
    engine = reload(tmp_path, mid)
    original = {m.modifier_id for m in _shell_modifiers(engine, FOE)}
    assert original, "the real native Void Shell must already be active"
    advance_to(table, mid, OWNER)
    _probe(combat, table, mid, "provenance")
    cast_field(combat, table, mid)
    _probe(combat, table, mid, "marks")
    prompts = advance_to(table, mid, FOE, choices={
        "choice:needle.hollow_field": ("speed15", "sphere|tianxia.sphere.void"),
    })
    assert any(any(o["id"] == "sphere|tianxia.sphere.void" for o in p["choice"]["options"]) for p in prompts)
    engine = reload(tmp_path, mid)
    foe = engine.state.actors[FOE]
    assert any(c.condition_id == hf.SYSTEM for c in foe.conditions.values())
    assert not _shell_modifiers(engine, FOE), "already-active native benefits must stop, not just future options"
    assert not _shell_modifiers(engine, ALLY), "contributions on other recipients belong to the same system"
    assert _shell_modifiers(engine, FOE, ALLY), "another producer's effects must be untouched"
    assert not any(c.condition_id == "condition:typed.invisible" for c in foe.conditions.values())
    assert foe.concentration is not None, "suppression must not end the original duration"
    assert any(c.condition_id == benefit_suppression.SUPPRESSED for c in foe.conditions.values())
    # The short-lived condition expires during suppression. Persistent native
    # contributions return with their original IDs and concentration, not a recast.
    advance_to(table, mid, OWNER)
    _probe(combat, table, mid, "end field")
    engine = reload(tmp_path, mid)
    assert {m.modifier_id for m in _shell_modifiers(engine, FOE)} == original
    assert _shell_modifiers(engine, ALLY)
    assert _shell_modifiers(engine, FOE, ALLY)
    assert not any(c.condition_id == "condition:typed.invisible" for c in engine.state.actors[FOE].conditions.values())
    assert not any(c.condition_id == benefit_suppression.SUPPRESSED
                   for a in engine.state.actors.values() for c in a.conditions.values())



def test_overlapping_bindings_keep_effects_and_rows_suspended_until_the_last_release(
        acquired, probes, tmp_path):
    service, project = acquired
    passive = "TAL_VOID_NO_PURCHASE_BODY"
    combat, table, mid = fight(tmp_path, service, project, foe_talents=(SHELL, passive), cha=-50)
    advance_to(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, "Void Shell").candidate_id)
    original = {m.modifier_id for m in _shell_modifiers(reload(tmp_path, mid), FOE)}
    advance_to(table, mid, OWNER)
    cast_field(combat, table, mid)
    for _ in range(2):
        _probe(combat, table, mid, "marks")
        advance_to(table, mid, FOE, choices={
            "choice:needle.hollow_field": ("speed15", "sphere|tianxia.sphere.void")})
        advance_to(table, mid, OWNER)
    engine = reload(tmp_path, mid)
    assert len([c for c in engine.state.actors[FOE].conditions.values() if c.condition_id == hf.SYSTEM]) == 2
    _probe(combat, table, mid, "release first")
    engine = reload(tmp_path, mid)
    assert not _shell_modifiers(engine, FOE)
    assert hf.gate_rows(engine, engine.state.actors[FOE], {"feature_id": passive}) is False
    _probe(combat, table, mid, "end stacked field")
    engine = reload(tmp_path, mid)
    assert {m.modifier_id for m in _shell_modifiers(engine, FOE)} == original
    assert any(r["feature_id"] == passive for r in engine.typed_passive_rows[FOE])


def test_deepen_suspends_an_active_native_area_and_restores_its_native_effects(
        acquired, probes, tmp_path):
    service, project = acquired
    combat, table, mid = fight(tmp_path, service, project, foe_talents=("TAL_VOID_QUIET_GAP",), cha=-50)
    advance_to(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, "Quiet Gap", at=(6, 6)).candidate_id)
    engine = reload(tmp_path, mid)
    gap = next(z for z in engine.state.zones.values() if z.owner_id == FOE and z.active)
    original_cells = gap.affected_cells

    def contributions(engine):
        return {
            key for actor in engine.state.actors.values()
            for rows in (actor.conditions, actor.modifiers) for key, row in rows.items()
            if row.source_definition_id == gap.source_definition_id and row.source_actor_id == FOE
        }

    # Quiet Gap applies its Perception penalty at casting; it does not publish
    # continuous "inside" grants. Check its actual native instances, not a
    # nonexistent zone-effect condition.
    original_effects = contributions(engine)
    assert original_cells and original_effects
    advance_to(table, mid, OWNER)
    cast_field(combat, table, mid)
    _probe(combat, table, mid, "marks")
    advance_to(table, mid, FOE, choices={
        "choice:needle.hollow_field": ("speed15", "sphere|tianxia.sphere.void")})
    engine = reload(tmp_path, mid)
    assert not engine.state.zones[gap.zone_id].affected_cells
    assert not contributions(engine)
    advance_to(table, mid, OWNER)
    _probe(combat, table, mid, "end field")
    engine = reload(tmp_path, mid)
    assert engine.state.zones[gap.zone_id].affected_cells == original_cells
    assert contributions(engine) == original_effects


def test_inherited_suppressed_rows_preserve_distinct_blocks_of_the_same_feature(
        acquired, tmp_path):
    service, project = acquired
    combat, table, mid = fight(tmp_path, service, project)
    cast_field(combat, table, mid)
    engine = reload(tmp_path, mid)
    foe = engine.state.actors[FOE]
    source = field(engine).source_definition_id
    rows = [{"feature_id": "TAL_VOID_NO_PURCHASE_BODY", "block": block} for block in ("first", "second")]
    engine.typed_passive_rows[FOE] = rows
    engine._apply_condition(foe, hf.SYSTEM, source, OWNER, expires_on="UNTIL_REMOVED",
                            data={"zone": field(engine).zone_id, "kind": "sphere", "value": "tianxia.sphere.void",
                                  "rows": {"passive": [], "reaction": []}, "label_text": "Test suppression"})
    hf._reconcile_systems(engine)
    marker = next(c for c in foe.conditions.values() if c.condition_id == hf.SYSTEM)
    assert marker.data["rows"]["passive"] == rows, "a feature can own more than one passive block"
    hf._release_system(engine, foe, marker, "TEST")
    assert engine.typed_passive_rows[FOE] == rows


def test_one_active_sphere_talent_loses_its_existing_benefits_until_expiry(
        acquired, probes, tmp_path):
    service, project = acquired
    combat, table, mid = fight(tmp_path, service, project, foe_talents=(SHELL,), cha=-50)
    advance_to(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, "Void Shell").candidate_id)
    original = {m.modifier_id for m in _shell_modifiers(reload(tmp_path, mid), FOE)}
    assert original
    advance_to(table, mid, OWNER)
    cast_field(combat, table, mid)
    advance_to(table, mid, FOE, choices={"choice:needle.hollow_field": "suppress_talent"})
    assert not _shell_modifiers(reload(tmp_path, mid), FOE)
    advance_to(table, mid, OWNER)
    _probe(combat, table, mid, "end field")
    assert not _shell_modifiers(reload(tmp_path, mid), FOE), "the Hollowing effect lasts until the target's next turn"
    advance_to(table, mid, FOE)
    assert {m.modifier_id for m in _shell_modifiers(reload(tmp_path, mid), FOE)} == original


@pytest.mark.parametrize("lamp_first", [True, False])
def test_partial_light_overlap_and_later_emitter_changes_survive_table_reload(
        acquired, probes, tmp_path, lamp_first):
    service, project = acquired
    combat, table, mid = fight(tmp_path, service, project)
    if lamp_first:
        _probe(combat, table, mid, "dim lamp")
    cast_field(combat, table, mid)
    if not lamp_first:
        _probe(combat, table, mid, "dim lamp")

    def visibility():
        engine = reload(tmp_path, mid)
        owner, foe = engine.state.actors[OWNER], engine.state.actors[FOE]
        return engine, zones.hidden_from(engine, owner, foe), zones.hidden_from(engine, foe, owner)

    engine, foe_hidden, owner_hidden = visibility()
    assert foe_hidden, "dim light becomes darkness even when the lamp is added after creation"
    assert not owner_hidden, "the dim lamp covers only part of the sphere, not the owner's square"
    foe = engine.state.actors[FOE]
    foe.position = foe.position.model_copy(update={"z": 2})
    assert not zones.hidden_from(engine, engine.state.actors[OWNER], foe), "a lamp must not darken the whole column"
    _probe(combat, table, mid, "bright lamp")
    _, foe_hidden, owner_hidden = visibility()
    assert not foe_hidden and not owner_hidden, "overlapping bright light becomes dim, not darkness"
    _probe(combat, table, mid, "remove bright")
    assert visibility()[1] is True, "removing the bright emitter restores the dim-to-dark result"
    _probe(combat, table, mid, "remove dim")
    assert visibility()[1:] == (False, False), "ended emitters must not leave stale darkness"

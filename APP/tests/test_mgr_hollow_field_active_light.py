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
        for op in ("marks", "end field", "dim lamp", "bright lamp", "remove bright", "remove dim", "provenance")
    ]


def _fixture_effect(ctx, row):
    engine = ctx.engine
    op = row["op"]
    if op == "marks":
        put_marks(engine, ctx.actor, engine.state.actors[FOE], field(engine), 2)
    elif op == "end field":
        engine._end_concentration(ctx.actor, "TEST")
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

"""Variant identity and catalog/noncatalog check-name edge cases."""
from types import SimpleNamespace

import pytest

from combat.ext.weapon_hits import weapon_identity
from combat.ext.d20_rewrite import RollCtx, check_source_id, roll_source_name
from combat.gate2_runtime_models import ActionDefinition, EconomyKind
from combat.typed_executor import Context


def _action(source, typed):
    return ActionDefinition(source_definition_id=source, display_name="Test attack",
                            owner_id="actor:test", economy=EconomyKind.NONE,
                            resolution_kind="TYPED", target_kind="SELF",
                            parameters={"typed": typed})


def _context(source, typed, catalog=None):
    engine = SimpleNamespace(action_catalog=dict(catalog or {}))
    return Context(engine, None, _action(source, typed), None, typed, [], None, {})


@pytest.mark.parametrize("typed", [
    {"delivered_by": "action:weapon.qiang#trip"},
    {"weapon_source_id": "action:weapon.qiang#pin"},
    {"delivered_by": "action:weapon.fu", "weapon_source_id": "action:weapon.qiang#pin"},
    {},
])
def test_weapon_delivery_variants_share_base_identity(typed):
    ctx = _context("action:weapon.qiang#trip", typed)
    assert weapon_identity(ctx) == "action:weapon.qiang"


@pytest.mark.parametrize("delivery", [{}, {"delivered_by": "action:weapon.qiang#trip"},
                                     {"weapon_source_id": "action:weapon.qiang#pin"}])
def test_opportunity_resolves_base_action_delivery(delivery):
    base = "action:technique#opt1" if delivery else "action:weapon.qiang#trip"
    ctx = _context("action:opportunity", {"opportunity_of": base},
                   {base: _action(base, delivery)})
    assert weapon_identity(ctx) == "action:weapon.qiang"


def test_opportunity_unknown_action_and_catalog_cycle_terminate():
    ctx = _context("action:opportunity", {"opportunity_of": "action:missing#opt1"})
    assert weapon_identity(ctx) == "action:missing"
    ctx.engine.action_catalog["action:missing#opt1"] = _action(
        "action:missing#opt1", {"opportunity_of": "action:opportunity"})
    assert weapon_identity(ctx) == "action:opportunity"


@pytest.mark.parametrize("suffix", ["", ":Stealth", ":ACTOR", ":DEFENDER", ":custom_skill"])
def test_check_catalog_resolution_preserves_namespaces_and_variants(suffix):
    source = "action:typed.actor.TAL_EXAMPLE#opt1"
    engine = SimpleNamespace(action_catalog={source: SimpleNamespace(display_name="Named Technique")})
    resolved = check_source_id(engine, "CHECK:" + source + suffix)
    assert resolved == source
    assert roll_source_name(engine, RollCtx(engine, None, "check", None, source_id=resolved)) == "Named Technique"


@pytest.mark.parametrize("source,expected", [
    ("system:combat.hold_position:Stealth", "Hold Position"),
    ("system:combat.movement:ACTOR", "Movement"),
    ("system:combat.movement:DEFENDER", "Movement"),
    ("system:combat.hold_position", "Hold Position"),
    ("action:typed.actor.TAL_EXAMPLE_STRIKE#opt1:Stealth", "Example Strike"),
    ("", "Ability Check"),
])
def test_check_noncatalog_fallback_is_readable(source, expected):
    engine = SimpleNamespace(action_catalog={})
    resolved = check_source_id(engine, "CHECK:" + source)
    assert roll_source_name(engine, RollCtx(engine, None, "check", None, source_id=resolved)) == expected

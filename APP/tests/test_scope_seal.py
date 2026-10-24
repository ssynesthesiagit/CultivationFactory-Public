"""Harmful area recipient scope is sealed at authority build, not re-read from prose.

One inclusive-wording harmful area record is compiled twice: once with its real
printed rules text and once with the same text scrambled, as public CI exports
it. The sealed scope must not depend on which text the compiler was handed.
"""
from combat import factory_compiler
from combat.factory_compiler import _action_definition

MECHANIC = "TEST_SCOPE_SEAL_WAVE"
REAL = "Each creature in the area takes 4 fire damage."
SCRAMBLED = "Eahc ertaure in teh aera tkaes 4 fire damge."


def _row():
    """A compiled-row shape carrying only the area record; no per-row recipient evidence."""
    effects = [{"type": "damage", "flat": 4, "damage_types": ["fire"], "dice": "", "formula": "none"}]
    area = {"shape": "sphere", "size_ft": 15}
    mechanic = {"mechanic_id": MECHANIC, "area": dict(area), "effects": effects}
    typed = {"area": dict(area), "effects": effects, "riders": [], "duration": {"kind": "instant"},
             "numbers": {"cl": 5}, "source": MECHANIC, "sphere": "tianxia.sphere.test"}
    return {"action_id": MECHANIC, "name": "Scope Seal Wave", "economy": "action", "target_kind": "point",
            "range_ft": 30, "costs": [], "mechanic": mechanic, "typed": typed}


def _compiled_area(monkeypatch, text):
    monkeypatch.setattr(factory_compiler, "_rules_text", lambda: {MECHANIC: text})
    action = _action_definition(_row(), "actor:test", {"cl": 5})
    return action.parameters["typed"]["area"]


def test_inclusive_harmful_area_scope_survives_scrambled_rules_text(monkeypatch):
    real = _compiled_area(monkeypatch, REAL)
    scrambled = _compiled_area(monkeypatch, SCRAMBLED)
    # The printed wording is genuinely inclusive: every creature, allies included.
    assert real["recipients"] == "all"
    assert real["harmful_recipients"] == "all"
    keys = ("recipients", "harmful_recipients", "harmful_recipient_override", "include_self",
            "exclude_self", "explicit_harmful_recipients", "chosen_harmful_recipients",
            "harmful_payload_scopes")
    assert {k: scrambled.get(k) for k in keys} == {k: real.get(k) for k in keys}

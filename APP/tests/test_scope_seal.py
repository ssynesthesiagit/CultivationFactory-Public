"""Harmful area recipient scope is sealed at authority build, from the final rows, not re-read from prose.

One inclusive-wording harmful area record is compiled twice: once with its real
printed rules text and once with the same text scrambled, as public CI exports
it. The sealed scope must not depend on which text the compiler was handed.

The builder runs apply_cl_scaling (adds dice_by_cl to damage rows) and option
splits after typing, so the seal is taken last (seal_mechanic_areas). A seal
taken before those rewrites no longer matches the row's content hash.
"""
from combat import factory_compiler
from combat.area_recipients import _payload_key, seal_mechanic_areas
from combat.factory_compiler import _action_definition
from factory_authoring.typed_mechanics import apply_cl_scaling

MECHANIC = "TEST_SCOPE_SEAL_WAVE"
REAL = "Each creature in the area takes 4 fire damage."
SCRAMBLED = "Eahc ertaure in teh aera tkaes 4 fire damge."
# The same damage with the printed CL-scaled dice table, as the builder sees it.
REAL_CL = REAL + "\n\n| CL | Damage |\n| 1–4 | `1d6` |\n| 5–9 | `2d6` |\n| 10–20 | `3d6` |"
SCRAMBLED_CL = "Eahc ertaure in teh aera tkaes 4 fire damge.\n\n| CL | Damge |\n| 1–4 | `1d6` |\n| 5–9 | `2d6` |\n| 10–20 | `3d6` |"


def _damage():
    return [{"type": "damage", "flat": 4, "damage_types": ["fire"]}]


def _built(text, effects=None):
    """A mechanic in the builder's final order: CL dice first, then the seal of the final rows."""
    mechanic = {"effects": effects or _damage(), "area": {"shape": "sphere", "size_ft": 15}}
    apply_cl_scaling(mechanic, text)
    seal_mechanic_areas(mechanic, text)
    return mechanic


def _row(mechanic):
    area = mechanic["area"]
    typed = {"area": dict(area), "effects": mechanic["effects"], "riders": [], "duration": {"kind": "instant"},
             "numbers": {"cl": 5}, "source": MECHANIC, "sphere": "tianxia.sphere.test"}
    return {"action_id": MECHANIC, "name": "Scope Seal Wave", "economy": "action", "target_kind": "point",
            "range_ft": 30, "costs": [], "mechanic": {"mechanic_id": MECHANIC, "area": dict(area), "effects": mechanic["effects"]},
            "typed": typed}


def _compiled_area(monkeypatch, mechanic, text):
    monkeypatch.setattr(factory_compiler, "_rules_text", lambda: {MECHANIC: text})
    action = _action_definition(_row(mechanic), "actor:test", {"cl": 5})
    return action.parameters["typed"]["area"]


KEYS = ("recipients", "harmful_recipients", "harmful_recipient_override", "include_self",
        "exclude_self", "explicit_harmful_recipients", "chosen_harmful_recipients",
        "harmful_payload_scopes")


def test_inclusive_harmful_area_scope_survives_scrambled_rules_text(monkeypatch):
    mechanic = _built(REAL)
    real = _compiled_area(monkeypatch, mechanic, REAL)
    scrambled = _compiled_area(monkeypatch, mechanic, SCRAMBLED)
    # The printed wording is genuinely inclusive: every creature, allies included.
    assert real["recipients"] == "all"
    assert real["harmful_recipients"] == "all"
    assert {k: scrambled.get(k) for k in KEYS} == {k: real.get(k) for k in KEYS}


def test_cl_scaled_harmful_area_keeps_scope_under_scrambled_text(monkeypatch):
    # Regression: the seal used to be taken before apply_cl_scaling added dice_by_cl, so its
    # payload key no longer matched the row and the inclusive damage fell back to "hostile".
    mechanic = _built(REAL_CL)
    assert all("dice_by_cl" in row for row in mechanic["effects"])
    seal = mechanic["area"]["printed_recipient_seal"]
    assert set(seal["payload_scopes"]) == {_payload_key(row) for row in mechanic["effects"]}
    real = _compiled_area(monkeypatch, mechanic, REAL_CL)
    scrambled = _compiled_area(monkeypatch, mechanic, SCRAMBLED_CL)
    assert real["recipients"] == "all"
    assert real["harmful_recipients"] == "all"
    assert {k: scrambled.get(k) for k in KEYS} == {k: real.get(k) for k in KEYS}


def test_option_area_is_sealed_from_its_own_rows():
    option = {"label": "Wave", "effects": [{"type": "damage", "flat": 4, "damage_types": ["fire"]}],
              "area": {"shape": "sphere", "size_ft": 15}}
    mechanic = {"effects": [], "area": None, "options": [option]}
    seal_mechanic_areas(mechanic, REAL_CL)
    sealed = mechanic["options"][0]["area"]["printed_recipient_seal"]
    assert set(sealed["payload_scopes"]) == {_payload_key(row) for row in option["effects"]}
    assert sealed["payload_scopes"] == {_payload_key(row): "all" for row in option["effects"]}


def test_stale_seal_is_removed_when_no_harmful_payload_remains():
    mechanic = _built(REAL)
    mechanic["effects"] = [{"type": "condition", "condition": "prone"}]
    seal_mechanic_areas(mechanic, REAL)
    assert "printed_recipient_seal" not in mechanic["area"]


def test_every_harmful_authority_area_carries_its_sealed_scope():
    """Guard: a harmful area payload in the generated authority always has the build-time seal.

    A record without the seal would make the compiler read prose again; that path exists only for
    legacy records outside the authority."""
    import json
    from pathlib import Path
    from combat.area_recipients import _harmful, _payload_key

    path = Path(__file__).resolve().parents[1] / "authority" / "Tianxia_Typed_Mechanics_Authority_R1.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    missing = []
    for key, mechanic in data["mechanics"].items():
        trees = [("", mechanic), *[(f"option{i}", o) for i, o in enumerate(mechanic.get("options") or [])]]
        if mechanic.get("modifier"):
            trees.append(("modifier", mechanic["modifier"]))
        for name, tree in trees:
            area = tree.get("area")
            effects = tree.get("effects") or []
            if not isinstance(area, dict) or not area.get("size_ft"):
                continue
            harmful = [row for row in effects if isinstance(row, dict) and _harmful(row) and row.get("applies_to") != "self"]
            if not harmful:
                continue
            seal = area.get("printed_recipient_seal")
            if seal is None or not all(_payload_key(row) in seal["payload_scopes"] for row in harmful):
                missing.append(f"{key}:{name}")
    assert not missing, missing[:20]

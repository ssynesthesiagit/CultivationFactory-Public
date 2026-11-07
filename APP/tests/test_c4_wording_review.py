"""C4 presentation regressions; no browser or GUI required."""
import pytest

from combat.factory_compiler import compile_character
from combat.tabletop import engine_button_description
from tests.h1_support import sheet
from types import SimpleNamespace

from combat.ext.benefit_suppression import benefits


@pytest.mark.parametrize("pool", ["Qi", "Stamina", "Resonance"])
@pytest.mark.parametrize("name,cost", [
    ("Aegis: Armored Aegis", 0),
    ("Aegis: Armored Aegis (Persistent)", 2),
    ("Aegis: Spell Ward", 1),
    ("Aegis: Spell Ward (Persistent)", 3),
    ("Ward: Protected Health", 0),
    ("Ward: Protected Health (Persistent)", 2),
])
def test_protection_button_names_full_paying_pool_cost(pool, name, cost):
    bundle = compile_character(sheet([
        "PROTECTION_BASE_AEGIS", "tianxia.talent.protection.spell_ward",
        "tianxia.talent.protection.protected_health",
    ], primary=pool), actor_id="actor:factory.wording")
    row = next(a for a in bundle["action_catalog"] if a["display_name"] == name)
    text = engine_button_description(row)
    assert "Action" in text
    assert ("1 hour" if name.startswith("Aegis") else "1 minute") in text
    assert ("without Concentration" if "Persistent" in name else "Requires Concentration") in text
    if cost:
        assert f"Cost: {cost} {pool} from your cultivation resource pool" in text
        assert row["costs"] == [[f"resource:core.{pool.lower()}", cost]]
    else:
        assert "Cost: no cultivation resources." in text
        assert not row["costs"]
    if name == "Aegis: Spell Ward (Persistent)":
        assert "1 base + 2 to make it Persistent" in text
    if name.startswith("Ward: Protected Health"):
        assert "half Poison damage" in text and "Advantage on saves against poison and disease" in text


@pytest.mark.parametrize("source,expected", [
    ("TAL_VOID_COURT_OF_THE_EMPTY_HORIZON", "Court of the Empty Horizon - Void Domain"),
    ("action:typed.owner.court:zone:inside", "Court of the Empty Horizon"),
    ("action:typed.owner.court#variant", "Court of the Empty Horizon"),
    ("TAL_UNKNOWN_INTERNAL_ID", "an unnamed temporary effect"),
    ("", "an unnamed temporary effect"),
])
def test_benefit_menu_resolves_sources_without_internal_names(source, expected):
    engine = SimpleNamespace(action_catalog={
        "action:typed.owner.court": SimpleNamespace(display_name="Court of the Empty Horizon"),
    })
    creature = SimpleNamespace(modifiers={"resist": SimpleNamespace(
        target_field="damage_resistance", value="FORCE", expires_on="END_OF_SOURCE_NEXT_TURN",
        source_definition_id=source)}, conditions={"invisible": SimpleNamespace(
        condition_id="condition:typed.invisible", expires_on="END_OF_SOURCE_NEXT_TURN",
        source_definition_id=source)})
    rows = benefits(engine, creature)
    assert len(rows) == 2
    assert all(expected in row["label"] for row in rows)
    assert "halves that damage" in rows[0]["label"]
    assert all("TAL_" not in row["label"] and "action:typed" not in row["label"] for row in rows)
    # The transport identity and filtering stay unchanged.
    assert [row["id"] for row in rows] == ["modifier:resist", "condition:invisible"]
    assert benefits(engine, creature, ["damage_resistance"]) == rows[:1]
    creature.modifiers["resist"].expires_on = "UNTIL_REMOVED"
    creature.conditions["invisible"].expires_on = "UNTIL_REMOVED"
    assert not benefits(engine, creature)


def test_marked_binding_button_explains_effect_duration_and_cost():
    bundle = compile_character(sheet(["tianxia.talent.ink.binding_script"]), actor_id="actor:factory.wording")
    row = next(a for a in bundle["action_catalog"] if a["display_name"] == "Binding Script (marked target)")
    text = engine_button_description(row)
    for part in ("Bonus Action", "60 feet", "anchors your Ink talents", "Strength save", "Restrained",
                 "Speed reduced by 10 feet", "start of your next turn", "Cost: 2 Qi"):
        assert part in text

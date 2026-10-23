"""Contract for the shared maneuver/Advancing Carnage weapon-action query."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from combat.ext.weapon_actions import weapon_attacks
from combat.gate2_runtime_models import EconomyKind


def action(source="action:test.sword", *, typed=None, **fields):
    attack = {"type": "attack", "attack_kind": "weapon"}
    return SimpleNamespace(**{
        "source_definition_id": source, "owner_id": "actor:test",
        "economy": EconomyKind.ACTION, "target_kind": "HOSTILE_ENTITY",
        "parameters": {"typed": {"weapon": {"name": "Sword"}, "effects": [attack],
                                  "range_ft": 5, **(typed or {})}}, **fields,
    })


@pytest.mark.parametrize("source,typed,kind", [
    ("action:test.sword", {}, "melee"),
    ("action:test.bow", {"range_ft": 60}, "ranged"),
    ("action:test.spear#thrown", {"range_ft": 20}, "thrown"),
    ("action:test.natural.claw", {"range_ft": 10}, "natural"),
    ("action:test.fist", {"weapon": {}, "unarmed_option": True}, "unarmed"),
    ("action:test.strike", {"effects": [{"type": "attack", "attack_kind": "unarmed"}]}, "unarmed"),
    ("action:test.default", {"range_ft": None}, "melee"),
])
def test_shared_query_classifies_base_attacks_without_copying_or_mutating(source, typed, kind):
    row = action(source, typed=typed)
    before = deepcopy(row)
    result = weapon_attacks([row], "actor:test")
    assert len(result) == 1
    selected, data, attack, found_kind = result[0]
    assert selected is row and data is row.parameters["typed"]
    assert attack is data["effects"][0] and found_kind == kind
    assert row == before


@pytest.mark.parametrize("fields,typed", [
    ({"owner_id": "actor:other"}, {}),
    ({"economy": EconomyKind.BONUS_ACTION}, {}),
    ({"target_kind": "SELF"}, {}),
    ({}, {"effects": []}),
    ({}, {"effects": ["attack", {"type": "damage"}]}),
    ({}, {"variant_of": "action:test.sword"}),
    ({"source_definition_id": "action:test.sword#variant"}, {}),
    ({}, {"source": "improvised:chair"}),
    ({}, {"weapon": {}, "unarmed_option": False}),
    ({"parameters": {"typed": {"weapon": True, "effects": [{"type": "attack"}]},
                     "requires_held_weapon": True}}, {}),
    ({"source_definition_id": "action:test.wall_attack"}, {}),
    ({"source_definition_id": "action:test.wall_attack#thrown"}, {}),
    ({"parameters": {}}, {}),
])
def test_shared_query_excludes_ineligible_actions(fields, typed):
    row = action(typed=typed, **fields)
    before = deepcopy(row)
    assert weapon_attacks([row], "actor:test") == []
    assert row == before


def test_shared_query_preserves_input_order_and_accepts_serialized_economy():
    bow = action("action:test.bow", typed={"range_ft": 60}, economy="ACTION")
    sword = action()
    excluded = action(owner_id="actor:other")
    fist = action("action:test.fist", typed={"unarmed_option": True})
    rows = weapon_attacks([bow, excluded, sword, fist], "actor:test")
    assert [row[0] for row in rows] == [bow, sword, fist]
    # Advancing Carnage chooses the first eligible melee/unarmed/natural row.
    assert next(row[0] for row in rows if row[3] in ("melee", "unarmed", "natural")) is sword


@pytest.mark.parametrize('suffix', ['#thrown', '#offhand', '#disarm', '#method_push'])
def test_weapon_identity_keeps_delivery_variants_together(suffix):
    from combat.ext.weapon_actions import strike_identity
    assert strike_identity(action('action:test.sword' + suffix)) == 'action:test.sword'
    assert strike_identity(action('action:test.other' + suffix)) != 'action:test.sword'


@pytest.mark.parametrize('field', ['option_of', 'variant_of'])
def test_weapon_identity_follows_explicit_compiler_parent(field):
    from combat.ext.weapon_actions import strike_identity
    assert strike_identity(action('action:test.modified', typed={field: 'action:test.natural.claw#disarm'})) == 'action:test.natural.claw'

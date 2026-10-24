"""Finding F2: the owner-attack lookup must match the typed inventory key as well as the row key.

Fails on the merged code, where the typed guard was dropped from compile_character.
"""
from types import SimpleNamespace

from combat import factory_compiler


def _row(owner_action, row_key, typed_key):
    action = SimpleNamespace(parameters={"typed": {"inventory_key": typed_key}})
    return {"owner_action": owner_action, "row": {"inventory_key": row_key}}, action


def test_attack_lookup_requires_typed_inventory_key_match():
    entry_a, action_a = _row("action:typed.a.weapon.x", row_key="given.0", typed_key="other.1")
    entry_b, action_b = _row("action:typed.b.weapon.y", row_key="given.0", typed_key="given.0")
    by_id = {"action:typed.a.weapon.x": action_a, "action:typed.b.weapon.y": action_b}
    item = {"key": "given.0"}
    # Two entries share the row key; only the one whose typed key also matches may be chosen.
    assert factory_compiler._item_weapon_attack([entry_a, entry_b], by_id, item) == "action:typed.b.weapon.y"


def test_attack_lookup_returns_none_when_only_row_key_matches():
    entry, action = _row("action:typed.a.weapon.x", row_key="given.0", typed_key="other.1")
    by_id = {"action:typed.a.weapon.x": action}
    assert factory_compiler._item_weapon_attack([entry], by_id, {"key": "given.0"}) is None

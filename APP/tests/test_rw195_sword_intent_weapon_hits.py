"""RW195: Sword Intent reaches weapon-delivered sword attacks, not only the named Sword Seed / Domain Armament Attack.

The printed trigger is "a Seed-Sword Attack, Sword Domain Armament Attack, weapon attack using your bound Seed Sword,
Qi-powered sword technique, or weapon-delivered technique delivered through a qualifying sword". The reviewed modifier
names two compiled actions and carries a ``scope_filter`` (weapon group "sword", sword-sphere attacks) so the native
weapon attack the fighter makes with a Sword gets the same once-per-turn Intent choice. Every assertion reads the
compiled action catalog the engine itself builds; nothing calls the plug-in or injects metadata.
"""
from __future__ import annotations

from tests.hunt12_support import fight, ME
from tests.test_mgr_t14_sword_in_hand import JIAN, SWORD_KIT

INTENT_FEATURE = "tianxia.subpath.qi.ten_thousand_sword_array_cultivator.feature.sword_intent"


def _actions(engine, predicate):
    return [row for row in engine.action_catalog.values() if row.owner_id == ME and predicate(row)]


def _carries_intent(action):
    return repr((action.parameters or {}).get("typed") or {}).count(INTENT_FEATURE) > 0


def test_sword_intent_is_offered_on_the_wielded_sword_weapon_attack(tmp_path):
    """The native Jian attack, which no compiled name reaches, carries the Sword Intent choice."""
    combat, _table, mid = fight(tmp_path, [INTENT_FEATURE], cl=18, dc=100, kit=SWORD_KIT)
    engine = combat._load_session(mid).engine
    jian_attacks = _actions(engine, lambda row: "#" not in row.source_definition_id
                            and ((row.parameters or {}).get("typed") or {}).get("weapon", {}).get("implement_id") == JIAN)
    assert jian_attacks, "the fighter has no Jian weapon attack to test"
    assert any(_carries_intent(row) for row in jian_attacks), \
        "a Sword weapon attack must offer Sword Intent (weapon group 'sword' in the modifier's scope_filter)"


def test_sword_intent_is_not_offered_on_an_unarmed_attack(tmp_path):
    """A selector on weapon groups and sword-sphere attacks leaves the fighter's unarmed strike alone."""
    combat, _table, mid = fight(tmp_path, [INTENT_FEATURE], cl=18, dc=100, kit=SWORD_KIT)
    engine = combat._load_session(mid).engine
    unarmed = _actions(engine, lambda row: "natural" in row.source_definition_id)
    assert unarmed, "the fighter has no unarmed strike to test"
    assert not any(_carries_intent(row) for row in unarmed)

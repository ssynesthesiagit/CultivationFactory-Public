"""Borrowed weapon rider settings follow possession at the live table."""
from tests.test_tabletop_hunt6 import LEFT, table_fight

DAGGER = {"starting_kit": {"items": [
    {"item_id": "tianxia.mortal.weapon.bi_shou", "name": "Bi Shou (Dagger)", "quantity": 1}]}}


def test_borrowed_weapon_riders_are_not_offered_until_held(tmp_path):
    combat, table, mid = table_fight(tmp_path, ["TAL_VOID_NULLIFYING_STRIKE"], cl=5,
                                      primary="Stamina", kit=DAGGER)
    engine = combat._load_session(mid).engine
    borrowed = [a for a in engine.action_catalog.values() if a.owner_id == LEFT
                and a.parameters.get("requires_held_weapon")
                and (a.parameters.get("typed") or {}).get("attack_modifier_loadout")]
    assert borrowed
    settings = [a for a in engine.action_catalog.values() if a.owner_id == LEFT
                and (a.parameters.get("attack_modifier_setting") or {}).get("family")
                in {a.source_definition_id for a in borrowed}]
    assert settings
    assert all(a.parameters.get("requires_held_weapon") for a in settings)
    state = table.state(mid)
    sources = {g["source_definition_id"] for g in state["menu"]["actions"]}
    assert not sources.intersection(a.source_definition_id for a in settings)
    assert not {a.source_definition_id for a in borrowed} & {
        e["base"] for e in state["shapes"].get(LEFT, [])}
    own = [a for a in engine.action_catalog.values() if a.owner_id == LEFT
           and ".weapon.bi_shou" in a.source_definition_id
           and not a.parameters.get("requires_held_weapon")]
    assert any(a.source_definition_id in sources for a in own if a.source_definition_id.endswith(".weapon.bi_shou"))
    assert any(a.source_definition_id in sources for a in own if a.source_definition_id.endswith(".weapon.bi_shou#thrown"))
    assert any((a.parameters.get("attack_modifier_setting") or {}).get("family") in
               {b.source_definition_id for b in own} and a.source_definition_id in sources
               for a in engine.action_catalog.values())

"""Copied Mountain-Weight Inscription dice belong to the weapon's critical hit."""
import pytest
from tests.hunt12_support import ME, FOE, candidate, fight, hit_dice, reload, send

KIT = {"starting_kit": {"items": [], "resolved_treasure_weapon": {
    "chassis": {"item_id": "test.mountainblade", "name": "Mountainblade", "damage": "1d10 Slashing", "properties": ""},
    "refinement_bonus": 0,
    "enchantments": [{"name": "Mountain-Weight Inscription",
                      "text": "Whenever you hit with the weapon, the target takes an additional 1d4 force damage."}]}}}


@pytest.mark.parametrize("auto", [False, True])
@pytest.mark.parametrize("critical", [False, True])
def test_inscription_on_hit_doubles_only_on_critical_table_reload(tmp_path, monkeypatch, auto, critical):
    combat, table, mid = fight(tmp_path, kit=KIT)
    hit_dice(monkeypatch, critical=critical)
    chosen = candidate(combat, mid, lambda c: c.display_name == "Mountainblade attack" and tuple(c.target_ids) == (FOE,))
    if auto:
        combat.set_controller_mode(mid, actor_id=ME, controller_mode="LOCAL_AUTO")
    assert send(combat, table, mid, chosen, auto=auto)["status"] == "COMMITTED"
    engine = reload(tmp_path, mid)
    rolled = [e.payload["expression"] for e in engine.events if e.event_type == "DAMAGE_ROLLED"]
    assert rolled == (["2d10+4", "2d4+0"] if critical else ["1d10+4", "1d4+0"])


def test_hit_context_does_not_double_separate_save_damage(tmp_path, monkeypatch):
    from tests import hunt12_support
    original = hunt12_support.compile_character

    def compile_with_save(*args, **kwargs):
        bundle = original(*args, **kwargs)
        for action in bundle["action_catalog"]:
            if action["display_name"] == "Mountainblade attack":
                action["parameters"]["typed"]["effects"][0]["on_hit"].append({
                    "type": "save", "ability": "con", "on_fail": [{"type": "damage", "applies_to": "target",
                    "dice": {"count": 1, "sides": 8, "bonus": 2}, "damage_types": ["fire"]}], "on_success": []})
                action["parameters"]["typed"]["effects"].append({"type": "damage", "applies_to": "target",
                    "dice": {"count": 1, "sides": 6, "bonus": 5}, "damage_types": ["cold"]})
        return bundle

    monkeypatch.setattr(hunt12_support, "compile_character", compile_with_save)
    combat, table, mid = fight(tmp_path, kit=KIT)
    hit_dice(monkeypatch, critical=True)
    chosen = candidate(combat, mid, lambda c: c.display_name == "Mountainblade attack" and tuple(c.target_ids) == (FOE,))
    assert send(combat, table, mid, chosen)["status"] == "COMMITTED"
    engine = reload(tmp_path, mid)
    assert [e.payload["expression"] for e in engine.events if e.event_type == "DAMAGE_ROLLED"] == ["2d10+4", "2d4+0", "1d8+2", "1d6+5"]

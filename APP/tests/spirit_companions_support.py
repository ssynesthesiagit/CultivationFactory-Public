"""Spirit Companion sheets shared by the C9 rider lane and SOL113's dying-table helper.

``tests.test_riders_c9`` keeps its own typing injection (C9_OLD compiles against the base authority) and
re-exports this sheet; ``tests.test_sol113_dying_table`` only needs the current Sphere and talent rows, so it
imports here instead of pulling the C9 lane's history-capable helpers into its dependency closure.
"""
import json
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SC = "tianxia.talent.spirit_companions."
JIAN = "tianxia.mortal.weapon.jian"
SPIRIT_KIT = [SC + "covenant_spirit", SC + "battle_manifestation"]


@lru_cache(maxsize=1)
def current_mechanics():
    """The shipped typed mechanics, read once; never repository history."""
    return json.loads((ROOT / "authority/Tianxia_Typed_Mechanics_Authority_R1.json").read_text())["mechanics"]


def sheet(ids, *, cl=10, dc=15, sphere=None, items=(JIAN,), pool=30, ac=14, mechanics=None):
    """A compiled-character sheet for ``ids``, with ``mechanics`` overriding the shipped authority."""
    mech = current_mechanics() if mechanics is None else mechanics
    sphere = sphere or (mech[ids[0]]["sphere_id"] if ids else None)
    bases = [key for key, row in mech.items() if sphere and row.get("sphere_id") == sphere and row.get("kind") == "base_ability"]
    return {
        "identity": {"proficiency_bonus": 4, "cultivation_level": cl, "path": "Qi Cultivation", "key_ability": "WIS"},
        "ability_scores_and_statistics": {
            "abilities": [{"ability": a, "score": 14, "modifier": 2} for a in ("STR", "DEX", "CON", "INT", "WIS", "CHA")],
            "primary_resource": {"name": "Qi", "maximum": pool}, "armor_class": {"base_value": ac}, "hit_points": {"maximum": 60},
            "speed": {"walking_ft": 30}, "technique_save_dc": dc, "technique_attack_bonus": 8},
        "spheres_and_talents": {"sphere_record_ids": [sphere] if sphere else [],
                                "learned_talent_record_ids": list(dict.fromkeys([*bases, *ids]))},
        "equipment": [{"starting_kit": {"items": [{"item_id": item, "quantity": 1} for item in items]}}],
    }

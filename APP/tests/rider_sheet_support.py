"""Character sheets the rider-lane tests compile, and the weapon ids they name.

A sheet is pure data: the dict the factory compiler reads. The typed-authority document comes from the caller
(default: the authority this checkout ships), so a rider lane's OLD=1 mode can compile the very same sheet against
the base authority of an older commit. Nothing here reads repository history.

Users: tests/test_riders_c9.py and its c9 family, tests/test_riders_c10.py, tests/test_c10_review_fixup.py,
tests/test_sol113_dying_table.py (a spirit kit's spheres and talents on a SOL113 fighter).
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from combat.factory_compiler import compile_character

ROOT = Path(__file__).resolve().parents[1]
JIAN = "tianxia.mortal.weapon.jian"
BOW = "tianxia.mortal.weapon.gong_jian"
DAGGER = "tianxia.mortal.weapon.bi_shou"
SHORTSWORD = "tianxia.mortal.weapon.duan_jian"
# The two Spirit Companions talents a spirit kit's fighter owns (riders c9 family, SOL113 spirit cases).
SPIRIT_KIT = ["tianxia.talent.spirit_companions.covenant_spirit",
              "tianxia.talent.spirit_companions.battle_manifestation"]
@lru_cache(maxsize=1)
def authority():
    """The typed-authority document this checkout ships (what compile_character takes)."""
    return json.loads((ROOT / "authority/Tianxia_Typed_Mechanics_Authority_R1.json").read_text())


def sheet(ids, *, cl=10, dc=15, sphere=None, items=(JIAN,), pool=30, ac=14, pb=4, score=14, key="WIS", bases=True,
          authority_doc=None):
    """A character owning ``ids``.

    The sphere is the first owned record's own sphere unless given; with ``bases`` the sphere's base abilities are
    learned too, which is how the factory's acquisition producer delivers them.
    """
    mech = (authority_doc if authority_doc is not None else authority())["mechanics"]
    sphere = sphere or (mech[ids[0]]["sphere_id"] if ids else None)
    base = [row_id for row_id, row in mech.items()
            if bases and sphere and row.get("sphere_id") == sphere and row.get("kind") == "base_ability"]
    return {
        "identity": {"proficiency_bonus": pb, "cultivation_level": cl, "path": "Qi Cultivation", "key_ability": key},
        "ability_scores_and_statistics": {
            "abilities": [{"ability": a, "score": score, "modifier": (score - 10) // 2}
                          for a in ("STR", "DEX", "CON", "INT", "WIS", "CHA")],
            "primary_resource": {"name": "Qi", "maximum": pool}, "armor_class": {"base_value": ac},
            "hit_points": {"maximum": 60},
            "speed": {"walking_ft": 30}, "technique_save_dc": dc, "technique_attack_bonus": 8},
        "spheres_and_talents": {"sphere_record_ids": [sphere] if sphere else [],
                                "learned_talent_record_ids": list(dict.fromkeys([*base, *ids]))},
        "equipment": [{"starting_kit": {"items": [{"item_id": item, "quantity": 1} for item in items]}}],
    }


def bundle(ids, *, actor_id, authority_doc=None, **kwargs):
    """The compiled character for :func:`sheet`, for the actor it is compiled for."""
    document = authority_doc if authority_doc is not None else authority()
    return compile_character(sheet(ids, authority_doc=document, **kwargs), actor_id=actor_id,
                             typed_authority=document)

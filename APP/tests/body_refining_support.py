"""Synthetic portable characters for S1; no owner fixtures, history or model calls."""
from pathlib import Path
import json
import zipfile

from canonical_catalog.service import CanonicalCatalogAuthorityService
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService

ROOT = Path(__file__).resolve().parents[1]
PID = "0badc0de-0000-4000-8000-000000000031"
BODY = "tianxia.path.body_refining"
QI = "tianxia.path.qi_cultivation"
DARK = "tianxia.sphere.dark"
UPGRADE = "insight.night-bound-body"


def sheet(*, cl=4, paths=None, spheres=(), talents=(), insights=()):
    return {
        "identity": {"display_name": "Body Student", "cultivation_level": cl, "proficiency_bonus": 2,
                     "path_ids": paths if paths is not None else [BODY], "key_ability": "INT"},
        "ability_scores_and_statistics": {
            "abilities": [{"ability": a, "score": 18 if a == "CON" else 12,
                          "modifier": 4 if a == "CON" else 1}
                         for a in ("STR", "DEX", "CON", "INT", "WIS", "CHA")],
            "armor_class": {"base_value": 12}, "hit_points": {"maximum": 40},
            "speed": {"walking_ft": 30}, "technique_save_dc": 11, "technique_attack_bonus": 3,
            "primary_resource": {"name": "Stamina", "maximum": 30}},
        "spheres_and_talents": {"sphere_record_ids": list(spheres), "learned_talent_record_ids": list(talents),
                               "cultivation_insight_record_ids": list(insights)},
        "selected_record_sections": {},
    }


def install(root, document, *, pid=PID):
    path = root / "portable_characters" / pid / "current.zip"
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(document))
    return path


def service(root):
    result = TabletopService(CombatService(ROOT, root), root)
    result.canonical_catalog = CanonicalCatalogAuthorityService(ROOT)
    return result

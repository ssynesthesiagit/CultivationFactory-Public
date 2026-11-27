"""Gatherer Training learns from one canonical skill row on the installed sheet."""
import json
from pathlib import Path
from zipfile import ZipFile

import pytest

from app.models import TabletopAdvanceRequest
from canonical_catalog.service import CanonicalCatalogAuthorityService
from combat.ext import gatherer_training
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService

ROOT = Path(__file__).resolve().parents[1]
PROJECT = "0badc0de-0000-4000-8000-000000000015"
SPHERE = "tianxia.sphere.harvesting_gathering"
BONUS = "tianxia.talent.harvesting_gathering.field_ledger"
PATH = "tianxia.path.qi_cultivation"


@pytest.mark.parametrize(("rank", "total", "bonus_talent"), [(2, 9, BONUS), (0, 2, None)],
                         ids=["already-expert", "not-yet-proficient"])
def test_gatherer_learns_from_a_padded_nature_row(tmp_path, monkeypatch, rank, total, bonus_talent):
    # The public export may rewrite prose. Only the integrity check is stubbed;
    # advancement, its persisted choice and the reopened projection are real.
    monkeypatch.setattr(gatherer_training, "_text_matches", lambda: True)
    nature = {"skill": " Nature ", "bonus": total, "proficiency_multiplier": rank}
    doc = {
        "identity": {"display_name": "Gatherer", "cultivation_level": 1, "proficiency_bonus": 2,
                     "path_ids": [PATH], "key_ability": "CON"},
        "path_and_subpath": {"path_record_id": PATH, "path_record_ids": [PATH]},
        "background_origin": {"background": {"background_id": "tianxia.background.abandoned_orphan"}},
        "ability_scores_and_statistics": {
            "abilities": [{"ability": key, "score": 14, "modifier": 2}
                          for key in ("STR", "DEX", "CON", "INT", "WIS", "CHA")],
            "armor_class": {"base_value": 12}, "hit_points": {"maximum": 30},
            "primary_resource": {"name": "Qi", "maximum": 10}, "speed": {"walking_ft": 30},
            "skills": [nature],
        },
        "proficiencies": {"skills": [], "tools": []},
        "spheres_and_talents": {"sphere_record_ids": [], "automatic_sphere_component_record_ids": [],
                               "learned_talent_record_ids": []},
        "equipment": [],
    }
    package = tmp_path / "portable_characters" / PROJECT
    package.mkdir(parents=True)
    with ZipFile(package / "current.zip", "w") as archive:
        archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(doc))

    table = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
    table.canonical_catalog = CanonicalCatalogAuthorityService(ROOT)
    learning = {"proficiency": "Nature"}
    if bonus_talent:
        learning["bonus_talent_id"] = bonus_talent
    request = TabletopAdvanceRequest.model_validate({"kind": "sphere", "record_id": SPHERE, "learning": learning})
    table.add_advancement(PROJECT, request.kind, request.record_id, gm=request.gm, learning=request.learning)

    cold = CombatService(ROOT, tmp_path)
    saved = TabletopService(cold, tmp_path).buttons.get(PROJECT)["advancement"]["spheres"][0]["learning"]
    assert saved["proficiency"] == "Nature"
    assert saved["already_proficient"] == int(rank > 0)
    learned = cold._factory_owner_sheet(PROJECT)
    assert learned["spheres_and_talents"]["learned_talent_record_ids"] == ([BONUS] if bonus_talent else [])
    [row] = learned["ability_scores_and_statistics"]["skills"]
    if rank:
        assert row == nature
    else:
        assert row["bonus"] == 4 and row["proficiency_multiplier"] == 1

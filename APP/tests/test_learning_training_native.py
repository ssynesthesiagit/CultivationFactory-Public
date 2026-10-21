"""Native portable sheet -> table acquisition -> fight -> cold mechanical replay."""
import copy
import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from canonical_catalog import CanonicalCatalogAuthorityService
from combat.gate2_runtime_content import AN
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.tabletop import TabletopError
from tests.h1_support import sheet

ROOT = Path(__file__).resolve().parents[1]
PID = "0badc0de-0000-4000-8000-000000000014"
AID = "actor:factory." + PID
ARENA = "battlefield:factory_pillar_arena"
# Explicit native fixture resource, also consumed by public snapshot dependency analysis.
NATIVE_AUTHORITY_PATHS = (
    ROOT / "authority/Tianxia_Sphere_Path_Access_R1.json",
    ROOT / "authority/Tianxia_Forged_Technique_Authority_R1.json",
    # Retained catalog/builder acceptance rebuilds these shipped CAT3 inputs.
    ROOT / "catalog_authority/cat3/source/INSIGHT_TYPE_MAPPING.json",
    ROOT / "catalog_authority/cat3/source/INSIGHT_GROUPING_INVENTORY.json",
    ROOT / "catalog_authority/cat3/source/SUPERSESSION_AND_COLLISION_LEDGER.json",
    ROOT / "catalog_authority/cat3/source/SPHERE_BASE_ABILITY_MATRIX.csv",
    ROOT / "catalog_authority/cat3/source/Tianxia_Central_Cultivation_Insights_AI_Reference_R5_Legacy_Restored.json",
)
PINS = {
    "ALCHEMY_BASE_ALCHEMY_TRAINING": "a7db5f2cd10be26e31bd7d6a111a948608244a33cb443e7dbac027133b84b87d",
    "JESTER_BASE_JESTER_TRAINING": "fe4634b8e1b6f0199c617e7cbb4ffb9ecf391284294cc63d0450fce5d98c8560",
    "LIFE_BASE_LIFE_INITIATION": "f5c08329605ce3ac025dd5482235df1748dd14cdfd7e89fd6aa586d21fd2a132",
    "SOURCE_BASE_SOURCE_TRAINING": "16c451520adae60673456fb6a374080a349a4ab571c24beb201c259838a8bef3",
    "SPEAR_BASE_SPEAR_TRAINING": "2b4e727b5e0547795fff0c7655f4aa6d13ff3fa0e863494770795ddadbfe5afb",
}
# The public CI export substitutes each printed body with a transformed copy, so
# the approved install's exact pins apply only when the owner's printed prose is
# the text the app loaded. Both environments still verify receipt/file agreement.
OWNER_PROSE = {
    "ALCHEMY_BASE_ALCHEMY_TRAINING": "When you learn Alchemy",
    "JESTER_BASE_JESTER_TRAINING": "gain proficiency in Charisma (Performance)",
    "LIFE_BASE_LIFE_INITIATION": "You can recognize obvious signs of bleeding",
    "SOURCE_BASE_SOURCE_TRAINING": "choose one Source talent and gain it for free",
    "SPEAR_BASE_SPEAR_TRAINING": "gain proficiency with spears, pikes, lances, and tridents",
}


def is_owner_prose(source, text):
    """True only for the owner install's printed text (the public export renames it)."""
    return OWNER_PROSE[source] in text


def native(tmp_path, *, skills=(), tools=(), weapons=(), cl=10, mods=None, key="INT"):
    assert all(path.is_file() for path in NATIVE_AUTHORITY_PATHS)
    doc = sheet([], cl=cl, key=key, name="Learner")
    doc["path_and_subpath"] = {"path_record_ids": ["tianxia.path.qi_cultivation"]}
    stats = doc["ability_scores_and_statistics"]
    for row in stats["abilities"]:
        if row["ability"] in (mods or {}):
            row["modifier"] = mods[row["ability"]]
            row["score"] = 10 + 2 * row["modifier"]
    stats["skills"] = [{"skill": name, "bonus": 4 + (mods or {}).get(
        {"Medicine": "WIS", "Performance": "CHA", "Deception": "CHA", "Acrobatics": "DEX"}.get(name, "WIS"), 2),
        "proficiency_multiplier": 1} for name in skills]
    stats["tool_proficiencies"] = list(tools)
    stats["weapon_proficiencies"] = list(weapons)
    folder = tmp_path / "portable_characters" / PID
    folder.mkdir(parents=True)
    with zipfile.ZipFile(folder / "current.zip", "w") as archive:
        archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(doc))
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    table.canonical_catalog = CanonicalCatalogAuthorityService(ROOT)
    return combat, table


def offered(table, sphere):
    return next(r["learning_choices"] for r in table.advancement(PID)["spheres"] if r["id"] == "tianxia.sphere." + sphere)


def picks(learning_options):
    chosen = {}
    for row in learning_options:
        chosen[row["id"]] = next(o["id"] for o in row["options"] if o["id"] not in chosen.values())
    return chosen


def acquire(table, sphere, selected=None):
    return table.add_advancement(PID, "sphere", "tianxia.sphere." + sphere,
                                 learning_choices=picks(offered(table, sphere)) if selected is None else selected)


def replay(combat, table, tmp_path):
    result = combat.create_factory_match(project_ids=[PID], opponent_actor_ids=[AN],
        control_modes={AID: "MANUAL", AN: "MANUAL"}, match_seed="TRAINING-NATIVE")
    mid = result["match_id"]
    menu = table.state(mid)["menu"]
    assert table.act(mid, menu["end_turn"], menu["decision_id"], menu["state_version"], 0, [])["status"] == "COMMITTED"
    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.model_dump(mode="json") == before
    assert loaded.mechanical.replay()["status"] == "PASS"
    return loaded

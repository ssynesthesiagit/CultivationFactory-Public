"""Shared synthetic helpers for the puppet scene tests (public: no owner prose, no private fixtures)."""
import json
import zipfile
from pathlib import Path

from canonical_catalog import CanonicalCatalogAuthorityService
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.ext.puppet_initiation import SOURCE, SPHERE, TOOLS, SKILL
from tests.h1_support import sheet
from tests.auto28_puppetry_support import turn, resolve

ROOT = Path(__file__).resolve().parents[1]
PID = "0badc0de-0000-4000-8000-000000000015"
OTHER = "0badc0de-0000-4000-8000-000000000016"
A = "actor:factory." + PID
B = "actor:factory." + OTHER
RESOURCES = (ROOT / "authority/Tianxia_Sphere_Path_Access_R1.json",
             ROOT / "authority/Tianxia_Forged_Technique_Authority_R1.json")


def printed_text():
    """The approved Puppet Initiation text, loaded from the corpus at test time."""
    return json.loads((ROOT / "authority/typed_mechanics/rules_text.json").read_text())[SOURCE]


def native(tmp_path, *, prior=None, cl=1):
    assert all(p.is_file() for p in RESOURCES)
    for pid in (PID, OTHER):
        doc = sheet([], cl=cl, key="INT", name="Puppeteer" if pid == PID else "Observer")
        doc["identity"]["proficiency_bonus"] = 2 + max(0, cl - 1) // 4
        doc["path_and_subpath"] = {"path_record_ids": ["tianxia.path.qi_cultivation"]}
        if prior and pid == PID:
            if prior == SKILL:
                doc["ability_scores_and_statistics"]["skills"] = [
                    {"skill": SKILL, "bonus": 4, "proficiency_multiplier": 1}]
            else:
                doc["ability_scores_and_statistics"]["tool_proficiencies"] = [prior]
        folder = tmp_path / "portable_characters" / pid
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(doc))
    return cold(tmp_path)


def cold(tmp_path):
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    table.canonical_catalog = CanonicalCatalogAuthorityService(ROOT)
    return combat, table


def choose(table, proficiency, project_id=PID):
    rows = table.learning_preview(project_id, SPHERE, {"proficiency": proficiency})["learning_choices"]
    selected = {"proficiency": proficiency, "free": rows[1]["options"][0]["id"]}
    rows = table.learning_preview(project_id, SPHERE, selected)["learning_choices"]
    if len(rows) == 3:
        selected["bonus"] = next(o["id"] for o in rows[2]["options"] if o["id"] != selected["free"])
    return selected


def scene_arena(combat, map_id, props):
    """Persist synthetic unattended props as map objects before match/journey creation."""
    combat.tabletop_maps.save({
        "map_id": map_id, "display_name": map_id, "width_squares": 12, "height_squares": 12,
        "starts": {"team1": [[3, 6]], "team2": [[4, 6]]},
        "objects": [{"id": i + 1, "kind": "crate", "x": x, "y": y, "name": "puppet-sized prop",
                     "unattended": True, "hp": 1, "ac": 10} for i, (x, y) in enumerate(props)],
    })
    return "battlefield:map." + map_id


def _raise_at(table, combat, mid, aid, at):
    turn(table, mid, aid)
    engine = combat._load_session(mid).engine
    candidate = next(c for c in engine.legal_candidates() if c.actor_id == aid
                     and c.display_name.startswith("Raise the Vessel") and c.destination
                     and (at is None or (c.destination.x, c.destination.y) == at))
    view = table.state(mid)
    menu = view["menu"]
    return resolve(lambda answers: table.act(mid, candidate.candidate_id, menu["decision_id"],
        menu["state_version"], view["last_sequence"], answers), {"choice:needle.vessel_raise_move": []})

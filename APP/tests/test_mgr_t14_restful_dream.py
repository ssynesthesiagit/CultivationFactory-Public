"""Restful Dream acquisition/routing evidence, not a claim of ritual delivery.

No synthetic action, condition, rest receipt or effect metadata is supplied.
The native procedure-to-rest executor remains missing; see the packet report.
"""
from hashlib import sha256
import json
from zipfile import ZipFile

from canonical_catalog.service import CanonicalCatalogAuthorityService
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.worker2_support import reload, settle


SOURCE = "DREAMS_BASE_RESTFUL_DREAM"
SPHERE = "tianxia.sphere.dreams"
PROJECT = "00000000-0000-4000-8000-000000000001"
ALLY_PROJECT = "00000000-0000-4000-8000-000000000002"
FOE_PROJECT = "00000000-0000-4000-8000-000000000003"
OWNER, ALLY, FOE = ["actor:factory." + pid for pid in (PROJECT, ALLY_PROJECT, FOE_PROJECT)]


def test_restful_dream_source_provenance():
    texts = json.loads((ROOT / "authority/typed_mechanics/rules_text.json").read_bytes())
    text = texts[SOURCE]
    assert sha256(text.encode()).hexdigest() == "8c95ba8002ea6c4de0c798921319c70a726cfecf015f22d643d8aff228bdd93d"
    assert "When you learn the Dreams sphere, you learn Restful Dream automatically." in text
    authority = json.loads((ROOT / "authority/Tianxia_Typed_Mechanics_Authority_R1.json").read_bytes())
    row = authority["mechanics"][SOURCE]
    assert row["kind"] == "base_ability" and row["sphere_id"] == SPHERE
    assert row["activation"]["economy"] == "ritual"


def test_native_acquisition_is_not_applied_rest_benefits_after_cold_reload(tmp_path):
    # Public character endpoints require real project IDs. Install ordinary
    # source-backed portable sheets, with no hand-written ability grants.
    for pid in (PROJECT, ALLY_PROJECT, FOE_PROJECT):
        folder = tmp_path / "portable_characters" / pid
        folder.mkdir(parents=True)
        with ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(sheet([])))
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    table.canonical_catalog = CanonicalCatalogAuthorityService(ROOT)
    # The installed character starts without Dreams. Use the public table grant
    # path, rather than the test sheet helper's synthetic list of base IDs.
    # This fixture has no Path record, so the ordinary GM grant is explicit.
    table.add_advancement(PROJECT, "sphere", SPHERE, gm=True)
    acquired = combat._factory_owner_sheet(PROJECT)
    block = acquired["spheres_and_talents"]
    assert block["automatic_sphere_component_record_ids"].count(SOURCE) == 1
    assert SOURCE not in block["learned_talent_record_ids"]
    bundle = compile_character(acquired, actor_id=OWNER)
    skipped = bundle["diagnostics"]["skipped"]
    assert "Restful Dream" in skipped["outside"]
    assert "Restful Dream" not in skipped["build"]
    assert not any(row.get("parameters", {}).get("typed", {}).get("source") == SOURCE
                   for row in bundle["action_catalog"])

    ids = [OWNER, ALLY, FOE]
    bundles = [bundle, *[compile_character(combat._factory_owner_sheet(pid), actor_id=aid)
                         for pid, aid in ((ALLY_PROJECT, ALLY), (FOE_PROJECT, FOE))]]
    arena = combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"]
    mid = combat._finish_factory_match(
        bundles, ids, {OWNER: "team:factory", ALLY: "team:factory", FOE: "team:opponents"},
        {OWNER: {"x": 3, "y": 6}, ALLY: {"x": 4, "y": 6}, FOE: {"x": 6, "y": 6}},
        arena, [OWNER, ALLY], [FOE], control_modes={aid: "MANUAL" for aid in ids},
        match_seed="RESTFUL-DREAM-BOUNDARY", display_name="Restful Dream acquisition boundary",
        maximum_rounds=15)["match_id"]

    # A real accepted table transaction and a new service preserve acquisition.
    # They must not invent a completed ritual/rest, spend CP or award temp HP.
    before = combat._load_session(mid).engine.state.actors[OWNER]
    resources, hp = dict(before.resources), before.temporary_hp
    settle(table, mid, table.state(mid)["menu"]["end_turn"])
    cold = CombatService(ROOT, tmp_path)
    cold_table = TabletopService(cold, tmp_path)
    cold_table.canonical_catalog = CanonicalCatalogAuthorityService(ROOT)
    saved = cold._factory_owner_sheet(PROJECT)
    assert saved["spheres_and_talents"]["automatic_sphere_component_record_ids"].count(SOURCE) == 1
    assert SOURCE not in cold._factory_owner_sheet(ALLY_PROJECT).get("spheres_and_talents", {}).get("automatic_sphere_component_record_ids", [])
    features = cold_table.sheet(PROJECT)["features"]
    assert "Restful Dream" in features["outside_fights"]
    assert "Restful Dream" not in features["build_features"]
    assert SOURCE not in features["automated_passives"]
    assert SOURCE not in features["automated_reactions"]
    actor = reload(tmp_path, mid).state.actors[OWNER]
    assert actor.resources == resources and actor.temporary_hp == hp

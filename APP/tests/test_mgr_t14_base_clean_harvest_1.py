"""Clean Harvest boundary evidence, not a claim that harvesting is automated.

The packet remains open: no native owner path records a Resource Site, Harvest
DC, remaining material, supported quality, harvest hazards or private sign facts.
These checks preserve source provenance and exercise actual table acquisition,
commit and cold reload without manufacturing any of those facts.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import zipfile

import pytest

from canonical_catalog.service import CanonicalCatalogAuthorityService
from combat.factory_compiler import TYPED_AUTHORITY, compile_character
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.tabletop_service import TabletopService
from tests.h1_support import sheet

ROOT = Path(__file__).resolve().parents[1]
MID = "HARVESTING_GATHERING_BASE_CLEAN_HARVEST"
SPHERE = "tianxia.sphere.harvesting_gathering"
PIN = "cbd527ee2642e1de236ec5d260c452f547e8229484ce5cb812a86533c473ca05"
OWNER = "c1ea0000-0000-4000-8000-000000000001"
OTHER = "c1ea0000-0000-4000-8000-000000000002"


def test_full_decoded_record_matches_owner_pin():
    text = json.loads((ROOT / "authority/typed_mechanics/rules_text.json").read_text())[MID]
    assert hashlib.sha256(text.encode()).hexdigest() == PIN
    for clause in (
        "10 minutes for ordinary work; Action only if a talent says so",
        "appropriate tools or a justified improvised method",
        "against the source’s Harvest DC", "one usable Lot or specific ingredient",
        "Success by 5 or More", "additional Lot if the source has enough material",
        "create a Pure Lot", "avoid harming the root, nest, vein, corpse, or future site",
        "one additional fact from Read the Sign", "avoid one minor hazard",
        "Success by 10 or More", "Perfect Lot if the source can support it",
        "choose two benefits", "Failure by 5 or Less", "Bruised Lot",
        "immediate sealing", "Failure by More Than 5", "Natural 1",
        "a hazard triggers if one exists",
    ):
        assert clause in text


def test_source_metadata_has_its_own_provenance_scope():
    row = json.loads(TYPED_AUTHORITY.read_text())["mechanics"][MID]
    assert row["kind"] == "base_ability"
    assert row["sphere_id"] == SPHERE
    assert row["source"]["line"] == 38468
    assert row["source"]["file_sha256"] == (
        "67f67275889467d43605debaa0c05dc5ddde9ba079222819aabea27c66167775"
    )
    # This is a recorded source digest, not the full decoded rules_text pin.
    assert row["source"]["text_sha256"] == (
        "c390250e8e64b1798b35f3d33c86e0bb58a87e1297de3686cef47e40de29b8e1"
    )


@pytest.mark.parametrize("learn", [False, True], ids=["wrong-owner", "learn-at-table"])
def test_unknown_site_cannot_become_a_free_harvest_and_ownership_reloads(tmp_path, monkeypatch, learn):
    # Never contact a live model. No test-only action, fact or harvest receipt.
    monkeypatch.setenv("CF_EMBED_MENU", "0")
    for project in (OWNER, OTHER):
        folder = tmp_path / "portable_characters" / project
        folder.mkdir(parents=True)
        document = sheet([])
        document["identity"]["path_ids"] = ["tianxia.path.qi_cultivation"]
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(document))
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    if learn:
        table.canonical_catalog = CanonicalCatalogAuthorityService(ROOT)
        table.add_advancement(OWNER, "sphere", SPHERE)
    # A fresh service must read the actual saved advancement, not a patched bundle.
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    doc = combat._factory_owner_sheet(OWNER)
    owned = doc.get("spheres_and_talents", {}).get("automatic_sphere_component_record_ids", [])
    assert (MID in owned) is learn
    other_doc = combat._factory_owner_sheet(OTHER)
    assert MID not in other_doc.get("spheres_and_talents", {}).get("automatic_sphere_component_record_ids", [])
    bundle = compile_character(doc, actor_id=FACTORY_ACTOR_PREFIX + OWNER)
    print("Clean Harvest compile diagnostics:", bundle["diagnostics"])
    view = combat.create_factory_match(
        project_ids=[OWNER], opponent_actor_ids=[FACTORY_ACTOR_PREFIX + OTHER],
        control_modes={FACTORY_ACTOR_PREFIX + p: "MANUAL" for p in (OWNER, OTHER)},
        match_seed="CLEAN-HARVEST-BOUNDARY", maximum_rounds=3,
    )
    mid = view["match_id"]
    state = table.state(mid)
    engine = combat._load_session(mid).engine
    # With no source or enabling talent, neither ownership nor a natural-looking
    # arena grants an in-combat harvest. Never infer material from map scenery.
    assert not [c for c in engine.legal_candidates() if "Clean Harvest" in c.display_name]
    menu = state["menu"]
    result = table.act(mid, menu["end_turn"], menu["decision_id"], menu["state_version"], state["last_sequence"])
    assert result["status"] == "COMMITTED"
    cold = CombatService(ROOT, tmp_path)._load_session(mid)
    assert cold.verify()["status"] == "PASS"
    assert cold.mechanical.replay()["status"] == "PASS"
    assert not [c for c in cold.engine.legal_candidates() if "Clean Harvest" in c.display_name]

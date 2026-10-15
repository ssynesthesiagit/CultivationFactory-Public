"""Harvest Lots provenance and native boundary evidence; delivery remains open.

Learning the sphere grants the definition, not raw material. These tests do not
manufacture a resource site, material, sealing receipt, or inventory producer.
They deliberately make no claim about delivering a Lot from a real source.
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
MID = "HARVESTING_GATHERING_BASE_HARVEST_LOTS_AND_LOT_QUALITY"
SPHERE = "tianxia.sphere.harvesting_gathering"
PIN = "19264d35d63e1e7217f2b5d78202bb5f96f1a738a96681d886aa396eb66a6771"
OWNER = "a71e0000-0000-4000-8000-000000000001"
OTHER = "a71e0000-0000-4000-8000-000000000002"


def test_whole_definition_matches_decoded_source_pin():
    text = json.loads((ROOT / "authority/typed_mechanics/rules_text.json").read_text())[MID]
    assert hashlib.sha256(text.encode()).hexdigest() == PIN
    for clause in (
        "sealed, usable portion of raw material",
        "a bundle of medicinal herbs", "a spirit fruit", "bark curls from a sacred tree",
        "sealed dew from moon grass", "a fungus cap harvested at the correct hour",
        "powdered mineral scraped from a vein", "venom in a waxed ampoule",
        "beast gall, horn, claw, hide, bone, scale, silk, shell, or blood",
        "a low-grade beast core", "a jar of spirit soil",
        "resin, incense wood, or aromatic root", "petals, seeds, pollen, or bitter leaves",
        "scene, downtime, market, sect field, wilderness route, or strategic project",
        "This sphere does not create Lots from nothing",
    ):
        assert clause in text


def test_source_identity_and_scope_are_not_an_automation_receipt():
    row = json.loads(TYPED_AUTHORITY.read_text())["mechanics"][MID]
    assert row["kind"] == "base_ability"
    assert row["sphere_id"] == SPHERE
    assert row["source"]["line"] == 38495
    assert row["source"]["file_sha256"] == (
        "67f67275889467d43605debaa0c05dc5ddde9ba079222819aabea27c66167775"
    )
    # Here both digest scopes match; do not assume this for sibling records.
    assert row["source"]["text_sha256"] == PIN


@pytest.mark.parametrize("learn", [False, True], ids=["wrong-owner", "native-acquisition"])
def test_learning_and_table_reload_do_not_fabricate_a_lot_source(tmp_path, monkeypatch, learn):
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
    # Read the real saved advancement through a new service, not injected IDs.
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    document = combat._factory_owner_sheet(OWNER)
    owned = document.get("spheres_and_talents", {}).get("automatic_sphere_component_record_ids", [])
    assert (MID in owned) is learn
    other = combat._factory_owner_sheet(OTHER)
    assert MID not in other.get("spheres_and_talents", {}).get("automatic_sphere_component_record_ids", [])
    bundle = compile_character(document, actor_id=FACTORY_ACTOR_PREFIX + OWNER)
    # The definition prints no action. An action that mints a Lot on acquisition
    # would contradict the real-source restriction, rather than automate it.
    assert not [row for row in bundle.get("action_catalog", [])
                if row.get("source_definition_id") == MID]
    view = combat.create_factory_match(
        project_ids=[OWNER], opponent_actor_ids=[FACTORY_ACTOR_PREFIX + OTHER],
        control_modes={FACTORY_ACTOR_PREFIX + p: "MANUAL" for p in (OWNER, OTHER)},
        match_seed="HARVEST-LOT-NO-SOURCE", maximum_rounds=3,
    )
    match_id = view["match_id"]
    state = table.state(match_id)
    engine = combat._load_session(match_id).engine
    assert not [c for c in engine.legal_candidates() if "Harvest Lot" in c.display_name]
    menu = state["menu"]
    result = table.act(match_id, menu["end_turn"], menu["decision_id"],
                       menu["state_version"], state["last_sequence"])
    assert result["status"] == "COMMITTED"
    cold = CombatService(ROOT, tmp_path)._load_session(match_id)
    assert cold.verify()["status"] == "PASS"
    assert cold.mechanical.replay()["status"] == "PASS"
    assert not [c for c in cold.engine.legal_candidates() if "Harvest Lot" in c.display_name]

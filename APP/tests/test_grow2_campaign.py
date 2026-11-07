"""Campaign gains use one durable record, never the sealed package.

Synthetic installed characters and shipped public authority only. Native Art
sources require BundledContent/Tianxia_Factory_HF05ZVK_R1H_Phase2I_HF2.zip
(the existing canonical catalog dependency, provisioned by the public export).
The optional sealed Art authoring pack is replaced by synthetic authority below.
No model servers, private fixtures, repository history, or browser process.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import zipfile

import pytest

from app.core import FoundryError
from canonical_catalog.service import CanonicalCatalogAuthorityService
from combat import table_advance as ta, table_growth as growth
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop import TabletopError
from combat.tabletop_service import TabletopService

ROOT = Path(__file__).resolve().parents[1]
PID = "0badc0de-0000-4000-8000-000000000021"
OTHER = "0badc0de-0000-4000-8000-000000000022"
INSIGHT = "insight.expanded-dantian"
ART = {"name": "Shelter of the Azure Mountain",
       "source_record_id": "tianxia.path.qi_cultivation.feature.qi_armor",
       "aspect_id": "tianxia.dao_aspect.fortification",
       "factor_ids": ["temporary_hp_fortification"], "burdens": []}


@pytest.fixture(autouse=True)
def synthetic_art_authority(monkeypatch):
    """The large sealed authoring pack is not in the public CI export.
    Supply synthetic numeric authority to the real pure constructor, not a
    fake constructor or a private fixture. Native action proofs still use
    the public shipped chapters and their real pinned source adapters.
    """
    authority = {
        "schema_version": "TianxiaFoundry.ImmortalArtAuthority.v1", "seal_sha256": "a" * 64,
        "aspects": [{
            "aspect_id": "tianxia.dao_aspect.fortification", "display_name": "Fortification",
            "semantic_tags": ["guard", "protect"], "mandate_cost": 2, "cp_modifier": 2,
            "source_text": "Synthetic Fortification rules: one minute of temporary protection.\n" * 130,
            "source": {"source_id": "source.synthetic.fortification", "path": "synthetic/fortification.md",
                       "source_hash": "b" * 64, "anchor": "document:full-text"},
            "factors": [{"factor_id": "temporary_hp_fortification", "display_name": "Temporary HP Fortification",
                         "mandate_cost": 2, "cp_cost": 2, "source_line": 1,
                         "mechanical_chassis": "Gain temporary Hit Points for 1 minute; ends when depleted."}],
            "burdens": [],
        }],
        "shared_rules": {
            "realm_thresholds": [{"realm": "Nascent Soul", "mandate_threshold": 3},
                                 {"realm": "Immortal", "mandate_threshold": 6}],
            "factor_escalation": {"0": 0, "1": 1, "2": 3, "3": 7, "4": 15, "5": 31},
            "source_package_modifier": {"1": 0, "2": 1, "3": 2, "4_plus": 3},
            "research_and_materials": {"research_days_per_complexity": 5, "material_gp_per_complexity_squared": 250},
        },
    }
    monkeypatch.setattr(growth, "art_authority", lambda: authority)
    return authority


def sheet(cl=15, path="qi_cultivation"):
    key, resource = {"qi_cultivation": ("INT", "Qi"), "body_refining": ("CON", "Stamina"),
                     "spirit_awakening": ("WIS", "Resonance")}[path]
    pb = 2 + (cl - 1) // 4
    return {
        "identity": {"display_name": "Campaign Student", "cultivation_level": cl, "proficiency_bonus": pb,
                     "path_ids": ["tianxia.path." + path], "path_id": "tianxia.path." + path,
                     "key_ability": key},
        "ability_scores_and_statistics": {
            "abilities": [{"ability": a, "score": 18 if a == key else 12, "modifier": 4 if a == key else 1}
                          for a in ta.ABILITIES],
            "armor_class": {"base_value": 15}, "hit_points": {"maximum": 100},
            "speed": {"walking_ft": 30}, "technique_save_dc": 8 + pb + 4, "technique_attack_bonus": pb + 4,
            "primary_resource": {"name": resource, "maximum": 30, "build_state_current": 30}},
        "spheres_and_talents": {}, "selected_record_sections": {},
    }


def install(root, pid=PID, source=None):
    path = root / "portable_characters" / pid / "current.zip"
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(source or sheet()))
    return path


def service(root):
    result = TabletopService(CombatService(ROOT, root), root)
    result.canonical_catalog = CanonicalCatalogAuthorityService(ROOT)
    return result


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def completion(preview):
    return {"die": 20, "research_hours": preview["required_research_hours"],
            "materials_gp": preview["required_materials_gp"]}


def test_insight_round_trip_cold_service_sheet_combat_and_seal(tmp_path):
    package, other = install(tmp_path), install(tmp_path, OTHER)
    hashes = digest(package), digest(other)
    before = sheet()
    original_scores = ta.current_scores(before)
    s = service(tmp_path)
    result = s.add_insight(PID, INSIGHT, note="Master Lin's winter lessons")
    assert result["added"]["insights"][0]["note"] == "Master Lin's winter lessons"
    saved = s.buttons.get(PID)["advancement"]
    assert saved["insights"] and not saved["abilities"]
    cold = service(tmp_path)
    overlaid = cold.combat._factory_owner_sheet(PID)
    assert INSIGHT in overlaid["spheres_and_talents"]["cultivation_insight_record_ids"]
    assert ta.current_scores(overlaid) == original_scores  # non-level source, never the printed level-selection +1
    assert not overlaid["spheres_and_talents"]["cultivation_insight_occurrences"][0]["ability_change_applied"]
    assert cold.combat._factory_owner_sheet(OTHER) == before
    bundle = compile_character(overlaid, actor_id="actor:campaign")
    assert INSIGHT in [row["id"] for row in bundle["diagnostics"]["insights"]]
    library = cold.sheet(PID)["library"]
    assert any(row["id"] == INSIGHT for group in library["groups"] for row in group.get("entries", []))
    removed = cold.remove_advancement(PID, "insight", "0")
    assert not removed["added"]["insights"]
    assert service(tmp_path).combat._factory_owner_sheet(PID) == before
    assert (digest(package), digest(other)) == hashes


def test_art_round_trip_cold_service_sheet_combat_and_seal(tmp_path):
    package, other = install(tmp_path), install(tmp_path, OTHER)
    hashes = digest(package), digest(other)
    s = service(tmp_path)
    preview = s.immortal_art(PID, ART)
    assert not s.buttons.get(PID).get("advancement")  # preview is not a mutation
    added = s.immortal_art(PID, ART, note="Refined during the mountain retreat",
                          proof=completion(preview), save=True)
    assert added["advancement"]["added"]["immortal_arts"][0]["name"] == ART["name"]
    assert not added["advancement"]["added"]["abilities"]
    cold = service(tmp_path)
    persisted = cold.buttons.get(PID)["advancement"]["immortal_arts"][0]
    assert persisted["refinement"]["total"] >= persisted["refinement"]["dc"]
    # Canonical construction retained unchanged; only the overlaid label is custom.
    growth.compile_immortal_art(growth.art_authority(), persisted["art"])
    applied = cold.combat._factory_owner_sheet(PID)
    assert applied["immortal_arts"][0]["name"] == ART["name"]
    bundle = compile_character(applied, actor_id="actor:campaign")
    assert any(row.get("immortal_from") == ART["source_record_id"] for row in bundle.get("typed_reactions", []))
    library = cold.sheet(PID)["library"]
    assert any(row["name"] == ART["name"] for group in library["groups"] if group["key"] == "arts" for row in group["entries"])
    assert cold.combat._factory_owner_sheet(OTHER) == sheet()
    cold.remove_advancement(PID, "immortal_art", persisted["art"]["art_id"])
    assert service(tmp_path).combat._factory_owner_sheet(PID) == sheet()
    assert (digest(package), digest(other)) == hashes


@pytest.mark.parametrize("path", ["qi_cultivation", "body_refining", "spirit_awakening"])
def test_creation_native_adapters_work_with_shipped_catalog_bundle(path):
    original = sheet(path=path)
    sources = growth.art_sources(original)
    assert sources and all(row["owning_path_id"] == "tianxia.path." + path for row in sources)
    assert original == sheet(path=path)


@pytest.mark.parametrize("change,reason", [
    ({"source_record_id": "invented.action"}, "known source"),
    ({"factor_ids": ["invented_factor"]}, "Factor"),
    ({"burdens": ["invented_burden"]}, "Burden"),
])
def test_invalid_art_decisions_refused_without_saving(tmp_path, change, reason):
    install(tmp_path)
    s = service(tmp_path)
    with pytest.raises((FoundryError, TabletopError), match=reason):
        s.immortal_art(PID, {**ART, **change}, note="From play", proof={}, save=True)
    assert not s.buttons.get(PID).get("advancement")


@pytest.mark.parametrize("proof,reason", [
    ({}, "d20"), ({"die": True}, "d20"), ({"die": 1}, "not refined"),
    ({"die": 20, "research_hours": 0}, "research"),
    ({"die": 20, "research_hours": 99999, "materials_gp": 0}, "materials"),
])
def test_incomplete_refinement_refused(tmp_path, proof, reason):
    install(tmp_path)
    s = service(tmp_path)
    with pytest.raises(FoundryError, match=reason):
        s.immortal_art(PID, ART, note="From play", proof=proof, save=True)
    assert not s.buttons.get(PID).get("advancement")


def test_art_level_and_realm_count_gate_and_remove_frees_slot(tmp_path):
    install(tmp_path, source=sheet(cl=14))
    s = service(tmp_path)
    with pytest.raises(FoundryError, match="15"):
        s.immortal_art(PID, ART)
    install(tmp_path)
    for n in range(3):
        design = {**ART, "name": f"Mountain Shelter {n}"}
        pv = s.immortal_art(PID, design)
        s.immortal_art(PID, design, note="From play", proof=completion(pv), save=True)
    with pytest.raises(FoundryError, match="unused Art slot"):
        s.immortal_art(PID, {**ART, "name": "Fourth"})
    first = s.buttons.get(PID)["advancement"]["immortal_arts"][0]["art"]["art_id"]
    s.remove_advancement(PID, "immortal_art", first)
    assert s.immortal_art(PID, {**ART, "name": "Replacement"})["art"]


def test_insight_minimum_prerequisites_uniqueness_and_repeat_limits(tmp_path):
    install(tmp_path, source=sheet(cl=1))
    s = service(tmp_path)
    with pytest.raises(TabletopError, match="level"):
        s.add_insight(PID, INSIGHT, note="From play", gm=True)
    with pytest.raises(TabletopError, match="Needs"):
        s.add_insight(PID, "insight.alloy-sense-disciple", note="From play", gm=True)
    with pytest.raises(TabletopError, match="catalog"):
        s.add_insight(PID, "insight.not-real", note="From play")
    install(tmp_path)
    s.add_insight(PID, INSIGHT, note="Mentor")
    s.add_insight(PID, INSIGHT, note="Tribulation")
    with pytest.raises(TabletopError, match="only 2"):
        s.add_insight(PID, INSIGHT, note="Third", gm=True)


@pytest.mark.parametrize("single", [False, True])
def test_existing_sealed_art_history_does_not_disable_source_menu(single):
    base = sheet()
    art = growth.construct_art(base, ART, PID)
    base["immortal_arts"] = [{**art, "record_id": art["art_id"], "source_packet_ids": ["sealed.packet"],
                              "refinement": {"attempts": [{"check_die_result": 20}]}}]
    if single:
        base["immortal_arts"] = base["immortal_arts"][0]
    assert growth.art_menu(base)["known"] == 1
    assert any(row["id"] == ART["source_record_id"] for row in growth.art_menu(base)["sources"])
    growth.arts_of(base)[0]["activation_cp"] += 1
    with pytest.raises(FoundryError, match="no longer matches"):
        growth.art_sources(base)


def test_secondary_path_uses_real_sheet_attainment_and_its_own_key_ability():
    base = sheet(path="body_refining")
    base["identity"]["path_ids"].append("tianxia.path.qi_cultivation")
    base["identity"]["paths"] = [
        {"path_id": "tianxia.path.body_refining", "effective_cl": 15, "key_ability": "CON"},
        {"path_id": "tianxia.path.qi_cultivation", "effective_cl": 15, "key_ability": "CHA"}]
    art = growth.construct_art(base, ART, PID)
    assert art["key_ability"] == "CHA"
    assert art["construction"]["request"]["owning_path_cl"] == 15
    base["identity"]["paths"][1]["effective_cl"] = 8
    assert not any(row["id"] == ART["source_record_id"] for row in growth.art_menu(base)["sources"])


def test_insight_choice_reaches_existing_resource_plugin_and_refuses_unowned_pool(tmp_path):
    install(tmp_path)
    s = service(tmp_path)
    key = "insight.legacy-enhanced-meridians"
    s.add_insight(PID, key, note="Training the meridians")
    applied = service(tmp_path).combat._factory_owner_sheet(PID)
    occurrence = applied["spheres_and_talents"]["cultivation_insight_occurrences"][0]
    assert occurrence["parameters"] == {"resource_pool": "qi"}
    bundle = compile_character(applied, actor_id="actor:campaign")
    pool = next(row for row in bundle["actor_template"]["resources"] if row["resource_id"] == "resource:core.qi")
    assert pool["maximum"] == 40  # base 30 + 2 × PB 5, by the existing plug-in
    with pytest.raises(TabletopError, match="active Path resource"):
        s.add_insight(PID, key, note="Another lesson", choice="Stamina", gm=True)
    multi = sheet()
    multi["ability_scores_and_statistics"]["primary_resource"]["definitions"] = [{"name": "Stamina", "max": 20}]
    record = s.canonical_catalog.get_insight(key)
    assert growth.insight_status(record, multi)["needs_choice"]
    assert growth.insight_status(record, multi, choice="Stamina")["parameters"] == {"resource_pool": "stamina"}


def test_nonrepeatable_and_story_prerequisites_fail_closed():
    record = {"canonical_insight_id": "insight.synthetic-lesson", "selectable": True,
              "raw_source_record": {"minimum_cl": 1, "repeatable": "No"}}
    original = sheet()
    assert growth.insight_status(record, original)["legal"]
    original["spheres_and_talents"]["cultivation_insight_record_ids"] = [record["canonical_insight_id"]]
    assert not growth.insight_status(record, original)["legal"]
    record["prerequisites"] = [{"kind": "narrative_condition", "value": "a willing bonded companion"}]
    status = growth.insight_status(record, sheet())
    assert not status["legal"] and status["gm"]
    assert "GM confirmation" in status["reasons"][0]


def test_missing_optional_art_pack_does_not_break_other_growth(tmp_path, monkeypatch):
    install(tmp_path)
    def missing():
        raise FoundryError("IMMORTAL_ART_AUTHORITY_INVALID", "The sealed Immortal Art authority is missing.")
    monkeypatch.setattr(growth, "art_authority", missing)
    s = service(tmp_path)
    options = s.add_insight(PID, INSIGHT, note="From play")
    assert options["added"]["insights"]
    assert "missing" in options["immortal_art"]["unavailable"]
    assert options["immortal_art"]["sources"] == []


def test_overlay_key_changes_and_preserves_every_growth_channel():
    doc = ta.empty()
    doc["insights"] = [{"id": INSIGHT, "name": "Expanded Dantian", "text": "Benefit", "note": "From play", "cl": 15}]
    assert ta.overlay_key(doc) != ta.overlay_key(ta.empty())
    restored = ta.normalized(json.loads(json.dumps(doc)))
    assert restored == doc
    projected = ta.apply(sheet(), restored)
    assert INSIGHT in projected["spheres_and_talents"]["cultivation_insight_record_ids"]
    assert sheet()["selected_record_sections"] == {}


def test_real_http_growth_and_factory_sheet(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app.api import create_app
    from app.core import Settings

    package = install(tmp_path)
    original_hash = digest(package)
    app = create_app(Settings.from_env(ROOT, tmp_path))
    monkeypatch.setattr(app.state.character_sheets, "sheet", lambda _: {
        "owner_character_sheet": sheet(), "display_owner_character_sheet": sheet(),
        "sections": {"abilities_statistics": {"data": sheet()["ability_scores_and_statistics"]}}})
    monkeypatch.setattr(app.state.character_creation, "recovery", lambda _: {})
    prefix = f"/api/tabletop/characters/{PID}/advancement"
    with TestClient(app) as client:
        headers = {"X-Foundry-Token": client.get("/api/session").json()["token"]}
        result = client.post(prefix + "/insight", headers=headers, json={"record_id": INSIGHT, "note": "Quest"})
        assert result.status_code == 200, result.text
        preview = client.post(prefix + "/immortal-art", headers=headers, json={"design": ART})
        assert preview.status_code == 200, preview.text
        result = client.post(prefix + "/immortal-art", headers=headers, json={
            "design": ART, "note": "Retreat", "save": True, "proof": completion(preview.json())})
        assert result.status_code == 200, result.text
        owner = client.get(f"/api/characters/{PID}/sheet")
        assert owner.status_code == 200, owner.text
        for key in ("owner_character_sheet", "display_owner_character_sheet"):
            assert INSIGHT in owner.json()[key]["spheres_and_talents"]["cultivation_insight_record_ids"]
            assert owner.json()[key]["immortal_arts"][0]["name"] == ART["name"]
        assert client.post(prefix + "/immortal-art", headers=headers, json={
            "design": {**ART, "known_sources": []}}).status_code == 422
        assert client.post(prefix + "/insight", headers=headers, json={"record_id": INSIGHT, "note": ""}).status_code == 422
    assert digest(package) == original_hash

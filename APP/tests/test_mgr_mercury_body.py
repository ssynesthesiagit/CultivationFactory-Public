"""Native admission prerequisite for the Living Mercury Body extraction.

The existing, source-contracted Palm record exercises the generic service seam.
Living Mercury Body deliberately remains unavailable through this seam until
its variant/session contract and complete combat consumers are implemented.
Fixtures are synthetic installed owner sheets, never precompiled ownership.
"""
import hashlib
import json
from pathlib import Path
import zipfile

import pytest

from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.source_acquisition import SourceAcquisitionStore
from combat.tabletop_service import TabletopService

ROOT = Path(__file__).resolve().parents[1]
PROJECT = "mercury-admission-owner"
OTHER = "mercury-admission-other"
A, B = (FACTORY_ACTOR_PREFIX + pid for pid in (PROJECT, OTHER))
PALM = "tianxia.tradition.spirit.last_inch_palm.feature.palm_across_emptiness"
LIVING = "tianxia.subpath.qi.living_quicksilver_immortal_embryo.feature.living_mercury_body"
ACCESS = {"kind": "restricted_spirit_tradition", "basis": "contact_boundary_teacher",
          "record_id": "owner:synthetic-teacher-admission"}


def document(*, cl=10):
    return {
        "identity": {"name": "Student", "cultivation_level": cl,
                     "proficiency_bonus": 4, "path": "Spirit Awakening", "key_ability": "WIS"},
        "ability_scores_and_statistics": {
            "abilities": [{"ability": a, "score": 14, "modifier": 2}
                          for a in ("STR", "DEX", "CON", "INT", "WIS", "CHA")],
            "primary_resource": {"name": "Resonance", "maximum": 20},
            "armor_class": {"base_value": 14}, "hit_points": {"maximum": 60},
            "speed": {"walking_ft": 30}, "technique_save_dc": 14, "technique_attack_bonus": 6,
        },
    }


def installed(tmp_path, monkeypatch, *, cl=10):
    for pid in (PROJECT, OTHER):
        folder = tmp_path / "portable_characters" / pid
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(document(cl=cl)))
    arena = {"stable_id": "battlefield:mercury-admission", "display_name": "Practice court",
             "width_squares": 10, "height_squares": 6, "square_size_ft": 5,
             "starting_positions": {}, "terrain_regions": []}
    monkeypatch.setattr(CombatService, "factory_arenas", lambda self, **kw: {"court": arena})
    return CombatService(ROOT, tmp_path)


def admit(service, *, feature=PALM, occurrence="owner:training:10", access=ACCESS):
    return service.acquire_source_feature(PROJECT, feature_id=feature,
                                          occurrence_id=occurrence, access_record=access)


def journey(service):
    return service.create_journey(project_ids=[PROJECT, OTHER], arena_id="court",
                                  positions={A: {"x": 1, "y": 1}, B: {"x": 5, "y": 1}},
                                  base_paces={A: 3000, B: 3000},
                                  control_modes={A: "MANUAL", B: "MANUAL"})


def end_turn(service, mid):
    table = TabletopService(service, service.userdata_root)
    menu = table.state(mid)["menu"]
    result = table.act(mid, menu["end_turn"], menu["decision_id"], menu["state_version"], 0, [])
    assert result["status"] == "COMMITTED", result


def test_native_admission_reaches_journey_table_commit_and_cold_replay(tmp_path, monkeypatch):
    service = installed(tmp_path, monkeypatch)
    package = tmp_path / "portable_characters" / PROJECT / "current.zip"
    sealed = package.read_bytes()
    receipt = admit(service)
    assert receipt["feature_id"] == PALM and receipt["actor_id"] == A
    assert receipt["access_record"] == ACCESS
    assert package.read_bytes() == sealed
    cold = CombatService(ROOT, tmp_path)
    state = journey(cold)
    jid = state["journey_id"]
    assert state["actors"][A]["bundle"]["source_acquisitions"] == [receipt]
    assert not state["actors"][B]["bundle"].get("source_acquisitions")
    # This is the ordinary service's acquisition projection, rather than a
    # manually loaded admission passed directly to compile_character.
    assert cold._factory_owner_sheet(PROJECT)["combat_acquisitions"] == [receipt]
    result = cold.journey_start_combat(jid, state["revision"], {A: "team:a", B: "team:b"})
    mid = result["match_id"]
    before = CombatService(ROOT, tmp_path)._load_session(mid)
    bundle = next(b for b in before.engine.typed_bundle_documents if b["actor_id"] == A)
    assert bundle["source_acquisitions"] == [receipt]
    end_turn(CombatService(ROOT, tmp_path), mid)
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.mechanical.replay()["status"] == "PASS"
    assert loaded.engine.state.state_version > before.engine.state.state_version
    saved = next(b for b in loaded.engine.typed_bundle_documents if b["actor_id"] == A)
    assert saved["source_acquisitions"] == [receipt]
    assert package.read_bytes() == sealed


def test_duplicate_admission_cannot_refill_or_rewrite_active_state(tmp_path, monkeypatch):
    service = installed(tmp_path, monkeypatch)
    admit(service)
    state = journey(service)
    jid = state["journey_id"]
    service.journey_act(jid, 0, A, "move", {"path": [{"x": 2, "y": 1}]})
    before = service.journey_state(jid)
    store = SourceAcquisitionStore(tmp_path)
    receipt_path = store.root / (hashlib.sha256(A.encode()).hexdigest() + ".json")
    raw = receipt_path.read_bytes()
    for occurrence in ("owner:training:10", "owner:duplicate:10"):
        with pytest.raises(ValueError, match="already acquired"):
            admit(CombatService(ROOT, tmp_path), occurrence=occurrence)
        assert receipt_path.read_bytes() == raw
        assert CombatService(ROOT, tmp_path).journey_state(jid) == before


@pytest.mark.parametrize("access", [None, {**ACCESS, "basis": "guessed_from_name"}])
def test_missing_or_ineligible_access_never_writes_an_admission(tmp_path, monkeypatch, access):
    service = installed(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="access record|Access record"):
        admit(service, access=access)
    assert not list(SourceAcquisitionStore(tmp_path).root.glob("*.json"))
    assert "combat_acquisitions" not in CombatService(ROOT, tmp_path)._factory_owner_sheet(PROJECT)


def test_underlevel_and_uncontracted_variant_fail_before_persistence(tmp_path, monkeypatch):
    service = installed(tmp_path, monkeypatch, cl=3)
    with pytest.raises(ValueError, match="Cultivation Level 10"):
        admit(service)
    # Access prose alone must not admit the incomplete Variant implementation.
    with pytest.raises(ValueError, match="no source-backed native admission contract"):
        admit(service, feature=LIVING, access={"kind": "rare_variant", "basis": "inheritance",
                                               "record_id": "owner:inheritance"})
    assert not list(SourceAcquisitionStore(tmp_path).root.glob("*.json"))


def test_native_projection_revalidates_source_and_owner(tmp_path, monkeypatch):
    service = installed(tmp_path, monkeypatch)
    admit(service)
    store = SourceAcquisitionStore(tmp_path)
    path = store.root / (hashlib.sha256(A.encode()).hexdigest() + ".json")
    doc = json.loads(path.read_text())
    doc["records"][0]["source_sha256"] = "0" * 64
    path.write_text(json.dumps(doc))
    with pytest.raises(ValueError, match="source or admission contract changed"):
        CombatService(ROOT, tmp_path)._factory_owner_sheet(PROJECT)


def test_no_admissions_preserves_native_owner_sheet(tmp_path, monkeypatch):
    service = installed(tmp_path, monkeypatch)
    assert service._factory_owner_sheet(PROJECT) == document()
    assert not SourceAcquisitionStore(tmp_path).root.exists()

"""F18 review: pin the journey precompile stub and one shared journey-source contract.

Both regressions are synthetic and public-CI safe (no repository history, owner
data or private fixtures). The stub check registers a test-scoped hook through
the same public dispatch point the engine uses, so the code under test stays the
real ``CombatService.create_journey`` and the real file-backed journey store.
"""
import ast
from pathlib import Path

from combat import ext
from combat.gate5_service import CombatService
from tests.h1_support import ROOT, sheet

A = "actor:factory.traveller"
B = "actor:factory.companion"


def _sheets(monkeypatch):
    documents = {
        "traveller": sheet(["tianxia.path.qi_cultivation.feature.qi_sensing"], cl=6, name="Wren"),
        "companion": sheet(["tianxia.path.qi_cultivation.feature.qi_sensing"], cl=6, name="Mara"),
    }
    for document in documents.values():
        document["path_and_subpath"] = {
            **document.get("path_and_subpath", {}),
            "path_record_id": "tianxia.path.qi_cultivation",
            "path_record_ids": ["tianxia.path.qi_cultivation"],
            "paths": [{"path_id": "tianxia.path.qi_cultivation",
                       "attainment": document["identity"]["cultivation_level"]}],
        }
    monkeypatch.setattr(CombatService, "_factory_owner_sheet", lambda self, pid: documents[pid])
    arena = {"display_name": "Cremation courtyard", "stable_id": "battlefield:cremation-f18",
             "width_squares": 16, "height_squares": 16, "square_size_ft": 5,
             "starting_positions": {}, "terrain_regions": []}
    monkeypatch.setattr(CombatService, "factory_arenas", lambda self, **kwargs: {"scene": arena})


def _create(service):
    return service.create_journey(project_ids=["traveller", "companion"], arena_id="scene",
                                  positions={A: {"x": 3, "y": 3}, B: {"x": 4, "y": 3}},
                                  base_paces={A: 100, B: 100})


def test_journey_precompile_stub_exposes_documented_identity_and_clock(tmp_path, monkeypatch):
    """A provider reading journey_id, scene_id and the clock runs against the stub.

    ``create_journey`` must project the prior sheet before compiling, and it does
    that by dispatching the journey hooks against a stand-in session. The stand-in
    is not a real scene: its journey id is not assigned yet, it has no scene_id
    key (exactly like the new session ``JourneyStore.create`` builds), it reports
    zero elapsed seconds and clock, and it carries exactly the one projected
    actor. A provider that reads those values must still work, and a dict it
    returns must reach the compiled journey.
    """
    _sheets(monkeypatch)
    seen = []

    def initialize(session, actor_id):
        seen.append({"point": "initialize", "actor_id": actor_id,
                     "journey_id": session.state["journey_id"],
                     "keys": sorted(session.state),
                     "scene_id": session.state.get("scene_id"),
                     "seconds": session.state["seconds"],
                     "clock": int(session.clock()),
                     "actors": sorted(session.state["actors"])})

    def project(sheet_in, session, actor_id):
        seen.append({"point": "sheet", "actor_id": actor_id,
                     "journey_id": session.state["journey_id"],
                     "keys": sorted(session.state),
                     "scene_id": session.state.get("scene_id"),
                     "seconds": session.state["seconds"],
                     "clock": int(session.clock()),
                     "actors": sorted(session.state["actors"])})
        result = dict(sheet_in)
        result["f18_projection"] = 1
        return result

    monkeypatch.setitem(ext._HOOKS, "journey_initialize",
                        [*ext.subscribers("journey_initialize"), initialize])
    monkeypatch.setitem(ext._HOOKS, "journey_source_sheet",
                        [*ext.subscribers("journey_source_sheet"), project])

    service = CombatService(ROOT, tmp_path)
    first = _create(service)
    jid = first["journey_id"]
    service.journey_end_scene(jid, service.journey_state(jid)["revision"], "the party leaves the shrine")
    service.journey_act(jid, service.journey_state(jid)["revision"], A, "wait", {"seconds": 120})
    service.journey_act(jid, service.journey_state(jid)["revision"], A, "finish", {})

    seen.clear()
    second = _create(service)
    assert second["journey_id"] != jid

    stub = [row for row in seen if row["journey_id"] == ""]
    assert [(row["point"], row["actor_id"]) for row in stub] == [
        ("initialize", A), ("sheet", A), ("initialize", B), ("sheet", B)]
    for row in stub:
        assert row["keys"] == ["actors", "journey_id", "seconds"]
        assert row["scene_id"] is None
        assert row["seconds"] == 0 and row["clock"] == 0
        assert row["actors"] == [row["actor_id"]]
    # The real creation pass runs the same hooks on the actual session.
    real = [row for row in seen if row["journey_id"] == second["journey_id"]]
    assert sorted((row["point"], row["actor_id"]) for row in real) == sorted([
        ("initialize", A), ("initialize", B)])
    for aid in (A, B):
        assert second["actors"][aid]["source_sheet"]["f18_projection"] == 1


def test_journey_source_contracts_are_stated_once_and_no_build_skip_is_documented():
    """One authoritative contract, and the documented reason journey_acquired skips."""
    documentation = ast.get_docstring(ast.parse((Path(ROOT) / "combat/ext/__init__.py").read_text()))
    assert documentation.count("journey_source_sheet(sheet, session, actor_id)") == 1
    assert documentation.count("journey_acquisition(session, actor_id, source, payload, sheet)") == 1
    assert documentation.count("journey_acquired(session, actor_id, source, acquisition_id)") == 1
    flat = " ".join(documentation.split())
    assert ("deliberately not dispatched when journey_acquisition returned sheet None"
            in flat)

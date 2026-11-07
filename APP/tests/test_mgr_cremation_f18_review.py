"""F18 review: one journey-source path for carried creatures, one contract statement.

Both regressions are synthetic and public-CI safe (no repository history, owner
data or private fixtures). The source-sheet check registers a test-scoped hook
through the same public dispatch point the engine uses, so the code under test
stays the real ``CombatService.create_journey`` and the real file-backed journey
store.
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


def test_carried_creature_source_sheet_is_projected_once_on_the_real_session(tmp_path, monkeypatch):
    """Carried creatures get one source-sheet projection, on the real session.

    ``JourneyStore.create`` runs the continuation path (``_continued_bundles``)
    for every carried creature, and that is the one place its installed sheet is
    decorated before the journey keeps it; ``create_journey`` must not compute the
    same projection a second time on a precompile stand-in. The provider here
    reads the documented session identity and clock, so the shape it receives is
    pinned (real journey id, the created scene, zero elapsed seconds), and it
    renames the creature to prove the projected sheet reaches the compiled
    journey instead of being discarded after inspection.
    """
    _sheets(monkeypatch)
    seen = []

    def initialize(session, actor_id):
        seen.append({"point": "initialize", "actor_id": actor_id,
                     "journey_id": session.state["journey_id"],
                     "scene_id": session.state.get("scene_id"),
                     "seconds": session.state["seconds"],
                     "clock": int(session.clock()),
                     "actors": sorted(session.state["actors"])})

    def project(sheet_in, session, actor_id):
        seen.append({"point": "sheet", "actor_id": actor_id,
                     "journey_id": session.state["journey_id"],
                     "scene_id": session.state.get("scene_id"),
                     "seconds": session.state["seconds"],
                     "clock": int(session.clock()),
                     "actors": sorted(session.state["actors"])})
        result = dict(sheet_in)
        result["identity"] = {**result["identity"],
                              "name": sheet_in["identity"]["name"] + " (projected)"}
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

    # One projection and one initialization per carried creature, both on the
    # real session: no second computation on a precompile stand-in.
    assert sorted((row["point"], row["actor_id"], row["journey_id"]) for row in seen) == sorted([
        ("sheet", A, second["journey_id"]), ("sheet", B, second["journey_id"]),
        ("initialize", A, second["journey_id"]), ("initialize", B, second["journey_id"])])
    for row in seen:
        assert row["scene_id"] == second["journey_id"] + ":scene:0"
        assert row["seconds"] == 0 and row["clock"] == 0
        assert row["actors"] == sorted([A, B])
    # The projected sheet is the one the journey compiled, not a discarded copy.
    for aid, name in ((A, "Wren (projected)"), (B, "Mara (projected)")):
        assert second["actors"][aid]["bundle"]["actor_template"]["display_name"] == name


def test_journey_source_contracts_are_stated_once_and_no_build_skip_is_documented():
    """One authoritative contract, and the documented reason journey_acquired skips."""
    documentation = ast.get_docstring(ast.parse((Path(ROOT) / "combat/ext/__init__.py").read_text()))
    assert documentation.count("journey_source_sheet(sheet, session, actor_id)") == 1
    assert documentation.count("journey_acquisition(session, actor_id, source, payload, sheet)") == 1
    assert documentation.count("journey_acquired(session, actor_id, source, acquisition_id)") == 1
    flat = " ".join(documentation.split())
    assert ("deliberately not dispatched when journey_acquisition returned sheet None"
            in flat)

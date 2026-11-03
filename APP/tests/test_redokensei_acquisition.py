"""Native table level acquisition must retain the CL18 transformation menu."""
from copy import deepcopy

from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.grow5_support import BODY, PID, SPHERE, baseline, install
from tests.h1_support import ROOT
from tests.worker2_support import OWNER, fixture, candidate, settle, reload

SUBPATH = "tianxia.subpath.body.kensei"
SAINT = SUBPATH + ".feature.sword_saint_incarnation"


def acquired_kensei(root, level=18):
    """Select Restricted Scripture via the native authorized access confirmation.

    No feature IDs are assigned by this fixture: published level progression
    grants them. The unrelated level-talent menu is a public synthetic catalog.
    """
    install(root, baseline(BODY))
    talents = [{"canonical_talent_id": f"synthetic.kensei.practice.{i}",
                "display_name": f"Practice {i}", "owning_canonical_sphere_id": SPHERE,
                "minimum_cl": 1, "typed_constraints": [{"kind": "minimum_cl", "value": 1}]}
               for i in range(20)]
    for cl in range(2, level + 1):
        table = TabletopService(CombatService(ROOT, root), root)
        table._talents_cache = deepcopy(talents)
        table._spheres_cache = {SPHERE: "Water"}
        view = table.advancement(PID)["level_up"]
        assert view["cl"] == cl
        selected = {}
        build = list(view.get("feature_choices") or [])
        for group in view["subpaths"]:
            option = next(r for r in group["options"] if r["id"] == SUBPATH)
            selected[group["path_id"]] = option["id"]
            build.extend(option.get("build_choices") or [])
        payload = {"cl": cl, "talent_ids": [talents[cl - 2]["canonical_talent_id"]],
                   "subpaths": selected, "access_confirmed": True,
                   "feature_choices": {b["feature_id"]: b["options"][0]["id"] for b in build}}
        if view["advancement_choice"]:
            payload.update(advancement="ability", changes={"CON" if cl <= 8 else "DEX": 2})
        table.level_up(PID, payload)
    return CombatService(ROOT, root)._factory_owner_sheet(PID)


def test_acquired_sword_saint_is_offered_at_match_start_and_cold_reload(tmp_path, monkeypatch):
    doc = acquired_kensei(tmp_path / "acquisition")
    features = doc["path_and_subpath"]["path_feature_record_ids"]
    assert SAINT in features
    assert all(SUBPATH + ".feature." + name in features for name in (
        "blade_fist", "sword_draws_before_thought", "flowing_blade_stance", "severing_palm"))
    bundle = compile_character(doc, actor_id=OWNER, reaction_plan={"ask": True})
    from tests import worker2_support as w
    with monkeypatch.context() as patch:
        patch.setattr(w, "turn", lambda *args: None)
        combat, table, mid = fixture(tmp_path / "fight", [], owner_bundle=bundle, seed="KENSEI-ACQUIRED")
    engine = reload(tmp_path / "fight", mid)
    assert all(a.turns_started == 0 for a in engine.state.actors.values())
    assert any(task.source_id == SUBPATH + ".feature.sword_draws_before_thought" for task in engine.state.setup_tasks)
    settle(table, mid, engine.legal_candidates()[0].candidate_id,
           choices={"choice:needle.sword_draws_before_thought": "ac"})
    w.turn(table, mid, OWNER)
    row = candidate(combat, mid, "Sword Saint Incarnation")
    reload(tmp_path / "fight", mid)
    cold = CombatService(ROOT, tmp_path / "fight")
    cold_table = TabletopService(cold, tmp_path / "fight")
    again = candidate(cold, mid, "Sword Saint Incarnation")
    assert again.source_definition_id == row.source_definition_id
    settle(cold_table, mid, again.candidate_id, choices={})
    engine = reload(tmp_path / "fight", mid)
    assert any(c.condition_id == "condition:typed.state.sword_saint_incarnation"
               for c in engine.state.actors[OWNER].conditions.values())

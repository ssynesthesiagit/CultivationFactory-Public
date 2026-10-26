"""TEMPORARY lane debug (not committed): one-line diagnostics for findings 1 and 2."""
from __future__ import annotations

SEAL = "TAL_WATER_ABYSSAL_PRESSURE_SEAL"
COURT = "TAL_WATER_COURT_OF_THE_ENDLESS_TIDE"


def test_dbg_silenced_conditions(tmp_path):
    from tests import test_riders_lane1 as R
    engine = R._rider_engine(SEAL, talents=(COURT,))
    foe = engine.state.actors[R.AN]
    R._rider_use(engine, COURT)
    d = ["aftercourt=%s" % sorted(r.condition_id.replace("condition:typed.", "") for r in foe.conditions.values())]
    before = len(engine.events)
    R._rider_use(engine, SEAL)
    d.append("seal_ev=" + ",".join(e.event_type.replace("CONDITION_", "C_") + ":" + str(e.payload.get("condition_id", "")).replace("condition:typed.", "").replace("condition:", "")
                                   for e in engine.events[before:] if e.event_type.startswith("CONDITION")))
    d.append("afterseal=%s" % sorted(r.condition_id.replace("condition:typed.", "") for r in foe.conditions.values()))
    assert False, " ;; ".join(d)[:900]


def test_dbg_two_court_seal_lifecycle(tmp_path):
    import json
    import zipfile
    from combat.factory_compiler import compile_character
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    from tests import test_mgr_t15_close_abyssal_pressure_seal as M

    OWNER, second, TARGET = M.OWNER, "actor:factory.seal-owner-two", M.TARGET
    owner_two = M.sheet([M.SEAL, M.COURT], cp=40)
    owner_two["ability_scores_and_statistics"]["technique_save_dc"] = 17
    owner_two["identity"]["name"] = "Second Keeper"
    traveller = M.sheet()
    traveller["identity"].update(name="Traveller", key_ability="DEX")
    next(a for a in traveller["ability_scores_and_statistics"]["abilities"] if a["ability"] == "DEX").update(score=30, modifier=10)
    traveller["spheres_and_talents"]["sphere_record_ids"].append("tianxia.sphere.space")
    traveller["spheres_and_talents"]["automatic_sphere_component_record_ids"].append("TAL_SPACE_FOLD_STEP")
    docs = {OWNER: M.sheet([M.SEAL, M.COURT], cp=40), second: owner_two, TARGET: traveller}
    for aid, doc in docs.items():
        folder = tmp_path / "portable_characters" / aid.removeprefix("actor:factory.")
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as z:
            z.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(doc))
    ids = [OWNER, second, TARGET]
    c = CombatService(M.ROOT, tmp_path); t = TabletopService(c, tmp_path)
    bundles = [compile_character(docs[a], actor_id=a, reaction_plan={"ask": True}) for a in ids]
    mid = c._finish_factory_match(bundles, ids,
        {OWNER: "team:factory", second: "team:factory", TARGET: "team:opponents"},
        {OWNER: {"x": 3, "y": 6}, second: {"x": 3, "y": 7}, TARGET: {"x": 4, "y": 6}},
        c.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"], [OWNER, second], [TARGET],
        control_modes={a: "MANUAL" for a in ids}, match_seed="ABYSSAL-TWO-COURTS",
        display_name="Abyssal two seals", maximum_rounds=10)["match_id"]
    M.turn(t, mid, OWNER)
    M.settle(t, mid, M.rows(c, mid, M.COURT)[0].candidate_id)
    M.settle(t, mid, M.rows(c, mid, M.SEAL, TARGET)[0].candidate_id)
    e = M.cold(tmp_path, mid)
    print("after first seal:", sorted((r.condition_id[-8:], r.expires_on) for r in e.state.actors[TARGET].conditions.values() if r.data.get("abyssal_pressure_seal")))
    first = [(r.condition_id[-6:], r.expires_on, r.applied_sequence) for r in e.state.actors[TARGET].conditions.values() if r.data.get("abyssal_pressure_seal")]
    M.turn(t, mid, second)
    e2 = M.cold(tmp_path, mid)
    mid_conds = sorted((r.condition_id[-6:], r.expires_on) for r in e2.state.actors[TARGET].conditions.values() if r.data.get("abyssal_pressure_seal"))
    M.settle(t, mid, M.rows(c, mid, M.COURT)[0].candidate_id)
    M.settle(t, mid, M.rows(c, mid, M.SEAL, TARGET)[0].candidate_id)
    e3 = M.cold(tmp_path, mid)
    third = sorted((r.condition_id[-6:], r.expires_on) for r in e3.state.actors[TARGET].conditions.values() if r.data.get("abyssal_pressure_seal"))
    removed = [str((ev.payload.get("condition_id", "")[-8:], ev.payload.get("expires_on"))) for ev in e3.events if ev.event_type == "CONDITION_REMOVED" and "abyssal_pressure_seal" in str(ev.payload.get("condition_id", ""))]
    assert False, ("first=%s | atsecondturn=%s | afterboth=%s | removed=%s" % (first, mid_conds, third, removed))[:900]

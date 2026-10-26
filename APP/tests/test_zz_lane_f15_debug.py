"""TEMPORARY lane debug (not committed): compact diagnostics for findings 1 and 2."""
from __future__ import annotations

SEAL = "TAL_WATER_ABYSSAL_PRESSURE_SEAL"
COURT = "TAL_WATER_COURT_OF_THE_ENDLESS_TIDE"


def _conds(foe):
    return ",".join(sorted(c.condition_id.split(":")[-1].replace("typed.", "") for c in foe.conditions.values())) or "-"


def test_dbg_silenced(tmp_path):
    from combat import typed_executor as te
    from tests import test_riders_lane1 as R
    engine = R._rider_engine(SEAL, talents=(COURT,))
    foe = engine.state.actors[R.AN]
    R._rider_use(engine, COURT)
    court = _conds(foe)
    mark = len(engine.events)
    R._rider_use(engine, SEAL)
    after = _conds(foe)
    imm = bool(te.condition_immune(engine, foe, "silenced"))
    ev = []
    for e in engine.events[mark:]:
        t = e.event_type
        if t.startswith("CONDITION") or t in ("PASSIVE_TRIGGERED", "CHECK_ROLLED", "SAVE_ROLLED", "NOTE", "GM_NOTE"):
            tail = str(e.payload.get("condition_id") or e.payload.get("check") or e.payload.get("log") or "")[-16:]
            ev.append(t[:7] + ":" + tail)
    assert False, ("after=[%s] imm=%s court=[%s] ev=%s" % (after, imm, court, "|".join(ev)))[:300]


def test_dbg_two_courts(tmp_path):
    import json
    import zipfile
    from combat.factory_compiler import compile_character
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    from tests import test_mgr_t15_close_abyssal_pressure_seal as M

    OWNER, TARGET = M.OWNER, M.TARGET
    second = "actor:factory.seal-owner-two"
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

    def seals():
        e = M.cold(tmp_path, mid)
        rows_ = [(r.condition_id.split(":")[-1].replace("actor:factory.seal-owner", "O"), r.data.get("dc"), r.expires_on)
                 for r in e.state.actors[TARGET].conditions.values() if r.data.get("abyssal_pressure_seal")]
        return e, rows_

    M.turn(t, mid, OWNER)
    M.settle(t, mid, M.rows(c, mid, M.COURT)[0].candidate_id)
    M.settle(t, mid, M.rows(c, mid, M.SEAL, TARGET)[0].candidate_id)
    _, one = seals()
    M.turn(t, mid, second)
    _, at_two = seals()
    M.settle(t, mid, M.rows(c, mid, M.COURT)[0].candidate_id)
    M.settle(t, mid, M.rows(c, mid, M.SEAL, TARGET)[0].candidate_id)
    _, both = seals()
    M.turn(t, mid, TARGET)
    e, at_target = seals()
    removed = [str(ev.payload.get("condition_id", "")[-9:]) for ev in e.events
               if ev.event_type == "CONDITION_REMOVED" and "abyssal_pressure_seal" in str(ev.payload.get("condition_id", ""))]
    position = e.state.actors[TARGET].position
    options = [r for r in M.rows(c, mid, "TAL_SPACE_FOLD_STEP") if r.destination and r.destination != position]
    if not options:
        assert False, ("NOOPT one=%s at2=%s both=%s atT=%s rm=%s" % (one, at_two, both, at_target, removed))[:300]
    M.settle(t, mid, options[0].candidate_id)
    e = M.cold(tmp_path, mid)
    checks = [int(v.payload["dc"]) for v in e.events if v.event_type == "CHECK_ROLLED"
              and v.actor_id == TARGET and v.payload.get("check") == "Water Check"]
    assert False, ("chk=%s atT=%s one=%s both=%s at2=%s rm=%s" % (checks, at_target, one, both, at_two, removed))[:300]

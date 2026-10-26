"""TEMPORARY lane debug (not committed): dump diagnostics for findings 1 and 2."""
from __future__ import annotations

SEAL = "TAL_WATER_ABYSSAL_PRESSURE_SEAL"
COURT = "TAL_WATER_COURT_OF_THE_ENDLESS_TIDE"


def test_dbg_silenced(tmp_path):
    from tests import test_riders_lane1 as R
    engine = R._rider_engine(SEAL, talents=(COURT,))
    foe = engine.state.actors[R.AN]
    print("before:", sorted(c.condition_id for c in foe.conditions.values()))
    ev = R._rider_use(engine, COURT)
    print("court events:", [(e.event_type, e.source_definition_id) for e in ev])
    print("after-court:", sorted((c.condition_id, c.expires_on, c.source_definition_id) for c in foe.conditions.values()))
    ev = R._rider_use(engine, SEAL)
    for e in ev:
        print("seal-event:", e.event_type, e.source_definition_id, str(e.payload)[:300])
    print("after-seal:", sorted((c.condition_id, c.expires_on, c.source_definition_id, c.data) for c in foe.conditions.values()))
    print("me conditions:", sorted(c.condition_id for c in engine.state.actors[R.ME].conditions.values()))
    assert False, "debug dump (see captured stdout)"


def test_dbg_two_courts(tmp_path):
    from combat.ext import ability_source, _HOOKS
    from combat.ext import water_second_pass as wsp
    from tests import test_mgr_t15_close_abyssal_pressure_seal as M

    orig = ability_source.cultivation_check
    seen = {}

    def logged(engine, actor, numbers, dc, source, check_name="Cultivation Check", modes=None):
        before = len(engine.events)
        out = orig(engine, actor, numbers, dc, source, check_name, modes)
        print("  cultivation_check dc=%s source=%s actor=%s -> %s new_events=%d"
              % (dc, source, actor.entity_id, out, len(engine.events) - before))
        return out

    ability_source.cultivation_check = logged
    orig_attempt = wsp.seal_attempt

    def attempt(engine, subject, source):
        seen["engine"] = engine
        before = len(engine.events)
        print("seal_attempt start: events=%d conds=%s" % (before, sorted(
            (c.condition_id, c.data.get("dc"), c.source_definition_id) for c in subject.conditions.values()
            if c.data.get("abyssal_pressure_seal"))))
        out = orig_attempt(engine, subject, source)
        print("seal_attempt subject=%s source=%r -> %s" % (subject.entity_id, source, out))
        for e in engine.events[before:]:
            if e.event_type == "CHECK_ROLLED":
                print("   check:", e.source_definition_id, e.payload.get("dc"), e.payload.get("success"))
        return out

    for name in ("teleport_context_check", "technique_declared", "effect_execution_allowed", "movement_attempt"):
        _HOOKS[name] = [attempt if h is orig_attempt else h for h in _HOOKS[name]]
    import combat.ext as ext
    ext.water_second_pass.seal_attempt = attempt
    try:
        M.test_two_water_courts_each_seal_rolls_against_its_own_dc(tmp_path, 17)
        print("two-courts test PASSED (17)")
    except AssertionError as exc:
        print("two-courts test FAILED (17):", exc)
    engine = seen.get("engine")
    if engine is not None:
        print("events with intent/check/condition:")
        for i, e in enumerate(engine.events):
            if e.event_type in ("INTENT_ACCEPTED", "CHECK_ROLLED", "CONDITION_APPLIED", "CONDITION_REMOVED"):
                print("   ", i, e.event_type, e.source_definition_id, e.actor_id, str(e.payload)[:220])
    assert False, "debug dump (see captured stdout)"

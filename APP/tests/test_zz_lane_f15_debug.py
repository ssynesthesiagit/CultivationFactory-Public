"""TEMPORARY lane debug (not committed): one-line diagnostics for findings 1 and 2."""
from __future__ import annotations

SEAL = "TAL_WATER_ABYSSAL_PRESSURE_SEAL"
COURT = "TAL_WATER_COURT_OF_THE_ENDLESS_TIDE"


def test_dbg_silenced(tmp_path):
    from tests import test_riders_lane1 as R
    engine = R._rider_engine(SEAL, talents=(COURT,))
    foe = engine.state.actors[R.AN]
    d = ["before=%s" % sorted(c.condition_id for c in foe.conditions.values())]
    ev = R._rider_use(engine, COURT)
    d.append("court=" + "|".join("%s:%s" % (e.event_type, e.source_definition_id) for e in ev)[-600:])
    d.append("after-court=%s" % sorted((c.condition_id, c.expires_on) for c in foe.conditions.values()))
    before = len(engine.events)
    ev = R._rider_use(engine, SEAL)
    d.append("seal=" + "|".join("%s:%s:%s" % (e.event_type, e.source_definition_id, str(e.payload)[:80]) for e in ev)[-1500:])
    d.append("after-seal=%s" % sorted((c.condition_id, c.expires_on) for c in foe.conditions.values()))
    d.append("me=%s" % sorted(c.condition_id for c in engine.state.actors[R.ME].conditions.values()))
    assert False, " ;; ".join(d)


def test_dbg_two_courts(tmp_path):
    from combat.ext import ability_source, _HOOKS
    from combat.ext import water_second_pass as wsp
    from tests import test_mgr_t15_close_abyssal_pressure_seal as M

    orig = ability_source.cultivation_check
    d = []

    def logged(engine, actor, numbers, dc, source, check_name="Cultivation Check", modes=None):
        before = len(engine.events)
        out = orig(engine, actor, numbers, dc, source, check_name, modes)
        d.append("check(dc=%s,src=%s,actor=%s)->%s,+%d" % (dc, str(source)[-30:], actor.entity_id[-12:], out, len(engine.events) - before))
        return out

    ability_source.cultivation_check = logged
    orig_attempt = wsp.seal_attempt

    def attempt(engine, subject, source):
        d.append("attempt[ev=%d,conds=%s]" % (len(engine.events), sorted(
            ("%s/%s" % (c.condition_id[-16:], c.data.get("dc"))) for c in subject.conditions.values()
            if c.data.get("abyssal_pressure_seal"))))
        out = orig_attempt(engine, subject, source)
        d.append("attempt->=%s" % out)
        return out

    for name in ("teleport_context_check", "technique_declared", "effect_execution_allowed", "movement_attempt"):
        _HOOKS[name] = [attempt if h is orig_attempt else h for h in _HOOKS[name]]
    import combat.ext as ext
    ext.water_second_pass.seal_attempt = attempt
    result = "PASS"
    try:
        M.test_two_water_courts_each_seal_rolls_against_its_own_dc(tmp_path, 17)
    except AssertionError as exc:
        result = "FAIL:%s" % str(exc)[:200]
    assert False, ("two-courts=" + result + " ;; " + " ;; ".join(d))[-3000:]

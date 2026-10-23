"""Forward Cut's approach bonus (combat/ext/approach.py): "If you moved at least 10 feet toward the target this turn, add
your Proficiency Bonus to the damage roll." Counted from the fighter's own moves this turn."""

from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent
from combat.ext.approach import approached_ft
from tests.test_auto_wenxue import ME, _bundle, _engine, _ready, _use


def _step_to(engine, x, y):
    candidate = next(c for c in engine.legal_candidates() if c.source_definition_id == "system:combat.movement"
                     and c.destination is not None and (c.destination.x, c.destination.y) == (x, y))
    engine.execute_intent(ActionIntent(intent_id=f"move{x}{y}", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=ME, target_ids=(), destination=candidate.destination))


def _bonus_events(engine):
    return [e for e in engine.events if e.event_type == "PASSIVE_TRIGGERED" and "toward the target" in str((e.payload or {}).get("trigger"))]


def _hit(engine):
    foe = engine.state.actors[AN]
    for _ in range(10):
        before = foe.current_hp
        _ready(engine)
        _use(engine, "Forward Cut")
        if foe.current_hp < before:
            return True
    return False


def test_ten_feet_toward_the_target_adds_proficiency_bonus_of_the_weapon_s_type():
    engine = _engine(_bundle(), foe_at=(7, 6))
    _step_to(engine, 5, 6)
    assert approached_ft(engine, engine.state.actors[ME], engine.state.actors[AN]) == 10
    _step_to(engine, 6, 6)
    assert _hit(engine)
    assert _bonus_events(engine)
    bonus = [e for e in engine.events if e.event_type == "DAMAGE_COMMITTED" and e.actor_id == ME][-1]
    assert bonus.payload["damage_type"] == "SLASHING"


def test_no_approach_no_bonus():
    engine = _engine(_bundle(), foe_at=(4, 6))
    assert approached_ft(engine, engine.state.actors[ME], engine.state.actors[AN]) == 0
    assert _hit(engine)
    assert not _bonus_events(engine)

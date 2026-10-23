"""Non-Yang options survive public-export inputs and a real table cold reload."""
from types import SimpleNamespace

from combat import factory_compiler
from combat.effect_rolls import roll_amount
from combat.gate2_runtime_models import DiceSpec, RollRecord
from combat.result_rolls import apply_bonus
from tests.test_option_tooltips import (
    synthetic_printed_options,
    test_printed_options_reach_sheet_and_real_table_menu_after_reload as check_table_options,
)


def test_non_yang_shape_darkness_after_reload_without_private_rule_text(tmp_path, monkeypatch):
    # Public snapshots can omit the source prose. The synthetic fixture must
    # supply the compiler's input too, not just the status/hover reader's copy.
    monkeypatch.setattr(factory_compiler, "_RULES_TEXT_CACHE", {}, raising=False)
    fixture = synthetic_printed_options.__wrapped__(tmp_path, monkeypatch)
    next(fixture)
    try:
        check_table_options(tmp_path, False)
    finally:
        next(fixture, None)


def test_shared_roll_seams_are_inert_without_yang_state():
    """No changed draw arguments, replacement record, state or bonus receipt."""
    actor = SimpleNamespace(entity_id="actor:darkness", conditions={})
    source = "TAL_DARK_NUMBING_DARKNESS"
    record = RollRecord(
        roll_id="roll:non-yang", counter_start=0, counter_end=1,
        expression="1d6+2", actor_id=actor.entity_id, reason="DAMAGE:" + source,
        dice=(3,), modifier=2, total=5)
    draws, events = [], []

    def draw(spec, **kwargs):
        draws.append((spec, kwargs))
        return record

    engine = SimpleNamespace(
        roller=SimpleNamespace(roll=draw), action_catalog={},
        state=SimpleNamespace(actors={actor.entity_id: actor}),
        _append_event=lambda *args, **kwargs: events.append((args, kwargs)))
    spec = DiceSpec(count=1, sides=6, modifier=2)
    for critical in (False, True):
        assert roll_amount(engine, actor, spec, source, record.reason, critical=critical) is record
    assert draws == [(spec, {"actor_id": actor.entity_id, "reason": record.reason, "critical": value})
                     for value in (False, True)]
    for failed in (False, True):
        assert apply_bonus(
            engine, record, source, "settled_save_roll_bonus",
            actor, "CON", 15, record, source, None, failed, actor) is record
    assert not events
    assert not actor.conditions

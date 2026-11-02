"""Silent Foundation reads check hazards without confusing consequence tags."""
from types import SimpleNamespace

import pytest

from combat.ext import insights7_batch6 as plug
from tests.auto_worker1_support import LEFT, RIGHT, action_sender, resolve
from tests.test_a2_ins7d_batch6 import fresh, rewrites, silent_match


@pytest.mark.parametrize("hazard", ["sound", "hearing", "noise"])
@pytest.mark.parametrize("ai", [False, True])
def test_native_sound_hazards_reach_silent_foundation_after_reload(tmp_path, hazard, ai):
    combat, table, mid = silent_match(tmp_path, hazard=hazard, ai=ai)
    # Reopen before the triggering action as well as after the committed reroll.
    fresh(combat, mid)
    _, prompts = resolve(action_sender(combat, table, mid, "Prepare", ai=ai, target_id=RIGHT))
    engine = fresh(combat, mid)
    events = rewrites(engine)
    assert len(events) == 1, "Silent Foundation must reroll a sound-caused failed Stealth check"
    assert events[0].actor_id == LEFT
    assert bool(prompts) is not ai
    assert engine.state.actors[LEFT].turn_flags["_round_h1_fight:" + plug.SILENT] == 1


@pytest.mark.parametrize("hazards,named,eligible", [
    (["sound"], [], True),
    (["hearing"], [], True),
    (["noise"], [], True),
    ([], ["sound"], False),
    (["visual_concealment"], ["sound"], False),
])
def test_guard_uses_actual_check_hazards_only(hazards, named, eligible):
    engine = SimpleNamespace(d20_context=lambda roll: {"skill": "stealth", "hazards": hazards})
    context = SimpleNamespace(roll=object(), ability="DEX", named=frozenset(named))
    assert plug.sound_failure(engine, None, context) is eligible


def test_original_guard_reproduces_missing_native_sound_reroll(tmp_path, monkeypatch):
    from combat.ext.d20_rewrite import RULES

    def original_guard(engine, holder, context):
        native = engine.d20_context(context.roll) or {}
        return (context.ability == "DEX" and str(native.get("skill") or "").lower() == "stealth"
                and bool(context.named & {"sound", "hearing", "noise"}))

    # Isolated historical-contract injection, restored at test teardown.
    # The real table commit/reload must reach the missing-reroll assertion.
    monkeypatch.setattr(RULES["ins7d_silent_foundation"], "guard", original_guard)
    with pytest.raises(AssertionError, match="Silent Foundation must reroll"):
        test_native_sound_hazards_reach_silent_foundation_after_reload(tmp_path, "sound", False)

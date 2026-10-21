from types import SimpleNamespace

from combat.ext.furnace_runtime import reinforcement_contest_mode


def test_seed_fed_reinforcement_applies_to_cultivation_contests_only():
    held = SimpleNamespace(
        condition_id="condition:typed.second_furnace_advantage",
        data={"cultivation": 1},
    )
    actor = SimpleNamespace(conditions={"advantage": held})
    ctx = SimpleNamespace(actor=actor)

    assert reinforcement_contest_mode(ctx, actor, object(), {"kind": "cultivation"}) == "ADVANTAGE"
    assert reinforcement_contest_mode(ctx, actor, object(), {"kind": "grapple"}) is None
    assert reinforcement_contest_mode(ctx, object(), actor, {"kind": "cultivation"}) is None

"""Replacing a standard damage payload with an Echo handler retains its strike role."""
from combat.ai_tactics import owned_profile
from combat.ext import echo_step_disciple as echo
from tests.h1_support import ME, duel


def test_echo_wrapped_mind_spike_is_still_a_strike():
    engine = duel([echo.AFTERIMAGE_EDGE, echo.MIND_SPIKE], primary="Resonance", cl=18)
    profile = owned_profile(engine, engine.state.actors[ME])["actions"]
    wrappers = [aid for aid in profile if aid.endswith(".echo_origin")
                and engine.action_catalog[aid].parameters["typed"].get("source") == echo.MIND_SPIKE]
    assert wrappers
    for aid in wrappers:
        assert profile[aid]["damage"] > 0
        assert profile[aid]["attack"] is True

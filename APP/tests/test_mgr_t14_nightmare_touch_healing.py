"""Review regression: Nightmare Touch's failed-save prohibition is committed state, and it refuses
only the healing the printed clause names (recovery from sleep or rest).

Printed clause: \"It ifcpg 4d8 + Wneovh ymykdsgh Puysham hfncpc, ydrav a Nsdpsimfm Scar, and afrydk
eukkcb Hit Ptsefm dmvw oftak or smfb lgmad the iubrv of yvdk fidh turn.\" An ability's or a potion's
healing is not sleep or rest recovery, so it still lands in the same window.
"""
import pytest

from combat.gate4_persistence import Gate4Persistence
from combat.gate2_runtime_models import ActionIntent
from combat import typed_executor
from tests.cw2_service_support import add_action
from tests.test_mgr_t14_ling_trad_nightmare_touch import ROOT, ME, FOE, DE, bundle

DENIAL = "condition:typed.nightmare_touch_healing_denied"


def heals(actor_bundle):
    add_action(actor_bundle, "Test recovery", [
        {"type": "healing", "applies_to": "target", "flat": 7}])
    for name, tag in (("Test rest recovery", "rest"), ("Test sleep recovery", "sleep")):
        add_action(actor_bundle, name, [
            {"type": "healing", "applies_to": "target", "flat": 7, tag: True}])


def cast(session, name, target=None):
    candidate = next(c for c in session.engine.legal_candidates()
                     if c.display_name == name and
                     (target is None or target in (c.target_ids or ())))
    session.mechanical.execute_intent(ActionIntent(
        intent_id=f"healing-{candidate.state_version}-{name}",
        decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
        state_version=candidate.state_version, actor_id=candidate.actor_id,
        target_ids=(target,) if target else candidate.target_ids,
        destination=candidate.destination))


def hp(session):
    return session.engine.state.actors[FOE].current_hp


def denied(session):
    victim = session.engine.state.actors[FOE]
    return any(c.condition_id == DENIAL for c in victim.conditions.values())


def heal_and_reload(session, persistence, name):
    """Cast one recovery at the victim, cold-reload, and return (before, after, denied)."""
    before = hp(session)
    was_denied = denied(session)
    cast(session, name, FOE)
    session = persistence.load_match(session.match_id)
    return session, before, hp(session), was_denied


@pytest.mark.parametrize("failed", [True, False])
def test_healing_denial_is_scoped_to_sleep_and_rest(tmp_path, failed):
    """A failed save refuses rest/sleep recovery only; an ordinary heal still lands, and the
    prohibition ends at the start of the printed source's next turn."""
    hunter = bundle([DE + "nightmare_touch"], dc=40 if failed else -40)
    patient = bundle([], actor_id=FOE)
    for actor_bundle in (hunter, patient):
        heals(actor_bundle)
    persistence = Gate4Persistence(ROOT, tmp_path)
    session = persistence.create_match(
        match_seed="NT-HEAL-RELOAD", typed_bundles=(hunter, patient),
        roster_setup={"primary_actor_ids": [ME, FOE],
                      "team_by_actor": {ME: "team:a", FOE: "team:b"},
                      "starting_positions": {ME: {"x": 3, "y": 6},
                                             FOE: {"x": 4, "y": 6}}})
    while session.engine.state.current_actor_id != ME:
        cast(session, "End turn")
    cast(session, "Nightmare Touch", FOE)
    session = persistence.load_match(session.match_id)
    victim = session.engine.state.actors[FOE]
    assert any(c.condition_id == DENIAL for c in victim.conditions.values()) == failed
    assert any(r.get("healing_denied") == ["sleep", "rest"]
               for r in typed_executor.condition_rules(victim)) == failed
    maximum_hp = victim.maximum_hp
    assert victim.current_hp < maximum_hp

    # Sleep and rest recovery: refused while the failed-save prohibition runs, in the same window.
    for name in ("Test rest recovery", "Test sleep recovery"):
        session, before, after, was_denied = heal_and_reload(session, persistence, name)
        assert was_denied == failed
        assert after == (before if failed else min(maximum_hp, before + 7))

    # An ordinary healing ability or potion is not sleep or rest recovery: it still heals.
    session, before, after, was_denied = heal_and_reload(session, persistence, "Test recovery")
    assert was_denied == failed
    assert after == min(maximum_hp, before + 7)
    assert denied(session) == failed

    # The victim's own turn does not end the printed "your next turn" window.
    cast(session, "End turn")
    assert session.engine.state.current_actor_id == FOE
    session, before, after, was_denied = heal_and_reload(session, persistence, "Test rest recovery")
    assert was_denied == failed
    assert after == (before if failed else min(maximum_hp, before + 7))

    # The start of the source's next turn ends it; rest recovery works again.
    cast(session, "End turn")
    assert session.engine.state.current_actor_id == ME
    session = persistence.load_match(session.match_id)
    assert not denied(session)
    session, before, after, was_denied = heal_and_reload(session, persistence, "Test rest recovery")
    assert was_denied is False
    assert after == min(maximum_hp, before + 7)
    assert session.verify()["status"] == "PASS"

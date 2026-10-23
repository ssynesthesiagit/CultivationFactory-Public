"""Redirecting Shield after Active Defense's after-roll timing (combat/ext/redirect_reactions.py).

Active Defense now opens after ATTACK_ROLLED, so the redirect hook must find that window on the far side of the roll.
The Active Defense reading comes from the synthetic authority (tests/active_defense_authority_support.py), because the
public printed prose does not classify to a production row. The real compiler and redirect consumer then execute.
"""
from combat import ext
from tests.active_defense_authority_support import install
from tests.test_h2_redirect_reactions import FOCUS, FOE, FOE2, ME, _foe_swings, _shielded, _table


def test_redirecting_shield_follows_ordinary_active_defense_on_a_missed_swing(tmp_path, monkeypatch):
    install(tmp_path, monkeypatch)
    ext.effects()
    engine = _shielded()
    me, foe2 = engine.state.actors[ME], engine.state.actors[FOE2]
    _table(engine, choice=FOE2, choice_source="redirecting_shield", uses=("SHIELD_BASE_ACTIVE_DEFENSE",))
    hp = foe2.current_hp
    events = _foe_swings(engine)
    roll = next(e for e in events if e.event_type == "ATTACK_ROLLED" and FOE in (e.actor_id,) and ME in (e.target_ids or ()))
    window = next(e for e in events if e.event_type == "REACTION_WINDOW_OPENED" and e.source_definition_id == "SHIELD_BASE_ACTIVE_DEFENSE")
    assert window.sequence > roll.sequence  # the ordinary post-roll timing
    triggered = [e for e in events if e.event_type == "PASSIVE_TRIGGERED" and e.source_definition_id == "passive:TAL_SHIELD_REDIRECTING_SHIELD"]
    assert len(triggered) == 1 and triggered[0].target_ids == (FOE, FOE2) and triggered[0].payload["hit"] is True
    assert me.resources[FOCUS] == 0 and foe2.current_hp < hp

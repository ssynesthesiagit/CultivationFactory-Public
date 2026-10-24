"""Anchor's reviewed movement reduction protects the mover, not the pusher.

riders/c13 (e8625061, merged 51edf97d; approved C13r3.review.md)
replaced the former generic condition with the printed choose-one outcomes.
These table regressions require the actual reduction, recipient and payment.
"""
import pytest

from tests.anchor_support import ANCHOR, ME, FRIEND, FOE, fight, push


@pytest.mark.parametrize("ai", [False, True])
@pytest.mark.parametrize("ally", [False, True])
def test_anchor_defends_mover_after_table_commit_reload_replay(tmp_path, monkeypatch, ai, ally):
    service, table, mid = fight(tmp_path, ally=ally, ai=ai)
    target = FRIEND if ally else ME
    before = service._load_session(mid).engine.state
    position = before.actors[target].position
    engine, prompts = push(service, table, mid, target, ai=ai, monkeypatch=monkeypatch)
    assert any(p["reaction"] == "Anchor the Link" for p in prompts)
    benefits = [e for e in engine.events if e.event_type == "REACTION_RESOLVED" and e.source_definition_id == ANCHOR]
    assert benefits and all(e.target_ids == (target,) for e in benefits)
    assert all(e.payload["distance_before"] == 5 and e.payload["distance_after"] == 0 for e in benefits)
    assert engine.state.actors[target].position == position
    assert engine.state.actors[ME].resources["resource:core.qi"] == before.actors[ME].resources["resource:core.qi"] - 1
    assert not any(m.source_definition_id == ANCHOR for m in engine.state.actors[FOE].conditions.values())


def test_defensive_recipient_keeps_explicit_attacker_source():
    from combat import typed_reactions
    from tests.test_forced_movement_reactions import _engine, _row, REACTOR, AN, LEE
    engine = _engine([])
    typed_reactions._run_generic_effects(engine, engine.state.actors[REACTOR], engine.state.actors[AN], _row("ally_forced_moved"),
        [{"type": "temp_hp", "flat": 3, "applies_to": "target"},
         {"type": "temp_hp", "flat": 4, "applies_to": "attacker"},
         {"type": "temp_hp", "flat": 5, "applies_to": "ally"}], recipient=engine.state.actors[LEE])
    assert engine.state.actors[LEE].temporary_hp == 5
    assert engine.state.actors[AN].temporary_hp == 4
    assert engine.state.actors[REACTOR].temporary_hp == 0


@pytest.mark.parametrize("ai", [False, True])
def test_ai_anchor_owner_defends_itself_without_player_prompt(tmp_path, monkeypatch, ai):
    service, table, mid = fight(tmp_path, ai=ai, auto_owner=True)
    before = service._load_session(mid).engine.state
    engine, prompts = push(service, table, mid, ME, ai=ai, monkeypatch=monkeypatch)
    assert not any(p["reaction"] == "Anchor the Link" for p in prompts)
    benefits = [e for e in engine.events if e.event_type == "REACTION_RESOLVED" and e.source_definition_id == ANCHOR]
    assert benefits and all(e.target_ids == (ME,) for e in benefits)
    assert all(e.payload["distance_before"] == 5 and e.payload["distance_after"] == 0 for e in benefits)
    assert engine.state.actors[ME].position == before.actors[ME].position
    assert engine.state.actors[ME].resources["resource:core.qi"] == before.actors[ME].resources["resource:core.qi"] - 1


def test_own_source_response_retains_its_offensive_target_contract():
    from tests.test_forced_movement_reactions import _engine, _row, _push, REACTOR, AN
    # Own forced-moved responses can mark/retaliate against the pusher;
    # defensive ally rows (including self) opt into the new recipient contract.
    row = _row("forced_moved", effects=[{"type": "temp_hp", "flat": 3, "applies_to": "target"}])
    engine = _engine([row])
    _push(engine, REACTOR, 5)
    assert engine.state.actors[AN].temporary_hp == 3
    assert engine.state.actors[REACTOR].temporary_hp == 0

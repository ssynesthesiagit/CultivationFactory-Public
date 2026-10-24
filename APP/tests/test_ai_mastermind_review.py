"""Synthetic regressions for AIUP2F2: truthful goals and bounded preparation."""
from types import SimpleNamespace as NS

from combat import ai_lookahead, ai_plays, flight_decision
from combat.gate2_runtime_models import Position


def situation(*, offered=True, strike=True):
    actor = NS(entity_id="self", current_hp=20, maximum_hp=100, temporary_hp=0,
               position=Position(x=0, y=0))
    foe = NS(entity_id="foe", position=Position(x=2, y=0), current_hp=100,
             maximum_hp=100, reaction_available=False, concentration_source_id=None)
    action = {"control": 10, "damage": 15, "costs": [], "ready": True}
    candidate = NS(candidate_id="attack", source_definition_id="strike",
                   kind="ACTION", target_ids=("foe",), destination=None,
                   metadata={}, movement_cost_ft=0)
    context = NS(tactics={"actions": {"strike": action}, "located_hostiles": ["foe"]},
                 legal_candidates=(candidate,) if offered else (), recent_events=(),
                 policy=NS(weights={}), actors=(actor, foe), search_move_candidate_id=None)
    plan = NS(actor=actor, foes=[foe], allies=[], has_strike=strike,
              attack_range=60, focus=foe, range_error=lambda p: 0)
    return ai_plays.Situation(context, plan=plan), candidate


def test_unoffered_catalogue_control_is_not_a_play_precondition():
    s, _ = situation(offered=False, strike=False)
    assert not s.facts["control"]
    assert not any(p["id"] == "control_burst" for p in s.proposals(rank=False))


def test_burst_goal_requires_remaining_attack_not_just_control():
    s, _ = situation(strike=False)
    assert s.facts["control"]
    assert not s.facts["followup"]
    assert not any(p["id"] == "control_burst" for p in s.proposals(rank=False))


def test_exhausted_turn_receipt_does_not_invent_a_search():
    s, _ = situation(offered=False, strike=False)
    s.facts = {k: False for k in s.facts}
    plays = s.proposals(rank=False)
    assert all(all(s.facts.get(k) for k in p["requires"]) for p in plays)
    assert plays[0]["id"] == "hold"


def test_goal_fit_accounts_for_own_printed_self_cost():
    base, c = situation()
    ordinary = base.features(c)
    augmented, c = situation()
    c.metadata = {"expected_damage": 22, "self_harm": True, "self_expected_damage": 8}
    result = augmented.features(c)
    assert result["damage"] < ordinary["damage"], "7 extra damage must not hide an 8 HP self cost"


def test_unknown_zone_damage_extensions_keep_their_native_estimate():
    from combat.ai_tactics import _plain_zone_effects
    assert _plain_zone_effects([{"type": "zone", "triggers": [
        {"effects": [{"type": "mark", "mark": "Slowed"}]}]}])
    assert not _plain_zone_effects([{"type": "zone", "triggers": [
        {"effects": [{"type": "damage", "flat": 5}]}]}])
    assert not _plain_zone_effects([{"type": "zone"}, {"type": "unmaking_domain"}])
    assert not _plain_zone_effects([{"type": "zone", "triggers": [
        {"effects": [{"type": "custom_damage_domain"}]}]}])


def test_printed_reaction_denial_is_not_zero_utility():
    normal, c = situation()
    normal.context.tactics["actions"]["strike"]["control"] = 0
    normal.actions["strike"]["control"] = 0
    before = normal.features(c)
    denial, c = situation()
    denial.actions["strike"].update(control=0, reaction_denial=True)
    after = denial.features(c)
    assert before["reaction_control"] == 0
    assert after["reaction_control"] > 0 and after["control"] > before["control"]


def test_native_move_speed_fact_is_call_local_not_per_endpoint():
    from combat.ext.movement_safety import movement_allowed
    from combat.read_queries import candidate_pass
    calls = []
    engine = NS(state=NS(state_version=1, event_sequence=1), action_catalog={},
                _effective_speed=lambda actor: calls.append(actor.position) or 30)
    actor = NS(position=Position(x=0, y=0), turn_flags={})
    candidate = NS(kind=NS(value="MOVE"), destination=Position(x=1, y=0))
    with candidate_pass(engine):
        assert movement_allowed(engine, actor, candidate, None) is None
        assert movement_allowed(engine, actor, candidate, None) is None
        assert len(calls) == 1
        actor.position = Position(x=1, y=0)
        movement_allowed(engine, actor, candidate, None)
        assert len(calls) == 2
        engine.state.event_sequence += 1
        movement_allowed(engine, actor, candidate, None)
        assert len(calls) == 3
    movement_allowed(engine, actor, candidate, None)
    assert len(calls) == 4


def test_expired_belief_preparation_does_not_scan_or_publish_partial_map(monkeypatch):
    from combat import senses
    def forbidden(*args):
        raise AssertionError("No more map preparation after the shared deadline")
    monkeypatch.setattr(senses, "perceives_cell", forbidden)
    engine = NS(grid=NS(width=5, height=5), battlefield_document={"terrain_regions": []})
    assert ai_lookahead.own_snapshot(engine, NS(), deadline=0) is None


def test_expired_flight_routes_keep_unchecked_positions_conservative(monkeypatch):
    from combat import candidate_knowledge
    monkeypatch.setattr(candidate_knowledge, "perceived_ids", lambda _: frozenset())
    def forbidden(*args):
        raise AssertionError("No more native flight projection after the deadline")
    monkeypatch.setattr(flight_decision, "_position_safety", forbidden)
    p, q = Position(x=0, y=0, z=1), Position(x=1, y=0, z=1)
    rows = flight_decision._route_safety(NS(), NS(), [("route", q, (p, q), True)], deadline=0)
    # Unchecked geometry is unevaluated: no proven fall, no proven block.
    assert rows["route"] == {"evaluated": False, "fall_required": False,
                             "path_requires_fall": False, "path_blocked": False}

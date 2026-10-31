"""A post-payment Internal Echo interruption stops the owning Reaction consumer."""
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from combat import typed_reactions
from combat.ext import flowing_river, karma_consumers


@pytest.mark.parametrize("can_continue", [False, True])
def test_native_flowing_response_obeys_payment_interruption(monkeypatch, can_continue):
    engine = SimpleNamespace(action_catalog={"native.attack": SimpleNamespace(reach_ft=5, display_name="Claw")})
    attacker = SimpleNamespace(entity_id="attacker")
    reactor = SimpleNamespace(entity_id="reactor")
    row = {"feature_id": "flowing.response", "effects": [{"type": "flowing_yield_attack", "second_pass": True}]}
    calls = []
    monkeypatch.setattr(flowing_river, "_response_row", lambda *_: row)
    monkeypatch.setattr(flowing_river, "_available", lambda *_: True)
    monkeypatch.setattr(typed_reactions, "_subject_ok", lambda *_: True)
    monkeypatch.setattr(typed_reactions, "declaration_priority_ok", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(typed_reactions, "_consent", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(typed_reactions, "_open", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(typed_reactions, "_spend_generic", lambda *_: can_continue)
    monkeypatch.setattr(typed_reactions, "spend_reaction", lambda *_: calls.append("reaction"))
    monkeypatch.setattr(flowing_river, "_reactor_context", lambda *_: object())
    monkeypatch.setattr(flowing_river, "yield_attack", lambda *_: calls.append("yield"))

    result = flowing_river.native_response_declared(
        engine, attacker, reactor, None, {"source_id": "native.attack"}
    )
    assert calls == (["reaction", "yield"] if can_continue else [])
    assert (result == {}) is can_continue


@pytest.mark.parametrize("can_continue", [False, True])
def test_reversal_does_not_spend_imprint_or_rewrite_roll_after_interruption(monkeypatch, can_continue):
    attacker = SimpleNamespace(entity_id="attacker", team_id="attackers", display_name="Attacker")
    target = SimpleNamespace(team_id="defenders")
    reactor = SimpleNamespace(entity_id="reactor", team_id="defenders", active=True, display_name="Reactor")
    engine = SimpleNamespace(state=SimpleNamespace(actors={"reactor": reactor}), typed_actor_ids={"reactor"})
    row = {"feature_id": "reversal", "natural": [20]}
    calls = []
    monkeypatch.setattr(karma_consumers, "held", lambda *_: True)
    monkeypatch.setattr(karma_consumers, "_rows", lambda *_: [row])
    monkeypatch.setattr(karma_consumers, "_consents_to_payment", lambda *_: True)
    monkeypatch.setattr(karma_consumers, "_pay_accepted", lambda *_: can_continue)
    monkeypatch.setattr(karma_consumers, "spend", lambda *_: calls.append("imprint") or True)
    monkeypatch.setattr(karma_consumers, "note", lambda *_: calls.append("note"))
    monkeypatch.setattr(karma_consumers, "_resolved", lambda *_: calls.append("resolved"))
    monkeypatch.setattr("combat.paid_relocation.activation", lambda *_: nullcontext())

    result = karma_consumers.hit_answer(engine, attacker, target, {}, 25, 20, 15)
    assert calls == (["imprint", "note", "resolved"] if can_continue else [])
    assert (result is not None) is can_continue

"""Synthetic busy action regression for the player-facing summary."""
import re

from test_feed_summary import _feed, _fight_events, render


def test_busy_action_summary_only_reports_outcomes():
    events, rolls = _fight_events()
    events = [e for e in events if e["transaction_id"] == "t2"]
    def add(kind, actor="t", targets=("a",), **payload):
        events.append(dict(sequence=len(events)+100, event_type=kind, actor_id=actor,
                           target_ids=list(targets), source_definition_id="action:test.strike",
                           trigger_or_intent_id="t2", transaction_id="t2", payload=payload))
    add("SAVE_ROLLED", actor="a", targets=(), dc=16, success=False)
    add("CONDITION_REMOVED", condition_id="condition:typed.concentration_held",
        gate3_condition_before={"condition_id": "condition:typed.concentration_held",
                                "data": {"label": "Concentration Held", "history_hidden": True}})
    add("PASSIVE_TRIGGERED", text="Test weapon breaks (it breaks at 3 Crack).")
    add("RESOURCE_GAINED", actor="a", targets=(), resource_id="resource:core.qi", amount=1, remaining=3)
    add("ATTACK_ROLLED", actor="a", targets=("t",), provisional_hit=True)
    add("DAMAGE_COMMITTED", actor="a", targets=("t",), hp_damage=3, damage_type="force", remaining_hp=10)
    rows = _feed(events, rolls)
    entries = render([rows], open=True)
    entry = next(e for e in entries if e["text"].startswith("Bram Holt"))
    clauses = [r["brief"]["text"] for r in rows if r["brief"]["kind"] == "clause"]
    message = entry["text"] + "\nclauses: " + str(len(clauses))
    assert not re.search(r"[0-9a-f]{8,}|Typed|Copy\\d+|Unnamed effect", entry["text"], re.I), message
    assert "breaks (it breaks" not in entry["text"], message
    assert any(r["event_type"] == "PASSIVE_TRIGGERED" and r["brief"]["kind"] == "quiet" for r in rows), message

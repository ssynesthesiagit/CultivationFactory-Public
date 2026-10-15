import pytest

from tests.anchor_support import ME, FRIEND, FOE, fight, push


@pytest.mark.parametrize("ai", [False, True])
def test_rescue_prompt_names_actual_mover(tmp_path, monkeypatch, ai):
    service, table, mid = fight(tmp_path, ally=True, ai=ai)
    captured = []
    original = table._reaction_prompt
    def capture(match_id, context, **kwargs):
        captured.append(context)
        # Reproduce the presentation ambiguity: the recent action points to
        # the protector, while the actual movement recipient is the ally.
        # This changes display history only, never engine state or rolls.
        recent = list(context.get("recent_events") or [])
        action = next((e for e in reversed(recent) if e.get("event_type") == "ATTACK_ROLLED"), {})
        decoy = {**action, "event_type": "ATTACK_ROLLED", "actor_id": FOE, "target_ids": [ME]}
        return original(match_id, {**context, "recent_events": [*recent, decoy]}, **kwargs)
    monkeypatch.setattr(table, "_reaction_prompt", capture)
    _engine, prompts = push(service, table, mid, FRIEND, ai=ai, monkeypatch=monkeypatch)
    prompt = next(p for p in prompts if p["reaction"] == "Anchor the Link")
    assert "Traveler is being moved" in prompt["trigger"]
    assert "Pusher" in prompt["trigger"] and "Wind Lash" in prompt["trigger"]
    assert "Protector is being moved" not in prompt["trigger"]
    context = next(c for c in captured if c["reaction_source_id"].endswith("TAL_CHAINS_ANCHOR_LINK_BASE"))
    assert context["choice_trigger"]["affected_id"] == FRIEND

"""Table proofs for the round17 damage checkpoint requalification.

The fixture hook asks a diagnostic choice, not Dissonant Pulse. It establishes
which existing transport contracts work without implementing a partial rider.
Only hook registries are scoped by pytest; no combat method is replaced.
"""
import pytest

from combat import ext
from combat.ext.needle import ask, checkpoint_id
from tests.test_r5i_integration import (
    OTHER, PLAYER, act, answer, check_reload, fixture, pin_ai, turn,
)

BELL = "TAL_SOUND_MOUNTAIN_CRACKING_BELL"
COURT = "TAL_SOUND_COURT_OF_THE_WORLD_RINGING_BELL"
PULSE = "TAL_SOUND_DISSONANT_PULSE"


def diagnostic_choice(monkeypatch):
    """Observe committed damage and use the documented choice transport."""
    seen = []
    ext.effects()

    def observe(engine, event_type, kwargs):
        if event_type != "DAMAGE_COMMITTED" or kwargs.get("actor_id") != PLAYER:
            return
        event = engine.events[-1]
        if not any(feature in event.source_definition_id for feature in (BELL, COURT)):
            return
        intent = engine._active_intent
        target = engine.state.actors[event.target_ids[0]]
        seen.append((intent, event.source_definition_id, dict(event.payload)))
        assert intent is not None
        ask(engine, intent, checkpoint_id(engine, "r5i_damage_audit", event.source_definition_id),
            engine.state.actors[PLAYER], "choice:needle.r5i_damage_audit", [target.entity_id],
            minimum=0, maximum=1, allow_decline=True, automatic=False, default="decline",
            target_id=target.entity_id, labels={target.entity_id: target.display_name},
            name="Damage contract audit", feature_id="test:r5i_damage_audit",
            prompt=f"Damage contract audit: {event.source_definition_id} damaged {target.display_name}.")

    monkeypatch.setitem(ext._HOOKS, "event", [*ext._HOOKS.get("event", []), observe])
    return seen


@pytest.mark.parametrize("dc", [1, 50])
@pytest.mark.parametrize("selection", ["USE", "DECLINE"])
def test_committed_save_damage_can_pause_and_replay_at_table(tmp_path, monkeypatch, dc, selection):
    def configure(bundle, other):
        for row in bundle["action_catalog"]:
            typed = row["parameters"].get("typed", {})
            if typed.get("source") == BELL:
                typed["numbers"]["save_dc"] = dc

    from combat.gate2_runtime_content import AN
    combat, table, mid = fixture(tmp_path, [BELL, PULSE], configure=configure,
        positions={PLAYER: {"x": 3, "y": 6}, OTHER: {"x": 4, "y": 6}, AN: {"x": 14, "y": 2}})
    turn(table, mid, PLAYER)
    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    position = combat._load_session(mid).engine.state.actors[OTHER].position
    cid = next(c.candidate_id for c in combat._load_session(mid).engine.legal_candidates()
               if c.display_name.startswith("Mountain-Cracking Bell") and c.destination == position)
    seen = diagnostic_choice(monkeypatch)
    result = act(table, mid, cid)
    assert result["status"] == "REACTION_REQUIRED"
    assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
    # Accepting and declining the fixture choice never charge a Reaction.
    answers = []
    # Owner 2026-10-01: this unrestricted area can damage its caster too.
    # Each affected creature has its own diagnostic checkpoint.
    while result['status'] == 'REACTION_REQUIRED':
        assert result['reaction']['context']['reaction_source_id'] == 'choice:needle.r5i_damage_audit'
        target = result['reaction']['choice']['options'][0]['id']
        answers.append(answer(result, selection=selection, options=[target] if selection == 'USE' else []))
        result = act(table, mid, cid, answers)
    assert result['status'] == 'COMMITTED'
    engine = check_reload(combat, mid, tmp_path)
    assert engine.state.actors[OTHER].current_hp < before["actors"][OTHER]["current_hp"]
    assert engine.state.actors[PLAYER].reaction_available
    assert seen and all(intent.candidate_id == cid for intent, _, _ in seen)
    assert all(payload["reduced_to"] > 0 for _, _, payload in seen)


@pytest.mark.parametrize("auto_turn", [False, True])
def test_zone_damage_checkpoint_retains_boundary_answers(tmp_path, monkeypatch, auto_turn):
    combat, table, mid = fixture(tmp_path, [COURT, PULSE])
    turn(table, mid, PLAYER)
    engine = combat._load_session(mid).engine
    order = list(engine.state.initiative_order)
    index = order.index(PLAYER)
    advancing, victim = order[(index + 1) % 3], order[(index + 2) % 3]
    cid = next(c.candidate_id for c in engine.legal_candidates()
               if c.display_name == "Court of the World-Ringing Bell: Ringing Court")
    assert act(table, mid, cid)["status"] == "COMMITTED"
    boundary = table.state(mid)["menu"]["end_turn"]
    result = act(table, mid, boundary)
    answers = []
    while result["status"] == "REACTION_REQUIRED":
        answers.append(answer(result, selection="DECLINE"))
        result = act(table, mid, boundary, answers)
    assert result["status"] == "COMMITTED"
    assert table.state(mid)["menu"]["actor_id"] == advancing
    cid = table.state(mid)["menu"]["end_turn"]
    seen = diagnostic_choice(monkeypatch)
    if auto_turn:
        pin_ai(combat, mid, advancing, cid)
    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    send = lambda answers=(): table.auto_step(mid, 0, list(answers)) if auto_turn else act(table, mid, cid, answers)
    result = send()
    answers = []
    while result["status"] == "REACTION_REQUIRED" and result["reaction"]["context"]["reaction_source_id"] != "choice:needle.r5i_damage_audit":
        answers.append(answer(result, selection="DECLINE"))
        result = send(answers)
    assert result["status"] == "REACTION_REQUIRED"
    assert result["reaction"]["context"]["reactor_id"] == PLAYER
    assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
    assert send([*answers, answer(result, selection="DECLINE")])["status"] == "COMMITTED"
    engine = check_reload(combat, mid, tmp_path)
    assert engine.state.current_actor_id == victim
    assert engine.state.actors[victim].current_hp < before["actors"][victim]["current_hp"]
    assert seen and all(intent.actor_id == advancing and intent.candidate_id == cid for intent, _, _ in seen)

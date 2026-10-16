"""Echoes: native Sound reactions after a same-round own-turn step.

Only the trigger is staged inside Hold's accepted table transaction. Bell-Shell
eligibility, payment, reroll/reduction, completion, choices, movement and replay
use their native implementations. No live model or embedding transport is used.
"""
import pytest

from combat.canonical import canonical_sha256
from combat.gate4_engine import Gate4ControllerEngine
from tests.h1_support import force_save, script
from tests.worker2_support import OWNER, ALLY, FOE, fixture, reload, settle, turn

FIELD = "TAL_SOUND_TEN_THOUSAND_ECHOES_FIELD"
BELL = "TAL_SOUND_BELL_SHELL_GUARD"
STEP = "choice:needle.echoes_step"


def _initiative(bundles):
    for bundle, bonus in zip(bundles, (200, 100, 0)):
        bundle["actor_template"]["initiative_bonus"] = bonus
        bundle.pop("bundle_sha256", None)
        bundle["bundle_sha256"] = canonical_sha256(bundle)


def _named(engine, name):
    return next(c for c in engine.legal_candidates()
                if c.display_name.split(" at ")[0] == name)


@pytest.mark.parametrize("mode,accept,trigger", [
    ("MANUAL", True, "reroll"),
    ("MANUAL", False, "reroll"),
    ("LOCAL_AUTO", True, "reroll"),
    ("MANUAL", True, "damage"),
])
def test_sound_reaction_step_uses_actual_turn_and_survives_reload(
        tmp_path, monkeypatch, mode, accept, trigger):
    combat, table, mid = fixture(
        tmp_path, [FIELD],
        ally_talents=[BELL, "TAL_SOUND_DAMPEN_SOUND", "TAL_SOUND_MUFFLE_FOOTFALL"],
        bundle_transform=_initiative, owner_dc=50, named=True,
        ally_position={"x": 5, "y": 6}, foe_position={"x": 8, "y": 8},
        seed="A2R04-REACTION-COMPLETION")
    settle(table, mid, _named(reload(tmp_path, mid), "Ten-Thousand Echoes Field").candidate_id)
    turn(table, mid, ALLY)
    for index, name in enumerate(("Dampen Sound", "Muffle Footfall")):
        engine = reload(tmp_path, mid)
        prompts = settle(table, mid, _named(engine, name).candidate_id,
                         picks={STEP: "step:4,6"})
        assert sum(p["context"]["reaction_source_id"] == STEP for p in prompts) == (index == 0)
    engine = reload(tmp_path, mid)
    own_turn_key = engine.state.actors[ALLY].turn_flags["echoes_step_round_"]
    own_round = engine.state.round_number
    own_turns = engine.state.actors[ALLY].turns_started
    assert (engine.state.actors[ALLY].position.x, engine.state.actors[ALLY].position.y) == (4, 6)
    turn(table, mid, FOE)
    if mode != "MANUAL":
        combat.set_controller_mode(mid, actor_id=ALLY, controller_mode=mode)
    engine = reload(tmp_path, mid)
    assert engine.state.round_number == own_round
    assert engine.state.current_actor_id == FOE
    assert engine.state.actors[ALLY].turns_started == own_turns
    assert engine.state.actors[ALLY].turn_flags["echoes_step_round_"] == own_turn_key
    assert BELL not in engine.action_catalog  # reaction source is a printed ID
    before = engine.state.actors[ALLY].position
    resources = dict(engine.state.actors[ALLY].resources)
    sequence = engine.state.event_sequence

    original = Gate4ControllerEngine._append_event

    def on_hold(live, event_type, *args, **kwargs):
        event = original(live, event_type, *args, **kwargs)
        if event_type == "HOLD_POSITION_COMMITTED":
            if trigger == "reroll":
                script(live, [1, 20])
                force_save(live, OWNER, "CON", dc=12, typed=True,
                           condition="deafened", forcer=FOE)
            else:
                # Damage without an intent deliberately skips reaction windows
                # (costs/environmental packets). Stage an incoming attack in
                # this accepted Hold transaction so Bell-Shell can answer it.
                assert live._active_intent is not None
                live._commit_damage(live.state.actors[OWNER], 20, "THUNDER",
                                    "test:thunder", FOE, live._active_intent,
                                    reaction_depth=0)
        return event

    monkeypatch.setattr(Gate4ControllerEngine, "_append_event", on_hold)
    prompts = settle(table, mid, _named(engine, "Hold position").candidate_id,
                     picks={"reaction:typed." + BELL: "first",
                            STEP: "step:5,6" if accept else None})
    engine = reload(tmp_path, mid)
    ally = engine.state.actors[ALLY]
    recent = [e for e in engine.events if e.sequence > sequence]
    if trigger == "reroll":
        assert any(e.event_type == "D20_REWRITTEN" and e.source_definition_id == BELL for e in recent)
        assert not any("deafened" in c.condition_id for c in engine.state.actors[OWNER].conditions.values())
    else:
        assert any(e.event_type == "REACTION_RESOLVED" and e.source_definition_id == BELL for e in recent)
    assert not ally.reaction_available
    assert sum(resources.values()) - sum(ally.resources.values()) == 1
    choices = [p for p in prompts if p["context"]["reaction_source_id"] == STEP]
    if mode == "MANUAL":
        assert len(choices) == 1
        assert choices[0]["context"]["reactor_id"] == ALLY
        assert "Bell-Shell Guard" in str(choices[0])
        assert "Tobin" in str(choices[0])
    else:
        assert not choices  # AI resolves its own choice, without a human prompt
    distance = engine.grid.distance_ft(before, ally.position)
    assert distance == (5 if accept else 0)
    assert (ally.turn_flags["echoes_step_round_"] != own_turn_key) is accept
    if accept:
        foe = engine.state.actors[FOE]
        assert ally.turn_flags["echoes_step_round_"] == f"{own_round}:{FOE}:{foe.turns_started}"
        completed = next(e for e in recent if e.source_definition_id == BELL and
                         (e.event_type == "REACTION_RESOLVED" if trigger == "damage" else
                          e.event_type == "PASSIVE_TRIGGERED" and "saving throw" in str(e.payload)))
        moved = next(e for e in recent if e.event_type == "MOVEMENT_COMMITTED" and e.actor_id == ALLY)
        assert completed.sequence < moved.sequence
    assert not any(e.source_definition_id == "system:combat.opportunity_attack" for e in recent)

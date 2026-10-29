"""Echoes: native Sound reactions after a same-round own-turn step.

Only the trigger is staged inside Hold's accepted table transaction. Bell-Shell
eligibility, payment, reroll/reduction, completion, choices, movement and replay
use their native implementations. No live model or embedding transport is used.
"""
import copy
import json

import pytest

from combat.canonical import canonical_sha256
from combat.gate4_engine import Gate4ControllerEngine
from tests.h1_support import ROOT, force_save, script
from tests.worker2_support import OWNER, ALLY, FOE, fixture, reload, settle, turn

FIELD = "TAL_SOUND_TEN_THOUSAND_ECHOES_FIELD"
BELL = "TAL_SOUND_BELL_SHELL_GUARD"
STEP = "choice:needle.echoes_step"
BELL_TRIGGER = ("You or one ally within 30 feet takes Thunder damage, is Deafened, or fails a "
                "Concentration saving throw caused by sound, voice, thunder, or vibration")


@pytest.fixture(autouse=True)
def pinned_printed_bell_trigger(monkeypatch):
    """Compile Bell-Shell Guard from its printed trigger even where the public export scrambled it.

    A Reaction's kind is read from the printed trigger sentence at compile time
    (combat/factory_compiler.py; combat/reaction_triggers.py). The public test export replaces every long
    printed sentence in the authority data with deterministic pseudo-words, so a public run would compile
    Bell-Shell Guard as an unsupported trigger and this reaction-driven step would never reach the prompt
    it asserts. Pinning the rule's own sentence restores nothing else: on a private run the file already
    says exactly this, so the original authority object is returned untouched, and every other field of
    the mechanic stays the shipped data. Same pattern as tests/test_body_refining_choices.py.
    """
    from combat import factory_compiler

    original = factory_compiler._read_compilation_authority

    def read(path):
        authority, sha256 = original(path)
        row = (authority.get("mechanics") or {}).get(BELL)
        if not row or (row.get("activation") or {}).get("trigger") == BELL_TRIGGER:
            return authority, sha256
        mechanics = copy.deepcopy(authority["mechanics"])
        mechanics[BELL].setdefault("activation", {})["trigger"] = BELL_TRIGGER
        return {**authority, "mechanics": mechanics}, sha256

    monkeypatch.setattr(factory_compiler, "_read_compilation_authority", read)


@pytest.fixture(scope="module", autouse=True)
def shipped_sound_reaction_inputs():
    # The authority builder enumerates reviewed_final.d dynamically, so an
    # isolated public-CI export cannot infer these inputs from imports. Name
    # the real shipped rows: without them the Field and Bell-Shell reactions
    # do not exist in the exported fight and every case fails before the code
    # under test runs. Never replace them with synthetic ownership.
    sound = json.loads((ROOT / "authority/typed_mechanics/reviewed_final.d/auto16_sound.json").read_text())
    assert FIELD in sound["mechanics"]
    smoke = json.loads((ROOT / "authority/typed_mechanics/reviewed_final.d/review_sw-smoke.json").read_text())
    assert BELL in smoke["mechanics"]


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
                # typed_executor records the incoming damage type before committing
                # damage (typed_reactions._generic_damage_type_ok reads it). A direct
                # _commit_damage call must record it too, or Thunder-limited rows never fire.
                previous_type = getattr(live, "_typed_pending_damage_type", None)
                live._typed_pending_damage_type = "THUNDER"
                try:
                    live._commit_damage(live.state.actors[OWNER], 20, "THUNDER",
                                        "test:thunder", FOE, live._active_intent,
                                        reaction_depth=0)
                finally:
                    live._typed_pending_damage_type = previous_type
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

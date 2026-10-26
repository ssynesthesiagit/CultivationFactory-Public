"""A2R04 R11: the three review findings, as real table behaviour.

Every case is a real table: a compiled bundle, a submitted intent, the event
log and a cold reload.

  Tremor Listening, "you may use Read the Vibration through that surface ...
  increase the range to 120 feet along the connected surface". The compiled
  action carried 120 feet, but the executor still chose its opponents and its
  recorded evidence at 60 feet, so a movement 90 feet away was invisible. The
  inquiry now reads the range of the action it is running, and evidence beyond
  that range stays out.

  Resonant Note, "the target cannot benefit from ordinary sound-based hiding
  until the start of your next turn". Two implementations of that one printed
  choice existed. There is now one menu option and one held rule, and both
  consumers read it: the native Hide procedure and the opposed hearing-only
  concealment check.

  Forbidden Silence Field, the positionless query. A creature with no square
  is an unknown for the pure path query, not a crash.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from combat import senses, stealth
from combat.ability_checks import SOUND_RELIANCE
from tests.worker2_support import OWNER, ALLY, FOE, fixture, reload, settle, turn

READ = "TAL_SOUND_READ_THE_VIBRATION"
TREMOR = "TAL_SOUND_TREMOR_LISTENING"
NOTE = "TAL_SOUND_RESONANT_NOTE"
HIDING_OPTION = "Resonant Note: Prevent ordinary sound-based hiding"
HIDING = "condition:typed.sound_hiding_block"
OLD_HIDING = "condition:typed.sound_hiding_denied"


def _open_arena(arena):
    """A wide, pillar-free arena: 120 feet of surface has to fit on the map."""
    arena["width_squares"] = 48
    arena["height_squares"] = 20
    arena["terrain_regions"] = []


def _sure_hit(bundles):
    """Make every one of the party's attacks land, so a test never depends on a seeded d20."""
    from combat.canonical import canonical_sha256

    for bundle in bundles:
        for row in bundle["action_catalog"]:
            typed = row["parameters"].get("typed") or {}
            typed.setdefault("numbers", {})["attack_bonus"] = 50
        bundle.pop("bundle_sha256", None)
        bundle["bundle_sha256"] = canonical_sha256(bundle)


def _resonance_on_hold(monkeypatch):
    """Run ``callback(engine, actor_id)`` inside the commit of a Hold Position.

    A trigger the table cannot otherwise stage (a mark another same-turn hit
    already left) is applied inside an accepted action, so its event and
    everything it raises are part of the commit and survive the cold reload
    -- the pattern tests/r10_fixup_support.py ``on_hold`` established.
    """
    from combat.gate4_engine import Gate4ControllerEngine

    def on_hold(callback):
        original = Gate4ControllerEngine._append_event

        def run(engine, event_type, *args, **kwargs):
            result = original(engine, event_type, *args, **kwargs)
            if event_type == "HOLD_POSITION_COMMITTED":
                callback(engine, kwargs.get("actor_id") or engine.state.current_actor_id)
            return result

        monkeypatch.setattr(Gate4ControllerEngine, "_append_event", run)

    return on_hold


def _candidate(engine, name, *, actor=OWNER, target=None):
    rows = [c for c in engine.legal_candidates()
            if c.display_name.split(" at ")[0] == name and c.actor_id == actor
            and (target is None or not c.target_ids or target in c.target_ids)]
    assert rows, f"{name!r} is not legal; legal: {sorted(c.display_name for c in engine.legal_candidates())}"
    return rows[0]


# --------------------------------------------------------------------------------------
# Tremor Listening: the inquiry reaches the range the chosen action prints.
# --------------------------------------------------------------------------------------

def _moved_foe_fight(tmp_path, *, tremor, foe_x):
    """A fight whose foe commits a movement far from the owner.

    The movement is a real committed move on the foe's own turn, so it is in
    the fight's journal and survives the cold reload.
    """
    talents = [READ] + ([TREMOR] if tremor else [])
    _combat, table, mid = fixture(tmp_path, talents,
                                  foe_position={"x": foe_x, "y": 6},
                                  positions={OWNER: {"x": 3, "y": 6},
                                             ALLY: {"x": 4, "y": 6},
                                             FOE: {"x": foe_x, "y": 6}},
                                  seed="A2R04R11", battlefield_transform=_open_arena)
    turn(table, mid, FOE)
    engine = reload(tmp_path, mid)
    move = next(c for c in engine.legal_candidates()
                if c.actor_id == FOE and c.kind == "MOVE" and c.destination is not None
                and (c.destination.x, c.destination.y) == (foe_x, 9))
    settle(table, mid, move.candidate_id)
    turn(table, mid, OWNER)
    return table, mid


def _movement_clue(tmp_path, table, mid, name):
    """Run the inquiry and return the clue the table recorded."""
    engine = reload(tmp_path, mid)
    candidate = _candidate(engine, name)
    settle(table, mid, candidate.candidate_id,
           picks={"choice:needle.vibration_clue": "movement",
                  "choice:needle.vibration_method": "gm_dc",
                  "choice:needle.scene_gm_dc": ("0", "done")})
    engine = reload(tmp_path, mid)
    clues = [e for e in engine.events if e.payload.get("clue") == "movement"]
    assert clues, "the inquiry recorded no clue at all"
    return clues[-1]


def test_tremor_listening_reaches_recorded_movement_beyond_sixty_feet(tmp_path):
    """90 feet of connected surface is inside Tremor Listening's 120 feet.

    The plain action (60 feet) does not reach it; the Tremor Listening
    variant does, after the foe's movement was committed and the fight was
    cold-reloaded.
    """
    plain_table, plain_mid = _moved_foe_fight(tmp_path / "plain", tremor=False, foe_x=21)
    plain = _movement_clue(tmp_path / "plain", plain_table, plain_mid, "Read the Vibration")
    assert not plain.payload["evidence_sequences"], \
        "the 60-foot action must not reach a movement 90 feet away"

    table, mid = _moved_foe_fight(tmp_path / "tremor", tremor=True, foe_x=21)
    clue = _movement_clue(tmp_path / "tremor", table, mid, "Read the Vibration + Tremor Listening")
    assert clue.payload["evidence_sequences"], \
        "Tremor Listening must reach the movement 90 feet away"
    assert "nearby space" in clue.payload["text"]


def test_tremor_listening_does_not_reach_beyond_its_own_range(tmp_path):
    """130 feet is beyond the printed 120 feet, so it stays unknown."""
    table, mid = _moved_foe_fight(tmp_path, tremor=True, foe_x=29)
    clue = _movement_clue(tmp_path, table, mid, "Read the Vibration + Tremor Listening")
    assert not clue.payload["evidence_sequences"], \
        "a movement beyond 120 feet must not be read as nearby"
    assert "unknown" in clue.payload["text"]


# --------------------------------------------------------------------------------------
# Resonant Note: one option, one held rule, both consumers.
# --------------------------------------------------------------------------------------

def _marked_foe_fight(tmp_path, monkeypatch, *, note=True):
    """The owner's Resonant Note has already marked the foe with Resonance.

    The printed rider needs the target to bear the caster's Resonance before
    the hit, so the mark is staged inside the owner's committed Hold Position,
    the way another same-turn hit would leave it.
    """
    talents = [NOTE] if note else []
    _combat, table, mid = fixture(tmp_path, talents, foe_position={"x": 3, "y": 3},
                                  seed="A2R04R11NOTE", bundle_transform=_sure_hit)

    def resonance(engine, actor_id):
        if actor_id != OWNER:
            return
        # The engine's own mark placement records the marker's turn with every
        # marker-token deadline (combat/typed_executor.block_mark); without it
        # the deadline reads as turn zero and the mark is swept before the Note
        # resolves, so the staged mark carries it too.
        engine._apply_condition(engine.state.actors[FOE],
                                "condition:typed.mark.resonance." + OWNER,
                                "test:resonance", OWNER,
                                expires_on="START_OF_MARKER_NEXT_TURN",
                                data={"marker_turn": int(engine.state.actors[OWNER].turns_started)})

    _resonance_on_hold(monkeypatch)(resonance)
    engine = reload(tmp_path, mid)
    hold = next(c for c in engine.legal_candidates() if c.display_name == "Hold position")
    settle(table, mid, hold.candidate_id)
    return table, mid


def test_resonant_note_offers_one_sound_hiding_choice(tmp_path):
    """One printed choice, one menu button, one condition id."""
    _combat, _table, mid = fixture(tmp_path, [NOTE], foe_position={"x": 3, "y": 3},
                                   seed="A2R04R11MENU")
    engine = reload(tmp_path, mid)
    offered = sorted(c.display_name.split(" at ")[0] for c in engine.legal_candidates()
                     if c.actor_id == OWNER and "hiding" in c.display_name.lower())
    assert offered == [HIDING_OPTION]
    compiled = sorted(a.display_name for a in engine.action_catalog.values()
                      if a.owner_id == OWNER and "hiding" in (a.display_name or "").lower())
    assert compiled == [HIDING_OPTION]


def test_the_sound_hiding_option_lands_the_one_held_rule(tmp_path, monkeypatch):
    """The option applies the rider, and only that rider.

    The held rule is the denial both consumers read, and it lasts until the
    start of the caster's next turn.
    """
    table, mid = _marked_foe_fight(tmp_path, monkeypatch)
    engine = reload(tmp_path, mid)
    settle(table, mid, _candidate(engine, HIDING_OPTION, target=FOE).candidate_id)
    engine = reload(tmp_path, mid)
    foe = engine.state.actors[FOE]
    held = [c for c in foe.conditions.values() if c.condition_id == HIDING]
    assert len(held) == 1, "the option must leave exactly one held rule"
    assert held[0].data["rule"] == {"hiding_denied": ["sound_reliance"]}
    assert held[0].expires_on == "START_OF_MARKER_NEXT_TURN"
    assert held[0].data["marker_turn"] == engine.state.actors[OWNER].turns_started
    assert not [c for c in foe.conditions.values() if c.condition_id == OLD_HIDING], \
        "the second implementation of the same printed rider is still applied"
    from combat.typed_executor import condition_rules
    assert any(row.get("hiding_denied") == ["sound_reliance"] for row in condition_rules(foe))


def _hiding_fight(tmp_path, monkeypatch, *, rider):
    """A fight where the foe's own Hide action is about to be resolved.

    The foe bears a sound-qualified Stealth advantage (the shape a muffling
    feature grants), the owner's team cannot see it (a blinded observer
    permits the Hide without granting any special sense), and -- when the
    rider is wanted -- the Resonant Note's sound-hiding option has just
    landed its held rule.
    """
    table, mid = _marked_foe_fight(tmp_path, monkeypatch, note=rider)
    if rider:
        engine = reload(tmp_path, mid)
        settle(table, mid, _candidate(engine, HIDING_OPTION, target=FOE).candidate_id)

    def stage(engine, actor_id):
        if actor_id != FOE:
            return
        foe = engine.state.actors[FOE]
        engine._apply_condition(foe, "condition:typed.check_mode", "test:sound_advantage", FOE,
                                expires_on="UNTIL_REMOVED",
                                data={"rule": {"check_mode": {"Stealth": "ADVANTAGE"},
                                               "hazards": [SOUND_RELIANCE]}})
        for actor in engine.state.actors.values():
            if actor.team_id != foe.team_id:
                engine._apply_condition(actor, "condition:typed.blinded", "test:blind",
                                        actor.entity_id, expires_on="UNTIL_REMOVED")

    _resonance_on_hold(monkeypatch)(stage)
    turn(table, mid, FOE)
    engine = reload(tmp_path, mid)
    hold = next(c for c in engine.legal_candidates()
                if c.actor_id == FOE and c.display_name == "Hold position")
    settle(table, mid, hold.candidate_id)
    return table, mid


def _foe_hide_mode(tmp_path, table, mid):
    """Resolve the foe's own Hide action and return the mode of its check."""
    engine = reload(tmp_path, mid)
    before = engine.state.event_sequence
    action = next(c for c in engine.legal_candidates()
                  if c.actor_id == FOE and c.display_name == "Hide")
    settle(table, mid, action.candidate_id)
    engine = reload(tmp_path, mid)
    event = next(e for e in engine.events if e.sequence > before and e.event_type == "CHECK_ROLLED"
                 and e.actor_id == FOE and e.payload.get("check") == "Stealth")
    return event.payload["actor"]["mode"], engine


def test_the_sound_hiding_option_denies_the_native_hide_advantage(tmp_path, monkeypatch):
    """The native Hide procedure reads the held rule.

    The foe's sound-qualified Stealth advantage is dropped while the rule is
    held, because the target cannot benefit from ordinary sound-based hiding;
    without the rule the same advantage stands.
    """
    table, mid = _hiding_fight(tmp_path / "rider", monkeypatch, rider=True)
    mode, engine = _foe_hide_mode(tmp_path / "rider", table, mid)
    assert mode == "NORMAL", "the sound-qualified advantage survived the held rule"


def test_without_the_rider_the_native_hide_keeps_its_sound_qualified_advantage(tmp_path, monkeypatch):
    """The control: the same Hide keeps the advantage when no rule is held."""
    table, mid = _hiding_fight(tmp_path / "plain", monkeypatch, rider=False)
    mode, engine = _foe_hide_mode(tmp_path / "plain", table, mid)
    assert mode == "ADVANTAGE"


def test_the_sound_hiding_option_denies_the_hearing_only_concealment_check(tmp_path, monkeypatch):
    """The opposed sound-concealment procedure reads the held rule.

    A target that cannot benefit from ordinary sound-based hiding cannot win
    the ordinary hearing-only concealment check it would use against a
    listener that can hear it. The check is the one Read the Vibration
    contests, so the contested procedure is exercised the same way.
    """
    table, mid = _marked_foe_fight(tmp_path, monkeypatch)
    engine = reload(tmp_path, mid)
    candidate = _candidate(engine, HIDING_OPTION, target=FOE)
    settle(table, mid, candidate.candidate_id)
    engine = reload(tmp_path, mid)

    from combat import typed_executor

    owner = engine.state.actors[OWNER]
    foe = engine.state.actors[FOE]
    action = engine.action_catalog[candidate.source_definition_id]
    ctx = typed_executor.Context(engine, owner, action, None, action.parameters["typed"], [foe], foe)
    metadata = {"source_actor_id": foe.entity_id, "observer_id": OWNER,
                "senses": ["hearing"], "purpose": "conceal_sound", "ordinary": 1}
    result = typed_executor.resolve_opposed_check(
        ctx, foe,
        {"kind": "cultivation", "label": "Sound Check",
         "metadata": {"source_actor_id": foe.entity_id, "observer_id": OWNER,
                      "senses": ["hearing"], "purpose": "read_vibration",
                      "method": "stealth", "inquiry": "movement"}},
        {"kind": "check", "ability": "DEX", "skill": "Stealth", "metadata": metadata})
    assert result.outcome_override is True, \
        "the hearing-only concealment check was not denied"


# --------------------------------------------------------------------------------------
# Forbidden Silence Field: the positionless query answers before any geometry.
# --------------------------------------------------------------------------------------

def test_the_silence_field_query_answers_none_for_a_positionless_creature(tmp_path):
    """A creature with no square is an unknown for the pure path query.

    The check comes before the containment and geometry queries, because both
    need a real square to ask about: a creature that lost its position inside
    the Field is still an unknown, not a crash.
    """
    from combat.ext.smoke_sound_residual import silence_field_path

    _combat, table, mid = fixture(tmp_path, ["TAL_SOUND_FORBIDDEN_SILENCE_FIELD"],
                                  positions={OWNER: {"x": 3, "y": 6}, ALLY: {"x": 0, "y": 6},
                                             FOE: {"x": 11, "y": 6}}, seed="A2R04R11SILENCE")
    engine = reload(tmp_path, mid)
    candidate = next(c for c in engine.legal_candidates()
                     if c.display_name.split(" at ")[0] == "Forbidden Silence Field"
                     and c.destination is not None
                     and (c.destination.x, c.destination.y) == (5, 6))
    settle(table, mid, candidate.candidate_id)
    engine = reload(tmp_path, mid)
    actors = engine.state.actors
    # Control: both creatures have squares, and the Field blocks the crossing.
    assert silence_field_path(engine, actors[OWNER], actors[FOE], "test:sound") is False
    # The owner stands inside the Field and no longer has a square. The
    # model's own field is a square, so the query is asked about a copy that
    # has lost it.
    owner = actors[OWNER].model_copy(update={"position": None})
    assert silence_field_path(engine, owner, actors[FOE], "test:sound") is None
    assert silence_field_path(engine, actors[FOE], owner, "test:sound") is None

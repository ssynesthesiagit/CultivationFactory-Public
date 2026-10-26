"""A2R04: the printed Smoke and Sound residual lines a fight now resolves (2026-10-13).

Each case is a fight-level check on a real CombatService table -- a compiled
bundle, a submitted intent, the event log, and a cold reload -- of a line the
owner's printed text states and the table used to leave to the GM or a rider:

  Resonant Note "If the target already bears your Resonance, choose one rider on
                 a hit: ... the target cannot benefit from ordinary sound-based
                 hiding until the start of your next turn."  (the rider did
                 nothing: ``sound_hiding_denied`` had no executor)
  Ten-Thousand Echoes Field "A creature that fails the save ... must choose
                 either lose its Reaction until the start of its next turn or
                 treat all spaces more than 30 feet away as lightly obscured by
                 echo confusion until the start of its next turn."  (the
                 ``echoes_save_choice`` rider had no executor)
  Ten-Thousand Echoes Field "Allies inside: may move 5 feet without provoking
                 opportunity attacks after using a Sound talent, once per turn."
                 (the deferred movement never fired for an ally's own talent)
  Smoke Mirror Trail "When one creature inside your Smoke Veil becomes
                 Invisible, successfully Hides, teleports, or leaves the veil
                 without using normal movement, you may place a Smoke Trace on
                 it without using your once-per-round Smoke Trace. Until that
                 trace ends, you know the direction to the target while it
                 remains within 120 feet."  (no trigger ever placed the trace)
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from combat.gate2_runtime_models import ActionIntent, Position
from combat.typed_executor import bears_mark, condition_rules, mark_condition_id
from tests.h1_support import sheet
from tests.worker2_support import OWNER, ALLY, FOE, act, fixture, reload, settle, turn

SOUND = "tianxia.sphere.sound"
SMOKE = "tianxia.sphere.smoke"
NOTE = "TAL_SOUND_RESONANT_NOTE"
ECHOES = "TAL_SOUND_TEN_THOUSAND_ECHOES_FIELD"
SILENCE_FIELD = "TAL_SOUND_FORBIDDEN_SILENCE_FIELD"
MUFFLE = "TAL_SOUND_MUFFLE_FOOTFALL"
VIBRATION = "TAL_SOUND_READ_THE_VIBRATION"
MIRROR = "TAL_SMOKE_SMOKE_MIRROR_TRAIL"
LIAR = "TAL_SMOKE_THE_SMOKE_KNOWS_WHO_LIED"
VEIL = "SMOKE_BASE_SMOKE_VEIL"
TRACE = "SMOKE_BASE_SMOKE_TRACE"
FAIL = 50  # technique save DC that makes the foe fail every save
HIDING = "condition:typed.sound_hiding_denied"
DENIED = "condition:typed.sound_hiding_denied"
# Explicit shipped data input for the public-CI dependency closure; the
# compiler's directory enumeration cannot be inferred from Python imports.
SMOKE_FEATURE_BLOCKS = "combat/rules/feature_blocks.d/auto43_smoke.json"
SOUND_FIELD_DATA = "combat/rules/sound_field.json"


def test_sound_field_channels_are_classified_from_printed_text():
    """The Field's own-Sound channel list is typed data, and each entry quotes its printed words.

    A talent is admissible inside the Field only when its own text names silent vibration, contact
    resonance, soul-sound, or a special feature, so the classification must say which and why;
    Muffle Footfall's text names none of them, which is why the Field stops it."""
    import json

    rules = json.loads((Path(__file__).resolve().parents[1] / SOUND_FIELD_DATA).read_text(encoding="utf-8"))
    channels = rules["silent_channels"]
    assert channels["TAL_SOUND_READ_THE_VIBRATION"]["channel"] == "contact resonance"
    assert "Muffle Footfall" not in {row["name"] for row in channels.values()}
    assert {row["channel"] for row in channels.values()} <= {
        "silent vibration", "contact resonance", "soul-sound", "a special feature"}
    assert all(row.get("why") for row in channels.values()), "every exception quotes its printed words"


def _mark(engine, target, name, owner, *, expires_on="UNTIL_REMOVED"):
    """The target already bears ``owner``'s ``name`` mark."""
    engine._apply_condition(target, mark_condition_id(name, owner), "test:mark", owner,
                            expires_on=expires_on)


def _candidate(engine, name, *, target=None):
    rows = [c for c in engine.legal_candidates()
            if c.display_name.split(" at ")[0] == name and c.actor_id == OWNER
            and (target is None or not c.target_ids or target in c.target_ids)]
    assert rows, f"{name!r} is not legal; legal: {sorted(c.display_name for c in engine.legal_candidates())}"
    return rows[0]


def _sure_hit(bundles):
    """Make every one of the party's attacks land, so a test never
    depends on a seeded d20."""
    from combat.canonical import canonical_sha256

    for bundle in bundles:
        for row in bundle["action_catalog"]:
            typed = row["parameters"].get("typed") or {}
            typed.setdefault("numbers", {})["attack_bonus"] = 50
        bundle.pop("bundle_sha256", None)
        bundle["bundle_sha256"] = canonical_sha256(bundle)


def _resonance_on_hold(monkeypatch):
    """Run ``callback(engine)`` inside the commit of the actor's Hold Position.

    A synthetic trigger the table cannot otherwise stage (a mark another
    same-turn hit already left) is applied inside an accepted action, so
    its event and everything it raises are part of the commit and survive
    the cold reload -- the pattern tests/r10_fixup_support.py ``on_hold``
    established.
    """
    from combat.gate4_engine import Gate4ControllerEngine

    def on_hold(callback):
        original = Gate4ControllerEngine._append_event

        def run(engine, event_type, *args, **kwargs):
            result = original(engine, event_type, *args, **kwargs)
            if event_type == "HOLD_POSITION_COMMITTED":
                callback(engine)
            return result

        monkeypatch.setattr(Gate4ControllerEngine, "_append_event", run)

    return on_hold


def test_resonant_note_sound_hiding_rider_denies_sound_stealth(tmp_path, monkeypatch):
    """The rider lands a denial of sound-only hiding until the caster's next turn.

    The rider only fires when the target already bears the caster's
    Resonance -- the mark a Resonant Note hit leaves for the rest of the
    caster's turn -- so the fight places that mark first (inside a committed
    Hold Position, the way another same-turn hit would) and then hits with
    the Sound Hiding rider while it holds."""
    combat, table, mid = fixture(tmp_path, [NOTE], owner_dc=FAIL,
                                 foe_position={"x": 3, "y": 3}, seed="A2R04RN",
                                 bundle_transform=_sure_hit)
    engine = reload(tmp_path, mid)

    def resonance(engine):
        # the target already bears the caster's Resonance
        engine._apply_condition(engine.state.actors[FOE],
                                mark_condition_id("Resonance", OWNER),
                                "test:resonance", OWNER,
                                expires_on="START_OF_SOURCE_NEXT_TURN")

    _resonance_on_hold(monkeypatch)(resonance)
    hold = next(c for c in engine.legal_candidates()
                if c.display_name == "Hold position")
    settle(table, mid, hold.candidate_id)
    engine = reload(tmp_path, mid)
    assert bears_mark(engine.state.actors[FOE], OWNER, "Resonance"), \
        "the pre-placed Resonance did not hold"
    # the Sound Hiding rider fires on the hit: the already-marked foe
    # is denied sound-based hiding
    prompts = settle(table, mid, _candidate(engine, "Resonant Note: Sound Hiding", target=FOE).candidate_id)
    engine = reload(tmp_path, mid)
    foe = engine.state.actors[FOE]
    rider = [c for c in foe.conditions.values()
             if c.condition_id == HIDING
             and (c.data or {}).get("rule", {}).get("hiding_denied") == ["sound_reliance"]]
    assert rider, "the sound-hiding rider did not land a condition"
    assert rider[0].expires_on == "START_OF_SOURCE_NEXT_TURN"
    # The persisted rule is a denial, not an unrelated check penalty.
    modes = condition_rules(foe)
    assert any(row.get("hiding_denied") == ["sound_reliance"] for row in modes)


def _echoes_fixture(tmp_path):
    """The owner's Ten-Thousand Echoes Field is up and the foe starts its turn inside."""
    combat, table, mid = fixture(tmp_path, [ECHOES], owner_dc=FAIL,
                                 foe_position={"x": 6, "y": 6}, seed="A2R04ECHO")
    engine = reload(tmp_path, mid)
    # the Field is a self-centered area; cast it on the owner's own square
    prompts = settle(table, mid, _candidate(engine, "Ten-Thousand Echoes Field").candidate_id)
    return combat, table, mid


def _foe_turn(table, mid, choice):
    """Advance to the foe's turn, answering its failed-save choice."""
    answers = []
    for _ in range(24):
        menu = table.state(mid)["menu"]
        if menu["actor_id"] == FOE:
            return
        result = act(table, mid, menu["end_turn"], answers)
        if result["status"] == "REACTION_REQUIRED":
            p = result["reaction"]
            context = p["context"]
            rid = context["reaction_source_id"]
            options = (p.get("choice") or {}).get("options") or []
            pick = None
            if rid == "choice:needle.echoes_save_choice" and context["checkpoint"].endswith(":" + FOE):
                pick = choice
            answer = {**context, "selection": "USE" if pick else ("USE" if options else "DECLINE")}
            if pick:
                answer["option_ids"] = [pick]
            elif options:
                answer["option_ids"] = [options[0]["id"]]
            answers.append(answer)
            continue
        assert result["status"] == "COMMITTED", result
    raise AssertionError("Never reached the foe's turn")


@pytest.mark.parametrize("choice,condition_id", [
    ("lose_reaction", "condition:typed.reaction_denied"),
    ("echo_confusion", "condition:typed.echo_confusion"),
])
def test_ten_thousand_echoes_failed_save_offers_the_printed_choice(tmp_path, choice, condition_id):
    """The creature that fails the Field's save is offered the two printed
    outcomes, and the one it picks lands as a real condition that expires
    at the start of its next turn."""
    combat, table, mid = _echoes_fixture(tmp_path)
    _foe_turn(table, mid, choice)
    engine = reload(tmp_path, mid)
    foe = engine.state.actors[FOE]
    landed = [c for c in foe.conditions.values() if c.condition_id == condition_id]
    assert landed, f"the {choice!r} outcome did not land a condition"
    from combat.ext.effect_durations import holder_next_turn
    assert landed[0].expires_on == holder_next_turn(foe)
    if condition_id == "condition:typed.reaction_denied":
        # the typed no-Reactions condition really silences the creature
        assert foe.reaction_available is False
    else:
        # The committed typed state drives the existing target-specific Search
        # mode seam: beyond 30 feet is lightly obscured, while a space exactly
        # 30 feet away is not.
        assert (landed[0].data or {}).get("obscured_beyond_ft") == 30
        from combat import stealth
        from combat.ext.smoke_sound_residual import echoes_search_mode

        ally = engine.state.actors[ALLY]
        ally.position = Position(x=12, y=6)  # 30 feet from the affected searcher
        near = engine.state.actors[OWNER]
        near.position = Position(x=3, y=6)  # 15 feet away
        assert echoes_search_mode(engine, foe, near) is None
        assert echoes_search_mode(engine, foe, ally) is None  # exactly 30 feet
        # The field separately penalizes every hearing-based Perception check
        # by an enemy inside it; that remains true even inside the 30-foot edge.
        assert "DISADVANTAGE" in stealth.search_modes(engine, foe, near)
        ally.position = Position(x=13, y=6)  # 35 feet: lightly obscured by echoes
        assert echoes_search_mode(engine, foe, ally) == "DISADVANTAGE"
        assert "DISADVANTAGE" in stealth.search_modes(engine, foe, ally)


def test_ten_thousand_echoes_post_sound_step_moves_an_ally(tmp_path):
    """An ally inside the Field that uses a Sound talent is offered the printed
    five-foot step, and the step moves it without provoking opportunity attacks."""
    combat, table, mid = fixture(tmp_path, [ECHOES],
                                 ally_talents=["TAL_SOUND_DAMPEN_SOUND"],
                                 owner_dc=FAIL, foe_position={"x": 6, "y": 6},
                                 ally_position={"x": 5, "y": 6}, seed="A2R04STEP",
                                 bundle_transform=_sure_hit)
    engine = reload(tmp_path, mid)
    # the owner casts the Field so the ally stands inside it
    settle(table, mid, _candidate(engine, "Ten-Thousand Echoes Field").candidate_id)
    engine = reload(tmp_path, mid)
    ally = engine.state.actors[ALLY]
    before = (ally.position.x, ally.position.y)
    # the ally's own turn: it uses a Sound talent (Dampen Sound)
    turn(table, mid, ALLY)
    engine = reload(tmp_path, mid)
    pulse = [c for c in engine.legal_candidates()
             if c.actor_id == ALLY and c.display_name.split(" at ")[0] == "Dampen Sound"]
    assert pulse, f"the ally has no Dampen Sound; legal: {sorted(c.display_name for c in engine.legal_candidates())}"
    # answering the talent commits it and answers the post-sound step it raises
    assert engine.state.actors[FOE].reaction_available
    sequence = engine.state.event_sequence
    prompts = settle(table, mid, pulse[0].candidate_id,
              picks={"choice:needle.echoes_step": "step:4,6"})
    engine = reload(tmp_path, mid)
    ally = engine.state.actors[ALLY]
    after = (ally.position.x, ally.position.y)
    # the offered step moved the ally one five-foot square (the grid's
    # own cell metric: a diagonal square is one five-foot cell here)
    moved_ft = engine.grid.distance_ft(before, after)
    assert moved_ft == 5, f"the post-sound step did not move the ally five feet (moved {moved_ft})"
    assert after == (4, 6)  # leaves the adjacent hostile's five-foot reach
    assert not any(e.sequence > sequence and e.source_definition_id == "system:combat.opportunity_attack"
                   for e in engine.events)
    step = next(p for p in prompts if p["context"]["reaction_source_id"] == "choice:needle.echoes_step")
    assert "Dampen Sound" in str(step)


def test_ten_thousand_echoes_post_sound_step_is_once_per_turn(tmp_path):
    """The step is offered once per turn: a second Sound talent the same
    turn does not raise it again."""
    combat, table, mid = fixture(tmp_path, [ECHOES],
                                 ally_talents=["TAL_SOUND_DAMPEN_SOUND",
                                               "TAL_SOUND_MUFFLE_FOOTFALL"],
                                 owner_dc=FAIL, foe_position={"x": 8, "y": 8},
                                 ally_position={"x": 5, "y": 6}, seed="A2R04STEP2",
                                 bundle_transform=_sure_hit)
    engine = reload(tmp_path, mid)
    settle(table, mid, _candidate(engine, "Ten-Thousand Echoes Field").candidate_id)
    engine = reload(tmp_path, mid)
    ally = engine.state.actors[ALLY]
    before = (ally.position.x, ally.position.y)
    turn(table, mid, ALLY)
    engine = reload(tmp_path, mid)
    # two Sound talents in one turn: only the first raises the step
    for index, name in enumerate(("Dampen Sound", "Muffle Footfall")):
        rows = [c for c in engine.legal_candidates()
                if c.actor_id == ALLY and c.display_name.split(" at ")[0] == name]
        assert rows, f"second same-turn Sound talent {name} must be legal"
        prompts = settle(table, mid, rows[0].candidate_id,
                  picks={"choice:needle.echoes_step": "first"})
        assert sum(p["context"]["reaction_source_id"] == "choice:needle.echoes_step"
                   for p in prompts) == (1 if index == 0 else 0)
        engine = reload(tmp_path, mid)
    ally = engine.state.actors[ALLY]
    after = (ally.position.x, ally.position.y)
    moved_ft = engine.grid.distance_ft(before, after)
    assert moved_ft == 5, f"the ally moved {moved_ft} feet, not one five-foot step"


def _smoke_fixture(tmp_path, *, dense=True, extra=()):
    """The owner's Smoke Veil covers the foe's square."""
    combat, table, mid = fixture(tmp_path, [VEIL, TRACE, MIRROR,
                                         *(["TAL_SMOKE_DENSE_VEIL"] if dense else []), *extra], owner_dc=FAIL,
                                 foe_position={"x": 3, "y": 5}, seed="A2R04MIRROR")
    engine = reload(tmp_path, mid)
    # place the Smoke Veil over the foe's square
    c = next(c for c in engine.legal_candidates()
             if c.display_name.split(" at ")[0].startswith("Smoke Veil")
             and c.destination is not None and (c.destination.x, c.destination.y) == (3, 5))
    settle(table, mid, c.candidate_id)
    return combat, table, mid


def _rename_echoes_field(bundles):
    """Persist the Field under a different display name, as owner-editable typed data may."""
    from combat.canonical import canonical_sha256

    renamed = False
    for bundle in bundles:
        for row in bundle["action_catalog"]:
            if ECHOES not in str(row.get("source_definition_id") or ""):
                continue
            spec = ((row.get("parameters") or {}).get("typed") or {}).get("zone_spec") or {}
            if spec:
                spec["name"] = "Renamed Echo Field"
                renamed = True
        bundle.pop("bundle_sha256", None)
        bundle["bundle_sha256"] = canonical_sha256(bundle)
    assert renamed, "the Echoes action carries the compiled zone it creates"


def test_ten_thousand_echoes_step_uses_its_record_not_its_printed_name(tmp_path):
    """A renamed Echoes Field still offers its printed step after reload.

    The name is owner-editable typed data; the Field is its record id, so a
    rename must not silently switch off the five-foot step."""
    combat, table, mid = fixture(tmp_path, [ECHOES],
                                 ally_talents=["TAL_SOUND_DAMPEN_SOUND"],
                                 owner_dc=FAIL, foe_position={"x": 6, "y": 6},
                                 ally_position={"x": 5, "y": 6}, seed="A2R04ECHOESNAME",
                                 bundle_transform=_rename_echoes_field)
    engine = reload(tmp_path, mid)
    settle(table, mid, _candidate(engine, "Ten-Thousand Echoes Field").candidate_id)
    engine = reload(tmp_path, mid)
    fields = [zone for zone in engine.state.zones.values()
              if zone.active and ECHOES in str(zone.source_definition_id or "")]
    assert fields, "the placed Field is saved with the record that created it"
    assert all(zone.trigger_profile.get("name") == "Renamed Echo Field" for zone in fields)
    ally = engine.state.actors[ALLY]
    before = (ally.position.x, ally.position.y)
    turn(table, mid, ALLY)
    engine = reload(tmp_path, mid)
    pulse = [c for c in engine.legal_candidates()
             if c.actor_id == ALLY and c.display_name.split(" at ")[0] == "Dampen Sound"]
    assert pulse, f"the ally has no Dampen Sound; legal: {sorted(c.display_name for c in engine.legal_candidates())}"
    prompts = settle(table, mid, pulse[0].candidate_id,
                     picks={"choice:needle.echoes_step": "first"})
    engine = reload(tmp_path, mid)
    ally = engine.state.actors[ALLY]
    assert engine.grid.distance_ft(before, (ally.position.x, ally.position.y)) == 5
    assert any(p["context"]["reaction_source_id"] == "choice:needle.echoes_step" for p in prompts)


@pytest.mark.parametrize("condition_id", ["condition:typed.invisible"])
def test_smoke_mirror_trail_traces_an_invisible_creature_in_the_veil(tmp_path, monkeypatch, condition_id):
    """A creature that becomes Invisible inside the owner's Smoke Veil is traced
    for free: it gains the owner's Smoke Trace, and the owner learns its
    direction, without spending the once-per-round Smoke Trace."""
    from combat import zones

    combat, table, mid = _smoke_fixture(tmp_path)
    engine = reload(tmp_path, mid)
    foe = engine.state.actors[FOE]
    owner = engine.state.actors[OWNER]
    # the foe is inside the owner's Smoke Veil
    veil = [z for z in zones.typed_zones(engine) if z.owner_id == OWNER]
    assert veil, "no Smoke Veil is up"

    def vanish(engine):
        # the foe becomes Invisible (the engine records this as a condition)
        engine._apply_condition(engine.state.actors[FOE], condition_id,
                                "test:invisible", FOE, expires_on="UNTIL_REMOVED")

    _resonance_on_hold(monkeypatch)(vanish)
    hold = next(c for c in engine.legal_candidates()
                if c.display_name == "Hold position")
    settle(table, mid, hold.candidate_id)
    engine = reload(tmp_path, mid)
    foe = engine.state.actors[FOE]
    owner = engine.state.actors[OWNER]
    # the Mirror Trail placed a Smoke Trace on the foe for free (no once-per-round spent)
    assert bears_mark(foe, OWNER, "Smoke Trace"), "no free Smoke Trace was placed"
    # and the owner learned the direction to it within 120 feet
    direction = [c for c in owner.conditions.values()
                 if c.condition_id == "condition:typed.mirror_trail"
                 and (c.data or {}).get("target_id") == FOE]
    assert direction, "the owner did not learn the direction to the traced creature"
    assert int((direction[0].data or {}).get("range_ft") or 0) == 120


def test_smoke_mirror_trail_traces_a_creature_that_hides_in_the_veil(tmp_path, monkeypatch):
    """A creature that successfully Hides inside the owner's Smoke Veil is traced
    for free, exactly as an Invisible one is."""
    from combat import zones

    combat, table, mid = _smoke_fixture(tmp_path)
    engine = reload(tmp_path, mid)
    foe = engine.state.actors[FOE]
    # the foe is inside the owner's Smoke Veil
    assert [z for z in zones.typed_zones(engine) if z.owner_id == OWNER], "no Smoke Veil is up"

    def hides(engine):
        from combat.stealth import hide
        assert hide(engine, engine.state.actors[FOE], 50, "test:hide")

    _resonance_on_hold(monkeypatch)(hides)
    hold = next(c for c in engine.legal_candidates()
                if c.display_name == "Hold position")
    settle(table, mid, hold.candidate_id)
    engine = reload(tmp_path, mid)
    foe = engine.state.actors[FOE]
    assert bears_mark(foe, OWNER, "Smoke Trace"), "no free Smoke Trace was placed for the hiding creature"
    owner = engine.state.actors[OWNER]
    assert any(c.condition_id == "condition:typed.mirror_trail"
               and (c.data or {}).get("target_id") == FOE for c in owner.conditions.values())


@pytest.mark.parametrize("movement,leaves,expected", [
    ("teleport", False, True),
    ("teleport", True, True),
    ("forced", True, True),
    ("forced", False, False),
])
def test_smoke_mirror_trail_native_movement_commits_and_reloads(
        tmp_path, monkeypatch, movement, leaves, expected):
    """Native teleport and forced-exit receipts trigger the optional free trace.

    Only the incoming movement is staged inside Hold's accepted transaction.
    The native movement executor, Mirror prompt, marking and persistence are real.
    Teleporting within the veil counts; a push still inside it does not.
    """
    from combat import zones
    from combat.typed_executor import Context, teleport_subject
    from combat.movement_paths import forced_steps
    from combat.ext.ironclad_smoke import ROUND_USE_CONDITION

    _, table, mid = _smoke_fixture(tmp_path)
    engine = reload(tmp_path, mid)
    destination = Position(x=9 if leaves else 4, y=5)
    before_sequence = engine.state.event_sequence

    def move(live):
        foe = live.state.actors[FOE]
        owner = live.state.actors[OWNER]
        veil = next(z for z in zones.typed_zones(live) if z.owner_id == OWNER)
        assert zones.actor_inside_zone(live, foe, veil)
        assert zones.actor_inside_zone(live, foe, veil, destination) is not leaves
        if movement == "teleport":
            action = next(a for a in live.action_catalog.values() if a.owner_id == FOE)
            ctx = Context(live, foe, action, live._active_intent, {}, [foe],
                          target=foe, effect_source="test:mirror_teleport")
            teleport_subject(ctx, foe, destination)
        else:
            steps = [Position(x=x, y=5) for x in range(4, destination.x + 1)]
            forced_steps(live, foe, steps, "test:mirror_push",
                         live._active_intent, len(steps))

    _resonance_on_hold(monkeypatch)(move)
    hold = next(c for c in engine.legal_candidates() if c.display_name == "Hold position")
    prompts = settle(table, mid, hold.candidate_id,
                     picks={"choice:needle.mirror_trail": "place_trace"})
    engine = reload(tmp_path, mid)
    foe, owner = engine.state.actors[FOE], engine.state.actors[OWNER]
    assert foe.position == destination
    moves = [e for e in engine.events if e.sequence > before_sequence
             and e.event_type == "MOVEMENT_COMMITTED" and e.actor_id == FOE]
    assert moves
    assert moves[-1].payload.get("teleport" if movement == "teleport" else "forced") is True
    mirror_prompts = [p for p in prompts
                      if p["context"]["reaction_source_id"] == "choice:needle.mirror_trail"]
    assert len(mirror_prompts) == int(expected)
    assert bears_mark(foe, OWNER, "Smoke Trace") is expected
    directions = [c for c in owner.conditions.values()
                  if c.condition_id == "condition:typed.mirror_trail"
                  and c.data.get("target_id") == FOE]
    assert bool(directions) is expected
    if expected:
        trace = next(c for c in foe.conditions.values()
                     if c.condition_id == mark_condition_id("Smoke Trace", OWNER))
        assert directions[0].data["trace_instance_id"] == trace.instance_id
        assert directions[0].data["range_ft"] == 120
    assert not any(c.condition_id == ROUND_USE_CONDITION for c in owner.conditions.values())


def test_forbidden_silence_field_admits_only_sound_talents_that_run_through_its_channels(tmp_path):
    """The printed line: "You may use Sound talents inside the Field only if they explicitly
    function through silent vibration, contact resonance, soul-sound, or a special feature."

    The caster stands inside its own Field on its next turn. Muffle Footfall's text names none of
    those channels, so the table stops offering it and says why in plain words; Read the Vibration
    runs through vibration and stays offered; native actions keep their whole menu. Outside the
    Field the same Muffle Footfall is offered again, so nothing about ordinary fights changed."""
    from combat import zones

    combat, table, mid = fixture(tmp_path, [SILENCE_FIELD, MUFFLE, VIBRATION],
                                       foe_position={"x": 11, "y": 6},
                                       positions={OWNER: {"x": 3, "y": 6},
                                                  ALLY: {"x": 0, "y": 6},
                                                  FOE: {"x": 11, "y": 6}},
                                       seed="A2R04CHAN")
    engine = reload(tmp_path, mid)
    assert "Muffle Footfall" in _offered(engine), "outside any Field the talent is offered"
    muffle = _action_id(engine, "Muffle Footfall")
    c = next(c for c in engine.legal_candidates()
             if c.display_name.split(" at ")[0] == "Forbidden Silence Field"
             and c.destination is not None and (c.destination.x, c.destination.y) == (5, 6))
    settle(table, mid, c.candidate_id)
    # Back to the caster's own turn, still standing inside its Field.
    settle(table, mid, table.state(mid)["menu"]["end_turn"])
    turn(table, mid, OWNER)
    engine = reload(tmp_path, mid)
    assert zones.actor_inside_zone(engine, engine.state.actors[OWNER],
                                   next(z for z in zones.typed_zones(engine) if z.owner_id == OWNER))
    offered = _offered(engine)
    assert "Muffle Footfall" not in offered, "a Sound talent with no printed silent channel is stopped"
    assert "Read the Vibration" in offered, "vibration through a surface is one of the printed channels"
    assert {"Hide", "Dash"} <= offered, "no non-Sound action is touched"
    answer = engine.action_availability(OWNER, muffle)
    assert answer["available"] is False, answer
    reason = str(answer.get("reason") or "")
    assert "Forbidden Silence Field" in reason and "Muffle Footfall" in reason, reason
    assert "silent vibration" in reason and "contact resonance" in reason, reason
    # Stepping out of the Field restores the whole menu.
    engine.state.actors[OWNER].position = Position(x=0, y=6)
    zones.sync_inside(engine, "test:leave_field")
    assert "Muffle Footfall" in _offered(engine)
    assert "Read the Vibration" in _offered(engine)


def _offered(engine):
    """The plain names of every choice the current fighter is offered right now."""
    return {getattr(engine.action_catalog.get(c.source_definition_id), "display_name",
                    c.source_definition_id).split(" at ")[0]
            for c in engine.legal_candidates()}


def _action_id(engine, name):
    return next(a.source_definition_id for a in engine.action_catalog.values()
                if getattr(a, "display_name", None) == name and getattr(a, "owner_id", None) == OWNER)


def test_forbidden_silence_field_holds_sound_back(tmp_path):
    """Ordinary sound cannot be created inside the Field or pass through it.

    A creature on one side of the Field never hears a creature on the
    other, ordinary sound whose path crosses the Field carries no sound
    either, and every creature inside is Deafened by the Field's own
    inside rule."""
    from combat import speech, typed_executor

    # the owner (3,6) stands inside the Field placed at (5,6); the ally
    # (0,6) and the foe (11,6) stand outside, on opposite banks, and a
    # fourth creature (0,8) stands outside on a path that misses the Field
    combat, table, mid = fixture(tmp_path, [SILENCE_FIELD],
                                     foe_position={"x": 11, "y": 6},
                                     ally_position={"x": 0, "y": 6},
                                     extra_allies=1,
                                     positions={OWNER: {"x": 3, "y": 6},
                                                ALLY: {"x": 0, "y": 6},
                                                FOE: {"x": 11, "y": 6},
                                                "actor:factory.worker2-ally3": {"x": 0, "y": 8}},
                                     owner_dc=FAIL, seed="A2R04SIL")
    engine = reload(tmp_path, mid)
    # place the Field at (5,6)
    c = next(c for c in engine.legal_candidates()
             if c.display_name.split(" at ")[0] == "Forbidden Silence Field"
             and c.destination is not None and (c.destination.x, c.destination.y) == (5, 6))
    settle(table, mid, c.candidate_id)
    engine = reload(tmp_path, mid)
    actors = engine.state.actors
    aside = actors["actor:factory.worker2-ally3"]
    # opposite banks: sound cannot cross the boundary, either direction
    assert not speech.can_hear_from(engine, actors[OWNER], actors[FOE])
    assert not speech.can_hear_from(engine, actors[FOE], actors[OWNER])
    assert not speech.can_hear_from(engine, actors[ALLY], actors[OWNER])
    # a path that crosses the Field's own squares carries no sound either
    assert not speech.can_hear_from(engine, actors[ALLY], actors[FOE])
    # the Field's inside rule Deafens everyone inside
    assert typed_executor.cant_hear(actors[OWNER])
    # a clear path that misses the Field is untouched
    assert speech.can_hear_from(engine, actors[ALLY], aside)


def test_resonant_note_adds_proficiency_to_construct_damage(tmp_path):
    """The printed line: "If the target is an unattended object,
    brittle structure, ordinary barrier, or construct, add your
    Proficiency Bonus to the damage." A construct target's damage
    roll carries the Proficiency Bonus; an ordinary creature's does
    not. The same seed rolls the same dice in both fights, so only
    the damage modifier can differ."""
    def _damage_modifier(creature_types):
        folder = tmp_path / ("construct" if creature_types else "ordinary")
        foe_sheet = sheet([], cl=15)
        if creature_types:
            foe_sheet["identity"]["creature_type"] = creature_types[0]
        combat, table, mid = fixture(folder, [NOTE], foe_sheet=foe_sheet,
                                          foe_position={"x": 3, "y": 3},
                                          seed="A2R04NOTE", bundle_transform=_sure_hit)
        settle(table, mid, _candidate(reload(folder, mid),
                    "Resonant Note: Deafen", target=FOE).candidate_id)
        engine = reload(folder, mid)
        assert ("construct" in {kind.casefold() for kind in engine.state.actors[FOE].creature_types}) is bool(creature_types)
        rolls = [r for r in engine.rolls
                 if r.actor_id == OWNER and r.reason.startswith("DAMAGE")]
        assert rolls, "no damage roll was recorded"
        return rolls[-1].modifier

    ordinary = _damage_modifier(())
    construct = _damage_modifier(("Construct",))
    assert construct - ordinary == 4  # the sheet's Proficiency Bonus


def test_sound_hiding_mask_reads_the_default_basis_a_native_hide_leaves_unrecorded(tmp_path):
    """A native Hide records no hiding_basis when it uses the default basis (visual and sound).

    A denial of both senses must still mask that Hidden benefit, and a
    sound-only denial must keep it because independent visual concealment
    survives. The mask read the missing basis as [""], so neither case
    matched a denial."""
    from combat import stealth
    from combat.ext import smoke_sound_residual

    _, table, mid = fixture(tmp_path, [NOTE], foe_position={"x": 3, "y": 3}, seed="A2R04MASK")
    engine = reload(tmp_path, mid)
    foe = engine.state.actors[FOE]
    engine._apply_condition(foe, stealth.HIDDEN, "test:hide", FOE, expires_on="UNTIL_REMOVED",
                            data={"stealth_total": 50})
    hidden = next(iid for iid, c in foe.conditions.items() if c.condition_id == stealth.HIDDEN)
    engine._apply_condition(foe, DENIED, "test:sound", OWNER, expires_on="UNTIL_REMOVED",
                            data={"rule": {"hiding_denied": ["sound_reliance"]}})
    assert hidden not in smoke_sound_residual.sound_hiding_masks(engine, foe, foe)[FOE]
    engine._apply_condition(foe, "condition:typed.test_visual_denial", "test:visual", OWNER,
                            expires_on="UNTIL_REMOVED",
                            data={"rule": {"hiding_denied": ["visual_concealment"]}})
    assert hidden in smoke_sound_residual.sound_hiding_masks(engine, foe, foe)[FOE]


def test_the_liar_talent_records_why_its_save_outcomes_stay_printed_text():
    """Review: two empty outcome arrays need a recorded reason, not silence.

    "Speaks a deliberate lie" and "attempting to conceal hostile intent" are
    social facts no committed fight record holds, so the GM-rider rule allows
    these two outcomes to stay printed text -- but the typed record must say
    so, so a later round neither automates the unobservable nor treats the
    empty arrays as an oversight.

    The assertions are structural because the public copy scrambles printed
    prose; the notes' wording is quoted in the lane report instead.
    """
    import json

    authority = json.loads((Path(__file__).resolve().parents[1]
                            / "authority/Tianxia_Typed_Mechanics_Authority_R1.json").read_text(encoding="utf-8"))
    row = authority["mechanics"][LIAR]
    save = next(effect for effect in row["effects"] if effect.get("type") == "save")
    assert save["on_fail"] == [] and save["on_success"] == []
    notes = row.get("notes")
    assert isinstance(notes, list) and len(notes) == 3, f"one note per outcome plus what is automated: {notes}"
    assert all(isinstance(note, str) and note.strip() for note in notes), notes
    assert len(row["riders"]) == 3, row["riders"]

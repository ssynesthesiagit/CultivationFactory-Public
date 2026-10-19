"""AUTO16 (Sound sphere): the printed lines the table now runs, at the level the bug showed.

Owner 2026-09-29: "we need to automate every aspect before another playtest". This lane's work is
APP/authority/typed_mechanics/reviewed_final.d/auto16_sound.json (the reviewed typing the builder
merges), APP/combat/rules/typed_conditions.json + APP/combat/voluntary_movement.py +
APP/combat/ext/approach_restriction.py (the general "cannot willingly move closer" restriction) and
APP/combat/condition_text.py (the pill reading). AUTO16f1 adds the printed check/DC seams in
APP/combat/save_dcs.py and APP/combat/ability_checks.py.

Every test here compiles a real Sound character and runs it through the engine:
  * the silence areas (True Silence, Forbidden Silence Field, Silence That Swallows Thunder) put a
    creature inside off any ability that needs its own voice, and The First Sound Before Heaven's
    Silence-Before-Sound mode does that to hostiles only;
  * the areas that print a hostile entry/start save run it (Resonance Field, Court of the
    World-Ringing Bell, Forbidden Silence Field, Ten-Thousand Echoes Field);
  * Name-Striking Tone's fourth printed rider keeps its target from moving closer -- with or without
    sight of it, and across a teleport -- while Frightened keeps its own printed sight exception;
  * Counter-Chant and Shatter the Chant compare their Sound Check with the printed alternative the
    target picks, which may be a Save DC rather than a defending die.
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

from combat.factory_compiler import TYPED_AUTHORITY, compile_character
from combat.gate2_runtime_models import ActionIntent

sys.path.insert(0, str(Path(__file__).resolve().parent))
t = importlib.import_module("test_review_sw-athletics")

ROOT = Path(__file__).resolve().parents[1]
ME, AN = t.ME, t.FOE
SOUND = "tianxia.sphere.sound"
AIR = "tianxia.sphere.air"
AIR_VOICE = "TAL_AIR_BREATH_OF_NO_DISTANCE"  # combat/rules/speech.json: an ability that needs its user's voice
FAIL = 50  # a technique save DC the foe cannot beat
ALLY1 = "actor:factory.ally1"

FIRST_SOUND = "tianxia.talent.sound.the_first_sound_before_heaven"
TRUE_SILENCE = "TAL_SOUND_TRUE_SILENCE"
FORBIDDEN = "TAL_SOUND_FORBIDDEN_SILENCE_FIELD"
SWALLOWS = "TAL_SOUND_SILENCE_THAT_SWALLOWS_THUNDER"
FIELD = "TAL_SOUND_RESONANCE_FIELD"
COURT = "TAL_SOUND_COURT_OF_THE_WORLD_RINGING_BELL"
ECHOES = "TAL_SOUND_TEN_THOUSAND_ECHOES_FIELD"
TONE = "TAL_SOUND_NAME_STRIKING_TONE"
MUFFLE = "TAL_SOUND_MUFFLE_FOOTFALL"
DAMPEN = "TAL_SOUND_DAMPEN_SOUND"


def _authority():
    return json.loads(Path(TYPED_AUTHORITY).read_text(encoding="utf-8"))["mechanics"]


def _sheet(sphere, talents, *, cl=17, dc=16, kit=None):
    spheres = [sphere] if isinstance(sphere, str) else list(sphere)
    return t._sheet(spheres[0], list(talents), kit or {"starting_kit": {"items": []}}, cl=cl, dc=dc)


def _bundle(sphere, talents, *, cl=17, dc=16, actor_id=ME, kit=None):
    return compile_character(_sheet(sphere, talents, cl=cl, dc=dc, kit=kit), actor_id=actor_id)


def _foe_bundle(talents=(), sphere="tianxia.sphere.force", dc=16):
    """A compiled Factory foe (its own typed defenses run), or one holding a voice ability."""
    return compile_character(_sheet(sphere, talents, cl=17, dc=dc), actor_id=AN)


def _fight(sphere, talents, *, cl=17, dc=16, foe_talents=("TAL_FORCE_FORCE_MANTLE",), foe_sphere=None,
           foe_dc=16, foe_at=(4, 6), foe_hp=400):
    """My Sound character against a compiled Factory foe (its typed rows run)."""
    from combat.gate4_engine import Gate4ControllerEngine

    mine = _bundle(sphere, talents, cl=cl, dc=dc)
    foe = _foe_bundle(foe_talents, foe_sphere or "tianxia.sphere.force", dc=foe_dc)
    engine = Gate4ControllerEngine(ROOT, match_seed="AUTO16", typed_bundles=(mine, foe),
                                   roster_setup={"primary_actor_ids": [ME, AN],
                                                 "team_by_actor": {ME: "team:a", AN: "team:b"},
                                                 "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": foe_at[0], "y": foe_at[1]}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    target = engine.state.actors[AN]
    target.armor_class = -50
    target.maximum_hp = target.current_hp = foe_hp
    t._ready(engine)
    return engine


def _ready(engine, actor_id=ME):
    t._ready(engine)
    engine.state.current_actor_id = actor_id
    return engine.state.actors[actor_id]


def _names(engine, actor_id=ME):
    _ready(engine, actor_id)
    return {c.display_name for c in engine.legal_candidates() if c.actor_id == actor_id}


def _use(engine, name, *, actor_id=ME, target=AN, destination=None, contains=False):
    """`contains` matches the printed name inside the button text (an area is offered as
    "Name at 4,6", a self-area as "Name - Hits allies too: ...")."""
    _ready(engine, actor_id)
    if name == "Name-Striking Tone: Kept at Distance":
        # The printed penalty is selected only after the Wisdom save fails.
        name = "Name-Striking Tone"
        engine.typed_control_modes = {actor_id: "MANUAL"}
        _with_provider(engine, lambda request, options:
                       ["distance"] if request["reaction_source_id"] == "choice:needle.sound_name_failure"
                       else options[:1])
    found = [c for c in engine.legal_candidates()
             if c.actor_id == actor_id and (name in c.display_name if contains else c.display_name == name)
             and (target is None or not c.target_ids or target in c.target_ids)
             and (destination is None or (c.destination and (c.destination.x, c.destination.y) == destination))]
    assert found, f"{name!r} is not legal; legal: {sorted(n for n in _names(engine, actor_id) if not n.startswith('Move'))[:40]}"
    candidate = found[0]
    before = len(engine.events)
    engine.execute_intent(ActionIntent(intent_id=f"a16-{name}-{engine.state.event_sequence}",
                                       decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=actor_id,
                                       target_ids=candidate.target_ids or ((target,) if target else ()),
                                       destination=candidate.destination))
    return engine.events[before:]


def _zone(engine, actor_id=ME):
    """The area this character owns (an aura on itself, a placed sphere in the map)."""
    from combat import zones

    mine = [zone for zone in zones.typed_zones(engine) if zone.owner_id == actor_id]
    assert len(mine) == 1, [zone.source_definition_id for zone in mine]
    return mine[0]


def _start_turn(engine, actor_id=AN):
    """Hand the turn to that creature the way the round clock does."""
    engine.state.current_slot_index = engine.state.initiative_order.index(actor_id)
    engine.state.current_actor_id = actor_id
    engine._system_start_turn()
    return engine.state.actors[actor_id]


# --------------------------------------------------------------------------- the reviewed typing (data level)
@pytest.mark.parametrize("talent", [FIELD, DAMPEN, MUFFLE, TONE])
def test_the_fully_run_talents_carry_no_gm_rider(talent):
    mechanic = _authority()[talent]
    assert mechanic["coverage"] == "FULL", (talent, mechanic["riders"])
    assert mechanic["riders"] == [], (talent, mechanic["riders"])


@pytest.mark.parametrize("talent", [TRUE_SILENCE, FORBIDDEN, SWALLOWS])
def test_the_silence_areas_run_the_voice_rule_inside(talent):
    """"verbal components and voice-dependent talents fail": the area carries the shared silenced
    inside rule (combat/speech.py), so a creature entirely inside is not offered a voice ability."""
    mechanic = _authority()[talent]
    zone = next(row for row in mechanic["effects"] if row.get("type") == "zone")
    inside = next(row for row in zone["inside"] if row["rule"].get("silenced") is True)
    assert inside["who"] == "any" and inside["reading"]
    assert not [line for line in mechanic["riders"] if "verbal component" in line], mechanic["riders"]


def test_silence_that_swallows_thunder_carries_its_executable_hostile_packet_gate():
    """The packet/check hook now resolves the printed hostile Thunder exception."""
    mechanic = _authority()[SWALLOWS]
    zone = next(row for row in mechanic["effects"] if row.get("type") == "zone")
    assert any(row["rule"].get("sound_hostile_thunder") == "check" for row in zone["inside"])
    assert not [line for line in mechanic["riders"] if "reduced to 0" in line]
    assert any("silent vibration" in line for line in mechanic["riders"])


# --------------------------------------------------------------------------- the table (service level)
def test_a_creature_inside_true_silence_is_not_offered_its_own_voice_ability():
    """True Silence: "creatures inside ... verbal components and voice-dependent talents fail"."""
    engine = _fight(SOUND, [TRUE_SILENCE], foe_talents=(AIR_VOICE,), foe_sphere=AIR)
    _use(engine, "True Silence", contains=True, target=None)
    assert "Breath of No Distance" in _names(engine, AN), "the foe starts with its voice ability"
    zone = _zone(engine)
    foe = engine.state.actors[AN]
    foe.position = foe.position.model_copy(update={"x": zone.center.x, "y": zone.center.y})
    from combat import zones

    zones.sync_inside(engine, zone.source_definition_id)
    assert "Breath of No Distance" not in _names(engine, AN), "a voice ability is still offered inside the field"
    from combat import speech

    assert speech.silenced(foe)
    # and the plain reading of the area says so for the player
    condition = next(c for c in foe.conditions.values() if c.condition_id == ZONE_EFFECT)
    assert condition.data["reading"] == ("A creature entirely inside the field cannot use an ability that needs its own "
                                         "voice: a shout, chant, song, spoken command or Verbal component.")


def test_leaving_true_silence_gives_the_voice_ability_back():
    engine = _fight(SOUND, [TRUE_SILENCE], foe_talents=(AIR_VOICE,), foe_sphere=AIR)
    _use(engine, "True Silence", contains=True, target=None)
    zone = _zone(engine)
    foe = engine.state.actors[AN]
    foe.position = foe.position.model_copy(update={"x": zone.center.x, "y": zone.center.y})
    from combat import zones

    zones.sync_inside(engine, zone.source_definition_id)
    assert "Breath of No Distance" not in _names(engine, AN)
    foe.position = foe.position.model_copy(update={"x": zone.center.x + 25, "y": zone.center.y})
    zones.sync_inside(engine, zone.source_definition_id)
    assert "Breath of No Distance" in _names(engine, AN)


def test_forbidden_silence_field_silences_a_hostile_that_starts_its_turn_inside():
    """"hostile creatures entering for the first time on a turn or starting their turns there make
    Constitution saving throws. Failed Save: The creature cannot speak, shout, command, sing, or use
    Voice talents until the start of its next turn." """
    engine = _fight(SOUND, [FORBIDDEN], dc=FAIL)
    _use(engine, "Forbidden Silence Field", contains=True, target=None, destination=_on(engine, AN))
    foe = _start_turn(engine)  # it starts its turn inside the Field
    assert speech_condition(foe), [c.condition_id for c in foe.conditions.values()]
    saves = [e for e in engine.events
             if e.event_type == "SAVE_ROLLED" and "FORBIDDEN_SILENCE" in str(e.source_definition_id)
             and foe.entity_id in ((e.target_ids or ()) + ((e.payload or {}).get("actor_id", ""),))]
    assert saves, [e.event_type for e in engine.events if e.event_type == "SAVE_ROLLED"]
    assert saves[-1].payload["actor_id"] == foe.entity_id, saves[-1].payload


ZONE_EFFECT = "condition:typed.zone_effect"


def speech_condition(actor):
    return [c for c in actor.conditions.values() if c.condition_id == "condition:typed.silenced"]


def test_resonance_field_marks_and_damages_a_hostile_that_starts_its_turn_inside():
    """"Once per turn when a hostile creature enters the aura for the first time on a turn or starts
    its turn there, it makes a Constitution saving throw. Failed Save: It gains Resonance and takes
    Thunder damage equal to your Proficiency Bonus."""
    engine = _fight(SOUND, [FIELD], dc=FAIL)
    _use(engine, "Resonance Field", contains=True, target=None)
    zone = _zone(engine)
    foe = _start_turn(engine)  # it starts its turn inside the aura
    foe = engine.state.actors[AN]
    assert foe.current_hp < foe.maximum_hp, "no Thunder damage on the failed save"
    marks = [c for c in foe.conditions.values() if "resonance" in str(c.condition_id).lower()]
    assert marks, [c.condition_id for c in foe.conditions.values()]


def test_court_of_the_world_ringing_bell_hurt_and_marks_on_a_failed_start_turn_save():
    """"hostile creatures that start their turn inside make Constitution saving throws. Failed Save:
    They take 4d8 Thunder damage and gain Resonance. Successful Save: They gain Resonance." """
    engine = _fight(SOUND, [COURT], dc=FAIL)
    _use(engine, "Court of the World-Ringing Bell", contains=True, target=None)
    foe = _start_turn(engine)  # it starts its turn inside the Domain
    foe = engine.state.actors[AN]
    assert foe.current_hp < foe.maximum_hp
    assert [c for c in foe.conditions.values() if "resonance" in str(c.condition_id).lower()]


def test_ten_thousand_echoes_field_runs_its_wisdom_save_and_moves_nobody_on_casting():
    """"Hostile creatures inside: make a Wisdom saving throw when they start their turn inside.
    Failed Save: The creature must choose either lose its Reaction ... Successful Save: No additional
    effect." and "may move 5 feet without provoking opportunity attacks after using a Sound talent,
    once per turn" -- casting the Field grants nobody movement."""
    engine = _fight(SOUND, [ECHOES], dc=FAIL)
    me = engine.state.actors[ME]
    before = me.position
    _use(engine, "Ten-Thousand Echoes Field", contains=True, target=None)
    assert me.position == before, "casting the Field moved its user"
    foe = _start_turn(engine)  # it starts its turn inside the Field
    assert _condition(foe, "reaction_denied"), "the failed Wisdom save did not take the foe's Reaction"


def _on(engine, actor_id):
    """Where that creature stands, as a (x, y) placement for an area."""
    position = engine.state.actors[actor_id].position
    return (position.x, position.y)


def _condition(actor, name):
    return [c for c in actor.conditions.values() if c.condition_id == f"condition:typed.{name}"]


def test_name_striking_tone_keeps_its_target_from_walking_closer():
    """"cannot willingly move closer to you until the end of your next turn" (the fourth printed rider)."""
    engine = _fight(SOUND, [TONE], dc=FAIL, foe_at=(5, 6))
    _use(engine, "Name-Striking Tone: Kept at Distance", contains=True)
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    assert [c for c in foe.conditions.values() if c.condition_id == "condition:typed.no_approach"]
    _ready(engine, AN)
    start = foe.position
    candidates = [c for c in engine.legal_candidates() if c.actor_id == AN and c.display_name.startswith("Move")]
    assert candidates, "the target has no movement at all"
    assert all(_distance(engine, c.destination, me.position) >= _distance(engine, start, me.position) for c in candidates), [
        (c.display_name, (c.destination.x, c.destination.y)) for c in candidates]
    away = next(c for c in candidates if (c.destination.x, c.destination.y) == (start.x + 5, start.y))
    _use(engine, away.display_name, actor_id=AN, target=None)
    assert (engine.state.actors[AN].position.x, engine.state.actors[AN].position.y) == (start.x + 5, start.y), \
        "walking away must still work"


def _distance(engine, one, other):
    return engine._distance_cells(one, other) if hasattr(engine, "_distance_cells") else (
        (one.x - other.x) ** 2 + (one.y - other.y) ** 2) ** 0.5


def test_the_approach_restriction_is_inert_for_a_character_without_the_talent():
    """The same path rule for everyone else: a creature without that condition walks closer."""
    engine = _fight(SOUND, [], foe_at=(6, 6))
    foe = engine.state.actors[AN]
    _ready(engine, AN)
    closer = [c for c in engine.legal_candidates()
              if c.actor_id == AN and c.display_name.startswith("Move")
              and (c.destination.x, c.destination.y) == (foe.position.x - 5, foe.position.y)]
    assert closer, sorted(c.display_name for c in engine.legal_candidates() if c.actor_id == AN)
    start_x = foe.position.x
    _use(engine, closer[0].display_name, actor_id=AN, target=None)
    assert engine.state.actors[AN].position.x == start_x - 5


def test_the_approach_restriction_still_blocks_a_frightened_creature():
    """Frightened's printed "It can't willingly take a step closer while that source is visible" is the
    same rule, read from the same table (combat/rules/typed_conditions.json)."""
    engine = _fight(SOUND, [], foe_at=(6, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    engine._apply_condition(foe, "condition:typed.frightened", "test:fear", me.entity_id, expires_on="UNTIL_REMOVED")
    _ready(engine, AN)
    closer = [c for c in engine.legal_candidates()
              if c.actor_id == AN and c.display_name.startswith("Move")
              and (c.destination.x, c.destination.y) == (foe.position.x - 5, foe.position.y)]
    assert not closer, "Frightened no longer keeps a creature from stepping closer"


# --------------------------------------------------------------------------- Counter-Chant: the printed opposed check
CHANT = "TAL_SOUND_COUNTER_CHANT"


def _chant_fight(foe_dc):
    """A Sound character with Counter-Chant against a foe whose only way to speak is Breath of No
    Distance (combat/rules/speech.json: it needs its user's voice). The foe's own Save DC decides
    the printed contest, so ``foe_dc`` makes either side of it certain."""
    return _fight(SOUND, [CHANT], dc=50, foe_talents=(AIR_VOICE,), foe_sphere=AIR, foe_dc=foe_dc)


def _spoken_use(engine):
    _ready(engine, AN)
    return _use(engine, "Breath of No Distance", actor_id=AN, target=None)


def _attack_modes(engine):
    return {modifier.value for modifier in engine.state.actors[AN].modifiers.values()
            if modifier.target_field == "attack_mode"}


def _force_printed_dc(engine, needle="its Save DC"):
    """Answer the defender's own choice with the printed Save DC, so a test states which gate it means."""
    return _with_provider(engine, lambda request, options: _by_label(request, options, needle))


def test_counter_chant_answers_a_spoken_ability_with_the_printed_contest():
    """"Make a Sound Check opposed by the target's ... check ... Success: The target's voice cracks.
    Choose one: it has Disadvantage on the triggering attack roll or ability check." """
    engine = _chant_fight(foe_dc=1)  # the printed gate it defends with cannot be beaten
    _force_printed_dc(engine)
    events = _spoken_use(engine)
    checks = [e for e in events if e.event_type == "CHECK_ROLLED" and str(e.source_definition_id).endswith("COUNTER_CHANT")]
    assert checks, [e.event_type for e in events]
    assert checks[0].payload["success"] is True, checks[0].payload
    assert "DISADVANTAGE" in _attack_modes(engine), _attack_modes(engine)


def test_counter_chant_only_lands_when_the_contest_is_won():
    """The printed check is the whole gate: Disadvantage appears exactly when the contest was won.
    Before this typing the rider was applied with no roll at all."""
    engine = _chant_fight(foe_dc=1)
    _force_printed_dc(engine)
    events = _spoken_use(engine)
    checks = [e for e in events if e.event_type == "CHECK_ROLLED" and str(e.source_definition_id).endswith("COUNTER_CHANT")]
    assert checks, [e.event_type for e in events]
    assert bool(checks[0].payload["success"]) == ("DISADVANTAGE" in _attack_modes(engine)), checks[0].payload


def test_counter_chant_ignores_a_silent_ability_and_is_inert_without_the_talent():
    """"speaks a command word, uses a Voice talent, casts a spell with a verbal component, or begins a
    supernatural chant": an ability that needs no voice is not a trigger, and a character without the
    talent has no reaction to offer."""
    engine = _fight(SOUND, [CHANT], dc=50, foe_talents=("TAL_AIR_WIND_LASH",), foe_sphere=AIR)
    events = _use(engine, "Wind Lash: Cut", actor_id=AN, target=ME, contains=True)
    assert not [e for e in events if str(e.source_definition_id or "").endswith("COUNTER_CHANT")], \
        [e.event_type for e in events if str(e.source_definition_id or "").endswith("COUNTER_CHANT")]
    engine = _fight(SOUND, [], dc=50, foe_talents=(AIR_VOICE,), foe_sphere=AIR)
    events = _spoken_use(engine)
    assert not [e for e in events if str(e.source_definition_id or "").endswith("COUNTER_CHANT")]


# =============================================== AUTO16f1: the printed check and DC, and the two decisions the typing took
def _with_provider(engine, decide):
    """Answer the fight's own choice checkpoints, so a test can play the defender or the caster."""
    from combat.gate2_runtime_models import ReactionDecision

    asked = []

    def provider(request):
        asked.append(request)
        options = list((request.get("choice_trigger") or {}).get("needle_options") or [])
        pick = decide(request, options)
        if pick == "DECLINE":
            return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                    reaction_source_id=request["reaction_source_id"], selection="DECLINE"), None
        return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                reaction_source_id=request["reaction_source_id"], selection="USE",
                                option_ids=tuple(pick if pick is not None else options[:1])), None

    engine._gate4_reaction_provider = provider
    return asked


def _by_label(request, options, needle):
    """The one printed alternative whose own label says ``needle`` (an exact match wins)."""
    labels = (request.get("choice_trigger") or {}).get("labels") or {}
    exact = [option for option in options if str(labels.get(option) or "") == needle]
    return exact or [option for option in options if needle in str(labels.get(option) or "")] or None


def _checks(events, mechanic):
    return [e for e in events if e.event_type == "CHECK_ROLLED"
            and str(e.source_definition_id).endswith(mechanic)]


def test_the_contest_compares_with_the_targets_printed_save_dc_and_rolls_no_defending_save():
    """"Make a Sound Check opposed by ... its saving throw DC converted to a check DC": a Save DC is a
    number to beat, not a Charisma saving throw the target rolls."""
    engine = _chant_fight(foe_dc=1)  # a Save DC nothing can miss
    _force_printed_dc(engine)       # the defender picks that gate
    events = _spoken_use(engine)
    checks = _checks(events, "COUNTER_CHANT")
    assert checks, [e.event_type for e in events]
    payload = checks[0].payload
    assert payload["roll_kind"] == "dc_check", payload
    assert payload["dc"] == 1, payload  # the target's own Save DC, not a rolled total
    assert payload["against"] == "its Save DC", payload
    assert payload["check"] == "Sound Check", payload
    assert "target" not in payload, "a printed DC draws no defending die"
    assert not [e for e in events if e.event_type == "SAVE_ROLLED"], [e.event_type for e in events]


def test_the_defender_ai_defends_with_the_hardest_alternative_it_prints():
    """Owner 2026-10-05 (AUTO16r1 review, finding 1): a higher printed DC is a harder gate for the
    attacker, so ranking it the other way made the AI defend with its weakest Save DC. Both rows below
    failed before the ranking was corrected."""
    engine = _chant_fight(foe_dc=40)  # its own Save DC 40: out of reach at CL 17
    events = _spoken_use(engine)       # nobody answering: the AI's own preference is the choice
    payload = _checks(events, "COUNTER_CHANT")[0].payload
    assert payload["dc"] == 40, payload
    assert payload["against"] == "its Save DC", payload
    assert payload["roll_kind"] == "dc_check", "it must prefer the unreachable DC over a beatable check"


def test_the_defender_ai_takes_the_rolled_check_over_a_mid_range_printed_dc():
    """Owner 2026-10-05 (AUTO16r2 review, finding 1): the previous regression only reached DC 40, where
    the printed gate is unreachable and any ranking that prefers the bigger number happens to agree.
    Counter-Chant prints both rolled checks and a Save DC, so the ordinary case is where the two have to
    be compared on the same scale. Nothing answers here, so this is the AI's own preference.

    At CL 17 the Sound Check is +7 and the foe's own Save DC is 16: the attacker reaches 16 with 12 rolls
    in 20 but beats a defending +7 with 19 in 40, so the printed difficulty is the weaker gate and the
    rolled Cultivation Check is the better defence. Ranking the numbers as "the total resisted" scored
    those 16 against 8 and sent the AI to the Save DC instead."""
    from combat.ext.contests import D20_PAIRS, holds_against_die, holds_against_difficulty, reaches_difficulty

    engine = _chant_fight(foe_dc=16)   # ordinary CL 17 numbers, nothing forced
    _ready(engine, AN)
    sound_bonus = printed_bonus(engine, ME, {"kind": "cultivation"})
    assert sound_bonus == 7, sound_bonus
    # the two shapes really are close here, and the printed difficulty really is the weaker gate
    assert reaches_difficulty(sound_bonus, 16) == 240, reaches_difficulty(sound_bonus, 16)
    assert holds_against_die(sound_bonus, printed_bonus(engine, AN, {"kind": "cultivation"})) == 210
    assert holds_against_difficulty(sound_bonus, 16) == 160, holds_against_difficulty(sound_bonus, 16)
    assert holds_against_die(sound_bonus, printed_bonus(engine, AN, {"kind": "cultivation"})) > \
        holds_against_difficulty(sound_bonus, 16) > 0
    assert D20_PAIRS == 400, D20_PAIRS

    events = _spoken_use(engine)
    payload = _checks(events, "COUNTER_CHANT")[0].payload
    assert payload["roll_kind"] == "opposed_check", payload
    assert payload["against"] == "Cultivation Check", payload
    assert payload["target"]["actor_id"] == AN, payload


def test_the_rolled_defences_outrank_a_printed_dc_at_the_numbers_they_print():
    """The three helpers that rank the menu are exhaustive counts of the 400 d20 pairs, not a stand-in
    for them, so a reviewer can check the arithmetic the AI chose by. A +7 attack lands against DC 15 in
    13 rolls in 20 and against a defending +7 in 19 in 40, which is the finding's own worked example."""
    from combat.ext.contests import (D20_PAIRS, holds_against_die, holds_against_difficulty,
                                     printed_modifier, reaches_difficulty)

    for attack in range(-3, 12):
        for defence in range(-3, 12):
            counted = sum(1 for mine in range(1, 21) for theirs in range(1, 21)
                          if mine + attack <= theirs + defence)
            assert holds_against_die(attack, defence) == counted, (attack, defence)
        for difficulty in range(1, 41):
            counted = sum(1 for mine in range(1, 21) if mine + attack >= difficulty)
            assert reaches_difficulty(attack, difficulty) == 20 * counted, (attack, difficulty)
            assert holds_against_difficulty(attack, difficulty) == D20_PAIRS - 20 * counted, (attack, difficulty)
    assert reaches_difficulty(7, 15) == 260, reaches_difficulty(7, 15)      # 65%
    assert D20_PAIRS - holds_against_die(7, 7) == 190, holds_against_die(7, 7)  # 47.5%
    assert holds_against_difficulty(7, 15) == 140 < holds_against_die(7, 7) == 210

    # A printed difficulty is the defending shape; printed_modifier says so rather than guessing a bonus.
    engine = _chant_fight(foe_dc=16)
    _ready(engine, AN)
    assert printed_modifier(engine, ME, {"kind": "dc"}, numbers={"pb": 4}) is None


def printed_bonus(engine, actor_id, row):
    """The d20 bonus a printed alternative's own roller carries, read through the plug-in's own seam."""
    from combat.ext.contests import printed_modifier
    from combat.ext.needle import numbers_of

    actor = engine.state.actors[actor_id]
    return printed_modifier(engine, actor, row, numbers=numbers_of(engine, actor))


def test_the_mixed_defence_menu_explains_both_equality_rules():
    """Owner 2026-10-05 (AUTO16r2 review, finding 3): Counter-Chant offers rolled checks AND a Save DC,
    so the prompt has to state both rules. Before this it told the defender to "choose your opposing roll"
    and that a tie leaves the situation unchanged even when the player picked the printed difficulty, where
    meeting it exactly now succeeds."""
    engine = _chant_fight(foe_dc=16)
    asked = _with_provider(engine, lambda request, options: None)
    _spoken_use(engine)
    contests = [r for r in asked if r["reaction_source_id"] == "choice:needle.contest_target"]
    assert contests, [r["reaction_source_id"] for r in asked]
    trigger = contests[0].get("choice_trigger") or {}
    labels = [str(trigger.get("labels", {}).get(option)) for option in trigger.get("needle_options") or []]
    assert "its Save DC" in labels and any("Check" in label or "check" in label for label in labels), labels
    prompt = trigger.get("prompt") or ""
    assert "tie leaves the situation unchanged" in prompt, prompt       # the rolled checks
    assert "reaches it exactly" in prompt, prompt                      # the printed difficulty
    assert "printed difficulty" in prompt, prompt


def test_a_printed_only_defence_menu_keeps_saying_only_its_own_rule():
    """Shatter the Chant prints three difficulties and no dice, so its prompt must not mention a tie."""
    engine = _shatter_fight(1)
    asked = _with_provider(engine, lambda request, options: None)
    _spoken_use(engine)
    contests = [r for r in asked if r["reaction_source_id"] == "choice:needle.contest_target"]
    assert contests, [r["reaction_source_id"] for r in asked]
    prompt = (contests[0].get("choice_trigger") or {}).get("prompt") or ""
    assert "reaches it exactly succeeds" in prompt, prompt
    assert "tie" not in prompt, prompt


def test_counter_chant_loses_when_the_targets_save_dc_is_out_of_reach():
    """The same check, lost: the printed gate is the whole outcome. Before the fix this setup won the
    same way as the winning one, because the target's Save DC never entered the roll."""
    engine = _chant_fight(foe_dc=40)  # its own Save DC: 40, unbeattainable at CL 17
    _with_provider(engine, lambda request, options: _by_label(request, options, "its Save DC"))
    events = _spoken_use(engine)
    checks = _checks(events, "COUNTER_CHANT")
    assert checks, [e.event_type for e in events]
    assert checks[0].payload["success"] is False, checks[0].payload
    assert checks[0].payload["dc"] == 40, checks[0].payload
    assert _attack_modes(engine) == set(), _attack_modes(engine)


def test_counter_chant_still_lets_the_target_roll_a_printed_check_when_it_is_the_better_bet():
    """The printed "or cultivation check" is still a rolled check, with its own die in the record. The
    defender takes it when it prefers that gate: its own Save DC of 1 is a worse bet than a roll."""
    engine = _chant_fight(foe_dc=1)
    _with_provider(engine, lambda request, options: _by_label(request, options, "Cultivation Check"))
    events = _spoken_use(engine)
    payload = _checks(events, "COUNTER_CHANT")[0].payload
    assert payload["roll_kind"] == "opposed_check", payload
    assert payload["against"] == "Cultivation Check", payload
    assert payload["target"]["actor_id"] == AN, payload


def test_the_defenders_choice_prompt_names_the_ability_that_spoke():
    """A player has to know what they are answering: the reaction, the creature, and the ability that
    just used its voice."""
    engine = _chant_fight(foe_dc=1)
    asked = _with_provider(engine, lambda request, options: None)
    _spoken_use(engine)
    contests = [r for r in asked if r["reaction_source_id"] == "choice:needle.contest_target"]
    assert contests, [r["reaction_source_id"] for r in asked]
    prompt = (contests[0].get("choice_trigger") or {}).get("prompt") or ""
    assert "Counter-Chant" in prompt and "Breath of No Distance" in prompt, prompt


SHATTER = "TAL_SOUND_SHATTER_THE_CHANT"


def _shatter_fight(foe_dc):
    return _fight(SOUND, [SHATTER], dc=50, foe_talents=(AIR_VOICE,), foe_sphere=AIR, foe_dc=foe_dc)


def _resonance(engine):
    return [c for c in engine.state.actors[AN].conditions.values() if "resonance" in c.condition_id.lower()]


def test_shatter_the_chant_wins_its_printed_check_and_applies_the_printed_resonance():
    """"Make a Sound Check against the triggering creature's Save DC, Cultivation Save DC, or named
    sphere Save DC. ... Critical Success or success by 5 or more: You may also apply Resonance"."""
    engine = _shatter_fight(1)
    _force_printed_dc(engine)
    events = _spoken_use(engine)
    payload = _checks(events, "SHATTER_THE_CHANT")[0].payload
    assert payload["roll_kind"] == "dc_check" and payload["dc"] == 1, payload
    assert payload["success"] is True and payload["margin"] >= 5, payload
    assert _resonance(engine), "a success by 5 or more offers Resonance"
    offered = _authority()[SHATTER]["effects"][0]["target_check"]["options"]
    assert [row["label"] for row in offered] == ["its Save DC", "its Cultivation Save DC",
                                                 "its named sphere Save DC"], offered
    assert all(row["kind"] == "dc" for row in offered), offered


def test_the_shatter_the_chant_defender_ai_defends_with_the_highest_save_dc_it_prints():
    """The same corrected ranking on a foe whose own Save DC is the weakest of its three: the AI takes
    the Cultivation/Sphere Save DC rather than the Save DC of 1 it would rather be beaten by."""
    from combat.save_dcs import save_dc

    engine = _shatter_fight(1)
    _ready(engine, AN)
    foe = engine.state.actors[AN]
    bases = {basis: save_dc(engine, foe, basis) for basis in ("save_dc", "cultivation", "sphere")}
    assert bases["save_dc"] < max(bases.values()), bases  # the fixture must really have a weakest gate
    events = _spoken_use(engine)
    payload = _checks(events, "SHATTER_THE_CHANT")[0].payload
    assert payload["dc"] == max(bases.values()), (payload, bases)


def test_meeting_a_printed_save_dc_exactly_is_a_success():
    """Owner 2026-10-05 (AUTO16r1 review, finding 2): a fixed difficulty is met by reaching it, so a
    Sound Check whose total equals the DC wins. Rolled checks keep their own rule (a tie still holds),
    which tests/test_a11_contests.py covers separately. Both runs below are the same seeded fight, so
    the second asks for a gate that lands exactly on the total the first one rolled."""
    engine = _shatter_fight(1)
    _force_printed_dc(engine)
    rolled = _checks(_spoken_use(engine), "SHATTER_THE_CHANT")[0].payload["actor"]["total"]

    engine = _shatter_fight(rolled)  # its Save DC is now exactly that total
    _force_printed_dc(engine)
    payload = _checks(_spoken_use(engine), "SHATTER_THE_CHANT")[0].payload
    assert payload["dc"] == rolled, payload
    assert payload["actor"]["total"] == rolled, payload
    assert payload["margin"] == 0, payload
    assert payload["success"] is True, payload
    assert payload["tied"] is False, "meeting a fixed difficulty is a success, not a draw"
    assert not _resonance(engine), "the printed Resonance rider still needs a margin of 5 or more"


def test_shatter_the_chant_loses_when_the_printed_dc_is_out_of_reach():
    engine = _shatter_fight(40)
    _with_provider(engine, lambda request, options: _by_label(request, options, "its Save DC"))
    events = _spoken_use(engine)
    payload = _checks(events, "SHATTER_THE_CHANT")[0].payload
    assert payload["dc"] == 40 and payload["success"] is False, payload
    assert not _resonance(engine), "a lost contest applies nothing"


def test_the_resonance_at_a_margin_of_five_is_the_casters_choice():
    """"You may also apply Resonance": a printed may is asked, not paid out."""
    engine = _shatter_fight(1)
    _force_printed_dc(engine)

    def skip_resonance(request, options):
        if request["reaction_source_id"] == "choice:needle.contest_optional":
            return _by_label(request, options, "Skip Resonance on the triggering creature")
        return None

    asked = _with_provider(engine, skip_resonance)
    _spoken_use(engine)
    optional = [r for r in asked if r["reaction_source_id"] == "choice:needle.contest_optional"]
    assert optional, [r["reaction_source_id"] for r in asked]
    prompt = (optional[0].get("choice_trigger") or {}).get("prompt") or ""
    assert not _resonance(engine), "declining the printed may must leave nothing behind"

    # Owner 2026-10-05 (AUTO16r1 review, finding 4): the question a player answers has to say what
    # triggered it and what accepting does. Resonance is a mark, it is free, and it lasts a stated
    # while; before this the prompt named only the ability and the creature.
    assert "Shatter the Chant" in prompt, prompt
    assert "Breath of No Distance" in prompt, "the ability whose voice triggered this is not named"
    assert "Resonance" in prompt, prompt
    assert "The check was won by " in prompt and " or more." in prompt, prompt
    assert "mark" in prompt and "Sound abilities" in prompt, prompt
    assert "costs you nothing extra" in prompt, prompt
    assert "until the end of your next turn" in prompt, prompt

    # Nothing answering takes the printed benefit, which is what an AI combatant chooses.
    engine = _shatter_fight(1)
    _force_printed_dc(engine)
    _spoken_use(engine)
    assert _resonance(engine)


def test_the_optional_resonance_prompt_reads_from_its_own_typed_row():
    """The explanation is typed data, not a per-ability string in the plug-in: the row carries it, so
    another ability's printed "you may" reads the same way."""
    rider = _authority()[SHATTER]["effects"][0]["success_by"][0]
    assert rider["optional"] is True and rider["margin"] == 5, rider
    assert "Resonance" in rider["label"] and rider["reading"], rider
    assert "mark" in rider["reading"] and "until the end of your next turn" in rider["reading"], rider


def test_the_printed_dc_is_recorded_as_a_difficulty_in_the_fight_log():
    """A player reading the log sees a number they can check, not a second d20."""
    from combat.history_feed import format_history_feed

    engine = _chant_fight(foe_dc=1)
    _force_printed_dc(engine)
    _spoken_use(engine)
    events = [e.model_dump(mode="json") for e in engine.events]
    rows = format_history_feed(events, [], pre_state=None, post_state=engine.state.model_dump(mode="json"),
                               actor_names={ME: "Sound caster", AN: "Speaker"},
                               definition_names={"TAL_SOUND_COUNTER_CHANT": "Counter-Chant"})
    lines = [row.get("summary") or "" for row in rows]
    said = [line for line in lines if "Counter-Chant" in line and "against" in line]
    assert said, lines
    assert "against 1 (its Save DC; Sound Check)" in said[0], said[0]
    assert "d20" not in said[0].split("against")[1], said[0]


def test_silence_before_sound_silences_a_hostile_and_leaves_an_ally_alone():
    """"hostile verbal components fail; hostile Voice talents fail": the field denies the voices of
    hostiles only, so an ally standing in the same field keeps its own."""
    engine = _squad([FIRST_SOUND], cl=18, foe_at=(5, 6), ally_at=(4, 6))
    _use(engine, "The First Sound Before Heaven: Silence-Before-Sound Mode at 5,6",
         contains=True, target=None, destination=(5, 6))
    zone = _zone(engine)
    from combat import speech, zones

    for actor_id in (AN, ALLY1):
        actor = engine.state.actors[actor_id]
        actor.position = actor.position.model_copy(update={"x": zone.center.x, "y": zone.center.y})
    zones.sync_inside(engine, zone.source_definition_id)
    assert "Breath of No Distance" not in _names(engine, AN), "a hostile voice still works inside the field"
    assert "Breath of No Distance" in _names(engine, ALLY1), "an ally's voice must not be silenced"
    assert speech.silenced(engine.state.actors[AN])
    assert not speech.silenced(engine.state.actors[ALLY1])
    assert not speech.silenced(engine.state.actors[ME]), "the caster's own voice is not hostile"
    # Leaving the field gives the hostile its voice back.
    engine.state.actors[AN].position = engine.state.actors[AN].position.model_copy(update={"x": zone.center.x + 25})
    zones.sync_inside(engine, zone.source_definition_id)
    assert "Breath of No Distance" in _names(engine, AN)


def _squad(talents, *, cl, foe_at, ally_at, foe_talents=(AIR_VOICE,), foe_sphere=AIR, foe_dc=16):
    """A Sound caster, an allied voice-talent character and a hostile, all in one engine."""
    from combat.gate4_engine import Gate4ControllerEngine

    mine = _bundle(SOUND, talents, cl=cl, dc=50, actor_id=ME)
    ally = _bundle(SOUND, [AIR_VOICE], cl=cl, dc=50, actor_id=ALLY1, kit={"starting_kit": {"items": []}})
    foe = _foe_bundle(foe_talents, foe_sphere, dc=foe_dc)
    engine = Gate4ControllerEngine(ROOT, match_seed="AUTO16f1", typed_bundles=(mine, ally, foe),
                                   roster_setup={"primary_actor_ids": [ME, ALLY1, AN],
                                                 "team_by_actor": {ME: "team:a", ALLY1: "team:a", AN: "team:b"},
                                                 "starting_positions": {ME: {"x": 3, "y": 6},
                                                                         ALLY1: {"x": ally_at[0], "y": ally_at[1]},
                                                                         AN: {"x": foe_at[0], "y": foe_at[1]}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    target = engine.state.actors[AN]
    target.armor_class = -50
    target.maximum_hp = target.current_hp = 400
    t._ready(engine)
    return engine


def _closer_candidates(engine, holder=AN, toward=ME):
    _ready(engine, holder)
    return [c for c in engine.legal_candidates()
            if c.actor_id == holder and c.display_name.startswith("Move")
            and (c.destination.x, c.destination.y) == (engine.state.actors[holder].position.x - 5,
                                                        engine.state.actors[holder].position.y)]


def _held_at_distance():
    """A Sound caster that has already used Name-Striking Tone's fourth printed rider on the foe."""
    engine = _fight(SOUND, [TONE], dc=FAIL, foe_at=(6, 6))
    _use(engine, "Name-Striking Tone: Kept at Distance", contains=True)
    assert [c for c in engine.state.actors[AN].conditions.values()
            if c.condition_id == "condition:typed.no_approach"], "the fixture applied nothing"
    return engine


def test_kept_at_distance_binds_even_when_the_holder_cannot_see_its_source():
    """"cannot willingly move closer to you": the printed line has no sight exception, so losing sight
    of the creature that applied it releases nothing. Frightened's own exception is untouched."""
    from combat.target_knowledge import can_see

    engine = _held_at_distance()
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    assert can_see(engine, foe, me), "the fixture must start in sight"
    assert not _closer_candidates(engine), "the printed rider is not enforcing anything"
    engine._apply_condition(me, "condition:typed.invisible", "test:shroud", me.entity_id,
                            expires_on="UNTIL_REMOVED")
    assert not can_see(engine, foe, me), "the fixture must really lose the sight line"
    assert not _closer_candidates(engine), "losing sight released Kept at Distance"

    # Frightened keeps its printed exception: out of sight, a step closer is legal again.
    engine = _fight(SOUND, [], foe_at=(6, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    engine._apply_condition(foe, "condition:typed.frightened", "test:fear", me.entity_id,
                            expires_on="UNTIL_REMOVED")
    engine._apply_condition(me, "condition:typed.invisible", "test:shroud", me.entity_id,
                            expires_on="UNTIL_REMOVED")
    assert not can_see(engine, foe, me)
    assert _closer_candidates(engine), "Frightened still needs its source in sight"


def test_a_creature_kept_at_distance_cannot_teleport_itself_closer_but_a_frightened_one_may():
    """The printed rider restricts willingly moving closer, and a teleport the holder chooses is one."""
    from combat.ext import approach_restriction

    engine = _held_at_distance()
    foe = engine.state.actors[AN]
    start = foe.position
    assert approach_restriction.approach_restriction(
        engine, foe, start, start.model_copy(update={"x": start.x - 5})) is False
    assert approach_restriction.approach_restriction(
        engine, foe, start, start.model_copy(update={"x": start.x + 5})) is None

    engine = _fight(SOUND, [], foe_at=(6, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    engine._apply_condition(foe, "condition:typed.frightened", "test:fear", me.entity_id,
                            expires_on="UNTIL_REMOVED")
    start = foe.position
    assert approach_restriction.approach_restriction(
        engine, foe, start, start.model_copy(update={"x": start.x - 5})) is None, \
        "Frightened's printed rule is about steps, not teleports"


def test_the_approach_restriction_is_inert_without_the_condition():
    """No Kept at Distance condition, nothing to enforce, whoever asks."""
    from combat.ext import approach_restriction

    engine = _fight(SOUND, [], foe_at=(6, 6))
    foe = engine.state.actors[AN]
    start = foe.position
    assert approach_restriction.approach_restriction(engine, foe, start,
                                                    start.model_copy(update={"x": start.x - 5})) is None


def test_kept_at_distance_names_a_turn_the_engine_actually_ends():
    """"until the end of your next turn": the expiry is the caster's next turn end, in the sealed engine's own
    clock name, so the restriction cannot outlive the fight by accident."""
    from tests.test_expiry_names import unknown

    engine = _held_at_distance()
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    held = [c for c in foe.conditions.values() if c.condition_id == "condition:typed.no_approach"][0]
    assert held.expires_on == f"END_OF_SOURCE_TURN_AT:{me.turns_started + 1}", held.expires_on
    assert not unknown(held.expires_on), held.expires_on
    # The turn counter the name names is the caster's, not the holder's.
    assert foe.turns_started == 0 and me.turns_started >= 1, (foe.turns_started, me.turns_started)


def test_kept_at_distance_survives_a_table_commit_and_a_disk_reload(tmp_path):
    """The restriction is stored state, so it is proven through the table with the real ability: an
    accepted Name-Striking Tone option applies it, the fight is reopened from storage, the pill says the
    printed sentence, the reloaded engine still refuses a step closer while offering a step away, and
    the condition ends at the printed turn instead of lasting the fight."""
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    from tests.test_lock2_persistence import act
    from tests.test_tabletop_hunt6 import LEFT, RIGHT, table_fight

    combat, table, mid = table_fight(tmp_path, [TONE], cl=17)

    def committed_option(text):
        state = table.state(mid)
        menu = state["menu"]
        group = next(g for g in menu["actions"] if text in g["label"])
        option = next(o for o in group["options"] if RIGHT in (o.get("target_ids") or ()))
        from tests.worker2_support import settle
        settle(table, mid, option["candidate_id"], picks={
            "choice:needle.sound_name_known": "known",
            "choice:needle.sound_name_failure": "distance"})

    committed_option("Name-Striking Tone")

    combat = CombatService(ROOT, tmp_path)          # a fresh service: the fight is read back from disk
    session = combat._load_session(mid)
    assert session.verify()["status"] == "PASS"
    engine = session.engine
    source = engine.state.actors[LEFT]
    mover = engine.state.actors[RIGHT]
    held = [c for c in mover.conditions.values() if c.condition_id == "condition:typed.no_approach"]
    assert len(held) == 1, held
    assert held[0].expires_on == f"END_OF_SOURCE_TURN_AT:{source.turns_started + 1}", held[0].expires_on
    assert held[0].source_actor_id == LEFT, held[0].source_actor_id
    from tests.test_expiry_names import unknown

    assert not unknown(held[0].expires_on), held[0].expires_on

    state = TabletopService(combat, tmp_path).state(mid)
    holder = next(a for a in state["presentation"]["actors"] if a["entity_id"] == RIGHT)
    row = next(c for c in holder["conditions"] if c["condition_id"] == "condition:typed.no_approach")
    assert "cannot willingly move closer" in row["rule_text"], row["rule_text"]
    assert "in sight or not" in row["rule_text"], row["rule_text"]  # the printed line has no sight exception
    assert "(GM)" not in row["rule_text"], row["rule_text"]
    assert row["applied_by"] == "Left"

    # The reloaded fight still enforces it for the creature that was held: no step toward the caster,
    # and walking away is still on the menu. (This fixture's actors are the table's, so the turn is
    # handed over directly rather than through the module's own _ready helper.)
    engine.state.current_slot_index = engine.state.initiative_order.index(RIGHT)
    engine.state.current_actor_id = RIGHT
    steps = [c for c in engine.legal_candidates()
             if c.actor_id == RIGHT and c.display_name.startswith("Move")]
    assert steps, "the reloaded fight offers the holder no movement at all"
    held_at = engine.grid.distance_ft(engine.state.actors[RIGHT].position, source.position)
    assert all(engine.grid.distance_ft(c.destination, source.position) >= held_at for c in steps), [
        (c.display_name, (c.destination.x, c.destination.y)) for c in steps]
    assert any(engine.grid.distance_ft(c.destination, source.position) > held_at for c in steps), \
        "walking away must still work after the reload"

    # And it ends at its printed boundary rather than lasting the rest of the fight. Owner 2026-10-05
    # (AUTO16r2 review, finding 2): accepting the disappearance on any of eight end-turn commits cannot
    # see an off-by-one. The boundary is therefore read from the printed rule ("until the end of your
    # next turn" -- the caster's turn after the one it was cast on) and the fight is driven against it on
    # every commit: present for the whole of that turn, gone the moment that turn ends, and no later.
    expected_name = f"END_OF_SOURCE_TURN_AT:{source.turns_started + 1}"
    assert held[0].expires_on == expected_name, (held[0].expires_on, expected_name)
    boundary = source.turns_started + 1
    assert source.turns_started == 1, source.turns_started   # the fixture cast it on the caster's first turn
    gone_at = None
    for step in range(1, 9):
        assert act(table, mid, "end")["status"] == "COMMITTED"
        live = CombatService(ROOT, tmp_path)._load_session(mid).engine
        caster = live.state.actors[LEFT]
        its_turn = live.state.current_actor_id == LEFT
        held_now = [c for c in live.state.actors[RIGHT].conditions.values()
                    if c.condition_id == "condition:typed.no_approach"]
        # END_OF_SOURCE_TURN_AT:N is the end of the caster's Nth turn, so it holds for the whole of that
        # turn and not one commit longer.
        expected = caster.turns_started < boundary or (caster.turns_started == boundary and its_turn)
        assert bool(held_now) is expected, (
            f"step {step}: caster on turn {caster.turns_started} (its turn {its_turn}), printed boundary "
            f"{boundary}, restriction present {bool(held_now)}")
        if held_now:
            assert held_now[0].expires_on == expected_name, held_now[0].expires_on
        else:
            gone_at = step
            break
    assert gone_at is not None, "Kept at Distance outlived the caster's next turn"
    state = TabletopService(combat, tmp_path).state(mid)
    holder = next(a for a in state["presentation"]["actors"] if a["entity_id"] == RIGHT)
    assert not [c for c in holder["conditions"] if c["condition_id"] == "condition:typed.no_approach"], \
        "the expired condition is still on the sheet after its printed turn ended"


def _void_step_hops(engine):
    """The teleport destinations the held creature's own Empty Step talent is offering, by "x,y"."""
    _ready(engine, AN)
    return {f"{c.destination.x},{c.destination.y}": c for c in engine.legal_candidates()
            if c.actor_id == AN and c.destination and c.display_name.startswith("Empty Step")}


def test_a_teleport_the_holder_chooses_is_refused_when_it_lands_it_closer():
    """"cannot willingly move closer to you": the veto runs on the real teleport action, not only when
    the guard is called by hand (AUTO16r1 review, finding 3). The ability is registered, a landing
    square closer to the caster is refused with a plain line and no move, and a square away still works."""
    VOID_STEP = "TAL_VOID_EMPTY_STEP"

    engine = _fight(SOUND, [TONE], dc=FAIL, foe_talents=(VOID_STEP,), foe_sphere="tianxia.sphere.void",
                    foe_at=(6, 6))
    assert "5,6" in _void_step_hops(engine), "the fixture offers no teleport to the closer square"
    _use(engine, "Name-Striking Tone: Kept at Distance", contains=True)
    assert "5,6" in _void_step_hops(engine), "the printed rider hid the ability instead of refusing the hop"

    closer = _void_step_hops(engine)["5,6"]
    before = len(engine.events)
    start = engine.state.actors[AN].position
    _use(engine, closer.display_name, actor_id=AN, target=None, destination=(5, 6))
    assert engine.state.actors[AN].position == start, "a refused teleport still moved the creature"
    said = [str(e.payload.get("text") or e.payload.get("log") or "") for e in engine.events[before:]
            if e.event_type == "PASSIVE_TRIGGERED"]
    assert any("cannot teleport closer" in line for line in said), said

    # The same creature may still teleport away on its next turn.
    _start_turn(engine, AN)
    away = _void_step_hops(engine)["10,6"]
    _use(engine, away.display_name, actor_id=AN, target=None, destination=(10, 6))
    assert (engine.state.actors[AN].position.x, engine.state.actors[AN].position.y) == (10, 6), \
        "teleporting away is not a closer approach and must still work"


def test_the_silence_field_commits_through_the_table_reloads_and_ends_with_its_concentration(tmp_path):
    """The area is stored state, so it is proven through the table with the real ability: an accepted
    True Silence is committed, the fight is reopened from storage with the field and the creature's
    inside state intact, and it ends when its printed one minute of Concentration does."""
    from combat import speech, zones
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    from tests.test_lock2_persistence import act
    from tests.test_tabletop_hunt6 import LEFT, RIGHT, table_fight

    combat, table, mid = table_fight(tmp_path, [TRUE_SILENCE], cl=17)
    state = table.state(mid)
    menu = state["menu"]
    group = next(g for g in menu["actions"] if "True Silence" in g["label"])
    option = group["options"][0]
    assert table.act(mid, option["candidate_id"], menu["decision_id"], menu["state_version"],
                     state["last_sequence"], [])["status"] == "COMMITTED"

    combat = CombatService(ROOT, tmp_path)          # a fresh service: the fight is read back from disk
    session = combat._load_session(mid)
    assert session.verify()["status"] == "PASS"
    engine = session.engine
    mine = [zone for zone in zones.typed_zones(engine) if zone.owner_id == LEFT]
    assert len(mine) == 1, [zone.source_definition_id for zone in mine]
    assert mine[0].trigger_profile.get("name") == "True Silence", mine[0].trigger_profile.get("name")
    inside = engine.state.actors[RIGHT]
    assert [c for c in inside.conditions.values() if c.condition_id == ZONE_EFFECT], \
        [c.condition_id for c in inside.conditions.values()]
    assert speech.silenced(inside), "the reloaded fight forgot who is standing in the silence"
    held = TabletopService(combat, tmp_path).state(mid)["presentation"]["actors"]
    pill = next(c for c in next(a for a in held if a["entity_id"] == RIGHT)["conditions"]
                if c["condition_id"] == ZONE_EFFECT)
    assert "voice" in pill["rule_text"], pill["rule_text"]

    # The field is Concentration for up to a minute, so it must not outlive that by accident. Owner
    # 2026-10-05 (AUTO16r2 review, finding 2): accepting the disappearance on any of 39 commits cannot
    # see an off-by-one. The boundary is therefore read from the printed rule (Concentration, up to 1
    # minute = ten rounds of the shared clock, in the slot the field was cast in) and asserted against the
    # recorded timer; the fight is then driven commit by commit to that exact round and slot, and the
    # recorded reason separates its own clock from a Concentration ended some other way.
    from combat.ext import effect_durations
    from combat.typed_executor import duration_round_count

    zone = mine[0]
    minutes = duration_round_count("minutes", 1)
    assert minutes == 10, minutes                                   # "up to 1 minute"
    assert zone.duration_rounds == minutes, zone.duration_rounds
    assert zone.concentration_link is True, zone.concentration_link
    owner_slot = engine.state.initiative_order.index(LEFT)
    deadline = [c for c in engine.state.actors[LEFT].conditions.values()
                if c.condition_id == "condition:typed.concentration_deadline"]
    assert len(deadline) == 1, [c.condition_id for c in engine.state.actors[LEFT].conditions.values()]
    boundary = (zone.created_round + minutes, owner_slot)
    assert effect_durations.parse_round(deadline[0].expires_on) == boundary, (
        deadline[0].expires_on, boundary)
    gone_at = None
    for step in range(1, 40):
        assert act(table, mid, "end")["status"] == "COMMITTED"
        live = CombatService(ROOT, tmp_path)._load_session(mid).engine
        field = [row for row in zones.typed_zones(live) if row.owner_id == LEFT]
        # The timer is due at (round boundary) slot boundary, so the field is still there for the whole
        # of the round before and gone from the first commit at or after it.
        due = (live.state.round_number, live.state.current_slot_index) >= boundary
        assert bool(field) is not due, (
            f"step {step}: round {live.state.round_number} slot {live.state.current_slot_index}, printed "
            f"boundary {boundary}, field present {bool(field)}")
        if not field:
            gone_at = step
            break
    assert gone_at is not None, "True Silence outlived its printed Concentration"
    end = CombatService(ROOT, tmp_path)._load_session(mid).engine
    ended = [e for e in end.events if e.event_type == "ZONE_REMOVED" and e.payload.get("zone_id") == zone.zone_id]
    assert [(e.payload or {}).get("reason") for e in ended] == ["DURATION_ENDED"], [
        (e.payload or {}).get("reason") for e in ended]
    concentrations = [e for e in end.events if e.event_type == "CONCENTRATION_ENDED" and e.actor_id == LEFT]
    assert [(e.payload or {}).get("reason") for e in concentrations] == ["DURATION_ENDED"], [
        (e.payload or {}).get("reason") for e in concentrations]
    shown = TabletopService(combat, tmp_path).state(mid)["presentation"]["actors"]
    assert not [c for c in next(a for a in shown if a["entity_id"] == RIGHT)["conditions"]
                if c["condition_id"] == ZONE_EFFECT], \
        "the expired field is still marked on the sheet"

"""Observer information and masking at the table (A2R13), after the independent review round.

Printed text (owner text, APP/authority/typed_mechanics/rules_text.json):

  TAL_THE_HIDDEN_EYE_MAGICAL_COGNIZANCE
    "Range: 10 feet. You may use the Search action to detect the presence and general location of an ongoing magical
     effect within range. If the effect does not provide a DC, use the creator's Cultivation Save DC or spell save DC.
     If no such DC exists, use DC 15. A successful check reveals that a magical effect is active and its general
     location. It does not automatically identify the effect, its creator, its school, its sphere, its duration, or a
     method of ending it. While you hold Martial Focus, calculate your Passive Cognizance as 10 + your highest bonus
     among Intelligence (Investigation), Wisdom (Perception), and Wisdom (Survival)."

  TAL_THE_HIDDEN_EYE_SPIRIT_TRACE_PURSUIT
    "When you successfully Analyze a creature through Spirit-Trace Pursuit, you also learn the direction in which the
     trace continued when it left the scene. Spirit-Trace Pursuit does not reveal the creature's exact location and
     does not create a permanent tracking mark."

  TAL_AIR_INVISIBLE_BLADE_CURRENT
    "A creature with blindsight, tremorsense that can read air pressure, Wind-Sense, or a comparable feature may have
     Advantage on this check."

Every case drives a real compiled character on a real TabletopService through session ``act`` and cold-reloads the
saved fight, so these are table commits rather than unit calls. The review rounds that followed this file ask for
regressions that cannot pass without exercising the behaviour, so no test here returns early on a lost roll, no test
edits ``engine.typed_passive_rows`` to fake a printed feature, and every assertion is read from a receipt or log line
the engine actually recorded. Each test states which failure it is built to catch.

Round 3 added the two cases the second review named, and both were checked against the pre-fix commit to confirm they
fail without the fix:

  * ``test_search_reports_only_what_the_creature_can_perceive`` runs the same fight with and without a sight-blocking
    pillar between the searching owner and the hidden foe. The foe is inside the printed 10 feet in both runs, so the
    barrier is the only difference, and the blocked run must lose the effects its anchor hides.
  * ``test_ordinary_movement_is_not_a_scene_departure`` has the target walk and stay, so it never left the scene.
    The old code answered "left this scene to the <direction>" from any committed step.
  * ``test_trace_reports_the_direction_a_real_departure_ran_on`` banishes the target for real, so the engine records
    that it left the field, and requires the learned direction to equal the ground it covered *before* going and to be
    stored as a value that survives the cold reload.
"""
import pytest

from combat.ext.air_currents import reads_air
from combat.ext.eye_awareness import (COGNIZANCE, TRACE_PURSUIT, TRACE_CHARACTERISTIC, compass,
                                      passive_cognizance)
from combat.ext.mind_hidden_eye import FOCUS
from tests.h1_support import sheet
from tests.test_a2_hidden_eye_fix_round import BASE
from tests.worker2_support import ALLY as ALLY_ID, FOE, OWNER, candidate, fixture, reload, settle, turn

COGNIZANCE_TALENT = "TAL_THE_HIDDEN_EYE_MAGICAL_COGNIZANCE"
TRACE_TALENT = "TAL_THE_HIDDEN_EYE_SPIRIT_TRACE_PURSUIT"
DARK = ["DARK_BASE_DARKNESS", "TAL_DARK_PURE_DARKNESS"]
APPROACH = "choice:needle.eye_approach"
LEARN = "choice:needle.eye_learn"
AIR_OWNER = ["AIR_BASE_GATHER_CURRENT", "AIR_BASE_WIND_LASH", "TAL_AIR_INVISIBLE_BLADE_CURRENT"]
GATHER = "Gather Current: Carry"
LASH = "Wind Lash: Cut"
BLADE_CHOICE = "choice:invisible_blade"
#: A real printed Path/Subpath feature that grants plain Tremorsense 30 feet. Its text is about vibrations through
#: connected ground, so it is exactly the "tremorsense that cannot read air pressure" the printed rule excludes.
GROUND_TREMORSENSE = "tianxia.subpath.qi.mountain_core_cultivator.feature.stone_sense"


def cognizance_checks(engine):
    """The Magical Cognizance receipts this fight actually recorded."""
    return [e for e in engine.events
            if e.event_type == "CHECK_ROLLED" and e.source_definition_id == COGNIZANCE]


def trace_lines(engine):
    return [str(e.payload.get("log") or "") for e in engine.events
            if e.event_type == "PASSIVE_TRIGGERED" and e.source_definition_id == TRACE_PURSUIT]


def cognition_lines(engine):
    return [str(e.payload.get("log") or "") for e in engine.events
            if e.event_type == "PASSIVE_TRIGGERED" and e.source_definition_id == COGNIZANCE]


#: The searching owner stands 10 feet from the foe's square, where the ally's Darkness lands. The foe must be
#: more than 5 feet from any enemy to be offered Hide, and the effect must be within the printed 10 feet of
#: the Searcher: 10 feet satisfies both at once.
def sharp_eyes(bundles):
    """Give the searching owner an Investigation bonus that clears the printed DC on any d20.

    These tests are about what a *successful* Search is allowed to learn. With an ordinary bonus the check can lose
    its contest against DC 15 and the regression would silently stop exercising the thing it guards.
    """
    bundles[0]["skills"] = {"Investigation": 20}


PLACES = {OWNER: {'x': 3, 'y': 6}, ALLY_ID: {'x': 4, 'y': 6}, FOE: {'x': 3, 'y': 8}}


def cognizance_fight(tmp_path, seed, *, talents=(BASE, COGNIZANCE_TALENT), **kwargs):
    """The owner holds Magical Cognizance and searches; the ally supplies the magical effect to be sensed."""
    return fixture(tmp_path, list(talents) + DARK, ally_talents=DARK, cl=15, seed=seed,
                   foe_sheet=stealthy_foe(), positions=dict(PLACES), **kwargs)


def commit(table, mid, combat, label, *, target=None, at=None, picks=None):
    """Commit one real table candidate and answer whatever it raises, returning the prompts it raised."""
    engine = combat._load_session(mid).engine
    rows = [c for c in engine.legal_candidates()
            if getattr(engine.action_catalog.get(c.source_definition_id), "display_name", None) == label
            and (target is None or c.target_ids == (target,))
            and (at is None or c.destination and (c.destination.x, c.destination.y) == at)]
    assert rows, f"{label!r} was not a legal table action here"
    return settle(table, mid, rows[0].candidate_id, picks=picks)


# --------------------------------------------------------------------------- a pure reading of the bearing
@pytest.mark.parametrize("dx,dy,expected", [
    (0, -5, "north"), (0, 5, "south"), (5, 0, "east"), (-5, 0, "west"),
    (4, 4, "south-east"), (-4, 4, "south-west"), (0, 0, "here"),
])
def test_bearing_words_are_player_readable(dx, dy, expected):
    """The direction is spoken, not printed as squares: a player has to be able to act on it."""
    assert compass(dx, dy) == expected


# --------------------------------------------------------------------------- Magical Cognizance
def stealthy_foe():
    """A foe whose Stealth check clears DC 15 on any d20, so the hide it attempts really lands.

    Without this the test would be a coin flip on the foe's Hide roll, and the printed ability under test
    (Magical Cognizance) would only sometimes run.
    """
    document = sheet([], cl=15)
    stats = document["ability_scores_and_statistics"]
    stats["skills"] = [{"skill": "Stealth", "bonus": 40}, {"skill": "Perception", "bonus": 4}]
    return document


def darken(combat, table, mid, searcher=OWNER):
    """Put a real ongoing magical effect next to ``searcher``, cast by *another* creature.

    The owner cannot be the caster: a Search never detects its own working (that is what "someone else put on the
    field" means), and a Search that only ever saw its own magic would prove nothing about the talent. So the ally
    lays ordinary magical Darkness on the foe's square -- a real ongoing magical effect, exactly what the printed
    talent is written to notice -- while the searching creature stands one square away, and the foe then takes its
    real Hide action there. The ally's own "shaping" condition is ordinary state with no sphere behind it, so it is
    there too as the thing the talent must *not* report.
    """
    turn(table, mid, ALLY_ID)
    settle(table, mid, candidate(combat, mid, "Shape Darkness: Pure Darkness").candidate_id)
    engine = combat._load_session(mid).engine
    spot = engine.state.actors[FOE].position
    settle(table, mid, candidate(combat, mid, "Darkness", at=(spot.x, spot.y)).candidate_id)
    for _ in range(8):
        turn(table, mid, FOE)
        engine = combat._load_session(mid).engine
        if any(c.condition_id == "condition:typed.hidden" for c in engine.state.actors[FOE].conditions.values()):
            return True
        hidden = [c for c in engine.legal_candidates()
                  if getattr(engine.action_catalog.get(c.source_definition_id), "display_name", None) == "Hide"]
        if not hidden:
            continue
        settle(table, mid, hidden[0].candidate_id)
    engine = combat._load_session(mid).engine
    return any(c.condition_id == "condition:typed.hidden" for c in engine.state.actors[FOE].conditions.values())


def test_search_senses_the_magical_effect_and_quotes_the_printed_dc(tmp_path):
    """A Search by a Cognizance owner detects the ongoing magical effect and rolls against the printed DC.

    Catches the review's finding 1 and 6: the effect must actually be sensed, each one gets its own check, and the
    line must report a bearing without naming the creature that carries it.
    """
    combat, table, mid = cognizance_fight(tmp_path, "A2R13-COGNIZANCE", bundle_transform=sharp_eyes)
    assert darken(combat, table, mid), "the foe never became hidden, so no Search was possible"
    turn(table, mid, OWNER)
    settle(table, mid, candidate(combat, mid, "Search").candidate_id)
    engine = reload(tmp_path, mid)

    checks = cognizance_checks(engine)
    assert checks, "Magical Cognizance rolled no check on a Search that had an ongoing magical effect to sense"
    # "use the creator's Cultivation Save DC or spell save DC. If no such DC exists, use DC 15": the sensed effect
    # carries no DC of its own, so the printed order falls through to the creature that put it on the field.
    from combat.save_dcs import save_dc

    live = combat._load_session(mid).engine
    for payload in (check.payload for check in checks):
        assert payload["check"] == "Investigation"
        assert payload["dc"] in (15, save_dc(live, live.state.actors[FOE]))
    reported = [line for line in cognition_lines(engine) if "senses an ongoing magical effect" in line]
    successes = [check.payload for check in checks if check.payload["success"]]
    assert bool(reported) == bool(successes), "a line was written with no successful check behind it"
    # Every effect gets its own check (there is no printed ceiling), so each line quotes the receipt it came from.
    for line in reported:
        assert "its nature, source and ending are still unknown" in line
        assert any(f"({receipt['actor']['total']} against DC {receipt['dc']})" in line for receipt in successes), \
            f"the line quotes a total or DC that no successful receipt recorded: {line}"


def test_a_sensed_effect_is_never_named_to_its_carrier(tmp_path):
    """Finding 1: the printed line reveals "its general location" and withholds identity, including whose it is.

    The old implementation printed ``on <creature>``, which answered a question the talent explicitly does not.
    This fails if any carrier name, effect name or creator name reaches the player.
    """
    combat, table, mid = cognizance_fight(tmp_path, "A2R13-NONAME", bundle_transform=sharp_eyes)
    assert darken(combat, table, mid)
    turn(table, mid, OWNER)
    settle(table, mid, candidate(combat, mid, "Search").candidate_id)
    engine = reload(tmp_path, mid)
    reported = [line for line in cognition_lines(engine) if "senses an ongoing magical effect" in line]
    assert reported, "nothing was sensed, so the leak this guards against cannot be observed"
    live = combat._load_session(mid).engine
    carriers = {actor.display_name for actor in live.state.actors.values()}
    for line in reported:
        assert not any(f"on {name}" in line or f"from {name}" in line for name in carriers), line
        assert "Darkness" not in line, "the effect's own identity is printed, which the ability withholds"


def test_a_mundane_condition_is_not_a_magical_effect(tmp_path):
    """Finding 1: only *magical* effects are sensed, so ordinary state never surfaces as a magical aura.

    The owner shapes Pure Darkness first, which leaves a real sourced ``shaping`` condition on the field that belongs
    to no sphere. A Search must not roll for it, and must not report it as an ongoing magical effect.
    """
    combat, table, mid = fixture(tmp_path, [BASE, COGNIZANCE_TALENT] + DARK, cl=15, seed="A2R13-MUNDANE",
                                  foe_sheet=stealthy_foe(), foe_position={"x": 3, "y": 8})
    turn(table, mid, OWNER)
    settle(table, mid, candidate(combat, mid, "Shape Darkness: Pure Darkness").candidate_id)
    engine = combat._load_session(mid).engine
    from combat.ext.eye_awareness import effect_is_magical

    shaping = [c for a in engine.state.actors.values() for c in a.conditions.values()
               if c.condition_id == "condition:typed.shaping"]
    assert shaping, "the shaping condition this test relies on was never applied"
    assert not any(effect_is_magical(engine, c) for c in shaping), \
        "a non-sphere condition would be reported as a magical effect, which is the leak being fixed"


def test_search_without_cognizance_rolls_no_magical_check(tmp_path):
    """The talent is what adds the magical half of a Search; a plain Searcher never rolls it."""
    combat, table, mid = fixture(tmp_path, [BASE] + DARK, ally_talents=DARK, cl=15, seed="A2R13-NOCOGNIZANCE",
                                  foe_sheet=stealthy_foe(), positions=dict(PLACES))
    assert darken(combat, table, mid), "the foe never became hidden, so no Search was possible"
    turn(table, mid, OWNER)
    settle(table, mid, candidate(combat, mid, "Search").candidate_id)
    engine = reload(tmp_path, mid)
    assert cognizance_checks(engine) == []


def test_passive_cognizance_uses_the_printed_skill_bonuses(tmp_path):
    """Finding 3: "10 + your highest bonus among Investigation, Perception and Survival" -- skill totals, not modifiers.

    The old formula added the bare Intelligence or Wisdom modifier and dropped proficiency from all three. This gives
    the owner a sheet whose Proficiency and skill bonuses are large and asymmetric, so the printed answer can only be
    reached by reading the three skills.
    """
    def owner_skills(bundles):
        bundles[0]["skills"] = {"Investigation": 14, "Perception": 11, "Survival": 9}

    combat, table, mid = cognizance_fight(tmp_path, "A2R13-PASSIVE", bundle_transform=owner_skills)
    engine = combat._load_session(mid).engine
    assert passive_cognizance(engine, engine.state.actors[OWNER]) == 24, \
        "Passive Cognizance must be 10 + the best of the three printed skill bonuses (10 + 14)"


def test_passive_cognizance_is_reported_only_while_martial_focus_is_held(tmp_path):
    """Finding 3: "While you hold Martial Focus" is the condition, so the number is not offered without it.

    A Search that fails its check must not turn into a detection through the passive score either -- the printed text
    leaves that to the Game Master.
    """
    combat, table, mid = cognizance_fight(tmp_path, "A2R13-FOCUS")
    assert darken(combat, table, mid)
    turn(table, mid, OWNER)
    before = combat._load_session(mid).engine
    holding = before.state.actors[OWNER].resources.get(FOCUS, 0) > 0
    settle(table, mid, candidate(combat, mid, "Search").candidate_id)
    engine = reload(tmp_path, mid)
    live = combat._load_session(mid).engine
    passive_lines = [line for line in cognition_lines(engine) if "Passive Cognizance" in line]
    assert bool(passive_lines) is holding, \
        "the passive score was reported without Martial Focus held, or withheld while it was"
    if holding:
        assert f"Passive Cognizance is {passive_cognizance(before, before.state.actors[OWNER])}" in " ".join(passive_lines)
    # Nothing may claim a detection that no successful check produced.
    for line in cognition_lines(engine):
        assert "would tell you something is there" not in line, \
            "a failed check must not become a passive detection; the printed text leaves that to the GM"


def test_every_qualifying_effect_near_the_searcher_gets_its_own_check(tmp_path):
    """Finding 6: the printed Search puts no ceiling on how many ongoing magical effects it can detect.

    The engine holds several real magical zones here (the Dark owner's court and its Darkness), so the regression is
    that a Search never silently stops after the first few. It fails if any qualifying effect is dropped.
    """
    combat, table, mid = cognizance_fight(tmp_path, "A2R13-NOCAP", bundle_transform=sharp_eyes)
    assert darken(combat, table, mid)
    engine = combat._load_session(mid).engine
    from combat.ext.eye_awareness import ongoing_effects

    qualifying = ongoing_effects(engine, engine.state.actors[OWNER])
    turn(table, mid, OWNER)
    settle(table, mid, candidate(combat, mid, "Search").candidate_id)
    reloaded = reload(tmp_path, mid)
    checks = cognizance_checks(reloaded)
    assert len(checks) == len(qualifying), \
        f"{len(qualifying)} qualifying magical effects were on the field but only {len(checks)} were resolved"
    assert len(checks) > 1, "this fixture did not produce the several nearby effects the cap used to truncate"


#: A real printed Space talent: "Exile Beyond the Horizon" banishes a creature, which is the engine's own record
#: that a creature left the scene (combat/ext/spatial_absence.py, the ``battlefield_presence`` veto). This is the
#: table-reachable way to produce the departure the printed Spirit-Trace clause is about.
EXILE = "tianxia.talent.space.exile_beyond_the_horizon"


def pillar(x, y):
    """A sight-blocking stone pillar on one square, in the arena the fixture builds the fight on.

    The printed pillar regions say exactly this: "cannot be entered and blocks line of sight", so the barrier here is
    the engine's own terrain, not a flag invented for the test.
    """
    def transform(arena):
        arena['terrain_regions'].append({
            "region_id": "test.pillar", "terrain_type": "BLOCKED", "movement_cost": 0,
            "description": "Stone pillar: cannot be entered and blocks line of sight.",
            "cells": [{"x": x, "y": y}]})
    return transform


def test_search_reports_only_what_the_creature_can_perceive(tmp_path):
    """Review round 3, finding 1: an effect sealed behind a wall is not knowledge the creature has.

    The owner ruling of 2026-10-12 says a player learns only what the creature they control can perceive. The old
    gate asked only whether the searcher and the effect's anchor were both standing on the field, so a Search happily
    reported a magical effect on a creature behind a solid pillar -- something the creature had no way to learn. This
    runs the same fight twice, once with the pillar between them and once without, and requires the blocked run to
    lose exactly the effects whose anchor the pillar hides, while the open run keeps them. It fails against any gate
    that does not consult perception.
    """
    # Each fight gets its own directory: the fixture writes a portable character per actor into the path it is
    # given, so two fights cannot share one.
    open_effects = _effects_beside_a_hidden_foe(tmp_path / "open", "A2R13-PERCEIVE-OPEN", None)
    walled = _effects_beside_a_hidden_foe(tmp_path / "walled", "A2R13-PERCEIVE-WALL", pillar(3, 7))
    assert open_effects, "the fixture produced no ongoing magical effect beside the foe, so this proves nothing"

    # The foe's own square is 10 feet away -- inside the printed range -- in both runs, so range is not the difference.
    assert open_effects > walled, \
        f"a stone pillar between the searcher and the foe hid nothing: {walled} effects were still reported"


def _effects_beside_a_hidden_foe(tmp_path, seed, barrier):
    """Run a real Search with the foe hidden 10 feet away and count the checks the table actually recorded.

    The count comes from ``CHECK_ROLLED`` receipts after a cold reload, not from calling the plug-in's own query, so
    this measures what a player would actually be told.
    """
    kwargs = {"battlefield_transform": barrier} if barrier else {}
    tmp_path.mkdir(parents=True, exist_ok=True)
    combat, table, mid = cognizance_fight(tmp_path, seed, bundle_transform=sharp_eyes, **kwargs)
    assert darken(combat, table, mid), "the foe never became hidden, so no Search was possible"
    before = combat._load_session(mid).engine
    owner = before.state.actors[OWNER]
    assert before._distance_actor_to_actor(owner, before.state.actors[FOE]) <= 10, \
        "the foe is outside the printed 10-foot range, so the barrier would not be the reason for any difference"
    turn(table, mid, OWNER)
    settle(table, mid, candidate(combat, mid, "Search").candidate_id)
    engine = reload(tmp_path, mid)
    return len(cognizance_checks(engine))


# --------------------------------------------------------------------------- Spirit-Trace Pursuit
def analyze_foe(table, mid, combat):
    """Take the owner's real Analyze intent against the foe, answering its printed prompts."""
    engine = combat._load_session(mid).engine
    rows = [c for c in engine.legal_candidates()
            if str(getattr(engine.action_catalog.get(c.source_definition_id), "display_name", "")).startswith("Analyze")
            and FOE in c.target_ids]
    assert rows, f"Analyze against the foe was not a legal table action ({len(engine.legal_candidates())} candidates)"
    return settle(table, mid, rows[0].candidate_id,
                  picks={APPROACH: "Investigation", LEARN: "first", "choice:needle.eye_learn": "first"})


def move_foe(combat, table, mid):
    """Make the foe really move, so its trace really does run somewhere.

    Any legal move the engine offers will do: the expected bearing is read back from the movement the engine itself
    committed, so the test never has to know which square was reachable.
    """
    engine = combat._load_session(mid).engine
    start = engine.state.actors[FOE].position
    rows = [c for c in engine.legal_candidates() if c.kind == "MOVE" and c.destination
            and (c.destination.x, c.destination.y) != (start.x, start.y)]
    rows.sort(key=lambda c: (c.destination.z != start.z,
                             abs(c.destination.x - start.x) + abs(c.destination.y - start.y)))
    assert rows, "the foe had no legal move, so its trace never ran anywhere"
    state = table.state(mid)
    result = table.act(mid, rows[0].candidate_id, state['menu']['decision_id'], state['menu']['state_version'],
                       state['last_sequence'], [])
    assert result['status'] == 'COMMITTED', result


def test_ordinary_movement_is_not_a_scene_departure(tmp_path):
    """Review round 3, finding 2: the creature walked and stayed, so it never left the scene.

    This is the regression the old test could not catch. It moved the target and then asserted that the reported
    direction equalled that movement -- which *is* the assumption under review: a creature that merely walked across
    the arena had left no scene, yet the old code answered "left this scene to the <direction>". Nothing may be claimed
    here, and no trace direction may be recorded. It fails against any implementation that treats a committed step as a
    departure.
    """
    def decisive(bundles):
        bundles[0]["skills"] = {"Investigation": 20}

    combat, table, mid = fixture(tmp_path, [BASE, TRACE_TALENT], cl=15, seed="A2R13-MOVED-NOT-GONE",
                                  bundle_transform=decisive,
                                  positions={OWNER: {'x': 3, 'y': 6}, "actor:factory.worker2-ally": {'x': 2, 'y': 6},
                                            FOE: {'x': 6, 'y': 6}})
    turn(table, mid, FOE)
    move_foe(combat, table, mid)
    turn(table, mid, OWNER)
    analyze_foe(table, mid, combat)
    engine = reload(tmp_path, mid)
    live = combat._load_session(mid).engine
    assert any(c.condition_id == "condition:typed.analyzed_by"
               for c in live.state.actors[FOE].conditions.values()), \
        "the Analyze lost its contested check, so the printed clause never fired"
    moves = [e for e in live.events if e.event_type == "MOVEMENT_COMMITTED" and e.actor_id == FOE]
    assert moves, "the foe never moved, so this test's premise (movement, but no departure) no longer holds"
    assert engine._on_battlefield(live.state.actors[FOE]), "the foe must still be on the field for this to be a stay"

    recorded = [c for c in live.state.actors[FOE].conditions.values()
                if (c.data or {}).get("characteristic") == TRACE_CHARACTERISTIC]
    assert recorded == [], "a trace direction was learned from ordinary movement, which is not a departure"
    for line in trace_lines(live):
        assert "left this scene to the" not in line, \
            f"a scene departure was reported for a creature that never left the scene: {line}"


def test_trace_reports_the_direction_a_real_departure_ran_on(tmp_path):
    """Review round 3, finding 2: a real scene departure, and the direction survives a cold reload.

    The ally really banishes the foe, so the engine's own battlefield-presence record says it left the scene; the
    direction learned is the ground it covered *before* going, and it is stored on the learned record as a value so
    later mechanics can read what was learned. The old implementation read the creature's last committed step whatever
    it was -- including the zero-cost teleport a banished creature takes coming back -- and stored only the fact's
    name, so this fails against it on both counts.
    """
    def decisive(bundles):
        bundles[0]["skills"] = {"Investigation": 20}

    combat, table, mid = fixture(tmp_path, [BASE, TRACE_TALENT], ally_talents=[EXILE], cl=15,
                                  seed="A2R13-DEPARTED", bundle_transform=decisive,
                                  positions={OWNER: {'x': 3, 'y': 6}, "actor:factory.worker2-ally": {'x': 2, 'y': 6},
                                            FOE: {'x': 6, 'y': 6}})
    turn(table, mid, FOE)
    move_foe(combat, table, mid)
    live = combat._load_session(mid).engine
    moves = [e for e in live.events if e.event_type == "MOVEMENT_COMMITTED" and e.actor_id == FOE]
    path = list(moves[-1].payload["path"])
    walked = compass(int(path[-1]["x"]) - int(path[0]["x"]), int(path[-1]["y"]) - int(path[0]["y"]))
    assert walked != "here", "the foe's movement did not run anywhere, so there is no trace bearing to read"

    turn(table, mid, "actor:factory.worker2-ally")
    exile = [c for c in combat._load_session(mid).engine.legal_candidates()
             if getattr(combat._load_session(mid).engine.action_catalog.get(c.source_definition_id),
                        "display_name", None) == "Exile Beyond the Horizon"]
    assert exile, "the ally had no Exile action, so the fight never produced a real departure"
    settle(table, mid, exile[0].candidate_id)
    live = combat._load_session(mid).engine
    assert not live._on_battlefield(live.state.actors[FOE]), \
        "the banishment did not take the creature off the field, so this is not a scene departure"

    # The banishment ends at the target's next turn, so the creature comes back. That round trip is not decoration:
    # a creature that is off the field cannot be Analyzed, so the printed clause can only ever be asked of a trace
    # the creature has already returned from, and it is what makes the learned direction survive as history.
    turn(table, mid, FOE)
    turn(table, mid, OWNER)
    analyze_foe(table, mid, combat)
    engine = reload(tmp_path, mid)
    live = combat._load_session(mid).engine
    assert any(c.condition_id == "condition:typed.analyzed_by"
               for c in live.state.actors[FOE].conditions.values()), \
        "the Analyze lost its contested check, so the printed 'when you successfully Analyze' never fired"

    lines = trace_lines(live)
    assert lines, "a successful Analyze of a departed creature recorded no trace line at all"
    assert any(f"left this scene to the {walked}" in line for line in lines), \
        f"the reported trace direction is not the bearing the creature's trail ran on before it left ({walked})"

    # Persisted, not merely logged: the learned fact is on the record and still there after the cold reload above.
    recorded = [c for c in live.state.actors[FOE].conditions.values()
                if (c.data or {}).get("characteristic") == TRACE_CHARACTERISTIC]
    assert recorded, "the trace direction was not recorded as a learned characteristic"
    for condition in recorded:
        assert condition.condition_id == "condition:typed.learned_characteristic", \
            "the trace direction must be a learned characteristic, not a mark left on the creature"
        assert (condition.data or {}).get("value") == walked, \
            "the learned direction must be stored as a value that later mechanics can recover"
        assert walked in str((condition.data or {}).get("label") or ""), \
            "the sheet line for the learned fact must show the direction that was learned"


def test_analyze_without_the_talent_records_no_trace_direction(tmp_path):
    combat, table, mid = fixture(tmp_path, [BASE], cl=15, seed="A2R13-NOTRACE")
    turn(table, mid, OWNER)
    analyze_foe(table, mid, combat)
    engine = reload(tmp_path, mid)
    assert trace_lines(engine) == []


# --------------------------------------------------------------------------- Invisible Blade Current
@pytest.mark.parametrize("foe_features,reads", [
    ([], False),                                   # ordinary senses: nothing to read the cut with
    ([GROUND_TREMORSENSE], False),                 # Finding 4: ground Tremorsense is not air-pressure Tremorsense
])
def test_ground_tremorsense_does_not_read_air(tmp_path, foe_features, reads):
    """Finding 4: "tremorsense *that can read air pressure*", asked of the sense row rather than the sense's name.

    The old helper answered True for any Tremorsense at all, so an ordinary ground-contact Tremorsense got the
    printed Advantage it never qualified for.
    """
    combat, table, mid = fixture(tmp_path, [], foe_sheet=sheet(foe_features, cl=15), seed="A2R13-AIRSENSE")
    engine = combat._load_session(mid).engine
    assert reads_air(engine, engine.state.actors[FOE]) is reads


def test_invisible_blade_grants_advantage_only_to_a_creature_that_reads_air(tmp_path):
    """Findings 4 and 5: drive Invisible Blade Current through a real table action and read the real roll mode.

    The Wind Lash is a genuine table intent from inside the caster's own Air Current, the defender really rolls
    Wisdom (Perception) against the caster's Cultivation Save DC, and the Advantage the printed qualification grants
    shows up in the recorded receipt's mode. The old test edited ``engine.typed_passive_rows`` and called the helper
    directly, so it proved neither the prompt nor the result.
    """
    positions = {OWNER: {'x': 3, 'y': 6}, "actor:factory.worker2-ally": {'x': 2, 'y': 6}, FOE: {'x': 3, 'y': 7}}
    combat, table, mid = fixture(tmp_path, AIR_OWNER, foe_sheet=sheet([GROUND_TREMORSENSE], cl=15),
                                  seed="A2R13-AIRTABLE", positions=positions)
    engine = combat._load_session(mid).engine
    assert reads_air(engine, engine.state.actors[FOE]) is False, "this defender must not read air"
    turn(table, mid, OWNER)
    commit(table, mid, combat, GATHER, at=(3, 6))
    commit(table, mid, combat, LASH, target=FOE, picks={BLADE_CHOICE: ["use"]})
    engine = reload(tmp_path, mid)

    checks = [e for e in engine.events if e.event_type == "CHECK_ROLLED"
              and e.source_definition_id == "TAL_AIR_INVISIBLE_BLADE_CURRENT"]
    assert checks, "the invisible Wind Lash rolled no Perception check, so this test proved nothing"
    assert checks[-1].payload["skill"] == "Perception"
    assert checks[-1].payload["actor"]["mode"] == "NORMAL", \
        "ground Tremorsense must not take Advantage on this check"
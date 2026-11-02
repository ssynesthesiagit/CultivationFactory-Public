"""AUTO57f1: the printed Glass lines that resolve at the table, and the ones that still need the GM.

Every test compiles a real Glass character, plays the printed line through the real engine and fails on the typing and
plug-ins the authority carried before (combat/ext/glass_pane.py, combat/ext/glass_refraction.py).  Printed text:
APP/authority/typed_mechanics/rules_text.json.  Overrides: authority/typed_mechanics/reviewed_final.d/auto57_glass.json
(Raised Pane Scripture's own row is edited in review_sw-force.json, Walking Pane Body and Shard Needle in riders_lane9.json).

The pre-merge review of this lane is AUTO57.review.md; each test below names the finding it holds down (F1..F9) where one
applies.  Tests drive a Gate4ControllerEngine fight or the real table service (TabletopService), never a unit call, and the
saved state they assert on is the committed fight.
"""

import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

from combat import factory_compiler
from combat.ext import glass_pane, glass_refraction
from combat.factory_compiler import compile_character
from combat.gate2_runtime_models import ActionIntent, Position
from combat.gate4_engine import Gate4ControllerEngine

ROOT = Path(__file__).resolve().parents[1]
T = "TAL_GLASS_"
ME = "actor:factory.a"
THEM = "actor:factory.b"
ALLY = "actor:factory.c"
FOE2 = "actor:factory.d"
FOE3 = "actor:factory.e"
BASES = ("GLASS_BASE_REFRACTION_RESPONSES", "GLASS_BASE_TEMPER_GLASS_SURFACE", "GLASS_BASE_FAULTLINE_MARKS",
         "GLASS_BASE_GLASS_SHARD", "GLASS_BASE_FAULTLINE_STRIKE")
PANE_MARK = "condition:typed.glass_pane_mark"


def _authority():
    return json.loads(Path(factory_compiler.TYPED_AUTHORITY).read_bytes())["mechanics"]


def _riders(mid):
    return _authority()[mid].get("riders") or []


def _blank(cl=15):
    from tests.test_carry import KIT
    from tests.test_zones import SHEET

    return {**SHEET, "equipment": [{"starting_kit": KIT}],
            "identity": {**SHEET["identity"], "cultivation_level": cl},
            "ability_scores_and_statistics": {**SHEET["ability_scores_and_statistics"],
                                              "primary_resource": {"name": "Qi", "maximum": 80}}}


def _sheet(talents, cl=15):
    return {**_blank(cl), "spheres_and_talents": {"sphere_record_ids": ["tianxia.sphere.glass"],
                                                  "automatic_sphere_component_record_ids": list(BASES),
                                                  "learned_talent_record_ids": [T + name for name in talents]}}


def _other(cl=15):
    return {**_blank(cl), "spheres_and_talents": {"sphere_record_ids": ["tianxia.sphere.brute"],
                                                  "learned_talent_record_ids": []}}


def _fight(talents, *, cl=15, me_at=(3, 6), them_at=(4, 6), ally_at=None, foe2_at=None, foe3_at=None, seed="A57",
           modes="LOCAL_AUTO", ally_talents=None):
    """ME (a Glass fighter with ``talents``) against a Brute, with an ally and a second hostile when asked for.

    Every fighter is an AI fighter (the mode a Factory fight gives one), so a printed "you may" is answered by the
    controller; the tests that check a player-controlled fighter pass ``modes="MANUAL"`` for ME. ``ally_talents`` gives
    ALLY the Glass sphere and those talents (its own base abilities come with the sphere) instead of a Brute."""
    bundles = [compile_character(_sheet(talents, cl), actor_id=ME)]
    ids, teams, spots = [ME], {"team": None, ME: "team:a"}, {ME: {"x": me_at[0], "y": me_at[1]}}
    for actor_id, cell, team in ((THEM, them_at, "team:b"), (ALLY, ally_at, "team:a"), (FOE2, foe2_at, "team:b"),
                                 (FOE3, foe3_at, "team:b")):
        if cell is None:
            continue
        sheet = _other(cl) if actor_id != ALLY or ally_talents is None else _sheet(ally_talents, cl)
        bundles.append(compile_character(sheet, actor_id=actor_id))
        ids.append(actor_id)
        teams[actor_id] = team
        spots[actor_id] = {"x": cell[0], "y": cell[1]}
    engine = Gate4ControllerEngine(ROOT, match_seed=seed, typed_bundles=tuple(bundles),
                                   roster_setup={"primary_actor_ids": ids, "team_by_actor": teams, "starting_positions": spots})
    engine.typed_control_modes = {actor_id: ("MANUAL" if modes == "MANUAL" and actor_id == ME else "LOCAL_AUTO")
                                  for actor_id in ids}
    _turn(engine, ME)
    return engine


def _turn(engine, actor):
    engine.state.current_slot_index = engine.state.initiative_order.index(actor)
    engine.state.current_actor_id = actor
    engine._system_start_turn()


def _act(engine, name, *, actor=ME, at=None, target=None):
    wanted = target if target is None or isinstance(target, str) else getattr(target, "entity_id", target)
    candidate = next(c for c in engine.legal_candidates() if c.actor_id == actor
                     and getattr(engine.action_catalog.get(c.source_definition_id), "display_name", None) == name
                     and (at is None or (c.destination is not None and (c.destination.x, c.destination.y) == at))
                     and (wanted is None or c.target_ids == (wanted,)))
    engine.execute_intent(ActionIntent(intent_id=f"{name}{engine.state.event_sequence}", decision_id=candidate.decision_id,
                                       candidate_id=candidate.candidate_id, state_version=candidate.state_version, actor_id=actor,
                                       target_ids=candidate.target_ids, destination=candidate.destination))


def _names(engine, actor=ME):
    return {getattr(engine.action_catalog.get(c.source_definition_id), "display_name", None) for c in engine.legal_candidates()
            if c.actor_id == actor}


def _stab(engine, target=THEM, name="Bi Shou (Dagger) attack", actor=THEM):
    _turn(engine, actor)
    _act(engine, name, actor=actor, target=target)


def _throw(engine, target, actor=THEM):
    _turn(engine, actor)
    _act(engine, "Bi Shou (Dagger) thrown", actor=actor, target=target)


def _walk(engine, actor, cells):
    """A willing 5-foot move inside an open intent, recorded the way the engine records one (so a Refraction Response can
    ask the caster which one it pays the mark with)."""
    _turn(engine, actor)
    subject = engine.state.actors[actor]
    subject.position = Position(x=cells[-1][0], y=cells[-1][1])
    engine._active_intent = ActionIntent(intent_id=f"walk{engine.state.event_sequence}", decision_id="walk", candidate_id="walk",
                                         state_version=0, actor_id=actor, target_ids=(), destination=None)
    try:
        engine._append_event("MOVEMENT_COMMITTED", "test", actor_id=actor,
                             payload={"path": [{"x": x, "y": y} for x, y in cells]})
    finally:
        engine._active_intent = None


def _conds(actor):
    return {c.condition_id for c in actor.conditions.values()}


def _panes(engine, who=ME):
    return glass_pane.panes_of(engine, engine.state.actors[who])


def _logs(engine):
    return [str((event.payload or {}).get("log") or "") for event in engine.events if event.event_type == "PASSIVE_TRIGGERED"]


def _answer(engine, choice_id, option, calls=None):
    """Answer one needle question with ``option``; every other question keeps its own answer."""
    original = engine._reaction_decision

    def decide(intent, checkpoint, actor_id, asked, **kwargs):
        if asked == choice_id:
            if calls is not None:
                calls.append({"asked": asked, **(kwargs.get("context") or {})})
            return SimpleNamespace(selection="USE", option_ids=(option,))
        return original(intent, checkpoint, actor_id, asked, **kwargs)

    engine._reaction_decision = decide


def _decline(engine, choice_id, calls=None):
    """Answer one needle question by declining it; every other question keeps its own answer."""
    original = engine._reaction_decision

    def decide(intent, checkpoint, actor_id, asked, **kwargs):
        if asked == choice_id:
            if calls is not None:
                calls.append({"asked": asked, **(kwargs.get("context") or {})})
            return SimpleNamespace(selection="DECLINE", option_ids=())
        return original(intent, checkpoint, actor_id, asked, **kwargs)

    engine._reaction_decision = decide


def _nobody_answers(engine, calls=None):
    """No player and no controller at the table: every question goes unanswered (used with ``modes``)."""
    def decide(intent, checkpoint, actor_id, asked, **kwargs):
        if calls is not None:
            calls.append({"asked": asked, **(kwargs.get("context") or {})})
        return None

    engine._reaction_decision = decide


def _spy(engine, answers=None, calls=None):
    """Record every question the fight asks; answer the ones named in ``answers`` (others keep their own answer)."""
    calls = [] if calls is None else calls
    original = engine._reaction_decision

    def decide(intent, checkpoint, actor_id, asked, **kwargs):
        if calls is not None:
            calls.append({"asked": asked, **(kwargs.get("context") or {})})
        if answers and asked in answers:
            return SimpleNamespace(selection="USE", option_ids=(answers[asked],))
        return original(intent, checkpoint, actor_id, asked, **kwargs)

    engine._reaction_decision = decide
    return calls


def _move(engine, actor, cell):
    """One ordinary 5-foot move, committed as a real move intent (so a leaving-reach Opportunity Attack is asked)."""
    candidate = next(c for c in engine.legal_candidates() if c.actor_id == actor
                     and c.source_definition_id == "system:combat.movement"
                     and c.destination is not None and (c.destination.x, c.destination.y) == cell)
    engine.execute_intent(ActionIntent(intent_id=f"move{engine.state.event_sequence}", decision_id=candidate.decision_id,
                                       candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                                       actor_id=actor, target_ids=candidate.target_ids, destination=candidate.destination))


def _clear_shattered(engine):
    """Sweep the caster's own one-square Shattered Glass Terrain patches off the map, so a test reads one trigger and not
    two: the Glass Domain's own area is Shattered Glass Terrain (its printed line), and the Faultline Marks rule about moving
    across broken glass fires on the same event as the Domain's crossing line.  The Domain itself is left standing."""
    from combat import zones

    for zone in [zone for zone in zones.typed_zones(engine)
                 if glass_pane.TERRAIN in (zone.trigger_profile.get("terrain") or [])
                 and len(zone.affected_cells) == 1]:
        zones.remove(engine, zone, "cleared for the test")


def _break(engine, pane, actor=ME, amount=999):
    """Reduce one object to 0 hit points the way an ordinary blow does, inside an open intent so the answers Clean Break
    asks are answered (combat/ext/objects.py)."""
    from combat.ext import objects

    engine._active_intent = ActionIntent(intent_id=f"break{engine.state.event_sequence}", decision_id="break", candidate_id="break",
                                         state_version=0, actor_id=actor, target_ids=(), destination=None)
    try:
        objects.deal(engine, engine.state.actors[actor], pane, [(amount, "SLASHING")], T + "RAISED_PANE_SCRIPTURE")
    finally:
        engine._active_intent = None


def _no_break_reward(engine, calls, why):
    """Assert that whatever just happened paid nothing of the printed break reward.

    The printed trigger is "When you reduce a Glass Surface ... to 0 HP"; ending Concentration, running out the minute and a
    free-standing pane collapsing are all ways the duration ends, not blows, so a fighter who simply stops concentrating must
    not harvest a mark, a patch of terrain or a free step once per pane. ``calls`` is the spy installed before the event, so
    the question Clean Break would have asked is checked whether or not it was answered."""
    assert not [call for call in calls if call["asked"] == "choice:needle.glass_clean_break"], \
        f"{why} is not a blow, so Clean Break's three answers are not on the table"
    assert not glass_pane.shattered_cells(engine, engine.state.actors[ME]), \
        f"{why} is not a break, so no Shattered Glass Terrain is left behind"


def _domain(talents, **kw):
    """A Glass Domain up, with the caster's own body tempered inside it (printed: "your body counts as a tempered Glass
    Surface"), and every fighter an AI fighter."""
    engine = _fight(talents, **kw)
    _act(engine, "Glass Domain: Court of Visible Faults")
    _act(engine, "Temper Glass Surface")
    return engine


# ------------------------------------------------------------------------------------------------ Raised Pane Scripture
def test_raised_pane_scripture_raises_panes_with_its_printed_numbers():
    engine = _fight(["RAISED_PANE_SCRIPTURE"], them_at=(10, 10))
    me = engine.state.actors[ME]
    row = next(r for r in engine.typed_passive_rows[ME] if r.get("kind") == "refraction")
    assert "Raised Pane Scripture" in _names(engine)
    _act(engine, "Raised Pane Scripture", at=(0, 6))  # the arena's edge: a solid surface to anchor to
    panes = _panes(engine)
    assert len(panes) == 3, "At CL 11 a Glass character raises three connected panes"
    pane = panes[0]
    assert (pane.position.x, pane.position.y) == (0, 6)
    assert pane.ac == 12 + int(row["pb"]) and pane.maximum_hp == 5 * 15
    assert set(pane.damage_immunities) == {"POISON", "PSYCHIC"}
    assert pane.component["vulnerable"] == ["THUNDER"] and pane.component["material"] == "glass"
    assert "Attack an object" in {a.display_name for a in engine.action_catalog.values() if a.owner_id == ME}
    assert _riders(T + "RAISED_PANE_SCRIPTURE") == []


def test_the_extra_panes_are_connected_squares_not_a_straight_line_from_the_caster():
    """F2: the old code stepped by the whole caster-to-aim displacement, so a caster at (3,6) aiming at (6,6) put panes
    at (6,6), (9,6) and (12,6) -- squares that touch nothing.  Each pane now touches the one before it."""
    engine = _fight(["RAISED_PANE_SCRIPTURE"], them_at=(10, 10))
    _act(engine, "Raised Pane Scripture", at=(0, 6))
    cells = sorted((pane.position.x, pane.position.y) for pane in _panes(engine))
    assert cells == [(0, 6), (1, 6), (2, 6)]
    for left, right in zip(cells, cells[1:]):
        assert max(abs(left[0] - right[0]), abs(left[1] - right[1])) == 1, "connected panes share a full side"


def test_the_chain_of_panes_stops_at_the_first_square_it_cannot_use():
    """F2: "In an unoccupied space you can see within range" applies to every pane, not only the aimed one.  The old code
    walked the caster-to-aim displacement and kept going into occupied squares (and out of reach)."""
    engine = _fight(["RAISED_PANE_SCRIPTURE"], them_at=(14, 12), me_at=(0, 0))
    _act(engine, "Raised Pane Scripture", at=(8, 0))   # the arena's blocked pillar stands at (9, 0)
    cells = [(pane.position.x, pane.position.y) for pane in _panes(engine)]
    assert (9, 0) not in cells, "the chain stops before the pillar instead of stepping into it"
    assert cells == [(8, 0), (7, 0), (6, 0)], "and the three connected panes run along the row instead"
    assert all(pane.component["anchored"] for pane in _panes(engine))


def test_a_pane_with_nothing_to_anchor_it_to_does_not_rise():
    """F2: the old code raised an unanchored pane silently.  The printed text requires an anchor unless Pane-Step
    Projection lets it stand free, so nothing rises and the log says why."""
    engine = _fight(["RAISED_PANE_SCRIPTURE"], them_at=(10, 10))
    _act(engine, "Raised Pane Scripture", at=(6, 6))   # open ground: no wall, no other pane
    assert not _panes(engine)
    assert any("anchored to a solid surface or another Glass Pane" in text for text in _logs(engine))


def test_a_pane_may_be_anchored_to_another_casters_pane():
    """AUTO57r1 review F3: "must be anchored to a solid surface or another Glass Pane" names no owner, but the anchor test was
    handed an empty set and only ever looked at walls, the map edge and the chain being built -- so a legal pane beside another
    caster's pane on open ground was refused."""
    engine = _fight(["RAISED_PANE_SCRIPTURE"], ally_at=(2, 6), them_at=(10, 10), cl=1,
                    ally_talents=["RAISED_PANE_SCRIPTURE"])   # CL 1: one pane each, so the ally's chain leaves (1,6) alone
    _turn(engine, ALLY)
    _act(engine, "Raised Pane Scripture", at=(0, 6), actor=ALLY)   # the ally's own pane, on the arena's edge
    theirs = _panes(engine, ALLY)
    assert theirs and (0, 6) in {(p.position.x, p.position.y) for p in theirs}, "the ally's pane is up"
    assert (1, 6) not in engine.grid.blocked and engine.grid.in_bounds((1, 6)), \
        "(1,6) is open ground with no wall and no map edge beside it"

    _turn(engine, ME)
    _act(engine, "Raised Pane Scripture", at=(1, 6))
    mine = _panes(engine, ME)
    assert any((p.position.x, p.position.y) == (1, 6) for p in mine), \
        "a pane may be anchored to another caster's pane: the printed anchor names no owner"
    assert not any("nothing beside that square to anchor it to" in text for text in _logs(engine))


def test_a_free_standing_pane_that_another_casters_pane_anchors_before_its_deadline_stays():
    """AUTO57r1 review F3 on the re-read: Pane-Step Projection's "unless it becomes anchored before then" reads the anchor again
    at the deadline, and the printed anchor names no owner, so another caster's pane keeps this one standing."""
    engine = _fight(["RAISED_PANE_SCRIPTURE", "PANE_STEP_PROJECTION"], ally_at=(6, 6), them_at=(10, 10), cl=1,
                    ally_talents=["RAISED_PANE_SCRIPTURE"])
    _answer(engine, "choice:needle.glass_pane_step", "near")
    _answer(engine, "choice:needle.glass_pane_square", "cell:5,6")
    _act(engine, "Raised Pane Scripture", at=(9, 9))
    loose = _panes(engine, ME)
    assert len(loose) == 1 and not loose[0].component["anchored"], "one pane standing free in the open"

    _turn(engine, ALLY)
    _act(engine, "Raised Pane Scripture", at=(4, 6), actor=ALLY)   # the ally's pane rises beside it
    assert any((p.position.x, p.position.y) == (4, 6) for p in _panes(engine, ALLY)), "the ally's own pane is anchored by it"

    for who in (THEM, ME):
        _turn(engine, who)
        engine.end_turn()
    assert glass_pane.anchored_now(engine, loose[0]), "another caster's pane anchors it, so it is anchored after all"
    assert any(pane.object_id == loose[0].object_id for pane in _panes(engine)), "so it does not collapse"
    assert any("has become anchored" in text for text in _logs(engine))


def test_a_pane_goes_when_its_concentration_ends():
    """F1: the printed duration is "Concentration, up to 1 minute"; the old code left anchored panes standing for the
    rest of the fight, because its lifecycle skipped anything without an ``ends_round``."""
    engine = _fight(["RAISED_PANE_SCRIPTURE"], them_at=(10, 10))
    _act(engine, "Raised Pane Scripture", at=(0, 6))
    panes = _panes(engine)
    assert panes and all(pane.component["anchored"] for pane in panes)
    assert all(pane.component["copy_start"] == engine.state.actors[ME].concentration.started_sequence for pane in panes)
    engine._end_concentration(engine.state.actors[ME], "TEST")
    assert not _panes(engine), "the panes go with the Concentration that made them"
    assert all(engine.state.objects[pane.object_id].destroyed for pane in panes)
    assert any("Concentration ends" in text for text in _logs(engine))


def test_a_pane_fades_after_its_minute():
    """F1: the printed "up to 1 minute" (the shared standard, ten rounds) on a pane nobody dropped."""
    engine = _fight(["RAISED_PANE_SCRIPTURE"], them_at=(10, 10))
    _act(engine, "Raised Pane Scripture", at=(0, 6))
    panes = _panes(engine)
    deadline = panes[0].component["deadline"]
    assert deadline.startswith("START_OF_SLOT_AT:"), deadline
    while engine.state.round_number < 11:
        engine.end_turn()
    assert not _panes(engine), "ten rounds later the minute is up"
    assert any("up to 1 minute" in text for text in _logs(engine))


def test_a_free_standing_pane_collapses_at_the_end_of_your_next_turn():
    """F1: Pane-Step Projection's "The pane collapses at the end of your next turn" was a round count checked at any
    turn start; it is now the owner's own next turn.  A CL 1 fighter raises one pane, so nothing else anchors it."""
    engine = _fight(["RAISED_PANE_SCRIPTURE", "PANE_STEP_PROJECTION"], them_at=(10, 10), cl=1)
    calls = []
    _answer(engine, "choice:needle.glass_pane_step", "near", calls)
    _answer(engine, "choice:needle.glass_pane_square", "cell:4,7")
    _act(engine, "Raised Pane Scripture", at=(9, 9))
    loose = _panes(engine)
    assert [pane.component["anchored"] for pane in loose] == [0]
    assert loose[0].component["collapse"] == f"END_OF_TURN_AT:{ME}:{engine.state.actors[ME].turns_started + 1}"
    for who in (THEM, ME):
        _turn(engine, who)
        engine.end_turn()
    assert not _panes(engine), "it collapses when its owner's next turn ends"
    assert any("collapses at the end of your next turn" in text for text in _logs(engine))


def test_a_free_standing_pane_that_becomes_anchored_stays():
    """F1: "... unless it becomes anchored before then": a pane that reaches a wall or another pane keeps standing."""
    engine = _fight(["RAISED_PANE_SCRIPTURE", "PANE_STEP_PROJECTION"], them_at=(10, 10))
    _answer(engine, "choice:needle.glass_pane_step", "near")
    _answer(engine, "choice:needle.glass_pane_square", "cell:4,7")
    _act(engine, "Raised Pane Scripture", at=(9, 9))
    loose = [pane for pane in _panes(engine) if not pane.component["anchored"]]
    assert len(loose) == 1, "the first pane is the free-standing one; its companions touch it"
    for who in (THEM, ME):
        _turn(engine, who)
        engine.end_turn()
    assert glass_pane.anchored_now(engine, loose[0]), "it touches the pane beside it, so it is anchored after all"
    assert any(pane.object_id == loose[0].object_id for pane in _panes(engine))
    assert any("has become anchored" in text for text in _logs(engine))


def test_pane_step_projection_offers_the_legal_square_to_place_the_pane():
    """F2: accepting Pane-Step used to throw the player's aimed square away and take the nearest one automatically."""
    engine = _fight(["RAISED_PANE_SCRIPTURE", "PANE_STEP_PROJECTION"], them_at=(10, 10))
    calls = []
    _answer(engine, "choice:needle.glass_pane_step", "near", calls)
    _answer(engine, "choice:needle.glass_pane_square", "cell:4,7", calls)
    _act(engine, "Raised Pane Scripture", at=(9, 9))
    assert [call.get("name") for call in calls] == ["Pane-Step Projection", "Pane-Step Projection"]
    square = next(call for call in calls if call["asked"] == "choice:needle.glass_pane_square")
    assert "cell:4,7" in square["needle_options"] and "cell:9,9" not in square["needle_options"], \
        "the player is asked which of the squares within 10 feet the pane stands in"
    pane = _panes(engine)[0]
    assert not pane.component["anchored"]
    assert engine.grid.distance_ft(engine.state.actors[ME].position, pane.position) <= 10
    assert _riders(T + "PANE_STEP_PROJECTION") == []


def test_a_broken_pane_shatters_into_shattered_glass_terrain():
    engine = _fight(["RAISED_PANE_SCRIPTURE"], them_at=(10, 10))
    _act(engine, "Raised Pane Scripture", at=(0, 6))
    pane = _panes(engine)[0]
    _break(engine, pane)
    assert engine.state.objects[pane.object_id].destroyed
    assert (0, 6) in glass_pane.shattered_cells(engine, engine.state.actors[ME])


def test_a_pane_that_leaves_with_its_concentration_awards_no_break_reward():
    """AUTO57r1 review F1: every retirement path wrote ``current_hp`` 0 and an OBJECT_UPDATED to the owner, which both readers
    of that event took for a blow -- so simply dropping Concentration harvested Clean Break once per pane."""
    engine = _fight(["RAISED_PANE_SCRIPTURE"], them_at=(4, 6))
    _act(engine, "Raised Pane Scripture", at=(0, 6))
    assert _panes(engine), "the pane is up before its Concentration ends"
    calls = _spy(engine, {"choice:needle.glass_clean_break": "mark"})
    engine._end_concentration(engine.state.actors[ME], "TEST")
    assert not _panes(engine), "the pane still goes with the Concentration that made it"
    _no_break_reward(engine, calls, "a pane whose Concentration ended")


def test_a_pane_that_fades_after_its_minute_awards_no_break_reward():
    """AUTO57r1 review F1: the same three retirement paths, read on the 1-minute clock."""
    engine = _fight(["RAISED_PANE_SCRIPTURE"], them_at=(4, 6))
    _act(engine, "Raised Pane Scripture", at=(0, 6))
    calls = _spy(engine, {"choice:needle.glass_clean_break": "mark"})
    while engine.state.round_number < 11:
        engine.end_turn()
    assert not _panes(engine), "ten rounds later the minute is up"
    _no_break_reward(engine, calls, "a pane that ran out its minute")


def test_a_free_standing_pane_that_collapses_awards_no_break_reward():
    """AUTO57r1 review F1: Pane-Step Projection's collapse is a printed duration ending, not a blow."""
    engine = _fight(["RAISED_PANE_SCRIPTURE", "PANE_STEP_PROJECTION"], them_at=(10, 10), cl=1)
    _answer(engine, "choice:needle.glass_pane_step", "near")
    _answer(engine, "choice:needle.glass_pane_square", "cell:4,7")
    _act(engine, "Raised Pane Scripture", at=(9, 9))
    assert len(_panes(engine)) == 1, "a CL 1 fighter raises one free-standing pane"
    calls = _spy(engine, {"choice:needle.glass_clean_break": "mark"})
    for who in (THEM, ME):
        _turn(engine, who)
        engine.end_turn()
    assert not _panes(engine), "it collapses when its owner's next turn ends"
    _no_break_reward(engine, calls, "a pane that collapsed")


def test_a_shattered_pane_lasts_until_the_end_of_your_next_turn():
    """F1: the printed deadline for the terrain a break leaves is the owner's next turn, not two rounds."""
    engine = _fight(["RAISED_PANE_SCRIPTURE"], them_at=(10, 10))
    _act(engine, "Raised Pane Scripture", at=(0, 6))
    me = engine.state.actors[ME]
    _break(engine, _panes(engine)[0])
    patch = next(zone for zone in engine.state.zones.values()
                 if glass_pane.TERRAIN in (zone.trigger_profile.get("terrain") or []))
    assert patch.duration_rounds is None, "no round countdown: the printed deadline is the owner's next turn"
    assert patch.trigger_profile["end_after_owner_turn"] == int(me.turns_started) + 1
    for who in (THEM, ME):
        _turn(engine, who)
        engine.end_turn()
    assert not engine.state.zones[patch.zone_id].active, "the broken glass is swept away at the end of your next turn"
    # AUTO57r3 review F1: the table is told the deadline in the line the break writes, not only in the terrain's own record,
    # so an ordinary broken pane says the owner's next turn -- the only lifetime this patch actually got.
    said = [text for text in _logs(engine) if "Shattered Glass Terrain fills its square" in text]
    assert said == ["The Glass Pane shatters: Shattered Glass Terrain fills its square until the end of your next turn."], \
        said
    assert not any("Glass Domain" in text for text in said), \
        "no Glass Domain tied this patch, so the log must not name one as the deadline"


# ------------------------------------------------------------------------------------------------ Clean Break
def test_clean_break_answers_with_shattered_glass_terrain_beside_the_broken_pane():
    engine = _fight(["RAISED_PANE_SCRIPTURE", "CLEAN_BREAK"], them_at=(10, 10))
    _act(engine, "Raised Pane Scripture", at=(0, 6))
    pane = _panes(engine)[0]
    _break(engine, pane)
    assert {(x, y) for x in range(0, 3) for y in range(5, 8)} & glass_pane.shattered_cells(engine, engine.state.actors[ME])
    assert _riders(T + "CLEAN_BREAK") == []


def test_clean_break_offers_every_square_next_to_the_broken_thing():
    """F8: the printed line is "one 5-foot square adjacent to it"; the old code offered only the four orthogonal squares
    and refused an occupied one, restrictions the printed text does not print."""
    engine = _fight(["RAISED_PANE_SCRIPTURE", "CLEAN_BREAK"], them_at=(1, 6), ally_at=(0, 7))
    _act(engine, "Raised Pane Scripture", at=(0, 6))
    calls = _spy(engine, {"choice:needle.glass_clean_break": "terrain", "choice:needle.glass_clean_break_square": "cell:1,6"})
    _break(engine, _panes(engine)[0])
    squares = next(call for call in calls if call["asked"] == "choice:needle.glass_clean_break_square")
    offered = {tuple(int(part) for part in option.split(":")[1].split(",")) for option in squares["needle_options"]}
    assert offered == {(0, 5), (1, 5), (1, 6), (0, 7), (1, 7)}, "every square that touches it, diagonals included"
    assert (1, 6) in offered and (0, 7) in offered, "the creatures standing there do not forbid the square"
    assert (1, 6) in glass_pane.shattered_cells(engine, engine.state.actors[ME]), \
        "the table's choice is where the broken glass goes, occupied square or not"


def test_clean_break_marks_the_creature_the_table_picks_even_when_it_is_an_ally():
    """F8: the mark menu listed teammates, but the mark routine refuses a same-side recipient, so an accepted answer did
    nothing.  The printed line says "one creature"."""
    engine = _fight(["RAISED_PANE_SCRIPTURE", "CLEAN_BREAK"], them_at=(1, 6), ally_at=(1, 7))
    _act(engine, "Raised Pane Scripture", at=(0, 6))
    _answer(engine, "choice:needle.glass_clean_break", "mark")
    _answer(engine, "choice:needle.glass_clean_break_mark", ALLY)
    _break(engine, _panes(engine)[0])
    assert glass_refraction.marked(engine.state.actors[ALLY], ME), "the mark lands on the creature the table chose"


def test_clean_break_step_ignores_a_creature_that_saw_the_break_from_across_the_map():
    """F8: "one creature that saw it break" is about sight, not reach: the old code wanted one within 5 feet and never
    looked at line of sight at all."""
    engine = _fight(["RAISED_PANE_SCRIPTURE", "CLEAN_BREAK"], them_at=(12, 6), ally_at=(2, 6))
    _act(engine, "Raised Pane Scripture", at=(0, 6))
    calls = _spy(engine, {"choice:needle.glass_clean_break": "step"})
    _break(engine, _panes(engine)[0])
    asked = [call for call in calls if call["asked"] == "choice:needle.glass_clean_break_watcher"]
    assert asked, "Clean Break asks which creature's Opportunity Attack is being ignored"
    assert {THEM, ALLY} <= set(asked[0]["needle_options"]), "any creature that could see it may be named, at any distance"


def test_clean_break_does_not_offer_the_step_when_nothing_saw_the_break():
    engine = _fight(["RAISED_PANE_SCRIPTURE", "CLEAN_BREAK"], them_at=(10, 10))
    engine.grid.opaque |= {(0, 5)}
    _act(engine, "Raised Pane Scripture", at=(0, 6))
    engine.grid.opaque |= {(1, 6), (2, 6), (3, 6), (0, 7), (1, 7)}
    calls = _spy(engine, {"choice:needle.glass_clean_break": "terrain"})
    _break(engine, _panes(engine)[0])
    assert "step" not in calls[0]["needle_options"], "an answer that could ignore nobody's Opportunity Attack is not offered"


# ------------------------------------------------------------------------------------------------ Refraction Responses
def test_refracted_step_is_offered_with_bitter_edge_and_moves_the_caster_out_of_reach():
    engine = _fight([], them_at=(4, 6))
    _act(engine, "Temper Glass Surface")
    glass_refraction.give_mark(engine, engine.state.actors[ME], engine.state.actors[THEM], "test")
    calls = []
    _answer(engine, "choice:needle.refraction_response", "step", calls)
    start = (engine.state.actors[ME].position.x, engine.state.actors[ME].position.y)
    _walk(engine, THEM, [(4, 6), (4, 7)])  # a marked creature moves 5 feet: Bitter Edge's trigger
    me = engine.state.actors[ME]
    assert (me.position.x, me.position.y) != start and not glass_refraction.marked(engine.state.actors[THEM], ME)
    assert any("Refracted Step" in str(label) for label in calls[-1]["labels"].values())


def test_refracted_step_steps_fifteen_feet_at_cl_fifteen():
    engine = _fight([], them_at=(4, 6), cl=15)
    _act(engine, "Temper Glass Surface")
    glass_refraction.give_mark(engine, engine.state.actors[ME], engine.state.actors[THEM], "test")
    _answer(engine, "choice:needle.refraction_response", "step")
    _answer(engine, "choice:needle.glass_refracted_step", "cell:0,3")  # three squares away: the printed 15 feet at CL 11+
    _walk(engine, THEM, [(4, 6), (4, 7)])
    me = engine.state.actors[ME]
    assert engine.grid.distance_ft(Position(x=3, y=6), me.position) == 15


def test_a_marked_creatures_miss_of_you_answers_one_response_that_does_something():
    """F3: the old code spent the mark on a Response named "obvious" that the caller never applied, so a mark vanished
    and nothing happened."""
    from tests.test_auto_lane4 import _script

    engine = _fight(["REFRACTION_OF_THE_OBVIOUS_BLOW"], them_at=(4, 6), ally_at=(5, 6))
    glass_refraction.give_mark(engine, engine.state.actors[ME], engine.state.actors[THEM], "test")
    me, them = engine.state.actors[ME], engine.state.actors[THEM]
    me.armor_class, them.armor_class = 60, 60
    _script(engine, [1])  # the marked creature's attack misses
    before = them.current_hp
    _stab(engine, target=me)
    assert not glass_refraction.marked(them, ME)
    assert them.current_hp == before - 4, "Shatter Warning's printed damage: Piercing equal to your Proficiency Bonus"
    assert me.reaction_available, "Refraction of the Obvious Blow costs no Reaction"
    assert _riders(T + "REFRACTION_OF_THE_OBVIOUS_BLOW") == []


def test_a_miss_at_someone_else_is_not_the_obvious_blow():
    """F3: the printed trigger is "misses you"; the old code fired for any teammate."""
    from tests.test_auto_lane4 import _script

    engine = _fight(["REFRACTION_OF_THE_OBVIOUS_BLOW"], them_at=(4, 6), ally_at=(5, 6))
    glass_refraction.give_mark(engine, engine.state.actors[ME], engine.state.actors[THEM], "test")
    me, them, ally = (engine.state.actors[who] for who in (ME, THEM, ALLY))
    me.armor_class, ally.armor_class = 60, 60
    _script(engine, [1])
    before = them.current_hp
    _stab(engine, target=ally)
    assert glass_refraction.marked(them, ME), "the mark is untouched: the printed trigger is a miss at you"
    assert them.current_hp == before
    assert me.turn_flags.get("glass_obvious_blow") is None, "and the once-a-round chance was not spent"


def test_declining_the_obvious_blow_keeps_the_mark_and_the_round():
    engine = _fight(["REFRACTION_OF_THE_OBVIOUS_BLOW"], them_at=(4, 6))
    glass_refraction.give_mark(engine, engine.state.actors[ME], engine.state.actors[THEM], "test")
    me, them = engine.state.actors[ME], engine.state.actors[THEM]
    me.armor_class = 60
    _decline(engine, "choice:needle.refraction_response")
    _stab(engine, target=me)
    assert glass_refraction.marked(them, ME)
    assert me.turn_flags.get("glass_obvious_blow") is None, "the round is reserved only when a Response is used"


def test_the_obvious_blow_is_the_casters_own_decision():
    """Checklist 9: an AI fighter decides for itself; an Ask me fighter is asked, and nobody answering it means nothing
    happens."""
    engine = _fight(["REFRACTION_OF_THE_OBVIOUS_BLOW"], them_at=(4, 6))
    glass_refraction.give_mark(engine, engine.state.actors[ME], engine.state.actors[THEM], "test")
    me, them = engine.state.actors[ME], engine.state.actors[THEM]
    me.armor_class = 60
    calls = []
    _nobody_answers(engine, calls)
    _stab(engine, target=me)
    assert them.current_hp < 60, "an AI fighter uses the free Response on its own"
    assert any(call["asked"] == "choice:needle.refraction_response" for call in calls)

    engine = _fight(["REFRACTION_OF_THE_OBVIOUS_BLOW"], them_at=(4, 6), modes="MANUAL")
    glass_refraction.give_mark(engine, engine.state.actors[ME], engine.state.actors[THEM], "test")
    me, them = engine.state.actors[ME], engine.state.actors[THEM]
    me.armor_class = 60
    _nobody_answers(engine)
    _stab(engine, target=me)
    assert them.current_hp == 60, "an Ask me fighter waits for its player: nothing happens until one answers"
    assert glass_refraction.marked(them, ME)


# ------------------------------------------------------------------------------------------------ mark-spending talents
def test_walking_pane_body_pays_temporary_hp_when_the_mark_a_melee_hit_earned_is_spent():
    from tests.test_auto_lane4 import _script

    engine = _fight(["WALKING_PANE_BODY"], them_at=(4, 6))
    _act(engine, "Temper Glass Surface")
    me, them = engine.state.actors[ME], engine.state.actors[THEM]
    me.armor_class = 60
    _script(engine, [20])  # a melee hit on your tempered body earns the mark
    _stab(engine, target=me)
    assert glass_refraction.marked(them, ME)
    assert f"{PANE_MARK}.{THEM}" in _conds(me), "the fight records which creature's hit earned the mark"
    assert me.temporary_hp == 0, "nothing is paid yet: the mark has to be spent"
    _walk(engine, THEM, [(4, 6), (4, 7)])  # Bitter Edge spends it
    assert not glass_refraction.marked(them, ME) and me.temporary_hp == 4
    assert not any(key.startswith(PANE_MARK) for key in _conds(me)), "the promise is spent with the mark"


def test_walking_pane_body_pays_only_for_the_creature_that_earned_the_mark():
    """F4: the old code remembered only the round, so spending some other creature's mark paid the Temporary HP."""
    from tests.test_auto_lane4 import _script

    engine = _fight(["WALKING_PANE_BODY"], them_at=(4, 6), foe2_at=(8, 6))
    _act(engine, "Temper Glass Surface")
    me, them, second = (engine.state.actors[who] for who in (ME, THEM, FOE2))
    me.armor_class = 60
    _script(engine, [20])
    _stab(engine, target=me)
    glass_refraction.give_mark(engine, me, second, "test")
    _walk(engine, FOE2, [(8, 6), (8, 7)])  # the other creature's mark pays for itself
    assert not glass_refraction.marked(second, ME)
    assert me.temporary_hp == 0, "it is not this creature's mark, so it pays nothing"
    assert glass_refraction.marked(them, ME), "and the qualifying mark is still there to be spent"
    assert f"{PANE_MARK}.{THEM}" in _conds(me)


def test_walking_pane_body_pays_a_mark_spent_during_the_owner_next_turn():
    """F4: the printed deadline is "before the end of your next turn"; the old code compared round numbers and so refused
    every spend that happened in a later round.  The spend here is a real one: on their own next turn the owner walks out of
    reach, the marked creature's Opportunity Attack hits, and Turn the Angle spends the mark."""
    from tests.test_auto_lane4 import _script

    engine = _fight(["WALKING_PANE_BODY"], them_at=(4, 6))
    _act(engine, "Temper Glass Surface")
    me, them = engine.state.actors[ME], engine.state.actors[THEM]
    me.armor_class = 60
    _script(engine, [20])
    _stab(engine, target=me)          # round one: their melee hit earns the mark
    assert f"{PANE_MARK}.{THEM}" in _conds(me)
    engine.end_turn()                 # the owner's next turn begins, and the record is still live
    assert me.turns_started >= 1 and f"{PANE_MARK}.{THEM}" in _conds(me)
    calls = _spy(engine, {"choice:needle.refraction_response": "warning"}, [])
    _move(engine, ME, (2, 6))         # leaving their reach: the marked creature's Opportunity Attack
    assert any(call["asked"] == "choice:needle.refraction_response" for call in calls), \
        "the marked creature's Opportunity Attack is the trigger that spends the mark"
    assert me.temporary_hp == 4
    assert not any(key.startswith(PANE_MARK) for key in _conds(me)), "the promise is spent with the mark"
    assert glass_refraction.marked(them, ME), \
        "the Opportunity Attack that spent it earns a fresh mark, as Faultline Marks' own line says"


def test_walking_pane_body_ignores_a_thrown_weapon():
    """F4: "a creature hits you with a melee attack"; the old code took any weapon hit, thrown ones included."""
    from tests.test_auto_lane4 import _script

    engine = _fight(["WALKING_PANE_BODY"], them_at=(8, 6))
    _act(engine, "Temper Glass Surface")
    me, them = engine.state.actors[ME], engine.state.actors[THEM]
    me.armor_class = 60
    _script(engine, [20])
    _throw(engine, me)
    assert glass_refraction.marked(them, ME), "Faultline Marks still places the mark: a ranged attack is an attack"
    assert not any(key.startswith(PANE_MARK) for key in _conds(me)), \
        "but it is not a melee hit, so it earns no Temporary HP promise"
    _walk(engine, THEM, [(8, 6), (8, 7)])
    assert me.temporary_hp == 0


def test_shard_needle_is_left_to_the_gm_and_pays_nothing_on_its_own():
    """F5: the printed clause needs "If you are a Body Refiner using your own body as the source", and a compiled fighter
    records Spheres, Talents and Techniques, not its Path.  The old code paid every owner's Constitution modifier on every
    Glass Shard from anywhere."""
    from tests.test_auto_lane4 import _script

    def shot(talents):
        engine = _fight(talents, them_at=(8, 6), seed="A57S")
        me, them = engine.state.actors[ME], engine.state.actors[THEM]
        me.armor_class, them.armor_class = 60, -50
        _script(engine, [20])  # the same Glass Shard roll in both fights
        _turn(engine, ME)
        _act(engine, "Glass Shard", target=THEM)
        return sum(int(event.payload["hp_damage"]) for event in engine.events
                   if event.event_type == "DAMAGE_COMMITTED" and THEM in event.target_ids)

    assert shot(["SHARD_NEEDLE"]) == shot([]), "no extra damage is paid: the printed clause is the GM's"
    rider = " ".join(_riders(T + "SHARD_NEEDLE"))
    assert "Body Refiner" in rider and "GM" in rider
    assert ".py" not in rider, "a player-facing line never names an implementation file"
    assert not any(row.get("kind") == "shard_needle"
                   for row in next(iter(_fight(["SHARD_NEEDLE"]).typed_passive_rows.values()), []))


def test_faultline_transfer_moves_another_mark_when_one_is_spent():
    engine = _fight(["FAULTLINE_TRANSFER"], them_at=(4, 6), foe2_at=(5, 6))
    me, them, second = (engine.state.actors[who] for who in (ME, THEM, FOE2))
    glass_refraction.give_mark(engine, me, them, "test")
    glass_refraction.give_mark(engine, me, second, "test")
    _answer(engine, "choice:needle.glass_transfer", f"{FOE2}>{THEM}")
    _walk(engine, THEM, [(4, 6), (4, 7)])  # spends its own mark on Bitter Edge
    assert not glass_refraction.marked(them, ME) or glass_refraction.marked(them, ME)
    assert not glass_refraction.marked(second, ME) and glass_refraction.marked(them, ME), \
        "the second mark moved onto the creature whose own mark was just spent"
    assert any("Faultline Mark moves" in text for text in _logs(engine))
    assert _riders(T + "FAULTLINE_TRANSFER"), "the object and Glass Surface destinations stay the GM's"


def test_faultline_transfer_offers_every_legal_pair():
    """F7: the old code took the nearest marked creature and gave up when nothing stood within 5 feet of it, so a mark that
    could have moved was never offered.  Here the nearest marked creature has no neighbour at all and the farther one has."""
    engine = _fight(["FAULTLINE_TRANSFER"], them_at=(5, 6), ally_at=(9, 8), foe2_at=(4, 7), foe3_at=(9, 7))
    me, them, near, far, ally = (engine.state.actors[who] for who in (ME, THEM, FOE2, FOE3, ALLY))
    glass_refraction.give_mark(engine, me, them, "test")       # the mark that is about to be spent
    glass_refraction.give_mark(engine, me, near, "test")       # nearest: nothing stands within 5 feet of it
    glass_refraction.give_mark(engine, me, far, "test")        # farther: its neighbour is 5 feet away
    calls = _spy(engine, {"choice:needle.glass_transfer": "decline"})
    _walk(engine, THEM, [(5, 6), (5, 7)])                      # spends its own mark on Bitter Edge
    asked = [call for call in calls if call["asked"] == "choice:needle.glass_transfer"]
    assert asked, "the mark with no neighbour does not hide the one that has a legal destination"
    options = set(asked[0]["needle_options"])
    assert f"{FOE3}>{ALLY}" in options, "the farther mark's one legal destination is offered"
    assert f"{FOE2}>{THEM}" in options, "the spent creature may take a different mark"
    assert f"{FOE2}>{ME}" not in options, "a mark never moves back onto the caster"
    assert glass_refraction.marked(near, ME), "declining spends nothing and moves nothing"
    assert glass_refraction.marked(far, ME) and me.turn_flags.get("glass_transfer") is None, \
        "the once-a-round chance was not spent"


def test_faultline_transfer_is_the_casters_own_decision():
    engine = _fight(["FAULTLINE_TRANSFER"], them_at=(4, 6), foe2_at=(5, 6), modes="MANUAL")
    me, them, second = (engine.state.actors[who] for who in (ME, THEM, FOE2))
    glass_refraction.give_mark(engine, me, them, "test")
    glass_refraction.give_mark(engine, me, second, "test")
    _nobody_answers(engine)
    _walk(engine, THEM, [(4, 6), (4, 7)])
    assert glass_refraction.marked(second, ME), "an Ask me fighter waits for its player"


def test_ten_angle_refraction_pays_nothing_for_standing_on_glass():
    """AUTO57r1 review F4: the printed reward is for ending "holding a Glass Surface". The old code paid for ending *on* one of
    the caster's surface squares, so walking across Glass Road or sharing an unattended pane's square paid out -- a fighter
    standing on glass is not holding any."""
    engine = _fight(["TEN_ANGLE_REFRACTION", "RAISED_PANE_SCRIPTURE"], them_at=(4, 6), ally_at=(2, 7))
    _act(engine, "Temper Glass Surface")
    me, them, ally = (engine.state.actors[who] for who in (ME, THEM, ALLY))
    _act(engine, "Raised Pane Scripture", at=(0, 8))
    surfaces = glass_refraction._surface_cells(engine, me)
    glass_refraction.give_mark(engine, me, them, "test")
    _answer(engine, "choice:needle.glass_ten_angle", ALLY)
    _answer(engine, "choice:needle.glass_ten_angle_step", "cell:2,8")   # it ends on one of your panes
    _walk(engine, THEM, [(4, 6), (4, 7)])
    assert (ally.position.x, ally.position.y) == (2, 8), "the ally did take the 5-foot step onto your pane"
    assert (2, 8) in surfaces, "which is one of your Glass Surfaces"
    assert ally.temporary_hp == 0, "standing on a pane is not holding it, so the printed reward is not met"
    assert not glass_refraction.tempered(engine, ally), "the ally holds no Glass Surface of its own"
    assert any("Standing on glass is not holding it" in text for text in _logs(engine)), \
        "and the table is told in plain words that this one is its call"
    assert _riders(T + "TEN_ANGLE_REFRACTION") == []


def test_ten_angle_refraction_pays_an_ally_who_ends_holding_a_glass_surface_of_their_own():
    """AUTO57r1 review F4: "holding a Glass Surface" is read as the ally holding one -- its own body, worn armor or held weapon
    or shield made a Glass Surface by the table -- which is a state the fight does record (glass_tempered)."""
    engine = _fight(["TEN_ANGLE_REFRACTION"], them_at=(4, 6), ally_at=(2, 7), ally_talents=[])
    me, them, ally = (engine.state.actors[who] for who in (ME, THEM, ALLY))
    _act(engine, "Temper Glass Surface")
    _turn(engine, ALLY)
    _act(engine, "Temper Glass Surface", actor=ALLY)      # the ally's own worn armor is a Glass Surface now
    assert glass_refraction.tempered(engine, ally)
    glass_refraction.give_mark(engine, me, them, "test")
    _answer(engine, "choice:needle.glass_ten_angle", ALLY)
    _answer(engine, "choice:needle.glass_ten_angle_step", "cell:2,6")
    _walk(engine, THEM, [(4, 6), (4, 7)])
    assert (ally.position.x, ally.position.y) == (2, 6), "the ally took the 5-foot step"
    assert ally.temporary_hp == 4, "ending while holding a Glass Surface is one of the printed answers"
    assert any("holding a Glass Surface of their own" in text for text in _logs(engine))


def test_ten_angle_refraction_pays_nothing_for_ground_beside_the_caster():
    engine = _fight(["TEN_ANGLE_REFRACTION"], them_at=(4, 6), ally_at=(2, 6))
    _act(engine, "Temper Glass Surface")
    me, them, ally = (engine.state.actors[who] for who in (ME, THEM, ALLY))
    glass_refraction.give_mark(engine, me, them, "test")
    _answer(engine, "choice:needle.glass_ten_angle", ALLY)
    _answer(engine, "choice:needle.glass_ten_angle_step", "cell:2,5")   # open ground beside the caster
    _walk(engine, THEM, [(4, 6), (4, 7)])
    assert ally.temporary_hp == 0, "standing next to the caster is not behind Cover, holding glass or beside broken glass"


def test_ten_angle_refraction_reaches_only_an_ally_within_thirty_feet():
    """F6: "choose one ally within 30 feet who can see a Glass Surface you control"."""
    engine = _fight(["TEN_ANGLE_REFRACTION"], them_at=(4, 6), ally_at=(10, 6))   # 35 feet away
    _act(engine, "Temper Glass Surface")
    me, them = engine.state.actors[ME], engine.state.actors[THEM]
    glass_refraction.give_mark(engine, me, them, "test")
    calls = _spy(engine, {"choice:needle.refraction_response": "bitter"})
    _walk(engine, THEM, [(4, 6), (4, 7)])
    assert not any(call["asked"] == "choice:needle.glass_ten_angle" for call in calls), \
        "an ally beyond 30 feet is not one the printed line reaches"
    assert glass_refraction._surface_cells(engine, me) == {(me.position.x, me.position.y)}, \
        "and the caster's tempered body is the Glass Surface an in-reach ally would look at"


def test_ten_angle_refraction_does_not_fire_without_a_glass_surface():
    engine = _fight(["TEN_ANGLE_REFRACTION"], them_at=(4, 6), ally_at=(2, 6))
    me, them = engine.state.actors[ME], engine.state.actors[THEM]
    glass_refraction.give_mark(engine, me, them, "test")
    calls = _spy(engine, {"choice:needle.refraction_response": "bitter"})
    _walk(engine, THEM, [(4, 6), (4, 7)])
    assert not any(call["asked"] == "choice:needle.glass_ten_angle" for call in calls), \
        "there is no Glass Surface to control, so the printed trigger is not met"


# ------------------------------------------------------------------------------------------------ Glass Domain and the shell
def test_living_pane_sutras_shattering_shell_fills_the_spaces_around_you_with_shattered_glass():
    from tests.test_auto_lane4 import _script

    engine = _fight(["LIVING_PANE_SUTRA"], them_at=(4, 6))
    me = engine.state.actors[ME]
    _act(engine, "Temper Glass Surface")
    assert glass_refraction.tempered(engine, me), "its body must be a tempered Glass Surface"
    me.current_hp, me.armor_class = 1, 10  # the next hit would take it to 0
    _script(engine, [20])  # it hits
    _stab(engine, target=me)
    assert me.current_hp == 1, "Living Pane Sutra drops to 1 HP instead of 0"
    around = glass_pane.shattered_cells(engine, me)
    assert (me.position.x + 1, me.position.y) in around and (me.position.x - 1, me.position.y) in around, \
        "the shell's Shattered Glass Terrain fills each space adjacent to you"


def test_shattered_glass_terrain_made_inside_the_glass_domain_lasts_until_the_domain_ends():
    """AUTO57r3 review F1: the terrain state AND the line the break writes into the table's history both have to name the
    Domain's longer lifetime.  The log once always said "until the end of your next turn", which is wrong for a patch the
    Domain tied and which therefore has no owner-turn clock at all."""
    engine = _fight(["GLASS_DOMAIN_COURT_OF_VISIBLE_FAULTS", "RAISED_PANE_SCRIPTURE"], them_at=(10, 10))
    me = engine.state.actors[ME]
    _act(engine, "Glass Domain: Court of Visible Faults")
    assert glass_refraction._zones_of(engine, me, {glass_refraction.DOMAIN_ID}), "the Domain is up"
    _turn(engine, THEM)
    engine.end_turn()  # the Domain cost the Action, so the pane goes up on the next turn
    _act(engine, "Raised Pane Scripture", at=(0, 6))  # inside the Domain's 30-foot emanation
    _break(engine, _panes(engine)[0])
    patch = next(zone for zone in engine.state.zones.values()
                 if zone.trigger_profile.get(glass_refraction.DOMAIN_LINK))
    assert patch.duration_rounds is None, "inside the Domain it does not count down; it lasts until the Domain ends"
    assert patch.trigger_profile.get("end_after_owner_turn") is None, \
        "and it has no owner-turn clock, so 'the end of your next turn' is not this patch's deadline"
    said = [text for text in _logs(engine) if "Shattered Glass Terrain fills its square" in text]
    assert said == ["The Glass Pane shatters: Shattered Glass Terrain fills its square until your Glass Domain ends."], \
        f"the table is told the deadline this terrain actually got, got={said}"
    from combat import zones

    domain = next(z for z in glass_refraction._zones_of(engine, me, {glass_refraction.DOMAIN_ID}))
    zones.remove(engine, domain, "the Domain ended")
    assert not engine.state.zones[patch.zone_id].active, "the terrain leaves with the Domain"


def test_shattered_glass_terrain_in_the_glass_domain_outlives_the_owners_next_turn():
    """AUTO57r1 review F2: creating the patch dispatches ZONE_CREATED first, so the Domain handler had already tied it to the
    Domain and cleared its countdown; ``owner_turn_terrain`` then stamped the owner's next turn on it anyway and the terrain was
    swept at the end of that turn while the Domain still stood.  "Shattered Glass Terrain you create inside the Domain lasts
    until the Domain ends" is the longer printed lifetime and wins."""
    engine = _fight(["GLASS_DOMAIN_COURT_OF_VISIBLE_FAULTS", "RAISED_PANE_SCRIPTURE"], them_at=(10, 10))
    me = engine.state.actors[ME]
    _act(engine, "Glass Domain: Court of Visible Faults")
    _turn(engine, THEM)
    engine.end_turn()  # the Domain cost the Action, so the pane goes up on the next turn
    _act(engine, "Raised Pane Scripture", at=(0, 6))  # inside the Domain's 30-foot emanation
    _break(engine, _panes(engine)[0])
    patch = next(zone for zone in engine.state.zones.values()
                 if (zone.center.x, zone.center.y) == (0, 6))
    assert patch.trigger_profile.get(glass_refraction.DOMAIN_LINK), \
        "the broken pane's own terrain is the patch the Domain's printed lifetime takes over"
    assert patch.trigger_profile.get("end_after_owner_turn") is None, \
        "a patch the Domain has taken over carries no owner-turn clock"
    for who in (THEM, ME):
        _turn(engine, who)
        engine.end_turn()
    assert engine.state.zones[patch.zone_id].active, \
        "the terrain stays through the owner's next turn while the Domain stands"
    assert (0, 6) in glass_pane.shattered_cells(engine, me)


def test_shattered_glass_terrain_in_the_glass_domain_keeps_its_lifetime_through_a_table_commit_and_reload(tmp_path):
    """AUTO57r1 review F2 / checklist 7: the Domain's tie is a zone id string on the zone's own record, so a fight the table
    committed and read back off disk still gives the terrain the Domain's lifetime -- never the end of its owner's next turn."""
    from tests.r1i_service_support import OWNER, fixture

    talent = T + "GLASS_DOMAIN_COURT_OF_VISIBLE_FAULTS"
    combat, table, mid, send, commit = fixture(tmp_path, GLASS_TALENTS + [talent],
                                              positions={OWNER: {"x": 3, "y": 6}, "actor:factory.r1i-foe": {"x": 4, "y": 6},
                                                         "actor:factory.r1i-second": {"x": 5, "y": 6}})
    cid, _menu = _at(table, mid, "Glass Domain: Court of Visible Faults")
    assert commit(cid)["status"] == "COMMITTED"
    # the Domain cost the Action, so the pane goes up on the caster's next turn
    assert commit(table.state(mid)["menu"]["end_turn"])["status"] == "COMMITTED"
    while table.state(mid)["menu"]["actor_id"] != OWNER:
        commit(table.state(mid)["menu"]["end_turn"])
    cid, _menu = _at(table, mid, "Raised Pane Scripture", (0, 6))
    assert commit(cid)["status"] == "COMMITTED"

    # the fight comes back off disk, and the Domain's printed lifetime is read out of it on its own square
    reloaded = reload_session(combat, mid).engine
    mine = reloaded.state.actors[OWNER]
    assert glass_pane.panes_of(reloaded, mine), "the pane the table committed is in the reloaded fight"
    assert any((p.position.x, p.position.y) == (0, 6) for p in glass_pane.panes_of(reloaded, mine)), "on the aimed square"

    from combat.gate2_runtime_models import ActionIntent
    from combat.ext import objects

    panes = glass_pane.panes_of(reloaded, mine)
    reloaded._active_intent = ActionIntent(intent_id="break", decision_id="break", candidate_id="break", state_version=0,
                                           actor_id=OWNER, target_ids=(), destination=None)
    before = set(reloaded.state.zones)
    try:
        objects.deal(reloaded, mine, panes[0], [(999, "SLASHING")], T + "RAISED_PANE_SCRIPTURE")
    finally:
        reloaded._active_intent = None
    patch = next(zone for zone in reloaded.state.zones.values()
                 if zone.zone_id not in before and (zone.center.x, zone.center.y) == (0, 6))
    assert patch.trigger_profile.get(glass_refraction.DOMAIN_LINK), \
        "the pane's terrain inside the Domain is tied to it in the reloaded fight"
    assert type(patch.trigger_profile[glass_refraction.DOMAIN_LINK]) is str, "the tie is a zone id string, not an object"
    assert patch.trigger_profile.get("end_after_owner_turn") is None, "and carries no owner-turn clock"
    assert patch.duration_rounds is None, "and does not count down"
    # the owner's next turn passes without taking the terrain with it
    for _ in range(3):
        _turn(reloaded, OWNER)
        reloaded.end_turn()
    assert reloaded.state.zones[patch.zone_id].active, \
        "the Domain's terrain outlives the owner's next turn in the reloaded fight"


def test_a_hostile_creature_that_crosses_a_glass_surface_inside_the_glass_domain_is_marked():
    engine = _domain(["GLASS_DOMAIN_COURT_OF_VISIBLE_FAULTS"], them_at=(4, 6))
    me, them = engine.state.actors[ME], engine.state.actors[THEM]
    _clear_shattered(engine)      # the Domain's own broken glass would mark the mover by another rule
    assert not glass_refraction.marked(them, ME)
    _walk(engine, THEM, [(4, 6), (3, 6)])  # it steps onto the square your tempered body covers
    assert glass_refraction.marked(them, ME), "crossing a Glass Surface inside the Domain earns the Domain's Faultline Mark"
    assert them.turn_flags.get(f"glass_domain:{ME}") == engine.state.round_number


def test_crossing_a_glass_surface_outside_the_glass_domain_is_not_the_domains_mark():
    """F9: the old code only asked whether the creature had *ended* up inside the Domain and looked at the whole path, so
    crossing a pane outside the Domain that ended inside it spent the Domain's once-a-round mark."""
    engine = _fight(["GLASS_DOMAIN_COURT_OF_VISIBLE_FAULTS", "RAISED_PANE_SCRIPTURE"], me_at=(9, 6), them_at=(1, 6))
    me, them = engine.state.actors[ME], engine.state.actors[THEM]
    _act(engine, "Glass Domain: Court of Visible Faults")
    _turn(engine, THEM)
    engine.end_turn()      # the Domain cost the Action, so the pane goes up on the next turn
    _act(engine, "Raised Pane Scripture", at=(0, 6))   # at the arena's edge, outside the Domain's 30 feet
    cells = {(pane.position.x, pane.position.y) for pane in _panes(engine)}
    inside = next(iter(glass_refraction._domain_cells(engine, me, them).values()))
    assert cells and not (cells & inside), "the panes stand outside the Domain"
    _walk(engine, THEM, [(1, 6), (2, 6), (3, 6)])    # it crosses the pane and walks into the Domain
    assert (them.position.x, them.position.y) in inside, "and it ends inside the Domain"
    assert them.turn_flags.get(f"glass_domain:{ME}") is None, \
        "the Domain's once-a-round mark is not spent by a crossing that happened outside it"
    mark = next(row for row in them.conditions.values() if row.condition_id.endswith(f".{ME}"))
    assert mark.source_definition_id == "GLASS_BASE_FAULTLINE_MARKS", \
        "the mark that does land comes from Faultline Marks' own broken-glass line, not from the Domain"


def test_an_attack_that_passes_through_the_casters_glass_inside_the_glass_domain_is_marked():
    """F9: the printed trigger is "attacks through a Glass Surface", so the attack's own path decides."""
    from tests.test_auto_lane4 import _script

    engine = _fight(["GLASS_DOMAIN_COURT_OF_VISIBLE_FAULTS"], them_at=(2, 6), ally_at=(6, 6))
    me, them, ally = (engine.state.actors[who] for who in (ME, THEM, ALLY))
    _act(engine, "Glass Domain: Court of Visible Faults")
    _act(engine, "Temper Glass Surface")
    me.position = Position(x=4, y=6)   # the caster stands between the thrower and its target
    me.armor_class = ally.armor_class = 60
    _script(engine, [1])  # the printed trigger is the attack, so a miss counts too
    _throw(engine, ally)
    assert glass_refraction.marked(them, ME), "the blow came through the caster's tempered body"


def test_an_attack_that_misses_the_casters_glass_is_not_the_domains_mark():
    """F9: the old code marked any attack on any ally standing in the Domain, whether it came through glass or not."""
    from tests.test_auto_lane4 import _script

    engine = _fight(["GLASS_DOMAIN_COURT_OF_VISIBLE_FAULTS"], them_at=(5, 6), ally_at=(6, 6))
    me, them, ally = (engine.state.actors[who] for who in (ME, THEM, ALLY))
    _act(engine, "Glass Domain: Court of Visible Faults")
    _act(engine, "Temper Glass Surface")
    me.position = Position(x=4, y=6)
    me.armor_class = ally.armor_class = 60
    _script(engine, [1])
    _throw(engine, ally)
    assert not glass_refraction.marked(them, ME), "an attack on an ally that never touches a Glass Surface earns nothing"
    assert them.turn_flags.get(f"glass_domain:{ME}") is None


def test_a_hostile_creature_attacking_through_the_domain_glass_at_an_ally_outside_is_marked():
    """AUTO57r1 review F5: the printed clause requires the hostile attacker to be inside the Domain and to attack *through* one
    of its Glass Surfaces; it names no side for the creature attacked and does not put it inside either. The old code demanded an
    allied victim standing inside the Domain, so an attacker inside shooting through the caster's own tempered body at an ally
    who had stepped outside earned nothing."""
    from tests.test_auto_lane4 import _script

    engine = _fight(["GLASS_DOMAIN_COURT_OF_VISIBLE_FAULTS"], them_at=(6, 6), ally_at=(10, 6))
    me, them, ally = (engine.state.actors[who] for who in (ME, THEM, ALLY))
    _act(engine, "Glass Domain: Court of Visible Faults")
    _act(engine, "Temper Glass Surface")
    me.position = Position(x=8, y=6)   # the caster stands inside the Domain, between the thrower and its target
    me.armor_class = ally.armor_class = 60
    inside_them = glass_refraction._domain_cells(engine, me, them)
    inside_ally = glass_refraction._domain_cells(engine, me, ally)
    assert any((them.position.x, them.position.y) in cells for cells in inside_them.values()), "the attacker is inside"
    assert not any((ally.position.x, ally.position.y) in cells for cells in inside_ally.values()), \
        "and the ally it shoots has stepped outside the Domain"
    _script(engine, [1])  # the printed trigger is the attack, so a miss counts too
    _throw(engine, ally)
    assert glass_refraction.marked(them, ME), \
        "a hostile attacker inside that attacks through one of your Glass Surfaces earns the mark, wherever the target stands"
    assert them.turn_flags.get(f"glass_domain:{ME}") == engine.state.round_number


def test_a_hostile_creature_attacking_through_glass_outside_the_domain_is_not_the_domains_mark():
    """AUTO57r1 review F5: the attacker must be inside. This one stands outside, so the same blow through the caster's body is
    not this line's mark."""
    from tests.test_auto_lane4 import _script

    engine = _fight(["GLASS_DOMAIN_COURT_OF_VISIBLE_FAULTS"], them_at=(13, 6), ally_at=(10, 6))
    me, them, ally = (engine.state.actors[who] for who in (ME, THEM, ALLY))
    _act(engine, "Glass Domain: Court of Visible Faults")
    _act(engine, "Temper Glass Surface")
    me.position = Position(x=12, y=6)
    me.armor_class = ally.armor_class = 60
    assert not any((them.position.x, them.position.y) in cells
                   for cells in glass_refraction._domain_cells(engine, me, them).values()), "the attacker is outside"
    _script(engine, [1])
    _throw(engine, ally)
    assert not glass_refraction.marked(them, ME), "an attacker outside the Domain is not this line's trigger"
    assert them.turn_flags.get(f"glass_domain:{ME}") is None


def test_an_attacker_outside_the_domain_through_glass_inside_it_is_not_the_domains_mark():
    """AUTO57r2 review F2: the attacker-inside half of "a hostile creature inside [the Domain] ... attacks through a Glass
    Surface [inside it]" is its own requirement. Reading it off the Domain's interior squares made a live Domain enough on
    its own -- ``_domain_cells`` decides each square with the probe standing on it, so it answers with interior squares
    whether the attacker is on them or not -- and an attacker shooting in from outside earned the mark through glass it
    never stood in. The earlier outside test moved the caster *and* the crossed glass outside, so it never caught this."""
    from tests.test_auto_lane4 import _script

    engine = _fight(["GLASS_DOMAIN_COURT_OF_VISIBLE_FAULTS"], them_at=(10, 6), ally_at=(6, 6))
    me, them, ally = (engine.state.actors[who] for who in (ME, THEM, ALLY))
    _act(engine, "Glass Domain: Court of Visible Faults")
    _act(engine, "Temper Glass Surface")
    me.position = Position(x=8, y=6)   # the caster's own body is the glass, and it is inside the Domain
    me.armor_class = ally.armor_class = 60
    assert glass_refraction._domain_zones(engine, me, me), "the caster's own body is inside the Domain"
    assert not glass_refraction._domain_zones(engine, me, them), "and the attacker standing 2 squares further out is not"
    assert (8, 6) in glass_refraction._surface_cells(engine, me), "the blow passes through the caster's tempered body"
    _script(engine, [1])
    _throw(engine, ally)
    assert not glass_refraction.marked(them, ME), \
        "glass inside the Domain is glass the attacker must already be inside to shoot through"
    assert them.turn_flags.get(f"glass_domain:{ME}") is None


def test_terrain_tied_to_a_domain_leaves_with_it_when_the_domain_ends_inside_another_event():
    """AUTO57r2 review F1: a Domain that ends *inside* another event -- damage committed while another event is being
    handled fails the caster's Concentration -- raises a nested ZONE_REMOVED, and the engine only offers a nested event to
    subscribers that opted into nested delivery. Terrain tied to that Domain was therefore never cleaned up, and with no
    owner-turn clock and no countdown it lasted the rest of the fight. The older test removed the Domain outside event
    handling, which is the path that already worked."""
    engine = _domain(["RAISED_PANE_SCRIPTURE", "GLASS_DOMAIN_COURT_OF_VISIBLE_FAULTS"], them_at=(10, 10))
    me, them = engine.state.actors[ME], engine.state.actors[THEM]
    _turn(engine, ME)                    # the Domain and the tempering spent the caster's turn; the pane goes up on the next
    _act(engine, "Raised Pane Scripture", at=(0, 6))
    _break(engine, _panes(engine)[0])
    patch = next(zone for zone in engine.state.zones.values() if zone.trigger_profile.get(glass_refraction.DOMAIN_LINK))
    assert patch.duration_rounds is None and patch.trigger_profile.get("end_after_owner_turn") is None, \
        "the patch has no clock of its own: the Domain is the whole of its lifetime"
    assert me.concentration is not None, "the caster is concentrating when the Domain ends"
    assert engine.state.zones[patch.trigger_profile[glass_refraction.DOMAIN_LINK]].active, \
        "and the Domain the patch is tied to is still standing"

    # the Domain ends inside the damage event: the shape the review names -- damage from a movement-triggered response. The
    # wrapper stands on one of the Glass Domain's own event helpers, which every committed move reaches, and deals the
    # caster's own damage from inside that event. The scripted 1 fails each Concentration save, so the pane's own copy
    # ends first and the Domain resumes, then the Domain's ends. The first ZONE_REMOVED is the pane's; the Domain's is
    # raised while the move's own event is still being handled, which is the nested delivery in question.
    original = glass_refraction._shattered_mark

    def deal_damage_inside_the_event(this, mover, path):
        original(this, mover, path)
        for _ in range(2):
            if me.concentration is not None:
                this._commit_damage(me, 999, "SLASHING", glass_refraction.RESPONSES_ID, them.entity_id, None,
                                    reaction_depth=1)

    from tests.test_auto_lane4 import _script

    glass_refraction._shattered_mark = deal_damage_inside_the_event
    try:
        _script(engine, [1])
        _walk(engine, THEM, [(9, 9), (9, 8)])
    finally:
        glass_refraction._shattered_mark = original

    assert me.concentration is None, "both Concentration checks failed inside the movement event"
    assert not any(zone.zone_id == patch.zone_id and zone.active for zone in engine.state.zones.values()), \
        "so the terrain tied to that Domain left with it, even though its removal was a nested event"
    assert (0, 6) not in glass_pane.shattered_cells(engine, me)


def test_the_domain_link_and_the_terrains_lifetime_survive_a_table_commit_and_reload(tmp_path):
    """AUTO57r2 review F3: the earlier commit/reload test reloaded the Domain and an intact pane, then broke the pane and
    wrote the terrain in that one in-memory engine -- nothing after it was ever committed, so no round trip could show
    whether the tie itself survived, and the string-type assertion it ended on could not detect a lost link or a changed
    lifetime. This one breaks the pane through the table's own object attack, so the terrain is written and committed by
    the table, reads the fight back off disk, and checks both halves of the printed promise on what came back: the terrain
    outlives the owner's next turn, and it leaves when the Domain does."""
    from combat import concentration
    from tests.r1i_service_support import OWNER, FOE, fixture

    talent = T + "GLASS_DOMAIN_COURT_OF_VISIBLE_FAULTS"

    def stocked(bundles):
        """A fighter with Qi to spare for three object attacks: the pane is a solid 85 HP and this test is about the round
        trip, not about the enemy's resource management."""
        for bundle, actor in zip(bundles, (OWNER, FOE, "actor:factory.r1i-second")):
            if actor != FOE:
                continue
            for row in bundle["actor_template"]["resources"]:
                if row["resource_id"].endswith(".qi"):
                    row["initial"] = row["maximum"] = 300

    combat, table, mid, send, commit = fixture(tmp_path, GLASS_TALENTS + [talent],
                                              foe_talents=["tianxia.subpath.qi.dust_cultivator.feature.dust_to_dust"],
                                              bundle_transform=stocked,
                                              positions={OWNER: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 6},
                                                         "actor:factory.r1i-second": {"x": 5, "y": 6}})
    cid, _menu = _at(table, mid, "Glass Domain: Court of Visible Faults")
    assert commit(cid)["status"] == "COMMITTED"
    # the Domain cost the Action, so the pane goes up on the caster's next turn
    assert commit(table.state(mid)["menu"]["end_turn"])["status"] == "COMMITTED"
    while table.state(mid)["menu"]["actor_id"] != OWNER:
        commit(table.state(mid)["menu"]["end_turn"])
    cid, _menu = _at(table, mid, "Raised Pane Scripture", (0, 6))
    assert commit(cid)["status"] == "COMMITTED"

    # the enemy's own blow, offered by the table against the pane object, until that pane is down to 0 HP
    for _ in range(4):
        session = reload_session(combat, mid)
        wanted = next((pane for pane in glass_pane.panes_of(session.engine, session.engine.state.actors[OWNER])
                       if (pane.position.x, pane.position.y) == (0, 6)), None)
        if wanted is None:
            break
        for _turn_index in range(12):
            menu = table.state(mid)["menu"]
            options = [option for group in menu["actions"] if "Crumble Matter" in group["label"]
                       for option in group["options"] if list(option.get("target_ids") or ()) == [wanted.object_id]]
            if menu["actor_id"] == FOE and options:
                assert commit(options[0]["candidate_id"])["status"] == "COMMITTED", \
                    "the enemy's own object attack on the pane is a committed table action"
                break
            commit(menu["end_turn"])
        else:
            raise AssertionError("the enemy was never offered its own blow at the pane")
    session = reload_session(combat, mid)
    engine = session.engine
    mine = engine.state.actors[OWNER]
    assert not any((pane.position.x, pane.position.y) == (0, 6) for pane in glass_pane.panes_of(engine, mine)), \
        "the pane the enemy broke is broken in the fight that comes back off disk"
    patch = next(zone for zone in engine.state.zones.values()
                 if zone.active and (zone.center.x, zone.center.y) == (0, 6))
    assert type(patch.trigger_profile.get(glass_refraction.DOMAIN_LINK)) is str \
        and patch.trigger_profile[glass_refraction.DOMAIN_LINK] in engine.state.zones, \
        "the Domain's tie is in the committed fight, as the zone id string of a Domain that is really there"
    assert patch.trigger_profile.get("end_after_owner_turn") is None and patch.duration_rounds is None, \
        "and the committed terrain carries no owner-turn clock and no round countdown"
    domain_zone = engine.state.zones[patch.trigger_profile[glass_refraction.DOMAIN_LINK]]
    assert domain_zone.active, "the Domain it is tied to is still standing in the reloaded fight"
    # AUTO57r3 review F1 at the table: the deadline the break wrote into the fight's own history is part of the committed
    # record too, so a fight read back off disk still tells the players the Domain's deadline rather than a stale one.
    said = [text for text in _logs(engine) if "Shattered Glass Terrain fills its square" in text]
    assert said == ["The Glass Pane shatters: Shattered Glass Terrain fills its square until your Glass Domain ends."], \
        f"the reloaded fight's history names the deadline the terrain really has, got={said}"

    # the owner's next turn passes and the terrain stays: "lasts until the Domain ends", not "until your next turn"
    for _ in range(2):
        _turn(engine, OWNER)
        engine.end_turn()
    assert engine.state.zones[patch.zone_id].active, "the Domain's terrain outlives the owner's next turn after the reload"
    assert session.mechanical.replay()["status"] == "PASS", "and the reloaded fight is still mechanically sound"

    # the Domain ends: the terrain leaves with it, in the reloaded fight
    held = next((instance for instance, state in concentration.held(mine) if state.zone_id == domain_zone.zone_id), None)
    assert held is not None, "the Domain is a held Concentration of the caster's"
    concentration.end_held(engine, mine, held, "TEST")
    assert not engine.state.zones[patch.zone_id].active, "so the terrain tied to it left with it"
    assert (0, 6) not in glass_pane.shattered_cells(engine, mine)


def test_the_domain_mark_is_the_casters_own_decision_on_any_turn():
    """Checklist 9: the printed "you may place a Faultline Mark" belongs to the caster, so it is asked even while the other
    side is taking its turn, and an Ask me fighter that nobody answers leaves the mark on the table."""
    from tests.test_auto_lane4 import _script

    engine = _domain(["GLASS_DOMAIN_COURT_OF_VISIBLE_FAULTS"], them_at=(2, 6), ally_at=(6, 6), modes="MANUAL")
    me, them, ally = (engine.state.actors[who] for who in (ME, THEM, ALLY))
    me.position = Position(x=4, y=6)     # the caster stands between the thrower and its target
    me.armor_class = ally.armor_class = 60
    _script(engine, [1])
    calls = []
    _nobody_answers(engine, calls)
    _throw(engine, ally)
    assert any(call["asked"] == "choice:needle.glass_domain_mark" for call in calls), \
        "an Ask me fighter is asked, even while something else is taking its turn"
    assert not glass_refraction.marked(them, ME), "and nothing happens until its player answers"
    assert them.turn_flags.get(f"glass_domain:{ME}") is None, "the round is reserved only on use"

    engine = _domain(["GLASS_DOMAIN_COURT_OF_VISIBLE_FAULTS"], them_at=(2, 6), ally_at=(6, 6), modes="MANUAL")
    me, them, ally = (engine.state.actors[who] for who in (ME, THEM, ALLY))
    me.position = Position(x=4, y=6)
    me.armor_class = ally.armor_class = 60
    _script(engine, [1])
    _answer(engine, "choice:needle.glass_domain_mark", "mark")
    _throw(engine, ally)
    assert glass_refraction.marked(them, ME), "the player's answer places it"


# ------------------------------------------------------------------------------------------------ the table service
GLASS_TALENTS = [T + "RAISED_PANE_SCRIPTURE", T + "WALKING_PANE_BODY"]


def _at(table, match_id, label, cell=None):
    """The table button for ``label`` (aimed at ``cell`` when one is given)."""
    menu = table.state(match_id)["menu"]
    group = next(group for group in menu["actions"] if label in group["label"])
    options = group["options"] if cell is None else [option for option in group["options"]
                                                    if (option.get("destination") or {}) == {"x": cell[0], "y": cell[1]}]
    assert options, f"{label} has no button for {cell}"
    return options[0]["candidate_id"], menu


def test_a_pane_keeps_its_deadlines_through_a_table_commit_and_reload(tmp_path):
    """F1 / checklist 7: the pane's own records are strings and integers, and a committed fight reads them back with the
    same deadlines: the 1-minute name, the Concentration copy that made it and (for a free-standing pane) the collapse."""
    from combat.gate5_service import CombatService
    from tests.r1i_service_support import OWNER, fixture, candidate

    combat, table, mid, send, commit = fixture(tmp_path, GLASS_TALENTS,
                                              positions={OWNER: {"x": 3, "y": 6}, "actor:factory.r1i-foe": {"x": 4, "y": 6},
                                                         "actor:factory.r1i-second": {"x": 5, "y": 6}})
    cid, menu = _at(table, mid, "Raised Pane Scripture", (0, 6))
    assert commit(cid)["status"] == "COMMITTED"

    session = CombatService(combat.source_root, combat.userdata_root)._load_session(mid)
    engine = session.engine
    panes = glass_pane.panes_of(engine, engine.state.actors[OWNER])
    assert panes, "the pane the table committed is in the reloaded fight"
    assert any((pane.position.x, pane.position.y) == (0, 6) for pane in panes), "the square the table aimed at rose a pane"
    for pane in panes:
        assert type(pane.component["deadline"]) is str and pane.component["deadline"].startswith("START_OF_SLOT_AT:")
        assert type(pane.component["copy_start"]) is int and pane.component["copy_start"] > 0
        assert type(pane.component["anchored"]) is int
    assert engine.state.actors[OWNER].concentration.source_definition_id.endswith("RAISED_PANE_SCRIPTURE")
    assert session.mechanical.replay()["status"] == "PASS"

    # the pane still ends with that Concentration, after the reload
    engine._end_concentration(engine.state.actors[OWNER], "TEST")
    assert not glass_pane.panes_of(engine, engine.state.actors[OWNER])


def test_the_melee_hit_record_survives_a_table_commit_and_reload(tmp_path):
    """F4 / checklist 7 and 9: the mark is offered by the real table while the other side is attacking, the answer is the
    player's, and which creature's hit earned it (and the turn the promise ends) is stored on the fight itself."""
    from tests.r1i_service_support import OWNER, FOE, fixture, candidate

    combat, table, mid, send, commit = fixture(tmp_path, GLASS_TALENTS, owner_ac=1,
                                              positions={OWNER: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 6},
                                                         "actor:factory.r1i-second": {"x": 5, "y": 6}})
    cid, _menu = _at(table, mid, "Temper Glass Surface")
    assert commit(cid)["status"] == "COMMITTED"
    while table.state(mid)["menu"]["actor_id"] != FOE:
        commit(table.state(mid)["menu"]["end_turn"])

    # the enemy's real melee hit on the tempered body, answering every prompt the way a player would
    asked, answers = [], []
    attack = candidate(table, mid, "Unarmed Strike", OWNER)
    for _ in range(8):
        result = send(attack, answers)
        if result["status"] == "COMMITTED":
            break
        prompt = result["reaction"]
        asked.append(prompt)
        answer = {**prompt["context"], "selection": "DECLINE"}
        assert prompt["context"]["reactor_id"] == OWNER, "the mark is the caster's to place"
        if prompt.get("choice"):
            options = prompt["choice"]["options"]
            answer.update(selection="USE",
                          option_ids=(prompt["choice"].get("preferred") or [options[0]["id"]])[:1])
        answers.append(answer)
    assert asked, "the table stopped and asked its player who earns the mark, on the enemy's own turn"
    assert result["status"] == "COMMITTED"

    session = reload_session(combat, mid)
    engine, mine, theirs = session.engine, session.engine.state.actors[OWNER], session.engine.state.actors[FOE]
    row = next((row for row in mine.conditions.values() if row.condition_id == f"{PANE_MARK}.{theirs.entity_id}"), None)
    assert row is not None, "the record of the melee hit is in the reloaded fight"
    assert row.data["creature"] == FOE and type(row.data["creature"]) is str
    assert row.expires_on == f"END_OF_TURN_AT:{OWNER}:{int(mine.turns_started) + 1}"
    assert glass_refraction.marked(theirs, OWNER)
    assert session.mechanical.replay()["status"] == "PASS"

    # spending that creature's mark in the reloaded fight still pays the Temporary HP
    glass_refraction._pane_body_pay(engine, mine, theirs)
    assert mine.temporary_hp == 4
    assert not any(row.condition_id.startswith(PANE_MARK) for row in mine.conditions.values())


def test_the_walking_pane_body_record_is_described_on_a_fighters_sheet():
    """AUTO57r1 review checklist 13: the status handler read ``getattr(row, "condition_id", "")`` while the status hook is handed
    a dict (combat/status_text.py ``describe``), and compared it with the unsuffixed id, so the card could never appear even
    though the record's own id carries the creature whose hit earned the mark."""
    from types import SimpleNamespace

    from combat import status_text

    fight = SimpleNamespace(action_catalog={}, state=SimpleNamespace(actors={}))
    condition = f"{PANE_MARK}.{THEM}"
    row = {"condition_id": condition, "source_definition_id": T + "WALKING_PANE_BODY", "source_actor_id": ME,
           "display_name": "Walking Pane Body"}
    data = {"creature": THEM,
            "label": f"Walking Pane Body: spending the marked foe's Faultline Mark before the end of your next turn "
                     f"gives you 4 Temporary HP"}
    supplied = glass_refraction.pane_mark_status(fight, ME, row, data)
    assert supplied is not None, "the handler answers a condition row that is a dict"
    assert "4 Temporary HP" in supplied["text"], "and it names the creature and the reward in plain words"
    assert "Temporary HP" in supplied["handling"], "and it says when the offer ends"

    card = status_text.describe(fight, ME, row, data, {}, {})
    written = " ".join(str(value) for value in card.values())
    assert "4 Temporary HP" in written, "so the fighter's sheet really shows this record"


def test_the_status_handler_leaves_other_conditions_alone():
    """A plug-in is inert for records it does not own (change standard 3)."""
    from types import SimpleNamespace

    fight = SimpleNamespace(action_catalog={}, state=SimpleNamespace(actors={}))
    for row in ({"condition_id": "condition:typed.glass_tempered"},
                {"condition_id": f"{PANE_MARK}"},
                {"condition_id": "condition:typed.something_else.actor:factory.b"},
                {}):
        assert glass_refraction.pane_mark_status(fight, ME, row, {}) is None, row


def test_a_free_standing_pane_keeps_its_collapse_deadline_through_a_table_commit_and_reload(tmp_path):
    """AUTO57r1 review checklist 7: the pane commit/reload test only ever raised an anchored pane, so nothing proved the
    "collapse" record -- the name that ends a free-standing pane -- survives a commit."""
    from tests.r1i_service_support import OWNER, fixture

    combat, table, mid, send, commit = fixture(tmp_path, GLASS_TALENTS + [T + "PANE_STEP_PROJECTION"],
                                              positions={OWNER: {"x": 3, "y": 6}, "actor:factory.r1i-foe": {"x": 4, "y": 6},
                                                         "actor:factory.r1i-second": {"x": 5, "y": 6}})
    while table.state(mid)["menu"]["actor_id"] != OWNER:
        commit(table.state(mid)["menu"]["end_turn"])
    cid, _menu = _at(table, mid, "Raised Pane Scripture", (0, 6))
    assert commit(cid)["status"] == "COMMITTED"

    session = reload_session(combat, mid)
    engine, mine = session.engine, session.engine.state.actors[OWNER]
    panes = glass_pane.panes_of(engine, mine)
    assert panes, "the pane the table committed is in the reloaded fight"
    loose = [pane for pane in panes if not pane.component["anchored"]]
    assert loose, "the table's own answer to Pane-Step Projection asked for a pane anchored to nothing"
    for pane in loose:
        assert type(pane.component["collapse"]) is str, "the collapse record is a string, so a saved fight replays it"
        assert pane.component["collapse"] == f"END_OF_TURN_AT:{OWNER}:{int(mine.turns_started) + 1}", \
            "and it is still the end of the owner's next turn after the reload"


def reload_session(combat, match_id):
    """A fresh service over the same userdata: the fight as it comes back off disk."""
    from combat.gate5_service import CombatService

    return CombatService(combat.source_root, combat.userdata_root)._load_session(match_id)

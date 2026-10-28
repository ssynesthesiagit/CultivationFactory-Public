"""AUTO23 + AUTO23f1: the Space sphere's printed effects happen at the table.

Owner 2026-10-04 ("automate everything"): every talent and base ability of the Space sphere is audited
against its printed text (authority/typed_mechanics/rules_text.json) and typed as far as the fight
engine can carry it.  AUTO23f1 (2026-10-05) fixed what the review found in that lane:

* Short Swap declared both squares legal but tested one cell and no height, and listed the *other*
  creature's own departing cells as obstacles, so a Large creature could never exchange places.  It
  also ignored the printed "Short Swap cannot force an unwilling creature to move" and moved any
  creature at all.  All three are now real rules (combat/ext/space_swap.py), each with a test that
  fails without the fix.
* Phase Step's "you cannot be Grappled or Restrained by ordinary physical means" refused *every*
  grapple and *every* restraint, whatever put them on; it now refuses only an ordinary physical blow,
  and the condition pill no longer promises a Difficult-Terrain step the fight map cannot make.
* Space Between Blades' "Then choose one" was compiled as three options the table had to pick before
  the fight, so the two other choices were unreachable at resolution; the first choice moved nothing
  and was free of *everyone's* opportunity attacks; the second took away the attacker's whole
  Reaction instead of only its Opportunity Attacks against this creature; and the third choice
  (Proficiency Bonus Force damage on the next melee hit) registered nothing at all.
* Blink Guard's and Space Between Blades' questions now name the printed trigger, the ability and the
  creature affected.

AUTO23r1f1 (2026-10-05) fixed what the review of AUTO23f1 found in that lane:

* Phase Step's immunity read "ordinary physical means" as "a confirmed hit", so the ordinary Grapple -- a
  Strength-or-Dexterity *save* whose condition sits in the failure branch -- walked straight through it, and a
  magical grapple that landed would have been refused instead.  The source is now read from the row that is
  trying, through the shared ``combat/ext/physical_holds.ordinary`` classifier, with a real Grapple regression
  and Black-Star Grip and Meridian Lock as the magical counterexamples.
* Space Between Blades' bonus carried the engine's ``END_OF_HOLDER_NEXT_TURN``, which ends with whichever turn
  the holder is next on -- this one, when a missed Opportunity Attack armed it during the reactor's own turn.
  It now names the reactor's own *next* turn by its turn counter, tested on both turn owners with real turn
  boundaries.
* The same bonus was spent from ``damage_dealt``, which only fires for a positive damage packet, so a miss or a
  fully prevented hit left it armed for a later attack.  The printed "the next melee attack you make against the
  attacker" is now tracked as the attack: spent by that attack, and a landed one delivers the Force damage
  whatever its ordinary packet did.
* The three questions the ability asks now name the action that triggered them and the creature that used it
  (``combat/ext/trigger_source``), instead of the record's own generic phrase.
* The regressions are behavioural: real Grapple attempts, real Opportunity Attacks (one provoked, one refused
  and another allowed), a real miss, a real immunity, real turn boundaries, and the printed menu answered by a
  player at the table on both turn owners (plus an AI combatant that answers for itself).

Two real harnesses: tests/test_auto_support.py's engine (a real Gate4ControllerEngine built from the
compiled bundles) for the fight-level assertions, and tests/test_hunt32_edge.py's saved table (commit,
journal replay, reload) plus this file's own table for the ones that must survive a save.
"""

from __future__ import annotations

import json

from combat.factory_compiler import TYPED_AUTHORITY, compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.gate2_runtime_models import ActionIntent, CandidateKind, ReactionDecision
from combat.typed_executor import CONDITION_PREFIX
from tests.h1_support import sheet
from tests.test_auto_support import AN, ME, ROOT, _bundle, _engine
from tests.test_hunt32_edge import FOE, OWNER, act, match, reload

ALLY = "actor:factory.h32-ally"
SIDE = "actor:factory.auto23-side0"  # a second creature on ME's own side, for a strike that is not the reactor's
FOE2 = "actor:factory.auto23-foe1"

SPACE = "tianxia.sphere.space"
SWAP = "tianxia.talent.space.short_swap"
BLINK = "tianxia.talent.space.blink_guard"
PHASE = "tianxia.talent.space.phase_step"
BLADES = "tianxia.talent.space.space_between_blades"
SEVERANCE = "tianxia.talent.space.spatial_severance"
DISPLACE = "tianxia.talent.space.spatial_displacement"
DOMAIN = "tianxia.talent.space.spatial_domain"
VOID = "tianxia.talent.space.void_between_worlds"
EDGE = "TAL_SPACE_SPATIAL_EDGE"
BLACK_STAR_GRIP = "tianxia.talent.gravity.black_star_grip"  # "The target is Grappled by gravitational pressure"
MERIDIAN_LOCK = "tianxia.talent.thread.meridian_lock"  # "it is Restrained until the end of your next turn"
MELEE = "TAL_AXES_SEVER_THE_STANDARD"  # a melee technique to strike with (any sphere may strike at a Space reactor)
MELEE_NAME = "Sever the Standard"
FOLD = "TAL_SPACE_FOLD_STEP"


def _sheet(mids, *, cl=10, attack_bonus=None):
    doc = sheet(mids, cl=cl)
    if attack_bonus is not None:
        doc["ability_scores_and_statistics"]["technique_attack_bonus"] = attack_bonus
    return doc


def _party(mine, *, theirs=(), side=0, foes=1, attacker_bonus=None, cl=10, places=None, seed="AUTO23"):
    """One compiled user plus other creatures, in one real engine (the shape tests/test_riders_lane4.py uses).

    ``side`` creatures share the user's team (so an ALLY_OR_SELF row may name them) and ``foes`` share the
    other one; the first of those is ``AN`` and owns ``theirs``.  ``places`` overrides the starting squares
    as ``{actor_id: {"x": .., "y": .., "z": ..}}``.
    """
    from combat.gate4_engine import Gate4ControllerEngine

    ids, teams, positions = [ME], {ME: "team:a"}, {ME: {"x": 3, "y": 6}}
    bundles = [compile_character(_sheet(mine, cl=cl, attack_bonus=attacker_bonus), actor_id=ME)]
    for index in range(side):
        actor_id = f"actor:factory.auto23-side{index}"
        ids.append(actor_id)
        teams[actor_id] = "team:a"
        positions[actor_id] = {"x": 3 + index, "y": 6}
        bundles.append(compile_character(_sheet([], cl=cl), actor_id=actor_id))
    for index in range(foes):
        actor_id = AN if index == 0 else f"actor:factory.auto23-foe{index}"
        ids.append(actor_id)
        teams[actor_id] = "team:b"
        positions[actor_id] = {"x": 4 + index, "y": 6}
        bundles.append(compile_character(_sheet(theirs if index == 0 else [], cl=cl), actor_id=actor_id))
    positions.update(places or {})
    engine = Gate4ControllerEngine(ROOT, match_seed=seed, typed_bundles=tuple(bundles),
                                   roster_setup={"primary_actor_ids": ids, "team_by_actor": teams,
                                                 "starting_positions": positions})
    _turn(engine, ME)
    return engine


def _duel(mine, theirs, *, attacker_bonus=None):
    """Two compiled characters in one real engine (the shape tests/test_riders_lane4.py uses for a duel)."""
    return _two(mine, theirs, attacker_bonus=attacker_bonus)


def _two(mine, theirs, *, attacker_bonus=None):
    from combat.gate4_engine import Gate4ControllerEngine

    engine = Gate4ControllerEngine(ROOT, match_seed="AUTO23", typed_bundles=(
        compile_character(_sheet(mine, attack_bonus=attacker_bonus), actor_id=ME),
        compile_character(_sheet(theirs), actor_id=AN)),
        roster_setup={"primary_actor_ids": [ME, AN], "team_by_actor": {ME: "team:a", AN: "team:b"},
                      "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": 4, "y": 6}}})
    _turn(engine, ME)
    return engine


def _turn(engine, actor_id):
    engine.state.current_slot_index = engine.state.initiative_order.index(actor_id)
    engine.state.current_actor_id = actor_id
    engine._system_start_turn()
    return engine


def _use(engine, name, actor=ME, target=None):
    candidate = next(c for c in engine.legal_candidates()
                     if c.display_name == name and (target is None or target in c.target_ids))
    engine.execute_intent(ActionIntent(intent_id=name, decision_id=candidate.decision_id,
                                       candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                                       actor_id=actor, target_ids=candidate.target_ids,
                                       destination=candidate.destination))


def _positions(engine):
    return {aid: (actor.position.x, actor.position.y, actor.position.z) for aid, actor in engine.state.actors.items()}


def _tough(engine, actor_id, hp=4000):
    actor = engine.state.actors[actor_id]
    actor.maximum_hp = hp
    actor.current_hp = hp
    actor.armor_class = -50
    actor.skills = {name: -100 for name in (actor.skills or {})}


def _answers(engine, picks):
    """A table that answers each reaction or extension choice whose id contains a key of ``picks``.

    A value may be a list of option ids, a callable taking the options, or None to decline.  Every
    other question is declined.  Returns the requests, so a test can assert what was asked.
    """
    asked = []

    def provider(request):
        asked.append(request)
        options = list(request.get("legal_option_ids") or ())
        for key, pick in picks.items():
            if key in str(request.get("reaction_source_id") or ""):
                chosen = pick(options) if callable(pick) else pick
                if chosen is None:
                    break
                return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                        reaction_source_id=request["reaction_source_id"], selection="USE",
                                        option_ids=tuple(chosen)), None
        return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                reaction_source_id=request["reaction_source_id"], selection="DECLINE",
                                option_ids=()), None

    engine.set_reaction_provider(provider)
    return asked


# --------------------------------------------------------------------------------------------------- Short Swap
def _swap_at_the_table(table, mid, *, agree):
    """Use Short Swap at the table, answering the one question the printed prohibition needs.

    The pause reserves the action, so the answer replays the very same request rather than a fresh menu.
    """
    state = table.state(mid)
    menu = state["menu"]
    group = next(g for g in menu["actions"] if g["label"] == "Short Swap")
    option = next(o for o in group["options"] if ALLY in o.get("target_ids", []))
    args = (option["candidate_id"], menu["decision_id"], menu["state_version"], state["last_sequence"])
    result = table.act(mid, *args)
    if result["status"] == "REACTION_REQUIRED":
        prompt = result["reaction"]
        answer = {**prompt["context"], "selection": "USE" if agree else "DECLINE"}
        if agree:
            answer["option_ids"] = [prompt["choice"]["options"][0]["id"]]
        result = table.act(mid, *args, [answer])
    return result


def test_short_swap_exchanges_both_creatures_squares_and_survives_a_table_commit(tmp_path):
    """"You and the target teleport, swapping spaces": before this lane only the picked creature moved."""
    combat, table, mid = match(tmp_path, [SWAP], allies=True)
    engine = reload(combat, tmp_path, mid)
    before = _positions(engine)
    assert before[OWNER] != before[ALLY]
    assert _swap_at_the_table(table, mid, agree=True)["status"] == "COMMITTED"
    engine = reload(combat, tmp_path, mid)  # the exchange is in the journal, not only in memory
    after = _positions(engine)
    assert after[OWNER] == before[ALLY] and after[ALLY] == before[OWNER]
    moved = [e for e in engine.events if e.event_type == "MOVEMENT_COMMITTED"
             and e.source_definition_id and "short_swap" in e.source_definition_id]
    assert {e.actor_id for e in moved} == {OWNER, ALLY}


def test_short_swap_is_offered_to_an_ai_combatant_with_no_menu_of_its_own(tmp_path):
    """The printed rule names no menu ("choose one willing creature"), so an AI combatant gets the same row a
    player does and the row carries no options of its own.  The only question the exchange asks is the one the
    printed prohibition needs: whether the creature being moved agrees."""
    combat, table, mid = match(tmp_path, [SWAP], mode="LOCAL_AUTO", allies=True, ally_mode="LOCAL_AUTO")
    engine = reload(combat, tmp_path, mid)
    assert engine.state.current_actor_id == OWNER
    candidate = next(c for c in engine.legal_candidates()
                     if c.display_name == "Short Swap" and ALLY in c.target_ids)
    assert not candidate.option_ids, "the printed rule asks no question of anybody"
    assert engine.action_catalog[candidate.source_definition_id].range_ft == 30, "the printed Range is not the row's reach"


def test_short_swap_exchanges_a_large_creature_rather_than_refusing_it():
    """"Both spaces must be ... large enough to safely hold the arriving creature": AUTO23f1.  The first
    version listed the *other* creature's own departing cells as obstacles, so a Large creature standing
    beside the user could never exchange places -- the arrival was refused by the body that was leaving that
    square.  Every cell each arrival's own body needs is now judged, and neither creature is in the other's
    way."""
    ally = "actor:factory.auto23-side0"
    engine = _party([SWAP], side=1, places={ally: {"x": 5, "y": 6}, AN: {"x": 8, "y": 6}})
    engine.state.actors[ally].transformed_size_category = "Large"  # a 2x2 body over four cells
    before = _positions(engine)
    _use(engine, "Short Swap", target=ally)
    after = _positions(engine)
    assert (after[ME][0], after[ME][1]) == (before[ally][0], before[ally][1]), "the user did not arrive on the target's square"
    assert (after[ally][0], after[ally][1]) == (before[ME][0], before[ME][1]), "the Large creature did not arrive on the user's square"


def test_short_swap_refuses_a_square_the_arriving_body_would_cover():
    """"large enough to safely hold the arriving creature": a body that would reach over a square the other
    creature is about to stand in has nowhere safe to land, so the whole exchange is refused.  AUTO23f1: the
    first version of this test asserted ``something or True`` and never moved anything, so it passed whatever
    the plug-in did."""
    ally = "actor:factory.auto23-side0"
    engine = _party([SWAP], side=1, places={ally: {"x": 4, "y": 6}, AN: {"x": 8, "y": 6}})
    engine.state.actors[ally].transformed_size_category = "Large"  # its 2x2 body would cover the user's square
    before = _positions(engine)
    _use(engine, "Short Swap", target=ally)
    assert _positions(engine) == before, "a body that does not fit was exchanged anyway"
    assert any("will not fit safely" in (e.payload or {}).get("rider", "") for e in engine.events
               if e.event_type == "GM_RIDER"), "the table was not told why nothing happened"


def test_short_swap_judges_the_arriving_square_at_its_own_height():
    """"large enough to safely hold the arriving creature": the arriving body's own height is judged too.
    AUTO23f1 asked the flat map whether a square was blocked and ignored the level it was arriving on, so a
    creature could never exchange onto the top of a pillar it can plainly stand on, and nothing checked that
    the square really holds a body at that level."""
    ally = "actor:factory.auto23-side0"
    engine = _party([SWAP], side=1, places={ally: {"x": 4, "y": 6, "z": 3}, AN: {"x": 7, "y": 6}})
    engine.grid.blocked.add((4, 6))  # a 15-foot pillar: solid below its top, open on it
    engine.grid.terrain_heights.setdefault("BLOCKED", {})[(4, 6)] = 15
    assert engine.grid.volume_legal((4, 6, 3), footprint=engine._footprint(engine.state.actors[ally]))
    assert not engine.grid.volume_legal((4, 6, 0)), "the pillar top test needs solid ground below it"
    before = _positions(engine)
    _use(engine, "Short Swap", target=ally)
    after = _positions(engine)
    assert (after[ME][0], after[ME][1], after[ME][2]) == (before[ally][0], before[ally][1], before[ally][2]), \
        "the user did not arrive on the ledge the target was standing on"
    assert (after[ally][0], after[ally][1], after[ally][2]) == (before[ME][0], before[ME][1], before[ME][2]), \
        "the creature on the ledge did not come down"


def test_short_swap_never_moves_an_unwilling_creature_and_asks_one_that_may_refuse():
    """"Short Swap cannot force an unwilling creature to move": AUTO23f1 typed the line as a reminder and moved
    whichever creature the ability was aimed at.  The creature that would be moved is now asked, through the
    shared choice transport, and a refusal leaves everything exactly where it was."""
    ally = "actor:factory.auto23-side0"
    engine = _party([SWAP], side=1, places={ally: {"x": 4, "y": 6}, AN: {"x": 7, "y": 6}})
    asked = _answers(engine, {"space_swap": None})  # the creature declines
    before = _positions(engine)
    _use(engine, "Short Swap", target=ally)
    assert _positions(engine) == before, "a creature that declined was moved anyway"
    assert any("space_swap_agree" in str(request["reaction_source_id"]) for request in asked), \
        "the creature that was about to be moved was never asked"
    assert any("cannot force an unwilling creature" in (e.payload or {}).get("rider", "") for e in engine.events
               if e.event_type == "GM_RIDER")

    engine = _party([SWAP], side=1, places={ally: {"x": 4, "y": 6}, AN: {"x": 7, "y": 6}})
    _answers(engine, {"space_swap": list})  # the creature goes along
    before = _positions(engine)
    _use(engine, "Short Swap", target=ally)
    assert (engine.state.actors[ally].position.x, engine.state.actors[ally].position.y) == (before[ME][0], before[ME][1]), \
        "a willing creature still did not exchange places"


def test_short_swap_never_moves_a_creature_sealed_against_teleporting():
    """"You and the target teleport": both hops answer the teleport locks, so a creature carrying the sealed
    rule (Dimensional Seal and its kin) is not carried off its square by somebody else's hop."""
    ally = "actor:factory.auto23-side0"
    engine = _party([SWAP], side=1, places={ally: {"x": 4, "y": 6}, AN: {"x": 7, "y": 6}})
    before = _positions(engine)
    engine._apply_condition(engine.state.actors[ally], CONDITION_PREFIX + "cannot_teleport", "test:seal", ME,
                            expires_on="UNTIL_REMOVED")
    _use(engine, "Short Swap", target=ally)
    assert _positions(engine) == before, "a sealed creature was teleported by somebody else's hop"


def test_short_swap_is_only_offered_against_the_users_own_side(tmp_path):
    """The printed prohibition at the table: the row is aimed at a creature on the user's own side, never at
    the other side, so the exchange can never begin by forcing somebody."""
    combat, table, mid = match(tmp_path, [SWAP], allies=True)
    swap = next(group for group in table.state(mid)["menu"]["actions"] if group["label"] == "Short Swap")
    offered = {target for option in swap["options"] for target in option.get("target_ids", ())}
    assert offered == {OWNER, ALLY}, offered
    assert FOE not in offered, "the exchange was offered against the other side"


def test_short_swap_refusal_commits_at_the_table_without_moving_anything(tmp_path):
    """A table-level regression for the printed prohibition: the creature refuses, and the commit + journal
    replay + reload keep every creature where it was."""
    combat, table, mid = match(tmp_path, [SWAP], allies=True)
    engine = reload(combat, tmp_path, mid)
    before = _positions(engine)
    assert _swap_at_the_table(table, mid, agree=False)["status"] == "COMMITTED"
    engine = reload(combat, tmp_path, mid)
    assert _positions(engine) == before, "a declined exchange still moved somebody"
    assert not [e for e in engine.events if e.event_type == "MOVEMENT_COMMITTED"
                and "short_swap" in str(e.source_definition_id)]


# ------------------------------------------------------------------------------- Blink Guard and Phase Step
def _blink_provider(*, accept=True):
    """Answer Blink Guard, and the square it asks for (the shared reaction teleport: the square farthest from
    the triggering creature is offered first).  Anything else is declined."""
    asked = []

    def provider(request):
        source = str(request.get("reaction_source_id") or "")
        asked.append(source)
        if "blink_guard" in source or "reaction_teleport" in source:
            options = request.get("legal_option_ids") or []
            return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                    reaction_source_id=request["reaction_source_id"],
                                    selection="USE" if accept and options else "DECLINE",
                                    option_ids=(options[0],) if accept and options else ()), None
        return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                reaction_source_id=request["reaction_source_id"], selection="DECLINE",
                                option_ids=()), None

    return provider, asked


def test_blink_guard_hops_out_of_the_attack_and_asks_for_its_square():
    """"Teleport up to 15 feet to an unoccupied space you can see": the hop is the printed one, it costs the
    printed 2 CP, and the square is the user's to choose (the shared reaction teleport offers every legal one,
    the farthest from the attacker first)."""
    engine = _duel([MELEE], [BLINK])
    provider, asked = _blink_provider()
    engine.set_reaction_provider(provider)
    reactor = engine.state.actors[AN]
    reactor.armor_class = -50
    engine.state.actors[ME].position = reactor.position.model_copy(update={"x": reactor.position.x - 1})
    before = _positions(engine)
    qi = reactor.resources.get("resource:core.qi", 0)
    _turn(engine, ME)
    _use(engine, MELEE_NAME, actor=ME, target=AN)
    assert any(e.event_type == "REACTION_WINDOW_OPENED" and "blink_guard" in str(e.source_definition_id)
               for e in engine.events), "Blink Guard was never offered as a Reaction to the attack"
    assert any("reaction_teleport" in source for source in asked), "the hop never asked for a square"
    assert _positions(engine)[AN] != before[AN], "Blink Guard did not move its user"
    assert reactor.resources.get("resource:core.qi", 0) == qi - 2, "the printed 2 CP was not spent"
    assert any(e.event_type == "MOVEMENT_COMMITTED" and "blink_guard" in str(e.source_definition_id)
               for e in engine.events)


def test_blink_guard_declined_leaves_the_creature_where_it_is():
    """A declined hop changes nothing: the creature stays in reach and the attack resolves as it would."""
    engine = _duel([MELEE], [BLINK])
    provider, _asked = _blink_provider(accept=False)
    engine.set_reaction_provider(provider)
    reactor = engine.state.actors[AN]
    reactor.armor_class = -50
    engine.state.actors[ME].position = reactor.position.model_copy(update={"x": reactor.position.x - 1})
    before = _positions(engine)
    _turn(engine, ME)
    _use(engine, MELEE_NAME, actor=ME, target=AN)
    assert _positions(engine)[AN] == before[AN], "the creature moved although the square was declined"


def test_blink_guard_carries_the_shared_negation_row_after_the_hop():
    """"If the triggering attack would no longer reach you from your new position ... the attack misses you"
    is the engine's own ``negate_attack`` reader, and it must read the position the hop left behind, so it is
    the row AFTER the hop on the same record (combat/typed_executor.block_negate_attack with
    ``if_out_of_reach``).  The reaction still fires on a hit, which is after the attack roll: the shared reader
    only sees an attack answered before it is rolled, so the printed miss is a reminder in that window and is
    listed as an engine seam in the AUTO23 report."""
    record = json.loads(TYPED_AUTHORITY.read_bytes())["mechanics"][BLINK]
    types = [row["type"] for row in record["effects"]]
    assert types == ["space_blink", "negate_attack"], types
    assert record["effects"][1]["if_out_of_reach"] is True
    row = next(r for r in compile_character(sheet([BLINK], cl=10), actor_id=ME)["typed_reactions"]
               if r["feature_id"] == BLINK)
    assert [effect["type"] for effect in row["effects"]] == ["space_blink", "negate_attack"], row["effects"]
    assert row["effects"][1]["if_out_of_reach"] is True


def test_blink_guard_names_the_attack_and_the_creature_it_answered():
    """"Trigger: You are hit by an attack, fail a Dexterity saving throw, or are included in an area effect":
    AUTO23r1f1.  The question used to open "Blink Guard: after the attack, saving throw or area effect it was
    answering" and then name only the teleporting creature, so a player could not tell who was answering
    anything.  The shared reader (combat/ext/trigger_source) supplies the action actually in flight and the
    creature that used it; the record's own generic phrase stays only as the fallback for a question asked
    outside any action."""
    engine = _party([BLINK], theirs=[MELEE], attacker_bonus=100,
                    places={ME: {"x": 3, "y": 6}, AN: {"x": 4, "y": 6}})
    _tough(engine, AN)
    asked = _answers(engine, {"reaction_teleport": lambda options: options[:1]})
    _turn(engine, AN)
    _use(engine, MELEE_NAME, actor=AN, target=ME)
    question = [r for r in asked if "reaction_teleport" in str(r["reaction_source_id"])]
    assert question, "the hop's square was never asked"
    prompt = (question[0].get("choice_trigger") or {}).get("prompt") or ""
    assert "Blink Guard" in prompt, prompt
    assert MELEE_NAME in prompt, f"the question does not name the action it answered: {prompt}"
    assert engine.state.actors[AN].display_name in prompt, f"the question does not name the attacker: {prompt}"
    assert "the attack, saving throw or area effect it was answering" not in prompt, \
        "the record's generic phrase is still what a player reads"
    assert (engine.state.actors[ME].position.x, engine.state.actors[ME].position.y) != (3, 6), "the hop did not happen"


def test_the_trigger_reader_is_inert_outside_a_reaction():
    """combat/ext/trigger_source only answers for another creature's action *in flight*, so a question asked on
    the user's own turn keeps the row's own words (checklist item 3).

    AUTO23r2f1: the claimed inertness here was the other-target context, and that is the one asserted.  An
    ability's own turn asks with the creature it acted on as ``ctx.target`` (``rider_step`` asks with the
    struck foe), so the reader is pointed at that creature and used to reach back through the whole event
    history for its last attack.  With an earlier attack in the history it named an action from a past turn
    as the current trigger, on characters with no Space ability at all."""
    from combat.ext import trigger_source
    from combat.typed_executor import Context

    engine = _engine(_bundle([BLINK], SPACE))
    _turn(engine, ME)
    action = engine.action_catalog[next(a for a in engine.state.actors[ME].action_ids if a in engine.action_catalog)]
    typed = {"source": "x", "effects": [], "numbers": {}, "duration": {"kind": "instant"}}
    on_own_turn = Context(engine, engine.state.actors[ME], action, None, typed, [engine.state.actors[AN]],
                          engine.state.actors[AN], {})
    assert trigger_source.creature(on_own_turn) is engine.state.actors[AN]
    self_only = Context(engine, engine.state.actors[ME], action, None, typed, [engine.state.actors[ME]],
                        engine.state.actors[ME], {})
    assert trigger_source.creature(self_only) is None, "a creature is not its own trigger"
    assert trigger_source.action_name(self_only, "the printed words") == "the printed words"


def test_the_trigger_reader_never_names_an_earlier_attack_as_the_current_trigger():
    """AUTO23r2f1: the fallback that names an attack must be scoped to the resolution being answered.

    Two real engines and the two moments that must differ: an ATTACK_ROLLED by the other creature that belongs
    to a *finished* transaction (a past turn) may not be named, while the same attack rolled inside the
    resolution being answered right now must be, or the fallback would be dead and a reaction would answer
    with its printed phrase instead of the action that set it off."""
    from combat.ext import trigger_source
    from combat.typed_executor import Context

    def own_turn_question(engine):
        """The shared reader as the user's own action asks it: the creature acted on is ``ctx.target``."""
        action = engine.action_catalog[next(a for a in engine.state.actors[ME].action_ids if a in engine.action_catalog)]
        typed = {"source": "x", "effects": [], "numbers": {}, "duration": {"kind": "instant"}}
        ctx = Context(engine, engine.state.actors[ME], action, None, typed, [engine.state.actors[AN]],
                      engine.state.actors[AN], {})
        return trigger_source.action_name(ctx, "the printed words")

    engine = _party([BLINK], theirs=[MELEE])
    # the compiled catalog key for that technique, which the reader looks the action up by
    melee_key = next(k for k, a in engine.action_catalog.items() if getattr(a, "display_name", "") == MELEE_NAME)
    # an attack by the other creature, rolled in a resolution that has since finished
    engine._append_event("ATTACK_ROLLED", melee_key, actor_id=AN, target_ids=(ME,))
    assert engine._transaction_id is None, "the table is still resolving something"
    assert own_turn_question(engine) == "the printed words", \
        "a past turn's attack was offered as the action that set this question off"

    # the same creature's attack, rolled inside the resolution being answered right now
    engine._active_action_source_id = None  # nothing accepted for the other creature this transaction
    with engine._transaction(melee_key, "int:current", AN):
        engine._append_event("ATTACK_ROLLED", melee_key, actor_id=AN, target_ids=(ME,))
        assert own_turn_question(engine) == MELEE_NAME, \
            "the attack being answered right now was not named"

    assert own_turn_question(engine) == "the printed words", "the attack outlived the resolution that rolled it"


def test_own_turn_movement_keeps_its_own_words_after_the_target_already_attacked():
    """AUTO23r2f1: the review's own case, at the level it showed -- the prompt the table is asked.

    A foe attacked last turn, and on the user's own turn the user's own action grants a movement step
    (Gravity's Weighted Strike -> Lightening Blow, ``combat/ext/gravity.py``).  ``rider_step`` asks with the
    struck foe as ``ctx.target``, so the shared reader was pointed at that foe and named the foe's old
    attack as what set the step off, telling a character with no Space ability why they can move.  The
    question must keep the step's own words instead."""
    from combat.typed_executor import Context, run_effects

    engine = _party([FOLD], theirs=[MELEE], attacker_bonus=100)
    _tough(engine, ME)
    _tough(engine, AN)
    asked = _answers(engine, {"rider_step": None})  # declined; only the wording of the question is under test

    _turn(engine, AN)
    _use(engine, MELEE_NAME, actor=AN, target=ME)
    assert any(e.event_type == "ATTACK_ROLLED" and e.actor_id == AN for e in engine.events), "the foe never attacked"

    _turn(engine, ME)
    actor, foe = engine.state.actors[ME], engine.state.actors[AN]
    candidate = next(c for c in engine.legal_candidates() if c.actor_id == ME and c.kind == CandidateKind.ACTION)
    intent = ActionIntent(intent_id="own-turn-step", decision_id=candidate.decision_id,
                          candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                          actor_id=ME, target_ids=candidate.target_ids, destination=candidate.destination)
    ctx = Context(engine, actor, engine.action_catalog[candidate.source_definition_id], intent,
                  {"source": candidate.source_definition_id, "effects": [], "numbers": {},
                   "duration": {"kind": "instant"}}, [foe], foe, {})
    with engine._transaction(candidate.source_definition_id, intent.intent_id, ME):
        engine._active_action_source_id = candidate.source_definition_id
        run_effects(ctx, [{"type": "rider_step", "distance_ft": 10, "label": "Lightening Blow"}])

    questions = [r for r in asked if "rider_step" in str(r.get("reaction_source_id") or "")]
    assert questions, "the movement step was never asked"
    prompt = (questions[0].get("choice_trigger") or {}).get("prompt") or ""
    assert "Lightening Blow" in prompt, prompt
    assert MELEE_NAME not in prompt, f"the step is attributed to the foe's earlier attack: {prompt}"
    assert "after" in prompt and "against" in prompt, prompt


def _fails_every_save(engine, actor_id):
    """A creature whose saves cannot be made, so a printed failure branch is reached deterministically."""
    actor = engine.state.actors[actor_id]
    actor.saving_throws = {key: -50 for key in (actor.saving_throws or {"STR": 0, "DEX": 0})}
    return actor


def _grapples(engine, who):
    return [c for c in engine.state.actors[who].conditions.values()
            if c.condition_id == "condition:typed.grappled"]


def _restrained(engine, who):
    return [c for c in engine.state.actors[who].conditions.values()
            if c.condition_id == "condition:typed.restrained"]


def _grapple_the_phased(engine):
    """A real ordinary Grapple (an Action at arm's length, a Strength-or-Dexterity save) on the phased creature."""
    _fails_every_save(engine, ME)
    _tough(engine, AN)
    _turn(engine, ME)
    _use(engine, "Phase Step")
    _turn(engine, AN)
    assert "Grapple" in [c.display_name for c in engine.legal_candidates() if c.actor_id == AN], \
        "the ordinary Grapple is not on this fighter's menu"
    _use(engine, "Grapple", actor=AN, target=ME)
    return engine


def test_phase_step_refuses_an_ordinary_grapple_and_says_why():
    """"you cannot be Grappled or Restrained by ordinary physical means": AUTO23r1f1.  The AUTO23f1 version
    read "ordinary physical means" as "a confirmed hit", so the ordinary Grapple walked straight through the
    immunity -- a Grapple is a Strength-or-Dexterity *save* whose condition sits in the failure branch and
    never has a confirmed hit -- while a magical grapple that landed would have been refused.  The source is
    now identified, so the printed refusal happens at the table and the table is told why."""
    from combat.ext import space_phase

    engine = _grapple_the_phased(_party([PHASE], places={ME: {"x": 3, "y": 6}, AN: {"x": 4, "y": 6}}))
    assert any(c.condition_id == space_phase.PHASE for c in engine.state.actors[ME].conditions.values())
    assert not _grapples(engine, ME), "an ordinary grapple still took hold of a phased creature"
    said = " ".join((e.payload or {}).get("rider", "") for e in engine.events if e.event_type == "GM_RIDER")
    assert "partly outside ordinary space" in said and "Grapple" in said, said[-200:]


def test_an_ordinary_grapple_still_holds_a_creature_that_did_not_phase():
    """The same refusal is inert for everybody else: without Phase Step the ordinary Grapple takes hold."""
    engine = _party([], places={ME: {"x": 3, "y": 6}, AN: {"x": 4, "y": 6}})
    _fails_every_save(engine, ME)
    _tough(engine, AN)
    _turn(engine, AN)
    _use(engine, "Grapple", actor=AN, target=ME)
    assert _grapples(engine, ME), "the ordinary Grapple no longer takes hold of anything"


def test_phase_step_does_not_refuse_a_magical_grapple_or_a_magical_restraint():
    """"by ordinary physical means" is about what is doing the holding.  A confirmed hit says nothing about
    magic, so the printed line keeps a spell, a conjured hand and any other magical grip working:
    Gravity's Black-Star Grip holds a phased creature ("Grappled by gravitational pressure", a Strength
    save) and Thread's Meridian Lock restrains one, both through their own printed saves."""
    grip = _party([PHASE], theirs=[BLACK_STAR_GRIP], places={ME: {"x": 3, "y": 6}, AN: {"x": 4, "y": 6}})
    _fails_every_save(grip, ME)
    _tough(grip, AN)
    _turn(grip, ME)
    _use(grip, "Phase Step")
    _turn(grip, AN)
    _use(grip, "Black-Star Grip", actor=AN, target=ME)
    assert _grapples(grip, ME), "a magical grapple was refused as though it were ordinary physical means"

    lock = _party([PHASE], theirs=[MERIDIAN_LOCK], places={ME: {"x": 3, "y": 6}, AN: {"x": 4, "y": 6}})
    _fails_every_save(lock, ME)
    _tough(lock, AN)
    _turn(lock, ME)
    _use(lock, "Phase Step")
    _turn(lock, AN)
    _use(lock, "Meridian Lock", actor=AN, target=ME)
    assert _restrained(lock, ME), "a magical restraint was refused as though it were ordinary physical means"


def test_phase_step_refusal_is_only_its_own_user_and_only_those_two_conditions():
    """The shared classifier answers for a real Grapple row whatever the condition, and it is asked of the
    phased creature alone: a Prone it would have taken anyway is untouched, and another creature's own hold is."""
    from combat.ext import physical_holds, space_phase

    engine = _engine(_bundle([PHASE], SPACE))
    _use(engine, "Phase Step")
    me, reactor = engine.state.actors[ME], engine.state.actors[AN]
    assert any(c.condition_id == space_phase.PHASE and c.expires_on == "END_OF_CURRENT_TURN"
               for c in me.conditions.values())
    assert space_phase.phased_ignores_opportunity_attacks(engine, reactor, me) is False
    assert space_phase.phased_ignores_opportunity_attacks(engine, me, reactor) is None  # only the phased mover
    # The compiler's own Grapple option, as it stands in a real fighter's typed row.
    grapple_typed = {"unarmed_option": "grapple", "attack_action": True, "range_ft": 5,
                     "effects": [{"type": "save", "ability": "STR_OR_DEX",
                                  "on_fail": [{"type": "condition", "condition": "grappled", "applies_to": "target"}]}]}
    from combat.typed_executor import Context

    action = engine.action_catalog[next(iter(engine.action_catalog))]

    def context(typed):
        return Context(engine, reactor, action, None, typed, [me], me, {})

    for row in ({"condition": "grappled"}, {"condition": "prone"}):
        answer = space_phase.phased_cannot_be_held(context(grapple_typed), me, row)
        assert answer is (False if row["condition"] == "grappled" else None), row  # only Grappled
    # A row that says in its printed authority that it is an ordinary physical hold (a net, a rope).
    assert space_phase.phased_cannot_be_held(
        context(grapple_typed), me, {"condition": "restrained", "hold_kind": "ordinary_physical"}) is False
    assert space_phase.phased_cannot_be_held(context(grapple_typed), reactor, {"condition": "grappled"}) is None
    assert space_phase.phased_cannot_be_held(context({"unarmed_option": "grapple"}), me, None) is None
    # The shared reader itself, on the rows the table really has: the compiler's Grapple option holds in
    # melee, a condition name alone proves nothing, and the printed ordinary-physical declaration does.
    assert physical_holds.ordinary(grapple_typed, {"condition": "grappled"}) is True
    assert physical_holds.ordinary(grapple_typed, {"condition": "prone"}) is False
    assert physical_holds.ordinary({}, {"condition": "grappled"}) is False, "a condition name alone proves nothing"
    assert physical_holds.ordinary({}, {"condition": "grappled", "hold_kind": "ordinary_physical"}) is True


def test_phase_step_condition_text_says_only_what_the_table_does():
    """The condition pill is the first thing a player reads.  The first version promised that creature
    squares became Difficult Terrain, which the fight map cannot do (an AUTO23 lock-round item); the pill
    now names only what actually happens, and the record's own rider says the rest is worked out by hand."""
    from combat.ext import space_phase

    assert "Difficult Terrain" not in space_phase.LABEL
    for said in ("Opportunity Attack", "Grappled", "Restrained", "Resistance"):
        assert said in space_phase.LABEL, said
    rider = json.loads(TYPED_AUTHORITY.read_bytes())["mechanics"][PHASE]["riders"]
    assert any("Difficult Terrain" in line for line in rider), "the printed pass-through line is no longer said anywhere"


def test_phase_step_ends_with_the_users_own_turn():
    """\"Until the end of your turn\": the state must not survive into the next one (checklist item 8)."""
    engine = _engine(_bundle([PHASE], SPACE))
    _use(engine, "Phase Step")
    assert any(c.condition_id == "condition:typed.space_phase" for c in engine.state.actors[ME].conditions.values())
    engine.end_turn()
    engine._system_start_turn()
    assert not any(c.condition_id == "condition:typed.space_phase" for c in engine.state.actors[ME].conditions.values())


# ----------------------------------------------------------------------------------------- the typed saves
def test_spatial_severance_blocks_the_targets_own_teleport():
    """"cannot teleport until the end of its next turn" (failed) and "until the start of its next turn"
    (successful) were both reminders; the block also answers the target's own Fold Step."""
    engine = _duel([SEVERANCE], [FOLD])
    _tough(engine, AN)
    _use(engine, "Spatial Severance", target=AN)
    foe = engine.state.actors[AN]
    held = [c for c in foe.conditions.values() if c.condition_id == CONDITION_PREFIX + "cannot_teleport"]
    assert held, "the printed teleport block never landed"
    assert held[0].expires_on not in (None, "UNTIL_REMOVED"), "the printed turn limit was lost"
    start = foe.position
    _turn(engine, AN)
    folded = next(c for c in engine.legal_candidates()
                  if c.display_name.startswith("Fold Step") and c.destination is not None and c.destination != start)
    engine.execute_intent(ActionIntent(intent_id="fold", decision_id=folded.decision_id,
                                       candidate_id=folded.candidate_id, state_version=folded.state_version,
                                       actor_id=AN, target_ids=folded.target_ids, destination=folded.destination))
    assert foe.position == start, "a sealed creature still teleported"


def test_void_between_worlds_types_its_teleport_block_not_a_reaction_denial():
    """\"cannot teleport for 1 minute\" was typed as a Reaction denial (the target could still blink but lost
    every Reaction); the record now says what the text says."""
    record = json.loads(TYPED_AUTHORITY.read_bytes())["mechanics"][VOID]
    save = record["effects"][0]
    for branch in ("on_fail", "on_success"):
        rows = save[branch][0]["on_return"] if branch == "on_fail" else save[branch]
        assert any(row["type"] == "condition" and row["condition"] == "cannot_teleport" for row in rows), branch
        assert not any(row["type"] == "reaction_denied" for row in rows), branch
    absence = save["on_fail"][0]
    assert absence["type"] == "spatial_absence"
    minute = next(row for row in absence["on_return"] if row["type"] == "condition")
    assert minute["duration"] == "minutes" and minute["amount"] == 1


def test_spatial_displacement_failed_save_teleports_without_also_pushing_five_feet():
    """The 5-foot move was typed on the failed branch as well, so a creature that failed was teleported and
    then pushed five feet more."""
    engine = _engine(_bundle([DISPLACE], SPACE))
    _tough(engine, AN)
    _use(engine, "Spatial Displacement", target=AN)
    pushed = [e for e in engine.events if e.event_type == "MOVEMENT_COMMITTED" and e.actor_id == AN
              and not (e.payload or {}).get("teleport")]
    assert not pushed, "the target was pushed as well as teleported"


def test_spatial_domain_failed_save_sets_speed_to_zero():
    """"Failed Save: Its Speed becomes 0 until the end of the current turn" was not typed at all."""
    engine = _engine(_bundle([DOMAIN], SPACE))
    _tough(engine, AN)
    _use(engine, "Spatial Domain")
    # combat/typed_executor._speed_becomes records the gap between the printed goal (0) and the Speed the
    # creature would otherwise have, so the foe really is stopped.
    assert engine._effective_speed(engine.state.actors[AN]) == 0, \
        sorted((m.target_field, m.value) for m in engine.state.actors[AN].modifiers.values())


# ------------------------------------------------------------------------- Space Between Blades' menu
FIRST = "Move 5 more feet, and it cannot make an Opportunity Attack against you for it"
SECOND = "It cannot make an Opportunity Attack against you until the start of your next turn"
THIRD = "Your next melee attack on it deals extra Force damage equal to your Proficiency Bonus"


def _blades_menu(bundle):
    row = next(r for r in bundle["typed_reactions"] if r["feature_id"] == BLADES)
    menu = next(effect for effect in row["effects"] if effect["type"] == "choose_effects")
    return row, menu


def test_space_between_blades_asks_its_three_printed_choices_at_the_table():
    """"Then choose one": AUTO23 compiled this as three options the table picked *before* the fight, so two
    of the three printed choices could never be taken at resolution.  It is now one menu the creature is
    asked at the moment it answers the trigger, carrying the three printed lines and nothing else."""
    bundle = _bundle([BLADES], SPACE)
    row, menu = _blades_menu(bundle)
    assert "option" not in row and "option_labels" not in row, "an option is still chosen before the fight"
    assert menu["count"] == 1
    labels = [option["label"] for option in menu["options"]]
    assert labels == [FIRST, SECOND, THIRD], labels
    kinds = [effect["type"] for option in menu["options"] for effect in option["effects"]]
    assert "attack" not in kinds, "the printed words \"Opportunity Attacks\" were read as an attack again"
    assert "reaction_denied" not in kinds, "the attacker would lose every Reaction it has"
    # Nothing outside the menu may type the same printed line twice, so no choice runs twice.
    assert [effect["type"] for effect in row["effects"]] == ["teleport", "choose_effects"], row["effects"]


def _blades_engine(menu, *, seed="AUTO23", **picks):
    """A real duel where a melee attack from ``ME`` misses ``AN``'s Space Between Blades, and the menu is answered.

    ``ME`` also brings a companion on its own side, so a test can strike somebody other than the creature that
    missed the reactor.
    """
    engine = _party([MELEE], theirs=[MELEE, BLADES], side=1, foes=1, attacker_bonus=-100, seed=seed,
                    places={ME: {"x": 3, "y": 6}, AN: {"x": 4, "y": 6},
                            "actor:factory.auto23-side0": {"x": 6, "y": 6}})
    _tough(engine, ME)
    reactor = engine.state.actors[AN]
    engine.typed_control_modes = {AN: "MANUAL"}  # the printed square is the reactor's to choose
    asked = _answers(engine, {"effect_choices": [menu], "space_between_blades": lambda options: options[:1],
                              "teleport_destination": lambda options: [o for o in options if o == "cell:5,6"],
                              "rider_step": lambda options: [o for o in options if o == "cell:5,5"],
                              **picks})
    _turn(engine, ME)
    _use(engine, MELEE_NAME, actor=ME, target=AN)
    return engine, reactor, asked


def _force_damage(events):
    return [e for e in events if e.event_type == "DAMAGE_COMMITTED" and "force" in json.dumps(e.payload or {}).lower()]


def _strike_back(engine, actor, target):
    """Land ``actor``'s ordinary melee strike on ``target`` (every fighter has an Unarmed Strike)."""
    for aid in engine.state.actors:
        engine.state.actors[aid].maximum_hp = engine.state.actors[aid].current_hp = 4000
        engine.state.actors[aid].armor_class = -50
    engine.state.actors[actor].position = engine.state.actors[target].position.model_copy(
        update={"x": engine.state.actors[target].position.x + 1})
    before = engine.state.actors[target].current_hp
    _turn(engine, actor)
    _use(engine, "Unarmed Strike", actor=actor, target=target)
    return before - engine.state.actors[target].current_hp


# SPACE-BLADES-TESTS-ANCHOR
def _blades_opportunity_attacks(engine, *, since=0):
    """The Opportunity Attacks really made since ``since``: (who struck, its roll, its AC)."""
    return [(e.actor_id, int((e.payload or {}).get("total") or 0))
            for e in engine.events[since:]
            if e.event_type == "ATTACK_ROLLED" and "opportunity_attack" in str(e.source_definition_id)]


def _blades_bonus(engine, who=AN):
    from combat.ext import space_blades

    return [c for c in engine.state.actors[who].conditions.values() if c.condition_id == space_blades.BONUS]


def _blades_own_turn_engine(menu, *, seed="AUTO23-OA", reactor_ac=30):
    """Blades answering a real Opportunity Attack during the reactor's own turn.

    ``AN`` owns Space Between Blades, ``ME`` a melee technique with an attack bonus of -100 (it misses
    everything) and ``SIDE`` a second creature that could also make one.  The reactor's armor class is high
    enough that every blow against it misses, so walking out of ``ME``'s reach is what sets the printed
    trigger off -- on the reactor's own turn, which is the case AUTO23r1's deadline fix is about.
    """
    engine = _party([MELEE], theirs=[MELEE, BLADES], side=1, foes=1, attacker_bonus=-100, seed=seed,
                    places={ME: {"x": 3, "y": 6}, AN: {"x": 4, "y": 6}, SIDE: {"x": 3, "y": 5}})
    for aid in engine.state.actors:
        actor = engine.state.actors[aid]
        actor.maximum_hp = actor.current_hp = 4000
        actor.armor_class = -50
    engine.state.actors[AN].armor_class = reactor_ac
    engine.typed_control_modes = {AN: "MANUAL"}
    asked = _answers(engine, {"effect_choices": [menu], "teleport_destination": lambda options: options[:1],
                              "rider_step": lambda options: [o for o in options if o == "cell:6,5"]})
    _turn(engine, AN)
    _use(engine, "Move to 6,6", actor=AN)
    return engine, asked


def test_space_between_blades_first_choice_moves_five_feet_and_provokes_only_other_opportunity_attacks():
    """"You may move 5 additional feet without provoking Opportunity Attacks from the attacker": AUTO23 typed
    this as a movement grant that moved nothing and was free of *everybody's* opportunity attacks.  It is now
    the shared rider step, which moves at once through native movement and exempts only the creature that just
    attacked.  This is the AUTO23r1f1 behavioural version: a second creature really does get an Opportunity
    Attack out of that step, and the creature that missed the reactor does not."""
    engine, reactor, asked = _blades_engine(FIRST)
    steps = [e for e in engine.events if e.event_type == "MOVEMENT_COMMITTED" and e.actor_id == AN
             and not (e.payload or {}).get("teleport")]
    assert steps, "the printed 5 extra feet never moved anybody"
    assert int((steps[-1].payload or {}).get("granted_cost_ft") or 0) == 5
    question = [r for r in asked if "rider_step" in str(r["reaction_source_id"])]
    assert question, "the square was never asked"
    prompt = (question[0].get("choice_trigger") or {}).get("prompt") or ""
    assert "Space Between Blades" in prompt and MELEE_NAME in prompt, prompt
    assert reactor.display_name in prompt
    assert "Opportunity Attack" in prompt, "the printed limit (only that creature's) is not said"

    # The same step, with a stranger inside the reactor's reach at the step's start and outside it at the end.
    engine = _party([MELEE], theirs=[MELEE, BLADES], side=1, foes=1, attacker_bonus=-100, seed="AUTO23-OA1",
                    places={ME: {"x": 3, "y": 6}, AN: {"x": 4, "y": 6}, SIDE: {"x": 4, "y": 7}})
    _tough(engine, ME)
    reactor = engine.state.actors[AN]
    reactor.armor_class = 30
    engine.typed_control_modes = {AN: "MANUAL"}
    _answers(engine, {"effect_choices": [FIRST],
                      "teleport_destination": lambda options: [o for o in options if o == "cell:5,6"],
                      "rider_step": lambda options: [o for o in options if o == "cell:5,5"]})
    _turn(engine, ME)
    _use(engine, MELEE_NAME, actor=ME, target=AN)
    step = [e for e in engine.events if e.event_type == "MOVEMENT_COMMITTED" and e.actor_id == AN
            and int((e.payload or {}).get("granted_cost_ft") or 0) == 5]
    assert step, "the printed 5 extra feet never moved anybody"
    assert (step[-1].payload or {}).get("destination"), "the step was not committed to a square"
    struck = _blades_opportunity_attacks(engine)
    assert struck == [(SIDE, struck[0][1])] and struck[0][0] == SIDE, \
        f"the creature that missed it still struck ({struck}), or the stranger did not"
    assert all(actor != ME for actor, _ in struck), "the attacker made an Opportunity Attack against its own victim"


def _shoved_engine(menu, *, seed="AUTO23-SHOVE"):
    """Blades' second choice, then a real forced move that takes the reactor out of two creatures' reach.

    ``ME`` is the creature whose missed melee attack set the printed trigger off; ``FOE2`` (a second
    creature on the other team) shoves the reactor one square away with the compiler's own Shove, which
    leaves both of them outside its new square: the one that attacked cannot punish it, the one that shoved
    it still can.  This is the only way the printed window is observable at all -- a creature leaves a
    neighbour's reach once per move -- so the printed "cannot make Opportunity Attacks against you" is
    exercised against real attacks on both sides.
    """
    from combat.gate4_engine import Gate4ControllerEngine

    ids, teams, places = [ME, AN, FOE2], {ME: "team:a", AN: "team:b"}, \
        {ME: {"x": 4, "y": 5}, AN: {"x": 4, "y": 6}}
    bundles = [compile_character(_sheet([MELEE], attack_bonus=-100), actor_id=ME),
               compile_character(_sheet([MELEE, BLADES], attack_bonus=100), actor_id=AN),
               compile_character(_sheet([], attack_bonus=100), actor_id=FOE2)]
    teams[FOE2] = "team:a"  # a second creature that attacked nothing, on the reactor's other side
    places[FOE2] = {"x": 3, "y": 6}  # beside the reactor, on the far side from ME
    engine = Gate4ControllerEngine(ROOT, match_seed=seed, typed_bundles=tuple(bundles),
                                   roster_setup={"primary_actor_ids": ids, "team_by_actor": teams,
                                                 "starting_positions": places})
    for aid in engine.state.actors:
        actor = engine.state.actors[aid]
        actor.maximum_hp = actor.current_hp = 4000
        actor.armor_class = -50
    engine.typed_control_modes = {AN: "MANUAL"}
    _answers(engine, {"effect_choices": [menu],
                      "teleport_destination": lambda options: options[:1],
                      "rider_step": lambda options: options[:1]})
    _turn(engine, ME)
    _use(engine, MELEE_NAME, actor=ME, target=AN)
    return engine


def test_space_between_blades_second_choice_stops_only_that_attackers_real_opportunity_attack():
    """"The attacker cannot make Opportunity Attacks against you until the start of your next turn": AUTO23
    typed this as ``reaction_denied``, which took away every Reaction the attacker had.  It is now the engine's
    own no-opportunity-attack rule, bound to the reactor.  AUTO23r1f1 asks the engine's own Opportunity Attack
    decision (``typed_reactions.wants_opportunity_attack``, the one gate2_engine consults before every one)
    in the live fight state instead of reading the condition back, and closes the printed window with real
    attacks: the creature that attacked cannot punish the reactor while the window is open, another creature
    still can, and at the start of the reactor's own next turn the creature that attacked can again.

    A *denied* attack cannot be made inside the window through movement: a creature leaves a neighbour's reach
    once per move, so the only move inside the window is the one that set the trigger off, and a shove does
    not provoke Opportunity Attacks at all (combat/typed_executor._push).  That is a limit of the printed
    window, not of this test; what the test can show is that the engine's own gate answers for the real
    condition, and that the real gate reopens at the printed moment."""
    from combat import typed_reactions
    from combat.ext import space_blades

    engine = _shoved_engine(SECOND)
    reactor = engine.state.actors[AN]
    attacker, other = engine.state.actors[ME], engine.state.actors[FOE2]
    held = [c for c in attacker.conditions.values() if c.condition_id == space_blades.NO_OPPORTUNITY]
    assert held, "the attacker still gets to make Opportunity Attacks"
    assert (held[0].data or {}).get("against") == AN, "the printed limit is \"against you\", not against everybody"
    assert held[0].expires_on == "START_OF_SOURCE_NEXT_TURN", \
        "the printed turn limit (the start of the reactor's own next turn) was lost"
    assert not [c for c in attacker.conditions.values() if c.condition_id == CONDITION_PREFIX + "reaction_denied"], \
        "the attacker lost its whole Reaction, not only its Opportunity Attacks"
    assert not [c for c in reactor.conditions.values() if c.condition_id == space_blades.NO_OPPORTUNITY], \
        "the reactor lost its own opportunity attacks"

    # The printed hop moved the reactor, so both neighbours are placed around the square it is really on.
    spot = reactor.position
    attacker.position = spot.model_copy(update={"y": spot.y + 1})
    other.position = spot.model_copy(update={"x": spot.x - 1})
    assert typed_reactions.wants_opportunity_attack(engine, attacker, reactor) is False, \
        "the engine's own Opportunity Attack gate still lets the attacker strike the reactor"
    assert typed_reactions.wants_opportunity_attack(engine, other, reactor) is True, \
        "the printed limit is \"against you\", not against everybody"
    # A shove really does move the reactor out of both of their reaches, and provokes neither: the printed
    # line is about Opportunity Attacks, not about being pushed.
    since = len(engine.events)
    _fails_every_save(engine, AN)
    _turn(engine, FOE2)
    _use(engine, "Shove: Push 5 ft", actor=FOE2, target=AN)
    assert [e for e in engine.events[since:] if e.event_type == "MOVEMENT_COMMITTED" and e.actor_id == AN], \
        "the shove never moved the reactor"
    assert not _blades_opportunity_attacks(engine, since=since), "a shove provoked an Opportunity Attack"

    # The printed window ends at the start of the reactor's own next turn, and the attacker can strike again.
    spot = reactor.position
    attacker.position = spot.model_copy(update={"y": spot.y - 1})
    for _ in range(4):  # real turn boundaries up to and past the reactor's own turn start
        engine.end_turn()
        if not held[0].instance_id in reactor.conditions and engine.state.current_actor_id == AN:
            break
    assert not [c for c in attacker.conditions.values() if c.condition_id == space_blades.NO_OPPORTUNITY], \
        "the printed window never ended at the start of the reactor's own next turn"
    assert typed_reactions.wants_opportunity_attack(engine, attacker, reactor) is True, \
        "the attacker still cannot strike the reactor once the printed window has passed"
    since = len(engine.events)
    _use(engine, "Move to 6,4", actor=AN)  # the reactor walks out of the attacker's reach
    assert ME in [actor for actor, _ in _blades_opportunity_attacks(engine, since=since)], \
        "the attacker's own Opportunity Attack never came back"


def test_space_between_blades_third_choice_binds_a_force_bonus_to_that_creature_and_spends_it_once():
    """"The next melee attack you make against the attacker before the end of your next turn deals additional
    Force damage equal to your Proficiency Bonus": AUTO23 typed a deferred ``extra_damage`` row, which registered
    nothing at all.  It is now one condition on the reactor naming the creature it is bound to, spent by the
    first melee attack it makes against that creature."""
    from combat.ext import space_blades

    engine, reactor, _asked = _blades_engine(THIRD, seed="AUTO23-B")
    armed = _blades_bonus(engine)
    assert armed, "the printed bonus was never armed"
    assert (armed[0].data or {}).get("against") == ME, "the bonus is bound to the creature that missed it"
    assert armed[0].expires_on.startswith("END_OF_SOURCE_TURN_AT:"), \
        "the printed deadline is the end of the reactor's own next turn, by its turn counter"

    # The printed line names the attacker: a melee attack on any other creature spends nothing.
    stranger = SIDE
    assert _strike_back(engine, AN, stranger) > 0, "the reactor's own blow did not land"
    assert not _force_damage(engine.events), "the bonus landed on a creature it was not bound to"
    assert _blades_bonus(engine), "the bonus was spent on the wrong creature"

    assert _strike_back(engine, AN, ME) > 0
    assert _force_damage(engine.events), "no Force damage reached the bound creature"
    assert not _blades_bonus(engine), "the printed \"next melee attack\" was not used up"
    spent = len(engine.events)
    assert _strike_back(engine, AN, ME) > 0
    assert not _force_damage(engine.events[spent:]), "the bonus was spent more than once"


def test_space_between_blades_bonus_is_spent_by_the_next_melee_attack_even_when_it_misses():
    """"The next melee attack you make against the attacker" is an *attack*, not a damage packet.  AUTO23r1f1:
    the bonus was spent from ``damage_dealt``, which only fires for a positive damage packet, so a miss left it
    armed for a later attack and a fighter could bank it across the whole round."""
    from combat.ext import space_blades

    engine, reactor, _asked = _blades_engine(THIRD, seed="AUTO23-MISS")
    for aid in engine.state.actors:
        _tough(engine, aid)
    engine.state.actors[ME].armor_class = 30  # the bound creature is out of the reactor's own reach
    hp = reactor.current_hp
    struck = len(engine.events)
    reactor.position = engine.state.actors[ME].position.model_copy(
        update={"x": engine.state.actors[ME].position.x + 1})
    _turn(engine, AN)
    _use(engine, "Unarmed Strike", actor=AN, target=ME)
    rolls = [e for e in engine.events[struck:] if e.event_type == "ATTACK_ROLLED" and e.actor_id == AN]
    assert rolls, "the reactor made no attack at all"
    assert all(int((e.payload or {}).get("modified_total") or 0) < int((e.payload or {}).get("target_ac") or 0)
               for e in rolls), [dict(e.payload or {}) for e in rolls]
    assert reactor.current_hp == hp, "the printed attack did not miss"
    assert not _force_damage(engine.events[struck:]), "a miss dealt the printed Force damage"
    assert not _blades_bonus(engine), "a missed melee attack left the printed bonus armed for a later one"
    assert space_blades.BONUS_EVIDENCE, "the printed line is kept with the delivered packet"


def test_space_between_blades_bonus_deals_force_damage_when_the_ordinary_damage_is_prevented():
    """The printed line says the attack *deals* additional Force damage; it does not say "the next attack that
    damages it".  AUTO23r1f1: with the bonus spent from ``damage_dealt``, a creature immune to the ordinary
    damage type prevented the additional Force packet from even being attempted."""
    from combat.typed_executor import Context, run_effects

    engine, reactor, _asked = _blades_engine(THIRD, seed="AUTO23-ZERO")
    attacker = engine.state.actors[ME]
    action = engine.action_catalog[next(a for a in attacker.action_ids if a in engine.action_catalog)]
    typed = {"effects": [], "riders": [], "weapon": None, "duration": {"kind": "instant"},
             "numbers": {"pb": 4, "cl": 10, "save_dc": 16, "attack_bonus": 8}}
    run_effects(Context(engine, attacker, action, None, typed, [reactor], reactor, {}),
                [{"type": "immunity", "applies_to": "self", "damage_types": ["BLUDGEONING"],
                  "expires_on": "UNTIL_REMOVED"}])  # the printed damage reduction the review names
    dealt = _strike_back(engine, AN, ME)
    packets = {(e.payload or {}).get("damage_type"): int((e.payload or {}).get("hp_damage") or 0)
               for e in engine.events if e.event_type == "DAMAGE_COMMITTED"}
    assert packets.get("BLUDGEONING") == 0, f"the ordinary packet was not fully prevented: {packets}"
    assert packets.get("FORCE", 0) > 0, f"the printed Force damage never arrived: {packets}"
    assert dealt == packets["FORCE"], f"something else dealt damage: {packets}"
    assert not _blades_bonus(engine), "the printed bonus was not used up by the attack it was for"


def test_space_between_blades_bonus_ends_at_the_end_of_the_reactors_own_next_turn_on_either_turn_owner():
    """"before the end of your next turn".  AUTO23r1f1: the bonus carried the engine's ``END_OF_HOLDER_NEXT_TURN``,
    which ends at whichever turn the holder is next on -- including the turn it was armed on.  An Opportunity
    Attack that missed the moving reactor arms it during the reactor's own turn, so it vanished at that turn's
    end and the printed Force damage could never be collected.  Both turn owners are driven here with real
    turn boundaries, not a comparison of expiry strings."""

    def through_the_reactors_next_turn(engine, armed_turn):
        from combat.ext import space_blades

        assert _blades_bonus(engine), "the printed bonus was never armed"
        wanted = int(str(_blades_bonus(engine)[0].expires_on).rsplit(":", 1)[1])
        assert wanted == armed_turn + 1, f"{_blades_bonus(engine)[0].expires_on} does not name the next turn"
        started = False
        for _ in range(8):  # end turns until the reactor's own next turn has begun and ended
            engine.end_turn()
            if engine.state.current_actor_id == AN:
                if started:
                    break
                started = True
        assert started, "the reactor never got another turn"
        return space_blades

    # Armed on the attacker's own turn (the printed trigger is normally answered there).
    engine, reactor, _asked = _blades_engine(THIRD, seed="AUTO23-DEADLINE-1")
    armed_turn = reactor.turns_started
    space_blades = through_the_reactors_next_turn(engine, armed_turn)
    assert not _blades_bonus(engine), "the bonus outlived the end of the reactor's own next turn"

    # Armed on the reactor's own turn, by a real Opportunity Attack that missed it while it moved.
    engine, _asked = _blades_own_turn_engine(THIRD, seed="AUTO23-DEADLINE-2")
    reactor = engine.state.actors[AN]
    assert _blades_opportunity_attacks(engine), "no Opportunity Attack was made to set the trigger off"
    assert _blades_bonus(engine), "the missed Opportunity Attack did not arm the printed bonus"
    assert reactor.turns_started == 1, f"the reactor was not on its own turn ({reactor.turns_started})"
    assert not [c for c in engine.state.actors[AN].conditions.values()
                if c.condition_id == space_blades.NO_OPPORTUNITY]
    through_the_reactors_next_turn(engine, reactor.turns_started)
    assert not _blades_bonus(engine), "the bonus ended with the turn it was armed on"


def test_space_between_blades_bonus_survives_a_table_commit_and_reload(tmp_path):
    """The printed bonus is state a table keeps: it is bound to one creature, ends with the reactor's own next
    turn, and a commit + journal replay + reload brings it back with every stored value unchanged.

    The row is put on through the real plug-in effect, aimed by the table at the creature it is bound to.
    """
    from combat.ext import space_blades

    armed = {"type": "space_blades_bonus", "applies_to": "target",
             "evidence": "The next melee attack you make against the attacker before the end of your next turn "
                         "deals additional Force damage equal to your Proficiency Bonus."}
    combat, table, mid = match(tmp_path, [BLADES], mode="MANUAL", cl=20,
                               setup_actions=[{"name": "Blade Bond Setup", "target": "HOSTILE_ENTITY",
                                               "effects": [armed]}])
    engine = reload(combat, tmp_path, mid)
    assert not _blades_bonus(engine, OWNER)
    assert act(table, mid, "Blade Bond Setup", FOE)["status"] == "COMMITTED"
    engine = reload(combat, tmp_path, mid)
    held = _blades_bonus(engine, OWNER)
    assert len(held) == 1, "the bound bonus did not survive the commit and reload"
    assert (held[0].data or {}).get("against") == FOE, "the bonus lost the creature it was bound to"
    assert held[0].expires_on == f"END_OF_SOURCE_TURN_AT:{engine.state.actors[OWNER].turns_started + 1}", \
        "the printed deadline (the end of its own next turn) was lost or renamed"
    assert all(isinstance(value, (int, str)) for value in (held[0].data or {}).values()), \
        "only integers and strings may be stored in fight state"
    # The engine's own counter sweep still removes it, and no other name would.
    for _ in range(6):
        engine.end_turn()
        if not _blades_bonus(engine, OWNER):
            break
    assert not _blades_bonus(engine, OWNER), "the saved bonus never ended at the end of its owner's next turn"


# ------------------------------------------------------------------- the menu at a real table (Manual and Ask me)
def _blades_table(tmp_path, *, owner_mode="MANUAL", foe_mode="MANUAL", seed="AUTO23-T3"):
    """A saved two-creature table: ``OWNER`` owns Space Between Blades, ``FOE`` is the melee attacker.

    ``tests/test_hunt32_edge.match`` picks its own match seed while it searches for an initiative order, which
    would leave "the attacker's blow misses" to luck; this builder takes the seed the test names (the first
    one that puts the owner first) and gives the owner an armor class the blow cannot beat, so the printed
    trigger really happens at the table.  Everything else is the real thing: compiled bundles, a real arena, a
    real journal, and the real Manual/auto control modes.
    """
    ids = [OWNER, FOE]
    docs = [sheet([BLADES], cl=20), sheet([], cl=20)]
    docs[0]["ability_scores_and_statistics"]["armor_class"]["base_value"] = 30
    bundles = [compile_character(doc, actor_id=a, reaction_plan={"ask": True}) for a, doc in zip(ids, docs)]
    combat = CombatService(ROOT, tmp_path)
    arena = combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"]
    mid = combat._finish_factory_match(
        bundles, ids, {OWNER: "team:factory", FOE: "team:opponents"},
        {OWNER: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 6}}, arena, [OWNER], [FOE],
        control_modes={OWNER: owner_mode, FOE: foe_mode}, match_seed=seed, maximum_rounds=10,
        display_name="AUTO23r1f1 Blades at the table")["match_id"]
    return combat, TabletopService(combat, tmp_path), mid


def test_space_between_blades_menu_is_asked_of_a_player_on_the_attackers_turn(tmp_path):
    """\"Then choose one\" is a player decision wherever the trigger lands: the attacker's own turn included.

    Checklist item 9.  The whole printed chain runs through the table -- the missed blow, the Use question,
    the square to hop to, and the three printed choices -- and the third choice lands as state a reload keeps.
    """
    from combat.ext import space_blades

    combat, table, mid = _blades_table(tmp_path)
    engine = reload(combat, tmp_path, mid)
    assert engine.state.current_actor_id == OWNER, "the owner is not first; the seed needs another one"
    act(table, mid)  # the owner ends its turn; the attacker now acts
    engine = reload(combat, tmp_path, mid)
    assert engine.state.current_actor_id == FOE
    state = table.state(mid)
    group = next(g for g in state["menu"]["actions"] if g["label"] == "Unarmed Strike")
    option = next(o for o in group["options"] if OWNER in o.get("target_ids", []))
    args = (option["candidate_id"], state["menu"]["decision_id"], state["menu"]["state_version"],
            state["last_sequence"])
    answers: list = []
    result = table.act(mid, *args)
    asked = []
    for _ in range(6):
        if result["status"] != "REACTION_REQUIRED":
            break
        prompt = result["reaction"]
        asked.append(prompt)
        options = (prompt.get("choice") or {}).get("options") or []
        answer = {**prompt["context"], "selection": "USE"}
        if [o["label"] for o in options] == [FIRST, SECOND, THIRD]:
            answer["option_ids"] = [options[2]["id"]]  # the printed next-melee-attack bonus
        elif options:
            answer["option_ids"] = [options[0]["id"]]
        answers.append(answer)
        result = table.act(mid, *args, answers)
    assert result["status"] == "COMMITTED", result
    menu = [p for p in asked if [o["label"] for o in (p.get("choice") or {}).get("options") or []] == [FIRST, SECOND, THIRD]]
    assert len(menu) == 1, "the printed \"Then choose one\" was never asked of the player"
    assert "Space Between Blades" in menu[0]["moment"], menu[0]["moment"]
    engine = reload(combat, tmp_path, mid)
    held = [c for c in engine.state.actors[OWNER].conditions.values() if c.condition_id == space_blades.BONUS]
    assert len(held) == 1, "the player's own choice never landed"
    assert (held[0].data or {}).get("against") == FOE
    assert held[0].expires_on == f"END_OF_SOURCE_TURN_AT:{engine.state.actors[OWNER].turns_started + 1}"


def test_space_between_blades_menu_is_asked_of_a_player_during_its_own_turn(tmp_path):
    """The same question when a real Opportunity Attack that misses the moving owner sets the trigger off, so
    the printed deadline is the end of that owner's own *next* turn and not this one (checklist items 8, 9)."""
    from combat.ext import space_blades

    combat, table, mid = _blades_table(tmp_path, foe_mode="LOCAL_AUTO")
    engine = reload(combat, tmp_path, mid)
    assert engine.state.current_actor_id == OWNER
    state = table.state(mid)
    from combat.gate2_runtime_models import Position

    start = engine.state.actors[OWNER].position
    away = next(m for m in state["menu"]["moves"]
                if engine.grid.distance_ft(Position(**m["destination"]), engine.state.actors[FOE].position) > 5)
    args = (away["candidate_id"], state["menu"]["decision_id"], state["menu"]["state_version"],
            state["last_sequence"])
    answers: list = []
    result = table.act(mid, *args)
    asked = []
    for _ in range(6):
        if result["status"] != "REACTION_REQUIRED":
            break
        prompt = result["reaction"]
        asked.append(prompt)
        options = (prompt.get("choice") or {}).get("options") or []
        answer = {**prompt["context"], "selection": "USE"}
        if [o["label"] for o in options] == [FIRST, SECOND, THIRD]:
            answer["option_ids"] = [options[2]["id"]]
        elif options:
            answer["option_ids"] = [options[0]["id"]]
        answers.append(answer)
        result = table.act(mid, *args, answers)
    assert result["status"] == "COMMITTED", result
    menu = [p for p in asked if [o["label"] for o in (p.get("choice") or {}).get("options") or []] == [FIRST, SECOND, THIRD]]
    assert len(menu) == 1, "the printed \"Then choose one\" was never asked while the owner was acting"
    engine = reload(combat, tmp_path, mid)
    assert engine.state.current_actor_id == OWNER, "the question was not asked on the owner's own turn"
    assert engine.state.actors[OWNER].position != start, "the owner never moved"
    opportunity = [e for e in engine.events if e.event_type == "ATTACK_ROLLED"
                   and "opportunity_attack" in str(e.source_definition_id)]
    assert opportunity, "no Opportunity Attack really was made"
    held = [c for c in engine.state.actors[OWNER].conditions.values() if c.condition_id == space_blades.BONUS]
    assert len(held) == 1, "the bonus was never armed on the owner's own turn"
    assert held[0].expires_on == f"END_OF_SOURCE_TURN_AT:{engine.state.actors[OWNER].turns_started + 1}", \
        "the printed deadline must be the end of the owner's own next turn, not the turn it was armed on"
    for _ in range(4):  # the owner ends its turn: the bonus must survive this one
        act(table, mid)
        engine = reload(combat, tmp_path, mid)
        if engine.state.current_actor_id != OWNER:
            break
    assert [c for c in engine.state.actors[OWNER].conditions.values() if c.condition_id == space_blades.BONUS], \
        "the bonus ended with the turn it was armed on"


def test_an_ai_combatant_answers_the_space_between_blades_menu_itself(tmp_path):
    """The printed menu is asked of whoever owns the ability; an AI combatant answers for itself and is never
    asked (checklist item 9).  The attacker here is played by the test, so only the AI's own decisions are on
    show: the whole trigger resolves inside one ``table.act`` with no REACTION_REQUIRED pause anywhere, and the
    printed 1 CP is paid for the Reaction.

    What an AI's answer *is* is not recorded in fight state (the automatic choice leaves no event and no saved
    answer), and with the record's own default the AI takes the first printed choice -- the optional five extra
    feet -- which it may then decline; the report records that as a balance observation, not a fix.
    """
    # Let the attacker go first: the revised AI can otherwise move the owner
    # out of melee reach before this reaction-specific test gets its trigger.
    combat, table, mid = _blades_table(tmp_path, owner_mode="LOCAL_AUTO", foe_mode="MANUAL", seed="SPHB1RELF-AI")
    for _ in range(8):
        if combat._load_session(mid).engine.state.current_actor_id == FOE:
            break
        assert table.auto_step(mid, table.state(mid)["last_sequence"])["status"] == "COMMITTED"
    state = table.state(mid)
    assert state["menu"]["actor_id"] == FOE, "the attacker is not acting; the seed needs another one"
    group = next(g for g in state["menu"]["actions"] if g["label"] == "Unarmed Strike")
    option = next(o for o in group["options"] if OWNER in o.get("target_ids", []))
    result = table.act(mid, option["candidate_id"], state["menu"]["decision_id"], state["menu"]["state_version"],
                       state["last_sequence"])
    assert result["status"] == "COMMITTED", "the AI combatant was asked something a player has to answer"
    engine = reload(combat, tmp_path, mid)
    spent = [e for e in engine.events if e.event_type == "RESOURCE_SPENT"
             and "space_between_blades" in str(e.source_definition_id)]
    assert spent, "the AI never used the printed Reaction"
    assert int((spent[0].payload or {}).get("amount") or 0) == 1, "the printed cost is 1 CP"
    assert [e for e in engine.events if e.event_type == "REACTION_RESOLVED"
            and "space_between_blades" in str(e.source_definition_id)], "the AI's Reaction never resolved"

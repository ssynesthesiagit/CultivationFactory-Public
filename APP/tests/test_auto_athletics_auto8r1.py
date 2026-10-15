"""Table-level regressions for the independent review of the Athletics lane (review AUTO8r1, lane AUTO8r1f1).

The companion file ``tests/test_auto_athletics.py`` holds the engine-level cases. Everything here runs on a real
Factory match whose owner answers through the table's own Ask-me transport -- the pause, the answer and the replay a
live player meets -- and reloads the stored fight from disk, so saved-fight compatibility is checked rather than
asserted. The three clauses the review named as unproven (Court's off-turn step, Dizzying Tumble's movement-time
question and Meridian's nested grapple choice) are driven here, not through a synchronous engine reaction provider.
"""

from __future__ import annotations

import pytest

from combat import motion
from combat.ext import athletics
from combat.gate2_engine import SYSTEM_OPPORTUNITY
from combat.gate2_runtime_content import AN, LING
from tests.auto8f1_table_support import (
    BESIDE_OWNER,
    FOE,
    FLANKED_BY_OWNER,
    OWNER,
    SECOND,
    candidate_id,
    easy_grapple_target,
    fixture,
    move_candidate_id,
    reload_identical,
    unknowable_armor,
    zero_martial_focus,
)
from tests.test_auto_athletics import COORDINATED, COURT, DIZZYING, MERIDIAN

FOCUS = "resource:core.martial_focus"
GRAPPLED = "condition:typed.grappled"
DIZZY = "condition:typed.dizzy"
# The id an older stored build used for Court's printed terrain clause, before Court had an id of its own.
LEGACY_CLAUSES = "condition:typed.ignore_difficult"


def _holds(actor):
    return {instance_id for instance_id, condition in actor.conditions.items()
            if condition.condition_id == GRAPPLED}


def _opportunity_windows_against(engine, owner_id):
    """The Opportunity Attack windows the engine opened *at* ``owner_id`` for it leaving a creature's reach.

    ``gate2_engine._resolve_leave_reach`` names the creature that moved as the event's ``actor_id`` and the
    creature that could attack it as a target (both the typed and the legacy branch). So the fighter whose
    printed step promised to provoke nothing is identified by ``actor_id``: looking for it among ``target_ids``
    instead never matches, and an Opportunity Attack offered against that fighter passes the check for the same
    reason the unspent Reactions and the real displacement did not rule it out (review AUTO8r3, R8).
    """
    return [event for event in engine.events
            if event.event_type == "REACTION_WINDOW_OPENED"
            and event.source_definition_id == SYSTEM_OPPORTUNITY
            and event.actor_id == owner_id]


def _both(*transforms):
    """The fixture takes one bundle transform; a test may need several."""
    return lambda bundles: [transform(bundles) for transform in transforms]


def _record_choice(feature):
    """A chooser that answers the printed Meridian benefit with ``feature`` and records every choice it was given."""
    calls: list[tuple] = []

    def chooser(prompt, choice):
        ids = [str(option["id"]) for option in choice["options"]]
        calls.append((prompt, ids))
        return [feature if feature in ids else ids[0]]

    chooser.calls = calls
    return chooser


# ============================================================ R1: a Focus that was never restored awards nothing
def test_a_later_dash_that_restored_no_focus_is_never_asked_about_at_the_table(tmp_path):
    """R1: the engine-only stamp that recognises Coordinated Movement's Focus named the fighter and the Action, not
    the resolution, so it survived the turn it was written in. Answering the printed choice once and then ending the
    turn *keeping* the Focus that Dash had restored left it matching, and the next Dash -- which restores nothing --
    was asked the question a second time at the table.

    Driven through the table with the fight stored and reloaded between the two Dashes, so an uninterrupted run and
    a reloaded one are compared rather than assumed to agree."""
    game = fixture(tmp_path, [COORDINATED, MERIDIAN], seed="AUTO8R1F1-R1",
                   bundle_transform=zero_martial_focus)
    assert game["reload_owner"]().resources.get(FOCUS, 0) == 0, "the owner starts without Martial Focus"

    first = _record_choice("step")
    game["commit"](candidate_id(game["menu"](), "Dash"), first)
    assert first.calls, "the printed choice was asked on the Dash that restored the Focus"
    owner = game["reload_owner"]()
    assert owner.resources[FOCUS] == 1, "Coordinated Movement restored Martial Focus through that Dash"
    reload_identical(game["combat"], game["match_id"], game["userdata"])

    # End the turn keeping the Focus, then take a later one.
    game["end_own_turn"]()
    game["to_owner"]()
    owner = game["reload_owner"]()
    assert owner.resources[FOCUS] == 1, "the Focus was kept, so the next Dash restores nothing"

    second = _record_choice("step")
    game["commit"](candidate_id(game["menu"](), "Dash"), second)
    assert not second.calls, f"a Dash that restored no Focus was asked the printed choice again: {second.calls}"
    owner = game["reload_owner"]()
    assert owner.resources[FOCUS] == 1, "and no Focus was invented"
    assert owner.turn_flags.get("oa_free_ft") is None, "so no printed movement was granted either"
    reload_identical(game["combat"], game["match_id"], game["userdata"])


# ============================ R2 and the off-turn step: asked, answered, reloaded, and provoked by nobody
def test_courts_off_turn_step_is_answered_at_the_table_and_provokes_neither_enemy(tmp_path):
    """R2: the printed clause is "move 5 feet without provoking Opportunity Attacks" and does not limit that
    protection to the attacker, but only the attacker's id reached the shared granted-movement path. Both enemies
    stand beside the fighter here, so the step leaves *both* their reaches and the second one would otherwise have
    attacked. The step is also asked on the enemy's turn, off the owner's, which is the Ask-me path the review asked
    to see covered: pause, answer, commit, reload."""
    game = fixture(tmp_path, [COURT], seed="AUTO8R1F1-R2", cl=15,
                   bundle_transform=unknowable_armor, places=BESIDE_OWNER)
    game["commit"](candidate_id(game["menu"](), "Court of Ten Thousand Steps"))
    start = game["reload_owner"]().position
    assert start.x == 3 and start.y == 6, "the fighter starts beside both enemies"

    asked: list[tuple] = []

    def answer_the_step(prompt, choice):
        asked.append((prompt, choice))
        ids = [str(option["id"]) for option in choice["options"]]
        standing = f"cell:{start.x},{start.y}"
        cells = [option for option in ids if option.startswith("cell:") and option != standing]
        # One square west: out of reach of the enemy that missed and of the one standing beside it.
        return ["cell:2,6" if "cell:2,6" in cells else cells[0]]

    game["foe_acts"](FOE, "Unarmed Strike", answer_the_step)

    assert asked, "the fighter really was asked, on the enemy's turn"
    prompt, choice = asked[0]
    question = str(prompt)
    assert "without provoking any Opportunity Attack" in question, \
        f"the question must not narrow the printed benefit to one attacker: {question}"
    assert "that attacker" not in question, \
        f"and must not promise less than the printed clause does: {question}"

    owner = game["reload_owner"]()
    assert (owner.position.x, owner.position.y) == (2, 6), f"the fighter really stepped: {owner.position}"
    engine = game["stored_engine"]()
    for enemy_id in (FOE, SECOND):
        enemy = engine.state.actors[enemy_id]
        assert engine.grid.distance_ft(owner.position, enemy.position) > 5, \
            f"{enemy_id} lost reach, so it was a candidate for the step to provoke"
        assert enemy.reaction_available, f"{enemy_id} still had its Reaction: the step provoked nothing"
    assert not [event for event in engine.events if event.event_type == "REACTION_RESOLVED"
                and event.actor_id == SECOND], "the second enemy made no Opportunity Attack"
    reload_identical(game["combat"], game["match_id"], game["userdata"])


# ============= R5: legacy fighters the chosen step cannot provoke must not turn it into a GM rider
def test_two_distant_legacy_enemies_do_not_take_courts_step_away_from_the_fighter(tmp_path):
    """R5: the shared granted-movement path has one single-creature exemption for fighters that predate the
    Factory's typed rules, and hands it to whichever *legacy* enemies the clause named. Naming them is right for
    every one of them, but naming them is not the same as needing them: the locked resolver only has room for one,
    so two legacy enemies anywhere on the board turned Court's printed step into a GM rider and the fighter never
    moved -- even though the prompt had already promised a step that provokes nothing.

    The roster is therefore mixed on purpose: one typed enemy beside the fighter to miss it, and two legacy
    fighters far enough away that no chosen step can leave their reach. The step must really displace the
    fighter, must not be abandoned to a rider, and must still spend Court's once-per-turn use."""
    game = fixture(tmp_path, [COURT], seed="AUTO8R2F1-R5-S1", cl=15, bundle_transform=unknowable_armor,
                   legacy_foes={AN: {"x": 1, "y": 12}, LING: {"x": 2, "y": 12}})
    game["commit"](candidate_id(game["menu"](), "Court of Ten Thousand Steps"))
    start = game["reload_owner"]().position
    assert (start.x, start.y) == (3, 6), f"the fighter starts beside the enemy that will miss it: {start}"

    engine = game["stored_engine"]()
    for legacy_id in (AN, LING):
        at = engine.state.actors[legacy_id].position
        assert engine.grid.distance_ft(start, at) > 20, \
            f"{legacy_id} really is out of reach of any step: {at} is {engine.grid.distance_ft(start, at)} feet off"

    asked: list[list[str]] = []

    def answer_the_step(prompt, choice):
        ids = [str(option["id"]) for option in choice["options"]]
        asked.append(ids)
        standing = f"cell:{start.x},{start.y}"
        cells = [option for option in ids if option.startswith("cell:") and option != standing]
        return ["cell:2,6" if "cell:2,6" in cells else cells[0]]

    game["foe_acts"](FOE, "Unarmed Strike", answer_the_step)

    # An Armor Class of 40 cannot be beaten by a roll, but a natural 20 always is. Say so plainly: a critical
    # would end the step before it was ever offered, and the failure below would then be about the dice.
    engine = game["stored_engine"]()
    attacks = [event for event in engine.events if event.event_type == "ATTACK_ROLLED"
               and event.actor_id == FOE and OWNER in (event.target_ids or ())]
    assert attacks and all(not (event.payload or {}).get("provisional_hit") for event in attacks), \
        f"the enemy's attack really missed: {[event.payload for event in attacks]}"
    assert asked, "the fighter really was asked for the printed step"
    owner = game["reload_owner"]()
    assert (owner.position.x, owner.position.y) == (2, 6), \
        f"the fighter really stepped away instead of waiting on a GM: {owner.position}"

    engine = game["stored_engine"]()
    riders = [event for event in engine.events if event.event_type == "GM_RIDER"]
    assert not riders, f"the step was resolved by the table, not abandoned: {[event.model_dump() for event in riders]}"
    windows = _opportunity_windows_against(engine, owner.entity_id)
    assert not windows, \
        f"and the step provoked no Opportunity Attack from anybody: {[event.model_dump() for event in windows]}"
    for legacy_id in (AN, LING):
        assert engine.state.actors[legacy_id].reaction_available, \
            f"{legacy_id} was never given the chance to react, so the step provokes nothing"

    stamp = owner.turn_flags.get("athletics_used:court_step")
    assert isinstance(stamp, str) and stamp.startswith(f"athletics_turn:{engine.state.round_number}:") \
        and stamp.endswith(f":{OWNER}"), \
        f"the printed once-per-turn use was spent, and spent against the fighter's own turn: {stamp!r}"
    reload_identical(game["combat"], game["match_id"], game["userdata"])


# ==================== R8: the check the R5 case rests on must be able to fail, and must fail on the right event
def test_leaving_a_legacy_enemy_in_reach_is_recorded_against_the_fighter_who_moved(tmp_path):
    """R8: the R5 case proves Court's step opened no Opportunity Attack window. That claim is only worth
    anything if the check can notice one, and the review found it could not: it looked for the fighter among an
    event's *target* ids, while the leave-reach window names the creature that moved as the event's actor.

    So this is the same movement with no grant and no exemption to protect it: the fighter with no Athletics
    talent walks out of a legacy fighter's reach and the window is recorded anyway. A check that passes here is
    the check R5 relies on; a check that finds nothing means R5's assertion would pass for any behaviour at all.

    The two Factory enemies stand well clear so that the legacy fighter is the only creature the step can
    provoke; every creature stands on its own square, which the engine requires."""
    # One layout for all four: the fighter beside the legacy fighter, both Factory enemies out of the way. Two
    # creatures may not share a square, and the fighter has to start inside the legacy fighter's reach for the
    # step to leave it.
    places = {OWNER: {"x": 3, "y": 6}, FOE: {"x": 5, "y": 9}, SECOND: {"x": 5, "y": 11}}
    game = fixture(tmp_path, [], seed="AUTO8R3F1-R8", places=places,
                   legacy_foes={AN: {"x": 4, "y": 6}})
    start = game["reload_owner"]().position
    assert (start.x, start.y) == (3, 6), f"the fighter starts inside the legacy fighter's reach: {start}"
    engine = game["stored_engine"]()
    assert engine.grid.distance_ft(start, engine.state.actors[AN].position) <= 5, \
        "and the legacy fighter really can reach the fighter's square"

    game["commit"](move_candidate_id(game["menu"](), 2, 6))

    owner = game["reload_owner"]()
    assert (owner.position.x, owner.position.y) == (2, 6), \
        f"an ordinary step, with no clause to protect it, really does leave that reach: {owner.position}"
    engine = game["stored_engine"]()
    assert engine.grid.distance_ft(owner.position, engine.state.actors[AN].position) > 5, \
        "and the fighter really is out of that reach afterwards"
    windows = _opportunity_windows_against(engine, OWNER)
    assert windows, "the engine records the window against the fighter who moved, and the check finds it"
    assert AN in [target for event in windows for target in (event.target_ids or ())], \
        f"naming the fighter that was offered the attack: {[event.model_dump() for event in windows]}"
    # The window really is there, and the fighter is really not one of its targets -- which is exactly why R5's
    # old check never failed. Spelled out so the wrong field cannot be reintroduced as a passing assertion.
    assert not [event for event in engine.events if event.event_type == "REACTION_WINDOW_OPENED"
                and OWNER in (event.target_ids or ())], \
        "the fighter is named as the window's actor, never among its targets, so a target_ids check finds nothing"
    reload_identical(game["combat"], game["match_id"], game["userdata"])


# ==================================== R3: a Court cast stored before Court had a condition id of its own
def _store_a_legacy_court(tmp_path, monkeypatch, seed):
    """Cast Court through the table while the module publishes the *old* shared condition id, then put that back.

    The stance, the clock and the terrain clause are written by the real commit path and land in the stored fight on
    disk, so the save below is genuinely an already-cast legacy one rather than a condition hand-placed in memory.
    This review's predecessor claimed to test an old stored cast but cast under the current code, which writes the
    new id; only the id being published is emulated here."""
    monkeypatch.setattr(athletics, "COURT_CLAUSES", LEGACY_CLAUSES)
    game = fixture(tmp_path, [COURT], seed=seed, cl=15)
    game["commit"](candidate_id(game["menu"](), "Court of Ten Thousand Steps"))
    monkeypatch.undo()
    return game


def test_a_court_cast_stored_with_the_old_terrain_clause_ends_with_the_stance(tmp_path, monkeypatch):
    """R3: the early end ("Court of Ten Thousand Steps ends early if you become Incapacitated") removed only the
    replacement condition id. A fight stored before Court had an id of its own still carries the shared
    ``condition:typed.ignore_difficult``, so its terrain benefit survived the Incapacitation and kept working until
    that instance's own expiry."""
    game = _store_a_legacy_court(tmp_path, monkeypatch, "AUTO8R1F1-R3")
    engine = game["stored_engine"]()
    owner = engine.state.actors[OWNER]
    assert [condition.condition_id for condition in owner.conditions.values()
            if condition.condition_id == LEGACY_CLAUSES], "the stored cast really holds the old shared id"
    assert motion.ignores_difficult(engine, owner) is True, "and the printed terrain clause really is running"

    engine._apply_condition(owner, "condition:core.incapacitated", "system:test", OWNER,
                            expires_on="UNTIL_REMOVED")

    assert not [condition for condition in owner.conditions.values()
                if condition.condition_id == LEGACY_CLAUSES], "the old clause ended with the stance"
    assert not [condition for condition in owner.conditions.values()
                if condition.condition_id.startswith("condition:typed.stance.")], "and so did the stance"
    assert motion.ignores_difficult(engine, owner) is False, "difficult terrain costs it again"


def test_a_stored_court_terrain_clause_moves_onto_the_current_condition_at_a_turn_boundary(tmp_path, monkeypatch):
    """The same old save, read the other way round: the clause is part of the stance, not of the cast, so a resumed
    fight keeps the printed benefit. It is republished on Court's own id rather than left as the shared one, which
    would otherwise show the fighter two terrain pills for a single stance."""
    game = _store_a_legacy_court(tmp_path, monkeypatch, "AUTO8R1F1-R3-MIGRATE")
    game["end_own_turn"]()  # the cast leaves it the owner's turn; ending it is the boundary that matters
    game["to_owner"]()
    owner = game["reload_owner"]()
    terrain = [condition.condition_id for condition in owner.conditions.values()
               if condition.condition_id in (athletics.COURT_CLAUSES, LEGACY_CLAUSES)]
    assert terrain == [athletics.COURT_CLAUSES], f"one terrain clause, on Court's own id: {terrain}"
    assert motion.ignores_difficult(game["stored_engine"](), owner) is True, "and the printed benefit still runs"


# ================================== Dizzying Tumble: the movement-time question, asked and answered at the table
def test_dizzying_tumble_asks_which_creature_to_dizzy_at_the_table(tmp_path):
    """"When you exit a space adjacent to a hostile creature, spend 10 feet of movement to force that creature to
    make a Wisdom saving throw." Which creature is the player's to name, and the review asked for the real
    pause/answer/reload path rather than a synchronous engine reaction provider."""
    game = fixture(tmp_path, [DIZZYING], seed="AUTO8R1F1-DIZZY", places=FLANKED_BY_OWNER)
    asked: list[tuple] = []

    def name_a_creature(prompt, choice):
        asked.append((prompt, choice))
        ids = [str(option["id"]) for option in choice["options"]]
        return [FOE if FOE in ids else ids[0]]

    game["commit"](move_candidate_id(game["menu"](), 3, 9), name_a_creature)

    assert asked, f"the fighter was not asked which creature to Dizzy: {asked}"
    ids = [str(option["id"]) for option in asked[0][1]["options"]]
    assert sorted(ids) == sorted([FOE, SECOND]), f"both creatures the fighter is leaving are on offer: {ids}"
    engine = game["stored_engine"]()
    assert any(event.event_type == "SAVE_ROLLED" and event.actor_id == FOE for event in engine.events), \
        "the chosen creature made the printed Wisdom saving throw"
    assert not [condition for condition in engine.state.actors[SECOND].conditions.values()
                if condition.condition_id == DIZZY], "and only the chosen one can be Dizzy"
    reload_identical(game["combat"], game["match_id"], game["userdata"])


# ============================ Meridian: the nested question about which grapple to end, at the real table
def test_meridian_asks_which_of_two_grapples_to_end_at_the_table(tmp_path):
    """Meridian asks twice in one Action -- once for the printed benefit, then again for which hold to end when
    more than one enemy has a grip. The nested question has to survive the table's pause/answer/reload path and
    end exactly one hold, which is the level the review said the engine-provider tests never reached."""
    game = fixture(tmp_path, [COORDINATED, MERIDIAN], seed="AUTO8R1F1-NESTED",
                   bundle_transform=_both(zero_martial_focus, easy_grapple_target), places=BESIDE_OWNER)
    game["end_own_turn"]()
    for enemy_id in (FOE, SECOND):
        game["foe_acts"](enemy_id, "Grapple")
    owner = game["reload_owner"]()
    assert len(_holds(owner)) == 2, f"both enemies really have a hold: {sorted(_holds(owner))}"

    asks: list[list[str]] = []
    picked: list[str] = []

    def answer(prompt, choice):
        ids = [str(option["id"]) for option in choice["options"]]
        asks.append(ids)
        if "grapple" in ids:  # the printed benefit
            return ["grapple"]
        picked.append(ids[-1])  # the nested question: name one of the two holds
        return [ids[-1]]

    game["to_owner"]()
    held = _holds(game["reload_owner"]())
    assert len(held) == 2, f"both enemies really have a hold at the moment of the choice: {sorted(held)}"
    game["commit"](candidate_id(game["menu"](), "Dash"), answer)

    assert len(asks) == 2, f"the printed benefit was asked, then the nested choice: {asks}"
    nested = asks[1]
    assert not any(option in ("step", "stand", "check") for option in nested), \
        f"the second question really is about the holds: {nested}"
    # The menu is exactly the two holds on the fighter, and the one it names is the one that ends. Comparing the
    # survivor against the *unselected* hold is what makes a wrong menu or a wrong removal fail here: counting
    # "one hold remains", or comparing the options against themselves, proves neither (review AUTO8r2, R7).
    assert set(nested) == held, \
        f"the second question offers exactly the holds on the fighter: {sorted(nested)} vs {sorted(held)}"
    assert picked == [nested[-1]], f"the hold that was chosen was recorded: {picked} vs {nested}"
    owner = game["reload_owner"]()
    assert _holds(owner) == held - {picked[0]}, \
        (f"exactly the chosen hold ended: {sorted(_holds(owner))} left, "
         f"but {sorted(held - {picked[0]})} should have")
    assert not [event for event in game["stored_engine"]().events
                if event.event_type == "GM_RIDER"], "and the resolving Action was not abandoned part way"
    reload_identical(game["combat"], game["match_id"], game["userdata"])
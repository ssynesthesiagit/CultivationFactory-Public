"""Hard Whip's chosen direction and Ground Game's Reaction, committed at the table and read back from
the saved fight.

Hard Whip: the printed Slam ends the grapple and then "Move the target up to 10 feet in one legal
direction other than directly upward". The direction is the user's to pick, so the table asks which way
the released creature goes and moves it exactly that way, through the ordinary forced-movement route
(save defenses, the moved creature's own reactions and Impact Collision all unchanged). A heading the
board blocks is not a "legal direction", so the menu offers only the ones that really move the creature
-- see `test_hard_whip_does_not_offer_a_map_edge_or_an_occupied_first_square`. Who answers that question
matters, so the declined answer, the table's own automatic chooser and a creature with no legal
direction at all each have their own table-level test.

Ground Game: "When one creature successfully grapples you, use your Reaction to force it to make the
same saving throw." The printed line names no hand, limb or physical grapple, so a grapple that arrives
by magic is offered the same Reaction as one made with the hands -- see
`test_ground_game_reaction_opens_for_a_grapple_that_used_no_hand` -- and because the Reaction is the
grabbed player's to spend, the table still stops for them when the grappler is played by the computer
(`test_ground_game_asks_the_manual_owner_while_the_grappler_turn_is_run_by_the_computer`).

The fixtures below are the only ones here. `positioned` puts two or more real compiled characters at
chosen squares, the first owning Hard Whip and a free (economy NONE) typed action named `Snare` whose
printed Grappled effect is applied without a hand -- the table's own definition of a grapple that
arrived by magic rather than by a Grapple attack -- so a test can ask about a heading without first
winning a contested Grapple; `worker2_support.fixture` is reused unchanged for everything that does not
need chosen squares.
"""
import copy
import json
import zipfile

import pytest

from combat.canonical import canonical_sha256
from combat.factory_compiler import compile_character
from combat.gate4_adapters import ManualControllerAdapter
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.ext.hand_occupancy import physical_row
from combat.ext.wrestling import first_step_open
from tests.h1_support import ROOT, sheet
from tests.test_carry import KIT
from tests.worker2_support import ALLY, FOE, OWNER, candidate, fixture, reload, settle, turn
from tests.test_r9i_karma_persistence import act

WHIP = "TAL_WRESTLING_HARD_WHIP"
GROUND = "TAL_WRESTLING_GROUND_GAME"
DIRECTION = "choice:needle.hard_whip_direction"
GRAPPLE_ROW = "choice:needle.ground_game"
HOLDER, HELD = "actor:factory.36000001", "actor:factory.36000002"
SEIZE = [{"type": "condition", "applies_to": "target", "condition": "grappled", "expires_on": "UNTIL_REMOVED"}]
# The eight headings the Slam's menu names, in the order the table lists them.
HEADINGS = (("north", (0, -1)), ("north-east", (1, -1)), ("east", (1, 0)), ("south-east", (1, 1)),
            ("south", (0, 1)), ("south-west", (-1, 1)), ("west", (-1, 0)), ("north-west", (-1, -1)))


# ----------------------------------------------------------------------------------------- fixtures
def prepare(bundles):
    """Seal the foe's escapes so the printed release, not a lucky escape roll, is what the test sees."""
    for bundle in bundles:
        if bundle["actor_id"] == FOE:
            bundle["actor_template"]["saving_throws"].update(STR=-100, DEX=-100, CON=-100)
        bundle.pop("bundle_sha256", None)
        bundle["bundle_sha256"] = canonical_sha256(bundle)


def positioned(tmp_path, places, *, holder_talents=(WHIP,), snare_on=HOLDER, blockers=(), modes=None,
               ask=(HOLDER,)):
    """Real compiled characters at ``places``: the first owns ``holder_talents``, and ``snare_on``
    names the fighter carrying the action-free `Snare`.

    ``blockers`` adds named bodies on the owner's team at their own squares; they only take up room,
    which is how a test walls a released creature in. ``modes`` sets any control mode other than
    MANUAL, and ``ask`` names the fighters compiled with the Ask me reaction plan. Everything is
    committed at the table like any other action, so nothing here
    reaches past the service to poke the engine.
    """
    roster = [(HOLDER, list(holder_talents), "River Keeper"), (HELD, [], "Visiting Fighter")]
    roster += [(actor_id, [], name) for actor_id, name in blockers]
    bundles, ids, teams = [], [], {}
    for actor_id, owned, name in roster:
        document = sheet(owned, cl=15, primary="Qi", kit={"starting_kit": KIT})
        document["identity"]["display_name"] = name
        document["ability_scores_and_statistics"]["hit_points"]["maximum"] = 1000
        folder = tmp_path / "portable_characters" / actor_id.removeprefix("actor:factory.")
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(document))
        bundle = compile_character(document, actor_id=actor_id, reaction_plan={"ask": actor_id in ask})
        if actor_id == HELD:
            bundle["actor_template"]["saving_throws"].update(STR=-100, DEX=-100, CON=-100)
        if actor_id == snare_on:
            action = copy.deepcopy(next(a for a in bundle["action_catalog"] if a["resolution_kind"] == "TYPED"))
            action.update(source_definition_id="action:test.auto135r1f1.seize", display_name="Snare",
                          economy="NONE", target_kind="HOSTILE_ENTITY", costs=[], range_ft=5)
            action["parameters"] = {"typed": {"effects": SEIZE, "numbers": {"cl": 15, "pb": 4, "save_dc": 100},
                                              "duration": {"kind": "instant"}, "riders": []}}
            bundle["action_catalog"].append(action)
            bundle["actor_template"]["action_ids"].append(action["source_definition_id"])
        bundle.pop("bundle_sha256", None)
        bundle["bundle_sha256"] = canonical_sha256(bundle)
        bundles.append(bundle)
        ids.append(actor_id)
        teams[actor_id] = "team:opponents" if actor_id == HELD else "team:factory"
    combat = CombatService(ROOT, tmp_path)
    mid = combat._finish_factory_match(bundles, ids, teams, places,
                                       combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"],
                                       [actor_id for actor_id in ids if actor_id != HELD], [HELD],
                                       control_modes={actor_id: (modes or {}).get(actor_id, "MANUAL")
                                                      for actor_id in ids},
                                       match_seed="AUTO135R1F1", display_name="AUTO135r1f1",
                                       maximum_rounds=10)["match_id"]
    return combat, TabletopService(combat, tmp_path), mid


def choosing(combat, candidate_id):
    """Hand the fight to Local Auto with one candidate named, keeping every other answer the real
    controller's: the table still resolves the Slam's own direction question by itself."""
    real = combat.controller

    class Fixed:
        def choose_primary_action(self, context):
            return ManualControllerAdapter(lambda _context: (candidate_id, ())).choose_primary_action(context)

        def __getattr__(self, name):
            return getattr(real, name)

    combat.controller = Fixed()


def named(combat, mid, name, target):
    engine = combat._load_session(mid).engine
    return next(c for c in engine.legal_candidates()
                if getattr(engine.action_catalog.get(c.source_definition_id), "display_name", None) == name
                and c.target_ids == (target,))


def grappled(tmp_path):
    combat, table, mid = fixture(tmp_path, [WHIP], foe_position={"x": 3, "y": 5}, bundle_transform=prepare)
    settle(table, mid, candidate(combat, mid, "Grapple", target=FOE).candidate_id)
    engine = reload(tmp_path, mid)
    assert any(c.condition_id == "condition:typed.grappled" for c in engine.state.actors[FOE].conditions.values())
    return combat, table, mid


def seized(tmp_path, places, **kwargs):
    combat, table, mid = positioned(tmp_path, places, **kwargs)
    settle(table, mid, named(combat, mid, "Snare", HELD).candidate_id)
    engine = reload(tmp_path, mid)
    assert any(c.condition_id == "condition:typed.grappled" for c in engine.state.actors[HELD].conditions.values())
    return combat, table, mid


def open_headings(engine, actor):
    """The headings the released creature can actually travel, in the order the menu lists them."""
    return [name for name, step in HEADINGS if first_step_open(engine, actor, step)]


def offered(prompts):
    for prompt in prompts:
        if prompt["context"]["reaction_source_id"] == DIRECTION:
            return [o["id"] for o in prompt["choice"]["options"]]
    raise AssertionError(f"Hard Whip never asked for a direction: {[p['context']['reaction_source_id'] for p in prompts]}")


# ----------------------------------------------------------------------------------------- Hard Whip
def test_hard_whip_asks_which_way_and_moves_the_released_creature_that_way(tmp_path):
    combat, table, mid = grappled(tmp_path)
    before = reload(tmp_path, mid).state.actors[FOE].position
    whip = candidate(combat, mid, "Apply a Slam: Hard Whip", target=FOE)
    prompts = settle(table, mid, whip.candidate_id, {DIRECTION: "east"})
    assert any(p["context"]["reaction_source_id"] == DIRECTION for p in prompts), prompts
    engine = reload(tmp_path, mid)
    after = engine.state.actors[FOE].position
    # 10 feet of chosen travel (two 5-foot squares), due east, across clear floor.
    assert (after.x, after.y) == (before.x + 2, before.y)
    # The printed line ends the grapple before it throws.
    assert not any(c.condition_id == "condition:typed.grappled"
                   for c in engine.state.actors[FOE].conditions.values())


@pytest.mark.parametrize("direction,delta", [("north", (0, -2)), ("north-east", (2, -2)),
                                             ("east", (2, 0)), ("west", (-2, 0)), ("north-west", (-2, -2))])
def test_hard_whip_honours_each_chosen_heading(tmp_path, direction, delta):
    combat, table, mid = grappled(tmp_path)
    before = reload(tmp_path, mid).state.actors[FOE].position
    settle(table, mid, candidate(combat, mid, "Apply a Slam: Hard Whip", target=FOE).candidate_id,
           {DIRECTION: direction})
    after = reload(tmp_path, mid).state.actors[FOE].position
    assert (after.x, after.y) == (before.x + delta[0], before.y + delta[1])


def test_hard_whip_offers_only_headings_the_released_creature_can_travel(tmp_path):
    """The owner stands at (3,6) and holds the foe at (3,5), so the ally's square and the owner's own
    square are the foe's south and south-east: neither is a legal direction, so neither is offered."""
    combat, table, mid = grappled(tmp_path)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].position.x == 3 and engine.state.actors[OWNER].position.y == 6
    assert engine.state.actors[ALLY].position.x == 4 and engine.state.actors[ALLY].position.y == 6
    prompts = settle(table, mid, candidate(combat, mid, "Apply a Slam: Hard Whip", target=FOE).candidate_id)
    assert set(offered(prompts)) == {"north", "north-east", "east", "west", "north-west"}


def test_hard_whip_does_not_offer_a_map_edge_or_an_occupied_first_square(tmp_path):
    """The foe is held at (0,5) beside its owner at (1,5).

    West leaves the board, so the route could not take even that first step; east is the owner's own
    square; the two east diagonals cross it. None of the four is a legal direction, and a menu that
    offered them would spend the Slam's Bonus Action and the hold for no travel at all."""
    combat, table, mid = seized(tmp_path, {HOLDER: {"x": 1, "y": 5}, HELD: {"x": 0, "y": 5}})
    engine = reload(tmp_path, mid)
    assert (engine.state.actors[HELD].position.x, engine.state.actors[HELD].position.y) == (0, 5)
    before = engine.state.actors[HELD].position
    prompts = settle(table, mid, named(combat, mid, "Apply a Slam: Hard Whip", HELD).candidate_id,
                     {DIRECTION: "north"})
    assert set(offered(prompts)) == {"north", "south", "south-west", "north-west"}
    engine = reload(tmp_path, mid)
    after = engine.state.actors[HELD].position
    assert (after.x, after.y) == (before.x, before.y - 2)
    assert not any(c.condition_id == "condition:typed.grappled" for c in engine.state.actors[HELD].conditions.values())


def test_hard_whip_declined_still_throws_straight_away_even_where_that_is_not_the_first_option(tmp_path):
    """The user is asked and refuses to answer: the Slam throws its target straight away anyway.

    The foe is held at (2,5) west of its owner at (3,5), so "straight away" is west while the first
    heading the menu lists is north. ``{DIRECTION: None}`` is this suite's explicit DECLINE answer
    (``tests.worker2_support.settle`` maps it to one), so this is the declined branch of the question,
    and it cannot pass by accident on the menu's first entry. The automatic chooser has its own test,
    `test_hard_whip_answered_automatically_prefers_straight_away_over_the_first_heading`."""
    combat, table, mid = seized(tmp_path, {HOLDER: {"x": 3, "y": 5}, HELD: {"x": 2, "y": 5}})
    before = reload(tmp_path, mid).state.actors[HELD].position
    prompts = settle(table, mid, named(combat, mid, "Apply a Slam: Hard Whip", HELD).candidate_id,
                     {DIRECTION: None})
    assert offered(prompts)[0] == "north"  # the heading nobody chose is not the one thrown
    after = reload(tmp_path, mid).state.actors[HELD].position
    assert (after.x, after.y) == (before.x - 2, before.y)


def test_hard_whip_answered_automatically_prefers_straight_away_over_the_first_heading(tmp_path):
    """The owner is under Local Auto, so the chooser the table ships with answers for the owner.

    The foe is held at (2,5) west of its owner at (3,5): north and west are both legal, so the menu
    lists them, and north is listed first, but "straight away" is west. The owner is handed to Local
    Auto for the Slam itself, so nothing is asked at the table and the direction comes from the
    automatic chooser -- a chooser that ignored the Slam's own preferred heading and took the first
    entry would send the foe north, which is what this test would catch."""
    combat, table, mid = seized(tmp_path, {HOLDER: {"x": 3, "y": 5}, HELD: {"x": 2, "y": 5}})
    engine = reload(tmp_path, mid)
    headings = open_headings(engine, engine.state.actors[HELD])
    assert headings[0] == "north" and "west" in headings  # straight away is legal, and is not first
    before = engine.state.actors[HELD].position
    combat.set_controller_mode(mid, actor_id=HOLDER, controller_mode="LOCAL_AUTO")
    choosing(combat, named(combat, mid, "Apply a Slam: Hard Whip", HELD).candidate_id)
    result = table.auto_step(mid, 0)
    assert result["status"] == "COMMITTED", result.get("reaction")  # the table was never asked
    engine = reload(tmp_path, mid)
    after = engine.state.actors[HELD].position
    assert (after.x, after.y) == (before.x - 2, before.y)
    assert not any(c.condition_id == "condition:typed.grappled"
                   for c in engine.state.actors[HELD].conditions.values())


def test_hard_whip_boxed_in_ends_the_grapple_without_moving_or_asking(tmp_path):
    """Every direction blocked: the hold and the Bonus Action are still spent, and nothing travels.

    The foe is held in the corner at (0,0) with its owner at (1,1) and two bodies at (1,0) and (0,1);
    the board edge closes the rest, so no heading is left. "Up to 10 feet" includes zero feet, so the
    table must not ask a question whose every answer would waste the Slam -- and it must say why the
    released creature stayed put, in the words the players read."""
    combat, table, mid = seized(tmp_path, {HOLDER: {"x": 1, "y": 1}, HELD: {"x": 0, "y": 0},
                                            "actor:factory.36000003": {"x": 1, "y": 0},
                                            "actor:factory.36000004": {"x": 0, "y": 1}},
                                 blockers=[("actor:factory.36000003", "Gate Warden"),
                                           ("actor:factory.36000004", "Gate Sentry")])
    engine = reload(tmp_path, mid)
    assert open_headings(engine, engine.state.actors[HELD]) == []  # genuinely walled in
    before = engine.state.actors[HELD].position
    assert engine.state.actors[HOLDER].bonus_action_available is True
    prompts = settle(table, mid, named(combat, mid, "Apply a Slam: Hard Whip", HELD).candidate_id)
    assert not any(p["context"]["reaction_source_id"] == DIRECTION for p in prompts), prompts
    engine = reload(tmp_path, mid)
    after = engine.state.actors[HELD].position
    assert (after.x, after.y) == (before.x, before.y)  # "up to 10 feet" is allowed to be none
    assert not any(c.condition_id == "condition:typed.grappled"
                   for c in engine.state.actors[HELD].conditions.values())
    assert engine.state.actors[HOLDER].bonus_action_available is False  # the Slam is still paid for
    said = [event.payload.get("log") for event in engine.events if event.event_type == "PASSIVE_TRIGGERED"]
    assert "Hard Whip ends River Keeper's grapple of Visiting Fighter, but every direction is blocked, " \
           "so Visiting Fighter is not moved." in said, said


def test_a_creature_without_hard_whip_is_never_asked_to_choose_a_direction(tmp_path):
    """The seam is inert for anyone who does not own the Slam: an ordinary shove never prompts for it."""
    combat, table, mid = fixture(tmp_path, [], foe_position={"x": 3, "y": 5}, bundle_transform=prepare)
    shove = candidate(combat, mid, "Shove: Push 5 ft", target=FOE)
    before = reload(tmp_path, mid).state.actors[FOE].position
    prompts = settle(table, mid, shove.candidate_id)
    assert not any(p["context"]["reaction_source_id"] == DIRECTION for p in prompts)
    after = reload(tmp_path, mid).state.actors[FOE].position
    # The ordinary push still moves straight away from the user, one square, unchanged.
    assert (after.x, after.y) == (before.x, before.y - 1)


# ----------------------------------------------------------------------------------------- Ground Game
def magic_grappler(bundles):
    """Give the foe a free `Snare` that applies the printed Grappled condition with no hand in it.

    The condition row carries no `grapple_source` and no `grappling_part`, and the action is not a
    Grapple attack, so `physical_row` -- the table's record of a grapple made by grabbing -- is False
    for it exactly as it would be for a projectile or a magical snare. That is what AUTO135r1 review
    finding 1 is about: the printed Reaction is not written for hands."""
    prepare(bundles)
    for bundle in bundles:
        if bundle["actor_id"] != FOE:
            continue
        action = copy.deepcopy(next(a for a in bundle["action_catalog"] if a["resolution_kind"] == "TYPED"))
        action.update(source_definition_id="action:test.auto135r1f1.snare", display_name="Snare",
                      economy="NONE", target_kind="HOSTILE_ENTITY", costs=[], range_ft=5)
        action["parameters"] = {"typed": {"effects": SEIZE, "numbers": {"cl": 15, "pb": 4, "save_dc": 100},
                                          "duration": {"kind": "instant"}, "riders": []}}
        bundle["action_catalog"].append(action)
        bundle["actor_template"]["action_ids"].append(action["source_definition_id"])
        bundle.pop("bundle_sha256", None)
        bundle["bundle_sha256"] = canonical_sha256(bundle)
    return bundles


@pytest.mark.parametrize("accept", [True, False])
def test_ground_game_reaction_opens_for_a_grapple_that_used_no_hand(tmp_path, accept):
    """A magical snare is still "one creature successfully grapples you", so the printed Reaction is
    offered on the grappler's own turn; spending it and refusing it both survive the saved fight."""
    combat, table, mid = fixture(tmp_path, [GROUND], foe_position={"x": 3, "y": 5},
                                 bundle_transform=magic_grappler)
    turn(table, mid, FOE)
    snare = named(combat, mid, "Snare", OWNER)
    first = act(table, mid, snare.candidate_id)
    assert first["status"] == "REACTION_REQUIRED", first
    prompts = settle(table, mid, snare.candidate_id, {GRAPPLE_ROW: "use" if accept else None})
    assert any(p["context"]["reactor_id"] == OWNER and p["context"]["reaction_source_id"] == GRAPPLE_ROW
               for p in prompts), [p["context"]["reaction_source_id"] for p in prompts]
    engine = reload(tmp_path, mid)
    held = next(c for c in engine.state.actors[OWNER].conditions.values() if c.condition_id == "condition:typed.grappled")
    assert not physical_row(engine, held)  # the snare used no hand, exactly as a magical grapple would not
    assert any(c.condition_id == "condition:typed.grappled" for c in engine.state.actors[OWNER].conditions.values())
    assert engine.state.actors[OWNER].reaction_available is (not accept)
    assert any(c.condition_id == "condition:typed.prone" for c in engine.state.actors[FOE].conditions.values()) == accept
    if accept:
        assert any(ev.event_type == "REACTION_RESOLVED" and ev.source_definition_id == GROUND
                   for ev in engine.events)
        save = next(ev for ev in engine.events if ev.event_type == "SAVE_ROLLED" and GROUND in ev.source_definition_id)
        assert save.payload["dc"] == 14


@pytest.mark.parametrize("accept", [True, False])
def test_ground_game_asks_the_manual_owner_while_the_grappler_turn_is_run_by_the_computer(tmp_path, accept):
    """The Reaction belongs to the grabbed player, so an AI-controlled grappler cannot answer it.

    The same magical snare, but this time the grappler is handed to Local Auto and plays the whole
    turn by itself, and only its opponent has the Ask me reaction plan. The fight must stop for
    that opponent -- the computer may not spend their Reaction -- and their answer, spent or refused,
    must survive the saved fight like any other."""
    combat, table, mid = positioned(tmp_path, {HOLDER: {"x": 1, "y": 5}, HELD: {"x": 0, "y": 5}},
                                     holder_talents=(GROUND,), snare_on=HELD, modes={HELD: "LOCAL_AUTO"})
    turn(table, mid, HELD)
    choosing(combat, named(combat, mid, "Snare", HOLDER).candidate_id)
    asked = table.auto_step(mid, 0)
    assert asked["status"] == "REACTION_REQUIRED", asked  # the AI's turn paused for the player
    prompt = asked["reaction"]
    assert prompt["context"]["reactor_id"] == HOLDER
    assert prompt["context"]["reaction_source_id"] == GRAPPLE_ROW
    assert [option["id"] for option in prompt["choice"]["options"]] == ["use"]
    saved = reload(tmp_path, mid).state
    assert not any(c.condition_id == "condition:typed.grappled"
                   for c in saved.actors[HOLDER].conditions.values())
    assert saved.actors[HOLDER].reaction_available is True  # asking commits nothing yet
    answer = {**prompt["context"], "selection": "USE" if accept else "DECLINE"}
    if accept:
        answer["option_ids"] = ["use"]
    done = table.auto_step(mid, 0, [answer])
    assert done["status"] == "COMMITTED", done.get("reaction")
    engine = reload(tmp_path, mid)
    assert any(c.condition_id == "condition:typed.grappled"
               for c in engine.state.actors[HOLDER].conditions.values())
    assert engine.state.actors[HOLDER].reaction_available is (not accept)
    assert any(c.condition_id == "condition:typed.prone"
               for c in engine.state.actors[HELD].conditions.values()) == accept
    assert any(event.event_type == "REACTION_RESOLVED" and event.source_definition_id == GROUND
               for event in engine.events) == accept

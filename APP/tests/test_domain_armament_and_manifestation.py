"""Hunt 81 #2-#3 (lane MMX59), review fixes (MMX63): the Domain Armament can protect an ally, and the Domain
Manifestation moves with you.

Hunt 81 found both at the table and this file keeps them fixed at the same level:

  * ``combat/ext/qi_path.py`` built Guard Mode so the Armament's owner was the protected creature whatever the
    Armament did ("At the end of your turn, designate one creature within 5 feet as protected", rules_text.json
    ``tianxia.path.qi_cultivation.feature.domain_armament``). The printed Armament also has a place -- "Initial
    Position: One unoccupied point within 30 feet" -- which the table never asked for and never kept. The table now
    asks for that point, remembers it across a commit and reload, asks which nearby creature is shielded, and ends
    the shield when that creature walks more than 5 feet from the Armament.

  * ``authority/typed_mechanics/reviewed_final.d/spirit.json`` left "The Domain moves with you" out of Domain
    Manifestation's zone effect, so the aura stayed on the square it was made on.

MMX63 corrected Guard Mode findings with table regressions and supplementary in-memory hook checks.
SOL86 adds committed controller/range/shield-correction coverage and explicit footprint geometry cases:

  * the protection lasts "until the start of your next turn" -- the *owner's* -- so it survives a turn taken by the
    creature it is protecting and ends when the owner's next turn starts;
  * a shield belongs to the owner that granted it: one owner's mode change, defeat or range correction no longer
    erases another's, and the owner may protect itself;
  * an automatic (AI) designation prefers the owner and then an eligible ally over an enemy whose id sorts first;
  * an Armament left out of range lands on the *nearest legal point* in its owner's real control range (60 feet
    with Domain Armament Link), and only loses the shield if the point it lands on leaves the beneficiary behind.

These are the printed rules, quoted from ``APP/authority/typed_mechanics/rules_text.json``:
    "At the end of your turn, designate one creature within 5 feet as protected until the start of your next turn."
    "The protection ends if: The creature moves more than 5 feet from the Armament. The Armament changes mode.
     The Domain Armament ends."
    "If a projected Armament ends outside range, it moves to the nearest legal point in range."
    "It must remain within 30 feet."  /  Domain Armament Link: "Control range becomes 60 feet."
"""

from __future__ import annotations

from pathlib import Path

import pytest

from combat import zones
from combat.ext import qi_path
from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate4_engine import Gate4ControllerEngine
from combat.gate5_service import CombatService
from combat.gate2_runtime_models import Position
from combat.tabletop_service import TabletopService
from tests.h1_support import sheet as _h1_sheet

ROOT = Path(__file__).resolve().parents[1]
ARMAMENT = "tianxia.path.qi_cultivation.feature.domain_armament"
LINK = "tianxia.path.qi_cultivation.feature.domain_armament_link"
MANIFESTATION = "tianxia.path.spirit_awakening.feature.domain_manifestation"
GUARD = f"passive:{ARMAMENT}.guard"
ME, ALLY, FOE = "actor:factory.mmx59", "actor:factory.mmx59_ally", "actor:factory.mmx59_foe"
# Ids for the automatic-designation regression, ordered so the enemy really is the first option in id order.
OWNER_RANKED, ALLY_RANKED, FOE_FIRST = ("actor:factory.mmx59_owner", "actor:factory.mmx59_ally",
                                         "actor:factory.mmx59_aaa_foe")
# The Armament hovers between the owner (3,6) and the ally (3,7), within 5 feet of both (5-foot squares).
BETWEEN = (4, 6)
BESIDE_ALLY = (4, 7)


def _doc(mid, *, path="Qi Cultivation", primary="Qi", cl=12):
    """A character owning ``mid``: one feature id, or several (a build with Domain Armament Link owns both)."""
    doc = _h1_sheet(list(mid) if not isinstance(mid, str) else [mid], cl=cl, primary=primary, score=18)
    doc["identity"]["path"] = path
    doc["ability_scores_and_statistics"]["primary_resource"] = {"name": primary, "maximum": 30}
    doc["ability_scores_and_statistics"]["hit_points"]["maximum"] = 80
    return doc


def _fight(tmp_path, *, path, primary, cl, feature, seed):
    bundles = [compile_character(_doc(feature, path=path, primary=primary, cl=cl), actor_id=ME, reaction_plan={"ask": True}),
               compile_character(_doc(feature, path=path, primary=primary, cl=cl), actor_id=FOE)]
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    mid = combat._finish_factory_match(
        bundles, [ME, FOE], {ME: "team:a", FOE: "team:b"}, {ME: {"x": 3, "y": 6}, FOE: {"x": 12, "y": 6}},
        combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"], [ME], [FOE],
        control_modes={ME: "MANUAL", FOE: "MANUAL"}, match_seed=seed,
        display_name="Hunt 81 Domain regression", maximum_rounds=20)["match_id"]
    return combat, table, mid


def _armament_fight(tmp_path, *, foe=FOE, foe_at=None, features=(ARMAMENT,), owner=ME, ally=ALLY,
                    owner_at=None, ally_at=None, stationary=False, shover=False, stored_range=None,
                    open_arena=False):
    """Owner and ally on team a and a foe on team b, so an ally worth shielding is present at the table.
    Every creature owns the Domain Armament, so one owner never disturbs another's."""
    owner_doc = _doc(features, cl=13 if LINK in features else 12)
    if stationary:
        owner_doc["ability_scores_and_statistics"]["speed"]["walking_ft"] = 1
    foe_doc = _doc(ARMAMENT, cl=10)
    if shover:
        # Deterministic ordinary Shove: its save DC exceeds every possible owner save.
        next(a for a in foe_doc["ability_scores_and_statistics"]["abilities"] if a["ability"] == "STR").update(score=60, modifier=25)
    bundles = [compile_character(owner_doc, actor_id=owner, reaction_plan={"ask": True}),
               compile_character(_doc(ARMAMENT, cl=10), actor_id=ally),
               compile_character(foe_doc, actor_id=foe)]
    if stored_range is not None:
        # Test-only restore action seeds the fallback-only stored representation using the normal
        # condition effect/commit path. This is not a claim about pre-MMX63 save contents.
        from copy import deepcopy
        from combat.canonical import canonical_sha256

        bundle = bundles[0]
        for action in bundle["action_catalog"]:
            action["parameters"].pop("armament_control_ft", None)
        restore = deepcopy(next(a for a in bundle["action_catalog"] if a["display_name"] == "Domain Armament: Guard Mode"))
        restore.update(source_definition_id="action:test.sol86.restore_armament", display_name="Restore stored Armament",
                       economy="ACTION")
        restore["parameters"] = {"typed": {"effects": [{"type": "condition", "condition": "domain_armament",
            "applies_to": "self", "until_escape": True,
            "condition_data": {"ax": 4, "ay": 6, "mode": "assault", "reach_ft": stored_range}}],
            "duration": {"kind": "permanent"}, "numbers": {"cl": 13, "pb": 4}}}
        bundle["action_catalog"].append(restore)
        bundle["actor_template"]["action_ids"].append(restore["source_definition_id"])
        bundle["bundle_sha256"] = canonical_sha256({k: v for k, v in bundle.items() if k != "bundle_sha256"})
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    arena = combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"]
    if open_arena:
        from copy import deepcopy
        arena = deepcopy(arena)
        arena["terrain_regions"] = []
    mid = combat._finish_factory_match(
        bundles, [owner, ally, foe], {owner: "team:a", ally: "team:a", foe: "team:b"},
        {owner: owner_at or {"x": 3, "y": 6}, ally: ally_at or {"x": 3, "y": 7}, foe: foe_at or {"x": 12, "y": 6}},
        arena, [owner, ally], [foe],
        control_modes={owner: "MANUAL", ally: "MANUAL", foe: "MANUAL"}, match_seed="MMX59",
        display_name="Hunt 81 Armament regression", maximum_rounds=20)["match_id"]
    return combat, table, mid


def _wait_for(table, mid, actor_id, limit=40):
    for _ in range(limit):
        state = table.state(mid)
        if state["menu"]["actor_id"] == actor_id:
            return state
        table.act(mid, state["menu"]["end_turn"], state["menu"]["decision_id"],
                  state["menu"]["state_version"], state["last_sequence"])
    raise AssertionError(f"the fight never reached {actor_id}")


def _act(table, mid, label, *, at=None):
    state = table.state(mid)
    group = next(g for g in state["menu"]["actions"] if g["label"] == label or g.get("display_name") == label)
    option = next(o for o in group["options"]
                  if at is None or (o.get("destination") and (o["destination"]["x"], o["destination"]["y"]) == at))
    return table.act(mid, option["candidate_id"], state["menu"]["decision_id"],
                     state["menu"]["state_version"], state["last_sequence"])


def _end_turn(table, mid, answers=()):
    state = table.state(mid)
    return table.act(mid, state["menu"]["end_turn"], state["menu"]["decision_id"],
                     state["menu"]["state_version"], state["last_sequence"], list(answers))


def _designate(table, mid, who):
    """Answer the end-of-turn Guard Mode question for ``who`` through a real table transaction, so the shield it
    grants is committed fight state that a reload can see."""
    paused = _end_turn(table, mid)
    assert paused["status"] == "REACTION_REQUIRED", paused
    context = paused["reaction"]["context"]
    assert who in {option["id"] for option in paused["reaction"]["choice"]["options"]}, who
    return _end_turn(table, mid, answers=[{**context, "selection": "USE", "option_ids": [who]}])


def _reload(tmp_path, mid):
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.mechanical.replay()["status"] == "PASS", "the fight still replays from its committed events"
    return loaded.engine


def _shield(engine, actor_id):
    return [m for m in engine.state.actors[actor_id].modifiers.values() if m.source_definition_id == GUARD]


def _shield_owners(engine, actor_id):
    """Which owners' Armaments are shielding this creature -- two owners may shield the same creature."""
    return {m.source_actor_id for m in _shield(engine, actor_id)}


def _guard_mode(table, mid, at=BETWEEN):
    """Manifest the Armament on ``at`` and put it in Guard Mode, on the actor whose turn it is."""
    _act(table, mid, "Domain Armament: Manifest", at=at)
    _act(table, mid, "Domain Armament: Guard Mode")


def _commit_move(table, mid, goal):
    """Walk the creature whose turn it is as far along as it can get toward ``goal`` -- the table only offers
    the endpoints it can actually reach on this turn."""
    state = table.state(mid)
    start = next(m for m in state["menu"]["moves"])["path"][0]
    move = min(state["menu"]["moves"],
               key=lambda m: (max(abs(m["destination"]["x"] - goal[0]), abs(m["destination"]["y"] - goal[1])),
                              -abs(m["destination"]["x"] - start["x"]) - abs(m["destination"]["y"] - start["y"])))
    return table.act(mid, move["candidate_id"], state["menu"]["decision_id"],
                     state["menu"]["state_version"], state["last_sequence"]), move["destination"]


def _nearest_in_range(grid, owner_position, from_point, reach_ft, taken):
    """Supplementary scan oracle; explicit occupied/blocked expectations below catch shared geometry errors."""
    best = None
    for x in range(grid.width):
        for y in range(grid.height):
            cell = (x, y)
            if grid.distance_ft(cell, owner_position) > reach_ft:
                continue
            if not grid.placement_legal(cell, occupied_cells=taken):
                continue
            key = (grid.distance_ft(cell, from_point), abs(x - from_point[0]) + abs(y - from_point[1]), x, y)
            if best is None or key < best:
                best = key
    return (best[2], best[3]) if best else None


def test_armament_actions_share_the_engine_condition_gate(tmp_path):
    combat, table, mid = _armament_fight(tmp_path, foe_at={"x": 8, "y": 6})
    _wait_for(table, mid, ME)
    session = combat._load_session(mid)
    engine = session.engine
    actions = {a.display_name: a for a in engine.action_catalog.values() if a.owner_id == ME}
    attack = actions["Domain Armament Attack"]
    guard = actions["Domain Armament: Guard Mode"]

    for action in (attack, guard):
        availability = engine.action_availability(ME, action.source_definition_id)
        assert availability["available"] is False
        assert availability["code"] == "REQUIRES_CONDITION"
        assert action.source_definition_id not in {
            row["source_definition_id"] for row in table.state(mid, lazy=False)["menu"]["actions"]
        }
    assert "Domain Armament Attack" not in {
        row["label"] for row in table.state(mid, lazy=True)["menu"]["actions"]
    }

    assert _act(table, mid, "Domain Armament: Manifest", at=BETWEEN)["status"] == "COMMITTED"
    engine = combat._load_session(mid).engine
    assert engine.action_availability(ME, attack.source_definition_id)["available"] is True
    assert engine.action_availability(ME, guard.source_definition_id)["available"] is True


# ------------------------------------------------------------------------------------------------ the Armament's place
def test_domain_armament_is_manifested_on_a_chosen_point_that_survives_a_reload(tmp_path):
    combat, table, mid = _armament_fight(tmp_path)
    _wait_for(table, mid, ME)
    assert _act(table, mid, "Domain Armament: Manifest", at=BETWEEN)["status"] == "COMMITTED"
    assert qi_path._place(combat._load_session(mid).engine.state.actors[ME]) == BETWEEN
    assert qi_path._place(_reload(tmp_path, mid).state.actors[ME]) == BETWEEN, "the Armament's point is fight state"


def test_domain_armament_asks_for_its_point_instead_of_only_its_owner(tmp_path):
    """"Initial Position: One unoccupied point within 30 feet": the table offers points, not just the owner."""
    combat, table, mid = _armament_fight(tmp_path)
    _wait_for(table, mid, ME)
    group = next(g for g in table.state(mid)["menu"]["actions"] if g["label"] == "Domain Armament: Manifest")
    points = {(o["destination"]["x"], o["destination"]["y"]) for o in group["options"]}
    engine = combat._load_session(mid).engine
    assert len(points) > 1, "one option per point in range, not a single self-only choice"
    assert all(engine.grid.distance_ft(engine.state.actors[ME].position, p) <= 30 for p in points)
    assert (3, 6) not in points, "a point the owner stands on is not a separate unoccupied point"


# ------------------------------------------------------------------------------------------------ Guard protects an ally
def test_guard_mode_lets_the_owner_shield_an_ally_rather_than_always_itself(tmp_path):
    combat, table, mid = _armament_fight(tmp_path)
    _wait_for(table, mid, ME)
    _guard_mode(table, mid)
    result = _end_turn(table, mid)
    assert result["status"] == "REACTION_REQUIRED", "designating the protected creature is the owner's decision"
    prompt = result["reaction"]
    assert {option["id"] for option in prompt["choice"]["options"]} == {ME, ALLY}, "only creatures within 5 feet"
    said = str(prompt.get("summary") or "")
    assert "5 feet" in said and "+2 AC" in said and "ranged" in said, said
    assert "choice:needle" not in said and "condition:typed" not in said, "no internal ids in player-facing text"
    described = " ".join(str(option.get("description") or "") for option in prompt["choice"]["options"])
    assert described.count("+2 AC against ranged attack rolls") == 2, described

    context = prompt["context"]
    answered = _end_turn(table, mid, answers=[{**context, "selection": "USE", "option_ids": [ALLY]}])
    assert answered["status"] in ("COMMITTED", "REACTION_REQUIRED"), answered

    engine = _reload(tmp_path, mid)
    assert _shield(engine, ALLY), "the creature the owner chose is the protected one"
    assert not _shield(engine, ME), "the owner is no longer protected in the chosen creature's place"
    modifier = _shield(engine, ALLY)[0]
    assert (modifier.target_field, modifier.operation, modifier.value) == ("armor_class_vs_ranged", "ADD", 2)
    # "until the start of your next turn" -- the owner's, not the protected creature's (MMX63 finding 1).
    assert modifier.expires_on == "START_OF_SOURCE_NEXT_TURN"
    assert modifier.source_actor_id == ME, "the shield records the owner that granted it"


def test_guard_shield_survives_the_protected_creatures_own_turn_and_ends_at_the_owners_next_turn(tmp_path):
    """"designate one creature ... as protected until the start of your next turn": the deadline is the owner's next
    turn, so the protected ally keeps the +2 AC through a whole turn of its own (MMX63 finding 1)."""
    combat, table, mid = _armament_fight(tmp_path)
    _wait_for(table, mid, ME)
    _guard_mode(table, mid)
    _designate(table, mid, ALLY)

    # The ally acts before the owner is back (initiative FOE, ALLY, ME). Its turn starting must not end the shield.
    _wait_for(table, mid, ALLY)
    engine = _reload(tmp_path, mid)
    assert _shield(engine, ALLY), "the protected creature's own turn start does not end the shield"
    assert _shield_owners(engine, ALLY) == {ME}, "and it is still the owner's shield"

    # The owner's next turn begins: "until the start of your next turn" has arrived.
    _wait_for(table, mid, ME)
    engine = _reload(tmp_path, mid)
    assert not _shield(engine, ALLY), "'until the start of your next turn' ends it on the owner's turn"


def test_guard_shield_ends_when_the_protected_creature_walks_more_than_5_feet_away(tmp_path):
    combat, table, mid = _armament_fight(tmp_path)
    _wait_for(table, mid, ME)
    _guard_mode(table, mid)
    _designate(table, mid, ALLY)

    # The shield is committed fight state and is still live on the ally's own turn, where the walk happens.
    _wait_for(table, mid, ALLY)
    engine = _reload(tmp_path, mid)
    assert _shield(engine, ALLY), "the committed shield is still there immediately before the walk"
    armed = engine.state.actors[ME]
    away = (engine.state.actors[ALLY].position.x + 4, engine.state.actors[ALLY].position.y + 4)
    result, reached = _commit_move(table, mid, away)
    assert result["status"] == "COMMITTED"
    engine = _reload(tmp_path, mid)
    moved = engine.state.actors[ALLY]
    assert (moved.position.x, moved.position.y) == tuple(reached.values())
    assert engine.grid.distance_ft(qi_path._hovering(engine.state.actors[ME]), moved.position) > 5
    assert not _shield(engine, ALLY), "'the creature moves more than 5 feet from the Armament'"


# ------------------------------------------------------------------------------------------------ one shield per owner
def test_two_owners_never_remove_each_others_shield_over_one_creature(tmp_path):
    """Two Armaments may shield the same creature. Only the owner that granted a shield takes it away -- a second
    owner's designation or mode change leaves the first owner's protection standing (MMX63 finding 2)."""
    combat, table, mid = _armament_fight(tmp_path)

    # The ally manifests first (it acts before the owner in the initiative) and shields the owner.
    _wait_for(table, mid, ALLY)
    _guard_mode(table, mid, at=BETWEEN)
    _designate(table, mid, ME)
    engine = _reload(tmp_path, mid)
    assert _shield_owners(engine, ME) == {ALLY}, "the ally's Armament is shielding the owner"

    # The owner brings up a second Armament on another point and shields *itself*: the same creature, twice over.
    _wait_for(table, mid, ME)
    _guard_mode(table, mid, at=BESIDE_ALLY)
    _designate(table, mid, ME)
    engine = _reload(tmp_path, mid)
    assert _shield_owners(engine, ME) == {ALLY, ME}, "the owner's own designation did not take the ally's shield"
    assert qi_path._place(engine.state.actors[ME]) == BESIDE_ALLY
    assert qi_path._place(engine.state.actors[ALLY]) == BETWEEN, "each Armament keeps its own place"

    # The ally changes mode: "the Armament changes mode" ends the protection *that* Armament granted, and only it.
    _wait_for(table, mid, ALLY)
    _act(table, mid, "Domain Armament: Assault Mode")
    engine = _reload(tmp_path, mid)
    assert _shield_owners(engine, ME) == {ME}, "only the ally's own shield went with the ally's mode change"
    assert qi_path._place(engine.state.actors[ME]) == BESIDE_ALLY, "and the owner's Armament is untouched"


def test_an_owner_may_protect_itself_and_the_armament_ending_takes_that_shield_off(tmp_path):
    """'designate one creature within 5 feet' has no exception for yourself, and 'the Domain Armament ends' --
    here the owner falling unconscious -- takes the shield off (MMX63 finding 3)."""
    combat, table, mid = _armament_fight(tmp_path)
    _wait_for(table, mid, ME)
    _guard_mode(table, mid)
    _designate(table, mid, ME)
    engine = _reload(tmp_path, mid)
    owner = engine.state.actors[ME]
    assert _shield_owners(engine, ME) == {ME}, "an owner can designate itself"

    # "Ends if you become Unconscious": the owner's own unconsciousness is an end condition for a self-shield.
    # (Applied through the engine, as the repo's own rider tests do -- the shield it removes was committed by the
    # table above and reloaded from the fight; only the end condition itself is raised in memory.)
    engine._apply_condition(owner, "condition:typed.unconscious", "test:knocked out", FOE, expires_on="UNTIL_REMOVED")
    assert not _shield(engine, ME), "the Domain Armament ended, so the shield it granted went with it"
    assert qi_path._armed(owner) is None, "and the Armament itself ended"


def test_an_owners_self_shield_goes_when_its_armament_changes_mode(tmp_path):
    """The other early end condition for a self-shield, driven through the plug-in's own mode change on a shield
    that a real committed table transaction granted."""
    combat, table, mid = _armament_fight(tmp_path)
    _wait_for(table, mid, ME)
    _guard_mode(table, mid)
    _designate(table, mid, ME)
    engine = _reload(tmp_path, mid)
    owner = engine.state.actors[ME]
    assert _shield(engine, ME), "the owner's self-shield is committed fight state"

    source = f"passive:{ARMAMENT}"
    ctx = type("Ctx", (), {"engine": engine, "actor": owner, "source": source})()
    qi_path.domain_armament(ctx, {"do": "assault"})
    assert not _shield(engine, ME), "'the Armament changes mode' ends the protection"


# ------------------------------------------------------------------------------------------------ automatic designation
def test_no_intent_guard_fallback_prefers_the_owner_in_memory(tmp_path):
    """Supplementary no-intent fallback check, not a controller or committed designation test."""
    owner, ally, foe = OWNER_RANKED, ALLY_RANKED, FOE_FIRST
    assert sorted([owner, ally, foe]) == [foe, ally, owner], "the enemy really is the first option in id order"
    combat, table, mid = _armament_fight(tmp_path, foe=foe, foe_at={"x": 4, "y": 7},
                                         owner=owner, ally=ally)

    _wait_for(table, mid, owner)
    _guard_mode(table, mid)
    paused = _end_turn(table, mid)                     # the question is asked ...
    assert paused["status"] == "REACTION_REQUIRED"
    assert {o["id"] for o in paused["reaction"]["choice"]["options"]} == {owner, ally, foe}, "all three are in reach"
    context = paused["reaction"]["context"]
    # ... and declined, so the reloaded engine has a Guard Mode Armament and no shield yet.
    _end_turn(table, mid, answers=[{**context, "selection": "DECLINE", "option_ids": []}])
    engine = _reload(tmp_path, mid)
    assert qi_path._armed(engine.state.actors[owner]) is not None, "the Armament is still in Guard Mode"
    assert not _shield(engine, foe) and not _shield(engine, owner), "nobody is protected yet"

    # Answer the question the way an actor whose turn is ending does: nobody is asked, and the turn belongs to it.
    engine.state.current_actor_id = owner
    qi_path.armament_guard(engine, engine.state.actors[owner])   # nobody answering: the automatic choice
    assert _shield_owners(engine, owner) == {owner}, "the automatic choice shields the owner"
    assert not _shield(engine, foe), "and never the enemy standing next to the Armament"


@pytest.mark.parametrize("point,protected", [(BETWEEN, OWNER_RANKED), ((4, 8), ALLY_RANKED)])
def test_local_auto_commits_guard_choice_and_reloads_friendly_preference(tmp_path, point, protected):
    owner, ally, foe = OWNER_RANKED, ALLY_RANKED, FOE_FIRST
    combat, table, mid = _armament_fight(tmp_path, owner=owner, ally=ally, foe=foe,
        foe_at={"x": 4, "y": 7}, stationary=True)
    _wait_for(table, mid, owner)
    _guard_mode(table, mid, at=point)
    _act(table, mid, "Dodge")
    engine = _reload(tmp_path, mid)
    assert not _shield(engine, owner) and not _shield(engine, ally)
    assert engine.grid.distance_ft(point, engine.state.actors[foe].position) <= 5
    assert (engine.grid.distance_ft(point, engine.state.actors[owner].position) <= 5) == (protected == owner)
    combat.set_controller_mode(mid, actor_id=owner, controller_mode="LOCAL_AUTO")
    for _ in range(10):
        result = table.auto_step(mid, table.state(mid)["last_sequence"])
        assert result["status"] == "COMMITTED", result
        if _reload(tmp_path, mid).state.current_actor_id != owner:
            break
    engine = _reload(tmp_path, mid)
    assert engine.state.current_actor_id != owner, "the stock controller committed End Turn"
    assert _shield_owners(engine, protected) == {owner}
    assert not _shield(engine, foe)
    assert not _shield(engine, ally if protected == owner else owner)
    # A recorded extension decision proves this went through the controller, not ask's no-intent fallback.
    journal = combat._load_session(mid).controller_journal_path.read_text()
    assert qi_path.GUARD_CHOICE in journal


@pytest.mark.parametrize("large_actor", [ALLY, ME])
def test_nearest_correction_excludes_non_anchor_footprint_cells_and_walls(tmp_path, large_actor):
    """Supplementary geometry check: (5,6) is occupied even though the 2x2 anchor is (5,5)."""
    from combat.footprints import ActorFootprintDefinition

    combat, table, mid = _armament_fight(tmp_path)
    engine = _reload(tmp_path, mid)
    owner = engine.state.actors[ME]
    owner.position = Position(x=11, y=6)
    engine.state.actors[large_actor].position = Position(x=5, y=5)
    engine.actor_footprints[large_actor] = ActorFootprintDefinition.rectangle(2, 2,
        footprint_id="footprint:test.sol86.large", source_definition_id="test:sol86.large")
    # The owner's footprint must also exclude non-anchor cells from the legal candidates.
    if large_actor == ME:
        assert qi_path._nearest_legal_point(engine, owner, (6, 6)) == (6, 7)
        return
    assert qi_path._nearest_legal_point(engine, owner, BETWEEN) == (5, 7)
    engine.grid.blocked.add((5, 7))
    assert qi_path._nearest_legal_point(engine, owner, BETWEEN) == (5, 4)


@pytest.mark.parametrize("ally_at,expected,retained", [
    ({"x": 5, "y": 6}, (5, 5), True),
    ({"x": 3, "y": 7}, (5, 6), False),
])
def test_table_shove_corrects_armament_and_commits_shield_retention(tmp_path, ally_at, expected, retained):
    """An ordinary committed Shove moves the owner beyond 30 feet during the foe's turn."""
    combat, table, mid = _armament_fight(tmp_path, owner_at={"x": 10, "y": 6},
        ally_at=ally_at, foe_at={"x": 9, "y": 6}, shover=True, open_arena=True)
    _wait_for(table, mid, ME)
    _guard_mode(table, mid)
    _designate(table, mid, ALLY)
    _wait_for(table, mid, FOE)
    before = _reload(tmp_path, mid)
    assert _shield_owners(before, ALLY) == {ME}
    assert qi_path._place(before.state.actors[ME]) == BETWEEN
    result = _act(table, mid, "Shove: Push 5 ft")
    assert result["status"] == "COMMITTED", result
    engine = _reload(tmp_path, mid)
    assert engine.state.actors[ME].position == Position(x=11, y=6)
    assert qi_path._place(engine.state.actors[ME]) == expected
    assert bool(_shield(engine, ALLY)) == retained


@pytest.mark.parametrize("fallback", [False, True])
def test_sixty_foot_correction_keeps_effective_range_after_commit_and_reload(tmp_path, fallback):
    """Real Link build, or a fixture restoring only a stored reach_ft=60, then real table Shoves."""
    combat, table, mid = _armament_fight(tmp_path, features=(ARMAMENT, LINK),
        owner_at={"x": 10, "y": 6}, foe_at={"x": 9, "y": 6}, shover=True,
        stored_range=60 if fallback else None, open_arena=True)
    _wait_for(table, mid, ME)
    _act(table, mid, "Restore stored Armament" if fallback else "Domain Armament: Manifest",
         at=None if fallback else BETWEEN)
    # Move exactly to the 60-foot boundary before handing the turn to the shover.
    state = table.state(mid)
    move = next(m for m in state["menu"]["moves"] if m["destination"] == {"x": 16, "y": 6})
    assert table.act(mid, move["candidate_id"], state["menu"]["decision_id"],
                     state["menu"]["state_version"], state["last_sequence"])["status"] == "COMMITTED"
    _end_turn(table, mid)
    _wait_for(table, mid, FOE)
    state = table.state(mid)
    move = next(m for m in state["menu"]["moves"] if m["destination"] == {"x": 15, "y": 6})
    assert table.act(mid, move["candidate_id"], state["menu"]["decision_id"],
                     state["menu"]["state_version"], state["last_sequence"])["status"] == "COMMITTED"
    before = _reload(tmp_path, mid)
    assert qi_path._control_range_ft(before, before.state.actors[ME]) == 60
    assert qi_path._place(before.state.actors[ME]) == BETWEEN, "60 feet does not correct into 30"
    if fallback:
        assert not any("armament_control_ft" in a.parameters for a in before.action_catalog.values()
                       if a.owner_id == ME)
    assert _act(table, mid, "Shove: Push 5 ft")["status"] == "COMMITTED"
    engine = _reload(tmp_path, mid)
    owner = engine.state.actors[ME]
    assert owner.position == Position(x=17, y=6)
    assert qi_path._place(owner) == (5, 6)
    assert qi_path._armed(owner).data["reach_ft"] == 60
    assert qi_path._control_range_ft(engine, owner) == 60
    # The owner takes one more ordinary step next turn. Losing the stored fallback would pull to 30 feet here.
    _wait_for(table, mid, ME)
    result, reached = _commit_move(table, mid, (18, 6))
    assert result["status"] == "COMMITTED"
    assert reached == {"x": 18, "y": 6}
    owner = _reload(tmp_path, mid).state.actors[ME]
    assert qi_path._place(owner) == (6, 6)
    assert qi_path._armed(owner).data["reach_ft"] == 60


# ------------------------------------------------------------------------------------------------ out of range
def test_manifesting_a_new_armament_out_of_range_brings_it_back_in(tmp_path):
    """"If a projected Armament ends outside range, it moves to the nearest legal point in range"."""
    combat, table, mid = _armament_fight(tmp_path)
    _wait_for(table, mid, ME)
    _act(table, mid, "Domain Armament: Manifest", at=BETWEEN)
    # Walking away takes more than one Speed: the Armament is 30 feet from its owner before it drifts.
    for _ in range(3):
        _wait_for(table, mid, ME)
        result, _reached = _commit_move(table, mid, (14, 6))
        assert result["status"] == "COMMITTED"
        _end_turn(table, mid)   # hand the turn back so the next walk is a fresh one
    engine = _reload(tmp_path, mid)
    owner = engine.state.actors[ME]
    assert engine.grid.distance_ft(BETWEEN, (owner.position.x, owner.position.y)) > 30, "the owner really walked away"
    place = qi_path._place(owner)
    assert place != BETWEEN, "the Armament no longer sits on the abandoned point"
    assert engine.grid.distance_ft(owner.position, place) <= 30, "it came back into range"
    assert qi_path._armed(owner) is not None, "and is still the owner's Armament"

    # "the NEAREST legal point in range", not merely a point in range: the owner's own square is not the answer, and
    # nothing legal between the abandoned point and where it landed was closer to the abandoned point.
    assert place != (owner.position.x, owner.position.y), "the owner stands on that square: it is not a free point"
    taken = {cell for a in engine.state.actors.values() if a.active for cell in engine._actor_cells(a)}
    expected = _nearest_in_range(engine.grid, owner.position, BETWEEN, 30, taken)
    assert place == expected, f"landed on {place}, nearest legal point in range is {expected}"
    assert engine.grid.distance_ft(BETWEEN, place) < engine.grid.distance_ft(BETWEEN, (owner.position.x, owner.position.y))


def test_an_armament_out_of_range_lands_on_the_nearest_legal_point_not_on_its_owner(tmp_path):
    """The reviewer's example, exactly: the Armament left at (4,6) with its owner at (11,6) comes to (5,6) -- a
    point 5 feet from where it ended and still 30 feet from the owner -- not to the owner's own square (MMX63
    finding 5)."""
    combat, table, mid = _armament_fight(tmp_path)
    _wait_for(table, mid, ME)
    _act(table, mid, "Domain Armament: Manifest", at=BETWEEN)
    engine = _reload(tmp_path, mid)
    owner = engine.state.actors[ME]
    owner.position = Position(x=11, y=6)          # the owner walks east, leaving the Armament behind
    engine.state.actors[FOE].position = Position(x=16, y=6)
    engine.state.actors[ALLY].position = Position(x=3, y=7)

    assert engine.grid.distance_ft(BETWEEN, (11, 6)) == 35 > 30, "the Armament is now out of range"
    armed = qi_path._armed(owner)
    assert armed is not None
    assert qi_path._nearest_legal_point(engine, owner, BETWEEN) == (5, 6)
    landed = qi_path._recentre(engine, owner, armed)
    assert landed == (5, 6), "'the nearest legal point in range' -- the owner's square is not a free point"
    assert qi_path._place(owner) == (5, 6), "and it is remembered there"


def test_domain_armament_link_holds_the_armament_at_sixty_feet_and_no_further(tmp_path):
    """Supplementary in-memory geometry check for Link's printed 60-foot control range."""
    combat, table, mid = _armament_fight(tmp_path, features=(ARMAMENT, LINK))
    _wait_for(table, mid, ME)
    _act(table, mid, "Domain Armament: Manifest", at=BETWEEN)
    engine = _reload(tmp_path, mid)
    owner = engine.state.actors[ME]
    assert qi_path._control_range_ft(engine, owner) == 60, "Domain Armament Link: control range becomes 60 feet"

    owner.position = Position(x=15, y=6)     # 55 feet from the Armament at (4,6)
    engine.state.actors[FOE].position = Position(x=18, y=6)
    assert not qi_path._drifting(engine, owner, BETWEEN), "55 feet is inside 60"
    owner.position = Position(x=17, y=6)     # 65 feet: out of range even with the Link
    engine.state.actors[FOE].position = Position(x=19, y=6)
    assert qi_path._drifting(engine, owner, BETWEEN), "65 feet is outside 60"
    taken = {cell for a in engine.state.actors.values() if a.active for cell in engine._actor_cells(a)}
    landed = qi_path._nearest_legal_point(engine, owner, BETWEEN)
    assert engine.grid.distance_ft(landed, owner.position) <= 60, "the correction lands inside the 60-foot range"
    assert landed == _nearest_in_range(engine.grid, owner.position, BETWEEN, 60, taken), "and on the nearest legal point"

    # The same Armament without the Link is corrected much sooner, at 30 feet.
    plain, plain_table, plain_mid = _armament_fight(tmp_path.parent / "plain")
    _wait_for(plain_table, plain_mid, ME)
    _act(plain_table, plain_mid, "Domain Armament: Manifest", at=BETWEEN)
    plain_engine = _reload(tmp_path.parent / "plain", plain_mid)
    plain_owner = plain_engine.state.actors[ME]
    assert qi_path._control_range_ft(plain_engine, plain_owner) == 30, "a plain Domain Armament keeps 30 feet"
    plain_owner.position = Position(x=15, y=6)
    assert qi_path._drifting(plain_engine, plain_owner, BETWEEN), "55 feet is outside 30"


def test_a_corrected_armament_keeps_the_shield_when_the_beneficiary_is_still_covered(tmp_path):
    """Supplementary in-memory hook check starting with a committed shield; corrections are not committed here.
    Correcting the Armament's place is not one of the printed end conditions: the shield only goes when the
    point it lands on leaves the beneficiary more than 5 feet away (MMX63 finding 5)."""
    combat, table, mid = _armament_fight(tmp_path)
    _wait_for(table, mid, ME)
    _guard_mode(table, mid)
    _designate(table, mid, ALLY)
    engine = _reload(tmp_path, mid)
    owner = engine.state.actors[ME]
    assert _shield(engine, ALLY), "a committed shield on the ally"

    # The owner walks 40 feet east, leaving the Armament behind at (4,6): the table's own movement event corrects it.
    engine.state.actors[FOE].position = Position(x=18, y=6)
    owner.position = Position(x=11, y=6)
    engine.state.actors[ALLY].position = Position(x=5, y=6)     # still 5 feet from the abandoned point
    assert qi_path._drifting(engine, owner, BETWEEN)
    qi_path.armament_moves(engine, "MOVEMENT_COMMITTED", {"actor_id": ME})
    landed = qi_path._place(owner)
    assert landed != (owner.position.x, owner.position.y), "the correction is not a teleport onto its owner"
    assert engine.grid.distance_ft(landed, engine.state.actors[ALLY].position) <= qi_path.SHIELD
    assert _shield(engine, ALLY), "the beneficiary is still covered by the corrected point: the shield stays"

    # The same correction with the beneficiary left behind: the point it lands on no longer covers it.
    engine2 = _reload(tmp_path, mid)
    other = engine2.state.actors[ME]
    engine2.state.actors[FOE].position = Position(x=18, y=6)
    engine2.state.actors[ALLY].position = Position(x=3, y=7)
    other.position = Position(x=11, y=6)
    qi_path.armament_moves(engine2, "MOVEMENT_COMMITTED", {"actor_id": ME})
    assert engine2.grid.distance_ft(qi_path._place(other), engine2.state.actors[ALLY].position) > qi_path.SHIELD
    assert not _shield(engine2, ALLY), "the corrected point left the beneficiary behind, so the shield goes"


# ------------------------------------------------------------------------------------------------ the Domain moves with you
def test_domain_manifestation_aura_moves_with_its_owner(tmp_path):
    combat, table, mid = _fight(tmp_path, path="Spirit Awakening", primary="Resonance", cl=15,
                                feature=MANIFESTATION, seed="MMX59-D")
    _wait_for(table, mid, ME)
    assert _act(table, mid, "Domain Manifestation")["status"] == "COMMITTED"
    engine = _reload(tmp_path, mid)
    mine = [z for z in zones.typed_zones(engine) if z.owner_id == ME]
    assert mine, "the Domain is on the table"
    assert zones.moves_with_owner(mine[0]), "'The Domain moves with you'"
    assert (mine[0].center.x, mine[0].center.y) == (3, 6), "and it is centred on its owner to begin with"

    _wait_for(table, mid, ME)
    result, elsewhere = _commit_move(table, mid, (9, 6))
    assert result["status"] == "COMMITTED"
    reloaded = _reload(tmp_path, mid)
    zone = reloaded.state.zones[mine[0].zone_id]
    assert (zone.center.x, zone.center.y) == (elsewhere["x"], elsewhere["y"]), "the aura followed its owner"
    assert (reloaded.state.actors[ME].position.x, reloaded.state.actors[ME].position.y) == (elsewhere["x"], elsewhere["y"])
    assert (zone.center.x, zone.center.y) != (3, 6), "and is no longer on the square the Domain was made on"
    assert zone.affected_cells, "and still covers its squares"


# ------------------------------------------------------------------------------------------------ the plug-in stays inert
def test_a_character_without_the_domain_armament_is_untouched():
    doc = _doc(ARMAMENT, cl=10)
    doc["path_and_subpath"] = {"path_feature_record_ids": []}
    engine = Gate4ControllerEngine(ROOT, match_seed="MMX59-inert", typed_bundles=(compile_character(doc, actor_id=ME),),
                                   roster_setup={"primary_actor_ids": [ME, AN], "team_by_actor": {ME: "team:a", AN: "team:b"},
                                                 "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": 4, "y": 6}}})
    stranger = engine.state.actors[ME]
    qi_path.armament_guard(engine, stranger)
    qi_path.armament_moves(engine, "MOVEMENT_COMMITTED", {"actor_id": stranger.entity_id})
    qi_path.armament_ends(engine, "ENTITY_DEFEATED", {"actor_id": stranger.entity_id})
    assert not _shield(engine, stranger.entity_id)
    assert not any(action.display_name.startswith("Domain Armament")
                   for action in engine.action_catalog.values() if action.owner_id == ME)
    assert qi_path._control_range_ft(engine, stranger) == 30, "no Armament, the printed control range"
    assert qi_path._nearest_legal_point(engine, stranger, (3, 6)) is not None, "harmless with no Armament"


def test_one_owners_armament_never_inspects_or_ends_another_owners_shield():
    """No Armament anywhere else: the owner-scoped lookup returns nothing, so nothing is logged or removed."""
    engine = Gate4ControllerEngine(ROOT, match_seed="MMX59-none", typed_bundles=(compile_character(_doc(ARMAMENT, cl=10), actor_id=ME),),
                                   roster_setup={"primary_actor_ids": [ME, AN], "team_by_actor": {ME: "team:a", AN: "team:b"},
                                                 "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": 4, "y": 6}}})
    owner = engine.state.actors[ME]
    engine._add_modifier(engine.state.actors[AN], GUARD, "armor_class_vs_ranged", "ADD", 2, "SELF", expires_on="UNTIL_REMOVED")
    assert qi_path._shields(engine, owner) == [], "a shield this owner did not grant is not found"
    qi_path._unshield(engine, owner, "TEST")
    assert len(_shield(engine, AN)) == 1, "and is not removed by anything that owner does"

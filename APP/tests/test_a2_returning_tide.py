"""Returning Tide Body through the real Jujutsu resolutions.

The printed rule (authority/typed_mechanics/reviewed_final.d/a2_insights7.json,
printed text ea47369e...): "Once per scene: Immediately after you successfully
redirect or throw a hostile creature through a Jujutsu feature, regain 1
Stamina, move up to 5 feet without provoking Opportunity Attacks, and gain
Advantage on the next Grapple roll you make before the end of your next
turn."  Each test compiles a real Body Refining cultivator owning the Jujutsu
feature and the Insight, and runs the engine's own resolutions: the foe's
missed unarmed strike offers the real Redirect Force (its printed
creature-moving option is the redirect), and the real Throw (a failed save) is
the throw.

* the redirect and the throw each grant the printed follow-up: 1 Stamina, the
  offered 5-foot step (the shared rider_step question), and the owner's next
  Grapple or Shove rolled with the target's save in Disadvantage (the table's
  model of the owner's Advantage);
* the scene allowance is spent by the first one: a later round's redirect or
  throw grants nothing more;
* the Grapple Advantage is consumed by the first attempt and ends at the end
  of the owner's next turn;
* a fighter without the Insight keeps the plain resolutions.

The last section drives the same two triggers through the real
CombatService and the table (session execute_intent), so the printed
follow-up -- and the once-per-scene allowance and the Grapple Advantage
it leaves behind -- are read from cold-reloaded saved fights.
"""
from __future__ import annotations

import copy
import pytest

from combat.factory_compiler import compile_character
from combat.gate2_runtime_models import ReactionDecision
from combat.typed_executor import Context

from tests.test_riders_c7 import (FOE, ME, STAMINA, _foe_misses_me, _grapple, _typed_foe,
                                   end_turns_until, fight, payloads, script, sheet, turn, use)
from tests.auto_worker1_support import (LEFT, RIGHT, act, fight as service_fight, reload,
                                         resolve, turn as table_turn)

from combat.ext import returning_tide as RT

JUJUTSU = "tianxia.subpath.body.jujutsu.feature."


def _jujutsu(ids, *, insight=True):
    """A Body Refining cultivator with the Jujutsu features (and the Insight)."""
    document = sheet([JUJUTSU + k for k in ids])
    if insight:
        document["spheres_and_talents"]["cultivation_insight_record_ids"] = [RT.FEATURE]
    engine = fight(compile_character(document, actor_id=ME), foe=_typed_foe())
    return engine, engine.state.actors[ME], engine.state.actors[FOE]


def _recorder(engine, picks):
    """Answer every extension choice (the listed option ids for a reaction
    source ending with a key, else the first legal options), recording the
  questions the table asked."""
    seen = []

    def provider(request):
        spec = request.get("extension_choice")
        if spec is None:
            return None, None
        seen.append(request["reaction_source_id"])
        chosen = next((value for suffix, value in picks.items() if request["reaction_source_id"].endswith(suffix)),
                      spec["option_ids"][:max(1, spec["minimum_selections"])])
        base = {key: request[key] for key in ("checkpoint", "reactor_id", "reaction_source_id")}
        return ReactionDecision(**base, selection="DECLINE" if chosen is None else "USE", option_ids=tuple(chosen or [])), None
    engine.set_reaction_provider(provider)
    return seen


def test_a_redirect_force_push_gains_the_printed_follow_up():
    """The redirect: 1 Stamina, the offered step, and the next Grapple's Advantage."""
    engine, me, foe = _jujutsu(["redirect_force"])
    assert RT.row_of(engine, ME, RT.BLOCK, RT.KIND) is not None
    me.resources[STAMINA] = 55
    seen = _recorder(engine, {"redirect_force": ["push"]})
    _foe_misses_me(engine, me)
    assert me.resources[STAMINA] == 56
    assert any(c.condition_id == RT.TIDE_EDGE for c in me.conditions.values())
    assert any(source.endswith("rider_step") for source in seen), seen
    turn(engine, ME)
    events = use(engine, "Grapple", target=FOE)
    assert len(payloads(events, "SAVE_ROLLED")[0]["dice"]) == 2  # its save against your Grapple has Disadvantage
    assert not any(c.condition_id == RT.TIDE_EDGE for c in me.conditions.values())


def test_a_failed_throw_gains_the_printed_follow_up():
    """The throw: the same follow-up after the real Throw's failed save."""
    engine, me, foe = _jujutsu(["throw"])
    me.resources[STAMINA] = 55
    seen = _recorder(engine, {})
    assert _grapple(engine, FOE)
    script(engine, [1] * 40)  # the foe's Strength or Dexterity save fails
    me.bonus_action_available = True
    start = foe.position
    use(engine, "Throw", target=FOE)
    assert me.resources[STAMINA] == 54  # the Throw's 2 Stamina, then the printed regain of 1
    assert any(c.condition_id == RT.TIDE_EDGE for c in me.conditions.values())
    assert any(source.endswith("rider_step") for source in seen), seen
    assert any(c.condition_id.endswith("prone") for c in foe.conditions.values())
    assert not any(c.condition_id.endswith(".grappled") for c in foe.conditions.values())
    assert engine.grid.distance_ft(foe.position, start) > 5  # thrown to a chosen open space


def test_the_scene_allowance_is_spent_by_the_first_redirect():
    """A later round's redirect gains nothing more: once per scene."""
    engine, me, foe = _jujutsu(["redirect_force"])
    me.resources[STAMINA] = 55
    _recorder(engine, {"redirect_force": ["push"]})
    _foe_misses_me(engine, me)
    assert me.resources[STAMINA] == 56
    turn(engine, ME)
    use(engine, "Grapple", target=FOE)  # the Advantage is spent on that attempt
    assert not any(c.condition_id == RT.TIDE_EDGE for c in me.conditions.values())
    turn(engine, ME)  # the next round
    _foe_misses_me(engine, me)
    assert me.resources[STAMINA] == 56
    assert not any(c.condition_id == RT.TIDE_EDGE for c in me.conditions.values())


def test_the_grapple_advantage_ends_at_the_end_of_the_next_turn():
    """The Advantage outlives the trigger's round and ends with the owner's next turn."""
    engine, me, foe = _jujutsu(["redirect_force"])
    _recorder(engine, {"redirect_force": ["push"]})
    _foe_misses_me(engine, me)
    assert any(c.condition_id == RT.TIDE_EDGE for c in me.conditions.values())
    end_turns_until(engine, ME)  # the owner's next turn: the Advantage is still live
    assert any(c.condition_id == RT.TIDE_EDGE for c in me.conditions.values())
    end_turns_until(engine, FOE)  # past the end of that turn: it is gone
    assert not any(c.condition_id == RT.TIDE_EDGE for c in me.conditions.values())
    end_turns_until(engine, ME)  # the owner's turn again
    events = use(engine, "Grapple", target=FOE)
    assert len(payloads(events, "SAVE_ROLLED")[0]["dice"]) == 1


def test_a_fighter_without_the_insight_gets_nothing():
    """The seam is default-inert: the plain resolutions, with no follow-up."""
    engine, me, foe = _jujutsu(["redirect_force"], insight=False)
    assert RT.row_of(engine, ME, RT.BLOCK, RT.KIND) is None
    me.resources[STAMINA] = 55
    seen = _recorder(engine, {"redirect_force": ["push"]})
    _foe_misses_me(engine, me)
    assert me.resources[STAMINA] == 55
    assert not any(c.condition_id == RT.TIDE_EDGE for c in me.conditions.values())
    assert not any(source.endswith("rider_step") for source in seen)
    turn(engine, ME)
    events = use(engine, "Grapple", target=FOE)
    assert len(payloads(events, "SAVE_ROLLED")[0]["dice"]) == 1


# --------------------------------------------------------------------------- the table
# The same two triggers through the real CombatService and the table
# (session execute_intent), each assertion read from a cold-reloaded
# saved fight: the printed follow-up, its once-per-scene allowance and
# the Grapple Advantage it leaves behind all survive a table commit and
# reload.


def table_fight(tmp_path, *, insight=True, grapple_ready=False, grapple_probe=False,
                right_team="team:opponents", nonhostile_miss=False, rooted_rim=False):
    """A Jujutsu duel through the real service: the left fighter owns the
    Jujutsu features (and the Insight), its AC is beyond the foe's strike
    (so the printed trigger -- a missed melee attack against the owner --
    fires), and its Path's Stamina pool starts with room for the printed
    regain.  ``grapple_ready`` also arms the real Grapple: the owner's
    Strength lifts the Grapple's save DC past the foe's save, so the foe
    is Grappled and the real Throw can follow."""
    def sheet_edit(doc, aid):
        fields = doc["spheres_and_talents"]
        fields["automatic_sphere_component_record_ids"] = []
        fields["cultivation_insight_record_ids"] = [RT.FEATURE] if insight else []
        doc["path_and_subpath"] = {"path_feature_record_ids":
                                    [JUJUTSU + k for k in ("redirect_force", "throw")]}
        stats = doc["ability_scores_and_statistics"]
        stats["primary_resource"]["definitions"] = [{"name": "Stamina", "max": 100}]
        if aid == LEFT:
            stats["armor_class"]["base_value"] = 99
            if grapple_ready:
                stats["abilities"] = [{**row, "score": 30, "modifier": 10}
                                       if row["ability"] == "STR" else row
                                       for row in stats["abilities"]]
        elif grapple_ready:
            stats["abilities"] = [{**row, "score": 1, "modifier": -5}
                                   for row in stats["abilities"]]

    def bundle_edit(bundle):
        if bundle["actor_id"] != LEFT:
            return
        if grapple_probe:
            probe = copy.deepcopy(next(a for a in bundle["action_catalog"] if a["display_name"] == "Grapple"))
            probe["source_definition_id"] += ".ins7d_probe"
            probe["display_name"] = "Grapple after Shove"
            probe["economy"] = "NONE"
            probe["parameters"]["free_primary"] = True
            bundle["action_catalog"].append(probe)
            bundle["actor_template"]["action_ids"].append(probe["source_definition_id"])
        for row in bundle["actor_template"]["resources"]:
            if row["resource_id"] == RT.STAMINA:
                row["initial"] = 55  # room for the printed regain

    # A synthetic melee attack permits any creature as its target so relation
    # filtering in the attack menu cannot hide the nonhostile miss trigger.
    # Redirect Force and Returning Tide still resolve through their real hooks.
    # An uninvolved hostile witness keeps combat active after a nonhostile pair
    # ends its turn; it neither attacks nor supplies the trigger.
    cause = [{"type": "attack", "attack_kind": "unarmed", "on_hit": [], "on_miss": []}] if nonhostile_miss else ()
    # Commit the existing defense through a setup action; the real forced-distance
    # provider then reduces the push by 10 feet, until the owner's next turn.
    prepare = [{"type": "condition", "condition": "rooted_rim", "applies_to": "target",
                "expires_on": "START_OF_SOURCE_NEXT_TURN"}] if rooted_rim else ()
    return service_fight(tmp_path, sheet_edit=sheet_edit, bundle_edit=bundle_edit,
                         prepare=prepare,
                         ally=False, right_team=right_team, cause=cause, cause_target="ANY_CREATURE",
                         extra_witness=nonhostile_miss, witness_team="team:opponents",
                         witness_position={"x": 2, "y": 5})


@pytest.mark.parametrize("ai", [False, True])
def test_returning_tide_does_not_benefit_or_consume_on_shove(tmp_path, ai):
    """The printed next Grapple survives a Shove, for player and AI service intents."""
    from tests.auto_worker1_support import action_sender
    combat, table, mid = table_fight(tmp_path, grapple_ready=True, grapple_probe=True)
    table_turn(table, mid, RIGHT)
    send = action_sender(combat, table, mid, "Unarmed Strike", ai=ai, target_id=LEFT)
    _, prompts = resolve(send, {"choice:needle.redirect_force": ["push"],
                               "choice:needle.redirect_force_push": ["cell:4,5"],
                               "choice:needle.rider_step": []})
    assert any(p["context"]["reaction_source_id"] == "choice:needle.rider_step" for p in prompts)
    combat.set_controller_mode(mid, actor_id=RIGHT, controller_mode="MANUAL")
    engine = reload(combat, mid)
    assert any(c.condition_id == RT.TIDE_EDGE for c in engine.state.actors[LEFT].conditions.values())
    table_turn(table, mid, LEFT)
    before = len(reload(combat, mid).events)
    send = action_sender(combat, table, mid, "Shove: Prone", ai=ai, target_id=RIGHT)
    resolve(send)
    engine = reload(combat, mid)
    assert any(c.condition_id == RT.TIDE_EDGE for c in engine.state.actors[LEFT].conditions.values())
    saves = [e for e in engine.events[before:] if e.event_type == "SAVE_ROLLED" and e.actor_id == RIGHT]
    assert saves and len(saves[-1].payload["dice"]) == 1
    combat.set_controller_mode(mid, actor_id=LEFT, controller_mode="MANUAL")
    before = len(reload(combat, mid).events)
    through_the_table(table, mid, "Grapple after Shove")
    engine = reload(combat, mid)
    assert not any(c.condition_id == RT.TIDE_EDGE for c in engine.state.actors[LEFT].conditions.values())
    saves = [e for e in engine.events[before:] if e.event_type == "SAVE_ROLLED" and e.actor_id == RIGHT]
    assert saves and len(saves[-1].payload["dice"]) == 2


def through_the_table(table, mid, action, picks=None, target_id=RIGHT):
    """A fighter uses the named table action at ``target_id``,
    answering every question the run of resolutions asks."""
    return resolve(lambda answers: act(table, mid, action, answers, target_id=target_id), picks)


def test_the_tables_redirect_sets_the_printed_follow_up_off(tmp_path):
    """The foe's missed strike offers the real Redirect Force; its push
    sets the Insight off: 1 Stamina, the offered 5-foot step, and the
    Grapple Advantage -- all of it in the cold-reloaded fight."""
    combat, table, mid = table_fight(tmp_path)
    engine = reload(combat, mid)
    assert RT.row_of(engine, LEFT, RT.BLOCK, RT.KIND) is not None
    table_turn(table, mid, RIGHT)
    result, prompts = through_the_table(table, mid, "Unarmed Strike",
                                        {"choice:needle.redirect_force": ["push"],
                                         "choice:needle.rider_step": ["cell:2,6"]},
                                        target_id=LEFT)
    assert result["status"] == "COMMITTED", result
    asked = {p["context"]["reaction_source_id"] for p in prompts}
    assert "choice:needle.redirect_force" in asked  # the Reaction itself
    assert "choice:needle.rider_step" in asked  # the printed step
    step = next(p for p in prompts if p["context"]["reaction_source_id"] == "choice:needle.rider_step")
    # Plain words for a player who knows only basic D&D: the ability,
    # the action that triggered it, the creature it affects, the
    # distance, that nothing is spent, and that no Opportunity Attack
    # is provoked.
    moment = step["moment"]
    assert "Returning Tide Body" in moment
    assert "Redirect Force" in moment
    assert "Visitor" in moment
    assert "5 feet" in moment
    assert "No extra action, resource or ordinary movement is spent" in moment
    assert "No opportunity attacks are provoked" in moment
    engine = reload(combat, mid)
    me, foe = engine.state.actors[LEFT], engine.state.actors[RIGHT]
    assert me.resources[RT.STAMINA] == 56  # the printed regain of 1 Stamina
    assert any(c.condition_id == RT.TIDE_EDGE for c in me.conditions.values())
    assert (foe.position.x, foe.position.y) != (4, 6)  # pushed 5 feet
    assert (me.position.x, me.position.y) == (2, 6)  # the printed step
    assert me.turn_flags.get(RT.USED) is not None


@pytest.mark.parametrize("ai", [False, True])
def test_fully_prevented_redirect_preserves_returning_tide_after_reload(tmp_path, ai):
    """A stopped push grants nothing and leaves Tide available for a later real push."""
    from combat.ext.shield_riders import RIM
    from tests.auto_worker1_support import action_sender

    combat, table, mid = table_fight(tmp_path, rooted_rim=True)
    through_the_table(table, mid, "Prepare")
    table_turn(table, mid, RIGHT)
    before = reload(combat, mid)
    assert any(c.condition_id == RIM for c in before.state.actors[RIGHT].conditions.values())
    owner_before = before.state.actors[LEFT]
    first_event = len(before.events)
    send = action_sender(combat, table, mid, "Unarmed Strike", ai=ai, target_id=LEFT)
    result, prompts = resolve(send, {"choice:needle.redirect_force": ["push"],
                                    "choice:needle.redirect_force_push": ["cell:4,5"]})
    assert result["status"] == "COMMITTED", result
    persisted = reload(combat, mid)
    owner, creature = persisted.state.actors[LEFT], persisted.state.actors[RIGHT]
    # Assert against the committed, cold-reloaded fight, including the Reaction
    # payment that proves Redirect Force actually ran (rather than being declined).
    assert not owner.reaction_available
    assert owner.turn_flags["_round_redirect_force"] == persisted.state.round_number
    assert creature.position == before.state.actors[RIGHT].position
    assert not any(e.event_type == "MOVEMENT_COMMITTED" and e.actor_id == RIGHT
                   and e.source_definition_id == JUJUTSU + "redirect_force"
                   for e in persisted.events[first_event:])
    assert owner.resources == owner_before.resources
    assert owner.turn_flags.get(RT.USED) == owner_before.turn_flags.get(RT.USED)
    assert not any(c.condition_id == RT.TIDE_EDGE for c in owner.conditions.values())
    assert owner.position == owner_before.position
    asked = {p["context"]["reaction_source_id"] for p in prompts}
    assert {"choice:needle.redirect_force", "choice:needle.redirect_force_push"} <= asked
    assert "choice:needle.rider_step" not in asked
    assert not any(e.source_definition_id in {RT.FEATURE, "passive:" + RT.FEATURE}
                   for e in persisted.events[first_event:])
    session = combat._load_session(mid)
    assert session.verify()["status"] == "PASS"
    assert session.mechanical.replay()["status"] == "PASS"

    # Once the defense expires, the next round's successful push still grants
    # the scene's one follow-up; a prevented attempt must not waste it.
    combat.set_controller_mode(mid, actor_id=RIGHT, controller_mode="MANUAL")
    table_turn(table, mid, LEFT)
    table_turn(table, mid, RIGHT)
    assert not any(c.condition_id == RIM for c in reload(combat, mid).state.actors[RIGHT].conditions.values())
    send = action_sender(combat, table, mid, "Unarmed Strike", ai=ai, target_id=LEFT)
    _, prompts = resolve(send, {"choice:needle.redirect_force": ["push"],
                               "choice:needle.redirect_force_push": ["cell:4,5"],
                               "choice:needle.rider_step": []})
    persisted = reload(combat, mid)
    owner = persisted.state.actors[LEFT]
    assert persisted.state.actors[RIGHT].position != creature.position
    assert owner.resources[RT.STAMINA] == owner_before.resources[RT.STAMINA] + 1
    assert owner.turn_flags[RT.USED] == 1
    assert any(c.condition_id == RT.TIDE_EDGE for c in owner.conditions.values())
    assert "choice:needle.rider_step" in {p["context"]["reaction_source_id"] for p in prompts}
    session = combat._load_session(mid)
    assert session.verify()["status"] == "PASS"
    assert session.mechanical.replay()["status"] == "PASS"


def foe_closes_in(combat, table, mid):
    """The foe walks back into the owner's reach: the round's
    push and printed step left it 10 feet away, and the
    printed trigger is a *melee* attack that misses the owner."""
    state = table.state(mid)
    menu = state["menu"]
    engine = combat._load_session(mid).engine
    owner = engine.state.actors[LEFT]
    candidate = next(c for c in engine.legal_candidates()
                     if c.source_definition_id == "system:combat.movement"
                     and c.actor_id == RIGHT
                     and engine.grid.distance_ft(c.destination, owner.position) <= 5)
    result = table.act(mid, candidate.candidate_id, menu["decision_id"],
                       menu["state_version"], state["last_sequence"], [])
    while result["status"] == "REACTION_REQUIRED":
        prompt = result["reaction"]
        answers = [{**prompt["context"], "selection": "DECLINE", "option_ids": []}]
        result = table.act(mid, prompt["context"].get("candidate_id", candidate.candidate_id),
                           menu["decision_id"], menu["state_version"],
                           state["last_sequence"], answers)
    assert result["status"] == "COMMITTED", result


def test_the_scene_allowance_survives_a_cold_reload(tmp_path):
    """Once per scene: a cold-reloaded later redirect gains nothing more."""
    combat, table, mid = table_fight(tmp_path)
    table_turn(table, mid, RIGHT)
    through_the_table(table, mid, "Unarmed Strike",
                      {"choice:needle.redirect_force": ["push"],
                       "choice:needle.rider_step": ["cell:2,6"]},
                      target_id=LEFT)
    engine = reload(combat, mid)
    assert engine.state.actors[LEFT].resources[RT.STAMINA] == 56
    assert any(c.condition_id == RT.TIDE_EDGE for c in engine.state.actors[LEFT].conditions.values())
    # A later round: the foe walks back into reach, its strike
    # misses again and Redirect Force answers it again (it is
    # once per round), but the scene's allowance is spent, so
    # no Stamina, no step and no edge.
    table_turn(table, mid, LEFT)
    table_turn(table, mid, RIGHT)
    foe_closes_in(combat, table, mid)
    result, prompts = through_the_table(table, mid, "Unarmed Strike",
                                        {"choice:needle.redirect_force": ["push"]},
                                        target_id=LEFT)
    assert result["status"] == "COMMITTED", result
    asked = {p["context"]["reaction_source_id"] for p in prompts}
    assert "choice:needle.redirect_force" in asked
    assert "choice:needle.rider_step" not in asked
    engine = reload(combat, mid)
    assert engine.state.actors[LEFT].resources[RT.STAMINA] == 56
    assert not any(c.condition_id == RT.TIDE_EDGE
                    for c in engine.state.actors[LEFT].conditions.values())


def test_same_team_enemy_triggers_returning_tide_through_the_table(tmp_path):
    """An explicit enemy relation overrides same-team membership and persists with the benefit."""
    combat, table, mid = table_fight(tmp_path, right_team="team:factory")
    combat.change_relations(mid, change={"kind": "ACTOR_RELATION", "subject": LEFT,
        "other": RIGHT, "relation": "ENEMY"},
        expected_state_version=combat._load_session(mid).engine.state.state_version)
    table_turn(table, mid, RIGHT)
    result, prompts = through_the_table(table, mid, "Unarmed Strike",
        {"choice:needle.redirect_force": ["push"]}, target_id=LEFT)
    assert result["status"] == "COMMITTED", result
    assert "choice:needle.rider_step" in {p["context"]["reaction_source_id"] for p in prompts}
    engine = reload(combat, mid)
    owner = engine.state.actors[LEFT]
    assert owner.resources[RT.STAMINA] == 56
    assert owner.turn_flags[RT.USED] == 1
    assert any(c.condition_id == RT.TIDE_EDGE for c in owner.conditions.values())
    session = combat._load_session(mid)
    assert session.verify()["status"] == "PASS"
    assert session.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("relation_value", ["ALLY", "NEUTRAL"])
def test_returning_tide_does_not_spend_allowance_on_nonhostile_relation(tmp_path, relation_value):
    """Inspect the invoked engine: a nonhostile trigger changes nothing at all."""
    combat, _, mid = table_fight(tmp_path)
    combat.change_relations(mid, change={"kind": "ACTOR_RELATION", "subject": LEFT,
        "other": RIGHT, "relation": relation_value},
        expected_state_version=combat._load_session(mid).engine.state.state_version)
    engine = reload(combat, mid)
    owner, creature = engine.state.actors[LEFT], engine.state.actors[RIGHT]
    assert RT.row_of(engine, LEFT, RT.BLOCK, RT.KIND) is not None
    assert owner.resources[RT.STAMINA] == 55
    assert RT.USED not in owner.turn_flags
    action = next(a for a in engine.action_catalog.values()
                  if a.owner_id == LEFT and a.display_name == "Throw")
    ctx = Context(engine, owner, action, None, action.parameters["typed"], [creature], creature)
    asked = _recorder(engine, {"rider_step": None})
    resources = copy.deepcopy(owner.resources)
    flags = copy.deepcopy(owner.turn_flags)
    conditions = copy.deepcopy(owner.conditions)
    events = copy.deepcopy(engine.events)
    position = owner.position

    RT.returning_tide(engine, owner, creature, JUJUTSU + "throw", ctx)

    # No transaction committed this direct invocation. A second cold reload
    # would inspect the original save and hide erroneous provider mutations.
    assert owner.resources == resources
    assert owner.turn_flags == flags
    assert owner.conditions == conditions
    assert engine.events == events
    assert owner.position == position
    assert not asked


@pytest.mark.parametrize("relation_value", ["ALLY", "NEUTRAL"])
def test_nonhostile_redirect_commits_without_returning_tide_and_reloads(tmp_path, relation_value):
    """A real Redirect Force commits its push but no nonhostile Tide benefit."""
    combat, table, mid = table_fight(tmp_path, right_team="team:factory", nonhostile_miss=True)
    combat.change_relations(mid, change={"kind": "ACTOR_RELATION", "subject": LEFT,
        "other": RIGHT, "relation": relation_value},
        expected_state_version=combat._load_session(mid).engine.state.state_version)
    table_turn(table, mid, RIGHT)
    before = reload(combat, mid)
    stamina = before.state.actors[LEFT].resources[RT.STAMINA]
    first_event = len(before.events)
    result, prompts = through_the_table(table, mid, "Cause",
        {"choice:needle.redirect_force": ["push"]}, target_id=LEFT)
    assert result["status"] == "COMMITTED", result
    asked = {p["context"]["reaction_source_id"] for p in prompts}
    assert "choice:needle.redirect_force" in asked
    assert "choice:needle.rider_step" not in asked
    persisted = reload(combat, mid)
    owner, creature = persisted.state.actors[LEFT], persisted.state.actors[RIGHT]
    assert owner.resources[RT.STAMINA] == stamina
    assert RT.USED not in owner.turn_flags
    assert not any(c.condition_id == RT.TIDE_EDGE for c in owner.conditions.values())
    assert not owner.reaction_available  # the real Redirect Force spent its Reaction
    assert creature.position != before.state.actors[RIGHT].position  # its actual push committed
    assert owner.position == before.state.actors[LEFT].position  # no follow-up step
    assert not any(e.source_definition_id in {RT.FEATURE, "passive:" + RT.FEATURE}
                   for e in persisted.events[first_event:])
    session = combat._load_session(mid)
    assert session.verify()["status"] == "PASS"
    assert session.mechanical.replay()["status"] == "PASS"


def test_the_grapple_edge_survives_a_cold_reload_and_ends(tmp_path):
    """The Advantage rides the target's save: it survives a cold reload,
    lives through the owner's next turn, and ends when that turn ends."""
    combat, table, mid = table_fight(tmp_path)
    table_turn(table, mid, RIGHT)
    through_the_table(table, mid, "Unarmed Strike", {"choice:needle.redirect_force": ["push"]},
                      target_id=LEFT)
    engine = reload(combat, mid)
    assert any(c.condition_id == RT.TIDE_EDGE for c in engine.state.actors[LEFT].conditions.values())
    # The owner's next turn: the edge is still live through it...
    table_turn(table, mid, LEFT)
    engine = reload(combat, mid)
    assert any(c.condition_id == RT.TIDE_EDGE for c in engine.state.actors[LEFT].conditions.values())
    # ...and it is gone once that turn has ended.
    resolve(lambda answers: act(table, mid, "end", answers))
    engine = reload(combat, mid)
    assert not any(c.condition_id == RT.TIDE_EDGE for c in engine.state.actors[LEFT].conditions.values())


def test_the_tables_throw_sets_the_same_follow_up_off(tmp_path):
    """The real Throw (the foe's failed save) is the throw: the same
    follow-up, in the cold-reloaded fight."""
    combat, table, mid = table_fight(tmp_path, grapple_ready=True)
    table_turn(table, mid, LEFT)
    result, prompts = through_the_table(table, mid, "Grapple")
    assert result["status"] == "COMMITTED", result
    engine = reload(combat, mid)
    assert any(c.condition_id.endswith("grappled") for c in engine.state.actors[RIGHT].conditions.values())
    result, prompts = through_the_table(table, mid, "Throw")
    assert result["status"] == "COMMITTED", result
    asked = {p["context"]["reaction_source_id"] for p in prompts}
    assert "choice:needle.rider_step" in asked
    engine = reload(combat, mid)
    me, foe = engine.state.actors[LEFT], engine.state.actors[RIGHT]
    assert me.resources[RT.STAMINA] == 54  # the Throw's 2 Stamina, then the printed regain of 1
    assert any(c.condition_id == RT.TIDE_EDGE for c in me.conditions.values())
    assert any(c.condition_id.endswith("prone") for c in foe.conditions.values())
    assert not any(c.condition_id.endswith("grappled") for c in foe.conditions.values())
    assert (foe.position.x, foe.position.y) != (4, 6)  # thrown to a chosen space


@pytest.mark.parametrize("trigger", ["redirect", "throw"])
def test_follow_up_error_rolls_back_resolution_and_initial_benefits(tmp_path, monkeypatch, trigger):
    from combat import typed_executor
    combat, table, mid = table_fight(tmp_path, grapple_ready=trigger == "throw")
    if trigger == "throw":
        table_turn(table, mid, LEFT)
        through_the_table(table, mid, "Grapple")
    else:
        table_turn(table, mid, RIGHT)
    before = reload(combat, mid).state.model_dump(mode="json")
    original = typed_executor.run_effects
    observed = []
    def fail_after_gain(ctx, effects):
        if (ctx.engine._gate4_reaction_provider is None
                and any(e.get("type") == "rider_step" and e.get("label") == "Returning Tide Body" for e in effects)):
            assert ctx.actor.turn_flags[RT.USED] == 1
            observed.append(ctx.actor.resources[RT.STAMINA])
            raise ValueError("INS7D injected follow-up failure")
        return original(ctx, effects)
    monkeypatch.setattr(typed_executor, "run_effects", fail_after_gain)
    try:
        result, _ = through_the_table(table, mid, "Throw" if trigger == "throw" else "Unarmed Strike",
            {"choice:needle.redirect_force": ["push"]}, target_id=RIGHT if trigger == "throw" else LEFT)
    except Exception as exc:
        assert "INS7D injected follow-up failure" in str(getattr(exc, "diagnostic", exc))
    else:
        assert result["status"] != "COMMITTED", result
    assert observed
    assert reload(combat, mid).state.model_dump(mode="json") == before
    session = combat._load_session(mid)
    assert session.verify()["status"] == "PASS"
    assert session.mechanical.replay()["status"] == "PASS"


def test_a_fighter_without_the_insight_gets_nothing_on_the_table(tmp_path):
    """The seam is default-inert on the table too: Redirect Force still
    answers the miss, with no follow-up."""
    combat, table, mid = table_fight(tmp_path, insight=False)
    engine = reload(combat, mid)
    assert RT.row_of(engine, LEFT, RT.BLOCK, RT.KIND) is None
    table_turn(table, mid, RIGHT)
    result, prompts = through_the_table(table, mid, "Unarmed Strike",
                                        {"choice:needle.redirect_force": ["push"]},
                                        target_id=LEFT)
    assert result["status"] == "COMMITTED", result
    asked = {p["context"]["reaction_source_id"] for p in prompts}
    assert "choice:needle.redirect_force" in asked  # the Reaction itself still runs
    assert "choice:needle.rider_step" not in asked  # the Insight's follow-up is gone
    engine = reload(combat, mid)
    me = engine.state.actors[LEFT]
    assert me.resources[RT.STAMINA] == 55  # nothing regained
    assert (me.position.x, me.position.y) == (3, 6)  # no step was offered
    assert not any(c.condition_id == RT.TIDE_EDGE for c in me.conditions.values())
    assert me.turn_flags.get(RT.USED) is None

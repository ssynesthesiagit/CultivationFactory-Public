"""Silk-Reeling Foundation through sealed CombatService fights and reload.

The owner's own turn drives the real Draw the Line action through the table
(execute_intent), so the printed trigger -- "when you use Draw the Line" --
fires from the engine's own typed resolution, hit or miss. Every assertion
reads a cold-reloaded saved fight.

The printed rule has four parts, each with its own regression:

* the step is offered after Draw the Line, in plain words naming the ability,
  the triggering action and the creature it affects, and it moves the owner;
* the step provokes no Opportunity Attack from the target of the feature
  (an ordinary walk away from the same foe does provoke one, so the
  suppression is not vacuous);
* the once-per-round allowance is spent by a taken step and kept by a
  declined one, and it returns in a later round. A second use of the feature
  inside one turn is a synthetic action carrying the same typed Thread source
  id (the authority id ``is_thread_attack`` reads), because the table allows
  one attack action per turn and the printed allowance is per *round*;
* a fighter without the Insight is never asked.
"""
import copy
from tests.auto_worker1_support import LEFT, RIGHT, act, fight as service_fight, reload, resolve, turn
from combat.ext.passive_rows import row_of

FEATURE = "insight.silk-reeling-foundation"
ONCE = "once_per_round:thread_silk_reeling_foundation"

THREAD = "THREAD_BASE_DRAW_THE_LINE"
RIDER = "choice:needle.rider_step"
OPPORTUNITY = "reaction:typed.opportunity_attack"
# The owner stands at (3,6) and the foe at (4,6): (2,6) is one square to the
# owner's left, leaving the foe's 5-foot reach, so a step there is the printed
# "move 5 feet ... without provoking Opportunity Attacks from the target".
AWAY = "cell:2,6"
# A second use of the feature inside one turn: the economy is NONE, so it stays
# available after the owner's attack action, and its typed source id is the
# Thread talent's own authority id -- exactly what a Thread ability carries.
STRIKE = {"type": "damage", "applies_to": "target", "flat": 1, "damage_types": ["force"]}


def thread_fight(tmp_path, *, insight=True):
    """A Thread-sphere duel whose left fighter holds (or lacks) the Insight."""
    def sheet_edit(doc, aid):
        fields = doc["spheres_and_talents"]
        fields["sphere_record_ids"] = ["tianxia.sphere.thread"]
        fields["learned_talent_record_ids"] = [THREAD]
        fields["automatic_sphere_component_record_ids"] = []
        fields["cultivation_insight_record_ids"] = [FEATURE] if insight else []
    def repeat_feature(bundle):
        # Repeat the actual compiled feature without a second action payment.
        # Its owned named modifiers must be retained; an effect inserted after
        # compilation cannot stand in for a compiled Thread activation.
        if bundle["actor_id"] != LEFT:
            return
        feature = next(a for a in bundle["action_catalog"] if a["display_name"] == "Draw the Line: Pull")
        probe = next(a for a in bundle["action_catalog"] if a["display_name"] == "Prepare")
        probe["parameters"] = {**copy.deepcopy(feature["parameters"]), "free_primary": True}
    return service_fight(tmp_path, sheet_edit=sheet_edit, ally=False,
                         prepare=[STRIKE], prepare_source=THREAD,
                         prepare_target="HOSTILE_ENTITY", bundle_edit=repeat_feature)


def use_draw_the_line(table, mid, picks=None):
    """The owner uses the real Draw the Line: Pull against the foe."""
    return resolve(lambda answers: act(table, mid, "Draw the Line: Pull", answers, target_id=RIGHT), picks)


def use_the_second_thread_ability(table, mid, picks=None):
    """The owner uses the other Thread ability the fixture gives this turn."""
    return resolve(lambda answers: act(table, mid, "Prepare", answers, target_id=RIGHT), picks)


def asked(prompts, source=RIDER):
    """The questions of one source a run of table answers put on the table."""
    return [p for p in prompts if (p.get("context") or {}).get("reaction_source_id") == source]


def test_draw_the_line_offers_the_step_that_moves_the_owner(tmp_path):
    combat, table, mid = thread_fight(tmp_path)
    engine = reload(combat, mid)
    assert next((r for r in engine.typed_passive_rows.get(LEFT, []) if r.get("block") == "thread_foundation_owner"), None) is not None
    turn(table, mid, LEFT)
    result, prompts = use_draw_the_line(table, mid, {RIDER: [AWAY]})
    assert result["status"] == "COMMITTED", result
    step = asked(prompts)
    assert len(step) == 1
    # Plain words for a player who knows only basic D&D: the ability, the action
    # that triggered it, the creature it affects, the distance, the cost, and
    # whose Opportunity Attack the step does not provoke.
    moment = step[0]["moment"]
    assert "Silk-Reeling Foundation" in moment
    assert "Draw the Line: Pull" in moment
    assert "Visitor" in moment
    assert "5 feet" in moment and "No extra action, resource or ordinary movement is spent" in moment
    assert "Visitor cannot make an Opportunity Attack against you because of this step" in moment
    engine = reload(combat, mid)
    owner = engine.state.actors[LEFT]
    assert (owner.position.x, owner.position.y) == (2, 6)
    assert owner.turn_flags.get(ONCE) == engine.state.round_number
    # The target's Opportunity Attack is suppressed for this step.
    assert not asked(prompts, OPPORTUNITY)
    assert not [event for event in engine.events if "OPPORTUNITY" in event.event_type]


def test_an_ordinary_walk_away_from_the_same_foe_provokes_its_attack(tmp_path):
    """The suppression above is real: an ordinary move out of the foe's reach asks for its attack."""
    combat, table, mid = thread_fight(tmp_path)
    turn(table, mid, LEFT)
    state = table.state(mid)
    menu = state["menu"]
    engine = combat._load_session(mid).engine
    walk = next(candidate.candidate_id for candidate in engine.legal_candidates()
                if candidate.destination is not None
                and (candidate.destination.x, candidate.destination.y) == (2, 6)
                and candidate.metadata.get("movement_mode") != "fly")
    result = table.act(mid, walk, menu["decision_id"], menu["state_version"], state["last_sequence"], [])
    prompts = []
    while result["status"] == "REACTION_REQUIRED":
        reaction = result["reaction"]
        prompts.append(reaction)
        answers = [{**reaction["context"], "selection": "DECLINE", "option_ids": []}]
        result = table.act(mid, reaction["context"].get("candidate_id", walk),
                           menu["decision_id"], menu["state_version"], state["last_sequence"], answers)
    assert result["status"] == "COMMITTED", result
    assert asked(prompts, OPPORTUNITY), "the fixture's ordinary walk must provoke the foe's attack"


def test_a_second_use_in_the_same_round_is_not_offered_the_step(tmp_path):
    combat, table, mid = thread_fight(tmp_path)
    turn(table, mid, LEFT)
    _, prompts = use_draw_the_line(table, mid, {RIDER: [AWAY]})
    assert asked(prompts), "the first use of the feature offers the step"
    # Still the owner's turn: the allowance is spent, so the second Thread
    # ability resolves with no step question at all.
    result, prompts = use_the_second_thread_ability(table, mid)
    assert result["status"] == "COMMITTED", result
    assert not asked(prompts)
    engine = reload(combat, mid)
    assert (engine.state.actors[LEFT].position.x, engine.state.actors[LEFT].position.y) == (2, 6)


def test_the_allowance_returns_in_a_later_round(tmp_path):
    combat, table, mid = thread_fight(tmp_path)
    turn(table, mid, LEFT)
    use_draw_the_line(table, mid, {RIDER: [AWAY]})
    assert reload(combat, mid).state.actors[LEFT].turn_flags.get(ONCE) is not None
    # Every other fighter takes a turn, so a new round begins.
    turn(table, mid, RIGHT)
    turn(table, mid, LEFT)
    result, prompts = resolve(
        lambda answers: act(table, mid, "Draw the Line: Guide", answers, target_id=RIGHT),
        {RIDER: [AWAY]})
    assert result["status"] == "COMMITTED", result
    assert asked(prompts), "a later round offers the step again"


def test_declining_the_step_keeps_the_rounds_allowance(tmp_path):
    """The allowance is spent by a step that is taken, not by the question itself."""
    combat, table, mid = thread_fight(tmp_path)
    turn(table, mid, LEFT)
    result, prompts = use_draw_the_line(table, mid, {RIDER: []})  # decline
    assert result["status"] == "COMMITTED", result
    engine = reload(combat, mid)
    assert engine.state.actors[LEFT].turn_flags.get(ONCE) is None
    assert (engine.state.actors[LEFT].position.x, engine.state.actors[LEFT].position.y) == (3, 6)
    # The same round's second use of the feature is still offered the step.
    result, prompts = use_the_second_thread_ability(table, mid, {RIDER: [AWAY]})
    assert result["status"] == "COMMITTED", result
    assert asked(prompts)
    engine = reload(combat, mid)
    assert engine.state.actors[LEFT].turn_flags.get(ONCE) == engine.state.round_number
    assert (engine.state.actors[LEFT].position.x, engine.state.actors[LEFT].position.y) == (2, 6)


def test_a_fighter_without_the_insight_is_never_asked(tmp_path):
    combat, table, mid = thread_fight(tmp_path, insight=False)
    engine = reload(combat, mid)
    assert next((r for r in engine.typed_passive_rows.get(LEFT, []) if r.get("block") == "thread_foundation_owner"), None) is None
    turn(table, mid, LEFT)
    result, prompts = use_draw_the_line(table, mid)
    assert result["status"] == "COMMITTED", result
    assert not asked(prompts)
    engine = reload(combat, mid)
    assert (engine.state.actors[LEFT].position.x, engine.state.actors[LEFT].position.y) == (3, 6)
    assert engine.state.actors[LEFT].turn_flags.get(ONCE) is None


def test_a_non_thread_action_is_not_the_printed_trigger(tmp_path):
    """Only a Thread ability sets the step off: an ordinary feature never asks."""
    def sheet_edit(doc, aid):
        fields = doc["spheres_and_talents"]
        fields["sphere_record_ids"] = ["tianxia.sphere.thread"]
        fields["learned_talent_record_ids"] = [THREAD]
        fields["automatic_sphere_component_record_ids"] = []
        fields["cultivation_insight_record_ids"] = [FEATURE]
    # The extra action carries no Thread source id, so it is not a Thread ability.
    plain = {"effects": [STRIKE], "target_kind": "HOSTILE_ENTITY", "sphere": "tianxia.sphere.thread"}
    combat, table, mid = service_fight(tmp_path, sheet_edit=sheet_edit, ally=False,
                                       extra_actions=[("Plain Strike", plain)])
    turn(table, mid, LEFT)
    result, prompts = resolve(lambda answers: act(table, mid, "Plain Strike", answers, target_id=RIGHT))
    assert result["status"] == "COMMITTED", result
    assert not asked(prompts)

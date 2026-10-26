"""Air sphere: printed effects the table now resolves by itself (automation lane AUTO18).

Each test is at the level the printed rule failed at -- the real combat engine (tests/h1_support.duel) for a
falling creature, the compiled authority for a typed row -- and states the owner's printed sentence.

  * Feather-Fall Breath (Sky-Step, CL 5+), a Reaction: "You create a cushioning current. Reduce the fall distance
    used to calculate fall damage by 30 feet for the target. At CL 5, reduce it by 60 feet. At CL 11, the target may
    also land on its feet if it is not Incapacitated. At CL 17, you may affect a number of falling creatures within
    range equal to your Proficiency Bonus." The talent owned nothing at the table: no reaction, no reminder.
  * Storm Without Direction, "No Safe Breath": "Breath-dependent hostile creatures have Disadvantage on
    Constitution saving throws to maintain Concentration."
  * Breathless Chamber, failed save: the creature "cannot speak above a whisper" -- the engine's Silenced.
  * Sky Road: "Other creatures treat the road as Difficult Terrain and must succeed on a Dexterity saving throw the
    first time they enter it on a turn or fall through."
  * Empty-Lung Edict, Court of the Four Winds, Sky-Sovereign Incarnation: reminders the table had already applied.
"""
from __future__ import annotations

import json

import pytest

from combat import falling
from combat.ext import physiology
from combat.ext.altitude_abilities import CUSHION_CONDITION
from combat.gate2_runtime_models import ReactionDecision
from tests.h1_support import ALLY, FOE, ME, duel, mechanics, script
from tests.test_lock10_falling import prone

FEATHER_FALL = "TAL_AIR_FEATHER_FALL_BREATH"
FEATHERFALL = "tianxia.path.qi_cultivation.feature.featherfall"
STORM = "TAL_AIR_STORM_WITHOUT_DIRECTION"
CHAMBER = "TAL_AIR_BREATHLESS_CHAMBER"
SKY_ROAD = "TAL_AIR_SKY_ROAD"
EDICT = "TAL_AIR_EMPTY_LUNG_EDICT"
COURT = "TAL_AIR_COURT_OF_THE_FOUR_WINDS"
SOVEREIGN = "TAL_AIR_SKY_SOVEREIGN_INCARNATION"
BLUDGEONING = "BLUDGEONING"


def _use_all(engine):
    """Answer a prompt the way a player protecting everyone would: take as many options as the prompt allows."""
    def provider(row):
        spec = row.get("extension_choice") or {}
        options = (row.get("legal_option_ids") or [])[:int(spec.get("maximum_selections", 1))]
        if not options:
            return ReactionDecision(checkpoint=row["checkpoint"], reactor_id=row["reactor_id"],
                                    reaction_source_id=row["reaction_source_id"], selection="DECLINE"), None
        return ReactionDecision(checkpoint=row["checkpoint"], reactor_id=row["reactor_id"],
                                reaction_source_id=row["reaction_source_id"], selection="USE",
                                option_ids=tuple(options)), None
    engine.set_reaction_provider(provider)


def _record_choices(engine, pick_first=True):
    """Answer every prompt with its own options and keep a log of what was asked: (choice id, options, labels, prompt)."""
    seen = []
    def provider(row):
        spec = row.get("extension_choice") or {}
        options = list(row.get("legal_option_ids") or [])
        trigger = row.get("choice_trigger") or {}
        seen.append((str(row.get("reaction_source_id")), tuple(options),
                     dict(trigger.get("labels") or {}), str(trigger.get("prompt") or "")))
        taken = options[:1] if pick_first else options
        selection = "USE" if taken else "DECLINE"
        return ReactionDecision(checkpoint=row["checkpoint"], reactor_id=row["reactor_id"],
                                reaction_source_id=row["reaction_source_id"], selection=selection,
                                option_ids=tuple(taken)), None
    engine.set_reaction_provider(provider)
    return seen


def _decline_choices(engine):
    """Answer every prompt by declining it, the way a player who wants nothing from this fall would."""
    seen = []
    def provider(row):
        seen.append(str(row.get("reaction_source_id")))
        return ReactionDecision(checkpoint=row["checkpoint"], reactor_id=row["reactor_id"],
                                reaction_source_id=row["reaction_source_id"], selection="DECLINE"), None
    engine.set_reaction_provider(provider)
    return seen


def _use_choices(engine, wanted):
    """Answer only the choice whose id is in ``wanted`` (a mapping of choice id -> option ids); decline the rest."""
    seen = []
    def provider(row):
        choice = str(row.get("reaction_source_id"))
        options = list(row.get("legal_option_ids") or [])
        seen.append(choice)
        taken = wanted[choice] if choice in wanted else []
        return ReactionDecision(checkpoint=row["checkpoint"], reactor_id=row["reactor_id"],
                                reaction_source_id=row["reaction_source_id"],
                                selection="USE" if taken else "DECLINE", option_ids=tuple(taken)), None
    engine.set_reaction_provider(provider)
    return seen



def _lift(engine, actor, feet):
    actor.position = actor.position.model_copy(update={"z": feet // 5})
    actor.maximum_hp = 500
    actor.current_hp = 500
    return actor


def _fall(engine):
    """The fall the printed trigger answers, asked for the way the engine asks (an open intent, not a bare call)."""
    from tests.test_lock10_flight_movement import request

    intent = request(next(candidate for candidate in engine.legal_candidates() if candidate.kind == "END_TURN"))
    falling.settle(engine, "test:launch", intent)


def _fall_distance(engine):
    """The feet this engine's next fall covers, as the falling providers see it."""
    return falling.plan_distance(engine, engine.state.actors[ME])


def _taken_fall_damage(engine, target):
    """The Bludgeoning damage this engine's fall actually took off ``target``, from the recorded packet."""
    packets = [event for event in engine.events
               if event.event_type == "DAMAGE_COMMITTED" and target.entity_id in event.target_ids
               and str(event.payload.get("damage_type") or "").upper() == BLUDGEONING
               and event.source_definition_id == falling.SOURCE]
    return max((int(packet.payload["reduced_to"]) for packet in packets), default=0)


def _rolled_fall_damage(engine, target):
    """The dice this engine's fall rolled for ``target``: (expression, total)."""
    rolls = [event for event in engine.events
             if event.event_type == "DAMAGE_ROLLED" and target.entity_id in event.target_ids
             and event.source_definition_id == falling.SOURCE]
    assert len(rolls) == 1, [event.payload.get("expression") for event in rolls]
    return str(rolls[0].payload["expression"]), int(rolls[0].payload["total"])


def _walk(rows):
    out = []
    for row in rows or []:
        if isinstance(row, dict):
            out.append(row)
            for key in ("effects", "on_fail", "on_success", "on_hit", "on_miss", "triggers", "inside"):
                out.extend(_walk(row.get(key)))
    return out


def _aim_at_foe(engine, label):
    """Use the printed ability, laid down on the square the foe stands on."""
    from combat.gate2_runtime_models import ActionIntent

    foe = engine.state.actors[FOE].position
    candidate = next(c for c in engine.legal_candidates() if c.source_definition_id in engine.action_catalog
                     and label in str(engine.action_catalog[c.source_definition_id].display_name)
                     and c.destination is not None and (c.destination.x, c.destination.y) == (foe.x, foe.y))
    engine.execute_intent(ActionIntent(intent_id="test:air", decision_id=candidate.decision_id,
                                       candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                                       actor_id=candidate.actor_id, destination=candidate.destination,
                                       target_ids=tuple(candidate.target_ids)))
    return candidate


# ------------------------------------------------------------------ Feather-Fall Breath: the printed Reaction exists
def test_feather_fall_breath_compiles_a_reaction_that_costs_only_the_reaction():
    """The printed card is a Reaction with "Cost: None"; before this the talent offered no action and no reminder."""
    engine = duel([FEATHER_FALL], ally_mids=[], cl=17)
    rows = [row for row in engine.typed_passive_rows.get(ME, []) if row.get("kind") == "fall_cushion"]
    assert len(rows) == 1, [row.get("kind") for row in engine.typed_passive_rows.get(ME, [])]
    row = rows[0]
    assert row["block"] == "altitude_abilities" and row["feature_id"] == FEATHER_FALL
    numbers = row["numbers"]
    assert numbers["range_ft"] == 30, numbers
    assert numbers["reduce_ft_by_cl"] == [[1, 4, 30], [5, 20, 60]], numbers
    assert numbers["targets_by_cl"] == [[1, 16, 1], [17, 20, "pb"]], numbers
    assert numbers["upright_cl"] == 11 and numbers["cost"] == 0 and numbers["cl"] == 17, numbers


def test_feather_fall_breath_shortens_the_fall_used_for_damage():
    """40 feet of fall past the printed 30-foot cushion is a 10-foot fall: no damage, and no landing Prone either."""
    engine = duel([FEATHER_FALL], ally_mids=[], cl=4)
    _use_all(engine)
    me = _lift(engine, engine.state.actors[ME], 30)
    _fall(engine)
    assert me.current_hp == me.maximum_hp, "a 30-foot fall past a 30-foot cushion still hurt"
    assert not prone(me)


def test_feather_fall_breath_counts_only_the_fall_the_cushion_leaves():
    """A 50-foot fall past the printed 30-foot cushion is a 20-foot fall, and a 20-foot fall knocks the creature down."""
    engine = duel([FEATHER_FALL], ally_mids=[], cl=4)
    _use_all(engine)
    me = _lift(engine, engine.state.actors[ME], 50)
    _fall(engine)
    assert 0 < me.current_hp < me.maximum_hp, "a 20-foot fall past a 30-foot cushion dealt no damage"
    assert prone(me), "the cushioned creature should still land on its face"


def test_feather_fall_breath_lands_the_target_on_its_feet_at_cl_11():
    """At CL 11 the target "may also land on its feet if it is not Incapacitated"; the cushion is 60 feet by then."""
    engine = duel([FEATHER_FALL], ally_mids=[], cl=11)
    _use_all(engine)
    me = _lift(engine, engine.state.actors[ME], 100)
    _fall(engine)
    assert 0 < me.current_hp < me.maximum_hp, "a 40-foot fall past a 60-foot cushion dealt no damage"
    assert not prone(me), "CL 11 did not let the cushioned creature land on its feet"


def test_feather_fall_breath_cushions_sixty_feet_at_cl_5():
    engine = duel([FEATHER_FALL], ally_mids=[], cl=5)
    _use_all(engine)
    me = _lift(engine, engine.state.actors[ME], 45)
    _fall(engine)
    assert me.current_hp == me.maximum_hp, "the CL 5 sixty-foot cushion did not apply"


def test_feather_fall_breath_helps_one_creature_below_cl_17_and_your_proficiency_bonus_at_cl_17():
    """At CL 17: "you may affect a number of falling creatures within range equal to your Proficiency Bonus"."""
    for cl, helped in ((11, 1), (17, 2)):
        engine = duel([FEATHER_FALL], ally_mids=[], cl=cl)
        _use_all(engine)
        first = _lift(engine, engine.state.actors[ME], 40)
        second = engine.state.actors[ALLY]
        second.position = first.position.model_copy(update={"y": first.position.y - 1, "z": 8})
        second.maximum_hp = 500
        second.current_hp = 500
        _fall(engine)
        resolved = [event for event in engine.events
                    if event.event_type == "REACTION_RESOLVED" and event.source_definition_id == FEATHER_FALL]
        assert len(resolved) == 1, [(e.event_type, e.source_definition_id) for e in engine.events[-8:]]
        assert len(resolved[0].target_ids) == helped, f"CL {cl} helped {len(resolved[0].target_ids)}, printed {helped}"
        assert first.current_hp == 500, "the chosen fall still hurt"
        assert (second.current_hp == 500) == (helped == 2), "a creature outside the printed count was cushioned"


def test_feather_fall_breath_spends_the_reaction_and_leaves_nothing_behind_after_the_fall():
    engine = duel([FEATHER_FALL], ally_mids=[], cl=17)
    _use_all(engine)
    me = engine.state.actors[ME]
    assert me.reaction_available
    _lift(engine, me, 40)
    _fall(engine)
    assert not me.reaction_available, "the Reaction was not spent"
    assert not any(c.condition_id == CUSHION_CONDITION for c in me.conditions.values()), "the cushion outlived its fall"
    assert CUSHION_CONDITION not in json.dumps(engine.state.model_dump(mode="json")), "the cushion is saved fight state"


def test_feather_fall_breath_reaches_only_a_creature_within_thirty_feet():
    engine = duel([FEATHER_FALL], ally_mids=[], cl=17)
    _use_all(engine)
    me = engine.state.actors[ME]
    ally = engine.state.actors[ALLY]
    ally.position = me.position.model_copy(update={"x": me.position.x + 20, "z": 8})
    ally.maximum_hp = 500
    ally.current_hp = 500
    _fall(engine)
    assert ally.current_hp < ally.maximum_hp, "the cushion reached a creature 100 feet away"


def test_a_feather_fall_breath_owner_without_the_talent_never_answers_a_fall():
    """Checklist 3: the plug-in is inert for a character that does not own the talent."""
    engine = duel([], ally_mids=[], cl=17)
    _use_all(engine)
    me = _lift(engine, engine.state.actors[ME], 40)
    _fall(engine)
    assert me.current_hp < me.maximum_hp
    assert me.reaction_available, "a character without Feather-Fall Breath spent a Reaction on it"


def test_the_table_asks_for_feather_fall_breath_and_commits_the_cushioned_fall(monkeypatch, tmp_path):
    """Checklist 7 at the level players meet it: a falling creature pauses the table for the printed Reaction, the
    pause rolls back, and the committed fall keeps the reduced damage through a reload from disk."""
    from combat.gate5_service import CombatService
    from tests.h1_support import ROOT
    from tests.r10_fixup_support import answer
    from tests.test_tabletop_hunt6 import HOLD, LEFT, on_hold, table_fight

    combat, table, match_id = table_fight(tmp_path, [FEATHER_FALL], cl=11, ask=True)

    def launch(engine):
        falling.displace(engine, engine.state.actors[LEFT], 20, "test:launch")

    on_hold(monkeypatch, launch)
    state = table.state(match_id)
    menu = state["menu"]
    group = next(group for group in menu["actions"] if group["source_definition_id"].startswith(HOLD))
    candidate = group["options"][0]["candidate_id"]

    def send(answers=()):
        return table.act(match_id, candidate, menu["decision_id"], menu["state_version"], state["last_sequence"], list(answers))

    before = combat._load_session(match_id).engine.state.model_dump(mode="json")
    result = send()
    assert result["status"] == "REACTION_REQUIRED", result["status"]
    assert combat._load_session(match_id).engine.state.model_dump(mode="json") == before, "the pause did not roll back"
    prompt = result["reaction"]
    assert prompt["title"] == "Feather-Fall Breath", prompt.get("title")
    shown = json.dumps(prompt)
    assert FEATHER_FALL not in shown and "condition:typed" not in shown, \
        f"the player is shown internal names: {shown[:300]}"
    assert "falling" in shown.lower(), "the prompt does not say what is happening"
    result = send([answer(prompt)])
    assert result["status"] == "COMMITTED", result["status"]

    reloaded = CombatService(ROOT, tmp_path)._load_session(match_id)
    assert reloaded.verify()["status"] == reloaded.mechanical.replay()["status"] == "PASS"
    assert any(event.source_definition_id == FEATHER_FALL and event.event_type == "REACTION_RESOLVED"
               for event in reloaded.engine.events), "the table never resolved Feather-Fall Breath"
    # Checklist 7 (persistence): the reloaded fight must still be the fight that was played. The cushioned fall is
    # a 40-foot drop for a 100-foot fall's 60-foot cushion, so the left creature's hit points must be down and
    # must be exactly what the commit recorded -- not re-rolled, and not the unshortened fall.
    landed = reloaded.engine.state.actors[LEFT]
    committed = next(event for event in reloaded.engine.events
                     if event.event_type == "DAMAGE_COMMITTED" and landed.entity_id in event.target_ids
                     and event.source_definition_id == falling.SOURCE)
    assert 0 < int(committed.payload["hp_damage"]) < landed.maximum_hp, \
        f"the reloaded cushioned fall took {committed.payload['hp_damage']} of {landed.maximum_hp}"
    assert landed.current_hp == landed.maximum_hp - int(committed.payload["hp_damage"]), \
        "the reloaded fight's remaining hit points are not the ones the commit recorded"
    assert "condition:typed.air_fall_cushion" not in json.dumps(
        reloaded.engine.state.model_dump(mode="json")), "the cushion is still saved fight state"


# ------------------------------------------------------------------ Feather-Fall Breath: defenses, boundaries and the cushion's lifetime
def _cushioned_fall(defense=None, flat=0, monkeypatch=None):
    """Stage a 50-foot fall past the printed 30-foot cushion, with one ordinary defense on the falling creature.

    The printed reading is "reduce the fall distance used to calculate fall damage by 30 feet", so the 20 feet
    that are left are rolled as 2d6 and then the creature's own defenses reduce those two dice. The exact total
    is whatever the seeded roller produced; what these tests pin is that the defense was applied to it.
    """
    from tests.test_lock_choices import install

    if flat:
        install(monkeypatch, "damage_reduction", lambda *args, _flat=flat: _flat)
    engine = duel([FEATHER_FALL], ally_mids=[], cl=4)
    _use_all(engine)
    me = _lift(engine, engine.state.actors[ME], 50)
    if defense:
        engine._add_modifier(me, "test:defense", defense, "SET", BLUDGEONING, "ALL", expires_on=None)
    return engine, me


def test_the_cushion_shortens_the_fall_before_bludgeoning_resistance_halves_it():
    """Resistance halves the shorter fall's two dice, and only those.

    Rolling the cushion's dice after the defenses would have halved the whole 5d6 drop and then compared that
    with a fresh, undefended 2d6, which is the wrong packet the review found.
    """
    engine, me = _cushioned_fall("damage_resistance")
    _fall(engine)
    expression, total = _rolled_fall_damage(engine, me)
    assert expression == "2d6+0", f"the cushion did not shorten the rolled fall: {expression}"
    assert _taken_fall_damage(engine, me) == total // 2, \
        f"Bludgeoning Resistance did not halve the two cushioned dice: {_taken_fall_damage(engine, me)} of {total}"


def test_the_cushion_shortens_the_fall_before_bludgeoning_vulnerability_doubles_it():
    """Vulnerability doubles the shorter fall's two dice, never the whole 5d6 drop."""
    engine, me = _cushioned_fall("damage_vulnerability")
    _fall(engine)
    expression, total = _rolled_fall_damage(engine, me)
    assert expression == "2d6+0", f"the cushion did not shorten the rolled fall: {expression}"
    assert _taken_fall_damage(engine, me) == total * 2, \
        f"Bludgeoning Vulnerability did not double the two cushioned dice: {_taken_fall_damage(engine, me)} of {total}"


def test_the_cushion_shortens_the_fall_before_a_flat_reduction_is_subtracted(monkeypatch):
    """A flat reduction takes its points off the shorter fall, not off the drop the cushion was spent on."""
    engine, me = _cushioned_fall(flat=3, monkeypatch=monkeypatch)
    _fall(engine)
    expression, total = _rolled_fall_damage(engine, me)
    assert expression == "2d6+0", f"the cushion did not shorten the rolled fall: {expression}"
    assert _taken_fall_damage(engine, me) == total - 3, \
        f"the flat reduction was not applied to the cushioned fall: {_taken_fall_damage(engine, me)} of {total}"


def test_uncushioned_fall_damage_still_goes_through_the_same_defenses():
    """Checklist 3: a creature without the talent is untouched by all of this: the whole 5d6 drop, halved."""
    engine = duel([FEATHER_FALL], ally_mids=[], cl=4)
    engine.typed_passive_rows[ME] = [row for row in engine.typed_passive_rows.get(ME, [])
                                     if row.get("kind") != "fall_cushion"]
    me = _lift(engine, engine.state.actors[ME], 50)
    engine._add_modifier(me, "test:defense", "damage_resistance", "SET", BLUDGEONING, "ALL", expires_on=None)
    _fall(engine)
    expression, total = _rolled_fall_damage(engine, me)
    assert expression == "5d6+0", f"a creature without the talent was cushioned anyway: {expression}"
    assert _taken_fall_damage(engine, me) == total // 2


def test_feather_fall_breath_is_not_offered_for_a_drop_of_less_than_ten_feet():
    """"You or a creature within 30 feet falls 10 feet or more": a five-foot drop never costs a Reaction."""
    engine = duel([FEATHER_FALL], ally_mids=[], cl=17)
    seen = _record_choices(engine)
    me = _lift(engine, engine.state.actors[ME], 5)
    assert _fall_distance(engine) == 5, "the test did not stage a five-foot drop"
    _fall(engine)
    assert not [choice for choice in seen if "fall" in choice[0]], seen
    assert me.reaction_available, "a five-foot drop spent the Reaction"
    assert not any(c.condition_id == CUSHION_CONDITION for c in me.conditions.values())


def _fall_prompt(seen):
    """The one prompt this lane asks about a fall, if it asked one at all."""
    prompts = [choice for choice in seen if "fall" in choice[0]]
    assert len(prompts) <= 1, f"the owner was asked about this fall more than once: {prompts}"
    return prompts[0] if prompts else None


def test_a_short_drop_beside_a_long_one_is_not_its_own_trigger():
    """"falls 10 feet or more" is printed about one creature, so a batch is not a single trigger.

    A creature dropping ten feet next to one dropping five must not make the five-foot drop spend the owner's
    Reaction: only the creature that actually falls far enough is offered, and offered on its own.
    """
    engine = duel([FEATHER_FALL], ally_mids=[], cl=17)
    seen = _record_choices(engine)
    ally, foe = _lift(engine, engine.state.actors[ALLY], 10), _lift(engine, engine.state.actors[FOE], 5)
    me = engine.state.actors[ME]
    _fall(engine)
    prompt = _fall_prompt(seen)
    assert prompt is not None, "the ten-foot drop was never offered"
    assert prompt[1] == (ALLY,), f"the five-foot drop was offered beside the ten-foot one: {prompt[1]}"
    assert not me.reaction_available, "the Reaction was not spent on the one creature that qualified"
    assert ally.current_hp == ally.maximum_hp, "the creature it was offered for was not the one that fell"
    assert foe.position.z == 0, "the five-foot drop never resolved"


def test_a_long_drop_out_of_reach_does_not_reach_the_short_one_next_to_the_owner():
    """The printed minimum and the printed range are both about the same creature.

    When the creature that falls far enough is beyond the owner's reach, the short drop beside the owner is not
    a trigger either: it was never its own, and one fall somewhere in the air cannot spend this Reaction.
    """
    engine = duel([FEATHER_FALL], ally_mids=[], cl=17)
    seen = _record_choices(engine)
    ally = _lift(engine, engine.state.actors[ALLY], 50)
    ally.position = ally.position.model_copy(update={"x": 15})  # twelve squares, far outside the printed 30 feet
    foe = _lift(engine, engine.state.actors[FOE], 5)
    me = engine.state.actors[ME]
    assert engine._distance_actor_to_actor(me, engine.state.actors[FOE]) <= 30, "the test staged no creature in reach"
    assert engine._distance_actor_to_actor(me, ally) > 30, "the ten-foot fall was inside the printed range"
    _fall(engine)
    assert not [choice for choice in seen if "fall" in choice[0]], \
        "a short drop was offered because some other creature in the batch fell far enough"
    assert me.reaction_available, "a fall out of reach spent the owner's Reaction"
    assert foe.current_hp == foe.maximum_hp, "the in-reach short drop was cushioned anyway"
    assert ally.current_hp < ally.maximum_hp, "the out-of-reach ten-foot fall was cushioned"


def test_two_printed_shortenings_compose_in_either_order_they_register_in(monkeypatch):
    """The documented shortening seam has to take more than one printed ability, whatever order they load in.

    Validating each answer against the distance an earlier answer had already shortened meant a valid pair of
    providers aborted the fall transaction in one registration order and quietly worked in the other, so where
    a second printed ability happened to sit decided whether the creature landed at all.
    """
    from combat import ext

    for answers in ([40, 70], [70, 40]):
        engine = duel([], ally_mids=[], cl=4)
        me = _lift(engine, engine.state.actors[ME], 100)
        monkeypatch.setitem(ext._HOOKS, "falling_damage_distance",
                            [lambda *a, feet=feet: feet for feet in answers])
        assert falling.damage_distance(engine, me, 100, "test:fall", None) == 40, \
            f"{answers} did not compose to the shortest reported distance"


def test_a_fall_measured_by_two_printed_shortenings_rolls_the_shorter_distance_either_way(monkeypatch):
    """The same composition through a real fall: the shorter reported distance is what the dice are rolled from."""
    from combat import ext

    rolled = {}
    for answers in ([40, 70], [70, 40]):
        engine = duel([], ally_mids=[], cl=4)
        script(engine, [6, 6, 6, 6])
        me = _lift(engine, engine.state.actors[ME], 100)
        monkeypatch.setitem(ext._HOOKS, "falling_damage_distance",
                            [lambda *a, feet=feet: feet for feet in answers])
        _fall(engine)
        rolled[answers[0]] = _rolled_fall_damage(engine, me)
        assert me.current_hp == me.maximum_hp - 24, f"{answers} rolled a distance other than four dice"
    assert rolled[40] == rolled[70], f"the registration order changed the fall: {rolled}"


def test_a_shortening_outside_the_distance_fallen_is_still_rejected(monkeypatch):
    """Combining by the shortest must not weaken the bound: a provider still cannot report more feet than fell."""
    from combat import ext

    engine = duel([], ally_mids=[], cl=4)
    me = _lift(engine, engine.state.actors[ME], 100)
    monkeypatch.setitem(ext._HOOKS, "falling_damage_distance", [lambda *a: 40])
    assert falling.damage_distance(engine, me, 100, "test:fall", None) == 40
    for bad in ([lambda *a: 130], [lambda *a: -1], [lambda *a: "40"], [lambda *a: 40, lambda *a: 130]):
        monkeypatch.setitem(ext._HOOKS, "falling_damage_distance", bad)
        with pytest.raises(ValueError):
            falling.damage_distance(engine, me, 100, "test:fall", None)


def test_feather_fall_breath_is_offered_again_for_the_next_ten_foot_drop():
    """The printed minimum is ten feet, not "ever": a second fall of ten feet or more may be helped again."""
    engine = duel([FEATHER_FALL], ally_mids=[], cl=17)
    seen = _record_choices(engine)
    me = _lift(engine, engine.state.actors[ME], 5)
    _fall(engine)
    assert not seen
    me.position = me.position.model_copy(update={"z": 2})
    assert _fall_distance(engine) == 10
    _fall(engine)
    assert [choice for choice in seen if "fall" in choice[0]], "a ten-foot drop was never offered"
    assert not me.reaction_available, "the Reaction was not spent on the ten-foot drop"


def test_a_cushioned_incapacitated_creature_does_not_land_on_its_feet():
    """"At CL 11, the target may also land on its feet if it is not Incapacitated"."""
    engine = duel([FEATHER_FALL], ally_mids=[], cl=11)
    _use_all(engine)
    me = _lift(engine, engine.state.actors[ME], 100)
    engine._apply_condition(me, "condition:typed.incapacitated", "test:down", me.entity_id, expires_on=None)
    _fall(engine)
    assert 0 < me.current_hp < me.maximum_hp, "the cushioned fall dealt no damage"
    assert prone(me), "an Incapacitated creature cannot land on its feet"


def test_the_cushion_is_spent_with_the_fall_it_cushioned_and_leaves_nothing_behind():
    """Checklist 8: the cushion lasts exactly as long as the fall, and never past it."""
    engine = duel([FEATHER_FALL], ally_mids=[], cl=17)
    seen = _record_choices(engine)
    me = _lift(engine, engine.state.actors[ME], 40)
    _fall(engine)
    assert not any(c.condition_id == CUSHION_CONDITION for c in me.conditions.values())
    me.position = me.position.model_copy(update={"z": 8})
    _fall(engine)
    assert not any(c.condition_id == CUSHION_CONDITION for c in me.conditions.values())


def _no_room_to_land(engine, actor, feet):
    """Stage falling's own blocked landing: a two-cell creature with a one-cell floor, in the air."""
    from combat.footprints import ActorFootprintDefinition

    engine.actor_footprints[actor.entity_id] = ActorFootprintDefinition.rectangle(
        2, 2, footprint_id="footprint:test.blocked", source_definition_id="test:blocked")
    engine.grid.width = engine.grid.height = 1
    actor.position = actor.position.model_copy(update={"x": 0, "y": 0, "z": feet // 5})
    assert falling.landing(engine, actor) is None, "the test did not stage a fall that cannot land"


def test_a_cushion_is_spent_even_by_a_fall_that_cannot_land():
    """A fall with nowhere to land cushions nothing, so the paid cushion must not cushion a later fall.

    "no space can fit the creature" is falling's own blocked-landing rule: the cushion goes with the attempt it
    was paid for, and nothing of that attempt is left in the state a commit writes.
    """
    engine = duel([FEATHER_FALL], ally_mids=[], cl=17)
    _use_all(engine)
    me = _lift(engine, engine.state.actors[ME], 40)
    _no_room_to_land(engine, me, 40)
    _fall(engine)
    assert any(event.event_type == "PASSIVE_TRIGGERED" and event.payload.get("blocked_landing")
               for event in engine.events), "the test did not stage a blocked landing"
    assert not any(c.condition_id == CUSHION_CONDITION for c in me.conditions.values()), \
        "the cushion outlived a fall that never landed"
    assert CUSHION_CONDITION not in json.dumps(engine.state.model_dump(mode="json")), \
        "the spent cushion is committed fight state"


def test_a_spent_cushion_does_not_protect_the_next_fall_once_the_floor_clears():
    """Checklist 8: the cushion lasts the fall it cushioned and nothing longer."""
    engine = duel([FEATHER_FALL], ally_mids=[], cl=17)
    _use_all(engine)
    me = _lift(engine, engine.state.actors[ME], 50)
    _no_room_to_land(engine, me, 50)
    _fall(engine)  # blocked: the cushion is spent with the attempt
    engine.grid.width, engine.grid.height = 20, 14  # the floor clears
    me.position = me.position.model_copy(update={"x": 3, "y": 6, "z": 10})
    _fall(engine)
    expression, total = _rolled_fall_damage(engine, me)
    assert expression == "5d6+0", f"the spent cushion cushioned a later fall: {expression}"
    assert _taken_fall_damage(engine, me) == total


# ------------------------------------------------------------------ both owned falling reactions are selectable
def _both_readings(engine):
    """Give ME both printed readings of the same shape, and keep the Qi it has to pay Featherfall."""
    from combat.ext import altitude_abilities

    rows = list(engine.typed_passive_rows.get(ME, []))
    rows.extend([{"feature_id": FEATHERFALL, "block": "altitude_abilities", "kind": "featherfall",
                  "name": "Featherfall", "resource_id": "resource:core.qi",
                  "numbers": {"cl": 17, "range_ft": 60, "fall_speed_ft": 60, "targets": "pb",
                              "upright": True, "cost": 1, "checkpoint": "featherfall",
                              "choice": "choice:needle.featherfall"}}])
    engine.typed_passive_rows[ME] = rows
    assert altitude_abilities.CUSHION_CONDITION
    return rows


def test_a_character_that_owns_both_falling_reactions_is_asked_which_one_to_use():
    """The free Air cushion must be reachable for a character that also owns Path Featherfall."""
    engine = duel([FEATHER_FALL], ally_mids=[], cl=17)
    _both_readings(engine)
    seen = _record_choices(engine)
    _lift(engine, engine.state.actors[ME], 100)
    _fall(engine)
    asked = [choice for choice in seen if choice[0] == "choice:needle.fall_ability"]
    assert len(asked) == 1, seen
    assert set(asked[0][1]) == {"featherfall", "fall_cushion"}, asked
    labels = asked[0][2]
    assert "Featherfall" in labels.get("featherfall", "") and "Feather-Fall Breath" in labels.get("fall_cushion", ""), \
        f"the menu does not name both abilities and what each costs: {labels}"
    assert "Qi" in labels.get("featherfall", "") and "Qi" not in labels.get("fall_cushion", ""), \
        f"each ability's own price must be beside its name: {labels}"


def test_both_falling_reactions_are_offered_and_the_chosen_one_is_the_one_that_is_paid_for():
    """Choosing the free cushion spends only the Reaction; choosing Featherfall spends the Qi as well."""
    engine = duel([FEATHER_FALL], ally_mids=[], cl=17)
    _both_readings(engine)
    me = engine.state.actors[ME]
    engine._gain_resource(me, "resource:core.qi", 5, "test:give")
    qi = me.resources["resource:core.qi"]
    _use_choices(engine, {"choice:needle.fall_ability": ["fall_cushion"],
                          "choice:needle.fall_cushion": [ME]})
    _lift(engine, me, 100)
    _fall(engine)
    assert me.resources["resource:core.qi"] == qi, "the free Air cushion charged Qi"
    assert not me.reaction_available, "the Reaction was not spent"
    assert not any(c.condition_id == "condition:typed.featherfall" for c in me.conditions.values()), \
        "the chosen cushion also laid a Featherfall descent"


def test_the_paid_featherfall_is_still_reachable_when_it_is_chosen_over_the_free_cushion():
    engine = duel([FEATHER_FALL], ally_mids=[], cl=17)
    _both_readings(engine)
    me = engine.state.actors[ME]
    engine._gain_resource(me, "resource:core.qi", 5, "test:give")
    qi = me.resources["resource:core.qi"]
    _use_choices(engine, {"choice:needle.fall_ability": ["featherfall"],
                          "choice:needle.featherfall": [ME]})
    _lift(engine, me, 100)
    _fall(engine)
    assert me.resources["resource:core.qi"] == qi - 1, "Featherfall no longer costs one Qi per creature"
    assert me.current_hp == me.maximum_hp, "Featherfall no longer gives a safe descent"
    assert any(c.condition_id == "condition:typed.featherfall" for c in me.conditions.values())


def test_the_free_cushion_is_still_reachable_when_path_featherfall_is_declined():
    """A player who says no to the first offer spends nothing and keeps their Reaction."""
    engine = duel([FEATHER_FALL], ally_mids=[], cl=17)
    _both_readings(engine)
    seen = _decline_choices(engine)
    _lift(engine, engine.state.actors[ME], 100)
    _fall(engine)
    assert "choice:needle.fall_ability" in seen, "the character was never asked which ability to use"
    assert engine.state.actors[ME].reaction_available, "declining the first offer spent the Reaction"


def test_the_free_cushion_is_still_reachable_with_no_qi_to_pay_featherfall_for():
    """Featherfall costs Qi; the Air cushion does not. A broke character is still offered the one it can afford."""
    engine = duel([FEATHER_FALL], ally_mids=[], cl=17)
    _both_readings(engine)
    me = engine.state.actors[ME]
    me.resources["resource:core.qi"] = 0
    seen = _use_choices(engine, {"choice:needle.fall_ability": ["fall_cushion"],
                                 "choice:needle.fall_cushion": [ME]})
    _lift(engine, me, 40)
    _fall(engine)
    assert "choice:needle.fall_ability" in seen, "the free cushion was not on the menu with no Qi"
    assert not me.reaction_available, "the affordable cushion was never used"
    assert me.current_hp == me.maximum_hp, "the cushioned fall still hurt"
    assert not any(c.condition_id == "condition:typed.featherfall" for c in me.conditions.values())


# ------------------------------------------------------------------ a saved Path Featherfall keeps its own numbers
def _legacy_featherfall_row(engine, cl=17):
    """The row a fight saved before Featherfall's printed numbers moved onto it carries only the block numbers."""
    return {"feature_id": FEATHERFALL, "block": "altitude_abilities", "kind": "featherfall",
            "resource_id": "resource:core.qi",
            "numbers": {"pb": engine.state.actors[ME].proficiency_bonus, "key_mod": 0, "cl": cl,
                        "armor": None, "shield": False}}


def test_a_fight_saved_before_the_numbers_moved_still_charges_one_qi_each_and_reaches_sixty_feet():
    """Checklist 3 and 12: an old saved row has none of the new fields and must fall back to the printed ones."""
    engine = duel([FEATHERFALL], ally_mids=[], cl=17)
    engine.typed_passive_rows[ME] = [_legacy_featherfall_row(engine)]
    me, ally, foe = (engine.state.actors[key] for key in (ME, ALLY, FOE))
    engine._gain_resource(me, "resource:core.qi", 9, "test:give")
    qi = me.resources["resource:core.qi"]
    ally.position = me.position.model_copy(update={"x": me.position.x + 12, "z": 8})  # 60 feet away
    ally.maximum_hp = ally.current_hp = 500
    foe.position = me.position.model_copy(update={"x": me.position.x + 20, "z": 8})  # 100 feet away
    foe.maximum_hp = foe.current_hp = 500
    _use_all(engine)
    _lift(engine, me, 40)
    _fall(engine)
    assert me.resources["resource:core.qi"] == qi - 2, \
        f"the saved row no longer charges one Qi for each chosen creature ({qi} -> {me.resources['resource:core.qi']})"
    assert ally.current_hp == ally.maximum_hp, "a creature 60 feet away was no longer reached"
    assert foe.current_hp < foe.maximum_hp, "the saved row reached further than its printed 60 feet"


def test_a_fight_saved_before_the_numbers_moved_still_uses_its_own_choice_and_log_line():
    """The transport a paused fight was recorded under is part of the save: a renamed one cannot be answered."""
    engine = duel([FEATHERFALL], ally_mids=[], cl=17)
    engine.typed_passive_rows[ME] = [_legacy_featherfall_row(engine)]
    seen = _record_choices(engine)
    _lift(engine, engine.state.actors[ME], 40)
    _fall(engine)
    assert [choice[0] for choice in seen] == ["choice:needle.featherfall"], seen
    line = next(event for event in engine.events if event.event_type == "REACTION_RESOLVED").payload["log"]
    assert line.endswith("the chosen creatures descend safely, at most 60 ft. each round."), \
        f"the saved row's own log line changed: {line!r}"


# ------------------------------------------------------------------ Storm Without Direction, No Safe Breath
def test_storm_without_direction_no_safe_breath_is_typed_as_the_printed_concentration_save():
    """No Safe Breath: breath-dependent creatures inside the storm have Disadvantage on Concentration saves."""
    option = next(option for option in mechanics()[STORM]["options"] if option["label"] == "No Safe Breath")
    zone = next(row for row in option["effects"] if row.get("type") == "zone")
    inside = [rule for rule in zone.get("inside") or []
              if (rule.get("rule") or {}).get("concentration_mode") == "DISADVANTAGE"]
    assert len(inside) == 1, zone.get("inside")
    rule = inside[0]
    assert rule["who"] == "hostile", rule
    assert rule["requires_physiology"] == {"any": ["breath_dependent"]}, rule
    assert rule.get("reading"), "an inside rule a newcomer cannot read"


def test_physiology_gates_a_zone_rule_as_well_as_an_effect_row():
    """The No Safe Breath reading is a printed-physiology gate on an area, not on an effect row."""
    engine = duel([], ally_mids=[], cl=17)
    undead = engine.state.actors[FOE]
    undead.creature_types = (*undead.creature_types, "Undead")
    assert physiology.trait(undead, "breath_dependent") is False, "an undead creature still breathes"
    assert physiology.trait(engine.state.actors[ME], "breath_dependent") is True
    spec = {"requires_physiology": {"any": ["breath_dependent"]}}
    assert physiology.eligible(undead, spec) is False
    assert physiology.eligible(engine.state.actors[ME], spec) is True


def test_no_safe_breath_costs_a_breath_dependent_creature_its_concentration_saves_inside_the_storm():
    """The printed effect at the level it happens: a hostile creature standing in the storm.

    The exempt subject is a hostile creature: "Breath-dependent HOSTILE creatures have Disadvantage". A creature
    that does not breathe must be one the rule would otherwise have charged, so this stages a hostile Undead in
    the storm. An allied Undead passes this assertion even with the gate removed, so it is not the case here.
    """
    from combat import concentration, zones
    from combat.gate2_runtime_models import ActionIntent

    engine = duel([STORM], ally_mids=[], cl=17)
    candidate = next(c for c in engine.legal_candidates() if c.source_definition_id in engine.action_catalog
                     and "No Safe Breath" in str(engine.action_catalog[c.source_definition_id].display_name))
    engine.execute_intent(ActionIntent(intent_id="test:storm", decision_id=candidate.decision_id,
                                       candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                                       actor_id=candidate.actor_id, destination=candidate.destination,
                                       target_ids=tuple(candidate.target_ids)))
    storm = next(zone for zone in zones.typed_zones(engine) if zone.active)
    foe = engine.state.actors[FOE]
    assert engine._in_zone(foe, storm)
    assert foe.team_id != engine.state.actors[ME].team_id, "the subject must be a hostile creature"
    assert concentration.save_mode(engine, foe) == "DISADVANTAGE", "the storm did not cost the creature its saves"
    undead = engine.state.actors[FOE]
    undead.creature_types = (*undead.creature_types, "Undead")
    zones.sync_inside(engine, "test:undead")
    assert engine._in_zone(undead, storm)
    assert undead.team_id != engine.state.actors[ME].team_id, "the Undead subject must still be a hostile creature"
    assert concentration.save_mode(engine, undead) != "DISADVANTAGE", "a creature that does not breathe was charged"


def test_the_zone_gate_is_what_exempts_that_creature(monkeypatch):
    """Checklist 7: the integration case above must fail when the zone gate is removed, or it proves nothing."""
    from combat import concentration, ext, zones
    from combat.gate2_runtime_models import ActionIntent

    engine = duel([STORM], ally_mids=[], cl=17)
    candidate = next(c for c in engine.legal_candidates() if c.source_definition_id in engine.action_catalog
                     and "No Safe Breath" in str(engine.action_catalog[c.source_definition_id].display_name))
    engine.execute_intent(ActionIntent(intent_id="test:storm", decision_id=candidate.decision_id,
                                       candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                                       actor_id=candidate.actor_id, destination=candidate.destination,
                                       target_ids=tuple(candidate.target_ids)))
    storm = next(zone for zone in zones.typed_zones(engine) if zone.active)
    undead = engine.state.actors[FOE]
    undead.creature_types = (*undead.creature_types, "Undead")
    zones.sync_inside(engine, "test:undead")
    assert concentration.save_mode(engine, undead) != "DISADVANTAGE"
    kept = [fn for fn in ext._HOOKS["zone_recipient_allowed"] if fn is not physiology.physiology_zone_recipient_allowed]
    monkeypatch.setitem(ext._HOOKS, "zone_recipient_allowed", kept)
    zones.sync_inside(engine, "test:undead-without-the-gate")
    assert concentration.save_mode(engine, undead) == "DISADVANTAGE", \
        "removing the zone gate did not change anything, so the test above proves nothing"


# ------------------------------------------------------------------ Breathless Chamber: the failed save silences
def test_breathless_chamber_failed_save_silences_and_keeps_the_stated_durations():
    """Failed Save: the creature cannot speak above a whisper, cannot take Reactions, and has Disadvantage on its
    Constitution saving throws to maintain Concentration, until the start of its next turn."""
    record = mechanics()[CHAMBER]
    saves = [row for row in _walk(record["effects"]) if row.get("type") == "save"]
    assert len(saves) == 1, "Breathless Chamber's save is not its own row"
    assert saves[0]["requires_physiology"] == {"any": ["breath_dependent"]}, saves[0]
    failed = saves[0]["on_fail"]
    assert "silenced" in {row.get("condition") for row in failed}, failed
    assert {"reaction_denied"} <= {row["type"] for row in failed}, failed
    assert all(row.get("duration") == "until_start_of_next_turn" for row in failed), failed


def test_a_creature_that_starts_its_turn_in_the_chamber_fails_the_save_and_loses_its_voice():
    """The printed effect as the table runs it: a hostile creature standing in the chamber when its turn begins."""
    from combat import speech

    engine = duel([CHAMBER], ally_mids=[], cl=17)
    script(engine, [1] * 40)  # it fails the Constitution save
    _aim_at_foe(engine, "Breathless Chamber")
    assert engine.state.actors[FOE].reaction_available
    engine.end_turn()  # the foe's turn starts inside the chamber
    foe = engine.state.actors[FOE]
    assert speech.silenced(foe), "the creature can still speak after failing the chamber's save"
    assert not foe.reaction_available, "the creature can still take Reactions"
    assert {condition.condition_id for condition in foe.conditions.values()} == {
        "condition:typed.silenced", "condition:typed.reaction_denied", "condition:typed.concentration_mode"}, \
        [condition.condition_id for condition in foe.conditions.values()]


# ------------------------------------------------------------------ Sky Road: other creatures save to cross it
def test_sky_road_saves_on_entry_only_and_names_who_its_penalties_touch():
    """"Other creatures treat the road as Difficult Terrain and must succeed on a Dexterity saving throw the first
    time they ENTER it on a turn or fall through."

    Both printed words are qualifications the typed row has to carry: the save is asked on entry only (a creature
    that stands still on the road has not entered it), and the Difficult-Terrain rule names its recipients so
    the area's own creator and the creatures it designates can be left out of it.
    """
    row = next(row for row in _walk(mechanics()[SKY_ROAD]["effects"]) if row.get("type") == "zone")
    difficult = row.get("difficult")
    assert isinstance(difficult, dict) and difficult.get("who") == "any", \
        f"the road's Difficult Terrain must name who it applies to: {difficult!r}"
    assert "Other creatures treat the road as Difficult Terrain" in str(difficult.get("evidence")), difficult
    triggers = [trigger for trigger in row.get("triggers") or []
                if any(effect.get("type") == "save" for effect in trigger["effects"])]
    assert len(triggers) == 1, row.get("triggers")
    trigger = triggers[0]
    assert set(trigger["on"]) == {"enter"}, \
        f"the save is asked for entering, not for standing on the road: {trigger['on']}"
    assert trigger["who"] == "any", trigger
    save = trigger["effects"][0]
    assert save["type"] == "save" and save["ability"] == "dex", save
    assert [effect["type"] for effect in save["on_fail"]] == ["air_road_fall"], save
    assert [effect["type"] for effect in save["on_success"]] == ["air_road_stand"], save


def test_sky_road_lays_a_road_that_only_other_creatures_are_stopped_and_asked_by():
    """The printed effect as the table runs it: the road exists; a creature that enters it is slowed and asked to
    save; the road's own creator and the creature it designates are left alone on it."""
    from combat import zones
    from combat.ext import air_currents

    engine = duel([SKY_ROAD], ally_mids=[], cl=17)
    _aim_at_foe(engine, "Sky Road")
    road = next(zone for zone in zones.typed_zones(engine) if zone.active)
    assert road.affected_cells, "the road was laid on no squares at all"
    assert road.trigger_profile["triggers"][0]["effects"][0]["ability"] == "dex"
    assert road.trigger_profile.get(air_currents.DESIGNATED) == (ALLY,), \
        f"the road did not record who it was designated for: {road.trigger_profile}"
    me, ally, foe = (engine.state.actors[key] for key in (ME, ALLY, FOE))
    road_cells = {(cell.x, cell.y) for cell in road.affected_cells}
    assert road_cells & zones.difficult_cells(engine, foe), \
        "the road is not difficult ground for a creature it was not designated for"
    assert not (road_cells & zones.difficult_cells(engine, me)), "the road slowed down its own creator"
    assert not (road_cells & zones.difficult_cells(engine, ally)), \
        "the road slowed down a creature it was designated for"
    near_row = min(cell.y for cell in road.affected_cells)

    def road_at(column):
        return next(cell for cell in road.affected_cells if (cell.y, cell.x) == (near_row, column))

    def off_at(column):
        return road_at(column).model_copy(update={"y": max(0, near_row - 3)})

    def saves():
        """The road's own crossing saves (this ability's action, not an initiative or concentration roll)."""
        return [event for event in engine.events if event.event_type == "SAVE_ROLLED"
                and event.source_definition_id == road.source_definition_id]

    def step(creature, column):
        outside = off_at(column)
        assert not zones._inside(engine, creature, road, outside), f"column {column} is still on the road"
        creature.position = road_at(column)  # the engine reads the live square and the segment endpoints
        zones.on_moved(engine, creature, outside, road_at(column))

    step(foe, 6)  # an unnamed creature walks onto the road: "Other creatures ... must succeed"
    assert len(saves()) == 1, f"the creature that entered the road was not asked exactly once: {len(saves())}"
    assert saves()[0].payload.get("actor_id") == FOE and saves()[0].payload.get("dc"), \
        f"the crossing save was asked of the wrong creature: {saves()[0].payload}"
    before = len(saves())
    step(ally, 8)  # designated
    step(me, 10)  # the road's own creator
    assert len(saves()) == before, "the road asked its creator or a designated creature for the crossing save"
    step(foe, 6)  # off the road and back onto it, on the same turn
    assert len(saves()) == before, "the crossing save was asked twice on one turn"
    engine.end_turn()  # the foe stands still on the road: entering it is the printed moment, not standing on it
    assert len(saves()) == before, "a creature that never entered the road this turn was asked to save"


# ------------------------------------------------------------------ Sky Road and the falling Reaction at the table
# The engine fixture above proves the rules; these two go through the real table service, because both add
# something a fight has to carry: a designation the player answers inside another actor's action, and a
# Reaction its owner decides on a turn that is not its own. Neither survives a save unless it commits.


def _table_fight(tmp_path, talents, **kw):
    from tests.test_tabletop_hunt6 import table_fight

    return table_fight(tmp_path, talents, **kw)


def _cast_sky_road(table, mid):
    """Have the manual owner lay the road on the square in front of them, and answer the designation prompt."""
    from combat.gate3_reducer import canonical_state_sha256

    state, menu = table.state(mid), table.state(mid)["menu"]
    group = next(g for g in menu["actions"] if g.get("source_definition_id", "").endswith(SKY_ROAD))
    # The table defers its square picker. This designation regression submits
    # the same native exact aim so its first pause remains the recipient choice.
    engine = table.combat._load_session(mid).engine
    option = next(c.model_dump(mode='json') for c in engine.legal_candidates()
                  if c.source_definition_id == group['source_definition_id']
                  and c.destination is not None
                  and (c.destination.x, c.destination.y, c.destination.z) == (3, 6, 0))
    args = (mid, option["candidate_id"], menu["decision_id"], menu["state_version"], state["last_sequence"])
    combat = table.combat
    before = canonical_state_sha256(combat._load_session(mid).engine.state)
    paused = table.act(*args, [])
    assert paused["status"] == "REACTION_REQUIRED", paused
    prompt = paused["reaction"]
    assert prompt["reaction"] == "Sky Road", prompt
    assert "Choose the creatures this road is for" in prompt["trigger"], prompt
    assert canonical_state_sha256(combat._load_session(mid).engine.state) == before, \
        "the unanswered designation left the road behind"
    labels = {option["id"]: option["label"] for option in prompt["choice"]["options"]}
    return args, prompt, labels


def test_the_road_the_owner_designated_survives_a_table_commit_and_reload(tmp_path):
    """"Creatures you designate may stand ... as though it were solid ground": the answer is part of the road.

    Asked and answered through the table, committed, reloaded from disk and replayed: the road comes back with
    the creatures it was designated for, they are still left out of its Difficult Terrain and its crossing save,
    and a creature it was not designated for is still stopped and asked.
    """
    from combat import zones
    from combat.ext import air_currents
    from combat.gate5_service import CombatService
    from tests.h1_support import ROOT
    from tests.test_tabletop_hunt6 import ALLY, LEFT, RIGHT

    combat, table, mid = _table_fight(tmp_path, [SKY_ROAD], cl=17, ask=True)
    args, prompt, labels = _cast_sky_road(table, mid)
    assert set(labels) == {ALLY, RIGHT}, f"the designation did not offer the other creatures by name: {labels}"
    answer = {**prompt["context"], "selection": "USE", "option_ids": [ALLY]}
    committed = table.act(*args, [answer])
    assert committed["status"] == "COMMITTED", committed

    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    engine = loaded.engine
    road = next(zone for zone in zones.typed_zones(engine) if zone.active)
    assert tuple(road.trigger_profile.get(air_currents.DESIGNATED) or ()) == (ALLY,), \
        f"the designation did not survive the commit: {road.trigger_profile}"
    me, ally, foe = (engine.state.actors[key] for key in (LEFT, ALLY, RIGHT))
    cells = {(cell.x, cell.y) for cell in road.affected_cells}
    assert cells & zones.difficult_cells(engine, foe), "the road is no longer difficult for a creature it spares nobody"
    assert not (cells & zones.difficult_cells(engine, ally)), "a designated creature is slowed on its own road"
    assert not (cells & zones.difficult_cells(engine, me)), "the road slowed down its own creator"
    assert loaded.verify()["status"] == loaded.mechanical.replay()["status"] == "PASS"

    near = min(cell.y for cell in road.affected_cells)
    row = sorted((cell for cell in road.affected_cells if cell.y == near), key=lambda cell: cell.x)
    assert len(row) >= 3, f"the road is too short to walk three creatures across: {len(row)} squares"

    def step(creature, index):
        cell = row[index]
        outside = cell.model_copy(update={"y": max(0, near - 3)})
        assert not zones._inside(engine, creature, road, outside), f"{cell} is still on the road"
        creature.position = cell
        zones.on_moved(engine, creature, outside, cell)

    def saves():
        return [event for event in engine.events if event.event_type == "SAVE_ROLLED"
                and event.source_definition_id == road.source_definition_id]

    step(foe, 0)  # a creature the owner did not designate enters: "Other creatures ... must succeed"
    assert len(saves()) == 1, f"the undesignated crossing save was not asked: {len(saves())}"
    assert saves()[0].payload.get("actor_id") == RIGHT, saves()[0].payload
    before = len(saves())
    step(ally, 1)  # the creature the owner designated, after the reload
    assert len(saves()) == before, "the reloaded road asked a designated creature to save"


def test_a_manual_owners_falling_reaction_is_asked_on_another_actors_turn(tmp_path, monkeypatch):
    """Checklist 9: a player's own decision is theirs to make on anyone's turn.

    The owner is a manual player holding an action; the fall happens during an automatically controlled
    creature's turn. The owner is still asked, the prompt names the ability and the creature, and answering it
    commits - the same pause, answer and reload the table runs for a turn of their own.
    """
    from combat import falling
    from combat.ext.altitude_abilities import CUSHION_CONDITION
    from combat.gate5_service import CombatService
    from tests.h1_support import ROOT
    from tests.test_tabletop_hunt6 import ALLY, LEFT, RIGHT, table_fight

    combat, table, mid = table_fight(tmp_path, [FEATHER_FALL], cl=17, ask=True, ally_talents=[])
    combat.set_controller_mode(mid, actor_id=RIGHT, controller_mode="LOCAL_AUTO")
    while table.state(mid)["menu"]["actor_id"] != RIGHT:
        state, menu = table.state(mid), table.state(mid)["menu"]
        assert table.act(mid, menu["end_turn"], menu["decision_id"], menu["state_version"],
                         state["last_sequence"], [])["status"] == "COMMITTED"

    launching = []

    def launch(engine):
        """The AI actor's move knocks its ally off a ledge, the way a shove or a gust would.

        The table answers a pause by re-executing the stored intent, so this runs again on the way back in; it
        only refuses to re-enter itself, so one executed move never falls the ally twice.
        """
        if launching:
            return
        launching.append(event := engine.state.event_sequence)
        try:
            ally = engine.state.actors[ALLY]
            ally.position = ally.position.model_copy(update={"z": 2})
            falling.displace(engine, ally, 2, "test:knocked_off_a_ledge", intent=engine._active_intent)
        finally:
            launching.pop()
            assert launching == [], event

    def once(engine, event_type, *args, **kwargs):
        result = append(engine, event_type, *args, **kwargs)
        if event_type == "INTENT_ACCEPTED":
            launch(engine)
        return result

    from combat.gate4_engine import Gate4ControllerEngine

    append = Gate4ControllerEngine._append_event
    monkeypatch.setattr(Gate4ControllerEngine, "_append_event", once)
    paused = table.auto_step(mid, 0)
    assert paused["status"] == "REACTION_REQUIRED", paused
    prompt = paused["reaction"]
    assert prompt["context"]["reactor_id"] == LEFT, \
        f"the fall was answered by {prompt['context']['reactor_id']}, not by its owner"
    assert prompt["reaction"] == "Feather-Fall Breath", prompt
    labels = {option["id"]: option["label"] for option in prompt["choice"]["options"]}
    assert list(labels) == [ALLY], f"the owner was offered a creature that is not falling far enough: {labels}"

    pending = table.state(mid)["pending_action"]
    engine_before = combat._load_session(mid).engine
    assert engine_before.state.current_actor_id == RIGHT, \
        f"the fall resolved outside an AI turn ({engine_before.state.current_actor_id})"
    resumed = getattr(table, pending["method"])(mid, **pending["request"],
                                                reactions=[{**prompt["context"], "selection": "USE",
                                                            "option_ids": [ALLY]}])
    assert resumed["status"] == "COMMITTED", resumed

    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    ally = loaded.engine.state.actors[ALLY]
    assert ally.current_hp == ally.maximum_hp, \
        f"the twenty-foot fall still hurt past the printed cushion ({ally.current_hp}/{ally.maximum_hp})"
    assert not any(c.condition_id == CUSHION_CONDITION for c in ally.conditions.values()), \
        "the cushion outlived the fall it was paid for"
    assert not loaded.engine.state.actors[LEFT].reaction_available, "the Reaction was not spent"
    assert loaded.verify()["status"] == loaded.mechanical.replay()["status"] == "PASS"


# ------------------------------------------------------------------ reminders the table had already applied
def test_reminders_the_table_has_already_applied_are_gone():
    """These printed lines were read back to the GM while the table did them itself."""
    for mechanic_id, gone in ((EDICT, "do not need to breathe"),
                              (COURT, "Air Control Limit"),
                              (SOVEREIGN, "Air Control Limit"),
                              (FEATHER_FALL, "CL 17, you may affect a number of falling creatures")):
        assert not [rider for rider in mechanics()[mechanic_id].get("riders") or [] if gone in rider], \
            f"{mechanic_id} still owes the GM a line the table applies: {mechanics()[mechanic_id].get('riders')}"

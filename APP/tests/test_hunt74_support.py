"""Hunt 74 support play (MiniMax MMX50, round 23 live 65cf60c9): a technique you cast on yourself no longer asks you to
answer a reaction about being targeted; the AI stops re-casting a self buff that is still up; decision text agrees with a
creature named "You". Engine-intent, AI-menu, serialization and direct-helper tests; no browser.

  self-cast   "You are targeted by a single-target supernatural effect" (tianxia.talent.talismans.talisman_reflection)
              answered the caster's own Healing Talisman on itself, spending a Reaction, 5 CP and a prepared talisman to
              redirect a heal toward its own source. combat/typed_reactions.py on_technique_start's targets loop now skips
              the actor, the same guard its technique_used loop already had.
  ai buff     combat/ext/ai_restraint.py _self_only: a self buff carrying a damage rider that fires on a later hit
              (Lightning-God Body's extra_damage) was not seen as a self buff, so its "already up" restraint was
              unreachable and the AI re-cast a 1-minute buff every turn until the pool was empty.
  wording     combat/decision_text.py: a creature named "You" read "You is about to take 5 damage".
"""
from pathlib import Path

from combat import decision_text, typed_reactions
from combat.factory_compiler import compile_character
from combat.gate2_engine import Gate2Engine
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent, MatchState
from combat.gate4_context import build_decision_context
from combat.gate4_policy import PolicyLibrary

ROOT = Path(__file__).resolve().parents[1]
ME = "actor:factory.hunt74"
ALLY = "actor:factory.hunt74_ally"
REFLECTION = "tianxia.talent.talismans.talisman_reflection"
HEAL = "tianxia.talent.talismans.healing_talisman"
PRISON_BARS = "TAL_LIGHTNING_LIGHTNING_PRISON_BARS"   # a real single-target hostile technique: 2 CP, a save
LIGHTNING_GOD_BODY = "TAL_LIGHTNING_LIGHTNING_GOD_BODY"


def _sheet(talents, sphere):
    return {
        "identity": {"proficiency_bonus": 6, "cultivation_level": 15, "path": "Qi Cultivation", "key_ability": "WIS"},
        "ability_scores_and_statistics": {
            "abilities": [{"ability": a, "score": 14, "modifier": 2} for a in ("STR", "DEX", "CON", "INT", "WIS", "CHA")],
            "primary_resource": {"name": "Qi", "maximum": 30}, "armor_class": {"base_value": 14},
            "hit_points": {"maximum": 60}, "speed": {"walking_ft": 30},
            "technique_save_dc": 15, "technique_attack_bonus": 8},
        "spheres_and_talents": {"sphere_record_ids": [sphere], "learned_talent_record_ids": list(talents)},
    }


def _fight(talents, sphere, seed):
    engine = Gate2Engine(ROOT, match_seed=seed, typed_bundles=(compile_character(_sheet(talents, sphere), actor_id=ME),),
                         roster_setup={"primary_actor_ids": [ME, AN], "team_by_actor": {ME: "team:a", AN: "team:b"},
                                       "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": 9, "y": 6}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    return engine


def _commit(engine, name, actor_id=None, targets=None):
    candidates = [c for c in engine.legal_candidates() if c.display_name.split(" at ")[0] == name]
    if targets is not None:  # an "ally or self" ability offers one candidate per recipient; pick the asked-for one
        wanted = tuple(targets)
        candidates = [c for c in candidates if tuple(c.target_ids or ()) == wanted] or candidates
    candidate = candidates[0]
    engine.execute_intent(ActionIntent(
        intent_id=f"h74-{name}", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
        state_version=candidate.state_version, actor_id=actor_id or candidate.actor_id,
        target_ids=candidate.target_ids, destination=candidate.destination))


def _reflection_events(engine):
    return [e for e in engine.events if e.source_definition_id == REFLECTION
            and e.event_type in ("REACTION_WINDOW_OPENED", "REACTION_RESOLVED")]


def _table(mine, theirs, seed, *, sphere="tianxia.sphere.talismans", their_sphere=None, their_id=ALLY, same_team=False,
           with_enemy=False):
    """A real table with two Factory fighters, so one casts a real technique at the other through the engine's
    own intent path (hunt 74 review: a fix that answers "you are being targeted" has to be exercised by an
    ability actually being cast, not by calling the reaction hook by hand). ``with_enemy`` adds the stock
    fighter on the far team, for the case that needs a real hostile creature to aim at."""
    roster, teams, places = [ME, their_id], {ME: "team:a", their_id: "team:a" if same_team else "team:b"}, \
        {ME: {"x": 3, "y": 6}, their_id: {"x": 4, "y": 6}}
    if with_enemy:
        roster.append(AN)
        teams[AN] = "team:b"
        places[AN] = {"x": 6, "y": 6}
    engine = Gate2Engine(ROOT, match_seed=seed, typed_bundles=(
        compile_character(_sheet(mine, sphere), actor_id=ME),
        compile_character(_sheet(theirs, their_sphere or sphere), actor_id=their_id)),
        roster_setup={"primary_actor_ids": roster, "team_by_actor": teams, "starting_positions": places})
    return engine


def _turn_of_actor(engine, actor_id):
    engine.state.current_slot_index = engine.state.initiative_order.index(actor_id)
    engine.state.current_actor_id = actor_id
    engine._system_start_turn()


# ------------------------------------------------------------------ finding 1: a self-cast is not "being targeted"
def test_a_self_cast_heal_never_asks_its_own_caster_to_answer_a_being_targeted_reaction():
    engine = _fight([REFLECTION, HEAL], "tianxia.sphere.talismans", "H74-SELF-HEAL")
    me = engine.state.actors[ME]
    me.current_hp = 30
    prepared = me.resources["resource:named.prepared_talismans"]
    qi = me.resources["resource:core.qi"]
    assert me.reaction_available
    _commit(engine, "Healing Talisman")
    assert not _reflection_events(engine), "a heal cast on yourself must not open a reaction about being targeted"
    assert me.reaction_available, "answering would have spent the caster's own Reaction"
    assert me.resources["resource:core.qi"] == qi, "answering would have spent 5 CP"
    assert me.resources["resource:named.prepared_talismans"] == prepared - 1  # only the talisman the heal itself used


def test_an_enemy_technique_targeting_a_fighter_still_offers_the_reflection_reaction():
    """The fix must not silence the reading it exists for: someone else casting at you still answers it."""
    engine = _fight([REFLECTION, HEAL], "tianxia.sphere.talismans", "H74-ENEMY")
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    assert me.reaction_available
    typed_reactions.on_technique_start(engine, foe, [me], {"numbers": {}})
    assert _reflection_events(engine), "an enemy technique on you is the moment the printed trigger is written for"
    assert not me.reaction_available


# ------------------------------------------- finding 1 (review): a BENEFIT aimed at you is not an attack either
def test_an_allies_heal_of_a_wounded_fighter_does_not_open_a_being_targeted_reaction():
    """MMX50r finding 1. The self-cast guard was only half of it: an ALLY's Healing Talisman is a single-target
    supernatural effect aimed at you, so the same window opened on you and spent YOUR Reaction, 5 CP and one of
    YOUR prepared talismans to redirect a heal back at the healer. Real two-fighter table, real intent."""
    engine = _table([REFLECTION, HEAL], [HEAL], "H74-ALLY-HEAL", same_team=True)
    me = engine.state.actors[ME]
    me.current_hp = 30
    qi, prepared = me.resources["resource:core.qi"], me.resources["resource:named.prepared_talismans"]
    assert me.reaction_available
    _turn_of_actor(engine, ALLY)
    _commit(engine, "Healing Talisman", actor_id=ALLY, targets=[ME])
    assert not _reflection_events(engine), "an ally's heal is not an attack, so nothing may answer 'you are being targeted'"
    assert me.reaction_available, "answering would have spent the healed fighter's own Reaction"
    assert me.resources["resource:core.qi"] == qi, "answering would have spent 5 CP of the healed fighter's Qi"
    assert me.resources["resource:named.prepared_talismans"] == prepared  # the heal spends the healer's, not yours
    assert me.current_hp > 30, "the ally's heal still landed: this must suppress the reaction, not the healing"


def test_a_benevolent_incoming_effect_is_not_adverse_but_an_enemy_one_is():
    """The rule itself, over real compiled abilities: an ally's heal is a benefit, an enemy's Prison Bars is not."""
    engine = _table([REFLECTION, HEAL], [HEAL, PRISON_BARS], "H74-ADVERSE", their_sphere="tianxia.sphere.lightning",
                    same_team=True, with_enemy=True)
    me, ally, enemy = engine.state.actors[ME], engine.state.actors[ALLY], engine.state.actors[AN]
    heal = next(a for a in engine.action_catalog.values() if a.display_name == "Healing Talisman")
    bars = next(a for a in engine.action_catalog.values() if a.display_name == "Lightning Prison Bars")
    assert not typed_reactions._incoming_is_adverse(ally, me, heal.parameters["typed"]), \
        "the same heal is not an attack when a teammate casts it"
    assert typed_reactions._incoming_is_adverse(enemy, me, bars.parameters["typed"]), \
        "and an enemy's Prison Bars is, even though the ability itself never changes"


# ------------------------------------------- finding 2 (review): a HOSTILE use still opens the real answers
def test_a_real_hostile_technique_from_an_enemy_still_automatically_uses_reflection():
    """MMX50r finding 2. The old test called the reaction hook by hand with empty data, which proved nothing
    about a real action. Here an enemy fighter really casts Lightning Prison Bars at a fighter who owns the
    reflection, through the engine's own intent path with automatic reactions."""
    engine = _table([REFLECTION, HEAL], [PRISON_BARS], "H74-HOSTILE", their_sphere="tianxia.sphere.lightning")
    me = engine.state.actors[ME]
    qi = me.resources["resource:core.qi"]
    assert me.reaction_available
    _turn_of_actor(engine, ALLY)
    _commit(engine, "Lightning Prison Bars", actor_id=ALLY, targets=[ME])
    assert _reflection_events(engine), "an enemy's hostile technique on you is exactly what the printed trigger is for"
    assert not me.reaction_available, "answering it spends your Reaction"
    assert me.resources["resource:core.qi"] == qi - 5, "Talisman Reflection costs 5 CP"


def test_a_hostile_candidate_from_the_ai_menu_still_automatically_uses_reflection():
    """Select from the AI menu and execute an intent; this does not run a controller decision."""
    engine = _table([REFLECTION, HEAL], [PRISON_BARS], "H74-HOSTILE-AI", their_sphere="tianxia.sphere.lightning")
    me = engine.state.actors[ME]
    qi = me.resources["resource:core.qi"]
    _turn_of_actor(engine, ALLY)
    menu = build_decision_context(engine, PolicyLibrary(ROOT).for_actor(ALLY)[0], for_ai=True).legal_candidates
    bars = next(c for c in menu if c.display_name.split(" at ")[0] == "Lightning Prison Bars")
    engine.execute_intent(ActionIntent(intent_id="h74-ai", decision_id=bars.decision_id, candidate_id=bars.candidate_id,
                                       state_version=bars.state_version, actor_id=ALLY, target_ids=bars.target_ids,
                                       destination=bars.destination))
    assert _reflection_events(engine), "an AI enemy's hostile technique opens the answer on its own turn as well"
    assert me.resources["resource:core.qi"] == qi - 5, "and the answer still spends the defender's 5 CP"


def test_a_row_that_only_helps_the_reactor_is_not_treated_as_a_hostile_effect_answer():
    """The filter must not close protective rows: an AC bonus or resistance for the creature it landed on
    (Bulwark's reading, "a protected ally is targeted by an attack roll") is not an answer to being attacked."""
    assert not typed_reactions._answers_a_hostile_effect({"effects": [{"type": "ac_bonus", "applies_to": "self"}]})
    assert not typed_reactions._answers_a_hostile_effect({"effects": [{"type": "resistance", "applies_to": "self"}]})
    assert typed_reactions._answers_a_hostile_effect({"effects": [{"type": "negate_attack"}]}), \
        "turning the effect back on its source is the clearest answer to being attacked there is"
    assert typed_reactions._answers_a_hostile_effect({"effects": [{"type": "damage", "applies_to": "attacker"}]}), \
        "so is a counter that harms the user"


# ------------------------------------------------------------------ finding 2: the AI leaves a live self buff alone
def test_the_ai_does_not_re_cast_a_self_buff_while_its_own_long_duration_one_is_still_up():
    engine = _fight([LIGHTNING_GOD_BODY], "tianxia.sphere.lightning", "H74-SELF-BUFF")
    me = engine.state.actors[ME]
    body = next(a for a in engine.action_catalog.values() if a.display_name == "Lightning-God Body")
    policy = PolicyLibrary(ROOT).for_actor(ME)[0]
    assert _offered_to_ai(engine, policy, body), "no buff up yet: the AI must be free to cast it"
    _commit(engine, "Lightning-God Body")
    assert any(c.condition_id for c in me.conditions.values()), "the buff is up, so the AI must see it"
    _turn_of(engine)  # a later turn: Lightning-God Body lasts 1 minute, well past one round
    assert not _offered_to_ai(engine, policy, body), \
        "Lightning-God Body lasts 1 minute: re-casting it every turn only spent the Resonance pool"


def _turn_of(engine) -> None:
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()


def _offered_to_ai(engine, policy, action) -> bool:
    """Whether the AI's own menu still offers a technique (combat/gate4_context.py build_decision_context, for_ai)."""
    menu = build_decision_context(engine, policy, for_ai=True).legal_candidates
    return any(c.source_definition_id == action.source_definition_id for c in menu)


def test_a_self_buff_carrying_a_damage_rider_that_fires_on_a_later_hit_is_still_a_self_buff():
    """The rider is part of the buff, not the buff acting now: this is the predicate the row above exercises."""
    from combat.ext import ai_restraint

    class Action:
        target_kind = "SELF"
        parameters = {"typed": {"effects": [
            {"type": "speed", "applies_to": "self", "flat": 10},
            {"type": "extra_damage", "applies_to": "target", "dice": {"count": 1, "sides": 6}},
            {"type": "advantage", "applies_to": "self"}]}}

    assert ai_restraint._self_only(Action()), "a later-firing rider must not read as the buff acting on an enemy now"
    Action.parameters = {"typed": {"effects": [{"type": "attack"}]}}
    assert not ai_restraint._self_only(Action()), "a technique that attacks right now is not a self buff"
    Action.target_kind = "HOSTILE_ENTITY"
    Action.parameters = {"typed": {"effects": [{"type": "extra_damage", "applies_to": "target"}]}}
    assert not ai_restraint._self_only(Action()), "a technique aimed at a creature is not a self buff"


# ------------- finding 2 (review): the buff is left alone ONLY while it is up. It must come back afterwards.
def _buffed_fighter(seed):
    """A fighter that has just cast Lightning-God Body, one turn later, with the buff still up."""
    engine = _fight([LIGHTNING_GOD_BODY], "tianxia.sphere.lightning", seed)
    body = next(a for a in engine.action_catalog.values() if a.display_name == "Lightning-God Body")
    _commit(engine, "Lightning-God Body")
    _turn_of(engine)
    assert not _offered_to_ai(engine, PolicyLibrary(ROOT).for_actor(ME)[0], body), "the buff is up, so the AI holds"
    return engine, body


def test_the_ai_offers_the_self_buff_again_once_its_one_minute_duration_has_run_out():
    """MMX50r finding 2: the restraint must be "while it lasts", not "for the rest of the fight". Lightning-God
    Body lasts 1 minute, which the rules' duration table carries on the round clock, so the engine's own expiry
    sweep takes the condition and its modifiers off at the round it names and the candidate must return."""
    from combat.ext import effect_durations

    engine, body = _buffed_fighter("H74-EXPIRY")
    me = engine.state.actors[ME]
    named = [str(condition.expires_on) for condition in me.conditions.values() if "SLOT_AT" in str(condition.expires_on)]
    assert named, "a 1-minute buff is carried by the round clock, so it carries a round token"
    round_now, _, slot = named[0].partition(":")[2].partition(":")
    engine.state.round_number, engine.state.current_slot_index = int(round_now), int(slot)
    effect_durations.sweep(engine, me, "START_OF_TURN")  # the engine's own expiry, emitting the same events
    assert not me.conditions and not me.modifiers, "the engine took the expired buff off"
    assert _offered_to_ai(engine, PolicyLibrary(ROOT).for_actor(ME)[0], body), \
        "with the buff gone the AI must be free to cast it again -- otherwise it never buffs up again"


def test_the_ai_offers_the_self_buff_again_after_manual_effect_removal():
    """Remove conditions and modifiers directly; this does not execute a dispel action."""
    engine, body = _buffed_fighter("H74-DISPEL")
    me = engine.state.actors[ME]
    for condition_id in {condition.condition_id for condition in me.conditions.values()}:
        engine._remove_condition(me, condition_id, "system:typed.dispel")  # what a dispel does
    for modifier_id in list(me.modifiers):
        del me.modifiers[modifier_id]
    assert _offered_to_ai(engine, PolicyLibrary(ROOT).for_actor(ME)[0], body), \
        "a dispelled buff is no buff: the AI must be free to cast it again"


def test_the_ai_still_offers_the_self_buff_again_after_model_serialization_and_reload():
    """Model serialization preserves the restraint; this does not commit through CombatService."""
    engine, body = _buffed_fighter("H74-RELOAD")
    committed = engine.state.model_dump(mode="json")
    committed.pop("schema_name", None)  # the persisted discriminator, not part of the state
    reloaded = _fight([LIGHTNING_GOD_BODY], "tianxia.sphere.lightning", "H74-RELOAD")
    reloaded.state = MatchState.model_validate(committed)
    me = reloaded.state.actors[ME]
    assert me.conditions and me.modifiers, "the buff is still up in the committed state"
    assert not _offered_to_ai(reloaded, PolicyLibrary(ROOT).for_actor(ME)[0], body), \
        "a reloaded table must not re-cast a buff that is still running"
    for condition_id in {condition.condition_id for condition in me.conditions.values()}:
        reloaded._remove_condition(me, condition_id, "system:typed.dispel")
    for modifier_id in list(me.modifiers):
        del me.modifiers[modifier_id]
    reloaded.state.round_number, reloaded.state.current_slot_index = 1, reloaded.state.current_slot_index
    reloaded.state.current_actor_id = ME
    reloaded._system_start_turn()
    assert _offered_to_ai(reloaded, PolicyLibrary(ROOT).for_actor(ME)[0], body), \
        "and once the buff is gone, the reloaded table's AI offers it again"



# ------------------------------------------------------------------ finding 3: a creature named "You" reads right
def test_decision_text_agrees_its_verb_with_a_creature_named_you():
    damage = {"checkpoint": "TYPED:DAMAGE_APPLICATION@5",
              "choice_trigger": {"damage_amount": 5, "target_id": "a2", "action_name": "Fire Bolt", "actor_id": "a1"}}
    prompt, definitions = {"reactor": "a2"}, {}
    actors = {"a1": "Ember Wisp", "a2": "You"}
    line = decision_text.trigger_text(damage, prompt, actors, definitions)
    assert "You are about to take 5 damage" in line, line
    assert "You is" not in line, line
    assert decision_text.trigger_text(damage, prompt, {"a1": "Ember Wisp", "a2": "Iron Boar"}, definitions) \
        == "Iron Boar is about to take 5 damage from Ember Wisp's Fire Bolt."  # a named creature is unchanged


def test_the_saving_throw_prompt_agrees_its_verb_with_a_creature_named_you():
    context = {"checkpoint": "TYPED:D20_PENDING@9", "choice_trigger": {
        "roll_kind": "save", "save_ability": "dex", "target_id": "a2", "actor_id": "a1", "action_name": "Fire Bolt"}}
    line = decision_text.trigger_text(context, {"reactor": "a2"}, {"a1": "Ember Wisp", "a2": "You"}, {})
    assert "You are about to make a Dexterity saving throw" in line, line

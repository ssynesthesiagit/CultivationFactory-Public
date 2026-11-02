"""Lane H1, family 6: Fortune Reversal (a natural 1 or 20 flipped), Bell-Shell Guard's reroll of a sound-caused failed save, Perfect
Counter-Evolution's Affliction Response, Chain-Breaker's Lesson and Famine Saint Intercession (a Foundation pool)."""

from combat.gate2_runtime_models import ConcentrationState
from combat.typed_executor import CONDITION_PREFIX
from tests.h1_support import ALLY, FOE, ME, amount, attack, duel, force_save, give, held, rewrites, script, use

FORTUNE = "TAL_FATE_FORTUNE_REVERSAL"
BELL = "TAL_SOUND_BELL_SHELL_GUARD"
COUNTER = "tianxia.subpath.body.heaven_answering_adaptive_body.feature.perfect_counter_evolution"
CHAIN_BREAKER = "tianxia.talent.chains.chain_breaker_s_lesson"
FAMINE = "foundation.FOUNDATION_03_EMPTY_BOWL_SOUL_ANCHOR.famine_saint_intercession"
GRAPPLED = CONDITION_PREFIX + "grappled"
DC = 16  # every saving throw modifier is +2


# ------------------------------------------------------------------------------------------------------------ Fortune Reversal
def test_fortune_reversal_turns_an_allys_natural_one_into_a_twenty_once_a_fight_for_six_cp_and_a_heavens_notice():
    engine = duel(FORTUNE, ally_mids=[])
    give(engine, ME, heaven_s_notice=0)
    script(engine, [1])
    roll = force_save(engine, ALLY, "DEX", dc=DC)
    (rewrite,) = rewrites(engine)
    assert rewrite.source_definition_id == FORTUNE and rewrite.payload["result"]["natural_result"] == 20 and roll.total == 22
    assert amount(engine, ME, "qi") == 24 and amount(engine, ME, "heaven_s_notice") == 1 and not engine.state.actors[ME].reaction_available
    engine.state.actors[ME].reaction_available = True
    script(engine, [1])
    force_save(engine, ALLY, "DEX", dc=DC)          # once per short rest: a fight
    assert len(rewrites(engine)) == 1


def test_fortune_reversal_turns_a_foes_natural_twenty_hit_into_a_one_unless_its_charisma_save_holds():
    engine = duel(FORTUNE, ally_mids=[])
    script(engine, [20, 3])          # a natural 20 against the ally, then the foe's failed Charisma save (DC 8 + 4 + 2 = 14)
    assert attack(engine, FOE, ALLY, bonus=5, ac=15) is False
    (rewrite,) = rewrites(engine)
    assert rewrite.payload["result"]["natural_result"] == 1
    engine = duel(FORTUNE, ally_mids=[])
    give(engine, ME, heaven_s_notice=0)
    script(engine, [20, 19])         # the Charisma save holds: the roll stands, the cost and the Notice are paid
    assert attack(engine, FOE, ALLY, bonus=5, ac=15) is True
    assert not rewrites(engine) and amount(engine, ME, "qi") == 24 and amount(engine, ME, "heaven_s_notice") == 1


def test_fortune_reversal_needs_a_natural_one_or_twenty_that_the_flip_turns_our_way_within_sixty_feet():
    engine = duel(FORTUNE, ally_mids=[])
    script(engine, [2, 20, 1])
    force_save(engine, ALLY, "DEX", dc=DC)          # a 2: not a natural 1
    force_save(engine, ALLY, "DEX", dc=DC)          # an ally's natural 20: flipping it would hurt
    force_save(engine, FOE, "DEX", dc=DC)           # a foe's natural 1: already good for us
    assert not rewrites(engine) and amount(engine, ME, "qi") == 30
    engine.state.actors[ALLY].position = engine.state.actors[ALLY].position.model_copy(update={"x": 20})   # 85 feet away
    script(engine, [1])
    force_save(engine, ALLY, "DEX", dc=DC)
    assert not rewrites(engine)


# ------------------------------------------------------------------------------------------------------------ Bell-Shell Guard
def _concentrating(engine, actor_id):
    engine.state.actors[actor_id].concentration = ConcentrationState(source_definition_id="test:held", started_sequence=len(engine.events))


def test_bell_shell_guard_rerolls_an_allys_concentration_save_lost_to_thunder_for_one_cp():
    engine = duel(BELL, ally_mids=[])
    _concentrating(engine, ALLY)
    script(engine, [3, 17])          # DC 10: 3 + 2 fails, the reroll 17 + 2 holds
    engine._commit_damage(engine.state.actors[ALLY], 8, "THUNDER", "test:thunder", FOE, None, reaction_depth=0)
    (rewrite,) = rewrites(engine)
    assert rewrite.source_definition_id == BELL and rewrite.actor_id == ALLY
    assert engine.state.actors[ALLY].concentration is not None and amount(engine, ME, "qi") == 29
    assert not engine.state.actors[ME].reaction_available


def test_bell_shell_guard_ignores_a_concentration_save_lost_to_other_damage():
    engine = duel(BELL, ally_mids=[])
    _concentrating(engine, ALLY)
    script(engine, [3])
    engine._commit_damage(engine.state.actors[ALLY], 8, "SLASHING", "test:blade", FOE, None, reaction_depth=0)
    assert not rewrites(engine) and engine.state.actors[ALLY].concentration is None


def test_bell_shell_guard_rerolls_a_failed_save_that_would_deafen():
    engine = duel(BELL)
    me = engine.state.actors[ME]
    script(engine, [4, 18])
    force_save(engine, ME, "CON", dc=DC, typed=True, condition="deafened")
    assert len(rewrites(engine)) == 1 and not any("deafened" in c.condition_id for c in me.conditions.values())
    me.reaction_available = True
    script(engine, [4])
    force_save(engine, ME, "CON", dc=DC, typed=True, condition="poisoned")   # not a sound effect
    assert len(rewrites(engine)) == 1


# ------------------------------------------------------------------------------------------------ Perfect Counter-Evolution
def test_perfect_counter_evolution_rerolls_a_failed_save_that_would_stun_for_two_stamina_once_a_round():
    engine = duel(COUNTER, primary="Stamina", cl=18)
    give(engine, ME, stamina=5)
    me = engine.state.actors[ME]
    script(engine, [5, 19])
    force_save(engine, ME, "CON", dc=DC, typed=True, condition="stunned")
    (rewrite,) = rewrites(engine)
    assert rewrite.source_definition_id == COUNTER and amount(engine, ME, "stamina") == 3
    assert not any("stunned" in c.condition_id for c in me.conditions.values()) and not me.reaction_available
    assert any(c.condition_id == "condition:typed.adaptations" and c.data["afflictions"][0]["condition"] == "stunned" for c in me.conditions.values())
    me.reaction_available = True
    script(engine, [5, 19])
    force_save(engine, ME, "CON", dc=DC, typed=True, condition="stunned")    # once per round
    assert len(rewrites(engine)) == 1


def test_perfect_counter_evolution_ignores_a_condition_it_cannot_adapt_to():
    engine = duel(COUNTER, primary="Stamina", cl=18)
    give(engine, ME, stamina=5)
    script(engine, [5])
    force_save(engine, ME, "DEX", dc=DC, typed=True, condition="prone")
    assert not rewrites(engine) and amount(engine, ME, "stamina") == 5


# ------------------------------------------------------------------------------------------------------ Chain-Breaker's Lesson
def _grappled(engine):
    engine._apply_condition(engine.state.actors[ME], GRAPPLED, "test:grip", FOE, expires_on="UNTIL_REMOVED", data={"escape_dc": 15})


def test_chain_breakers_lesson_rerolls_a_failed_escape_check_once_a_fight():
    engine = duel(CHAIN_BREAKER)
    me = engine.state.actors[ME]
    me.current_hp = 40               # hurt: the AI spends a once-a-fight reroll
    _grappled(engine)
    script(engine, [3, 18])          # 3 + 2 fails DC 15; the reroll 18 + 2 escapes
    use(engine, "Escape grapple")
    (rewrite,) = rewrites(engine)
    assert rewrite.source_definition_id == CHAIN_BREAKER and not held(me, GRAPPLED)
    _grappled(engine)
    me.action_available = True
    script(engine, [3])
    use(engine, "Escape grapple")    # once per short rest: a fight
    assert len(rewrites(engine)) == 1 and held(me, GRAPPLED)


def test_chain_breakers_lesson_ignores_a_save_that_is_not_an_escape():
    engine = duel(CHAIN_BREAKER)
    engine.state.actors[ME].current_hp = 40
    _grappled(engine)
    script(engine, [3])
    force_save(engine, ME, "DEX", dc=DC)
    assert not rewrites(engine)


# ------------------------------------------------------------------------------------------------ Famine Saint Intercession
def _famine():
    foundation = {"foundation_id": "FOUNDATION_03_EMPTY_BOWL_SOUL_ANCHOR", "stage": "Refined",
                  "resource": {"name": "Empty Bowl Mark", "resource_id": "tianxia.foundation.empty_bowl.mark", "maximum": 1, "current": 1}}
    engine = duel(FAMINE, ally_mids=[], foundation=foundation)
    assert engine.state.actors[ME].resources["resource:foundation.empty_bowl_mark"] == 1   # the Foundation's own pool pays
    return engine


def test_famine_saint_intercession_rerolls_an_allys_failed_fear_save_and_a_success_gives_temporary_hp():
    engine = _famine()
    ally = engine.state.actors[ALLY]
    script(engine, [3, 17])          # 3 + 2 fails DC 16; 17 + 2 succeeds
    force_save(engine, ALLY, "WIS", dc=DC, typed=True, condition="frightened")
    (rewrite,) = rewrites(engine)
    assert rewrite.source_definition_id == FAMINE and rewrite.actor_id == ALLY
    assert engine.state.actors[ME].resources["resource:foundation.empty_bowl_mark"] == 0 and not engine.state.actors[ME].reaction_available
    assert ally.temporary_hp == 6    # Proficiency Bonus 4 + key ability modifier 2
    assert not any("frightened" in c.condition_id for c in ally.conditions.values())


def test_famine_saint_intercession_leaves_a_save_outside_its_scope_and_needs_the_mark():
    engine = _famine()
    script(engine, [3])
    force_save(engine, ALLY, "WIS", dc=DC, typed=True, condition="charmed")   # not fear, despair, exhaustion or hunger
    assert not rewrites(engine)
    engine.state.actors[ME].resources["resource:foundation.empty_bowl_mark"] = 0
    script(engine, [3])
    force_save(engine, ALLY, "WIS", dc=DC, typed=True, condition="frightened")
    assert not rewrites(engine)

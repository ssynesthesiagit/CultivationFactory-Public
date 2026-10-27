"""Whole-packet reductions on a native mixed-damage hit (Mantis F13 review fixes).

Two shipped defenses state one flat amount for the hit they defend: Berserk's
"apply this reduction before Resistance" (a reduction_before_resistance row) and
Stand Against the Calamity's "allies inside reduce all damage taken by your
Proficiency Bonus" (a damage_reduction plug-in). A native thousand-cuts packet asks
the same creature to defend components of different damage types, so those
amounts must be spent once for the whole hit: applying the Berserk row per
component takes it off twice, and the old per-hook cap spent the Calamity
reduction on a single damage type and discarded the rest. A component the target
is immune to deals nothing, so it holds no share of either amount and the
reducible part keeps the whole reduction.

Both regressions drive the real providers through
typed_reactions.defend_components, the seam combat/gate2_engine.py uses whenever a
hit carries components.
"""
from combat import typed_reactions
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent
from tests.auto_worker1_support import settle
from tests.hunt15_support import ALLY, LEFT, act, fight, turn
from tests.test_auto_body import ME, _bundle, _engine
from tests.test_zones import SHEET

CALAMITY = 'TAL_GUARDIAN_STAND_AGAINST_THE_CALAMITY'
PRACTICE = 'GUARDIAN_BASE_CHALLENGE_PRACTICE'
LABEL = 'Stand Against the Calamity'
STATE = 'condition:typed.state.stand_against_the_calamity'
PB = SHEET['identity']['proficiency_bonus']


def test_mixed_hit_applies_berserks_before_resistance_reduction_once():
    """Berserk states one -PB for the hit, before Resistance, not one -PB per damage type."""
    engine = _engine(_bundle(['TAL_BERSERKER_BERSERK'], spheres=('tianxia.sphere.berserker',)),
                     {ME: {'x': 3, 'y': 6}, AN: {'x': 4, 'y': 6}})
    me = engine.state.actors[ME]
    choose = next(c for c in engine.legal_candidates() if c.display_name == 'Adrenaline: Berserk')
    engine.execute_intent(ActionIntent(intent_id='adrenaline', decision_id=choose.decision_id,
                                       candidate_id=choose.candidate_id, state_version=choose.state_version,
                                       actor_id=ME, target_ids=choose.target_ids))
    assert typed_reactions.defend(engine, me, 10, 'BLUDGEONING', None, None) == 10 - PB
    whole = typed_reactions.defend_components(engine, me, [(10, 'BLUDGEONING'), (20, 'PIERCING')], None, None)
    assert whole == 30 - PB, "the whole hit loses Berserk's reduction once, not once per component"


def _berserk(positions):
    """The real Berserk provider: spend Adrenaline to hold its before-Resistance reduction."""
    engine = _engine(_bundle(['TAL_BERSERKER_BERSERK'], spheres=('tianxia.sphere.berserker',)), positions)
    choose = next(c for c in engine.legal_candidates() if c.display_name == 'Adrenaline: Berserk')
    engine.execute_intent(ActionIntent(intent_id='adrenaline', decision_id=choose.decision_id,
                                       candidate_id=choose.candidate_id, state_version=choose.state_version,
                                       actor_id=ME, target_ids=choose.target_ids))
    return engine


def test_a_component_the_target_is_immune_to_takes_no_share_of_the_whole_hit_reduction():
    """Berserk's reduction still lands on the reducible component beside an immune one, in either order.

    Printed Immunity to one damage type is the ``damage_immunity`` modifier every real immunity provider writes
    (combat/ext creatures included), so an immune component deals nothing at all and holds no share of the
    one-per-hit reduction: the Piercing part keeps losing Berserk's -PB.
    """
    for order in ([(10, 'BLUDGEONING'), (20, 'PIERCING')], [(20, 'PIERCING'), (10, 'BLUDGEONING')]):
        engine = _berserk({ME: {'x': 3, 'y': 6}, AN: {'x': 4, 'y': 6}})
        me = engine.state.actors[ME]
        engine._add_modifier(me, 'test:printed-immunity', 'damage_immunity', 'ADD', 'BLUDGEONING', 'ALWAYS',
                             expires_on=None)
        assert typed_reactions.defend(engine, me, 10, 'BLUDGEONING', None, None) == 0
        assert typed_reactions.defend_components(engine, me, order, None, None) == 20 - PB


def test_mixed_hit_spends_calamitys_reduction_across_every_covered_component(tmp_path):
    """Stand Against the Calamity pays its full PB across the hit, even when no component alone can absorb it."""
    combat, table, mid = fight(tmp_path, left=[PRACTICE, CALAMITY], right=[], ally=[], effects=[])
    turn(table, mid, LEFT)
    settle(lambda answers: act(table, mid, LABEL, answers))
    engine = combat._load_session(mid).engine
    ally = engine.state.actors[ALLY]
    assert any(condition.condition_id == STATE for condition in engine.state.actors[LEFT].conditions.values())
    whole = typed_reactions.defend_components(engine, ally, [(3, 'BLUDGEONING'), (3, 'PIERCING')], None, None)
    assert whole == 6 - PB, 'the reduction covers both components and never discards its leftover points'

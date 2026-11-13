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

A third defense states its amount per attack rather than per damage type:
Sovereign Shield-Soul Incarnation's "reduce damage from the triggering attack by
your Proficiency Bonus before Resistance". It answers the ``incoming_attack_damage``
hook, whose contract is one amount for the triggering attack, so a native hit
spends it once across the packet.

Berserk's row and the Incarnation's plug-in both state one amount for the
triggering attack, so they are two answers to one question and share the hit's
ledger: stacking them must not charge the same damage twice. A component shorter
than the two amounts together (3 Bludgeoning under two Proficiency Bonuses) hands
the rest of either amount to the components that still take damage, instead of
spending both amounts on damage that exists only once.

The direct regressions drive the real providers through
typed_reactions.defend_components, the seam combat/gate2_engine.py uses whenever a
hit carries components; the Incarnation ones play the real fight at the table and
read the packet its own damage commit recorded. The reviewed small-component case
is played on the same seam with both providers up, because the fight's own
Bludgeoning component is longer than the two amounts together.
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


def test_exact_counterweight_sees_and_settles_one_committed_mixed_hit():
    """A real paid response reduces the full Mantis packet, not its first component."""
    from combat.gate2_runtime_models import ActionIntent, RollRecord
    from tests.test_riders_c8 import EM_ALL, ME as KEEPER, FOE as MANTIS, MEASURE
    from tests.test_riders_c8 import answers, fight as spirit_fight, turn as spirit_turn

    engine = spirit_fight(EM_ALL, foe_at=(4, 6), pb=2)
    keeper, mantis = engine.state.actors[KEEPER], engine.state.actors[MANTIS]
    spirit_turn(engine, MANTIS)
    keeper.resources[MEASURE["impact"]] = 1
    keeper.resources["resource:core.resonance"] = 2
    keeper.reaction_available = True
    answers(engine, {"equal_measure.impact_counterweight": ("reduce",)})
    engine.roller.roll = lambda spec, **kw: RollRecord(
        roll_id="mixed-counterweight", counter_start=1, counter_end=2, expression="3d8",
        actor_id=kw.get("actor_id"), reason=kw.get("reason") or "", dice=(8, 8, 8),
        modifier=1, total=25, natural_result=None)
    candidate = next(c for c in engine.legal_candidates() if c.actor_id == MANTIS)
    intent = ActionIntent(intent_id="mantis-mixed-packet", decision_id=candidate.decision_id,
                          candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                          actor_id=MANTIS, target_ids=(KEEPER,))
    start = len(engine.events)
    engine._active_intent = intent
    engine._typed_pending_damage_type = "MIXED"
    try:
        engine._commit_damage(keeper, 30, "MIXED", source_definition_id=
                              "tianxia.subpath.body.mantis_style.feature.death_of_a_thousand_cuts",
                              source_actor_id=MANTIS, intent=intent, reaction_depth=0,
                              components=[(10, "BLUDGEONING"), (20, "PIERCING")])
    finally:
        engine._active_intent = None
    events = engine.events[start:]
    packet = next(e.payload for e in events if e.event_type == "DAMAGE_COMMITTED")
    assert packet["damage_type"] == "MIXED" and packet["reduced_to"] == 5
    assert not any(e.event_type == "DAMAGE_COMMITTED" and MANTIS in e.target_ids and e.actor_id == KEEPER
                   for e in events), "25 reduction does not fully stop a 30-damage hit, so no retaliation"
    assert keeper.resources[MEASURE["impact"]] == 0
    assert keeper.resources["resource:core.resonance"] == 0 and not keeper.reaction_available


def test_paid_instance_defense_receives_packet_after_positive_damage_bonus(monkeypatch):
    """The full positive per-component addition is visible to a whole-instance defense."""
    from combat import ext

    engine = _engine(_bundle([], spheres=()), {ME: {'x': 3, 'y': 6}, AN: {'x': 4, 'y': 6}})
    target = engine.state.actors[ME]
    original_run, original_strict = ext.run, ext.run_strict
    seen = []

    def run(point, *args, **kwargs):
        return [3] if point == "incoming_damage_bonus" else original_run(point, *args, **kwargs)

    def run_strict(point, *args, **kwargs):
        if point == "incoming_damage_instance":
            seen.append(args[2])
            return [{"BLUDGEONING": 5}]
        return original_strict(point, *args, **kwargs)

    monkeypatch.setattr(ext, "run", run)
    monkeypatch.setattr(ext, "run_strict", run_strict)
    assert typed_reactions.defend_components(engine, target, [(10, "BLUDGEONING")], None, None) == 8
    assert seen == [(("BLUDGEONING", 13),)]


def test_paid_instance_defense_does_not_charge_immune_component(monkeypatch):
    """An immune component is absent from the paid whole-instance defense's packet."""
    from combat import ext

    engine = _engine(_bundle([], spheres=()), {ME: {'x': 3, 'y': 6}, AN: {'x': 4, 'y': 6}})
    target = engine.state.actors[ME]
    engine._add_modifier(target, 'test:printed-immunity', 'damage_immunity', 'ADD', 'BLUDGEONING', 'ALWAYS',
                         expires_on=None)
    original_strict = ext.run_strict
    seen = []

    def run_strict(point, *args, **kwargs):
        if point == "incoming_damage_instance":
            seen.append(args[2])
            return [{"PIERCING": 5}]
        return original_strict(point, *args, **kwargs)

    monkeypatch.setattr(ext, "run_strict", run_strict)
    assert typed_reactions.defend_components(engine, target,
                                             [(10, "BLUDGEONING"), (20, "PIERCING")], None, None) == 15
    assert seen == [(("PIERCING", 20),)]


def test_paid_instance_defense_sees_signed_damage_taken_bonus(monkeypatch):
    """A counter-style defense sees the final amount after a signed damage-taken bonus."""
    from combat import ext

    engine = _engine(_bundle([], spheres=()), {ME: {'x': 3, 'y': 6}, AN: {'x': 4, 'y': 6}})
    target = engine.state.actors[ME]
    original_run, original_strict = ext.run, ext.run_strict
    seen = []

    def run(point, *args, **kwargs):
        return [-4] if point == "incoming_damage" else original_run(point, *args, **kwargs)

    def run_strict(point, *args, **kwargs):
        if point == "incoming_damage_instance":
            packet = args[2]
            seen.append(packet)
            return [{kind: amount for kind, amount in packet}]
        return original_strict(point, *args, **kwargs)

    monkeypatch.setattr(ext, "run", run)
    monkeypatch.setattr(ext, "run_strict", run_strict)
    assert typed_reactions.defend_components(engine, target, [(10, "BLUDGEONING")], None, None) == 0
    assert seen == [(("BLUDGEONING", 14),)]


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

INCARNATION = 'TAL_SHIELD_SOVEREIGN_SHIELD_SOUL_INCARNATION'
PROJECTED_FACE = 'tianxia.talent.shield.projected_shield_face'
SHIELD_KIT = {'items': [{'item_id': 'tianxia.mortal.armor.lacquered_lamellar', 'name': 'Lacquered Lamellar', 'quantity': 1},
                        {'item_id': 'tianxia.mortal.armor.shield', 'name': 'Shield', 'quantity': 1},
                        {'item_id': 'tianxia.mortal.weapon.bi_shou', 'name': 'Bi Shou (Dagger)', 'quantity': 1}]}


def test_a_mixed_native_hit_loses_an_attack_wide_reduction_once(tmp_path):
    """Sovereign Shield-Soul Incarnation takes its Proficiency Bonus off the triggering attack once.

    The printed line reduces "damage from the triggering attack ... before Resistance", so a hit that carries a
    Bludgeoning and a Piercing component loses one Proficiency Bonus, not one per damage type. The shipped mixed
    packet is a real Mantis Death of a Thousand Cuts strike; the real Incarnation is activated on the defender's
    own turn through the table. It answers ``incoming_attack_damage``, which the hit asks once per component, so a
    plug-in that repeated its stated amount per damage type would take double here.
    """
    from tests.mantis_native_support import DECLINE, P, hit, native
    from tests.worker2_support import FOE as DEFENDER, OWNER as MANTIS
    from tests.worker2_support import candidate, reload, settle, turn

    combat, table, mid = native(tmp_path, foe_talents=(INCARNATION, PROJECTED_FACE), foe_kit=SHIELD_KIT)
    turn(table, mid, DEFENDER)
    settle(table, mid, candidate(combat, mid, 'SOVEREIGN SHIELD-SOUL INCARNATION').candidate_id)
    from combat.ext import shield_incarnation

    engine = combat._load_session(mid).engine
    assert shield_incarnation.incarnate(engine, engine.state.actors[DEFENDER]), \
        'the defender enters the Incarnation before the hit it reduces'
    turn(table, mid, MANTIS)
    hit(combat, table, mid, picks={**DECLINE, 'choice:needle.iron_fist_damage_type': 'BLUDGEONING',
                                   'choice:needle.path_hit.' + P + 'death_of_a_thousand_cuts': 'No Reactions'})
    engine = reload(tmp_path, mid)
    assert [event for event in engine.events if event.event_type == 'REACTION_WINDOW_OPENED'
            and event.source_definition_id == 'SHIELD_BASE_ACTIVE_DEFENSE' and event.actor_id == DEFENDER], \
        'Active Defense answers this attack, so the Incarnation reduction applies to it'
    packets = [event.payload for event in engine.events if event.event_type == 'DAMAGE_COMMITTED'
               and event.actor_id == MANTIS and event.target_ids == (DEFENDER,)]
    mixed = next(packet for packet in packets if packet['damage_type'] == 'MIXED')
    assert [component['damage_type'] for component in mixed['damage_components']] == ['BLUDGEONING', 'PIERCING']
    bonus = engine.state.actors[DEFENDER].proficiency_bonus
    assert mixed['reduced_to'] == mixed['rolled_or_pending_damage'] - bonus, \
        'the whole hit loses the attack-wide reduction once, not once per damage type'


BERSERK = 'TAL_BERSERKER_BERSERK'
ADRENALINE = 'Adrenaline: Berserk'
BERSERKED = 'condition:typed.body_adrenaline_berserk'
EXTENSIVE = 'TAL_SHIELD_EXTENSIVE_DEFENSE'
EXTENSIVE_STATE = 'condition:typed.extensive_defense'


def _stacked_defender(tmp_path):
    """A real fight whose defender holds both one-amount-for-the-hit reductions, with Active Defense answering.

    Berserk comes from the defender's own real Adrenaline toggle and the Incarnation from its real candidate,
    both driven through the table, so the strike below meets the shipped compiled row and the shipped plug-in
    exactly as a player's fight would.
    """
    from tests.mantis_native_support import DECLINE, P, hit, native
    from tests.worker2_support import FOE as DEFENDER, OWNER as MANTIS
    from tests.worker2_support import candidate, settle as driven, turn as advance

    combat, table, mid = native(tmp_path, control_modes={DEFENDER: 'MANUAL'},
                                foe_talents=(INCARNATION, PROJECTED_FACE, BERSERK), foe_kit=SHIELD_KIT)
    advance(table, mid, DEFENDER)
    driven(table, mid, candidate(combat, mid, ADRENALINE).candidate_id)
    driven(table, mid, candidate(combat, mid, 'SOVEREIGN SHIELD-SOUL INCARNATION').candidate_id)
    from combat.ext import shield_incarnation

    engine = combat._load_session(mid).engine
    defender = engine.state.actors[DEFENDER]
    assert shield_incarnation.incarnate(engine, defender), 'the Incarnation answers the Active Defense this hit meets'
    assert any(condition.condition_id == BERSERKED for condition in defender.conditions.values()), 'Berserk is active'
    advance(table, mid, MANTIS)
    hit(combat, table, mid, picks={**DECLINE, 'choice:needle.iron_fist_damage_type': 'BLUDGEONING',
                                   'choice:needle.path_hit.' + P + 'death_of_a_thousand_cuts': 'No Reactions'})
    return combat, mid, DEFENDER, MANTIS


def test_a_hit_answered_by_both_whole_hit_reductions_loses_each_of_them_once(tmp_path):
    """Stacking Berserk with the Incarnation reduces the hit by two Proficiency Bonuses, never by the same one twice.

    Both providers state one amount for the triggering attack (before Resistance), so a real Bludgeoning plus
    Piercing hit loses one amount per provider however the damage is split.
    """
    combat, mid, DEFENDER, MANTIS = _stacked_defender(tmp_path)
    engine = combat._load_session(mid).engine
    packets = [event.payload for event in engine.events if event.event_type == 'DAMAGE_COMMITTED'
               and event.actor_id == MANTIS and event.target_ids == (DEFENDER,)]
    mixed = next(packet for packet in packets if packet['damage_type'] == 'MIXED')
    bonus = engine.state.actors[DEFENDER].proficiency_bonus
    assert 2 * bonus < mixed['rolled_or_pending_damage'], 'the hit is large enough for both amounts to land in full'
    assert mixed['reduced_to'] == mixed['rolled_or_pending_damage'] - 2 * bonus, \
        'each whole-hit reduction takes its own amount off the hit; neither spends capacity the other already used'


def _stacked_engine():
    """A fighter holding both one-amount-for-the-hit reductions with Active Defense meeting the attack.

    The Berserk row comes from the real Adrenaline toggle. The Incarnation's state and Extensive Defense's state are
    written the way their shipped effects write them (combat/ext/shield_faces.py:105,
    combat/ext/shield_riders.py:451), including Extensive Defense's expiry, so the two providers below are the same
    two the real strike above meets: Active Defense answers this attack without a Reaction, and the Incarnation
    reduces the triggering attack.
    """
    from combat.ext import shield_faces

    engine = _engine(_bundle([BERSERK, INCARNATION, PROJECTED_FACE],
                             spheres=('tianxia.sphere.berserker', 'tianxia.sphere.shield')),
                     {ME: {'x': 3, 'y': 6}, AN: {'x': 4, 'y': 6}})
    berserk = next(c for c in engine.legal_candidates() if c.display_name == ADRENALINE)
    engine.execute_intent(ActionIntent(intent_id='adrenaline', decision_id=berserk.decision_id,
                                       candidate_id=berserk.candidate_id, state_version=berserk.state_version,
                                       actor_id=ME, target_ids=berserk.target_ids))
    me = engine.state.actors[ME]
    engine._apply_condition(me, shield_faces.SOVEREIGN, INCARNATION, me.entity_id, expires_on='START_OF_SOURCE_NEXT_TURN',
                            data={'label': 'Sovereign Shield-Soul Incarnation: the Incarnation is running'})
    engine._apply_condition(me, EXTENSIVE_STATE, EXTENSIVE, me.entity_id, expires_on='START_OF_SOURCE_NEXT_TURN',
                            data={'label': 'Extensive Defense: Active Defense against every attack without a Reaction'})
    return engine


def test_a_small_component_carries_the_rest_of_both_whole_hit_reductions():
    """The reviewed case: 3 Bludgeoning and 20 Piercing under Berserk and the Incarnation.

    The first component is shorter than the two amounts together (2 x Proficiency Bonus), so neither may charge
    it beyond the damage it holds: both spend what is there and carry the rest to the Piercing component, which
    still takes damage, leaving 23 - 2 x Proficiency Bonus. Charging each amount per damage type, or capping the
    plug-in at what one component could absorb, loses the difference.
    """
    from combat.damage_context import AttackDamage
    from combat.ext import shield_incarnation

    engine = _stacked_engine()
    me = engine.state.actors[ME]
    assert shield_incarnation.incarnate(engine, me) and any(
        condition.condition_id == BERSERKED for condition in me.conditions.values()), \
        'both one-amount-for-the-hit defenses are up before the hit lands'
    packet = AttackDamage('action:typed.test.mantis_mixed_hit', AN, ME, 1, 'roll:test', 15, 25, False)
    engine._damage_packet_context = packet
    try:
        taken = typed_reactions.defend_components(engine, me, [(3, 'BLUDGEONING'), (20, 'PIERCING')],
                                                  packet.source_id, AN)
    finally:
        engine._damage_packet_context = None
    assert taken == 23 - 2 * me.proficiency_bonus, \
        'both amounts land once in full; the emptied component holds no double charge'

def test_a_damage_value_reduction_keeps_a_mixed_hits_components_nonnegative(monkeypatch):
    """A reduction before defenses can be larger than one component, so the components shrink with it.

    ``damage_value_reduction`` (a native weapon's Dull) takes its points off the packet at the damage-roll stage,
    before any defense is asked, and the mixed hit then hands the components it still carries to
    typed_reactions.defend_components, which refuses a negative amount. Giving the whole difference to the first
    component leaves -4 Bludgeoning here (3 + 3 - 10) and crashes the hit; the reduction comes off the components
    in order instead, so they add up to the reduced packet and every one stays nonnegative.
    """
    from combat import ext

    assert ext.has('damage_value_reduction'), 'the native weapon damage seam is a shipped hook'
    engine = _engine(_bundle([], spheres=()), {ME: {'x': 3, 'y': 6}, AN: {'x': 4, 'y': 6}})
    target = engine.state.actors[ME]
    original_strict = ext.run_strict

    def run_strict(point, *args, **kwargs):
        return [7] if point == "damage_value_reduction" else original_strict(point, *args, **kwargs)

    monkeypatch.setattr(ext, "run_strict", run_strict)
    engine._commit_damage(target, 10, 'BLUDGEONING', 'action:typed.test.mantis_mixed_hit', AN, None,
                          reaction_depth=0, components=[(3, 'BLUDGEONING'), (7, 'PIERCING')])
    committed = [event for event in engine.events if event.payload.get('damage_components')][-1].payload
    assert committed['rolled_or_pending_damage'] == 3, 'the seam reduced the packet to what is left'
    assert [entry['amount'] for entry in committed['damage_components']] == [0, 3], \
        'the reduction comes off the components in order and none goes negative'

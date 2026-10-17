"""Daemonic Cultivation: Thousand-Hunger Adaptation and the Demon Mark land at the table.

AUTO103, with the AUTO103r1 and AUTO103r2f1 review fixes. Every case drives real compiled characters
through the table's own commits and fresh reloads, and asserts the printed rule rather than a marker:

* paying for the adaptation really halves the next packet of that type, and the prompt names the
  ability, the attack that caused it, the creature affected, the cost and the length;
* a NATIVE (non-typed) attack offers the same benefit, which a typed-only seam cannot see;
* at CL 11+ the Resistance lasts to the END of the owner's next turn, and below it only to its start;
* "Prerequisite: CL 5+" offers nothing at CL 4, and Demon Seed being down offers nothing at all;
* at CL 17 the next damage roll with a Daemonic talent deals additional damage OF THE ADAPTED TYPE --
  once, through a table commit and a reload, even when the Daemonic roll is of a different type, and
  never for a matching-type roll that is not a Daemonic talent's;
* that same clause is spent by the ROLL, so a type the target is immune to, a roll reduced to nothing
  and a roll that defeats the creature each consume it and still receive the additional damage, instead
  of leaving it waiting for some later roll;
* a manual owner is asked before its Essence is spent when an AI fighter attacks it -- on a freshly
  compiled row and on a row sealed before this marker alike -- while an AI owner answers for itself;
* an AI-controlled owner adapts without being asked, and the Demon Mark reaches the target itself.
"""
import pytest

from tests.cw2_service_support import add_action, seal
from tests.h1_support import sheet
from tests.test_r9i_karma_persistence import end_turn
from tests.worker2_support import (ALLY, FOE, OWNER, candidate, fixture, reload,
                                   sealed_native_attack, settle, turn)

P = 'TAL_DAEMONIC_CULTIVATION_'
ESSENCE = 'resource:named.devoured_essence'
ADAPTATION = P + 'THOUSAND_HUNGER_ADAPTATION'
SEED = P + 'DEMON_SEED'
MARK = P + 'DEMON_MARK'
SPEND_CHOICE = 'choice:spend.thousand_hunger_adaptation'
DEMON_SEED = 'condition:typed.stance.demon_seed'
PENDING = 'condition:typed.thousand_hunger_adaptation'


def cycle(table, mid, actor):
    """Wait for ``actor``'s NEXT turn: the open menu may still belong to whoever acted last."""
    for _ in range(16):
        end_turn(table, mid)
        if table.state(mid)['menu']['actor_id'] == actor:
            return
    raise AssertionError(f'{actor} never receives another turn')


def sow(combat, table, mid):
    """Put Demon Seed up, the printed gate on the whole talent."""
    engine = combat._load_session(mid).engine
    rows = [c for c in engine.legal_candidates()
            if getattr(engine.action_catalog.get(c.source_definition_id), 'display_name', '') == 'Demon Seed']
    assert rows, 'Demon Seed is a printed action on its owner'
    settle(table, mid, rows[0].candidate_id)


def _essence(bundles, count=4):
    for resource in bundles[0]['actor_template']['resources']:
        if resource['resource_id'] == ESSENCE:
            resource.update(initial=count, maximum=10)


def _scorch(bundles):
    """The owner starts with Essence to spend; the opponent gets two sealed Fire packets."""
    _essence(bundles)
    add_action(bundles[2], 'Scorch cultivator',
               [{'type': 'damage', 'flat': 12, 'applies_to': 'target', 'damage_types': ['fire']}])
    add_action(bundles[2], 'Scorch again',
               [{'type': 'damage', 'flat': 12, 'applies_to': 'target', 'damage_types': ['fire']}])
    seal(bundles[0])
    seal(bundles[2])


def _acid_lash(bundles):
    """One sealed NATIVE action that strikes twice for 6+1d2 Acid, so a halved packet is 3 or 4 and a
    whole one is 7 or 8, and both land inside the Resistance's own window."""
    _essence(bundles)
    sealed_native_attack(bundles[2], 'Acid lash', damage_type='ACID', count=1, sides=2, modifier=6, attacks=2)
    seal(bundles[0])


def _seeded(actor):
    return any(c.condition_id == DEMON_SEED for c in actor.conditions.values())


def _resists(actor, kind):
    return [m for m in actor.modifiers.values()
            if m.target_field == 'damage_resistance' and m.value == kind.upper()]


def _asked(prompts):
    return [p for p in prompts if (p.get('context') or {}).get('reaction_source_id') == SPEND_CHOICE]


def _own_words(prompt):
    """The ability's own sentence, as opposed to the transport's line about whose turn it is."""
    return str(prompt.get('trigger') or '')


def _prompt_text(prompt):
    return ' '.join(str(part) for part in (
        prompt.get('reaction', ''), _own_words(prompt), prompt.get('action', ''),
        (prompt.get('choice') or {}).get('prompt') or '',
        ' '.join(o.get('label', '') for o in (prompt.get('choice') or {}).get('options') or ())))


def _packets(engine, actor_id):
    """(damage type, committed amount) of every damage packet this creature took, in order."""
    return [(str(e.payload.get('damage_type') or ''), int(e.payload.get('reduced_to') or 0))
            for e in engine.events if e.event_type == 'DAMAGE_COMMITTED' and actor_id in (e.target_ids or ())]


def _fire_bonus(engine, victim_id):
    """The adaptation's own packets against this creature: damage of the adapted type, attributed to it."""
    return [int(e.payload.get('reduced_to') or 0) for e in engine.events
            if e.event_type == 'DAMAGE_COMMITTED' and victim_id in (e.target_ids or ())
            and str(e.payload.get('damage_type') or '').upper() == 'FIRE'
            and (e.payload.get('display_source_id') or '') == ADAPTATION]


def session_ok(combat, mid):
    """The saved fight still verifies and replays from disk after the steps above."""
    session = combat._load_session(mid)
    return session.verify()['status'] == 'PASS' and session.mechanical.replay()['status'] == 'PASS'


def test_paying_halves_the_next_packet_of_that_type_and_names_the_attack(tmp_path):
    combat, table, mid = fixture(tmp_path, [ADAPTATION, SEED], bundle_transform=_scorch,
                                 foe_position={'x': 4, 'y': 7})
    sow(combat, table, mid)
    assert _seeded(reload(tmp_path, mid).state.actors[OWNER]), 'Demon Seed must be active'

    turn(table, mid, FOE)
    prompts = settle(table, mid, candidate(combat, mid, 'Scorch cultivator', target=OWNER).candidate_id,
                     {SPEND_CHOICE: '1'})
    asked = _asked(prompts)
    assert asked, f'the owner was never asked: {[p.get("reaction") for p in prompts]}'
    owner_name = reload(tmp_path, mid).state.actors[OWNER].display_name
    words = _own_words(asked[0])
    text = _prompt_text(asked[0])
    # Rule 13 plus the review: the ability's own sentence names the ability, the attack that caused
    # it, the damage type and the creature hit; the prompt also says what it costs and how it helps.
    for word in ('Thousand-Hunger Adaptation', 'fire', owner_name, 'Scorch cultivator'):
        assert word.lower() in words.lower(), f'{word!r} missing from the prompt: {words}'
    for word in ('Devoured Essence', 'halved', 'next turn'):
        assert word.lower() in text.lower(), f'{word!r} missing from the prompt: {text}'

    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    assert owner.resources[ESSENCE] == 3, 'the printed cost of 1 Devoured Essence must actually be paid'
    assert _packets(engine, OWNER) == [('FIRE', 12)], 'the packet that triggered it lands at full damage'
    assert _resists(owner, 'fire'), 'Resistance to the damage type just taken must be real'

    # Same turn, so the printed window has not closed: the next Fire packet is halved for real.
    settle(table, mid, candidate(combat, mid, 'Scorch again', target=OWNER).candidate_id,
           {SPEND_CHOICE: None})
    engine = reload(tmp_path, mid)
    assert _packets(engine, OWNER) == [('FIRE', 12), ('FIRE', 6)], \
        f'12 Fire damage must become 6 while the Resistance lasts: {_packets(engine, OWNER)}'
    assert engine.state.actors[OWNER].resources[ESSENCE] == 3, 'a declined offer spends nothing'
    assert session_ok(combat, mid)


def test_passing_keeps_the_essence(tmp_path):
    combat, table, mid = fixture(tmp_path, [ADAPTATION, SEED], bundle_transform=_scorch,
                                 foe_position={'x': 4, 'y': 7})
    sow(combat, table, mid)
    turn(table, mid, FOE)
    prompts = settle(table, mid, candidate(combat, mid, 'Scorch cultivator', target=OWNER).candidate_id,
                     {SPEND_CHOICE: None})
    assert _asked(prompts), 'the printed benefit is optional, so the owner must still be asked'
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[ESSENCE] == 4, 'passing must not spend anything'
    assert not _resists(engine.state.actors[OWNER], 'fire'), 'passing must not grant Resistance'


def test_adaptation_offers_nothing_while_demon_seed_is_down(tmp_path):
    combat, table, mid = fixture(tmp_path, [ADAPTATION], bundle_transform=_scorch,
                                 foe_position={'x': 4, 'y': 7})
    turn(table, mid, FOE)
    prompts = settle(table, mid, candidate(combat, mid, 'Scorch cultivator', target=OWNER).candidate_id)
    assert not _asked(prompts), 'the printed gate is "while Demon Seed is active"'
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[ESSENCE] == 4
    assert not _resists(engine.state.actors[OWNER], 'fire')


def test_adaptation_offers_nothing_below_the_cl5_prerequisite(tmp_path):
    combat, table, mid = fixture(tmp_path, [ADAPTATION, SEED], cl=4, bundle_transform=_scorch,
                                 foe_position={'x': 4, 'y': 7})
    sow(combat, table, mid)
    turn(table, mid, FOE)
    prompts = settle(table, mid, candidate(combat, mid, 'Scorch cultivator', target=OWNER).candidate_id)
    assert not _asked(prompts), 'the printed prerequisite is CL 5+'
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[ESSENCE] == 4
    assert not _resists(engine.state.actors[OWNER], 'fire')


def test_native_damage_offers_the_same_benefit(tmp_path):
    """A native attack never reaches a typed damage seam, so this is the regression for that."""
    combat, table, mid = fixture(tmp_path, [ADAPTATION, SEED], bundle_transform=_acid_lash,
                                 foe_position={'x': 4, 'y': 7})
    sow(combat, table, mid)
    turn(table, mid, FOE)
    prompts = settle(table, mid, candidate(combat, mid, 'Acid lash', target=OWNER).candidate_id,
                     decline_after=1)
    asked = _asked(prompts)
    assert asked, f'native damage offers nothing: {[p.get("reaction") for p in prompts]}'
    assert 'Acid lash' in _own_words(asked[0]), 'the prompt names the attack that caused it'
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[ESSENCE] == 3
    assert _resists(engine.state.actors[OWNER], 'acid')

    engine = reload(tmp_path, mid)
    first, second = _packets(engine, OWNER)
    assert first[0] == 'ACID' and first[1] in (7, 8), first
    assert second[0] == 'ACID' and second[1] in (3, 4), \
        f'6+1d2 Acid damage must be halved while the Resistance lasts: {second}'
    assert session_ok(combat, mid)


@pytest.mark.parametrize('cl,edge', [(5, 'start'), (11, 'end')])
def test_resistance_ends_at_the_printed_edge_of_the_next_turn(tmp_path, cl, edge):
    combat, table, mid = fixture(tmp_path, [ADAPTATION, SEED], cl=cl, bundle_transform=_scorch,
                                 foe_position={'x': 4, 'y': 7})
    sow(combat, table, mid)
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Scorch cultivator', target=OWNER).candidate_id,
           {SPEND_CHOICE: '1'})
    assert _resists(reload(tmp_path, mid).state.actors[OWNER], 'fire')
    # The boundary is the printed one, not the fight's own record: the owner's next turn.
    cycle(table, mid, OWNER)
    held = _resists(reload(tmp_path, mid).state.actors[OWNER], 'fire')
    assert bool(held) is (edge == 'end'), \
        f'CL {cl}: at CL 11+ the Resistance lasts until the end of the next turn, so it must still be up'
    cycle(table, mid, FOE)
    assert not _resists(reload(tmp_path, mid).state.actors[OWNER], 'fire'), \
        f'CL {cl}: the Resistance must be gone once the {"end" if edge == "end" else "start"} of that turn has passed'


def test_cl17_next_daemonic_roll_adds_the_adapted_type_once(tmp_path):
    def prepare(bundles):
        _scorch(bundles)
        # Demon Seed's printed hit rider adds 1d10 Necrotic/Psychic/Force once per turn on a hit: a
        # Daemonic talent's damage roll of a type that is NOT the adapted one.
        bundles[2]['actor_template']['armor_class'] = 1
        bundles[2]['actor_template']['saving_throws'] = {key: -100 for key in
                                                         bundles[2]['actor_template']['saving_throws']}
        seal(bundles[2])

    combat, table, mid = fixture(tmp_path, [ADAPTATION, SEED], cl=17, bundle_transform=prepare,
                                 foe_position={'x': 4, 'y': 7})
    sow(combat, table, mid)
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Scorch cultivator', target=OWNER).candidate_id,
           {SPEND_CHOICE: '1'})
    engine = reload(tmp_path, mid)
    pending = [c for c in engine.state.actors[OWNER].conditions.values() if c.condition_id == PENDING]
    assert len(pending) == 1, 'the CL 17 clause waits for the next Daemonic roll'
    assert pending[0].data == {'damage_type': 'fire', 'pb': 4}, pending[0].data
    assert session_ok(combat, mid)

    turn(table, mid, OWNER)
    strike = settle(table, mid, candidate(combat, mid, 'Unarmed Strike', target=FOE).candidate_id)
    assert not _asked(strike)
    engine = reload(tmp_path, mid)
    # The strike's own Bludgeoning roll is not a Daemonic talent's; the Seed rider's Necrotic roll is,
    # and the clause adds 4 Fire of the adapted type as its own packet. The clause is spent by the
    # ROLL, so the additional damage lands with that roll -- before its own packet is committed --
    # which is what lets it land at all when the roll is absorbed to nothing or defeats the creature.
    assert _packets(engine, FOE) == [('BLUDGEONING', 3), ('FIRE', 4), ('NECROTIC', 5)], _packets(engine, FOE)
    assert _fire_bonus(engine, FOE) == [4]
    assert not [c for c in engine.state.actors[OWNER].conditions.values() if c.condition_id == PENDING]

    cycle(table, mid, OWNER)
    settle(table, mid, candidate(combat, mid, 'Unarmed Strike', target=FOE).candidate_id)
    engine = reload(tmp_path, mid)
    assert _fire_bonus(engine, FOE) == [4], \
        'the clause is spent by one roll, not by every roll after it'


def test_cl17_clause_ignores_a_matching_type_roll_from_another_ability(tmp_path):
    def prepare(bundles):
        _scorch(bundles)
        add_action(bundles[0], 'Cold brand flourish',
                   [{'type': 'damage', 'flat': 3, 'applies_to': 'target', 'damage_types': ['fire']}])
        bundles[2]['actor_template']['armor_class'] = 1
        seal(bundles[2])

    combat, table, mid = fixture(tmp_path, [ADAPTATION, SEED], cl=17, bundle_transform=prepare,
                                 foe_position={'x': 4, 'y': 7})
    sow(combat, table, mid)
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Scorch cultivator', target=OWNER).candidate_id,
           {SPEND_CHOICE: '1'})
    turn(table, mid, OWNER)
    settle(table, mid, candidate(combat, mid, 'Cold brand flourish', target=FOE).candidate_id)
    engine = reload(tmp_path, mid)
    assert _packets(engine, FOE) == [('FIRE', 3)], _packets(engine, FOE)
    assert not _fire_bonus(engine, FOE)
    assert [c for c in engine.state.actors[OWNER].conditions.values()
            if c.condition_id == PENDING], 'the printed clause waits for a Daemonic roll, not any roll'


def _next_daemonic_roll_lands(bundles, defence=None, *, foe_hp=None):
    """CL 17 setup: the owner may pay for an adaptation, and Demon Seed's printed hit rider
    (1d10 Necrotic/Psychic/Force) is the next Daemonic damage roll it makes."""
    _scorch(bundles)
    bundles[2]['actor_template']['armor_class'] = 1
    bundles[2]['actor_template']['saving_throws'] = {key: -100 for key in
                                                     bundles[2]['actor_template']['saving_throws']}
    if foe_hp is not None:
        bundles[2]['actor_template']['maximum_hp'] = foe_hp
    if defence is not None:
        bundles[2]['typed_passives'].append(defence)
    seal(bundles[2])


def test_cl17_clause_lands_against_a_creature_immune_to_the_rolls_own_type(tmp_path):
    """The review's own example: the Daemonic roll is Necrotic, the creature is Necrotic-immune.

    The printed clause is spent by "your next damage roll", so the roll still spends it and the
    additional damage -- of the ADAPTED type, which nothing here is immune to -- still lands.
    """
    defence = {'feature_id': 'TEST:DAEMONIC_WARD', 'block': 'resistance', 'kind': 'immunity',
               'damage_types': ['NECROTIC', 'PSYCHIC', 'FORCE'], 'name': 'Test ward'}

    def prepare(bundles):
        _next_daemonic_roll_lands(bundles, defence)

    combat, table, mid = fixture(tmp_path, [ADAPTATION, SEED], cl=17, bundle_transform=prepare,
                                 foe_position={'x': 4, 'y': 7})
    sow(combat, table, mid)
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Scorch cultivator', target=OWNER).candidate_id,
           {SPEND_CHOICE: '1'})

    turn(table, mid, OWNER)
    settle(table, mid, candidate(combat, mid, 'Unarmed Strike', target=FOE).candidate_id)
    engine = reload(tmp_path, mid)
    packets = _packets(engine, FOE)
    assert ('NECROTIC', 0) in packets, f'the Daemonic roll really was reduced to nothing: {packets}'
    assert _fire_bonus(engine, FOE) == [4], \
        f'the clause adds 4 Fire of the adapted type whatever the roll itself became: {_fire_bonus(engine, FOE)}'
    assert not [c for c in engine.state.actors[OWNER].conditions.values() if c.condition_id == PENDING], \
        'the roll spent the clause; it must not wait for a later, unrelated roll'
    assert session_ok(combat, mid)


def test_cl17_adapted_damage_subscriber_runs_when_triggering_type_is_immune(tmp_path):
    """A separate damage reward is not the triggering Fire packet and survives Fire immunity."""
    from tests.cw2_service_support import add_action

    def prepare(bundles):
        _essence(bundles)
        add_action(bundles[2], 'Chill cultivator',
                   [{'type': 'damage', 'flat': 12, 'applies_to': 'target', 'damage_types': ['cold']}])
        add_action(bundles[0], 'Daemonic flame',
                   [{'type': 'damage', 'flat': 9, 'applies_to': 'target', 'damage_types': ['fire']}],
                   typed={'source': SEED})
        bundles[2]['typed_passives'].append(
            {'feature_id': 'TEST:FIRE_WARD', 'block': 'resistance', 'kind': 'immunity',
             'damage_types': ['FIRE'], 'name': 'Fire ward'})
        seal(bundles[0])
        seal(bundles[2])

    combat, table, mid = fixture(tmp_path, [ADAPTATION, SEED], cl=17, bundle_transform=prepare,
                                 foe_position={'x': 4, 'y': 7})
    sow(combat, table, mid)
    turn(table, mid, FOE)
    prompts = settle(table, mid, candidate(combat, mid, 'Chill cultivator', target=OWNER).candidate_id,
                     {SPEND_CHOICE: '1'})
    assert _asked(prompts), 'the player chooses the Cold adaptation'
    assert _resists(reload(tmp_path, mid).state.actors[OWNER], 'cold')

    turn(table, mid, OWNER)
    settle(table, mid, candidate(combat, mid, 'Daemonic flame', target=FOE).candidate_id)
    engine = reload(tmp_path, mid)
    packets = _packets(engine, FOE)
    assert ('FIRE', 0) in packets, f'the triggering packet is Fire-immune: {packets}'
    assert ('COLD', 4) in packets, f'the separate adapted reward must still land: {packets}'
    assert not [c for c in engine.state.actors[OWNER].conditions.values() if c.condition_id == PENDING], \
        'the reward is consumed by this Daemonic roll'
    assert session_ok(combat, mid)


def test_cl17_clause_lands_when_the_daemonic_roll_is_reduced_to_nothing(tmp_path):
    """A roll the creature's own flat reduction takes to nothing is still the roll the clause names."""
    defence = {'feature_id': 'TEST:DAEMONIC_WARD', 'block': 'resistance', 'kind': 'reduction',
               'amount': 99, 'damage_types': ['NECROTIC', 'PSYCHIC', 'FORCE'], 'name': 'Test ward'}

    def prepare(bundles):
        _next_daemonic_roll_lands(bundles, defence)

    combat, table, mid = fixture(tmp_path, [ADAPTATION, SEED], cl=17, bundle_transform=prepare,
                                 foe_position={'x': 4, 'y': 7})
    sow(combat, table, mid)
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Scorch cultivator', target=OWNER).candidate_id,
           {SPEND_CHOICE: '1'})

    turn(table, mid, OWNER)
    settle(table, mid, candidate(combat, mid, 'Unarmed Strike', target=FOE).candidate_id)
    engine = reload(tmp_path, mid)
    packets = _packets(engine, FOE)
    assert ('NECROTIC', 0) in packets, f'the Daemonic roll really was reduced to nothing: {packets}'
    assert _fire_bonus(engine, FOE) == [4], \
        f'the clause adds 4 Fire of the adapted type whatever the roll itself became: {_fire_bonus(engine, FOE)}'
    assert not [c for c in engine.state.actors[OWNER].conditions.values() if c.condition_id == PENDING]


def test_cl17_clause_is_spent_when_its_bonus_defeats_the_target(tmp_path):
    """A roll that brings the creature down spends the clause too: "your next damage roll" is the
    roll, and a defeated creature cannot be the one an earlier clause was still waiting for."""
    def prepare(bundles):
        _next_daemonic_roll_lands(bundles, foe_hp=5)

    combat, table, mid = fixture(tmp_path, [ADAPTATION, SEED], cl=17, bundle_transform=prepare,
                                 foe_position={'x': 4, 'y': 7})
    sow(combat, table, mid)
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Scorch cultivator', target=OWNER).candidate_id,
           {SPEND_CHOICE: '1'})

    turn(table, mid, OWNER)
    settle(table, mid, candidate(combat, mid, 'Unarmed Strike', target=FOE).candidate_id)
    engine = reload(tmp_path, mid)
    assert not engine.state.actors[FOE].active, 'the adapted Fire bonus defeats the creature'
    assert _fire_bonus(engine, FOE), 'the clause is delivered by the roll that defeats the creature'
    assert not [c for c in engine.state.actors[OWNER].conditions.values() if c.condition_id == PENDING], \
        'a roll that defeats its target still spends the clause'


def test_cl17_qualifying_daemonic_packet_itself_defeats_the_target(tmp_path):
    def prepare(bundles):
        _next_daemonic_roll_lands(bundles, foe_hp=10)

    combat, table, mid = fixture(tmp_path, [ADAPTATION, SEED], cl=17, bundle_transform=prepare,
                                 foe_position={'x': 4, 'y': 7})
    sow(combat, table, mid)
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Scorch cultivator', target=OWNER).candidate_id,
           {SPEND_CHOICE: '1'})
    turn(table, mid, OWNER)
    settle(table, mid, candidate(combat, mid, 'Unarmed Strike', target=FOE).candidate_id)
    engine = reload(tmp_path, mid)
    packets = [e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED'
               and FOE in e.target_ids]
    assert [(e.payload['damage_type'], e.payload['reduced_to'], e.payload['remaining_hp'])
            for e in packets] == [('BLUDGEONING', 3, 7), ('FIRE', 4, 3), ('NECROTIC', 5, 0)]
    defeats = [e for e in engine.events if e.event_type == 'LIFE_STATE_CHANGED' and e.actor_id == FOE
               and e.payload.get('life_state') == 'DYING']
    assert len(defeats) == 1
    assert defeats[0].source_definition_id == packets[-1].source_definition_id
    assert engine.events.index(defeats[0]) > engine.events.index(packets[-1])
    assert engine.action_catalog[packets[-1].payload['display_source_id']].parameters['typed']['source'] == SEED
    assert engine.state.actors[FOE].current_hp == 0
    assert engine.state.actors[FOE].life_state == 'DYING'
    assert not any(c.condition_id == PENDING for c in engine.state.actors[OWNER].conditions.values())
    assert session_ok(combat, mid)


@pytest.mark.parametrize('defence', [None, 'immunity', 'reduction', 'defeat'])
def test_cl17_actual_needle_primary_packet_consumes_clause_after_reload(tmp_path, defence):
    """Use the compiled Needle, retaining its normal weapon damage and secondary save.

    Only Seed's hit rider is removed from this fixture: it must not hide a missed
    primary-roll subscription by spending the clause on its separate damage.
    """
    needle = P + 'PARASITE_MERIDIAN_NEEDLE'
    kit = {'starting_kit': {'items': [{'item_id': 'tianxia.mortal.weapon.qiang',
                                     'name': 'Qiang (Spear)', 'quantity': 1}]}}

    def prepare(bundles):
        _next_daemonic_roll_lands(bundles, foe_hp=5 if defence == 'defeat' else None)
        for action in bundles[0]['action_catalog']:
            if (action.get('parameters', {}).get('typed') or {}).get('source') == SEED:
                for effect in action['parameters']['typed']['effects']:
                    if effect['type'] == 'stance':
                        effect['hit_riders'] = []
        if defence in ('immunity', 'reduction'):
            bundles[2]['typed_passives'].append({
                'feature_id': 'TEST:NEEDLE_WARD', 'block': 'resistance', 'kind': defence,
                'damage_types': ['PIERCING'], 'amount': 99, 'name': 'Test ward'})
        seal(bundles[0])
        seal(bundles[2])

    combat, table, mid = fixture(tmp_path, [ADAPTATION, SEED, needle], cl=17,
                                 owner_kit=kit, bundle_transform=prepare,
                                 foe_position={'x': 4, 'y': 7})
    sow(combat, table, mid)
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Scorch cultivator', target=OWNER).candidate_id,
           {SPEND_CHOICE: '1'})
    before = reload(tmp_path, mid)
    assert any(c.condition_id == PENDING for c in before.state.actors[OWNER].conditions.values())
    turn(table, mid, OWNER)
    action = candidate(combat, mid, 'Parasite Meridian Needle', target=FOE)
    settle(table, mid, action.candidate_id)
    engine = reload(tmp_path, mid)
    packets = [e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED'
               and FOE in e.target_ids]
    assert [e.payload['damage_type'] for e in packets] == ['FIRE', 'PIERCING']
    assert _fire_bonus(engine, FOE) == [4]
    primary = packets[-1]
    assert primary.source_definition_id == action.source_definition_id
    assert engine.action_catalog[primary.source_definition_id].parameters['typed']['source'] == needle
    assert primary.payload['rolled_or_pending_damage'] > 0
    if defence in ('immunity', 'reduction'):
        assert primary.payload['reduced_to'] == 0
    else:
        assert primary.payload['reduced_to'] > 0
    assert not any(c.condition_id == PENDING for c in engine.state.actors[OWNER].conditions.values())
    if defence == 'defeat':
        assert packets[0].payload['remaining_hp'] == 1, 'Fire must not defeat the target'
        assert primary.payload['remaining_hp'] == 0
        defeats = [e for e in engine.events if e.event_type == 'LIFE_STATE_CHANGED' and e.actor_id == FOE
                   and e.payload.get('life_state') == 'DYING']
        assert len(defeats) == 1
        assert defeats[0].source_definition_id == primary.source_definition_id
        assert engine.events.index(defeats[0]) > engine.events.index(primary)
        assert engine.state.actors[FOE].current_hp == 0
        assert engine.state.actors[FOE].life_state == 'DYING'
    else:
        cycle(table, mid, OWNER)
        settle(table, mid, candidate(combat, mid, 'Parasite Meridian Needle', target=FOE).candidate_id)
        assert _fire_bonus(reload(tmp_path, mid), FOE) == [4], 'only the next roll gains the bonus'
    assert session_ok(combat, mid)


def _ai_attacks_the_owner(bundles, *, legacy=False):
    """An AI opponent whose one attack is a real Action it will actually choose, and -- for the legacy
    case -- an owner whose adaptation row was sealed before this marker and so carries no choice_owner.

    A test-built action is player-only and carries no damage estimate, and the generic AI reads both:
    an unreadable menu item never reaches the controller, and a zero estimate loses to repositioning.
    Clearing the flag and stating the estimate is the same contract a compiled attack uses.
    """
    _essence(bundles)
    add_action(bundles[2], 'Scorch fiend',
               [{'type': 'damage', 'flat': 12, 'applies_to': 'target', 'damage_types': ['fire']}],
               target='HOSTILE_ENTITY')
    for action in bundles[2]['action_catalog']:
        if action.get('display_name') == 'Scorch fiend':
            action['economy'] = 'ACTION'
            action['parameters'] = {key: value for key, value in (action.get('parameters') or {}).items()
                                    if key != 'player_only'}
            action['parameters']['expected_damage'] = 40
    bundles[2]['action_catalog'] = [a for a in bundles[2]['action_catalog']
                                    if a.get('display_name') == 'Scorch fiend']
    bundles[2]['actor_template']['action_ids'] = [a['source_definition_id']
                                                  for a in bundles[2]['action_catalog']]
    # The opponent attacks whichever of the two it rates higher, so the owner is marked the primary
    # combatant: this is the creature the printed question is about, not its ally.
    bundles[0]['actor_template']['primary_combatant'] = True
    bundles[1]['actor_template']['primary_combatant'] = False
    seal(bundles[2])
    if legacy:
        for row in bundles[0]['typed_passives']:
            if row.get('block') == 'thousand_hunger_adaptation':
                row['block'] = 'daemonic_thousand_hunger'  # the block this marker replaced
                for carried in ('pb', 'cl', 'choice_owner'):
                    row.pop(carried, None)  # a sealed row carried no numbers and no ownership flag
    seal(bundles[0])


def _ai_fires_at_the_owner(combat, table, mid):
    """Let the AI make its own choices until its attack reaches the owner.

    Every choice is the AI's own: a real controller, real rolls, real recorded decisions. Anything it
    raises that is NOT the owner's printed decision is declined so the fight carries on; the owner's
    own prompt stops the step unanswered. Returns that step, or None if the fight ran out first.
    """
    answers: list[dict[str, object]] = []
    for _ in range(24):
        engine = combat._load_session(mid).engine
        if engine.state.terminal_result is not None:
            return None
        if engine.state.current_actor_id == FOE:
            step = combat.local_step(mid, answers or None)
            if step['status'] != 'AWAITING_REACTION':
                answers = []
                continue
            asked = step['reaction_context']
            if asked['reactor_id'] == OWNER and asked['reaction_source_id'] == SPEND_CHOICE:
                return step
            answers = [{'checkpoint': asked['checkpoint'], 'reactor_id': asked['reactor_id'],
                        'reaction_source_id': asked['reaction_source_id'], 'selection': 'DECLINE'}]
            continue
        menu = table.state(mid)['menu']
        if menu and menu.get('actor_id') == engine.state.current_actor_id and 'end_turn' in menu:
            end_turn(table, mid)
        else:
            combat.local_step(mid)
    return None


@pytest.mark.parametrize('legacy', [False, True], ids=['fresh-row', 'legacy-sealed-row'])
def test_a_manual_owner_is_asked_when_an_ai_fighter_attacks_it(tmp_path, legacy):
    """Rule 9 and the review: the trigger arrives on the AI's own turn, and the creature that has to
    decide is the player's. A row sealed before this marker carries no choice_owner flag, so without
    the plug-in's own ownership query the printed "you may spend" is paid without ever asking."""
    combat, table, mid = fixture(tmp_path, [ADAPTATION, SEED], cl=17,
                                 bundle_transform=lambda bundles: _ai_attacks_the_owner(bundles, legacy=legacy),
                                 foe_position={'x': 3, 'y': 5}, seed='SEED-OWNER-FIRST',
                                 modes={OWNER: 'MANUAL', ALLY: 'MANUAL', FOE: 'LOCAL_AUTO'})
    sow(combat, table, mid)

    step = _ai_fires_at_the_owner(combat, table, mid)
    assert step is not None and step['status'] == 'AWAITING_REACTION', \
        f'a manual owner must be asked before its Essence is spent: {step}'
    asked = step['reaction_context']
    assert asked['reactor_id'] == OWNER, f'the owner is the creature that has to decide: {asked["reactor_id"]}'
    assert asked['reaction_source_id'] == SPEND_CHOICE, asked['reaction_source_id']
    owner_name = reload(tmp_path, mid).state.actors[OWNER].display_name
    trigger = asked.get('choice_trigger') or {}
    text = ' '.join(str(part) for part in (trigger.get('prompt'), trigger.get('action_name'),
                                           trigger.get('cost'), trigger.get('payment_note')))
    for word in ('Thousand-Hunger Adaptation', 'fire', owner_name, 'Scorch fiend', 'Devoured Essence'):
        assert word.lower() in text.lower(), f'{word!r} missing from the prompt: {text}'
    assert reload(tmp_path, mid).state.actors[OWNER].resources[ESSENCE] == 4, \
        'nothing is spent until the player has answered'


def test_an_ai_controlled_owner_of_a_legacy_row_is_never_asked(tmp_path):
    """Rule 9's other half on the legacy row too: the AI answers its own choices."""
    combat, table, mid = fixture(tmp_path, [ADAPTATION, SEED], cl=17,
                                 bundle_transform=lambda bundles: _ai_attacks_the_owner(bundles, legacy=True),
                                 foe_position={'x': 3, 'y': 5}, seed='SEED-OWNER-FIRST',
                                 modes={OWNER: 'MANUAL', ALLY: 'MANUAL', FOE: 'LOCAL_AUTO'})
    sow(combat, table, mid)
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    assert _ai_fires_at_the_owner(combat, table, mid) is None, 'an AI owner is never prompted'
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[ESSENCE] < 4, 'the AI pays the printed cost itself'
    assert _resists(engine.state.actors[OWNER], 'fire')


def test_an_ai_fighter_adapts_for_itself_without_being_asked(tmp_path):
    """Rule 9's other half: an AI fighter is never prompted and pays the printed cost itself.

    The talent and Demon Seed belong to the AI opponent here, so the trigger arrives on the player's
    turn and the creature that has to decide is not the player's."""
    def prepare(bundles):
        from combat.factory_compiler import compile_character

        ai = compile_character(sheet([ADAPTATION, SEED], cl=17), actor_id=FOE)
        for resource in ai['actor_template']['resources']:
            if resource['resource_id'] == ESSENCE:
                resource.update(initial=4, maximum=10)
        bundles[2].clear()
        bundles[2].update(ai)
        add_action(bundles[0], 'Sow Demon Seed',
                   [{'type': 'condition', 'condition': 'stance.demon_seed', 'applies_to': 'target',
                     'expires_on': 'UNTIL_REMOVED'}])
        add_action(bundles[0], 'Scorch fiend',
                   [{'type': 'damage', 'flat': 12, 'applies_to': 'target', 'damage_types': ['fire']}])
        seal(bundles[0])

    combat, table, mid = fixture(tmp_path, [], seed='SEED-OWNER-FIRST', bundle_transform=prepare,
                                 foe_position={'x': 4, 'y': 7},
                                 modes={OWNER: 'MANUAL', ALLY: 'MANUAL', FOE: 'LOCAL_AUTO'})
    settle(table, mid, candidate(combat, mid, 'Sow Demon Seed', target=FOE).candidate_id)
    assert _seeded(reload(tmp_path, mid).state.actors[FOE]), 'the printed gate is Demon Seed'
    prompts = settle(table, mid, candidate(combat, mid, 'Scorch fiend', target=FOE).candidate_id)
    assert not _asked(prompts), 'an AI fighter answers its own choices; it is never prompted'
    engine = reload(tmp_path, mid)
    assert engine.state.actors[FOE].resources[ESSENCE] == 3, 'the AI pays the printed cost itself'
    assert _resists(engine.state.actors[FOE], 'fire')


def test_demon_mark_actually_reaches_the_target(tmp_path):
    def prepare(bundles):
        # The printed line is "Failed Save: It bears your Demon Mark", so the save must fail.
        bundles[2]['actor_template']['saving_throws']['CHA'] = -100
        seal(bundles[2])

    combat, table, mid = fixture(tmp_path, [MARK, SEED], bundle_transform=prepare)
    engine = combat._load_session(mid).engine
    rows = [c for c in engine.legal_candidates()
            if getattr(engine.action_catalog.get(c.source_definition_id), 'display_name', '').startswith('Demon Mark')
            and c.target_ids == (FOE,)]
    assert rows, 'Demon Mark is a printed Bonus Action on the owner'
    settle(table, mid, rows[0].candidate_id)
    engine = reload(tmp_path, mid)
    from combat.typed_executor import bears_mark

    assert bears_mark(engine.state.actors[FOE], OWNER, 'Demon Mark'), \
        'the marked creature must bear the mark itself, not be told about it'


def session_ok(combat, mid):
    """The saved fight still verifies and replays after every one of the steps above."""
    session = CombatService(ROOT, combat.user_data)._load_session(mid) if hasattr(combat, 'user_data') \
        else combat._load_session(mid)
    return session.verify()['status'] == 'PASS' and session.mechanical.replay()['status'] == 'PASS'

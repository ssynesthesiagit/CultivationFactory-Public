"""Red Lotus Cautery's base reduction: one signed Proficiency Bonus + Path key sum.

MGR-T14-ling-cautery-sum-1. The atomic row is the printed clause of
foundation.red_lotus_ash_returning_v0_2B.red_lotus_cautery: "Reduce the
triggering damage by your Proficiency Bonus + your Path key ability modifier."

The v41 typing carried that clause as two separate ``damage_modifier`` rows
(formula ``pb`` and ``key_ability_modifier``), and the generic "when you take
damage" reduction sums the rows after each one's own nonnegative clamp. Each
term therefore floored on its own: PB 2 / Path key modifier -1 reduced by
``max(0, 2) + max(0, -1)`` = 2 instead of the printed signed sum 1, and a key
modifier below -PB still reduced by the full PB instead of nothing. The
reviewed record combines the amount into the single ``pb+key`` expression the
existing ``static_bonus`` row reader already evaluates as one signed sum,
clamped once by ``_generic_amount`` before the final damage clamp.

Every test drives a real table: the foe's qualifying typed weapon attack lands
its hostile fire (or necrotic) packet on an owner above half Hit Points, the
Ask-me Cautery consent is answered through the table's own reaction transport,
1 Funeral Ash is really spent, the table is committed, and a cold reload must
replay PASS with the resulting HP and event state.
"""
from combat.canonical import canonical_sha256
from combat.factory_compiler import compile_character
from tests.h1_support import sheet
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, settle, turn, reload

CAUTERY = "foundation.red_lotus_ash_returning_v0_2B.red_lotus_cautery"
CONSENT = "reaction:typed." + CAUTERY
ASH = "resource:foundation.funeral_ash"
# A natural 1 always misses in this engine, so the pinned seed must roll a hit
# for the foe's qualifying attack to land its triggering packet; MGR-T14-s0
# rolls a 12 on the attack.
SEED = "MGR-T14-s0"
# The flat fire damage the foe's qualifying attack carries (the engine adds the
# foe's own attack-ability modifier when it delivers the weapon packet, so the
# tests read the delivered packet off the committed events instead of pinning it).
PACKET = 8


def owner_bundle(proficiency_bonus=2, con=8, ash=1):
    """A Red Lotus Ash Returning owner: PB 2 and a Path key (CON) ability modifier
    chosen by ``con`` (8 -> -1, 16 -> +3, 4 -> -3), holding ``ash`` Funeral Ash."""
    document = sheet([CAUTERY], foundation={
        'foundation_id': 'red_lotus_ash_returning_v0_2B', 'stage': 'Awakened',
        'resource': {'name': 'Funeral Ash', 'resource_id': 'tianxia.resource.test',
                     'maximum': 1, 'current': ash}})
    document['identity']['proficiency_bonus'] = proficiency_bonus
    for row in document['ability_scores_and_statistics']['abilities']:
        if row['ability'] == 'CON':
            row['score'] = con
            row['modifier'] = (con - 10) // 2
    return compile_character(document, actor_id=OWNER, reaction_plan={'ask': True})


def seal_qualifying_attack(bundles, *, damage_type='fire', flat=PACKET):
    """The foe's real qualifying hit: a typed weapon attack that always lands,
    delivering the triggering hostile damage packet."""
    source = "action:test.cautery.qualifying_attack"
    row = {'source_definition_id': source, 'display_name': 'Cautery qualifying attack',
           'owner_id': bundles[2]['actor_id'], 'economy': 'ACTION',
           'resolution_kind': 'TYPED', 'target_kind': 'HOSTILE_ENTITY', 'range_ft': 60,
           'parameters': {'typed': {'source': source, 'range_ft': 60,
                                     'numbers': {'pb': 2, 'key_mod': -1, 'save_dc': 30, 'attack_bonus': 100},
                                     'effects': [{'type': 'attack', 'attack_kind': 'weapon', 'count': 1,
                                                  'on_hit': [{'type': 'damage', 'flat': flat,
                                                              'damage_types': [damage_type], 'applies_to': 'target'}]}],
                                     'duration': {'kind': 'instant'}, 'riders': []},
                        'expected_damage': flat}}
    bundles[2]['action_catalog'].append(row)
    bundles[2]['actor_template']['action_ids'].append(source)
    bundles[2].pop('bundle_sha256', None)
    bundles[2]['bundle_sha256'] = canonical_sha256(bundles[2])


def cautery_fight(tmp_path, *, consent=True, damage_type='fire', extra=None,
                   picks=None, path=None, **owner):
    """The foe lands its qualifying hit on the owner and the committed table is
    cold-reloaded (the reload asserts the replay still passes)."""
    def delivery(bundles):
        seal_qualifying_attack(bundles, damage_type=damage_type)
        if extra:
            extra(bundles)

    combat, table, mid = fixture(tmp_path / path if path else tmp_path, [], seed=SEED,
                                 owner_bundle=owner_bundle(**owner),
                                 bundle_transform=delivery)
    turn(table, mid, FOE)
    strike = candidate(combat, mid, 'Cautery qualifying attack', target=OWNER).candidate_id
    settle(table, mid, strike, {CONSENT: 'first', **(picks or {})} if consent else {})
    return reload(tmp_path / path if path else tmp_path, mid)


def resolved(engine):
    """The Cautery reaction's own resolved rows (the reductions it applied)."""
    return [event.payload for event in engine.events
            if event.event_type == 'REACTION_RESOLVED'
            and event.source_definition_id == CAUTERY]


def committed(engine):
    """The triggering attack's committed damage packet."""
    [payload] = [event.payload for event in engine.events
                 if event.event_type == 'DAMAGE_COMMITTED'
                 and event.source_definition_id == 'action:test.cautery.qualifying_attack']
    return payload


def spent_ash(engine):
    return [event.payload for event in engine.events
            if event.event_type == 'RESOURCE_SPENT'
            and event.source_definition_id == CAUTERY]


def test_cautery_delivery_contains_the_compiled_signed_override():
    # Delivery regression: submitting the old branch/base without the reviewed
    # override (or forgetting its generated authority) leaves two amount rows.
    # Check the compiler's actual output rather than trusting a report's SHA.
    bundle = owner_bundle(proficiency_bonus=2, con=8)
    [reaction] = [row for row in bundle['typed_reactions']
                  if row.get('feature_id') == CAUTERY]
    amounts = [effect for effect in reaction['effects']
               if effect.get('type') == 'damage_modifier']
    assert [effect['formula'] for effect in amounts] == ['pb+key']
    assert reaction['kind'] == 'damaged'
    assert reaction['costs'] == [{'resource_id': ASH, 'amount': 1}]


def test_cautery_reduces_by_pb_plus_negative_key_as_one_signed_sum(tmp_path):
    # PB 2 / Path key ability modifier -1: the printed signed sum is 1.
    engine = cautery_fight(tmp_path, proficiency_bonus=2, con=8)
    [row] = resolved(engine)
    assert row['reduction'] == 1
    packet = committed(engine)
    assert packet['hp_damage'] == row['pending_before'] - 1
    assert engine.state.actors[OWNER].current_hp == 60 - packet['hp_damage']
    # The pre-existing resource paid the admission through the same consent
    # (the receipt is authoritative: Funeral Ash regenerates each round, so
    # the reloaded pool is refilled by the owner's next turn already).
    assert spent_ash(engine) == [{'amount': 1, 'remaining': 0, 'resource_id': ASH}]


def test_cautery_nonpositive_signed_sum_reduces_nothing(tmp_path):
    # PB 2 / Path key ability modifier -3: the signed sum is -1, so the final
    # nonnegative clamp reduces nothing (the key term is never clamped on its
    # own and delivered as a separate PB reduction).
    engine = cautery_fight(tmp_path, proficiency_bonus=2, con=4)
    [row] = resolved(engine)
    assert row['reduction'] == 0
    packet = committed(engine)
    assert packet['hp_damage'] == row['pending_before']
    assert engine.state.actors[OWNER].current_hp == 60 - packet['hp_damage']
    # The qualifying hit still spent the admission; only the reduction clamps away.
    assert spent_ash(engine) == [{'amount': 1, 'remaining': 0, 'resource_id': ASH}]
    assert row['gate3_reaction_available_after'] is False


def test_cautery_reduces_by_pb_plus_positive_key_as_the_signed_sum(tmp_path):
    # PB 2 / Path key ability modifier +3: the printed signed sum is 5 (the
    # positive control that already held before the fix, and still holds).
    engine = cautery_fight(tmp_path, proficiency_bonus=2, con=16)
    [row] = resolved(engine)
    assert row['reduction'] == 5
    packet = committed(engine)
    assert packet['hp_damage'] == row['pending_before'] - 5
    assert engine.state.actors[OWNER].current_hp == 60 - packet['hp_damage']
    assert spent_ash(engine) == [{'amount': 1, 'remaining': 0, 'resource_id': ASH}]


def test_cautery_declining_the_ask_me_window_keeps_the_ash(tmp_path):
    # Declining the Ask-me window keeps the pre-existing resource and applies no
    # reduction: the ordinary consent behavior around the triggering damage is
    # preserved, and the full packet lands.
    engine = cautery_fight(tmp_path, consent=False, proficiency_bonus=2, con=8)
    assert resolved(engine) == []
    assert spent_ash(engine) == []
    assert engine.state.actors[OWNER].resources[ASH] == 1
    packet = committed(engine)
    assert packet['hp_damage'] == packet['rolled_or_pending_damage']
    assert engine.state.actors[OWNER].current_hp == 60 - packet['hp_damage']


def test_cautery_keeps_the_printed_damage_type_gate(tmp_path):
    # The printed trigger lists fire, necrotic and poison (the automated types):
    # a hostile necrotic packet is still eligible, and a hostile cold packet --
    # a type the row never listed -- is not answered at all, so the change did
    # not widen or narrow the gate.
    engine = cautery_fight(tmp_path, path='necrotic', damage_type='necrotic',
                               proficiency_bonus=2, con=8)
    [row] = resolved(engine)
    assert row['reduction'] == 1
    assert spent_ash(engine) == [{'amount': 1, 'remaining': 0, 'resource_id': ASH}]

    engine = cautery_fight(tmp_path, path='cold', damage_type='cold',
                               proficiency_bonus=2, con=8)
    assert resolved(engine) == []
    assert spent_ash(engine) == []
    assert engine.state.actors[OWNER].resources[ASH] == 1
    packet = committed(engine)
    assert packet['hp_damage'] == packet['rolled_or_pending_damage']


def test_cautery_stacks_with_an_unrelated_free_damage_reduction(tmp_path):
    # An unrelated free "when you take damage" reduction still answers the same
    # packet alongside the paid Cautery (a paid answer no longer silences a free
    # one), so the two reductions compose: free 1, then the signed PB + key 1.
    def unrelated_free_reduction(bundles):
        # A sealed self row: no printed distance (a null range keeps the
        # row's own trigger contract, like the compiled Cautery row).
        bundles[0]['typed_reactions'].append({
            'block': 'generic', 'kind': 'damaged', 'free': True,
            'feature_id': 'test:cautery.unrelated_free_reduction',
            'name': 'Unrelated free reduction', 'costs': [],
            'effects': [{'type': 'damage_modifier', 'applies_to': 'self', 'flat': 1,
                         'formula': 'none', 'damage_types': [], 'ability': 'none',
                         'condition': 'none', 'distance_ft': 0, 'on': '',
                         'duration': 'instant'}]})

    engine = cautery_fight(tmp_path, extra=unrelated_free_reduction,
                               picks={'reaction:typed.test:cautery.unrelated_free_reduction': 'first'},
                               proficiency_bonus=2, con=8)
    rows = [event.payload for event in engine.events
            if event.event_type == 'REACTION_RESOLVED'
            and event.source_definition_id in (CAUTERY, 'test:cautery.unrelated_free_reduction')]
    assert [row['reduction'] for row in rows] == [1, 1]
    packet = committed(engine)
    assert packet['hp_damage'] == rows[0]['pending_before'] - 2
    assert engine.state.actors[OWNER].current_hp == 60 - packet['hp_damage']
    assert spent_ash(engine) == [{'amount': 1, 'remaining': 0, 'resource_id': ASH}]

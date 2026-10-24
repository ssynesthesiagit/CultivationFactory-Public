"""A2-karma (automation second pass): Karma talents that become FULL, through the table.

Every case builds a real fixture through CombatService and TabletopService, commits the real Record the Deed, Return the Sting
and Harm Returned reactions with the table's own prompts, cold-reloads the fight (mechanical replay PASS) and asserts on the
reloaded state. Printed text: authority/typed_mechanics/rules_text.json (TAL_KARMA_RECORD_THE_DEED, return_the_sting,
harm_returned).
"""
import json
from pathlib import Path

import pytest

from combat import factory_compiler
from combat.ext import karma_imprints
from tests.cw2_service_support import add_action, seal
from tests.h1_support import sheet
from tests.worker2_support import ALLY, FOE, OWNER, candidate, fixture, reload, settle, sealed_native_attack, turn

RECORD = 'TAL_KARMA_RECORD_THE_DEED'
RETURN = 'tianxia.talent.karma.return_the_sting'
HARM = 'tianxia.talent.karma.harm_returned'
GRACE_REPAID = 'tianxia.talent.karma.grace_repaid'
SEAL = 'tianxia.talent.karma.ledger_seal_scripture'


class _Use(dict):
    """settle() answers a reaction with USE when ``picks.get(reaction_source_id)`` is set; this answers USE for any prompt whose id
    names one of ``needles`` and DECLINE for every other one, so a round can take one reaction and refuse the rest."""

    def __init__(self, *needles):
        super().__init__()
        self.needles = needles

    def __bool__(self):
        return True

    def get(self, key, default=None):
        return 'use' if any(needle in key for needle in self.needles) else default


def _prepare(bundles, *, heavy=None):
    """The owner and ally carry 300 HP; the foe's strikes are sealed native attacks (a +100 attack bonus always hits AC 14; a typed
    attack's bonus is not applied, so its rolls were random). A ~4-point strike, and a ``heavy``-point one for the Harm Returned cap."""
    for bundle, initiative in zip(bundles, [100, -100, 0]):
        bundle['actor_template']['initiative_bonus'] = initiative
        bundle['actor_template']['maximum_hp'] = 300
        seal(bundle)
    sealed_native_attack(bundles[2], 'Foe strike', damage_type='FORCE', count=1, sides=2, modifier=3, attack_bonus=100, range_ft=120)
    if heavy is not None:  # 1d2 + (heavy - 1): every roll is ``heavy`` or ``heavy + 1``, so half rounded down is fixed
        sealed_native_attack(bundles[2], 'Foe heavy', damage_type='FORCE', count=1, sides=2, modifier=heavy - 1, attack_bonus=100, range_ft=120)


def _strike(combat, table, mid, name, answers, *, target=ALLY):
    """The foe attacks ally with ``name`` in its own turn, which then ends so the next round restores the owner's Reaction;
    ``answers`` decides each reaction prompt the strike raises."""
    turn(table, mid, FOE)
    prompts = settle(table, mid, candidate(combat, mid, name, target=target).candidate_id, answers)
    if table.state(mid)['menu']['actor_id'] == FOE:
        settle(table, mid, table.state(mid)['menu']['end_turn'])
    return prompts


def test_return_the_sting_harm_returned_and_grace_repaid_leave_no_gm_riders_in_the_authority():
    """The engine resolves both printed effects, so the typed record carries no rider for the GM to read."""
    mechanics = json.loads(Path(factory_compiler.TYPED_AUTHORITY).read_bytes())['mechanics']
    for talent in (RETURN, HARM, GRACE_REPAID):
        assert mechanics[talent]['coverage'] == 'FULL', talent
        assert mechanics[talent]['riders'] == [], talent


def test_grace_repaid_reduces_a_strike_on_the_creature_carrying_your_grace_imprint(tmp_path):
    """Round 1: the foe hits the owner (Record the Deed: a Debt on the foe). Round 2: the ally heals the owner (Record the Deed: a
    Grace Imprint on the ally). Round 3: the foe's heavy strike hits the ally, and Grace Repaid reduces it by 2d8 + key modifier (CL 5)."""
    def prepare(bundles):
        _prepare(bundles, heavy=20)
        add_action(bundles[1], 'Ally mend', [{'type': 'healing', 'applies_to': 'target', 'flat': 5}], target='ANY_CREATURE')
        seal(bundles[1])

    combat, table, mid = fixture(tmp_path, [RECORD, GRACE_REPAID], cl=5, bundle_transform=prepare)
    _strike(combat, table, mid, 'Foe strike', _Use(RECORD), target=OWNER)
    turn(table, mid, OWNER)  # the ally's round-1 turn ends; round 2 begins with the owner's Reaction back
    turn(table, mid, ALLY)  # the foe's round-2 turn ends
    settle(table, mid, candidate(combat, mid, 'Ally mend', target=OWNER).candidate_id, _Use(RECORD))
    engine = reload(tmp_path, mid)
    assert len(karma_imprints.held(engine.state.actors[ALLY], OWNER, 'grace')) == 1
    turn(table, mid, FOE)
    qi = engine.state.actors[OWNER].resources['resource:core.qi']
    prompts = _strike(combat, table, mid, 'Foe heavy', _Use(GRACE_REPAID), target=ALLY)
    assert len([rid for rid in _ids(prompts) if GRACE_REPAID in rid]) == 1
    engine = reload(tmp_path, mid)
    ally = engine.state.actors[ALLY]
    reduction = _roll_with(engine, GRACE_REPAID)
    struck = _roll_with(engine, 'foe_heavy')
    assert reduction.expression == '2d8+2'  # CL 5: 2d8 + the owner's key modifier (Constitution +2)
    assert ally.maximum_hp - ally.current_hp == max(0, struck.total - reduction.total)  # exact, and zero when fully absorbed
    assert not karma_imprints.held(ally, OWNER, 'grace')  # the Grace Imprint is spent
    assert engine.state.actors[OWNER].resources['resource:core.qi'] == qi - 1


def _roll_with(engine, text):
    """The one roll the engine logged whose reason names ``text`` (a Karma reduction, or a native strike's damage)."""
    found = [r for r in engine.rolls if text in r.reason and (r.reason.startswith('GENERIC_AMOUNT:') or r.reason.startswith('DAMAGE:'))]
    assert len(found) == 1, [r.reason for r in engine.rolls]
    return found[0]


def _ids(prompts):
    return [p['context']['reaction_source_id'] for p in prompts]


def _pb_and_mod(engine):
    """Psychic damage from a Karma reaction is the owner's Proficiency Bonus + its key modifier (Constitution 14: +2 in the sheet)."""
    return engine.state.actors[OWNER].proficiency_bonus + 2


def test_return_the_sting_is_offered_only_when_the_striker_carries_a_debt_imprint(tmp_path):
    combat, table, mid = fixture(tmp_path, [RETURN], ally_talents=(), bundle_transform=_prepare)
    prompts = _strike(combat, table, mid, 'Foe strike', _Use(RETURN))
    assert not [rid for rid in _ids(prompts) if RETURN in rid]
    engine = reload(tmp_path, mid)
    assert engine.state.actors[FOE].current_hp == engine.state.actors[FOE].maximum_hp
    assert engine.state.actors[OWNER].reaction_available


def test_record_then_return_the_sting_costs_one_cp_and_deals_psychic_damage_once(tmp_path):
    combat, table, mid = fixture(tmp_path, [RECORD, RETURN], cl=5, bundle_transform=_prepare)
    prompts = _strike(combat, table, mid, 'Foe strike', _Use(RECORD))
    assert any(RECORD in rid for rid in _ids(prompts))
    engine = reload(tmp_path, mid)
    foe = engine.state.actors[FOE]
    assert len(karma_imprints.held(foe, OWNER, 'debt')) == 1  # Record the Deed placed the Debt Imprint on the striker
    qi = engine.state.actors[OWNER].resources['resource:core.qi']

    prompts = _strike(combat, table, mid, 'Foe strike', _Use(RETURN))
    # This fixture checks the first response; the two-sided case below checks chaining.
    assert len([rid for rid in _ids(prompts) if RETURN in rid]) == 1
    engine = reload(tmp_path, mid)
    foe = engine.state.actors[FOE]
    assert foe.maximum_hp - foe.current_hp == _pb_and_mod(engine)  # no extra die below CL 11
    assert not karma_imprints.held(foe, OWNER, 'debt')  # the Imprint was spent
    assert engine.state.actors[OWNER].resources['resource:core.qi'] == qi - 1
    assert engine.state.actors[OWNER].reaction_available is False  # the Reaction answered the strike


def test_return_the_sting_adds_a_d8_at_level_eleven(tmp_path):
    combat, table, mid = fixture(tmp_path, [RECORD, RETURN], cl=11, bundle_transform=_prepare)
    _strike(combat, table, mid, 'Foe strike', _Use(RECORD))
    _strike(combat, table, mid, 'Foe strike', _Use(RETURN))
    engine = reload(tmp_path, mid)
    foe = engine.state.actors[FOE]
    dealt = foe.maximum_hp - foe.current_hp
    assert _pb_and_mod(engine) + 1 <= dealt <= _pb_and_mod(engine) + 8


@pytest.mark.parametrize('heavy,expected', [(20, 10), (80, 25)])
def test_harm_returned_halves_the_strike_and_stops_at_five_times_cl(tmp_path, heavy, expected):
    """Two Debt Imprints (one per round's Record the Deed), then a strike of ``heavy`` damage. Half, rounded down, capped at 5 x CL (25 at CL 5)."""
    combat, table, mid = fixture(tmp_path, [RECORD, HARM], cl=5, bundle_transform=lambda bs: _prepare(bs, heavy=heavy))
    _strike(combat, table, mid, 'Foe strike', _Use(RECORD))
    _strike(combat, table, mid, 'Foe strike', _Use(RECORD))
    engine = reload(tmp_path, mid)
    foe = engine.state.actors[FOE]
    assert len(karma_imprints.held(foe, OWNER, 'debt')) == 2
    qi = engine.state.actors[OWNER].resources['resource:core.qi']
    prompts = _strike(combat, table, mid, 'Foe heavy', _Use(HARM))
    # This fixture checks the first response; the two-sided case below checks chaining.
    assert len([rid for rid in _ids(prompts) if HARM in rid]) == 1
    engine = reload(tmp_path, mid)
    foe = engine.state.actors[FOE]
    assert foe.maximum_hp - foe.current_hp == expected
    assert not karma_imprints.held(foe, OWNER, 'debt')  # both Debt Imprints are spent
    assert engine.state.actors[OWNER].resources['resource:core.qi'] == qi - 3


def test_harm_returned_needs_two_debt_imprints_on_the_striker(tmp_path):
    combat, table, mid = fixture(tmp_path, [RECORD, HARM], cl=5, bundle_transform=lambda bs: _prepare(bs, heavy=80))
    _strike(combat, table, mid, 'Foe strike', _Use(RECORD))  # one Debt Imprint only
    prompts = _strike(combat, table, mid, 'Foe heavy', _Use(HARM))
    assert not [rid for rid in _ids(prompts) if HARM in rid]
    engine = reload(tmp_path, mid)
    foe = engine.state.actors[FOE]
    assert foe.maximum_hp - foe.current_hp == 0
    assert len(karma_imprints.held(foe, OWNER, 'debt')) == 1


@pytest.mark.parametrize('response', [RETURN, HARM])
def test_reflection_cannot_chain_or_recreate_its_spent_cause_with_two_eligible_ledgers(tmp_path, response):
    """Both sides earn two Debts through committed damage actions. The receiving ledger has
    both reflection talents, CP and a Reaction; Ledger Seal could record the original
    strike after the defender spends its Reaction, but that spent Cause is forbidden.
    A later ordinary strike proves both opposing responses and Seal are otherwise offered.
    """
    talents = [RECORD, RETURN, HARM, SEAL]

    def prepare(bundles):
        _prepare(bundles)
        # Flat damage setup avoids a natural-1 miss silently leaving a ledger short.
        for bundle, name, amount in [(bundles[0], 'Owner deed', 5),
                                      (bundles[2], 'Foe deed', 5),
                                      (bundles[2], 'Foe severe deed', 20)]:
            add_action(bundle, name, [{'type': 'damage', 'applies_to': 'target',
                                      'flat': amount, 'damage_types': ['FORCE']}], target='HOSTILE_ENTITY')
            seal(bundle)
        add_action(bundles[1], 'Ally mend', [{'type': 'healing', 'applies_to': 'target', 'flat': 5}], target='ANY_CREATURE')
        seal(bundles[1])

    combat, table, mid = fixture(tmp_path, talents, cl=5,
                               foe_sheet=sheet(talents, cl=5), bundle_transform=prepare)
    for _ in range(2):
        turn(table, mid, OWNER)
        settle(table, mid, candidate(combat, mid, 'Owner deed', target=FOE).candidate_id, _Use(RECORD))
        _strike(combat, table, mid, 'Foe deed', _Use(RECORD), target=OWNER)
    turn(table, mid, FOE)
    before = reload(tmp_path, mid)
    for holder, creature in [(OWNER, FOE), (FOE, OWNER)]:
        assert len(karma_imprints.held(before.state.actors[creature], holder, 'debt')) == 2
        actor = before.state.actors[holder]
        assert actor.reaction_available
        assert actor.resources['resource:core.qi'] >= 3
        assert actor.turn_flags.get('_round_karma_recorded', [0])[0] != before.state.round_number
        assert actor.turn_flags.get('_round_karma_sealed') != before.state.round_number

    # Do not advance a turn after committing: availability must be observed before resets.
    prompts = settle(table, mid, candidate(combat, mid, 'Foe severe deed', target=OWNER).candidate_id, _Use(response))
    reflected = [p for p in prompts if any(t in p['context']['reaction_source_id'] for t in (RETURN, HARM))]
    assert reflected and all(p['context']['reactor_id'] == OWNER for p in reflected)
    assert len([p for p in reflected if response in p['context']['reaction_source_id']]) == 1
    assert not [p for p in prompts if p['context']['reactor_id'] == OWNER
                and RECORD in p['context']['reaction_source_id']]
    after = reload(tmp_path, mid)
    expected_reflection = _pb_and_mod(after) if response == RETURN else 10
    assert after.state.actors[FOE].current_hp == before.state.actors[FOE].current_hp - expected_reflection
    assert after.state.actors[FOE].reaction_available
    assert after.state.actors[FOE].resources['resource:core.qi'] == before.state.actors[FOE].resources['resource:core.qi']
    assert len(karma_imprints.held(after.state.actors[OWNER], FOE, 'debt')) == 2
    spent = 1 if response == RETURN else 2
    assert len(karma_imprints.held(after.state.actors[FOE], OWNER, 'debt')) == 2 - spent
    assert after.state.actors[OWNER].resources['resource:core.qi'] == before.state.actors[OWNER].resources['resource:core.qi'] - (1 if response == RETURN else 3)

    # Positive control: the same opposing ledger can answer an ordinary strike.
    turn(table, mid, OWNER)
    normal = settle(table, mid, candidate(combat, mid, 'Owner deed', target=FOE).candidate_id)
    assert all(any(p['context']['reactor_id'] == FOE and talent in p['context']['reaction_source_id']
                   for p in normal) for talent in (RETURN, HARM))
    reload(tmp_path, mid)
    # Replenish OWNER's Debt so its next round can spend a Reaction on reflection.
    _strike(combat, table, mid, 'Foe deed', _Use(RECORD), target=OWNER)
    turn(table, mid, ALLY)
    seal_before = reload(tmp_path, mid)
    assert not seal_before.state.actors[OWNER].reaction_available
    # In a fresh round, reflect a strike, then record a distinct healing Cause with
    # Ledger Seal for 1 CP. This proves Record works with a spent Reaction when the
    # Cause has not been settled, rather than merely suppressing every such prompt.
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Foe deed', target=OWNER).candidate_id, _Use(RETURN))
    turn(table, mid, ALLY)
    seal_before = reload(tmp_path, mid)
    assert not seal_before.state.actors[OWNER].reaction_available
    normal_record = settle(table, mid, candidate(combat, mid, 'Ally mend', target=OWNER).candidate_id, _Use(RECORD))
    assert any(p['context']['reactor_id'] == OWNER and RECORD in p['context']['reaction_source_id'] for p in normal_record)
    sealed = reload(tmp_path, mid)
    assert len(karma_imprints.held(sealed.state.actors[ALLY], OWNER, 'grace')) == 1
    assert sealed.state.actors[OWNER].resources['resource:core.qi'] == seal_before.state.actors[OWNER].resources['resource:core.qi'] - 1

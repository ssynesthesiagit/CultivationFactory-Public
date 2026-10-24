"""Ferry investigation: compiled ownership is not whole-feature acquisition proof.

These use the real table's attack, reaction answer, commit and cold replay.
The narrowly marked expected failure preserves the observed timing defect;
it does not certify native character acquisition or any route/arrival clause.
No plugin callbacks, trigger receipts or effect rows are installed by this test.
"""
import pytest

from tests.worker2_support import ALLY, FOE, OWNER, candidate, fixture, reload, settle, turn


PREFIX = 'tianxia.subpath.qi.riverway_cultivator.feature.'
FERRY = PREFIX + 'ferry_the_wounded'
REACTION = 'reaction:typed.' + FERRY
AXE = {'starting_kit': {'items': [
    {'item_id': 'tianxia.mortal.weapon.fu', 'name': 'Fu (Short Axe)', 'quantity': 1}
]}}


class FerryBeforeDamage(AssertionError):
    """Only the demonstrated pre-settlement reaction is an expected failure."""


def wounded_table(tmp_path, *, owned=True, distant=False):
    """Compile ordinary sheet records and attack with a genuinely compiled weapon.

    This intentionally tests the combat adapter below character acquisition;
    do not describe the sheet's supplied ownership as a native acquisition receipt.
    """
    combat, table, mid = fixture(
        tmp_path, [FERRY] if owned else [], cl=6, named=True, foe_kit=AXE,
        positions={OWNER: {'x': 11 if distant else 3, 'y': 6},
                   ALLY: {'x': 4, 'y': 6}, FOE: {'x': 5, 'y': 6}},
        seed='MGR-T14-FERRY-SETTLEMENT')
    turn(table, mid, FOE)
    return combat, table, mid


def damage_ally(combat, table, mid, tmp_path):
    """Find a real damaging attack, declining unrelated reactions along the way."""
    for _ in range(12):
        before = len(reload(tmp_path, mid).events)
        prompts = settle(table, mid,
            candidate(combat, mid, 'Fu (Short Axe) attack', target=ALLY).candidate_id,
            choices={REACTION: 'first'})
        engine = reload(tmp_path, mid)
        events = engine.events[before:]
        if any(e.event_type == 'DAMAGE_COMMITTED' and ALLY in e.target_ids
               and int(e.payload.get('hp_damage') or 0)
               + int(e.payload.get('temporary_hp_absorbed') or 0) > 0 for e in events):
            return engine, events, prompts
        # A miss still spends the Action. Advance the actual turn before
        # looking for another weapon attack by this same creature.
        settle(table, mid, table.state(mid)['menu']['end_turn'])
        turn(table, mid, FOE)
    pytest.fail('The bounded stock-weapon probe never dealt damage')


@pytest.mark.xfail(strict=True, raises=FerryBeforeDamage,
    reason='PARTIAL: generic ally_damaged consumes Ferry before damage is committed')
def test_ferry_response_follows_real_damage_commit_and_cold_replay(tmp_path):
    combat, table, mid = wounded_table(tmp_path)
    engine, events, prompts = damage_ally(combat, table, mid, tmp_path)
    assert any(p['context']['reaction_source_id'] == REACTION for p in prompts), prompts
    damage = next(i for i, e in enumerate(events)
                  if e.event_type == 'DAMAGE_COMMITTED' and ALLY in e.target_ids)
    response = next(i for i, e in enumerate(events)
                    if e.event_type == 'REACTION_WINDOW_OPENED'
                    and e.source_definition_id == FERRY)
    compact = [(e.event_type, e.source_definition_id, e.actor_id, e.target_ids)
               for e in events if e.event_type in {
                   'DAMAGE_COMMITTED', 'REACTION_WINDOW_OPENED', 'REACTION_RESOLVED',
                   'RESOURCE_SPENT', 'TEMP_HP_GRANTED', 'MOVEMENT_COMMITTED'}]
    print('FERRY_SETTLEMENT_EVIDENCE', compact)
    assert not engine.state.actors[OWNER].reaction_available
    if response < damage:
        raise FerryBeforeDamage('Ferry response precedes the ally damage commit: ' + repr(compact))
    assert damage < response


@pytest.mark.parametrize('owned,distant', [(False, False), (True, True)])
def test_wrong_owner_and_outside_thirty_feet_do_not_offer_ferry(tmp_path, owned, distant):
    combat, table, mid = wounded_table(tmp_path, owned=owned, distant=distant)
    engine, events, prompts = damage_ally(combat, table, mid, tmp_path)
    assert not any(p['context']['reaction_source_id'] == REACTION for p in prompts)
    assert not any(e.source_definition_id == FERRY and e.event_type in {
        'REACTION_WINDOW_OPENED', 'RESOURCE_SPENT', 'TEMP_HP_GRANTED'} for e in events)
    assert engine.state.actors[OWNER].reaction_available

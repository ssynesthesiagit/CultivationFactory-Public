"""A real parked Haft Guard survives a table commit and reload."""
from combat.gate5_service import CombatServiceError
from tests.worker2_support import fixture, reload, candidate, settle, turn, OWNER, FOE, sealed_native_attack

HAFT = 'TAL_AXES_HAFT_GUARD'
KIT = {'starting_kit': {'items': [{'item_id': 'tianxia.mortal.weapon.fu', 'name': 'Fu (Short Axe)', 'quantity': 1}]}}


def test_haft_guard_parked_reduction_commits_and_reloads(tmp_path):
    def prepare(bundles):
        sealed_native_attack(bundles[2], 'Melee Blow', damage_type='SLASHING',
                             count=1, sides=2, modifier=30, attack_bonus=100, range_ft=None)

    combat, table, mid = fixture(tmp_path, [HAFT], owner_kit=KIT, owner_ac=10,
                                foe_position={'x': 4, 'y': 6}, ally_position={'x': 4, 'y': 7},
                                bundle_transform=prepare)
    turn(table, mid, FOE)
    before = reload(tmp_path, mid).state.actors[OWNER].current_hp
    c = candidate(combat, mid, 'Melee Blow', target=OWNER)
    try:
        prompts = settle(table, mid, c.candidate_id, picks={HAFT: 'first'})
    except CombatServiceError as exc:
        raise AssertionError(exc.to_dict()) from exc
    engine = reload(tmp_path, mid)
    assert any(HAFT in p['context']['reaction_source_id'] for p in prompts)
    receipt = next(e for e in engine.events if e.event_type == 'REACTION_RESOLVED'
                   and e.source_definition_id == HAFT)
    assert receipt.payload['pending_damage_reduction'] > 0
    damage = next(e.payload for e in engine.events if e.event_type == 'DAMAGE_COMMITTED'
                  and OWNER in e.target_ids and e.source_definition_id.startswith('action:test.native.'))
    assert before - engine.state.actors[OWNER].current_hp == damage['hp_damage']
    assert damage['hp_damage'] < damage['rolled_or_pending_damage']

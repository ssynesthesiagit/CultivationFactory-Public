"""Refined Lotus Recovery adds the Witness's PB to its save through the paid-conversion provider (service level)."""
from tests.test_a2_foundations3 import add_action, setup, use, pool
from tests.worker2_support import OWNER, FOE, candidate, settle, turn, reload
from combat.ext.foundation_conversion_bonus import CLOCK

WITNESS = 'reaction:typed.foundation.mud_lotus_dantian_v0_2A.humble_medicine_witness'
EXPRESSION = 'Foundation expression: Refined — Lotus Recovery'


def test_refined_witness_spend_adds_pb_to_the_save(tmp_path):
    def delivery(bundles):
        add_action(bundles[2], 'Scoped save', [{'type': 'save', 'ability': 'CON', 'dc': 30, 'save_categories': ['poisoned'],
            'on_fail': [{'type': 'damage', 'flat': 1, 'damage_types': ['force'], 'applies_to': 'target'}], 'on_success': []}],
            dc=30, economy='NONE')
    combat, table, mid = setup(tmp_path, 'lotus', initial=1, stage='Refined', extra=delivery)
    turn(table, mid, OWNER)
    use(combat, table, mid, EXPRESSION, OWNER)
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Scoped save', target=OWNER).candidate_id, choices={WITNESS: 'USE'})
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[pool('lotus')] == 0
    receipt = engine.state.actors[OWNER].turn_flags[CLOCK]['receipt']
    assert receipt['conversion'] == 'humble_medicine_witness'
    # The PB is read from the Witness's own passive row, not assumed: Refined adds 1 x PB to the paid receipt.
    row = next(r for r in engine.typed_passive_rows[engine.state.actors[OWNER].entity_id]
               if r.get('feature_id') == WITNESS.removeprefix('reaction:typed.'))
    pb = int(row['pb'])
    assert receipt['bonus'] == pb
    # The applied bonus: the Witness's own PB plus the Refined PB lands on the rewritten save.
    rewrites = [e for e in engine.events if e.event_type == 'D20_REWRITTEN'
                and e.source_definition_id == WITNESS.removeprefix('reaction:typed.')]
    assert len(rewrites) == 1
    payload = rewrites[0].payload or {}
    assert payload['result']['modifier'] - payload['original']['modifier'] == 2 * pb

"""Humble Medicine Witness: after a scoped save or check, spend Lotus Dew to add the Proficiency Bonus to the same roll."""
from tests.test_a2_foundations3 import add_action, setup, pool
from tests.worker2_support import OWNER, FOE, candidate, settle, turn, reload

WITNESS = 'reaction:typed.foundation.mud_lotus_dantian_v0_2A.humble_medicine_witness'
FEATURE = 'foundation.mud_lotus_dantian_v0_2A.humble_medicine_witness'


def _save(tmp_path, category, *, accept=True, initial=1):
    def delivery(bundles):
        add_action(bundles[2], 'Scoped save', [{'type': 'save', 'ability': 'CON', 'dc': 30, 'save_categories': [category],
            'on_fail': [{'type': 'damage', 'flat': 1, 'damage_types': ['force'], 'applies_to': 'target'}], 'on_success': []}],
            dc=30, economy='NONE')
    combat, table, mid = setup(tmp_path, 'lotus', initial=initial, extra=delivery)
    turn(table, mid, FOE)
    prompts = settle(table, mid, candidate(combat, mid, 'Scoped save', target=OWNER).candidate_id,
                     choices={WITNESS: 'USE' if accept else None})
    return prompts, reload(tmp_path, mid)


def _offered(prompts):
    return any(p['context']['reaction_source_id'] == WITNESS for p in prompts)


def test_a_scoped_save_offers_the_witness_and_spends_one_dew(tmp_path):
    prompts, engine = _save(tmp_path, 'poisoned')
    assert _offered(prompts)
    assert engine.state.actors[OWNER].resources[pool('lotus')] == 0
    assert [e for e in engine.events if e.event_type == 'D20_REWRITTEN'][-1].source_definition_id == FEATURE


def test_declining_spends_nothing(tmp_path):
    prompts, engine = _save(tmp_path, 'poisoned', accept=False)
    assert _offered(prompts)
    assert engine.state.actors[OWNER].resources[pool('lotus')] == 1


def test_a_save_outside_the_scope_is_not_offered(tmp_path):
    prompts, engine = _save(tmp_path, 'frightened')
    assert not _offered(prompts)
    assert engine.state.actors[OWNER].resources[pool('lotus')] == 1


def test_without_dew_nothing_is_offered(tmp_path):
    prompts, engine = _save(tmp_path, 'poisoned', initial=0)
    assert not _offered(prompts)

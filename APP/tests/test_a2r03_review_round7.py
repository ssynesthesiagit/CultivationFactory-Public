"""Signed Marrow Pack Guard arithmetic through table consent and cold reload."""
import pytest

from combat.ability_checks import key_modifier
from tests import test_a2r11_foundations as fixtures
from tests.test_a2r03_fix_round import _prepare_pressure, _play_picked, _add_companion, COMPANION
from tests.test_a2r03_review_repairs import _action


@pytest.mark.parametrize('protected,modifier', [
    (fixtures.FIGHTER, -1), (fixtures.SERVICE_ALLY, -1), (COMPANION, -5)])
@pytest.mark.parametrize('consent', ['USE', 'DECLINE'])
def test_negative_modifier_guard_is_offered_paid_and_exact_after_table_reload(
        tmp_path, monkeypatch, protected, modifier, consent):
    original_doc = fixtures._doc

    def low_constitution(*args, **kwargs):
        doc = original_doc(*args, **kwargs)
        if kwargs.get('foundation'):
            for ability in doc['ability_scores_and_statistics']['abilities']:
                if ability['ability'] == 'CON':
                    ability.update(score=10 + 2 * modifier, modifier=modifier)
        return doc

    monkeypatch.setattr(fixtures, '_doc', low_constitution)

    def prepare(bundles):
        _prepare_pressure('WIS', 30, 'frightened', held=1)(bundles)
        if protected == COMPANION:
            _add_companion(bundles)
        blow = _action(bundles, 'Beast blow', [{'type': 'damage', 'applies_to': 'target',
            'flat': 10, 'damage_types': ['bludgeoning']}])
        blow['range_ft'] = 120  # The summoned companion can arrive beyond Unarmed Strike reach.

    combat, table, mid = fixtures._service_fight(
        tmp_path, monkeypatch, fixtures._marrow(
            'Perfected' if protected == COMPANION else 'Awakened'), fixtures.MARROW_BARE,
        ally=True, foe_creature_types=('Beast',), prepare=prepare)
    before = fixtures._engine(combat, mid)
    owner = before.state.actors[fixtures.FIGHTER]
    assert key_modifier(before, owner) == modifier
    reduction = owner.proficiency_bonus * (2 if protected == COMPANION else 1) + modifier
    assert reduction > 0
    hp = before.state.actors[protected].current_hp

    def pick(prompt):
        return consent if prompt['reaction'] == 'Marrow Pack Guard' else 'DECLINE'

    _, prompts = _play_picked(table, mid, fixtures._candidate(
        table, mid, 'Beast blow', protected), pick)
    assert any(p['reaction'] == 'Marrow Pack Guard' for p in prompts)
    cold = fixtures._engine(combat, mid)
    owner = cold.state.actors[fixtures.FIGHTER]
    assert key_modifier(cold, owner) == modifier
    assert cold.state.actors[protected].current_hp == hp - 10 + (
        reduction if consent == 'USE' else 0)
    assert owner.resources[fixtures.ECHO] == (0 if consent == 'USE' else 1)
    assert owner.reaction_available is (consent == 'DECLINE')
    receipts = [e for e in cold.events if e.event_type == 'REACTION_RESOLVED'
                and e.source_definition_id == fixtures.M_GUARD]
    assert len(receipts) == (1 if consent == 'USE' else 0)

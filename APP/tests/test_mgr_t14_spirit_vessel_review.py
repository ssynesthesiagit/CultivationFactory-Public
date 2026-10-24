"""Service regressions for stored native-save grants and Speech bonus transport."""
import pytest

from tests.cw2_service_support import add_action
from tests.worker2_support import ALLY, FOE, OWNER, candidate, fixture, reload, settle, turn


@pytest.mark.parametrize('modes, expected', [
    (['advantage'], 'ADVANTAGE'),
    (['disadvantage'], 'DISADVANTAGE'),
    (['advantage', 'disadvantage'], 'NORMAL'),
])
def test_hazard_consumes_stored_next_dex_modes_once_without_vessel(tmp_path, modes, expected):
    from combat.ext.save_against import CONDITION

    def prepare(bundles):
        add_action(bundles[0], 'Prepare next Dexterity save', [
            {'type': mode, 'on': 'the next Dexterity saving throw', 'applies_to': 'target',
             'duration': {'kind': 'until_removed'}} for mode in modes])

    def arena(battlefield):
        battlefield['terrain_regions'].append({
            'terrain_type': 'QI_HAZARD', 'cells': [{'x': 4, 'y': 7}], 'movement_cost': 5})

    combat, table, mid = fixture(tmp_path, [], bundle_transform=prepare,
                                battlefield_transform=arena, seed='VESSEL-REVIEW-HAZARD')
    settle(table, mid, candidate(combat, mid, 'Prepare next Dexterity save', target=ALLY).candidate_id)
    before = reload(tmp_path, mid)
    held = {iid for iid, c in before.state.actors[ALLY].conditions.items() if c.condition_id == CONDITION}
    assert len(held) == len(modes)
    turn(table, mid, ALLY)
    move = next(row['candidate_id'] for row in table.state(mid)['menu']['moves']
                if row.get('destination') == {'x': 4, 'y': 7})
    settle(table, mid, move)
    engine = reload(tmp_path, mid)
    saves = [r for r in engine.rolls if r.actor_id == ALLY and r.reason == 'QI_HAZARD_DEX_SAVE']
    assert len(saves) == 1 and saves[0].mode == expected
    assert len(saves[0].dice) == (1 if expected == 'NORMAL' else 2)
    assert not held.intersection(engine.state.actors[ALLY].conditions)
    removals = [e.payload['instance_id'] for e in engine.events
                if e.event_type == 'CONDITION_REMOVED' and e.payload.get('instance_id') in held]
    assert sorted(removals) == sorted(held)


@pytest.mark.parametrize('forced_mode, expected', [(None, 'ADVANTAGE'), ('DISADVANTAGE', 'NORMAL')])
def test_speech_concentration_save_keeps_numeric_support_and_unsimplified_modes(
        tmp_path, monkeypatch, forced_mode, expected):
    """A fake scalar provider isolates transport; ownership policy is tested separately.

    Stable Modulation creates the real held grant. The scenario action invokes
    Speech's production concentration_save effect, as Locked Breath Method does.
    No engine/save/collector is replaced, and no live client is involved.
    """
    from combat import support_values
    from combat.concentration import MODE
    from combat.gate2_engine import SYSTEM_CONCENTRATION

    calls = []

    def bonus(engine, provider, beneficiary, source, purpose):
        calls.append((provider.entity_id, beneficiary.entity_id, source, purpose))
        return 4

    monkeypatch.setattr(support_values, 'resolve_save_bonus', bonus)

    def prepare(bundles):
        add_action(bundles[2], 'Press held breath', [
            {'type': 'concentration_save', 'applies_to': 'target',
             **({'mode': forced_mode} if forced_mode else {})}])
        if forced_mode:
            add_action(bundles[0], 'Persistent save support', [
                {'type': 'advantage', 'on': 'Constitution saving throws', 'applies_to': 'target',
                 'duration': {'kind': 'until_removed'}}])

    talents = ['TAL_QIWEAVING_TURBULENT_FIELD', 'TAL_QIWEAVING_STABLE_MODULATION']
    combat, table, mid = fixture(tmp_path, [], ally_talents=talents,
                                bundle_transform=prepare, named=True, seed='VESSEL-REVIEW-SPEECH')
    if forced_mode:
        settle(table, mid, candidate(combat, mid, 'Persistent save support', target=ALLY).candidate_id)
    turn(table, mid, ALLY)
    settle(table, mid, candidate(combat, mid, 'Turbulent Field + Stable Modulation', target=ALLY).candidate_id)
    before = reload(tmp_path, mid)
    held = {iid for iid, c in before.state.actors[ALLY].conditions.items() if c.condition_id == MODE}
    assert held and before.state.actors[ALLY].concentration is not None
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Press held breath', target=ALLY).candidate_id)
    engine = reload(tmp_path, mid)
    rolled = [r for r in engine.rolls if r.actor_id == ALLY and r.reason == f'SAVE:{SYSTEM_CONCENTRATION}:CON']
    assert len(rolled) == 1 and rolled[0].mode == expected
    assert calls and calls[0][:2] == (ALLY, ALLY) and calls[0][3] == 'concentration'
    assert rolled[0].modifier == engine.state.actors[ALLY].saving_throws['CON'] + 4
    assert not held.intersection(engine.state.actors[ALLY].conditions)


@pytest.mark.parametrize('reader', ['save_mode', 'save_modes'])
def test_mode_only_concentration_readers_do_not_resolve_or_spend_numeric_support(tmp_path, monkeypatch, reader):
    from combat import concentration, support_values

    def forbidden_bonus(*args):
        pytest.fail('A mode-only reader must not resolve or spend a numeric support value')

    monkeypatch.setattr(support_values, 'resolve_save_bonus', forbidden_bonus)
    talents = ['TAL_QIWEAVING_TURBULENT_FIELD', 'TAL_QIWEAVING_STABLE_MODULATION']
    combat, table, mid = fixture(tmp_path, talents, seed='VESSEL-REVIEW-MODE-ONLY')
    settle(table, mid, candidate(combat, mid, 'Turbulent Field + Stable Modulation', target=OWNER).candidate_id)
    engine = reload(tmp_path, mid)
    actor = engine.state.actors[OWNER]
    held = {iid for iid, c in actor.conditions.items() if c.condition_id == concentration.MODE}
    assert held
    expected = 'ADVANTAGE' if reader == 'save_mode' else {'ADVANTAGE'}
    assert getattr(concentration, reader)(engine, actor) == expected
    assert not held.intersection(actor.conditions)

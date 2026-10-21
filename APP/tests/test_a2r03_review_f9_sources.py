"""F9: opaque forged Guard provenance and the State's saves-only boundary.

The published snapshot replaces printed rules text with pseudowords, so it does
not compile the Marrow Pack Guard reaction (combat/factory_compiler.py:2017).
The Guard parameters that need the compiled row carry ``requires_private_prose``.
"""
import pytest

from combat.ext import beast_echo_marrow as marrow
from combat.gate5_service import CombatService
from combat.typed_executor import check_modes
from tests.public_snapshot import requires_private_prose
from tests.test_a2r03_fix_round import _prepare_pressure, _play_picked
from tests.test_a2r03_review_repairs import _action
from tests.test_a2r11_foundations import (
    ROOT, FIGHTER, SERVICE_FOE, MARROW_BARE, ECHO, ME, ALLY, FOE, M_STATE,
    _marrow, _service_fight, _candidate, _engine, _duel, give, use,
    script, force_save,
)


@pytest.mark.parametrize('source,lineage,qualifies', [
    pytest.param('forged:3c178a9f', 'tianxia.talent.blood.strike', True, marks=requires_private_prose),
    pytest.param('tianxia.talent.blood.strike', 'TAL_BRUTE_MOUNTAIN_MOVING_PALM', True,
                 marks=requires_private_prose),
    ('forged:3c178a9f', 'TAL_BRUTE_MOUNTAIN_MOVING_PALM', False),
])
def test_opaque_forged_guard_provenance_survives_table_reload(
        tmp_path, monkeypatch, source, lineage, qualifies):
    opaque = 'action:typed.4581a9.forged.734e1a89c503'

    def prepare(bundles):
        _prepare_pressure('WIS', 30, 'frightened', held=1)(bundles)
        # Match factory_compiler's forged shape: neither hash names its sphere.
        row = _action(bundles, 'Blood in the title is not provenance', [
            {'type': 'damage', 'applies_to': 'target', 'flat': 10,
             'damage_types': ['bludgeoning']}], source=opaque)
        row['parameters']['typed'].update(source=source, forged_from=lineage,
                                          typing_status='forged', base_form='Strike')

    combat, table, mid = _service_fight(
        tmp_path, monkeypatch, _marrow('Awakened'), MARROW_BARE,
        foe_creature_types=('Humanoid',), prepare=prepare)
    before = _engine(CombatService(ROOT, tmp_path), mid)
    assert before.action_catalog[opaque].parameters['typed']['forged_from'] == lineage
    owner = before.state.actors[FIGHTER]
    hp, held = owner.current_hp, owner.resources[ECHO]
    assert held == 1 and owner.reaction_available
    assert not any(e.event_type == 'DAMAGE_COMMITTED' for e in before.events)
    _, prompts = _play_picked(
        table, mid, _candidate(table, mid, 'Blood in the title is not provenance', FIGHTER),
        lambda p: 'USE' if p['reaction'] == 'Marrow Pack Guard' else 'DECLINE')
    cold = _engine(CombatService(ROOT, tmp_path), mid)
    owner = cold.state.actors[FIGHTER]
    assert any(p['reaction'] == 'Marrow Pack Guard' for p in prompts) is qualifies
    assert owner.resources[ECHO] == held - int(qualifies)
    assert owner.reaction_available is (not qualifies)
    reduction = before.state.actors[FIGHTER].proficiency_bonus + 2
    assert owner.current_hp == hp - 10 + (reduction if qualifies else 0)
    receipts = [e for e in cold.events if e.event_type == 'REACTION_RESOLVED'
                and e.source_definition_id == marrow.GUARD]
    assert len(receipts) == int(qualifies)


@pytest.mark.parametrize('subject_id', [ME, ALLY])
@pytest.mark.parametrize('ability', ['STR', 'DEX', 'CON', 'INT', 'WIS', 'CHA'])
def test_state_grants_beast_pressure_save_advantage_but_no_check_advantage(subject_id, ability):
    engine = _duel([M_STATE], _marrow('Perfected'), ally_mids=[])
    engine.state.actors[FOE].creature_types = ('Beast',)
    give(engine, ME, pack_echo=1)
    use(engine, 'Beast-Echo Marrow State')
    subject = engine.state.actors[subject_id]
    assert any(c.condition_id == marrow.STATE_CONDITION for c in subject.conditions.values())
    with engine.d20_scope({'kind': 'check', 'source_actor_id': FOE,
                           'actor_id': subject_id, 'ability': ability}):
        assert 'ADVANTAGE' not in check_modes(
            subject, ability, engine=engine, hazards=('forced_movement',))
    script(engine, [10, 10])
    save = force_save(engine, subject_id, ability, dc=12, typed=True,
                      condition='frightened', forcer=FOE)
    assert save.payload['mode'] == 'ADVANTAGE'

"""Void Needle's real Cost Lock option blocks native and plug-in discounts."""
import json
import zipfile

import pytest

from combat.ext.void_riders import COST_LOCK, NEEDLE, COST_DENY, USED
from combat.gate2_runtime_models import ActionIntent
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.typed_executor import mark_condition_id
from tests.h1_support import ROOT, sheet
from tests.test_hidden_targeting import turn
from tests.test_lock_choices import install
from tests.test_lock2_persistence import act
from tests.r10_fixup_support import cast_sender, commit

CASTER, TARGET = 'actor:factory.aaaaaaaa', 'actor:factory.ffffffff'
QI = 'resource:core.qi'
EFFICIENCY = 'tianxia.path.qi_cultivation.feature.golden_core_efficiency'


def fight(monkeypatch, tmp_path, *, denying=False, hit=True, target_extra=()):
    for pid in ('aaaaaaaa', 'ffffffff'):
        owned = [NEEDLE, *([COST_DENY] if denying else [])] if pid == 'aaaaaaaa' else [
            EFFICIENCY, 'tianxia.talent.blood.blood_mending', *target_extra]
        doc = sheet(owned)
        doc['identity']['display_name'] = 'Caster' if pid == 'aaaaaaaa' else 'Target'
        folder = tmp_path / 'portable_characters' / pid
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / 'current.zip', 'w') as z:
            z.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(doc))
    install(monkeypatch, 'd20_result', lambda *a: {'source_id': 'test:attack-result',
        'operation': 'replace', 'natural_result': 20 if hit else 1})
    def prepare(engine, kind, kwargs):
        if kind != 'HOLD_POSITION_COMMITTED':
            return
        target = engine.state.actors[TARGET]
        if kwargs['actor_id'] == CASTER:
            engine._apply_condition(target, mark_condition_id('Blood Thread', TARGET), 'test:thread', TARGET,
                expires_on='UNTIL_REMOVED', data={'mark': 'Blood Thread'})
        else:
            engine._commit_damage(target, 5, 'UNTYPED', 'test:wound', CASTER, None, reaction_depth=0)
    install(monkeypatch, 'event', prepare)
    combat = CombatService(ROOT, tmp_path)
    combat.tabletop_maps.save({'display_name': 'Void yard', 'width_squares': 12, 'height_squares': 8,
        'walls': [], 'starts': {'team1': [[3, 4]], 'team2': [[6, 4]]}})
    mid = combat.create_factory_match(project_ids=['aaaaaaaa'], opponent_actor_ids=[TARGET],
        control_modes={CASTER: 'MANUAL', TARGET: 'MANUAL'}, arena_id='battlefield:map.void-yard',
        match_seed='LOCK7-COST-LOCK')['match_id']
    table = TabletopService(combat, tmp_path)
    turn(table, mid, CASTER)
    assert act(table, mid, 'system:combat.hold_position')['status'] == 'COMMITTED'
    return combat, table, mid


def reload_checked(tmp_path, mid):
    session = CombatService(ROOT, tmp_path)._load_session(mid)
    assert session.verify()['status'] == session.mechanical.replay()['status'] == 'PASS'
    return session.engine


def cast_pressure(combat, table, mid, name='Cost Lock'):
    return commit(cast_sender(combat, table, mid, 'Void Needle', target=TARGET, contains=name))


@pytest.mark.parametrize('pressure,hit,locked', [('Cost Lock', True, True), ('Cost Lock', False, False),
                                              ('Empty Vitality', True, False), ('Unsettle Invisibility', True, False)])
def test_real_option_blocks_qi_discount_and_survives_reload(monkeypatch, tmp_path, pressure, hit, locked):
    combat, table, mid = fight(monkeypatch, tmp_path, hit=hit)
    assert not cast_pressure(combat, table, mid, pressure)
    e = reload_checked(tmp_path, mid)
    assert any(c.condition_id == COST_LOCK for c in e.state.actors[TARGET].conditions.values()) is locked
    assert bool(e.state.actors[CASTER].turn_flags.get(USED)) is hit
    turn(table, mid, TARGET)
    assert act(table, mid, 'system:combat.hold_position')['status'] == 'COMMITTED'
    before = combat._load_session(mid).engine.state.actors[TARGET].resources[QI]
    commit(cast_sender(combat, table, mid, 'Blood Mending', target=TARGET))
    e = reload_checked(tmp_path, mid)
    assert e.state.actors[TARGET].resources[QI] == before - (3 if locked else 2)
    assert bool(e.state.actors[TARGET].turn_flags.get('golden_core_efficiency')) is not locked


def test_expiry_restores_real_discount_on_source_next_turn(monkeypatch, tmp_path):
    combat, table, mid = fight(monkeypatch, tmp_path)
    cast_pressure(combat, table, mid)
    assert act(table, mid, 'end')['status'] == 'COMMITTED'
    turn(table, mid, CASTER)
    e = reload_checked(tmp_path, mid)
    assert not any(c.condition_id == COST_LOCK for c in e.state.actors[TARGET].conditions.values())
    assert not e.state.actors[CASTER].turn_flags.get(USED)
    assert act(table, mid, 'end')['status'] == 'COMMITTED'
    turn(table, mid, TARGET)
    assert act(table, mid, 'system:combat.hold_position')['status'] == 'COMMITTED'
    before = combat._load_session(mid).engine.state.actors[TARGET].resources[QI]
    commit(cast_sender(combat, table, mid, 'Blood Mending', target=TARGET))
    assert reload_checked(tmp_path, mid).state.actors[TARGET].resources[QI] == before - 2


@pytest.mark.parametrize('denying', [False, True])
def test_cost_denying_is_explicitly_manual_without_recovery_provenance(monkeypatch, tmp_path, denying):
    combat, table, mid = fight(monkeypatch, tmp_path, denying=denying)
    cast_pressure(combat, table, mid)
    def regain(engine, kind, kwargs):
        if kind == 'HOLD_POSITION_COMMITTED' and kwargs['actor_id'] == TARGET:
            target = engine.state.actors[TARGET]
            engine._spend_resource(target, QI, 2, 'test:spend')
            engine._gain_resource(target, QI, 2, 'test:temporary-restoration')
    install(monkeypatch, 'event', regain)
    turn(table, mid, TARGET)
    before = combat._load_session(mid).engine.state.actors[TARGET].resources[QI]
    assert act(table, mid, 'system:combat.hold_position')['status'] == 'COMMITTED'
    e = reload_checked(tmp_path, mid)
    assert e.state.actors[TARGET].resources[QI] == before
    assert not any(c.condition_id == 'condition:typed.no_cp_regain' for c in e.state.actors[TARGET].conditions.values())
    notes = [row['summary'] for row in table.events(mid, 0)['events'] if 'Recovery is not blocked automatically' in row['summary']]
    assert bool(notes) is denying
    if denying:
        assert 'Target' in notes[0] and 'permanent' in notes[0] and 'temporary' in notes[0]


def test_permanent_stable_golden_core_recovers_after_cost_denying_hit(monkeypatch, tmp_path):
    from combat.ext.qi_path import GOLDEN
    combat, table, mid = fight(monkeypatch, tmp_path, denying=True, target_extra=[GOLDEN])
    def empty(engine, kind, kwargs):
        if kind == 'HOLD_POSITION_COMMITTED' and kwargs['actor_id'] == CASTER:
            target = engine.state.actors[TARGET]
            engine._spend_resource(target, QI, target.resources[QI], 'test:empty-pool')
    install(monkeypatch, 'event', empty)
    assert act(table, mid, 'system:combat.hold_position')['status'] == 'COMMITTED'
    cast_pressure(combat, table, mid)
    turn(table, mid, TARGET)
    e = reload_checked(tmp_path, mid)
    assert e.state.actors[TARGET].resources[QI] > 0
    assert any(ev.event_type == 'RESOURCE_GAINED' and ev.source_definition_id == f'passive:{GOLDEN}.stable' for ev in e.events)
    assert any(c.condition_id == COST_LOCK for c in e.state.actors[TARGET].conditions.values())


@pytest.mark.parametrize('locked,funds,payment', [(False, 2, 2), (True, 2, None), (True, 3, 3)])
def test_real_blossom_discount_availability_payment_and_reload(monkeypatch, tmp_path, locked, funds, payment):
    from combat.ext.blossom import SCRIPTURE, SEED
    combat, table, mid = fight(monkeypatch, tmp_path, target_extra=[SCRIPTURE, SEED])
    turn(table, mid, TARGET)
    commit(cast_sender(combat, table, mid, 'Ten-Thousand Bloom Scripture'))
    commit(cast_sender(combat, table, mid, 'Blossom: Exploding Seed'))
    assert act(table, mid, 'end')['status'] == 'COMMITTED'
    turn(table, mid, CASTER)
    cast_pressure(combat, table, mid, 'Cost Lock' if locked else 'Empty Vitality')
    turn(table, mid, TARGET)
    def budget(engine, kind, kwargs):
        if kind == 'HOLD_POSITION_COMMITTED' and kwargs['actor_id'] == TARGET:
            target = engine.state.actors[TARGET]
            engine._spend_resource(target, QI, target.resources[QI] - funds, 'test:budget')
    install(monkeypatch, 'event', budget)
    assert act(table, mid, 'system:combat.hold_position')['status'] == 'COMMITTED'
    offers = [c for c in combat._load_session(mid).engine.legal_candidates()
              if c.display_name.startswith('Cultivate Blossom (bloom at once)')]
    assert bool(offers) is (payment is not None)
    if payment is not None:
        commit(cast_sender(combat, table, mid, 'Cultivate Blossom (bloom at once)', at=(7, 4)))
    e = reload_checked(tmp_path, mid)
    assert e.state.actors[TARGET].resources[QI] == funds - (payment or 0)
    # This plug-in spends the quote at bloom time; it must not issue a compensating refund.
    assert not any(ev.event_type == 'RESOURCE_GAINED' and '.blossom.' in ev.source_definition_id for ev in e.events)


def test_public_discount_quotes_preserve_all_printed_pools_without_mutation(monkeypatch, tmp_path):
    combat, table, mid = fight(monkeypatch, tmp_path)
    cast_pressure(combat, table, mid)
    e = reload_checked(tmp_path, mid); actor = e.state.actors[TARGET]
    listed = ((QI, 3), ('resource:core.stamina', 2), ('resource:core.martial_focus', 1))
    reduced = ((QI, 1), ('resource:core.stamina', 0), ('resource:core.martial_focus', 0))
    before = e.state.model_dump(mode='json'), list(e.events), e.roller.counter
    assert e.effective_costs(actor, 'test:multi-pool', listed, reduced_costs=reduced) == listed
    assert e.effective_costs(actor, 'test:multi-pool', listed, reduced_costs=((QI, 4),)) == (
        (QI, 4), ('resource:core.stamina', 2), ('resource:core.martial_focus', 1))
    assert (e.state.model_dump(mode='json'), e.events, e.roller.counter) == before


@pytest.mark.parametrize('first,second', [('Cost Lock', 'Empty Vitality'), ('Empty Vitality', 'Cost Lock'),
                                      ('Unsettle Invisibility', 'Cost Lock')])
def test_pressure_options_share_once_per_turn_after_saved_first_hit(monkeypatch, tmp_path, first, second):
    combat, table, mid = fight(monkeypatch, tmp_path)
    cast_pressure(combat, table, mid, first)
    e = reload_checked(tmp_path, mid)
    # Unit continuation of the verified saved hit: grant an extra action to
    # exercise two hits in one turn without adding an unrelated ability port.
    e.state.actors[CASTER].action_available = True
    e.state.actors[TARGET].current_hp = e.state.actors[TARGET].maximum_hp
    before = {k: c.model_dump(mode='json') for k, c in e.state.actors[TARGET].conditions.items()}
    c = next(c for c in e.legal_candidates() if 'Void Needle' in c.display_name and second in c.display_name and c.target_ids == (TARGET,))
    e.execute_intent(ActionIntent(intent_id='test:second-pressure', decision_id=c.decision_id,
        candidate_id=c.candidate_id, state_version=c.state_version, actor_id=CASTER, target_ids=c.target_ids))
    assert {k: c.model_dump(mode='json') for k, c in e.state.actors[TARGET].conditions.items()} == before

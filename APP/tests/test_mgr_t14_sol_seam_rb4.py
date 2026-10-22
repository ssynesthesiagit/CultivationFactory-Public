"""Regression receipts for the Sol seam review F17R (RB4) on Iron Oath consumers.

Each test fails on the tree before its fix:
- F1: the Scar-Ledger receipt lived on the engine (`_iron_scar_pending`) and was lost on reload.
- F3: the RB3 Stand-Fast tests were shape checks only; these run real fights.
- F4: validate_project took an arbitrary first project action; qualified_pressure ignored
  known_only for GM-recorded subject pressures; save_advancement ran for a missing project row.
"""
import json
from types import SimpleNamespace

import pytest

from combat.ext import foundation_combat as f
from combat.ext import iron_oath_consumers as ioc
from combat import project_checks, protected_subjects, source_effects
from combat import target_knowledge
from tests.test_mgr_t14_iron_oath_3 import oath_table, use
from tests.worker2_support import OWNER, FOE, turn, reload


def _scar_fight(tmp_path):
    combat, table, mid = oath_table(tmp_path, stage='Refined', dc=1)
    use(combat, table, mid, 'Foundation expression: Scar-Ledger Defense')
    turn(table, mid, FOE)
    use(combat, table, mid, 'Pressure hit', OWNER)
    return combat, table, mid


def test_f1_scar_receipt_lives_on_the_owner_and_survives_a_reload_before_settlement(tmp_path, monkeypatch):
    """The Witness receipt must be persisted on the paying owner before settlement, so a
    save/reload between the paid roll and its final outcome still leaves the bar pending."""
    snapshots = []
    real_settle = ioc.settle_scar_roll

    def snapshot_then_settle(engine, roll_id, success):
        snapshots.append((roll_id, json.dumps(engine.state.actors[OWNER].turn_flags, default=str),
                          hasattr(engine, '_iron_scar_pending')))
        return real_settle(engine, roll_id, success)

    monkeypatch.setattr(ioc, 'settle_scar_roll', snapshot_then_settle)
    combat, table, mid = _scar_fight(tmp_path)
    use(combat, table, mid, 'Frightful Roar', choices={f.CHOICE + 'foundation_combat': ['use']})
    assert snapshots, 'the paid Witness roll reached settlement'
    roll_id, persisted, on_engine = snapshots[-1]
    assert ioc.SCAR_PENDING in persisted and roll_id in persisted, 'receipt persisted on the owner'
    assert not on_engine, 'no engine-level receipt attribute'
    engine = reload(tmp_path, mid)
    assert ioc.SCAR_PENDING not in engine.state.actors[OWNER].turn_flags, 'settled receipt is cleared'


def test_f1_reload_between_roll_and_settlement_keeps_the_pending_receipt(tmp_path, monkeypatch):
    """Simulate a reload at settlement time: the receipt written to the owner round-trips through the
    persisted actor model and still settles (pops) to the same source and DC."""
    from combat.gate2_runtime_models import ActorState
    seen = {}
    real_settle = ioc.settle_scar_roll

    def reload_then_settle(engine, roll_id, success):
        owner = engine.state.actors[OWNER]
        restored = ActorState.model_validate(owner.model_dump(mode='json'))
        seen['receipt'] = restored.turn_flags.get(ioc.SCAR_PENDING, {}).get(roll_id)
        return real_settle(engine, roll_id, success)

    monkeypatch.setattr(ioc, 'settle_scar_roll', reload_then_settle)
    combat, table, mid = _scar_fight(tmp_path)
    use(combat, table, mid, 'Frightful Roar', choices={f.CHOICE + 'foundation_combat': ['use']})
    assert seen.get('receipt') is not None, 'receipt survives an actor serialization round trip'
    assert seen['receipt'][0] == OWNER


def test_f3_stand_fast_rewrite_is_the_typed_proficiency_bonus_on_the_real_roll(tmp_path):
    """Behaviour, not shape: the rewrite the engine applies carries the owner's actual proficiency bonus."""
    from tests.test_mgr_t14_iron_oath_3 import oath_table as _ot
    combat, table, mid = oath_table(tmp_path, stage='Refined', dc=100, damage=40)
    use(combat, table, mid, 'Foundation expression: Scar-Ledger Defense')
    turn(table, mid, FOE)
    use(combat, table, mid, 'Pressure hit', OWNER)
    use(combat, table, mid, 'Frightful Roar', choices={f.CHOICE + 'foundation_combat': ['use']})
    engine = reload(tmp_path, mid)
    changes = [e for e in engine.events if e.event_type == 'D20_REWRITTEN'
               and e.source_definition_id == f.feature('oath', 'stand_fast_witness')]
    assert changes, 'Stand-Fast Witness rewrote a real d20'
    assert changes[-1].payload['bonus'] == engine.state.actors[OWNER].proficiency_bonus


# ---- F4: fake-engine unit checks (no fight needed) ----

def _project_fixture(ability, keys):
    source = project_checks.SOURCE
    actions = {f'a{i}': SimpleNamespace(owner_id=OWNER, parameters={
        'typed': {'source': source}, 'project_cultivation_ability': key}) for i, key in enumerate(keys)}
    engine = SimpleNamespace(state=SimpleNamespace(actors={OWNER: object(), FOE: object()}), action_catalog=actions)
    project = SimpleNamespace(actor_id=OWNER, pressure_source_actor_id=None, skill='Cultivation',
                              ability=ability, sphere_ids=[])
    return engine, SimpleNamespace(project_check=project)


def test_f4_project_key_is_any_owned_projects_key_not_the_first_action(tmp_path):
    engine, fact = _project_fixture('WIS', ['INT', 'WIS'])
    project_checks.validate_project(engine, fact)  # the WIS project's own key is legitimate


def test_f4_project_key_outside_every_owned_projects_key_is_still_rejected():
    engine, fact = _project_fixture('CHA', ['INT', 'WIS'])
    with pytest.raises(ValueError, match='Key Ability'):
        project_checks.validate_project(engine, fact)


def _pressure_fixture(monkeypatch, *, visible_fact):
    pressure = SimpleNamespace(actor_id=FOE, verdict='qualifies')
    fact = SimpleNamespace(subject_pressures=[pressure], subject_kind='object', subject_id='obj:1')
    monkeypatch.setattr(protected_subjects, 'duties', lambda engine, actor: {'rec': (fact, None)})
    monkeypatch.setattr(target_knowledge, 'recent_events', lambda engine, actor, events: [{'sequence': 7}])
    events = [SimpleNamespace(event_type='TABLE_FACT_RECORDED', sequence=7, actor_id=None, target_ids=(),
                              payload={'fact': {'subject_id': 'obj:1' if visible_fact else 'other'}})]
    engine = SimpleNamespace(events=events)
    return engine, SimpleNamespace(entity_id=OWNER), SimpleNamespace(entity_id=FOE)


def test_f4_known_only_gm_subject_pressure_needs_a_visible_recording(monkeypatch):
    engine, actor, target = _pressure_fixture(monkeypatch, visible_fact=False)
    assert protected_subjects.qualified_pressure(engine, actor, 'rec', target, known_only=True) is False
    assert protected_subjects.qualified_pressure(engine, actor, 'rec', target) is True


def test_f4_known_only_gm_subject_pressure_counts_when_the_recording_is_visible(monkeypatch):
    engine, actor, target = _pressure_fixture(monkeypatch, visible_fact=True)
    assert protected_subjects.qualified_pressure(engine, actor, 'rec', target, known_only=True) is True


def test_f4_missing_project_row_keeps_the_receipt_pending_not_a_crash(monkeypatch):
    from combat.tabletop_service import FACTORY_PREFIX

    class Event:
        event_type = 'TABLE_FACT_RECORDED'
        sequence = 3
        match_id = 'm'

        def __init__(self, payload):
            self.payload = payload

        def model_dump(self, mode='json'):
            return {'sequence': self.sequence, 'payload': self.payload}

    project_id = 'proj-missing'
    state = {'power_id': 'power:p', 'state': 'ready', 'actor_id': FACTORY_PREFIX + project_id}
    acquisition = 'acq-1'
    document = {'power_states': [state], 'witness_ids': [FACTORY_PREFIX + project_id]}
    event = Event({'fact': document})
    engine = SimpleNamespace(events=[event], state=SimpleNamespace(actors={FACTORY_PREFIX + project_id: object()}))
    proposal = {'power_state': state, 'initial_acquisition_id': acquisition}
    monkeypatch.setattr(source_effects.ext, 'run_strict', lambda name, eng, ev: [[proposal]])

    class Buttons:
        def get(self, pid):
            return None

        def save_advancement(self, pid, saved):
            raise AssertionError('a missing project row must not be written')

    table = SimpleNamespace(buttons=Buttons())
    result = source_effects.settle(table, 'm', engine=engine)
    assert result['status'] == 'PENDING'
    assert result['recorded'] == 0

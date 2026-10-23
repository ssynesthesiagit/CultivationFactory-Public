"""Native table saves, real Foundation acquisition, hostile damage and reload.

Pressure actions use ordinary typed save/condition/damage rows. They introduce
no provenance tag: typed_executor produces the pending bodily condition facts.
"""
import pytest

from combat.gate2_rolls import DeterministicRollAuthority
from combat.ext import foundation_combat as f
from tests.test_a2_foundations_two import table_fixture, use
from tests.test_a2_foundations3 import add_action
from tests.worker2_support import OWNER, ALLY, FOE, turn, reload, settle

RESOURCE = f.pool('integrity')
RID = f.CHOICE + 'heavenly_rejection'
REJECTION = f.feature('integrity', 'integrity_rejection')
MARROW = f.feature('integrity', 'heaven_rejecting_marrow')


def fixed(monkeypatch, natural=8):
    original = DeterministicRollAuthority.raw_d20
    def draw(self, *, modifier, actor_id, reason, mode='NORMAL'):
        roll = original(self, modifier=modifier, actor_id=actor_id, reason=reason, mode=mode)
        if reason.startswith('SAVE:'):
            return roll.model_copy(update={'dice': (natural,), 'natural_result': natural,
                                           'total': natural + modifier})
        return roll
    monkeypatch.setattr(DeterministicRollAuthority, 'raw_d20', draw)


def setup(tmp_path, *, stage='Awakened', expression=False, current=0, modes=None):
    def delivery(bundles):
        for aid in (0, 1, 2):
            for name, ability, condition in [('Bodily poison', 'DEX', 'poisoned'),
                                              ('Constitution pressure', 'CON', 'poisoned'),
                                              ('Fear pressure', 'WIS', 'frightened')]:
                add_action(bundles[aid], name, [{'type': 'save', 'ability': ability,
                    'dc': 14, 'applies_to': 'target', 'on_fail': [
                        {'type': 'condition', 'condition': condition, 'applies_to': 'target'}],
                    'on_success': []}], economy='NONE', target_kind='ANY_CREATURE', dc=14)
        add_action(bundles[2], 'Damage then poison', [{'type': 'attack', 'attack_kind': 'weapon',
            'on_hit': [{'type': 'damage', 'flat': 1, 'damage_types': ['force']},
                       {'type': 'save', 'ability': 'DEX', 'dc': 15, 'applies_to': 'target',
                        'on_fail': [{'type': 'condition', 'condition': 'poisoned', 'applies_to': 'target'}],
                        'on_success': []}]}], economy='NONE', bonus=100, dc=15)
        add_action(bundles[2], 'Knock down', [{'type': 'damage', 'flat': 500,
            'damage_types': ['force'], 'applies_to': 'target'}], economy='NONE')
    combat, table, mid = table_fixture(tmp_path, 'integrity', stage=stage,
                                     current=current, transform=delivery, modes=modes)
    if expression:
        use(combat, table, mid, 'Foundation expression: Heaven-Rejecting Marrow')
    turn(table, mid, FOE)
    return combat, table, mid


def generate(combat, table, mid):
    use(combat, table, mid, 'Hostile blow', OWNER,
        choices={f.CHOICE + 'foundation_combat': None})
    engine = combat._load_session(mid).engine
    assert engine.state.actors[OWNER].resources[RESOURCE] == 1
    assert any(e.event_type == 'RESOURCE_GAINED' and e.actor_id == OWNER
               and e.payload.get('resource_id') == RESOURCE for e in engine.events)


def spent(engine):
    return [e for e in engine.events if e.event_type == 'RESOURCE_SPENT'
            and e.source_definition_id == REJECTION]


@pytest.mark.parametrize('stage,expression,bonus,phase', [
    ('Awakened', False, 4, 'before_outcome'),
    ('Refined', False, 4, 'before_outcome'),
    ('Refined', True, 4, 'after_failure'),
    ('Perfected', True, 8, 'after_failure')])
def test_hostile_bodily_save_cost_timing_and_cold_reload(tmp_path, monkeypatch, stage, expression, bonus, phase):
    fixed(monkeypatch)
    combat, table, mid = setup(tmp_path, stage=stage, expression=expression)
    generate(combat, table, mid)
    prompts = use(combat, table, mid, 'Bodily poison', OWNER, choices={RID: ['use']})
    prompt = next(p for p in prompts if p['context']['reaction_source_id'] == RID)
    assert 'Integrity Rejection' in str(prompt) and 'Bodily poison' in str(prompt)
    assert '1 Heavenly Integrity' in str(prompt)
    engine = reload(tmp_path, mid)
    actor = engine.state.actors[OWNER]
    resolved = [e for e in engine.events if e.source_definition_id == REJECTION and e.event_type == 'REACTION_RESOLVED']
    assert resolved[-1].payload['bonus'] == bonus and resolved[-1].payload['checkpoint'] == phase
    assert len(spent(engine)) == 1 and actor.resources[RESOURCE] == 0
    assert actor.reaction_available  # no Reaction or turn economy paid
    assert not any(c.condition_id.endswith('.poisoned') for c in actor.conditions.values())
    declarations = [e for e in engine.events if e.event_type == 'PASSIVE_TRIGGERED'
                    and e.payload.get('rule') == 'save_failure_declared' and e.actor_id == OWNER]
    assert bool(declarations) == expression
    if expression:
        assert declarations[-1].sequence < resolved[-1].sequence
        assert f.held(actor, 'expression').data['feature'] == MARROW


@pytest.mark.parametrize('case', ['empty', 'wrong_owner', 'nonbody', 'friendly_body', 'decline', 'same_event'])
def test_wrong_owner_body_boundary_empty_decline_and_same_event(tmp_path, monkeypatch, case):
    fixed(monkeypatch)
    combat, table, mid = setup(tmp_path)
    if case not in {'empty', 'same_event'}:
        generate(combat, table, mid)
    if case == 'friendly_body':
        # Preserve predecessor 27dc9f2c: stop before genuine resource expiry.
        # A self-produced non-CON bodily save is not a hostile effect.
        turn(table, mid, OWNER)
    target = ALLY if case == 'wrong_owner' else OWNER
    name = ('Fear pressure' if case == 'nonbody' else
            'Damage then poison' if case == 'same_event' else 'Bodily poison')
    prompts = use(combat, table, mid, name, target, choices={RID: None})
    engine = reload(tmp_path, mid)
    assert not spent(engine)
    assert any(p['context']['reaction_source_id'] == RID for p in prompts) == (case == 'decline')
    assert engine.state.actors[OWNER].resources[RESOURCE] == (0 if case == 'empty' else 1)


def test_manual_rejection_on_owners_turn(tmp_path, monkeypatch):
    fixed(monkeypatch)
    combat, table, mid = setup(tmp_path)
    generate(combat, table, mid)
    turn(table, mid, OWNER)
    prompts = use(combat, table, mid, 'Constitution pressure', OWNER, choices={RID: ['use']})
    assert any(p['context']['reaction_source_id'] == RID for p in prompts)
    engine = reload(tmp_path, mid)
    assert len(spent(engine)) == 1
    assert engine.state.actors[OWNER].resources[RESOURCE] == 0


def test_vessel_shared_clock_and_no_reuse_of_consumed_integrity(tmp_path, monkeypatch):
    fixed(monkeypatch)
    combat, table, mid = setup(tmp_path, stage='Perfected')
    generate(combat, table, mid)
    use(combat, table, mid, 'Constitution pressure', OWNER, choices={RID: ['use']})
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].turn_flags['foundation_round_vessel'] == engine.state.round_number
    # Production can't generate a second Integrity in the same round. Two
    # saves following one prior gain must not silently reuse that one unit.
    use(combat, table, mid, 'Constitution pressure', OWNER, choices={RID: ['use']})
    engine = reload(tmp_path, mid)
    assert len(spent(engine)) == 1


def test_vessel_already_used_by_guard_adds_no_second_bonus(tmp_path, monkeypatch):
    fixed(monkeypatch)
    combat, table, mid = setup(tmp_path, stage='Perfected', current=1)
    # A declared encounter-held unit pays Guard. This real hostile damage then
    # generates the unit that pays the later save; Vessel already modified Guard.
    use(combat, table, mid, 'Hostile blow', OWNER,
        choices={f.CHOICE + 'foundation_combat': ['use']})
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[RESOURCE] == 1
    assert engine.state.actors[OWNER].turn_flags['foundation_round_vessel'] == engine.state.round_number
    use(combat, table, mid, 'Bodily poison', OWNER, choices={RID: ['use']})
    engine = reload(tmp_path, mid)
    resolved = [e for e in engine.events if e.event_type == 'REACTION_RESOLVED'
                and e.source_definition_id == REJECTION]
    assert resolved[-1].payload['bonus'] == 4
    assert len(spent(engine)) == 1


@pytest.mark.parametrize('natural,expected_bonus,success', [(8, 4, True), (1, 0, False), (20, 0, True)])
def test_death_save_native_turn_start_and_natural_boundaries(tmp_path, monkeypatch, natural, expected_bonus, success):
    fixed(monkeypatch, natural)
    combat, table, mid = setup(tmp_path, stage='Refined', expression=True)
    generate(combat, table, mid)
    use(combat, table, mid, 'Knock down', OWNER,
        choices={f.CHOICE + 'foundation_combat': None})
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].life_state == 'DYING'
    # This is the automatic policy's natural-die boundary: humans retain the
    # printed option to spend even when a natural 1/20 cannot change outcome.
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    # End turns via the table so the ordinary next-slot death-save producer
    # raises the same consent window and commits the adjusted save.
    turn(table, mid, OWNER)
    engine = reload(tmp_path, mid)
    saves = [e for e in engine.events if e.event_type == 'CHECK_ROLLED'
             and e.actor_id == OWNER and e.payload.get('skill') == 'Death Saving Throw']
    assert saves and saves[-1].payload['success'] is success
    assert saves[-1].payload['actor']['natural_result'] == natural
    assert saves[-1].payload['actor']['modifier'] == expected_bonus
    assert len(spent(engine)) == bool(expected_bonus)


def test_automatic_defender_uses_rejection_without_player_prompt(tmp_path, monkeypatch):
    fixed(monkeypatch)
    combat, table, mid = setup(tmp_path)
    generate(combat, table, mid)
    # Use the real controller API after reaching the hostile turn. Automatic
    # participants have no manual end-turn menu for the fixture to advance.
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    prompts = use(combat, table, mid, 'Bodily poison', OWNER, choices={RID: ['use']})
    assert not any(p['context']['reaction_source_id'] == RID for p in prompts)
    assert len(spent(reload(tmp_path, mid))) == 1


def test_player_can_preserve_vessel_by_spending_only_base_rejection(tmp_path, monkeypatch):
    fixed(monkeypatch)
    combat, table, mid = setup(tmp_path, stage='Perfected', expression=True)
    generate(combat, table, mid)
    prompts = use(combat, table, mid, 'Bodily poison', OWNER, choices={RID: ['base']})
    prompt = next(p for p in prompts if p['context']['reaction_source_id'] == RID)
    assert {o['id'] for o in prompt['choice']['options']} == {'use', 'base'}
    engine = reload(tmp_path, mid)
    actor = engine.state.actors[OWNER]
    assert actor.resources[RESOURCE] == 0
    assert actor.turn_flags.get('foundation_round_vessel') != engine.state.round_number
    resolved = [e for e in engine.events if e.event_type == 'REACTION_RESOLVED'
                and e.source_definition_id == REJECTION]
    assert resolved[-1].payload['bonus'] == 4
    assert not any(c.condition_id.endswith('.poisoned') for c in actor.conditions.values())

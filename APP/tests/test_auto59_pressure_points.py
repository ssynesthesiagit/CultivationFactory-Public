"""Pressure Point grants, real recovery actions and actual native save gates."""
import pytest
from combat.ext import healing_interception, figment
from combat import speech
from combat.typed_executor import bears_mark
from tests.auto_worker1_support import LEFT, RIGHT, fight, act, reload, action_sender
from tests.auto_worker1_support import turn, cell_send, prefix_send, settle
P = 'tianxia.talent.pressure_points.'
FOCUS = 'resource:core.martial_focus'

def records(e):
    return [c for c in e.state.actors[RIGHT].conditions.values() if c.condition_id == healing_interception.RECORD and c.data.get('name') == 'Weak Pulse Point']

@pytest.mark.parametrize('kind', ['hp', 'temp_hp'])
@pytest.mark.parametrize('ai', [False, True])
def test_weak_pulse_first_actual_grant_of_either_kind_is_reduced_once(tmp_path, kind, ai):
    effect = {'type': 'healing' if kind == 'hp' else 'temp_hp', 'flat': 10, 'applies_to': 'self'}
    c, t, m = fight(tmp_path, [P + 'weak_pulse_point'], left_score=50, cause_target='SELF', cause=[effect])
    settle(action_sender(c, t, m, 'Unarmed Strike', ai=ai, target_id=RIGHT))
    e = reload(c, m)
    assert len(records(e)) == 1 and records(e)[0].data['reduce'] == 4
    before = e.state.actors[RIGHT].current_hp
    if ai:
        c.set_controller_mode(m, actor_id=LEFT, controller_mode='MANUAL')
    turn(t, m, RIGHT)
    settle(lambda a: act(t, m, 'Cause', a))
    e = reload(c, m)
    assert not records(e)
    if kind == 'hp':
        assert e.state.actors[RIGHT].current_hp == before + 6
    else:
        assert e.state.actors[RIGHT].temporary_hp == 6
    settle(lambda a: act(t, m, 'Cause', a))
    e = reload(c, m)
    if kind == 'hp':
        assert e.state.actors[RIGHT].current_hp == before + 16
    else:
        assert e.state.actors[RIGHT].temporary_hp == 10

@pytest.mark.parametrize('kind', ['hp', 'temp_hp'])
def test_legacy_weak_pulse_rows_keep_hp_only_behavior(tmp_path, kind):

    def legacy(b):
        for row in b['typed_passives']:
            if row.get('feature_id') == P + 'weak_pulse_point':
                row.pop('point_effects', None)
    c, t, m = fight(tmp_path, [P + 'weak_pulse_point'], left_score=50, bundle_edit=legacy, cause_target='SELF', cause=[{'type': 'healing' if kind == 'hp' else 'temp_hp', 'flat': 10, 'applies_to': 'self'}])
    settle(lambda a: act(t, m, 'Unarmed Strike', a, target_id=RIGHT))
    e = reload(c, m)
    before = e.state.actors[RIGHT].current_hp
    assert not records(e)
    turn(t, m, RIGHT)
    settle(lambda a: act(t, m, 'Cause', a))
    e = reload(c, m)
    if kind == 'hp':
        assert e.state.actors[RIGHT].current_hp == before + 6
    else:
        assert e.state.actors[RIGHT].temporary_hp == 10

def test_weak_pulse_unspent_record_expires_at_owner_next_start(tmp_path):
    c, t, m = fight(tmp_path, [P + 'weak_pulse_point'], left_score=50, cause_target='SELF', cause=[{'type': 'temp_hp', 'flat': 10, 'applies_to': 'self'}])
    settle(lambda a: act(t, m, 'Unarmed Strike', a, target_id=RIGHT))
    assert records(reload(c, m))
    turn(t, m, RIGHT)
    turn(t, m, LEFT)
    assert not records(reload(c, m))
    turn(t, m, RIGHT)
    settle(lambda a: act(t, m, 'Cause', a))
    assert reload(c, m).state.actors[RIGHT].temporary_hp == 10

def test_breath_catching_changes_one_real_concentration_save_not_other_con_saves(tmp_path):
    c, t, m = fight(tmp_path, [P + 'breath_catching_point'], left_score=50, right_score=214, right_talents=['tianxia.talent.poison.miasma_form'], cause_target='SELF', cause=[{'type': 'save', 'ability': 'con', 'dc': 'technique_save_dc', 'applies_to': 'self', 'on_fail': [], 'on_success': []}, {'type': 'damage', 'flat': 1, 'damage_types': ['fire'], 'applies_to': 'self'}])
    turn(t, m, RIGHT)
    settle(lambda a: act(t, m, 'Miasma Form', a))
    turn(t, m, LEFT)
    settle(lambda a: act(t, m, 'Unarmed Strike', a, target_id=RIGHT))
    e = reload(c, m)
    assert bears_mark(e.state.actors[RIGHT], LEFT, 'Pressure Point')
    assert any((c.condition_id == 'condition:typed.concentration_mode' for c in e.state.actors[RIGHT].conditions.values()))
    before = len(e.events)
    turn(t, m, RIGHT)
    for _ in range(2):
        settle(lambda a: act(t, m, 'Cause', a))
    e = reload(c, m)
    saves = [v for v in e.events[before:] if v.event_type == 'SAVE_ROLLED']
    assert [v.payload['mode'] for v in saves] == ['NORMAL', 'DISADVANTAGE', 'NORMAL', 'NORMAL']
    assert e.state.actors[RIGHT].concentration is not None

def test_breath_catching_unspent_save_expires_at_owner_next_start(tmp_path):
    c, t, m = fight(tmp_path, [P + 'breath_catching_point'], left_score=50)
    settle(lambda a: act(t, m, 'Unarmed Strike', a, target_id=RIGHT))
    assert any((c.condition_id == 'condition:typed.concentration_mode' for c in reload(c, m).state.actors[RIGHT].conditions.values()))
    turn(t, m, RIGHT)
    turn(t, m, LEFT)
    assert not any((c.condition_id == 'condition:typed.concentration_mode' for c in reload(c, m).state.actors[RIGHT].conditions.values()))

@pytest.mark.parametrize('action', ['Dodge', 'Search'])
def test_patient_hand_actual_action_restores_absent_focus(tmp_path, action):
    search = action == 'Search'
    prepare = [{'type': 'condition', 'condition': 'hidden', 'applies_to': 'target', 'duration': 'until_removed', 'condition_data': {'stealth_total': 1}}] if search else [{'type': 'temp_hp', 'flat': 1, 'applies_to': 'self'}]
    c, t, m = fight(tmp_path, [P + 'patient_hand'], prepare_target='HOSTILE_ENTITY' if search else 'SELF', prepare=prepare, prepare_costs=[(FOCUS, 1)])
    settle(lambda a: act(t, m, 'Prepare', a, target_id=RIGHT if search else None))
    assert reload(c, m).state.actors[LEFT].resources[FOCUS] == 0
    settle(lambda a: act(t, m, action, a))
    e = reload(c, m)
    assert e.state.actors[LEFT].resources[FOCUS] == 1
    assert any((v.event_type == 'RESOURCE_GAINED' and v.source_definition_id == P + 'patient_hand' for v in e.events))
    if search:
        assert any((v.event_type == 'CHECK_ROLLED' for v in e.events))
        assert not any((v.condition_id == 'condition:typed.hidden' for v in e.state.actors[RIGHT].conditions.values()))

def test_patient_hand_actual_study_of_an_enemy_illusion_restores_focus(tmp_path):
    """Any Study declares illusion_study=1 (Illusion's own Study ability is another lane's);
    Patient Hand keys off that flag, so a synthetic Study drives the same hook.  What the Study
    itself rolls is Illusion's to assert, not this hook's."""
    c, t, m = fight(tmp_path, [P + 'patient_hand'], right_talents=[figment.CREATE], right_spheres=[figment.SPHERE],
                    prepare_target='SELF', prepare=[{'type': 'temp_hp', 'flat': 1, 'applies_to': 'self'}], prepare_costs=[(FOCUS, 1)],
                    extra_actions=(('Study an illusion', {'illusion_study': 1, 'economy': 'ACTION'}),))
    settle(lambda a: act(t, m, 'Prepare', a))
    turn(t, m, RIGHT)
    settle(prefix_send(t, m, 'Create Figment', (4, 8)))
    turn(t, m, LEFT)
    settle(lambda a: act(t, m, 'Study an illusion', a))
    e = reload(c, m)
    assert e.state.actors[LEFT].resources[FOCUS] == 1
    assert any((v.event_type == 'RESOURCE_GAINED' and v.source_definition_id == P + 'patient_hand' for v in e.events))

@pytest.mark.parametrize('owned,visible', [(False, True), (True, False)])
def test_patient_hand_requires_owned_row_and_perceived_hostile(tmp_path, owned, visible):
    c, t, m = fight(tmp_path, [P + 'patient_hand'] if owned else [], prepare_target='SELF', prepare=[{'type': 'condition', 'condition': 'blinded', 'applies_to': 'self', 'duration': 'until_removed'}] if not visible else [{'type': 'temp_hp', 'flat': 1, 'applies_to': 'self'}], prepare_costs=[(FOCUS, 1)])
    settle(lambda a: act(t, m, 'Prepare', a))
    settle(lambda a: act(t, m, 'Dodge', a))
    assert reload(c, m).state.actors[LEFT].resources[FOCUS] == 0

@pytest.mark.parametrize('failed', [True, False])
def test_speech_knot_point_binds_and_checks_actual_voiced_activation_before_payment(tmp_path, failed):
    kiai = 'tianxia.subpath.qi.kiai_master.feature.kiai'
    c, t, m = fight(tmp_path, [P + 'speech_knot_point'], left_score=50, right_score=14 if failed else 214, right_talents=[kiai])
    settle(lambda a: act(t, m, 'Unarmed Strike', a, target_id=RIGHT))
    e = reload(c, m)
    assert any((v.condition_id == speech.SPEECH_KNOT for v in e.state.actors[RIGHT].conditions.values()))
    turn(t, m, RIGHT)
    settle(lambda a: act(t, m, 'Kiai', a, target_id=LEFT))
    e = reload(c, m)
    assert not any((v.condition_id == speech.SPEECH_KNOT for v in e.state.actors[RIGHT].conditions.values()))
    assert e.state.actors[RIGHT].resources['resource:core.qi'] == 100 - int(not failed)
    assert e.state.actors[RIGHT].bonus_action_available == failed
    assert any((v.event_type == 'SAVE_ROLLED' and v.actor_id == RIGHT and (v.payload['success'] == (not failed)) for v in e.events))

@pytest.mark.parametrize('failed', [True, False])
def test_soft_paralysis_actual_seal_save_and_owner_start_expiry(tmp_path, failed):
    c, t, m = fight(tmp_path, [P + 'soft_paralysis_tap'], left_score=50, right_score=14 if failed else 214, prepare=[{'type': 'mark', 'mark': 'Pressure Point', 'applies_to': 'target', 'duration': {'kind': 'until_removed'}}])
    settle(lambda a: act(t, m, 'Prepare', a, target_id=RIGHT))
    settle(lambda a: act(t, m, 'Unarmed Strike', a, target_id=RIGHT))
    e = reload(c, m)
    assert e._effective_speed(e.state.actors[RIGHT]) == 0
    assert any((v.condition_id == 'condition:typed.restrained' for v in e.state.actors[RIGHT].conditions.values())) == failed
    assert [v for v in e.events if v.event_type == 'SAVE_ROLLED'][-1].payload['success'] == (not failed)
    turn(t, m, RIGHT)
    turn(t, m, LEFT)
    e = reload(c, m)
    assert e._effective_speed(e.state.actors[RIGHT]) == 30

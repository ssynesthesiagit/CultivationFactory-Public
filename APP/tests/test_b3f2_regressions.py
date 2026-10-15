"""General integration contracts behind B3F2's sphere fixes."""
import copy

import pytest

from combat.factory_compiler import _attach, _replacement_summary
from combat.forged import payload


@pytest.mark.parametrize('talent,condition,failed_condition', [
    ('TAL_VOID_VOID_FIELD', 'no_temp_hp', 'hollowed'),
    ('tianxia.talent.radiance.world_of_revealed_morning', 'reaction_denied', 'blinded'),
])
@pytest.mark.parametrize('success', [False, True])
@pytest.mark.parametrize('form', ['cone', 'projection'])
def test_carried_zone_save_outcomes_commit_and_reload(tmp_path, talent, condition, failed_condition, success, form):
    from tests.auto_worker1_support import LEFT, RIGHT, act, fight, reload, cell_send, resolve
    from tests.h1_support import sheet
    from tests.test_mmx107_forged_button_text import _technique
    from combat.factory_compiler import compile_character

    label = 'Carried field'
    def edit(bundle):
        if bundle['actor_template']['entity_id'] == LEFT:
            doc = sheet([talent], cl=15, dc=100)
            doc['forged_techniques'] = [_technique(label, form, talent=talent)]
            compiled = compile_character(doc, actor_id=LEFT)
            rows = [a for a in compiled['action_catalog'] if a['display_name'] == label]
            # Make hit delivery deterministic without changing its save outcome.
            for row in rows:
                row['parameters']['typed']['numbers']['attack_bonus'] = 100
            bundle['action_catalog'].extend(rows)
            bundle['actor_template']['action_ids'].extend(a['source_definition_id'] for a in rows)
    combat, table, mid = fight(tmp_path, [talent], right_score=214 if success else 14,
                              bundle_edit=edit,
                              prepare=[{'type': 'temp_hp', 'applies_to': 'target', 'flat': 8}],
                              cause_target='SELF',
                              cause=[{'type': 'temp_hp', 'applies_to': 'self', 'flat': 8}])
    if form == 'cone':
        assert resolve(cell_send(table, mid, label, (4, 6)))[0]['status'] == 'COMMITTED'
    else:
        assert resolve(lambda answers: act(table, mid, label, answers))[0]['status'] == 'COMMITTED'
    engine = reload(combat, mid)
    target = engine.state.actors[RIGHT]
    conditions = list(target.conditions.values())
    # Hollowed itself also denies Temporary HP on failure; the success branch
    # must deny it independently, without applying Hollowed.
    assert any(c.condition_id.endswith('.' + condition) for c in conditions) is (success or talent == 'TAL_VOID_VOID_FIELD')
    assert any(c.condition_id.endswith('.' + failed_condition) for c in conditions) is (not success)
    damage = [e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED' and RIGHT in e.target_ids]
    roll = [e for e in engine.events if e.event_type == 'DAMAGE_ROLLED'][-1]
    expected = roll.payload['total']//2 if success and form == 'cone' else roll.payload['total']
    assert len(damage) == 1 and damage[0].payload['hp_damage'] == expected
    if success:
        held = next(c for c in conditions if c.condition_id.endswith('.' + condition))
        from combat.ext.effect_durations import token
        assert held.expires_on == token('start', RIGHT, target.turns_started + 1)
        if condition == 'reaction_denied':
            from combat.typed_reactions import can_use_reaction
            assert not can_use_reaction(engine, target, engine.state.actors[LEFT], {})
        else:
            assert act(table, mid, 'Prepare')['status'] == 'COMMITTED'
            assert reload(combat, mid).state.actors[RIGHT].temporary_hp == 0
        from tests.void_support import turn
        turn(table, mid, RIGHT)
        engine = reload(combat, mid)
        target = engine.state.actors[RIGHT]
        assert not any(c.condition_id.endswith('.' + condition) for c in target.conditions.values())
        if condition == 'reaction_denied':
            assert can_use_reaction(engine, target, engine.state.actors[LEFT], {})
        assert act(table, mid, 'Cause')['status'] == 'COMMITTED'
        assert reload(combat, mid).state.actors[RIGHT].temporary_hp == 8


@pytest.mark.parametrize('form', ['ward', 'movement', 'counter'])
def test_zone_success_outcome_is_rejected_when_delivery_cannot_represent_it(form):
    from combat.forged import mechanic_for
    from tests.test_mmx107_forged_button_text import _technique
    source = {'effects': [{'type': 'zone', 'triggers': [{'on': ['enter'], 'effects': [
        {'type': 'save', 'ability': 'con', 'on_fail': [{'type': 'damage', 'flat': 7}],
         'on_success': [{'type': 'reaction_denied', 'expires_on': 'START_OF_TARGET_NEXT_TURN'}]}]}]}]}
    assert mechanic_for(_technique(talent='primary', form=form), {'primary': source}) is None


def test_zone_success_outcome_is_not_silently_dropped_from_a_secondary():
    from combat.forged import mechanic_for
    from tests.test_mmx107_forged_button_text import _technique
    source = {'effects': [{'type': 'zone', 'triggers': [{'on': ['enter'], 'effects': [
        {'type': 'save', 'ability': 'con', 'on_fail': [{'type': 'damage', 'flat': 7}],
         'on_success': [{'type': 'deny_temp_hp', 'expires_on': 'START_OF_TARGET_NEXT_TURN'}]}]}]}]}
    technique = _technique(talent='primary')
    technique['secondary_sphere_effects'] = [{'talent_id': 'secondary'}]
    assert mechanic_for(technique, {'primary': {'effects': [{'type': 'damage', 'flat': 7}]},
                                   'secondary': source}) is None


@pytest.mark.parametrize('damage_type', ['damage', 'extra_damage'])
def test_independent_zone_success_damage_is_rejected_instead_of_doubled(damage_type):
    from combat.forged import mechanic_for
    from tests.test_mmx107_forged_button_text import _technique
    source = {'effects': [{'type': 'zone', 'triggers': [{'on': ['enter'], 'effects': [
        {'type': 'save', 'ability': 'con', 'on_fail': [{'type': 'damage', 'flat': 7}],
         'on_success': [{'type': damage_type, 'flat': 3}]}]}]}]}
    assert mechanic_for(_technique(talent='primary'), {'primary': source}) is None


@pytest.mark.parametrize('talent', [
    'tianxia.talent.radiance.consecrated_boundary',
    'tianxia.talent.pressure_points.meridian_stillness_field',
])
@pytest.mark.parametrize('eligible', [False, True])
def test_restricted_zone_forge_is_rejected_at_table_and_after_reload(tmp_path, talent, eligible):
    from tests.auto_worker1_support import LEFT, RIGHT, act, fight, reload
    from tests.h1_support import sheet
    from tests.test_mmx107_forged_button_text import _technique
    from combat.factory_compiler import compile_character

    label = 'Restricted field strike'
    def edit(bundle):
        if bundle['actor_template']['entity_id'] == LEFT:
            doc = sheet([talent], cl=15)
            doc['forged_techniques'] = [_technique(label, 'projection', talent=talent)]
            compiled = compile_character(doc, actor_id=LEFT)
            rows = [a for a in compiled['action_catalog'] if a['display_name'] == label]
            bundle['action_catalog'].extend(rows)
            bundle['actor_template']['action_ids'].extend(a['source_definition_id'] for a in rows)
        else:
            bundle['actor_template']['creature_types'] = ['Unclean'] if eligible else ['Humanoid']
    prepare = ([{'type':'mark', 'mark':'Pressure Point', 'applies_to':'target',
                 'duration':{'kind':'minutes', 'amount':1}}] if eligible and 'pressure_points' in talent else [])
    combat, table, mid = fight(tmp_path, [talent], prepare=prepare, bundle_edit=edit)
    if prepare:
        assert act(table, mid, 'Prepare')['status'] == 'COMMITTED'
    before = reload(combat, mid).state.actors[RIGHT].model_dump(mode='json')
    if 'radiance' in talent:
        assert ('Unclean' in before['creature_types']) is eligible
    else:
        from combat.typed_executor import mark_condition_id
        assert any(c['condition_id'] == mark_condition_id('Pressure Point', LEFT)
                   for c in before['conditions'].values()) is eligible
    for _ in range(2):
        assert not any(g['label'] == label for g in table.state(mid)['menu']['actions'])
        assert not any(a.display_name == label for a in reload(combat, mid).action_catalog.values())
        assert act(table, mid, 'system:combat.hold_position')['status'] == 'COMMITTED'
        assert reload(combat, mid).state.actors[RIGHT].model_dump(mode='json') == before


@pytest.mark.parametrize('existing_seal', [False, True])
def test_zone_dependent_forge_is_rejected_and_preserves_seals_after_reload(tmp_path, existing_seal):
    from tests.test_mmx107_forged_button_text import _fight, _technique, LEFT, RIGHT
    from tests.auto_worker1_support import cell_send, resolve, reload
    from tests.test_lock2_persistence import act
    talent = 'SOURCE_BASE_SOURCE_SEAL'
    label = 'Carried Fetter'
    combat, table, mid = _fight(tmp_path, talents=[talent], forged=[
        _technique(label, 'projection', talent=talent)],
        starts={'team1': [[4, 4], [4, 7]], 'team2': [[5, 4]]})
    if existing_seal:
        assert resolve(cell_send(table, mid, 'Source Seal', (5, 4)))[0]['status'] == 'COMMITTED'
    engine = reload(combat, mid)
    seals = {k: z.model_dump(mode='json') for k, z in engine.state.zones.items()}
    assert bool(seals) is existing_seal
    target = engine.state.actors[RIGHT].model_dump(mode='json')
    resources = dict(engine.state.actors[LEFT].resources)
    for _ in range(2):
        assert not any(g['label'] == label for g in table.state(mid)['menu']['actions'])
        assert not any(a.display_name == label for a in reload(combat, mid).action_catalog.values())
        assert act(table, mid, 'system:combat.hold_position')['status'] == 'COMMITTED'
        loaded = reload(combat, mid)
        assert {k: z.model_dump(mode='json') for k, z in loaded.state.zones.items()} == seals
        assert loaded.state.actors[RIGHT].model_dump(mode='json') == target
        assert loaded.state.actors[LEFT].resources == resources


@pytest.mark.parametrize('wrapper', ['delivery_once', 'conditional_delivery'])
def test_replacing_a_nested_save_preserves_damage_and_reports_the_trade(wrapper):
    damage = {'type':'damage', 'flat':7, 'damage_types':['force']}
    mark = {'type':'mark', 'mark':'Test mark'}
    save = {'type':'save', 'ability':'con', 'on_fail':[mark], 'on_success':[]}
    base = [{'type':'attack', 'on_hit':[damage, {'type':wrapper, 'effects':[save]}]}]
    before = copy.deepcopy(base)
    changed = _attach(base, [copy.deepcopy(mark)], 'replace_save')
    assert base == before
    assert changed[0]['on_hit'] == [damage, {'type':wrapper, 'effects':[mark]}]
    summary = _replacement_summary(base, changed, 'replace_save')
    assert summary['reliable'] == [mark] and save in summary['removed']


def test_forge_carries_one_repeated_zone_payload_without_mutating_the_source():
    save = {'type':'save', 'ability':'con', 'on_fail':[{'type':'damage', 'flat':7}],
            'on_success':[{'type':'half_damage'}]}
    source = {'effects':[{'type':'zone', 'triggers':[
        {'event':'entry', 'effects':[save]}, {'event':'turn_start', 'effects':[save]}]}]}
    before = copy.deepcopy(source)
    assert payload(source) == {'effects':save['on_fail'], 'ability':'CON', 'half':True, 'own':[]}
    assert source == before
    source['effects'][0]['triggers'][1]['effects'] = [{'type':'condition','condition':'prone'}]
    assert payload(source)['effects'] == []  # Distinct effects need an explicit choice.


@pytest.mark.parametrize('guard', ['requires_kind', 'requires_mark', 'future_eligibility'])
def test_forge_rejects_unknown_or_unrepresented_trigger_guards(guard):
    from combat.forged import mechanic_for
    from tests.test_mmx107_forged_button_text import _technique
    source = {'effects': [{'type': 'zone', 'triggers': [{
        'on': ['enter'], guard: ['restricted'],
        'effects': [{'type': 'damage', 'flat': 7}]}]}]}
    assert mechanic_for(_technique(talent='primary'), {'primary': source}) is None


def test_forge_rejects_unknown_nested_zone_handlers_and_unsafe_secondaries():
    from combat.forged import mechanic_for
    from tests.test_mmx107_forged_button_text import _technique
    source = {'effects': [{'type': 'zone', 'triggers': [{
        'on': ['enter'], 'effects': [{'type': 'save', 'ability': 'con',
            'on_fail': [{'type': 'future_zone_handler'}], 'on_success': []}]}]}]}
    technique = _technique(talent='primary')
    assert mechanic_for(technique, {'primary': source}) is None
    technique['secondary_sphere_effects'] = [{'talent_id': 'secondary'}]
    assert mechanic_for(technique, {'primary': {'effects': [{'type': 'damage', 'flat': 7}]},
                                     'secondary': source}) is None


def test_persistent_meld_commits_and_reloads_with_both_concentration_representations_detached(tmp_path):
    from combat import senses
    from tests.auto_worker1_support import LEFT, act, fight, reload
    talents = ['TAL_DARK_MELD', 'TAL_DARK_DARKVISION', 'TAL_DARK_HIDE_IN_DARKNESS']
    combat, table, mid = fight(tmp_path, talents)
    assert act(table, mid, 'Meld: Hide in Darkness')['status'] == 'COMMITTED'
    engine = reload(combat, mid)
    held = next(c for c in engine.state.actors[LEFT].conditions.values() if c.condition_id == senses.MELD)
    assert held.expires_on == 'CONCENTRATION_END' and held.data['concentration'] is True
    label = next(g['label'] for g in table.state(mid)['menu']['actions'] if 'keep Meld without Concentration' in g['label'])
    assert act(table, mid, label)['status'] == 'COMMITTED'
    engine = reload(combat, mid); actor = engine.state.actors[LEFT]
    kept = next(c for c in actor.conditions.values() if c.condition_id == senses.MELD)
    assert actor.concentration is None and kept.data['concentration'] is False
    assert kept.expires_on != 'CONCENTRATION_END'
    assert 'TAL_DARK_HIDE_IN_DARKNESS' in senses.melds_of(engine, actor)

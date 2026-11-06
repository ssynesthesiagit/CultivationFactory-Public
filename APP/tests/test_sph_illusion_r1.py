"""Illusion review regressions through committed, reloaded table actions."""
import pytest

from combat.ext import figment, placed, run
from tests.auto_worker1_support import LEFT, RIGHT, fight, act, reload, turn, action_sender
from tests.test_auto41_illusion import cell_action, answer


@pytest.mark.parametrize('ai', [False, True])
@pytest.mark.parametrize('disadvantage', [False, True])
def test_study_does_not_use_grapple_only_advantage(tmp_path, ai, disadvantage):
    effects = [{'type': 'condition', 'condition': 'stance.rooted_stance',
                'applies_to': 'self', 'duration': 'until_removed'}]
    if disadvantage:
        effects.append({'type': 'ongoing', 'condition': 'test_investigation',
                        'applies_to': 'self', 'expires_on': 'UNTIL_REMOVED',
                        'rule': {'check_mode': {'Investigation': 'DISADVANTAGE'}}})
    combat, table, mid = fight(tmp_path, [figment.MINOR], spheres=[figment.SPHERE],
                              cause=effects, cause_target='SELF')
    result = cell_action(table, mid, 'Minor Illusion', (4, 6))
    assert cell_action(table, mid, 'Minor Illusion', (4, 6), [answer(result, ['image'])])['status'] == 'COMMITTED'
    turn(table, mid, RIGHT)
    assert act(table, mid, 'Cause')['status'] == 'COMMITTED'
    engine = reload(combat, mid)
    assert 'ADVANTAGE' in run('escape_mode', engine, engine.state.actors[RIGHT], [])
    zone, = placed.of(engine, 'figment')
    send = action_sender(combat, table, mid, 'Study an illusion', ai=ai)
    result = send([])
    if not ai:
        assert result['status'] == 'REACTION_REQUIRED'
        result = send([answer(result, [zone.zone_id])])
    assert result['status'] == 'COMMITTED'
    check, = [e for e in reload(combat, mid).events if e.event_type == 'CHECK_ROLLED']
    assert check.payload['actor']['mode'] == ('DISADVANTAGE' if disadvantage else 'NORMAL')


@pytest.mark.parametrize('recorded_skill', [None, 2])
def test_native_catalogue_study_never_uses_int_save_proficiency(tmp_path, monkeypatch, recorded_skill):
    # Model a persisted native/older catalogue: no compiled Study action or
    # ordinary ability modifiers, and an INT saving throw that includes +15.
    from tests import auto_worker1_support as support
    original = support.compile_character
    def compile_fixture(*args, **kwargs):
        bundle = original(*args, **kwargs)
        if kwargs['actor_id'] != RIGHT:
            return bundle
        template = bundle['actor_template']
        template['saving_throws']['INT'] = 17
        template['skills'] = {} if recorded_skill is None else {'Investigation': recorded_skill}
        bundle['skills'] = dict(template['skills'])
        removed = {a['source_definition_id'] for a in bundle['action_catalog']
                   if a.get('parameters', {}).get('illusion_study')}
        template['action_ids'] = [a for a in template['action_ids'] if a not in removed]
        bundle['action_catalog'] = [a for a in bundle['action_catalog'] if a['source_definition_id'] not in removed]
        for a in bundle['action_catalog']:
            a.get('parameters', {}).get('typed', {}).get('numbers', {}).pop('ability_mods', None)
        return bundle
    monkeypatch.setattr(support, 'compile_character', compile_fixture)
    combat, table, mid = fight(tmp_path, [figment.MINOR], spheres=[figment.SPHERE])
    result = cell_action(table, mid, 'Minor Illusion', (4, 6))
    assert cell_action(table, mid, 'Minor Illusion', (4, 6), [answer(result, ['image'])])['status'] == 'COMMITTED'
    turn(table, mid, RIGHT)
    engine = reload(combat, mid)
    assert engine.state.actors[RIGHT].saving_throws['INT'] == 17
    assert not any(engine.action_catalog[a].parameters.get('illusion_study')
                   for a in engine.state.actors[RIGHT].action_ids)
    groups = [g for g in table.state(mid)['menu']['actions'] if g['label'] == 'Study an illusion']
    if recorded_skill is None:
        assert not groups
        return
    assert groups[0]['source_definition_id'] == figment.STUDY
    zone, = placed.of(engine, 'figment')
    result = act(table, mid, 'Study an illusion')
    assert act(table, mid, 'Study an illusion', [answer(result, [zone.zone_id])])['status'] == 'COMMITTED'
    check, = [e for e in reload(combat, mid).events if e.event_type == 'CHECK_ROLLED']
    assert check.payload['actor']['modifier'] == 2


@pytest.mark.parametrize('ai', [False, True])
@pytest.mark.parametrize('stimulus', ['blinded', 'caster_concealed'])
def test_phantom_sting_perceives_hit_space_not_caster(tmp_path, ai, stimulus):
    effects = ([{'type': 'condition', 'condition': 'blinded', 'applies_to': 'target',
                 'duration': 'until_removed'}] if stimulus == 'blinded' else
               [{'type': 'condition', 'condition': 'invisible', 'applies_to': 'self',
                 'duration': 'until_removed'}])
    combat, table, mid = fight(tmp_path, ['TAL_ILLUSION_PHANTOM_STING'], spheres=[figment.SPHERE],
                              prepare=effects, prepare_target='HOSTILE_ENTITY' if stimulus == 'blinded' else 'SELF',
                              left_attack_bonus=100, positions={LEFT: {'x': 3, 'y': 6}, RIGHT: {'x': 6, 'y': 6}})
    assert act(table, mid, 'Prepare', target_id=RIGHT if stimulus == 'blinded' else LEFT)['status'] == 'COMMITTED'
    engine = reload(combat, mid)
    from combat.senses import perceives_cell
    perceived = stimulus != 'blinded'
    assert perceives_cell(engine, engine.state.actors[RIGHT], engine.state.actors[RIGHT].position) == perceived
    if perceived:
        from combat.senses import perceives
        assert not perceives(engine, engine.state.actors[RIGHT], engine.state.actors[LEFT])
    send = action_sender(combat, table, mid, 'Phantom Sting', ai=ai, target_id=RIGHT)
    result = send([])
    if perceived and not ai:
        assert result['status'] == 'REACTION_REQUIRED'
        assert 'Phantom Sting' in str(result['reaction']) and 'Visitor' in str(result['reaction'])
        result = send([answer(result, ['PREMISE'])])
    assert result['status'] == 'COMMITTED', result
    engine = reload(combat, mid)
    assert engine.state.actors[RIGHT].current_hp < 1000
    assert bool([e for e in engine.events if e.event_type == 'SAVE_ROLLED']) == perceived

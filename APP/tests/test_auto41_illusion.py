"""Owned minor images, explicit exemptions and recognition through real tables."""
import pytest
from combat.ext import figment, placed
from tests.auto_worker1_support import LEFT, RIGHT, fight, act, reload, turn, action_sender


def cell_action(table, mid, label, xy, answers=()):
    state = table.state(mid)
    menu = state['menu']
    options = next(g['options'] for g in menu['actions'] if g['label'] == label)
    native = next((o for o in options if o.get('destination') == {'x': xy[0], 'y': xy[1]}), None)
    if native is not None:
        return table.act(mid, native['candidate_id'], menu['decision_id'], menu['state_version'], state['last_sequence'], list(answers))
    root = next(o for o in options if o.get('destination') is None)
    from combat.placement_menu import CHOICE
    result = table.act(mid, root['candidate_id'], menu['decision_id'], menu['state_version'], state['last_sequence'], [])
    assert result['status'] == 'REACTION_REQUIRED'
    if result['reaction']['context']['reaction_source_id'] != CHOICE:
        # A prior call already bound the square; continue its later detail
        # question instead of demanding that the server ask placement again.
        prefix = []
        for prior in (state.get('pending_action') or {}).get('reactions') or []:
            if prior.get('reaction_source_id') != CHOICE:
                break
            prefix.append(prior)
        return (table.act(mid, root['candidate_id'], menu['decision_id'], menu['state_version'], state['last_sequence'], [*prefix, *answers])
                if answers else result)
    placement = {**result['reaction']['context'], 'selection': 'USE', 'option_ids': [f'cell:{xy[0]},{xy[1]},0']}
    return table.act(mid, root['candidate_id'], menu['decision_id'], menu['state_version'], state['last_sequence'], [placement, *answers])


def answer(result, ids):
    return {**result['reaction']['context'], 'selection': 'USE' if ids else 'DECLINE', 'option_ids': ids}


@pytest.mark.parametrize('detail', list(figment.MINOR_DETAILS))
def test_minor_image_choices_move_and_no_concentration(tmp_path, detail):
    combat, table, mid = fight(tmp_path, [figment.MINOR], spheres=[figment.SPHERE])
    send = lambda answers: cell_action(table, mid, 'Minor Illusion', (3, 7), answers)
    result = send([])
    assert result['status'] == 'REACTION_REQUIRED'
    assert 'Minor Illusion' in str(result['reaction'])
    assert send([answer(result, [detail])])['status'] == 'COMMITTED'
    engine = reload(combat, mid)
    zone, = placed.of(engine, 'figment')
    assert placed.data(zone)['detail'] == detail
    assert placed.data(zone)['minor'] == 1 and len(zone.affected_cells) == 1
    assert not zone.concentration_link and zone.duration_rounds == 100
    assert engine.state.actors[LEFT].concentration is None
    assert engine.state.actors[LEFT].resources['resource:core.qi'] == 100
    options = next(g['options'] for g in table.state(mid)['menu']['actions'] if g['label'] == 'Move Minor Illusion (up to 5 feet)')
    assert not any(o.get('destination') == {'x': 3, 'y': 9} for o in options)
    assert cell_action(table, mid, 'Move Minor Illusion (up to 5 feet)', (3, 8))['status'] == 'COMMITTED'
    engine = reload(combat, mid)
    zone, = placed.of(engine, 'figment')
    assert (zone.center.x, zone.center.y) == (3, 8)
    assert not engine.state.actors[LEFT].bonus_action_available
    assert engine._effective_speed(engine.state.actors[RIGHT]) == 30
    assert not zone.trigger_profile['triggers']


def test_unowned_minor_and_study_are_inert(tmp_path):
    combat, table, mid = fight(tmp_path)
    labels = [g['label'] for g in table.state(mid)['menu']['actions']]
    assert 'Minor Illusion' not in labels and 'Study an illusion' not in labels
    reload(combat, mid)


@pytest.mark.parametrize('ai', [False, True])
def test_successful_study_is_local_and_phantasm_saves_have_advantage(tmp_path, ai):
    combat, table, mid = fight(tmp_path, [figment.POTENT], spheres=[figment.SPHERE], left_save_dc=1)
    assert act(table, mid, 'Figment: Potent Phantasm, Deafened (1 CP)')['status'] == 'COMMITTED'
    assert cell_action(table, mid, 'Create Figment', (4, 6))['status'] == 'COMMITTED'
    turn(table, mid, RIGHT)
    engine = reload(combat, mid)
    zone, = placed.of(engine, 'figment')
    send = action_sender(combat, table, mid, 'Study an illusion', ai=ai)
    result = send([])
    if not ai:
        assert result['status'] == 'REACTION_REQUIRED'
        result = send([answer(result, [zone.zone_id])])
    assert result['status'] == 'COMMITTED', result
    engine = reload(combat, mid)
    zone, = placed.of(engine, 'figment')
    assert placed.data(zone)['recognized'] == [RIGHT]
    assert placed.data(zone)['studied'] == [RIGHT]
    assert not engine.state.actors[RIGHT].action_available
    if ai:
        combat.set_controller_mode(mid, actor_id=RIGHT, controller_mode='MANUAL')
    turn(table, mid, LEFT)
    assert cell_action(table, mid, 'Keep a figment without Concentration (2 CP)', (4, 6))['status'] == 'COMMITTED'
    assert cell_action(table, mid, 'Create Figment', (9, 6))['status'] == 'COMMITTED'
    engine = reload(combat, mid)
    assert placed.data(placed.of(engine, 'figment')[1])['recognized'] == []
    turn(table, mid, RIGHT)
    engine = reload(combat, mid)
    saves = [e for e in engine.events if e.event_type == 'SAVE_ROLLED' and e.actor_id == RIGHT]
    assert saves[-1].payload['mode'] == 'ADVANTAGE'


@pytest.mark.parametrize('mode', ['recognize', 'immune'])
def test_selective_creation_can_choose_hostile_with_separate_modes(tmp_path, mode):
    combat, table, mid = fight(tmp_path, [figment.SELECTIVE, figment.POTENT], spheres=[figment.SPHERE])
    assert act(table, mid, 'Figment: Selective Premise (choose creatures when created)')['status'] == 'COMMITTED'
    assert act(table, mid, 'Figment: Potent Phantasm, Deafened (1 CP)')['status'] == 'COMMITTED'
    send = lambda answers: cell_action(table, mid, 'Create Figment', (4, 6), answers)
    result = send([])
    assert result['status'] == 'REACTION_REQUIRED'
    answers = [answer(result, [RIGHT])]
    result = send(answers)
    assert result['status'] == 'REACTION_REQUIRED'
    answers.append(answer(result, [mode]))
    assert send(answers)['status'] == 'COMMITTED'
    engine = reload(combat, mid)
    zone, = placed.of(engine, 'figment')
    assert placed.data(zone)['recognized'] == ([RIGHT] if mode == 'recognize' else [])
    assert placed.data(zone)['immune'] == ([RIGHT] if mode == 'immune' else [])
    turn(table, mid, RIGHT)
    engine = reload(combat, mid)
    assert any(c.condition_id == 'condition:typed.deafened' for c in engine.state.actors[RIGHT].conditions.values()) == (mode == 'recognize')
    assert engine.state.actors[LEFT].resources['resource:core.qi'] == 99


def test_failed_study_does_not_recognize(tmp_path):
    combat, table, mid = fight(tmp_path, [figment.MINOR], spheres=[figment.SPHERE])
    send = lambda answers: cell_action(table, mid, 'Minor Illusion', (4, 6), answers)
    result = send([])
    assert send([answer(result, ['sound'])])['status'] == 'COMMITTED'
    turn(table, mid, RIGHT)
    zone, = placed.of(reload(combat, mid), 'figment')
    result = act(table, mid, 'Study an illusion')
    assert act(table, mid, 'Study an illusion', [answer(result, [zone.zone_id])])['status'] == 'COMMITTED'
    zone, = placed.of(reload(combat, mid), 'figment')
    assert placed.data(zone)['recognized'] == [] and placed.data(zone)['studied'] == []
    assert not reload(combat, mid).state.actors[RIGHT].action_available


@pytest.mark.parametrize('ai,accept', [(False, False), (False, True), (True, True)])
def test_phantom_sting_optional_hit_premise(tmp_path, ai, accept):
    from combat.typed_executor import bears_mark
    combat, table, mid = fight(tmp_path, ['TAL_ILLUSION_PHANTOM_STING'], spheres=[figment.SPHERE], left_attack_bonus=100)
    send = action_sender(combat, table, mid, 'Phantom Sting', ai=ai, target_id=RIGHT)
    result = send([])
    if not ai:
        assert result['status'] == 'REACTION_REQUIRED', result
        assert 'Visitor' in str(result['reaction'])
        result = send([answer(result, ['PREMISE'] if accept else [])])
    assert result['status'] == 'COMMITTED', result
    engine = reload(combat, mid)
    assert engine.state.actors[RIGHT].current_hp < 1000
    assert bears_mark(engine.state.actors[RIGHT], LEFT, 'False Premise') == accept
    assert bool([e for e in engine.events if e.event_type == 'SAVE_ROLLED']) == accept


def test_minor_detail_change_and_sovereign_bonus_creation(tmp_path):
    sovereign = 'tianxia.talent.illusion.sovereign_illusion_incarnation'
    combat, table, mid = fight(tmp_path, [figment.MINOR, sovereign], spheres=[figment.SPHERE])
    assert act(table, mid, 'Sovereign Illusion Incarnation')['status'] == 'COMMITTED'
    turn(table, mid, RIGHT)
    turn(table, mid, LEFT)
    send = lambda answers: cell_action(table, mid, 'Minor Illusion (Bonus Action)', (4, 6), answers)
    result = send([])
    assert send([answer(result, ['image'])])['status'] == 'COMMITTED'
    engine = reload(combat, mid)
    assert engine.state.actors[LEFT].action_available and not engine.state.actors[LEFT].bonus_action_available
    turn(table, mid, RIGHT)
    turn(table, mid, LEFT)
    send = lambda answers: cell_action(table, mid, 'Change Minor Illusion detail', (4, 6), answers)
    result = send([])
    assert send([answer(result, ['sound'])])['status'] == 'COMMITTED'
    zone, = placed.of(reload(combat, mid), 'figment')
    assert placed.data(zone)['detail'] == 'sound'
    assert 'brief repeating sound' in zone.trigger_profile['name']


def test_minor_selective_decline_and_ai_placement_blocker(tmp_path):
    combat, table, mid = fight(tmp_path, [figment.MINOR, figment.SELECTIVE], spheres=[figment.SPHERE])
    assert act(table, mid, 'Figment: Selective Premise (choose creatures when created)')['status'] == 'COMMITTED'
    send = lambda answers: cell_action(table, mid, 'Minor Illusion', (4, 6), answers)
    result = send([])
    answers = [answer(result, ['sound'])]
    result = send(answers)
    assert result['status'] == 'REACTION_REQUIRED'
    answers.append(answer(result, []))
    assert send(answers)['status'] == 'COMMITTED'
    zone, = placed.of(reload(combat, mid), 'figment')
    assert not placed.data(zone)['recognized'] and not placed.data(zone)['immune']
    turn(table, mid, RIGHT)
    turn(table, mid, LEFT)
    # The locked AI context omits all any-cell empty-area actions. Preserve and
    # test that boundary; the report names the missing general placement seam.
    from combat.gate4_adapters import ManualControllerAdapter
    real = combat.controller
    class Controller:
        def choose_primary_action(self, context):
            assert not any(c.source_definition_id.endswith('.figment.minor.create') for c in context.legal_candidates)
            candidate = next(c for c in context.legal_candidates if c.kind == 'END_TURN')
            return ManualControllerAdapter(lambda _: (candidate.candidate_id, ())).choose_primary_action(context)
        def __getattr__(self, name):
            return getattr(real, name)
    combat.controller = Controller()
    combat.set_controller_mode(mid, actor_id=LEFT, controller_mode='LOCAL_AUTO')
    assert table.auto_step(mid, table.state(mid)['last_sequence'], [])['status'] == 'COMMITTED'
    zones = placed.of(reload(combat, mid), 'figment')
    assert len(zones) == 1 and placed.data(zones[0])['detail'] == 'sound'


def test_blinded_viewer_cannot_study_an_image_by_sight(tmp_path):
    combat, table, mid = fight(tmp_path, [figment.MINOR], spheres=[figment.SPHERE],
        cause=[{'type': 'condition', 'condition': 'blinded', 'applies_to': 'self', 'duration': 'until_removed'}],
        cause_target='SELF')
    send = lambda answers: cell_action(table, mid, 'Minor Illusion', (4, 6), answers)
    result = send([])
    assert send([answer(result, ['image'])])['status'] == 'COMMITTED'
    turn(table, mid, RIGHT)
    assert any(g['label'] == 'Study an illusion' for g in table.state(mid)['menu']['actions'])
    assert act(table, mid, 'Cause')['status'] == 'COMMITTED'
    assert not any(g['label'] == 'Study an illusion' for g in table.state(mid)['menu']['actions'])
    reload(combat, mid)

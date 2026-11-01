"""Second-pass Illusion transactions, cold reload and mixed-side AI choices."""
import pytest
from combat.ext import figment, placed
from combat.ext.illusion_second_pass import HOLD, PERMANENT, PRISON
from combat.typed_executor import bears_mark
from tests.auto_worker1_support import LEFT, RIGHT, ALLY, fight, act, reload, turn, action_sender, resolve
from tests.test_auto41_illusion import cell_action, answer


@pytest.mark.parametrize('ai', [False, True])
@pytest.mark.parametrize('study_success', [False, True])
def test_phantom_prison_study_and_speed_deadline(tmp_path, ai, study_success):
    def edit(bundle):
        if bundle['actor_template']['entity_id'] == RIGHT:
            bundle['actor_template'].setdefault('skills', {})['Investigation'] = 200 if study_success else -200
            bundle.setdefault('skills', {})['Investigation'] = 200 if study_success else -200
    combat, table, mid = fight(tmp_path, [PRISON], spheres=[figment.SPHERE], bundle_edit=edit)
    assert action_sender(combat, table, mid, 'Phantom Prison', ai=ai, target_id=RIGHT)([])['status'] == 'COMMITTED'
    if ai:
        combat.set_controller_mode(mid, actor_id=LEFT, controller_mode='MANUAL')
    engine = reload(combat, mid)
    target = engine.state.actors[RIGHT]
    assert engine._effective_speed(target) == 0
    assert bears_mark(target, LEFT, 'False Premise')
    assert any(c.condition_id == HOLD for c in target.conditions.values())
    assert engine.state.actors[LEFT].resources['resource:core.qi'] == 96
    turn(table, mid, RIGHT)
    result, prompts = resolve(lambda answers: act(table, mid, 'Break free', answers))
    assert result['status'] == 'COMMITTED'
    engine = reload(combat, mid)
    target = engine.state.actors[RIGHT]
    assert not target.action_available
    assert any(c.condition_id == HOLD for c in target.conditions.values()) != study_success
    assert bears_mark(target, LEFT, 'False Premise') != study_success
    assert engine._effective_speed(target) == (30 if study_success else 0)
    if not study_success:
        turn(table, mid, LEFT)
        engine = reload(combat, mid)
        assert engine._effective_speed(engine.state.actors[RIGHT]) == 30
        assert any(c.condition_id == HOLD for c in engine.state.actors[RIGHT].conditions.values())
        assert len([e for e in engine.events if e.event_type == 'SAVE_ROLLED']) == 2


def test_prison_initial_save_success_and_lost_concentration(tmp_path):
    combat, table, mid = fight(tmp_path/'success', [PRISON], left_save_dc=1)
    assert act(table, mid, 'Phantom Prison', target_id=RIGHT)['status'] == 'COMMITTED'
    target = reload(combat, mid).state.actors[RIGHT]
    assert not any(c.condition_id == HOLD for c in target.conditions.values())
    def saves(bundle):
        if bundle['actor_template']['entity_id'] == LEFT:
            bundle['actor_template']['saving_throws']['CON'] = -200
    combat, table, mid = fight(tmp_path/'failure', [PRISON], spheres=[figment.SPHERE],
        bundle_edit=saves, cause=[{'type':'damage', 'flat':60, 'damage_types':['force']}])
    assert act(table, mid, 'Phantom Prison', target_id=RIGHT)['status'] == 'COMMITTED'
    turn(table, mid, RIGHT)
    assert act(table, mid, 'Cause', target_id=LEFT)['status'] == 'COMMITTED'
    target = reload(combat, mid).state.actors[RIGHT]
    assert not any(c.condition_id == HOLD for c in target.conditions.values())
    assert not bears_mark(target, LEFT, 'False Premise')


@pytest.mark.parametrize('minor', [False, True])
def test_permanent_figment_creation_dismissal_and_concentration(tmp_path, minor):
    combat, table, mid = fight(tmp_path, [PERMANENT, figment.MINOR], spheres=[figment.SPHERE])
    toggle = next(group for group in table.state(mid)['menu']['actions'] if group['label'] == 'Figment: Permanent Illusion (8 CP)')
    assert 'future figment creations' in toggle['description'] and 'does not create an illusion now' in toggle['description']
    assert act(table, mid, 'Figment: Permanent Illusion (8 CP)')['status'] == 'COMMITTED'
    setup = next(row for row in reload(combat, mid).state.actors[LEFT].conditions.values() if row.condition_id == figment.SETUP)
    assert 'future creations cost +8 CP' in setup.data['label'] and 'until dismissed or dispelled' in setup.data['label']
    send = lambda answers: cell_action(table, mid, 'Minor Illusion' if minor else 'Create Figment', (7, 6), answers)
    resolve(send)
    engine = reload(combat, mid)
    zone, = placed.of(engine, 'figment')
    assert zone.duration_rounds is None and not zone.concentration_link
    assert placed.data(zone)['permanent'] == 1
    assert engine.state.actors[LEFT].concentration is None
    assert not any(g['label'] == ('Move Minor Illusion (up to 5 feet)' if minor else 'Move Figment') for g in table.state(mid)['menu']['actions'])
    assert engine.state.actors[LEFT].resources['resource:core.qi'] == 92
    turn(table, mid, RIGHT)
    turn(table, mid, LEFT)
    assert act(table, mid, 'Figment: Permanent Illusion (8 CP)')['status'] == 'COMMITTED'
    assert cell_action(table, mid, 'Create Figment', (9, 6))['status'] == 'COMMITTED'
    engine = reload(combat, mid)
    assert placed.of(engine, 'figment')[0].active
    assert engine.state.actors[LEFT].concentration is not None
    assert cell_action(table, mid, 'Dismiss Figment', (7, 6))['status'] == 'COMMITTED'
    engine = reload(combat, mid)
    assert len(placed.of(engine, 'figment')) == 1
    assert engine.state.actors[LEFT].concentration is not None


def test_permanent_glamer_retains_early_attack_ending(tmp_path):
    glamer = 'TAL_ILLUSION_OBSCURING_GLAMER'
    combat, table, mid = fight(tmp_path, [PERMANENT, glamer], spheres=[figment.SPHERE],
                              prepare=[{'type':'attack', 'attack_kind':'cultivation', 'no_damage':True}],
                              prepare_attack_bonus=100)
    labels = [g['label'] for g in table.state(mid)['menu']['actions']]
    matching = [label for label in labels if 'Obscuring Glamer' in label and 'Permanent Illusion' in label]
    assert matching, labels
    engine = reload(combat, mid)
    label = next(a.display_name for a in engine.action_catalog.values() if a.display_name in matching
                 and sum(n for _,n in a.costs)==8)
    assert act(table, mid, label, target_id=LEFT)['status'] == 'COMMITTED'
    engine = reload(combat, mid)
    modifiers = [m for m in engine.state.actors[LEFT].modifiers.values() if m.source_definition_id.endswith('.permanent')]
    assert modifiers and all(m.expires_on == 'UNTIL_REMOVED' for m in modifiers)
    assert engine.state.actors[LEFT].resources['resource:core.qi'] == 92
    assert engine.state.actors[LEFT].concentration is None
    assert act(table, mid, 'Prepare', target_id=RIGHT)['status'] == 'COMMITTED'
    engine = reload(combat, mid)
    assert not any(m.source_definition_id.endswith('.permanent') for m in engine.state.actors[LEFT].modifiers.values())


def test_permanent_muffled_glamer_removes_all_effects_when_it_ends(tmp_path):
    from combat.ext.illusion_riders import MUFFLED
    glamer = 'TAL_ILLUSION_OBSCURING_GLAMER'
    combat, table, mid = fight(tmp_path, [PERMANENT, glamer], spheres=[figment.SPHERE],
        prepare=[{'type': 'attack', 'attack_kind': 'cultivation', 'no_damage': True}], prepare_attack_bonus=100)
    assert act(table, mid, 'Obscuring Glamer: Muffled (1 CP) + Permanent Illusion (8 CP)', target_id=LEFT)['status'] == 'COMMITTED'
    engine = reload(combat, mid)
    assert any(row.condition_id == MUFFLED and row.source_definition_id.endswith('.permanent')
               for row in engine.state.actors[LEFT].conditions.values())
    assert act(table, mid, 'Prepare', target_id=RIGHT)['status'] == 'COMMITTED'
    engine = reload(combat, mid)
    assert not any(row.condition_id == MUFFLED for row in engine.state.actors[LEFT].conditions.values())
    assert not any(row.source_definition_id.endswith('.permanent') for row in engine.state.actors[LEFT].modifiers.values())


def test_permanent_glamer_dismissal_is_committed(tmp_path):
    combat, table, mid = fight(tmp_path, [PERMANENT, 'tianxia.talent.illusion.greater_invisibility'], spheres=[figment.SPHERE])
    assert act(table, mid, 'Greater Invisibility + Permanent Illusion (8 CP)', target_id=LEFT)['status'] == 'COMMITTED'
    assert any(c.condition_id.endswith('invisible') for c in reload(combat, mid).state.actors[LEFT].conditions.values())
    resolve(lambda answers: act(table, mid, 'Dismiss Permanent Glamer', answers))
    assert not any(c.condition_id.endswith('invisible') for c in reload(combat, mid).state.actors[LEFT].conditions.values()), [(i,c.model_dump(mode='json')) for i,c in reload(combat, mid).state.actors[LEFT].conditions.items()]


@pytest.mark.parametrize('hidden_enemy', [False, True])
def test_ai_selective_and_substantial_pick_sides_in_mixed_group(tmp_path, hidden_enemy):
    combat, table, mid = fight(tmp_path, [figment.SELECTIVE, 'tianxia.talent.illusion.substantial_phantasm'],
        spheres=[figment.SPHERE], ally=True, extra_witness=hidden_enemy, cause_target='SELF',
        positions={LEFT:{'x':3,'y':6}, RIGHT:{'x':4,'y':6}, ALLY:{'x':2,'y':6}},
        cause=[{'type':'condition', 'condition':'invisible', 'applies_to':'self', 'duration':'until_removed'}] if hidden_enemy else [])
    assert act(table, mid, 'Figment: Selective Premise (choose creatures when created)')['status'] == 'COMMITTED'
    if hidden_enemy:
        turn(table, mid, RIGHT)
        assert act(table, mid, 'Cause')['status']=='COMMITTED'
        turn(table, mid, LEFT)
        from combat.target_knowledge import can_see
        engine=reload(combat, mid)
        assert not can_see(engine, engine.state.actors[LEFT], engine.state.actors[RIGHT])
    # Drive a CELL action through session.execute_intent via the actual auto adapter.
    from combat.gate4_adapters import ManualControllerAdapter
    real = combat.controller
    class Controller:
        def choose_primary_action(self, context):
            cid = next(c.candidate_id for c in context.legal_candidates if c.source_definition_id.endswith('.substantial.grappled')
                       and c.destination and c.destination.x==3 and c.destination.y==6)
            return ManualControllerAdapter(lambda _: (cid, ())).choose_primary_action(context)
        def __getattr__(self, name):
            return getattr(real, name)
    combat.controller = Controller()
    combat.set_controller_mode(mid, actor_id=LEFT, controller_mode='LOCAL_AUTO')
    assert table.auto_step(mid, table.state(mid)['last_sequence'], [])['status']=='COMMITTED'
    engine=reload(combat, mid)
    zone, = placed.of(engine, 'figment')
    for aid in (LEFT, ALLY, RIGHT) + (('actor:factory.auto111-witness',) if hidden_enemy else ()):
        assert engine._footprint_intersects(engine.state.actors[aid], zone.affected_cells)
    assert set(placed.data(zone)['recognized']) <= {LEFT, ALLY}
    assert LEFT in placed.data(zone)['recognized']
    assert RIGHT not in placed.data(zone)['immune']
    engine=reload(combat, mid)
    assert any(c.condition_id.endswith('grappled') for c in engine.state.actors[RIGHT].conditions.values()) != hidden_enemy
    if hidden_enemy:
        assert any(c.condition_id.endswith('grappled') for c in engine.state.actors['actor:factory.auto111-witness'].conditions.values())
    assert not any(c.condition_id.endswith('grappled') for aid in (LEFT,ALLY) for c in engine.state.actors[aid].conditions.values())


def test_prison_successful_repeat_save_ends_exact_components(tmp_path):
    combat, table, mid = fight(tmp_path, [PRISON], cause_target='SELF',
        cause=[{'type':'save_bonus', 'flat':200, 'abilities':['INT'], 'applies_to':'self', 'duration':'until_removed'}])
    assert act(table, mid, 'Phantom Prison', target_id=RIGHT)['status']=='COMMITTED'
    turn(table, mid, RIGHT)
    assert act(table, mid, 'Cause')['status']=='COMMITTED'
    turn(table, mid, LEFT)
    engine=reload(combat, mid)
    target=engine.state.actors[RIGHT]
    assert not any(c.condition_id==HOLD for c in target.conditions.values())
    assert not bears_mark(target, LEFT, 'False Premise')
    assert engine._effective_speed(target)==30
    saves=[e for e in engine.events if e.event_type=='SAVE_ROLLED' and e.actor_id==RIGHT]
    assert len(saves)==2 and saves[-1].payload['success']


def test_ai_phantom_prison_triggers_marked_players_complete_resolve_after_authority_reload(tmp_path):
    """The built authority must expose Prison's Speed consequence to a marked defender's real save reaction."""
    from tests.hunt15_support import action_sender
    from combat.typed_executor import mark_condition_id

    yang = 'tianxia.sphere.yang'
    resolve_id = 'TAL_YANG_KINDLED_RESPONSES#complete_resolve'
    combat, table, mid = fight(tmp_path, [PRISON], right_talents=[resolve_id], right_spheres=[yang],
        cause=[{'type': 'mark', 'mark': 'Kindled Mark', 'applies_to': 'self',
                'duration': {'kind': 'until_end_of_your_next_turn'}}], cause_target='SELF', left_save_dc=1)
    engine = reload(combat, mid)
    prison = next(a for a in engine.action_catalog.values() if a.source_definition_id.endswith('illusion.phantom_prison'))
    typed = prison.parameters['typed']['effects'][0]
    custom = typed['on_fail'][0]
    assert custom['pending_effects'] == [{'type': 'speed', 'applies_to': 'target', 'becomes': 0}]

    turn(table, mid, RIGHT)
    assert act(table, mid, 'Cause')['status'] == 'COMMITTED'
    engine = reload(combat, mid)
    assert any(c.condition_id == mark_condition_id('Kindled Mark', RIGHT)
               for c in engine.state.actors[RIGHT].conditions.values())
    turn(table, mid, LEFT)
    # The Prison user is AI controlled. The defender is manual and receives no
    # forced choice; Complete Resolve spends the player's already placed mark.
    result, _ = resolve(action_sender(combat, table, mid, 'Phantom Prison', ai=True, target_id=RIGHT))
    assert result['status'] == 'COMMITTED'
    engine = reload(combat, mid)
    assert any(e.event_type == 'REACTION_RESOLVED' and e.source_definition_id == resolve_id
               and e.target_ids == (RIGHT,) for e in engine.events)
    assert not any(c.condition_id == mark_condition_id('Kindled Mark', RIGHT)
                   for c in engine.state.actors[RIGHT].conditions.values())
    assert not any(c.condition_id == HOLD for c in engine.state.actors[RIGHT].conditions.values())
    assert engine._effective_speed(engine.state.actors[RIGHT]) > 0


@pytest.mark.parametrize('stored_modes,independent,expected', [
    (['ADVANTAGE'], None, 'ADVANTAGE'),
    (['DISADVANTAGE'], None, 'DISADVANTAGE'),
    (['ADVANTAGE'], 'DISADVANTAGE', 'NORMAL'),
    (['DISADVANTAGE'], 'ADVANTAGE', 'NORMAL'),
    (['ADVANTAGE', 'DISADVANTAGE'], 'ADVANTAGE', 'NORMAL'),
])
def test_prison_repeat_consumes_matching_modes_once_through_reload(tmp_path, monkeypatch, stored_modes, independent, expected):
    """Native repeat reads persisted statuses once, then cancels all sources together."""
    import copy
    from combat import typed_executor
    rules = copy.deepcopy(typed_executor.rules())
    rules['conditions']['test_repeat_int_mode'] = {'save_mode': {'INT': independent}}
    monkeypatch.setattr(typed_executor, 'rules', lambda: rules)
    effects = [
        {'type': mode.lower(), 'applies_to': 'self', 'on': 'the next Intelligence saving throw', 'duration': 'until_removed'}
        for mode in stored_modes
    ] + [{'type': 'advantage', 'applies_to': 'self', 'on': 'the next Dexterity saving throw', 'duration': 'until_removed'}]
    if independent:
        effects.append({'type': 'condition', 'condition': 'test_repeat_int_mode', 'applies_to': 'self', 'duration': 'until_removed'})
    combat, table, mid = fight(tmp_path, [PRISON], cause_target='SELF', cause=effects)
    assert act(table, mid, 'Phantom Prison', target_id=RIGHT)['status'] == 'COMMITTED'
    turn(table, mid, RIGHT)
    assert act(table, mid, 'Cause')['status'] == 'COMMITTED'
    before = reload(combat, mid)
    statuses = {iid: c.data['rule']['save_against']['abilities']
                for iid, c in before.state.actors[RIGHT].conditions.items()
                if c.condition_id == 'condition:typed.save_against'}
    consumed = {iid for iid, abilities in statuses.items() if abilities == ['INT']}
    unrelated = {iid for iid, abilities in statuses.items() if abilities == ['DEX']}
    assert len(consumed) == len(stored_modes) and len(unrelated) == 1
    turn(table, mid, LEFT)
    engine = reload(combat, mid)
    saves = [e for e in engine.events if e.event_type == 'SAVE_ROLLED' and e.actor_id == RIGHT]
    assert len(saves) == 2 and saves[-1].payload['mode'] == expected
    assert consumed.isdisjoint(engine.state.actors[RIGHT].conditions)
    assert unrelated <= engine.state.actors[RIGHT].conditions.keys()
    assert any(c.condition_id == HOLD for c in engine.state.actors[RIGHT].conditions.values())
    removals = [e.payload['instance_id'] for e in engine.events
                if e.event_type == 'CONDITION_REMOVED' and e.payload.get('reason') == 'CONSUMED']
    assert all(removals.count(iid) == 1 for iid in consumed)
    # A second repeat must leave the unrelated status and never reconsume INT.
    turn(table, mid, RIGHT)
    turn(table, mid, LEFT)
    engine = reload(combat, mid)
    saves = [e for e in engine.events if e.event_type == 'SAVE_ROLLED' and e.actor_id == RIGHT]
    assert len(saves) == 3 and saves[-1].payload['mode'] == (independent or 'NORMAL')
    assert unrelated <= engine.state.actors[RIGHT].conditions.keys()
    removals = [e.payload['instance_id'] for e in engine.events
                if e.event_type == 'CONDITION_REMOVED' and e.payload.get('reason') == 'CONSUMED']
    assert all(removals.count(iid) == 1 for iid in consumed)

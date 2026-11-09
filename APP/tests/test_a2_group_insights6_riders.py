"""Existing Axes, Body guard and Concentration routes for the partial Insight clauses."""
import pytest
from combat.ext import insights6 as ix

POISE = 'insight.poise-tempered-presence'
from tests.test_a2_group_insights6 import fight
from tests.auto_worker1_support import LEFT,RIGHT,act,resolve,reload,turn
from tests.test_carry import KIT

AXE={'item_id':'tianxia.mortal.weapon.fu','name':'Fu (Battleaxe)','quantity':1}


@pytest.mark.parametrize('owned', [False,True])
def test_logging_breath_actual_hewing_strike_bite_and_rooted_success(tmp_path,owned):
    hewing='TAL_AXES_HEWING_STRIKE'
    combat,table,mid=fight(tmp_path,[hewing]+([ix.LOG] if owned else []),spheres=['tianxia.sphere.axes'],
        left_kit={'items':[*KIT['items'],AXE]},left_attack_bonus=100,left_score=50,
        prepare=[{'type':'mark','mark':'Bite','applies_to':'target','duration':{'kind':'until_removed'}}],
        cause=[{'type':'save','ability':'str','on_fail':[{'type':'forced_movement','distance_ft':15,'direction':'away'}],'on_success':[]}])
    resolve(lambda a:act(table,mid,'Prepare',a,target_id=RIGHT))
    engine=reload(combat,mid)
    name=next(a.display_name for a in engine.action_catalog.values() if a.owner_id==LEFT and
        (a.parameters.get('typed') or {}).get('source')==hewing and ': Bite' in a.display_name)
    resolve(lambda a:act(table,mid,name,a,target_id=RIGHT))
    assert reload(combat,mid).state.actors[LEFT].temporary_hp==(4 if owned else 0)
    turn(table,mid,RIGHT)
    before=reload(combat,mid).state.actors[LEFT].position
    resolve(lambda a:act(table,mid,'Cause',a,target_id=LEFT))
    engine=reload(combat,mid)
    assert (engine.state.actors[LEFT].position==before)==owned
    if owned:
        assert any(e.event_type=='D20_REWRITTEN' for e in engine.events)
        resolve(lambda a:act(table,mid,'Cause',a,target_id=LEFT))
        assert reload(combat,mid).state.actors[LEFT].position!=before


@pytest.mark.parametrize('owned', [False,True])
def test_frame_real_stamina_guard_qualifying_save_once(tmp_path,owned):
    guard='tianxia.path.body_refining.feature.stamina_guard'
    rows=[{'type':'damage','flat':20,'damage_types':['force']},
        {'type':'save','ability':'wis','on_fail':[{'type':'condition','condition':'frightened'}],'on_success':[]},
        # Meridian Breath overlaps Frame here: the smoke save can knock the
        # owner Prone, but Frame must still be spent on this same first roll.
        {'type':'save','ability':'con','save_categories':['smoke'],
         'on_fail':[{'type':'condition','condition':'prone'}],'on_success':[]},
        {'type':'save','ability':'str','on_fail':[{'type':'condition','condition':'grappled'}],'on_success':[]}]
    combat,table,mid=fight(tmp_path,[guard]+([ix.FRAME,ix.BREATH] if owned else []),left_resource='Stamina',cause=rows,cause_save_dc=100)
    turn(table,mid,RIGHT)
    resolve(lambda a:act(table,mid,'Cause',a,target_id=LEFT))
    engine=reload(combat,mid)
    assert any(e.event_type=='REACTION_RESOLVED' and e.source_definition_id.endswith('feature.stamina_guard') for e in engine.events)
    saves=[r for r in engine.rolls if str(r.reason).startswith('SAVE:')]
    assert [r.mode for r in saves[-3:]]==['NORMAL','ADVANTAGE' if owned else 'NORMAL','NORMAL']
    assert not any(c.condition_id==ix.GUARD for c in engine.state.actors[LEFT].conditions.values())


@pytest.mark.parametrize('owned',[False,True])
def test_pincer_changes_real_damage_concentration_roll(tmp_path,owned):
    lock='tianxia.subpath.body.mantis_style.feature.joint_lock'
    def concentrated(bundle):
        if bundle['actor_id']==RIGHT:
            for action in bundle['action_catalog']:
                if action['display_name']=='Cause':action['parameters']['typed']['duration']={'kind':'one_minute','concentration':True}
    combat,table,mid=fight(tmp_path,[lock]+([ix.PINCER] if owned else []),left_resource='Stamina',
        cause=[{'type':'ac_bonus','applies_to':'self','flat':1}],cause_target='SELF',bundle_edit=concentrated,
        prepare=[{'type':'condition','condition':'grappled','applies_to':'target','duration':{'kind':'until_removed'}}],
        extra_actions=[('Wound',{'target_kind':'HOSTILE_ENTITY','effects':[{'type':'damage','flat':1,'damage_types':['force']} ]})])
    turn(table,mid,RIGHT)
    resolve(lambda a:act(table,mid,'Cause',a))
    turn(table,mid,LEFT)
    resolve(lambda a:act(table,mid,'Prepare',a,target_id=RIGHT))
    resolve(lambda a:act(table,mid,'Joint Lock',a,target_id=RIGHT))
    resolve(lambda a:act(table,mid,'Wound',a,target_id=RIGHT))
    engine=reload(combat,mid)
    saves=[r for r in engine.rolls if 'CONCENTRATION' in str(r.reason).upper()]
    assert saves and saves[-1].mode==('DISADVANTAGE' if owned else 'NORMAL')


@pytest.mark.parametrize('owned',[False,pytest.param(True,marks=pytest.mark.xfail(strict=True,raises=AssertionError,reason='Inherited Erode Technique does not deliver its printed temporary-benefit trigger/options; Null-Script is PARTIAL.'))])
def test_null_script_erode_temporary_hp_at_extended_range(tmp_path,owned):
    erode='TAL_VOID_ERODE_TECHNIQUE'
    combat,table,mid=fight(tmp_path,[erode]+([ix.NULL] if owned else []),spheres=['tianxia.sphere.void'],
        cause=[{'type':'temp_hp','flat':10,'applies_to':'self'}],cause_target='SELF',
        positions={LEFT:{'x':1,'y':6},RIGHT:{'x':16,'y':6}},arena_edit=lambda a:a.update(width_squares=30))
    turn(table,mid,RIGHT)
    resolve(lambda a:act(table,mid,'Cause',a))
    engine=reload(combat,mid)
    assert engine.state.actors[LEFT].resources[ix.QI]==100-(1 if owned else 0)
    assert engine.state.actors[RIGHT].temporary_hp==(6 if owned else 10)


@pytest.mark.parametrize('auto',[False,True])
def test_poise_automatic_choice_does_not_use_unperceived_source(tmp_path,auto):
    rows=[{'type':'condition','condition':'invisible','applies_to':'self','duration':{'kind':'one_minute'}},
        {'type':'save','ability':'wis','on_fail':[{'type':'condition','condition':'frightened'}],'on_success':[]}]
    combat,table,mid=fight(tmp_path,[POISE],cause=rows,cause_save_dc=1)
    turn(table,mid,RIGHT)
    if auto:combat.set_controller_mode(mid,actor_id=LEFT,controller_mode='LOCAL_AUTO')
    resolve(lambda a:act(table,mid,'Cause',a,target_id=LEFT))
    engine=reload(combat,mid)
    assert bool([c for c in engine.state.actors[RIGHT].conditions.values() if 'beauty_mark' in c.condition_id]) == (not auto)


def test_frame_is_spent_on_first_qualifying_save_even_with_mountain_advantage(tmp_path):
    guard = 'tianxia.path.body_refining.feature.stamina_guard'
    def add_later_saves(bundle):
        if not any(action.get('owner_id') == RIGHT for action in bundle['action_catalog']):
            return
        for label, category in (('Prone Save', 'prone'), ('Grapple Save', 'grappled')):
            action_id = 'action:test.insights6.' + label.lower().replace(' ', '_')
            bundle['actor_template']['action_ids'].append(action_id)
            bundle['action_catalog'].append({
                'source_definition_id': action_id, 'display_name': label, 'owner_id': RIGHT,
                'economy': 'NONE', 'resolution_kind': 'TYPED', 'target_kind': 'HOSTILE_ENTITY',
                'range_ft': 60, 'costs': [], 'parameters': {'free_primary': True, 'typed': {
                    'effects': [{'type': 'save', 'ability': 'str',
                                'on_fail': [{'type': 'condition', 'condition': category}], 'on_success': []}],
                    'numbers': {'cl': 15, 'pb': 4, 'key_mod': 3, 'save_dc': 100},
                    'duration': {'kind': 'instant'}, 'riders': []}}})
    combat, table, mid = fight(tmp_path, [guard, ix.FRAME, ix.MOUNTAIN], left_resource='Stamina',
        cause=[{'type': 'damage', 'flat': 20, 'damage_types': ['force']},
               {'type': 'save', 'ability': 'wis', 'on_fail': [{'type': 'condition', 'condition': 'frightened'}],
                'on_success': []}], cause_name='Frame Trigger', bundle_edit=add_later_saves)
    turn(table, mid, RIGHT)
    resolve(lambda a: act(table, mid, 'Frame Trigger', a, target_id=LEFT))
    engine = reload(combat, mid)
    assert any(e.event_type == 'REACTION_RESOLVED' and e.source_definition_id.endswith('feature.stamina_guard')
               for e in engine.events)
    assert any(c.condition_id == ix.GUARD for c in engine.state.actors[LEFT].conditions.values())
    resolve(lambda a: act(table, mid, 'Prone Save', a, target_id=LEFT))
    engine = reload(combat, mid)
    first_save = [r for r in engine.rolls if str(r.reason).startswith('SAVE:')][-1]
    assert first_save.mode == 'ADVANTAGE'
    assert not any(c.condition_id == ix.GUARD for c in engine.state.actors[LEFT].conditions.values())
    resolve(lambda a: act(table, mid, 'Grapple Save', a, target_id=LEFT))
    engine = reload(combat, mid)
    second_save = [r for r in engine.rolls if str(r.reason).startswith('SAVE:')][-1]
    assert second_save.mode == 'NORMAL'


def test_frame_source_survives_golden_bell_nested_event_and_cold_reload(tmp_path, monkeypatch):
    """Golden Bell's nested TEMP_HP_GRANTED must not hide Stamina Guard's source."""
    guard = 'tianxia.path.body_refining.feature.stamina_guard'
    bell = {'name': 'Golden Bell Circulation', 'rounds': 10,
            'evidence': 'Golden Bell Circulation: +2 AC and temporary hit points when Stamina Guard reduces damage to 0.'}
    combat, table, mid = fight(tmp_path, [guard, ix.FRAME], left_resource='Stamina',
        extra_actions=[('Golden Bell Circulation', {'economy': 'BONUS_ACTION', 'target_kind': 'SELF',
                        'effects': [{'type': 'stance', **bell}]})],
        cause=[{'type': 'damage', 'flat': 5, 'damage_types': ['force']},
               {'type': 'save', 'ability': 'wis', 'on_fail': [{'type': 'condition', 'condition': 'frightened'}],
                'on_success': []}], cause_name='Frame Trigger')

    # Pin the documented subscriber ordering: Golden Bell can append its
    # temporary HP event while the original reaction is still being delivered.
    from combat import ext
    from combat.ext import bodya_body_refining as bodya
    monkeypatch.setitem(ext._HOOKS, 'event', list(ext._HOOKS['event']))
    event_hooks = ext._HOOKS['event']
    event_hooks.remove(bodya.golden_bell_soak)
    event_hooks.insert(event_hooks.index(ix.events), bodya.golden_bell_soak)

    # Activate Golden Bell through a journaled service intent before the hit.
    turn(table, mid, LEFT)
    resolve(lambda a: act(table, mid, 'Golden Bell Circulation', a))
    turn(table, mid, RIGHT)
    _, prompts = resolve(lambda a: act(table, mid, 'Frame Trigger', a, target_id=LEFT),
                         {'reaction:typed.' + guard: ['4']})
    engine = reload(combat, mid)
    assert any(e.event_type == 'TEMP_HP_GRANTED' and e.source_definition_id.endswith('Golden_Bell_Circulation')
               for e in engine.events), f"prompts={prompts!r}; reactions={[(e.source_definition_id, e.payload) for e in engine.events if e.event_type == 'REACTION_RESOLVED']!r}"
    assert any(c.condition_id == ix.GUARD for c in engine.state.actors[LEFT].conditions.values())

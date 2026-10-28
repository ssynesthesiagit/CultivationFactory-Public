"""Newly sealed blast save rules, distinct rays and bound persistent pulses."""
import pytest
from tests.auto_worker1_support import LEFT, RIGHT, fight, act, reload, action_sender, settle, turn, cell_send
from combat.gate4_adapters import ManualControllerAdapter
P = 'tianxia.talent.destruction.'
SPHERE = 'tianxia.sphere.destruction'
POOL = 'resource:core.qi'
BASE = 'TAL_DESTRUCTION_DESTRUCTIVE_BLAST'


OTHER = 'actor:factory.h15-other'
PASSAGE_ALLY = 'actor:factory.b3f2-passage-ally'

def triple_fight(tmp_path, talents, *, spheres=(), cause_stun=False, third_ally=False,
                 left_score=14, bundle_edit=None, right_talents=(), other_talents=(), fourth_ally=False):
    """Three independently compiled sheets, sealed before constructing the table."""
    import json, zipfile
    from combat.canonical import canonical_sha256
    from combat.factory_compiler import compile_character
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    from tests.h1_support import ROOT, sheet
    from tests.test_carry import KIT
    bundles = []
    roster = [LEFT, RIGHT, OTHER] + ([PASSAGE_ALLY] if fourth_ally else [])
    for aid, owned in [(LEFT, talents), (RIGHT, list(right_talents)), (OTHER, list(other_talents))] + ([(PASSAGE_ALLY, [])] if fourth_ally else []):
        doc = sheet(list(owned), cl=15, dc=100, kit={'starting_kit': KIT},
                    score=left_score if aid == LEFT else 14)
        doc['identity']['display_name'] = {LEFT:'Keeper', RIGHT:'Visitor', OTHER:'Second visitor', PASSAGE_ALLY:'Passage ally'}[aid]
        doc.setdefault('spheres_and_talents', {})['sphere_record_ids'] = list(spheres)
        doc['spheres_and_talents']['automatic_sphere_component_record_ids'] = []
        stats = doc['ability_scores_and_statistics']
        stats['technique_attack_bonus'] = 100
        stats['primary_resource']['maximum'] = 100
        stats['hit_points']['maximum'] = 1000
        folder = tmp_path / 'portable_characters' / aid.removeprefix('actor:factory.')
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder/'current.zip', 'w') as z:z.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(doc))
        b = compile_character(doc, actor_id=aid, reaction_plan={'ask':True})
        if cause_stun and aid == RIGHT:
            sid = 'action:test.tether_stun'
            b['actor_template']['action_ids'].append(sid)
            b['action_catalog'].append(dict(source_definition_id=sid, display_name='Cause', owner_id=aid,
                economy='NONE', resolution_kind='TYPED', target_kind='HOSTILE_ENTITY', range_ft=60, costs=[],
                parameters={'typed':{'effects':[{'type':'condition','condition':'stunned','applies_to':'target'}],
                'numbers':{}, 'duration':{'kind':'instant'}, 'riders':[]}}))
        if bundle_edit is not None:
            bundle_edit(b)
        b.pop('bundle_sha256', None);b['bundle_sha256'] = canonical_sha256(b);bundles.append(b)
    c = CombatService(ROOT, tmp_path)
    m = c._finish_factory_match(bundles, roster, {LEFT:'team:a', RIGHT:'team:b', OTHER:'team:a' if third_ally else 'team:b',
        **({PASSAGE_ALLY:'team:a'} if fourth_ally else {})},
        {LEFT:{'x':3,'y':6}, RIGHT:{'x':4,'y':6}, OTHER:{'x':3 if third_ally else 4,'y':5},
         **({PASSAGE_ALLY:{'x':3,'y':5}} if fourth_ally else {})},
        c.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena'], ([LEFT,OTHER] if third_ally else [LEFT]) + ([PASSAGE_ALLY] if fourth_ally else []),
        [RIGHT] if third_ally else [RIGHT,OTHER],
        control_modes={a:'MANUAL' for a in roster}, match_seed='worker1',
        display_name='Destruction regression', maximum_rounds=10)['match_id']
    t = TabletopService(c, tmp_path);turn(t,m,LEFT)
    return c,t,m


def cell_sender(c, t, m, label, xy, ai):
    if not ai:
        return cell_send(t, m, label, xy)
    menu = t.state(m)['menu']
    cid = next(o['candidate_id'] for g in menu['actions'] if g['label'] == label for o in g['options']
               if o.get('destination') == dict(x=xy[0], y=xy[1]))
    real = c.controller
    class Controller:
        def choose_primary_action(self, context):
            return ManualControllerAdapter(lambda _: (cid, ())).choose_primary_action(context)
        def __getattr__(self, name):
            return getattr(real, name)
    c.controller = Controller()
    c.set_controller_mode(m, actor_id=menu['actor_id'], controller_mode='LOCAL_AUTO')
    return lambda answers: t.auto_step(m, t.state(m)['last_sequence'], answers)


def picker(p):
    if p['context']['reaction_source_id'] == 'choice:needle.destruction_self':
        return ['exclude']
    return [o['id'] for o in (p.get('choice') or {}).get('options', [])][:1]


@pytest.mark.parametrize('case', ['free', 'paid', 'deepened'])
@pytest.mark.parametrize('ai', [False, True])
def test_final_paid_save_halves_damage_and_never_applies_blast_rider(tmp_path, case, ai):
    c, t, m = fight(tmp_path, [P+'calamity_form', P+'crushing_break'], right_score=214, spheres=[SPHERE])
    settle(lambda a: act(t, m, 'Blast Type: Crushing Break', a))
    if case == 'deepened':
        settle(lambda a: act(t, m, 'Deepen the Calamity: more dice (1 CP a blast: 1 + 1 per 2 Cultivation Levels)', a))
    before = reload(c, m)
    xy = (4, 6)
    name = 'Calamity Form: Line (1 CP)' if case == 'paid' else 'Calamity Form: Sphere'
    _, prompts = settle(cell_sender(c, t, m, name, xy, ai), picker)
    e = reload(c, m)
    rolls = [r for r in e.events if r.event_type == 'SAVE_ROLLED' and r.actor_id == RIGHT]
    assert rolls and all(r.payload['success'] for r in rolls)
    damage = [r for r in e.events if r.event_type == 'DAMAGE_COMMITTED' and RIGHT in r.target_ids]
    if case == 'free':
        assert not damage
    else:
        assert len(damage) == 1 and damage[0].payload['damage_type'] == 'BLUDGEONING'
        rolled = [r for r in e.events if r.event_type == 'DAMAGE_ROLLED' and RIGHT in r.target_ids][-1]
        assert damage[0].payload['hp_damage'] == rolled.payload['total'] // 2 > 0
        assert len(rolled.payload['dice']) == (8 if case == 'deepened' else 3)
    assert e.state.actors[RIGHT].position == before.state.actors[RIGHT].position
    assert not any(r.payload.get('ability') == 'STR' for r in rolls)
    assert e.state.actors[LEFT].resources[POOL] == 100 - int(case != 'free')
    assert e.state.actors[LEFT].current_hp == 1000
    if not ai and case != 'paid':
        assert any('exclude Keeper' in str(p) for p in prompts)


@pytest.mark.parametrize('case', ['new', 'legacy'])
def test_deepen_is_paid_even_when_successful_free_shape_negates_damage(tmp_path, case):
    def legacy(b):
        if case == 'legacy':
            for action in b['action_catalog']:
                for row in (action.get('parameters', {}).get('typed', {}).get('effects') or []):
                    if row.get('type') == 'destruction_shape_save':
                        row['type'] = 'save'
    c, t, m = fight(tmp_path, [P+'leaping_ruin'], right_score=214, spheres=[SPHERE], bundle_edit=legacy)
    settle(lambda a: act(t, m, 'Deepen the Calamity: more dice (1 CP a blast: 1 + 1 per 2 Cultivation Levels)', a))
    settle(lambda a: act(t, m, 'Leaping Ruin', a, target_id=RIGHT))
    e = reload(c, m)
    assert e.state.actors[LEFT].resources[POOL] == (99 if case == 'new' else 100)
    assert (e.state.actors[RIGHT].current_hp < 1000) == (case == 'new')


@pytest.mark.parametrize('case', ['paid_legacy', 'incarnation_discount', 'engine_and_incarnation'])
def test_paid_save_uses_final_cost_after_existing_discounts_and_preserves_legacy(tmp_path, case):
    def legacy(b):
        if case == 'paid_legacy':
            for action in b['action_catalog']:
                for row in (action.get('parameters', {}).get('typed', {}).get('effects') or []):
                    if row.get('type') == 'destruction_shape_save':row['type'] = 'save'
    talents = [P+'calamity_form']
    if case != 'paid_legacy':talents += [P+'calamity_sovereign_incarnation']
    if case == 'engine_and_incarnation':talents += [P+'catastrophe_engine']
    c, t, m = fight(tmp_path, talents, right_score=214, spheres=[SPHERE], bundle_edit=legacy)
    if case != 'paid_legacy':settle(lambda a: act(t, m, 'Calamity-Sovereign Incarnation', a))
    if case == 'engine_and_incarnation':settle(lambda a: act(t, m, 'Deepen the Calamity: more dice (1 CP a blast: 1 + 1 per 2 Cultivation Levels)', a))
    settle(cell_send(t, m, 'Calamity Form: Line (1 CP)', (4, 6)), picker)
    e = reload(c, m)
    assert e.state.actors[RIGHT].current_hp == 1000
    assert e.state.actors[LEFT].resources[POOL] == (99 if case == 'paid_legacy' else 95)


@pytest.mark.parametrize('case', ['manual', 'ai', 'legacy'])
def test_multi_ray_uses_distinct_creatures_and_one_attack_each(tmp_path, case):
    def legacy(b):
        if case == 'legacy':
            for action in b['action_catalog']:
                for row in (action.get('parameters', {}).get('typed', {}).get('effects') or []):
                    row.pop('distinct_targets', None)
    c, t, m = triple_fight(tmp_path, [P+'heaven_piercing_ray']) if case != 'legacy' else fight(tmp_path, [P+'heaven_piercing_ray'], left_attack_bonus=100, bundle_edit=legacy)
    def pick(p):
        if p['context']['reaction_source_id'] == 'choice:needle.rider_targets':return [RIGHT, OTHER]
        return picker(p)
    _, prompts = settle(action_sender(c, t, m, 'Heaven-Piercing Ray (Multi-Ray, 1 CP)', ai=case == 'ai', target_id=RIGHT), pick)
    e = reload(c, m)
    attacks = [r for r in e.events if r.event_type == 'ATTACK_ROLLED' and 'multi_ray' in r.source_definition_id]
    targets = [r.target_ids[0] for r in attacks]
    assert targets == ([RIGHT]*4 if case == 'legacy' else [RIGHT, OTHER])
    assert e.state.actors[LEFT].resources[POOL] == 99
    if case == 'manual':assert any('Each creature receives only one ray' in str(p) for p in prompts)


@pytest.mark.parametrize('case', ['new', 'legacy'])
def test_tether_pulse_binds_target_type_and_dice_without_repaying_deepen(tmp_path, case):
    def legacy(b):
        if case == 'legacy':
            for action in b['action_catalog']:
                rows = action.get('parameters', {}).get('typed', {}).get('effects') or []
                rows[:] = [r for r in rows if r.get('type') != 'destruction_prepare_release']
                for row in rows:
                    row.pop('bound_target', None)
                    for e in row.get('on_hit') or []:e.pop('bind_target', None)
    c, t, m = fight(tmp_path, [P+'ruin_binding_tether', P+'crushing_break'], left_attack_bonus=100,
                     spheres=[SPHERE], bundle_edit=legacy)
    assert not any(g['label'] == 'Ruin-Binding Tether: Pulse' for g in t.state(m)['menu']['actions']) if case == 'new' else True
    settle(lambda a: act(t, m, 'Blast Type: Crushing Break', a))
    settle(lambda a: act(t, m, 'Deepen the Calamity: more dice (1 CP a blast: 1 + 1 per 2 Cultivation Levels)', a))
    settle(lambda a: act(t, m, 'Ruin-Binding Tether', a, target_id=RIGHT))
    first = reload(c, m)
    stored = next(v.data for v in first.state.actors[LEFT].conditions.values() if v.condition_id.endswith('destruction_tether_type'))
    if case == 'new':assert stored['target_id'] == RIGHT and stored['dice_count'] == 8 and stored['final_cp'] == 1
    settle(lambda a: act(t, m, 'Blast Type: Unshaped Ruin (Force)', a))
    settle(lambda a: act(t, m, 'Deepen the Calamity: ordinary dice (no extra CP)', a))
    settle(lambda a: act(t, m, 'Ruin-Binding Tether: Pulse', a, target_id=RIGHT))
    e = reload(c, m)
    roll = [r for r in e.events if r.event_type == 'DAMAGE_ROLLED' and 'ruin_binding_tether.pulse' in r.source_definition_id][-1]
    assert len(roll.payload['dice']) == (8 if case == 'new' else 3)
    assert e.state.actors[LEFT].resources[POOL] == 99
    assert any(r.payload['damage_type'] == 'BLUDGEONING' for r in e.events if r.event_type == 'DAMAGE_COMMITTED' and 'tether.pulse' in r.source_definition_id)


@pytest.mark.parametrize('ai', [False, True])
def test_bound_tether_excludes_other_target_and_ends_with_concentration(tmp_path, ai):
    c,t,m = triple_fight(tmp_path, [P+'ruin_binding_tether'], cause_stun=True)
    settle(lambda a: act(t,m,'Ruin-Binding Tether',a,target_id=RIGHT))
    e = reload(c,m)
    candidates = [v for v in e.legal_candidates() if v.display_name == 'Ruin-Binding Tether: Pulse']
    assert candidates and all(v.target_ids == (RIGHT,) for v in candidates)
    settle(action_sender(c,t,m,'Ruin-Binding Tether: Pulse',ai=ai,target_id=RIGHT))
    e = reload(c,m)
    assert not any(OTHER in v.target_ids for v in e.events if v.event_type == 'DAMAGE_COMMITTED')
    if ai:c.set_controller_mode(m, actor_id=LEFT, controller_mode='MANUAL')
    turn(t,m,RIGHT)
    settle(lambda a: act(t,m,'Cause',a,target_id=LEFT))
    turn(t,m,LEFT)
    e = reload(c,m)
    assert e.state.actors[LEFT].concentration is None
    assert not any(v.condition_id.endswith('destruction_tether_type') for v in e.state.actors[LEFT].conditions.values())
    assert not any(v.display_name == 'Ruin-Binding Tether: Pulse' for v in e.legal_candidates())


@pytest.mark.parametrize('case', ['new', 'legacy'])
def test_blast_type_rider_requires_actual_damage_after_immunity(tmp_path, case):
    def legacy(b):
        if case == 'legacy':
            for action in b['action_catalog']:
                for row in (action.get('parameters', {}).get('typed', {}).get('effects') or []):
                    for e in row.get('on_hit') or []:e.pop('damage_required',None)
    c,t,m = fight(tmp_path, [BASE,P+'crushing_break'], left_attack_bonus=100, bundle_edit=legacy,
                  prepare=[{'type':'immunity','damage_types':['bludgeoning'],'applies_to':'target','duration':'one_minute'}])
    settle(lambda a: act(t,m,'Prepare',a,target_id=RIGHT))
    settle(lambda a: act(t,m,'Blast Type: Crushing Break',a))
    before = reload(c,m).state.actors[RIGHT].position
    settle(lambda a: act(t,m,'Destructive Blast',a,target_id=RIGHT))
    e = reload(c,m)
    assert e.state.actors[RIGHT].current_hp == 1000
    assert bool([v for v in e.events if v.event_type == 'SAVE_ROLLED' and v.actor_id == RIGHT]) == (case == 'legacy')
    assert (e.state.actors[RIGHT].position == before) == (case == 'new')


def returning(send, use):
    answers, prompts = [],[]
    for _ in range(12):
        result = send(answers)
        if result['status'] == 'COMMITTED':return result,prompts
        assert result['status'] == 'REACTION_REQUIRED'
        p = result['reaction'];prompts.append(p)
        ids = picker(p)
        answers.append({**p['context'],'selection':'USE' if use else 'DECLINE','option_ids':ids})
    raise AssertionError('too many choices')


@pytest.mark.parametrize('case', ['use','decline','far','unowned','legacy','broke'])
@pytest.mark.parametrize('ai', [False,True])
def test_returning_calamity_actual_damage_trigger_cost_range_and_choice(tmp_path,case,ai):
    def legacy(b):
        if case == 'legacy':
            for row in b['typed_reactions']:
                if row.get('feature_id') == P+'returning_calamity':row.update(costs=[],range_ft=None)
    c,t,m = fight(tmp_path, [] if case == 'unowned' else [P+'returning_calamity'], bundle_edit=legacy,
                  positions={LEFT:{'x':1,'y':1},RIGHT:{'x':8,'y':1}} if case=='far' else {LEFT:{'x':3,'y':6},RIGHT:{'x':4,'y':6}},
                  cause=[{'type':'damage','applies_to':'target','flat':1,'damage_types':['force']}],
                  prepare_target='SELF',prepare=[{'type':'rider','text':'Synthetic resource exhaustion'}] if case=='broke' else [],
                  prepare_costs=[(POOL,100)] if case=='broke' else [])
    if case == 'broke':settle(lambda a: act(t,m,'Prepare',a))
    turn(t,m,RIGHT)
    _,prompts = returning(action_sender(c,t,m,'Cause',ai=ai,target_id=LEFT),case!='decline')
    e = reload(c,m)
    fired = case in {'use','legacy'}
    assert bool([v for v in e.events if v.event_type=='DAMAGE_COMMITTED' and v.source_definition_id==P+'returning_calamity']) == fired
    assert e.state.actors[LEFT].resources[POOL] == (0 if case=='broke' else 99 if case=='use' else 100)
    assert e.state.actors[LEFT].reaction_available == (not fired)
    assert e.state.actors[LEFT].current_hp == 999
    assert bool(prompts) == (case in {'use','decline','legacy'})
    if case in {'use','decline'}:assert 'Returning Calamity' in str(prompts) and 'Visitor' in str(prompts)


@pytest.mark.parametrize('case', ['exclude','include','ai','unowned','legacy'])
def test_controlled_ruin_optional_self_exclusion_requires_new_owned_row(tmp_path,case):
    def legacy(b):
        # This test covers the earlier sealed creature-wide geometry and the
        # ownership of its optional self-exclusion. Newly reviewed Crossing
        # releases obey the owner's unscoped damaging-area rule (enemies only),
        # covered separately by test_a2_destruction_service.
        for a in b['action_catalog']:
            typed = a.get('parameters', {}).get('typed', {})
            if typed.get('source') == P+'ruin_crossing_step' and a['display_name']=='Ruin-Crossing Step':
                for key in ('recipients','harmful_recipients','include_self','exclude_self'):
                    typed.get('area', {}).pop(key, None)
                for row in typed.get('effects', []):
                    if row.get('type')=='destruction_shape_save':row['applies_to']='creatures_in_area'
                    if row.get('type')=='destruction_ruin_crossing_teleport':
                        row.pop('choose_landing',None);row.pop('applies_to',None)
        if case == 'legacy':b['typed_passives'][:] = [r for r in b['typed_passives'] if r.get('kind')!='controlled_self']
    talents = [P+'ruin_crossing_step'] + ([] if case=='unowned' else [P+'controlled_ruin'])
    c,t,m = fight(tmp_path,talents,bundle_edit=legacy)
    def pick(p):
        if p['context']['reaction_source_id']=='choice:needle.destruction_self':return ['include' if case=='include' else 'exclude']
        return picker(p)
    def exact_base(answers):
        view = t.state(m); menu = view['menu']
        group = next(g for g in menu['actions'] if g['label']=='Ruin-Crossing Step')
        cid = next(o['candidate_id'] for o in group['options'] if o.get('destination')=={'x':4,'y':6})
        return t.act(m,cid,menu['decision_id'],menu['state_version'],view['last_sequence'],answers)
    _,prompts = settle(cell_sender(c,t,m,'Ruin-Crossing Step',(4,6),True) if case=='ai' else exact_base,pick)
    e = reload(c,m)
    assert (e.state.actors[LEFT].current_hp == 1000) == (case in {'exclude','ai'})
    assert bool(prompts) == (case in {'exclude','include'})


def test_area_blast_excludes_caster_only_and_damages_allied_creature(tmp_path):
    c,t,m = triple_fight(tmp_path,[P+'calamity_form'],third_ally=True)
    settle(cell_send(t,m,'Calamity Form: Sphere',(3,6)),picker)
    e = reload(c,m)
    assert e.state.actors[LEFT].current_hp == 1000
    assert e.state.actors[RIGHT].current_hp < 1000 and e.state.actors[OTHER].current_hp < 1000
    assert {r.actor_id for r in e.events if r.event_type=='SAVE_ROLLED'} == {RIGHT,OTHER}


@pytest.mark.parametrize('case', ['manual','ai','legacy','unowned'])
def test_hammer_collision_adds_one_die_and_prone_not_full_cl_pool(tmp_path,case):
    def legacy(b):
        if case=='legacy':
            for row in b['typed_passives']:row.pop('single_collision_die',None)
    c,t,m = fight(tmp_path,[BASE,P+'crushing_break']+([] if case=='unowned' else [P+'hammer_through_the_line']),
                   left_attack_bonus=100,bundle_edit=legacy,positions={LEFT:{'x':3,'y':6},RIGHT:{'x':1,'y':6}})
    settle(lambda a: act(t,m,'Blast Type: Crushing Break',a))
    settle(action_sender(c,t,m,'Destructive Blast',ai=case=='ai',target_id=RIGHT))
    e = reload(c,m)
    rolls = [v for v in e.rolls if v.reason.endswith(':hammer')]
    assert len(rolls) == int(case!='unowned')
    if rolls:assert len(rolls[0].dice) == (3 if case=='legacy' else 1)
    assert any(v.condition_id.endswith('prone') for v in e.state.actors[RIGHT].conditions.values()) == (case!='unowned')


def test_tether_uses_native_dice_progression_above_last_table_band(tmp_path):
    c,t,m = fight(tmp_path,[P+'ruin_binding_tether'],cl=21,left_attack_bonus=100)
    settle(lambda a: act(t,m,'Ruin-Binding Tether',a,target_id=RIGHT))
    settle(lambda a: act(t,m,'Ruin-Binding Tether: Pulse',a,target_id=RIGHT))
    e = reload(c,m)
    roll = [v for v in e.events if v.event_type=='DAMAGE_ROLLED' and 'tether.pulse' in v.source_definition_id][-1]
    assert len(roll.payload['dice']) == 4
    stored = next(v.data for v in e.state.actors[LEFT].conditions.values() if v.condition_id.endswith('destruction_tether_type'))
    assert stored['dice_count'] == 4


# ------------------------------------------------------------------ Break the Guard: one option per creature
def guard_marker(engine, target):
    """The Break the Guard marker on ``target``: which option it carries, who put it there, and the exact
    instances that option created."""
    return next((v for v in target.conditions.values() if v.condition_id.endswith('destruction_break_guard_active')), None)


def guard_modifiers(target, field):
    return sorted(m.modifier_id for m in target.modifiers.values() if m.target_field == field)


def test_old_guard_marker_uses_its_source_actor_for_cross_caster_replacement_after_reload(tmp_path):
    # Commit the pre-instance-ID schema using ordinary typed effects in a fixture action.
    # No saved state or engine is edited: its source_actor_id is the only saved caster identity.
    source = 'action:test.old_break_guard'

    def old_guard_bundle(bundle):
        if bundle['actor_template']['entity_id'] != LEFT:
            return
        bundle['actor_template']['action_ids'].append(source)
        bundle['action_catalog'].append(dict(
            source_definition_id=source, display_name='Prepare old guard', owner_id=LEFT,
            economy='NONE', resolution_kind='TYPED', target_kind='HOSTILE_ENTITY', range_ft=60, costs=[],
            parameters={'typed': {'effects': [
                {'type': 'ac_bonus', 'applies_to': 'target', 'flat': -1,
                 'expires_on': 'START_OF_SOURCE_NEXT_TURN'},
                {'type': 'condition', 'condition': 'destruction_break_guard_active', 'applies_to': 'target',
                 'expires_on': 'START_OF_SOURCE_NEXT_TURN',
                 'condition_data': {'option': 'ac', 'origin': source, 'type_id': P + 'scouring_break',
                                    'label': 'Break the Guard: Reduce AC'}},
            ], 'numbers': {}, 'duration': {'kind': 'instant'}, 'riders': []}}))

    c, t, m = triple_fight(tmp_path, [P + 'scouring_break', P + 'break_the_guard'],
                           right_talents=[P + 'calamity_form', P + 'scouring_break', P + 'break_the_guard'],
                           spheres=[SPHERE], bundle_edit=old_guard_bundle)
    settle(lambda a: act(t, m, 'Prepare old guard', a, target_id=OTHER))
    first = reload(c, m)
    foe = first.state.actors[OTHER]
    marker = guard_marker(first, foe)
    assert marker.source_actor_id == LEFT
    assert set(marker.data) == {'option', 'origin', 'type_id', 'label'}
    old_ac = guard_modifiers(foe, 'armor_class')
    assert len(old_ac) == 1 and foe.modifiers[old_ac[0]].source_actor_id == LEFT

    turn(t, m, RIGHT)
    settle(lambda a: act(t, m, 'Break the Guard: Ignore Half Cover', a))
    settle(lambda a: act(t, m, 'Blast Type: Scouring Break', a))
    settle(cell_send(t, m, 'Calamity Form: Sphere', (3, 5)), picker)
    final = reload(c, m)
    foe = final.state.actors[OTHER]
    assert not guard_modifiers(foe, 'armor_class'), 'the original caster AC penalty must be removed'
    assert marker.instance_id not in foe.conditions
    assert any(v.condition_id.endswith('no_half_cover') and v.source_actor_id == RIGHT
               for v in foe.conditions.values())
    assert guard_marker(final, foe).data['caster'] == RIGHT
    assert any(v.event_type == 'MODIFIER_REMOVED' and v.payload.get('modifier_id') == old_ac[0]
               for v in final.events)


def test_guard_replacement_preserves_original_fracturing_modifier_id_after_reload(tmp_path):
    # Both initial modifiers come from the same Fracturing release. The replacing
    # Scouring release supplies no fresh Advantage, so it cannot hide loss of the original.
    c, t, m = triple_fight(tmp_path, [P + 'calamity_form', P + 'fracturing_break', P + 'break_the_guard'],
                           right_talents=[P + 'calamity_form', P + 'scouring_break', P + 'break_the_guard'],
                           spheres=[SPHERE])
    settle(lambda a: act(t, m, 'Break the Guard: Attack Advantage', a))
    settle(lambda a: act(t, m, 'Blast Type: Fracturing Break', a))
    settle(cell_send(t, m, 'Calamity Form: Sphere', (4, 5)), picker)
    first = reload(c, m)
    foe = first.state.actors[OTHER]
    marker = guard_marker(first, foe)
    guard_id = marker.data['mods']
    initial_ids = set(guard_modifiers(foe, 'incoming_attack_mode'))
    assert len(initial_ids) == 2 and guard_id in initial_ids
    type_id, = initial_ids - {guard_id}
    assert all(foe.modifiers[mid].source_actor_id == LEFT and
               foe.modifiers[mid].source_definition_id == marker.data['origin'] for mid in initial_ids)

    turn(t, m, RIGHT)
    settle(lambda a: act(t, m, 'Break the Guard: Reduce AC', a))
    settle(lambda a: act(t, m, 'Blast Type: Scouring Break', a))
    settle(cell_send(t, m, 'Calamity Form: Sphere', (3, 5)), picker)
    final = reload(c, m)
    foe = final.state.actors[OTHER]
    assert set(guard_modifiers(foe, 'incoming_attack_mode')) == {type_id}, \
        'the original Fracturing Type ID must survive and the original guard ID must disappear'
    assert guard_id not in foe.modifiers
    assert any(v.target_field == 'armor_class' and v.value == -1 for v in foe.modifiers.values())
    assert any(v.event_type == 'MODIFIER_REMOVED' and v.payload.get('modifier_id') == guard_id
               for v in final.events)
    assert not any(v.event_type == 'MODIFIER_REMOVED' and v.payload.get('modifier_id') == type_id
                   for v in final.events)


def test_a_second_caster_replaces_the_first_casters_break_the_guard_option_after_reload(tmp_path):
    # "A creature can suffer only one option from Break the Guard at a time" is a rule about the creature, not
    # about one caster. Two casters each own the talent and both failed saves on the same creature, so when the
    # second caster changes the option the earlier instance is the first caster's and has to be found by the marker
    # the first caster wrote -- not by whoever happens to be casting now. Matched against the casting creature
    # instead, the first caster's "cannot benefit from half cover" survived next to the new AC -1, and two options
    # were live on one creature. Committed and reloaded at each step: the marker is the only thing that survives.
    c, t, m = triple_fight(tmp_path, [P + 'calamity_form', P + 'fracturing_break', P + 'break_the_guard'],
                           right_talents=[P + 'calamity_form', P + 'fracturing_break', P + 'break_the_guard'],
                           spheres=[SPHERE])
    settle(lambda a: act(t, m, 'Break the Guard: Ignore Half Cover', a))
    settle(lambda a: act(t, m, 'Blast Type: Fracturing Break', a))
    settle(cell_send(t, m, 'Calamity Form: Sphere', (4, 5)), picker)
    first = reload(c, m)
    foe = first.state.actors[OTHER]
    marker = guard_marker(first, foe)
    cover = [v for v in foe.conditions.values() if v.condition_id.endswith('no_half_cover')]
    assert cover and marker is not None, 'the first caster should have left Ignore Half Cover and its marker'
    assert marker.data['option'] == 'cover' and marker.data['caster'] == LEFT
    assert cover[0].instance_id == marker.data['conds'], 'the marker must name the exact instance it created'

    turn(t, m, RIGHT)
    settle(lambda a: act(t, m, 'Break the Guard: Reduce AC', a))
    settle(lambda a: act(t, m, 'Blast Type: Fracturing Break', a))
    settle(cell_send(t, m, 'Calamity Form: Sphere', (3, 5)), picker)
    e = reload(c, m)
    foe = e.state.actors[OTHER]
    assert not [v for v in foe.conditions.values() if v.condition_id.endswith('no_half_cover')], \
        "the first caster's Ignore Half Cover must not survive the second caster's option change"
    penalty = [m for m in foe.modifiers.values() if m.target_field == 'armor_class' and m.value == -1]
    assert len(penalty) == 1, f'only the AC option should be live, got {[(m.target_field, m.value) for m in foe.modifiers.values()]}'
    replaced = guard_marker(e, foe)
    assert replaced.data['option'] == 'ac' and replaced.data['caster'] == RIGHT
    assert replaced.data['mods'] and penalty[0].modifier_id in replaced.data['mods'].split(',')


def test_break_the_guard_keeps_the_blast_types_own_advantage_and_removes_only_its_own_across_reload(tmp_path):
    # Fracturing Break prints its own Advantage for the creature that failed its save, and Break the Guard's
    # Attack Advantage option rides that same failed save, so the engine holds two Advantaging modifiers. When the
    # option changes only Break the Guard's own instance may be taken: Fracturing Break's printed benefit has to
    # survive. Asserted on exact modifier ids through a commit and reload, because a "there is still an Advantage"
    # check passes either way -- the Fracturing Blast below supplies a fresh Advantage of its own.
    # The first caster releases through a Ruin-Binding Tether Pulse, which freezes Scouring Break, while Fracturing
    # Break is what its sticky choice reads: Scouring Break grants no Advantage of its own, so nothing at all should
    # remain from that release once the option changes. A Pulse also locks out the Destruction shapes while it is
    # active, so the second release is a second caster's Fracturing Blast -- which also keeps the earlier option live,
    # because the marker lasts until the caster who wrote it takes its next turn.
    c, t, m = triple_fight(tmp_path, [P + 'ruin_binding_tether', P + 'scouring_break', P + 'fracturing_break', P + 'break_the_guard'],
                           right_talents=[P + 'calamity_form', P + 'fracturing_break', P + 'break_the_guard'],
                           spheres=[SPHERE])
    settle(lambda a: act(t, m, 'Blast Type: Scouring Break', a))
    settle(lambda a: act(t, m, 'Ruin-Binding Tether', a, target_id=OTHER))
    settle(lambda a: act(t, m, 'Blast Type: Fracturing Break', a))
    settle(lambda a: act(t, m, 'Break the Guard: Attack Advantage', a))
    settle(lambda a: act(t, m, 'Ruin-Binding Tether: Pulse', a, target_id=OTHER))
    first = reload(c, m)
    foe = first.state.actors[OTHER]
    marker = guard_marker(first, foe)
    assert marker.data['type_id'] == P + 'scouring_break', \
        f"a bound pulse must record the Type it froze, not the live choice, got {marker.data['type_id']!r}"
    guard_instance = marker.data['mods']
    assert guard_instance and guard_instance in guard_modifiers(foe, 'incoming_attack_mode'), \
        'the guard option from the pulse should be on the creature'

    turn(t, m, RIGHT)
    settle(lambda a: act(t, m, 'Break the Guard: Reduce AC', a))
    settle(lambda a: act(t, m, 'Blast Type: Fracturing Break', a))
    settle(cell_send(t, m, 'Calamity Form: Sphere', (3, 5)), picker)
    e = reload(c, m)
    foe = e.state.actors[OTHER]
    live = guard_modifiers(foe, 'incoming_attack_mode')
    assert guard_instance not in live, \
        'the guard option must be removed when the option changes; Scouring Break granted no Advantage to keep'
    assert live, "Fracturing Break grants its own Advantage; it must survive the option changing"
    assert [m for m in foe.modifiers.values() if m.target_field == 'armor_class' and m.value == -1]
    replaced = guard_marker(e, foe)
    assert replaced.data['option'] == 'ac' and replaced.data['type_id'] == P + 'fracturing_break'


def test_a_bound_tether_pulse_records_its_frozen_type_not_the_live_blast_type(tmp_path):
    # "The Blast Type ... [is] selected when you activate [the Tether] and cannot be changed while it remains
    # active", so a Pulse releases the Type frozen at activation. The marker recorded the caster's current sticky
    # choice instead, so a Scouring Break pulse released while Fracturing Break was selected was filed as
    # Fracturing-derived, and a later option change took the "the blast type granted an Advantage of its own"
    # exemption on that false premise.
    c, t, m = fight(tmp_path, [P + 'scouring_break', P + 'fracturing_break', P + 'break_the_guard', P + 'ruin_binding_tether'],
                    left_attack_bonus=100, spheres=[SPHERE])
    settle(lambda a: act(t, m, 'Blast Type: Scouring Break', a))
    settle(lambda a: act(t, m, 'Ruin-Binding Tether', a, target_id=RIGHT))
    settle(lambda a: act(t, m, 'Blast Type: Fracturing Break', a))
    settle(lambda a: act(t, m, 'Break the Guard: Attack Advantage', a))
    settle(lambda a: act(t, m, 'Ruin-Binding Tether: Pulse', a, target_id=RIGHT))
    first = reload(c, m)
    foe = first.state.actors[RIGHT]
    marker = guard_marker(first, foe)
    assert marker.data['type_id'] == P + 'scouring_break', \
        f"a bound pulse must record the Type it froze, got {marker.data['type_id']!r}"
    guard_instance = marker.data['mods']
    assert guard_instance and guard_instance in guard_modifiers(foe, 'incoming_attack_mode')
    # the pulse's Scouring Break denied reactions; Fracturing Break's own Advantage was never applied, which is
    # what makes a Fracturing-derived record wrong rather than merely untidy.
    assert not [v for v in foe.conditions.values() if v.condition_id.endswith('reaction_denied')
                and v.source_actor_id == RIGHT]

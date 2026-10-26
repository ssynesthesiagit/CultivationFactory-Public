"""Owned Magma choices, actual hit limits, active dice and local safe terrain."""
import json
from pathlib import Path
import pytest
from combat import zones, zone_subjects
from combat.ext import magma_crust, placed
from combat.typed_executor import condition_rules
from tests.auto_worker1_support import LEFT, RIGHT, fight, act, reload, action_sender, cell_send, settle
from tests.hunt15_support import turn
G = 'TAL_MAGMA_MAGMA_GLOB'
S = 'TAL_MAGMA_VOLCANO_SOVEREIGN_INCARNATION'
MAGMA = 'tianxia.sphere.magma'

def glob_attack():
    return json.loads((Path(__file__).resolve().parents[1] / 'authority/Tianxia_Typed_Mechanics_Authority_R1.json').read_text())['mechanics'][G]['effects'][0]

def choose(p):
    source = p['context']['reaction_source_id']
    if source == 'choice:needle.magma_glob_expression':
        return ['Heat Pressure']
    if source == 'choice:needle.magma_heat_pressure':
        return ['reactions']
    return [p['choice']['options'][0]['id']]

@pytest.mark.parametrize('ai', [False, True])
def test_glob_asks_on_actual_hit_and_limits_expression_across_real_hits(tmp_path, ai):
    c, t, m = fight(tmp_path, [G, magma_crust.SHAPE], spheres=[MAGMA], prepare=[glob_attack()], prepare_source=G, prepare_attack_bonus=100, left_attack_bonus=100)
    _, prompts = settle(action_sender(c, t, m, 'Magma Glob: Heat Pressure', ai=ai, target_id=RIGHT), choose)
    e = reload(c, m)
    assert any((r.get('no_reactions') for r in condition_rules(e.state.actors[RIGHT]))) if not ai else e._effective_speed(e.state.actors[RIGHT]) == 20
    if not ai:
        assert any((p['context']['reaction_source_id'] == 'choice:needle.magma_glob_expression' for p in prompts))
    if ai:
        c.set_controller_mode(m, actor_id=LEFT, controller_mode='MANUAL')
    _, later = settle(lambda a: act(t, m, 'Prepare', a, target_id=RIGHT), choose)
    assert not any((p['context']['reaction_source_id'] == 'choice:needle.magma_glob_expression' for p in later))
    e = reload(c, m)
    assert len([v for v in e.events if v.event_type == 'ATTACK_ROLLED']) == 2
    turn(t, m, RIGHT)
    turn(t, m, LEFT)
    _, again = settle(lambda a: act(t, m, 'Prepare', a, target_id=RIGHT), choose)
    assert any((p['context']['reaction_source_id'] == 'choice:needle.magma_glob_expression' for p in again))

def test_missed_glob_has_no_expression_choice_or_allowance(tmp_path):
    c, t, m = fight(tmp_path, [G, magma_crust.SHAPE], spheres=[MAGMA], left_attack_bonus=-1000)
    _, prompts = settle(lambda a: act(t, m, 'Magma Glob: Heat Pressure', a, target_id=RIGHT), choose)
    e = reload(c, m)
    assert not any((p['context']['reaction_source_id'] == 'choice:needle.magma_glob_expression' for p in prompts))
    assert not any((k.startswith('auto46:glob:') for k in e.state.actors[LEFT].turn_flags))

@pytest.mark.parametrize('cl,base', [(15, 3), (17, 4)])
def test_sovereign_glob_dice_require_active_form_and_revert_after_expiry(tmp_path, cl, base):
    c, t, m = fight(tmp_path, [S, G], spheres=[MAGMA], cl=cl, left_attack_bonus=100, prepare=[glob_attack()], prepare_source=G, prepare_attack_bonus=100, maximum_rounds=12)
    settle(lambda a: act(t, m, 'Magma Glob: Push 5 Feet', a, target_id=RIGHT))
    e = reload(c, m)
    rolls = [v for v in e.events if v.event_type == 'DAMAGE_ROLLED']
    assert rolls[-1].payload['expression'] == f'{base}d10+2'
    settle(lambda a: act(t, m, 'Volcano-Sovereign Incarnation', a))
    e = reload(c, m)
    assert magma_crust.sovereign_active(e, e.state.actors[LEFT]) and e.state.actors[LEFT].resources['resource:core.qi'] == 85
    assert len([v for v in e.events if v.event_type == 'DAMAGE_ROLLED']) == len(rolls)
    settle(lambda a: act(t, m, 'Prepare', a, target_id=RIGHT))
    e = reload(c, m)
    assert [v for v in e.events if v.event_type == 'DAMAGE_ROLLED'][-1].payload['expression'] == '6d10+3'
    for _ in range(10):
        turn(t, m, RIGHT)
        turn(t, m, LEFT)
    e = reload(c, m)
    assert not magma_crust.sovereign_active(e, e.state.actors[LEFT])
    settle(lambda a: act(t, m, 'Prepare', a, target_id=RIGHT))
    e = reload(c, m)
    attack = [v for v in e.events if v.event_type == 'ATTACK_ROLLED'][-1]
    count = base * (2 if attack.payload['dice'][0] == 20 else 1)
    assert [v for v in e.events if v.event_type == 'DAMAGE_ROLLED'][-1].payload['expression'] == f'{count}d10+3'

def test_safe_step_belongs_to_actual_ally_and_patch_and_survives_movement(tmp_path):
    c, t, m = fight(tmp_path, [G, magma_crust.SHAPE], spheres=[MAGMA], left_attack_bonus=100, prepare_target='SELF', prepare=[{'type': 'zone'}], prepare_zone_spec={'shape': 'sphere', 'size_ft': 5, 'centered_on_self': True, 'difficult': 'all', 'duration': {'kind': 'minutes', 'amount': 1}, 'name': 'Ordinary rubble'})

    def patch(p):
        source = p['context']['reaction_source_id']
        return ['Molten Terrain Patch'] if source == 'choice:needle.magma_glob_expression' else ['cell:3,5'] if source == 'choice:needle.magma_patch' else [p['choice']['options'][0]['id']]
    settle(lambda a: act(t, m, 'Magma Glob: Molten Terrain Patch', a, target_id=RIGHT), patch)
    e = reload(c, m)
    z, = magma_crust.patches(e, e.state.actors[LEFT], 'molten')
    assert (3, 5) in zones.difficult_cells(e, e.state.actors[LEFT])
    settle(cell_send(t, m, 'Shape the Crust: Safe Stepping Line', (3, 5)), lambda p: [LEFT])
    e = reload(c, m)
    z = e.state.zones[z.zone_id]
    assert not zone_subjects.allowed(e, z, e.state.actors[LEFT], {'who': 'any'})
    assert zone_subjects.allowed(e, z, e.state.actors[RIGHT], {'who': 'any'})
    assert (3, 5) not in zones.difficult_cells(e, e.state.actors[LEFT])
    settle(lambda a: act(t, m, 'Prepare', a))
    e = reload(c, m)
    assert (3, 5) in zones.difficult_cells(e, e.state.actors[LEFT])
    st = t.state(m)
    menu = st['menu']
    candidate = next((v for v in c._load_session(m).engine.legal_candidates() if v.display_name.startswith('Move') and v.destination and ((v.destination.x, v.destination.y) == (3, 5))))
    settle(lambda a: t.act(m, candidate.candidate_id, menu['decision_id'], menu['state_version'], st['last_sequence'], a))
    e = reload(c, m)
    assert e.state.actors[LEFT].position.y == 5 and e.state.actors[LEFT].current_hp == 1000
    assert not any((v.event_type == 'SAVE_ROLLED' for v in e.events))
    turn(t, m, RIGHT)
    turn(t, m, LEFT)
    e = reload(c, m)
    assert not magma_crust.patches(e, e.state.actors[LEFT])
    assert not any((v.condition_id == magma_crust.SAFE for v in e.state.actors[LEFT].conditions.values()))

def test_sovereign_molten_patch_snapshots_actual_glob_dice_for_entry(tmp_path):
    c, t, m = fight(tmp_path, [G, S], left_attack_bonus=100)
    settle(lambda a: act(t, m, 'Volcano-Sovereign Incarnation', a))

    def pick(p):
        source = p['context']['reaction_source_id']
        return ['Molten Terrain Patch'] if source.endswith('magma_glob_expression') else ['cell:5,6']
    settle(lambda a: act(t, m, 'Magma Glob: Molten Terrain Patch', a, target_id=RIGHT), pick)
    e = reload(c, m)
    z, = magma_crust.patches(e, e.state.actors[LEFT])
    damage = placed.data(z)['damage']
    assert damage[0]['dice'] == {'count': 6, 'sides': 10} and 'dice_by_cl' not in damage[0]
    turn(t, m, RIGHT)
    st = t.state(m)
    menu = st['menu']
    candidate = next((v for v in c._load_session(m).engine.legal_candidates() if v.display_name.startswith('Move') and v.destination and ((v.destination.x, v.destination.y) == (5, 6))))
    settle(lambda a: t.act(m, candidate.candidate_id, menu['decision_id'], menu['state_version'], st['last_sequence'], a))
    e = reload(c, m)
    assert any((v.event_type == 'SAVE_ROLLED' and v.actor_id == RIGHT and (not v.payload['success']) for v in e.events))
    assert [v for v in e.events if v.event_type == 'DAMAGE_ROLLED'][-1].payload['expression'] == '6d10+2'

@pytest.mark.parametrize('key,label,cl,dice,cost', [('TAL_MAGMA_LAVA_BURST', 'Lava Burst', 11, '8d6+0', 4), ('TAL_MAGMA_LAVA_BURST', 'Lava Burst', 17, '10d6+0', 4), ('TAL_MAGMA_OBSIDIAN_RAIN', 'Obsidian Rain', 10, '8d8+0', 7), ('TAL_MAGMA_OBSIDIAN_RAIN', 'Obsidian Rain', 17, '10d8+0', 7)])
def test_audited_full_area_damage_failure_and_ground_persist(tmp_path, key, label, cl, dice, cost):
    c, t, m = fight(tmp_path, [key], cl=cl, positions={LEFT: {'x': 3, 'y': 6}, RIGHT: {'x': 8, 'y': 6}})
    settle(cell_send(t, m, label, (8, 6)))
    e = reload(c, m)
    assert any((v.event_type == 'DAMAGE_ROLLED' and v.payload['expression'] == dice for v in e.events))
    assert e.state.actors[LEFT].resources['resource:core.qi'] == 100 - cost
    assert any((z.active and (8, 6) in {(p.x, p.y) for p in z.affected_cells} for z in e.state.zones.values()))
    if key.endswith('RAIN'):
        assert any((r.get('no_reactions') for r in condition_rules(e.state.actors[RIGHT])))
    else:
        assert any((v.condition_id == 'condition:typed.prone' for v in e.state.actors[RIGHT].conditions.values()))

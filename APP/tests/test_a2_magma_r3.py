"""Readable overlapping surface-copy choices through persisted service execution."""
import copy
import json
import pytest
from combat import zones
from combat.gate2_runtime_models import Position
from tests.test_a2_magma import (FLOW, RIVER, MAGMA, LEFT, RIGHT, fight, settle,
                                cell_send, turn, cold, act, clear_arena)


@pytest.mark.parametrize('source,name', [(FLOW, 'Lava Flow'), (RIVER, 'Blackglass River')])
@pytest.mark.parametrize('chosen_copy', [1, 2])
def test_overlapping_copies_display_clocks_and_move_selected_label(tmp_path, source, name, chosen_copy):
    c,t,m=fight(tmp_path,[source],spheres=[MAGMA],arena_edit=clear_arena,
                positions={LEFT:{'x':3,'y':6},RIGHT:{'x':5,'y':6}})
    settle(cell_send(t,m,name,(5,6)))
    turn(t,m,RIGHT);turn(t,m,LEFT)
    settle(cell_send(t,m,name,(5,6)))
    c,t,e=cold(c,m)
    areas=sorted(zones.typed_zones(e),key=lambda z:z.created_round)
    assert len(areas)==2 and areas[0].created_round < areas[1].created_round
    old={z.zone_id:copy.deepcopy(z.model_dump(mode='json')) for z in areas}
    selected=[]
    def pick(p):
        source=p['context']['reaction_source_id']
        if source=='choice:needle.surface_destination':
            return ['cell:5,8']
        if source=='choice:needle.surface_area':
            assert p['context']['reactor_id']==LEFT
            options=p['choice']['options']
            labels=[v['label'] for v in options]
            assert len(labels)==2 and len(set(labels))==2
            for i,z in enumerate(areas,1):
                remaining=z.duration_rounds-(e.state.round_number-z.created_round)
                label=next(v['label'] for v in options if v['id']==z.zone_id)
                assert name in label and '(5, 6)' in label
                assert f'copy {i}' in label
                assert f'cast in round {z.created_round}' in label
                assert f'{remaining} rounds remaining' in label
                assert all(a.zone_id not in label for a in areas)
            # Choose by the information actually displayed to the player.
            option,= [v for v in options if f'copy {chosen_copy} ' in v['label']]
            selected.append(option['id'])
            (tmp_path/'displayed-choice.json').write_text(json.dumps(p,indent=2))
            return [option['id']]
        return [p['choice']['options'][0]['id']]
    result,prompts=settle(lambda answers:act(t,m,name+': move the line',answers),pick)
    assert result['status']=='COMMITTED' and len(selected)==1
    assert any(p['context']['reaction_source_id']=='choice:needle.surface_area' for p in prompts)
    assert selected[0]==areas[chosen_copy-1].zone_id
    c,t,e=cold(c,m)
    for z in zones.typed_zones(e):
        if z.zone_id==selected[0]:
            assert z.center==Position(x=5,y=8)
            assert {(p.x,p.y,p.z) for p in z.affected_cells}=={
                (p['x'],p['y']+2,p.get('z',0)) for p in old[z.zone_id]['affected_cells']}
            assert z.created_round==old[z.zone_id]['created_round']
            assert z.duration_rounds==old[z.zone_id]['duration_rounds']
            assert z.per_turn_triggered==old[z.zone_id]['per_turn_triggered']
        else:
            assert z.model_dump(mode='json')==old[z.zone_id]
    assert not e.state.actors[LEFT].bonus_action_available

"""Explicit destination transport for B3F2 Shadow/Void table fixtures."""
from tests.auto_worker1_support import cell_send as area_send
from combat.ext.needle import cell_id
from combat.gate2_runtime_models import Position


def cell_send(table, mid, label, xy):
    def send(answers):
        state = table.state(mid)
        menu = state['menu']
        group = next(g for g in menu['actions'] if g['label'] == label)
        if not group.get('destination_choice') and any(o.get('destination') for o in group['options']):
            return area_send(table, mid, label, xy)(answers)
        cid = group['options'][0]['candidate_id']
        submitted = list(answers)
        result = table.act(mid, cid, menu['decision_id'], menu['state_version'], state['last_sequence'], submitted)
        if result['status'] == 'REACTION_REQUIRED':
            prompt = result['reaction']
            if prompt['context']['reaction_source_id'] == 'choice:needle.teleport_destination':
                destination = cell_id(Position(x=xy[0], y=xy[1]))
                assert destination in [o['id'] for o in prompt['choice']['options']], (xy, prompt)
                submitted.append({**prompt['context'], 'selection': 'USE', 'option_ids': [destination]})
                result = table.act(mid, cid, menu['decision_id'], menu['state_version'], state['last_sequence'], submitted)
        return result
    return send

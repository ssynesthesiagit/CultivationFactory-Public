"""Temporary diagnostic (removed before commit)."""
from test_mgr_t15_close_ten_thousand_returning_streams import MINOR, ALLY, OWNER, cold, prepare, send


def test_diag_second_return_heal(tmp_path):
    mid, areas = prepare(tmp_path, count=4, injured=True)
    eng = cold(tmp_path, mid)[2]
    info = {'hp0': eng.state.actors[ALLY].current_hp, 'max': eng.state.actors[ALLY].maximum_hp,
            'areas': [z.zone_id for z in areas], 'active': [z.active for z in areas]}
    sel = []
    def choose(p):
        kind = p['context']['reaction_source_id']
        info.setdefault('prompts', []).append(kind[-40:])
        if kind.endswith('returning_streams_select'):
            return sel
        if kind.endswith('returning_streams_operation'):
            return ['end']
        if kind.endswith('returning_streams_heal'):
            return [ALLY]
        return None
    for i, name in enumerate((MINOR, MINOR.removesuffix(' (free)'))):
        sel[:] = [z.zone_id for z in areas[i * 2:i * 2 + 2]]
        info.setdefault('run', []).append(i)
        send(tmp_path, mid, name, choose=choose)
        e = cold(tmp_path, mid)[2]
        info.setdefault('hp', []).append(e.state.actors[ALLY].current_hp)
        info.setdefault('active_after', []).append([z.active for z in e.state.zones.values() if z.owner_id == OWNER and z.trigger_profile.get('name') == 'Shape Current'])
    assert False, repr(info)

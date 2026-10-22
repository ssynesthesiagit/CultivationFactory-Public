
from tests.test_survivor_cinder_breath import setup, OWNER, ALLY, FOE, use
from tests.worker2_support import candidate


def test_probe(tmp_path):
    modes = {OWNER: 'LOCAL_AUTO', ALLY: 'MANUAL', FOE: 'LOCAL_AUTO'}
    combat, table, mid = setup(tmp_path, modes=modes)
    out = []
    for i in range(30):
        menu = table.state(mid)['menu']
        eng = combat._load_session(mid).engine
        out.append(('menu', menu.get('actor_id'), sorted(menu.keys()), eng.state.current_actor_id, eng.state.state_version))
        r = table.auto_step(mid, 0, [])
        eng = combat._load_session(mid).engine
        out.append(('status', r['status'], [(e.event_type, getattr(e, 'source_definition_id', None), getattr(e,'actor_id',None)) for e in eng.events[-4:]]))
        if r['status'] != 'COMMITTED':
            break
    for row in out:
        print(row)
    assert False, out

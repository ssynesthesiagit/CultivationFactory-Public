
import pathlib, tempfile
from tests.test_survivor_cinder_breath import setup, OWNER, ALLY, FOE


def test_probe(tmp_path):
    modes = {OWNER: 'LOCAL_AUTO', ALLY: 'MANUAL', FOE: 'LOCAL_AUTO'}
    combat, table, mid = setup(tmp_path, modes=modes)
    out = []
    for i in range(14):
        menu = table.state(mid)['menu']
        out.append(('menu', menu.get('actor_id'), sorted(menu.keys())))
        r = table.auto_step(mid, 0, [])
        out.append(('status', r['status'], r.get('actor_id')))
        eng = combat._load_session(mid).engine
        out.append(('events', [(e.event_type, getattr(e, 'source_definition_id', None)) for e in eng.events[-3:]]))
        if r['status'] == 'REACTION_REQUIRED':
            break
    for row in out:
        print(row)
    assert False, out

"""Sol review F18 regressions for the Orbiting Shield Warden lane.

F18-1: destroying a projected Ward from a stale copy writes nothing when the live
Ward already fell, and never overwrites fields changed since the caller read it.
F18-2: a real table commit of Manifest Ward spends the Qi, creates one projected
Ward, and the Ward survives a cold replay (service level, not unit calls).
"""
from types import SimpleNamespace

from combat.ext import orbiting_shield_warden as w
from combat.gate2_runtime_models import Position, RuntimeObjectState
from tests import r1i_service_support as s
from tests import test_mgr_t14_warden_review_f9 as f9

OWNER = 'actor:f18.owner'
QI = 'resource:core.qi'


def _ward(**component):
    return RuntimeObjectState(object_id='object:f18.ward', object_kind='QI_CONSTRUCT', owner_id=OWNER,
                              position=Position(x=1, y=1, z=0), unattended=True, flammable=False,
                              component={w.TAG: {'owner': OWNER, 'projected': 1, 'location': 'floating',
                                                 'protected': '', **component}})


def _engine(ward):
    writes = []
    engine = SimpleNamespace(state=SimpleNamespace(objects={ward.object_id: ward}, actors={}, round_number=1,
                                                   current_slot_index=0))
    def update_object(obj, source, owner):
        writes.append(obj)
        engine.state.objects[obj.object_id] = obj
    engine._update_object = update_object
    return engine, writes


def test_f18_projected_ward_already_destroyed_is_not_written_again_from_stale_copy():
    live = _ward().model_copy(update={'destroyed': True, 'current_hp': 0})
    engine, writes = _engine(live)
    stale = _ward()  # the caller still holds the pre-destroy copy
    w.destroy(engine, stale, 'test')
    assert writes == []
    assert engine.state.objects[live.object_id].destroyed


def test_f18_projected_ward_destroy_keeps_fields_changed_since_the_stale_copy():
    live = _ward(protected='prot:f18.target')
    engine, writes = _engine(live)
    stale = _ward()  # read before the Ward was assigned to a protected creature
    w.destroy(engine, stale, 'test')
    assert len(writes) == 1
    written = engine.state.objects[live.object_id]
    assert written.destroyed
    assert written.component[w.TAG]['protected'] == 'prot:f18.target'


def test_f18_real_table_manifest_ward_spends_qi_and_survives_cold_replay(tmp_path):
    combat, table, mid = f9.match(tmp_path)
    before = f9.fresh(combat, mid).state.actors[s.OWNER].resources.get(QI, 0)
    f9.commit(table, mid, s.candidate(table, mid, 'Manifest Ward'))
    engine = f9.fresh(combat, mid)
    assert engine.state.actors[s.OWNER].resources.get(QI, 0) == before - 1
    wards = w.shields(engine, engine.state.actors[s.OWNER])
    assert len(wards) == 1
    assert wards[0].component[w.TAG]['projected']

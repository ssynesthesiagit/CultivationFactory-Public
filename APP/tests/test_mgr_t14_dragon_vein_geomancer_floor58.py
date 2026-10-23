"""Dragon-Vein native acquisition, table and cold-replay regressions.

Test authority is installed and admitted through NS1R. No injected passive,
fabricated ownership marker, external server or browser is used.
"""
from copy import deepcopy

import pytest

from app.core import Database, Settings, FoundryError
from combat.factory_compiler import compile_character
from combat.ext.dragon_vein_geomancer import READ, CIRCUIT, NETWORK, PASSAGE, IMPERIAL, BLOCK
from non_sphere_authority import NonSphereAuthorityService
from tests.h1_support import ROOT, sheet
from tests.ns1r_evidence_helpers import install_authority_test_pack, ap_award, commit_authority_event
from tests.test_ns1r_non_sphere_authority import insert_project
from tests.worker2_support import OWNER, fixture, reload, settle

QI_PATH = 'tianxia.path.qi_cultivation'
SUBPATH = 'tianxia.subpath.qi.dragon_vein_geomancer'


@pytest.fixture(scope='module')
def acquired(tmp_path_factory):
    settings = Settings.from_env(ROOT,tmp_path_factory.mktemp('geomancy-acquisition'))
    settings.ensure_dirs()
    db = Database(settings)
    db.migrate()
    service = NonSphereAuthorityService(db)
    install_authority_test_pack(db,service)
    cache = {}
    def get(cl):
        if cl not in cache:
            pid = 'geomancy-'+str(cl)
            insert_project(db,pid,cl)
            service.initialize_for_project(pid,target_cl=cl,path_ids=[QI_PATH],method_id='METHOD-001')
            service.allocate_advancement(pid,{QI_PATH:cl-1},
                evidence_id=ap_award(db,service,pid,'METHOD-001',cl,cl-1),idempotency_key=pid+'-advance')
            # Restricted Scripture is denied until its exact native access
            # event is committed; a similar school never supplies the grant.
            with pytest.raises(FoundryError,match='exact access-source record'):
                service.select_subpath(pid,QI_PATH,SUBPATH)
            access = commit_authority_event(db,service,pid,'subpath_access',{'selection_id':SUBPATH})
            service.select_subpath(pid,QI_PATH,SUBPATH,access_source_records=[access])
            current = NonSphereAuthorityService(db).get_state(pid)
            doc = sheet([],cl=cl,name='Geomancer')
            doc['path_and_subpath'] = {'paths':current['paths']}
            cache[cl] = doc
        return deepcopy(cache[cl])
    return get


@pytest.mark.parametrize('cl,expected',[(3,{READ}),(6,{READ,CIRCUIT}),(10,{READ,CIRCUIT,NETWORK}),
                                     (14,{READ,CIRCUIT,NETWORK,PASSAGE}),(18,{READ,CIRCUIT,NETWORK,PASSAGE,IMPERIAL})])
def test_native_acquisition_gates_each_tier(acquired,cl,expected):
    bundle = compile_character(acquired(cl),actor_id=OWNER)
    marker = next(r for r in bundle['typed_passives'] if r.get('block') == BLOCK)
    assert set(marker['owned']) == expected
    assert marker['numbers']['cl'] == cl


def test_wrong_parent_and_no_owner_are_inert(acquired):
    for doc in (sheet([],cl=18),acquired(18)):
        if doc.get('path_and_subpath'):
            next(r for r in doc['path_and_subpath']['paths'] if r['path_id'] == QI_PATH)['path_id'] = 'tianxia.path.body_refining'
        bundle = compile_character(doc,actor_id=OWNER)
        assert not any(r.get('block') == BLOCK for r in bundle['typed_passives'])
        assert not any(a['parameters'].get('geomancy') for a in bundle['action_catalog'])


def test_suppression_uses_the_owning_path_level(acquired):
    doc = acquired(18)
    next(r for r in doc['path_and_subpath']['paths'] if r['path_id'] == QI_PATH)['effective_cl'] = 3
    bundle = compile_character(doc,actor_id=OWNER)
    marker = next(r for r in bundle['typed_passives'] if r.get('block') == BLOCK)
    assert marker['owned'] == [READ]
    assert marker['numbers']['cl'] == 3


def test_anchor_placement_is_a_table_commit_and_cold_replay(tmp_path,acquired):
    owner = compile_character(acquired(3),actor_id=OWNER,reaction_plan={'ask':True})
    combat,table,mid = fixture(tmp_path,[],cl=3,owner_bundle=owner,seed='GEOMANCY-ANCHOR')
    before = reload(tmp_path,mid)
    action = next(a for a in before.action_catalog.values() if a.parameters.get('geomancy') == 'place')
    candidates = [c for c in before.legal_candidates() if c.source_definition_id == action.source_definition_id]
    assert candidates
    qi = before.state.actors[OWNER].resources['resource:core.qi']
    selected = candidates[0]
    settle(table,mid,selected.candidate_id)
    after = reload(tmp_path,mid)
    objects = [o for o in after.state.objects.values() if (o.component or {}).get(BLOCK)]
    assert len(objects) == 1
    anchor = objects[0]
    assert anchor.position == selected.destination
    assert anchor.owner_id == OWNER and anchor.ac == 14 and anchor.maximum_hp == 6
    assert anchor.damage_immunities == ('POISON','PSYCHIC')
    assert anchor.component[BLOCK]['end_round'] == before.state.round_number+4800
    assert after.state.actors[OWNER].resources['resource:core.qi'] == qi-1
    assert not after.state.actors[OWNER].action_available
    assert any(e.event_type == 'OBJECT_UPDATED' and e.payload['object']['object_id'] == anchor.object_id for e in after.events)
